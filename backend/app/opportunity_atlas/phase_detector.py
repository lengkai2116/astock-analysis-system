"""
统一阶段判定引擎 — PhaseDetectionEngine

五源融合：价格位置 / 量能 / 资金流向 / 筹码分布 / 已有阶段检测器
数据不足时静默降级，不抛异常。
"""

import json
import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)

# ── 阶段常量 ──────────────────────────────────────────────
PHASE_BUILDING = "building"
PHASE_WASHING = "washing"
PHASE_LIFTING = "lifting"
PHASE_DISTRIBUTING = "distributing"
PHASE_UNKNOWN = "unknown"

ALL_PHASES = {PHASE_BUILDING, PHASE_WASHING, PHASE_LIFTING, PHASE_DISTRIBUTING}


class PhaseDetectionEngine(DataAwareMixin):
    """统一阶段判定引擎 — 五源融合投票"""

    def __init__(self, data_manager=None):
        self._dm = data_manager  # DataAwareMixin 统一注入点
        self._chip_estimator = None  # 延迟初始化
        self._chip_indicators = None
        self._trading_phase_detector = None
        self._stage_detector = None
        self._last_dim_insufficient = False     # 312号：数据不足标记（unknown 细分）

    # ── 主入口 ──────────────────────────────────────────────
    def compute_tags(self, ts_code: str, df: pd.DataFrame,
                     extra_tags: Optional[Dict] = None) -> Dict:
        """计算阶段标签（312号方案：8 维度加权共识，替代原五源等权投票）

        Args:
            ts_code: 股票代码
            df: 日线 OHLCV DataFrame（必须含 trade_date, open, high, low, close, vol）
            extra_tags: 可选下游标签 {buy_sell_point, sentiment_phase, sector_heat,
                        capital_nature}（由 data_daemon 在缠论/情绪/板块计算后传入）

        Returns:
            {main_force_phase, phase_confidence, price_position,
             trend_alignment, fund_flow, phase_conflict, phase_vote_ratio}
        """
        extra_tags = extra_tags or {}
        result = {
            "main_force_phase": PHASE_UNKNOWN,
            "phase_confidence": 0.0,
            "price_position": "mid_zone",
            "trend_alignment": "no_trend",
            "fund_flow": "none",
            "phase_conflict": False,
            "phase_vote_ratio": json.dumps({"unknown_kind": "unknown_insufficient"}, ensure_ascii=False),
        }

        if df is None or df.empty or len(df) < 30:
            return result

        try:
            df_sorted = df.sort_values("trade_date").reset_index(drop=True)
        except Exception:
            return result

        # 基础标签（保持输出契约）
        price_pos, ma_alignment = self._price_position_analysis(df_sorted)
        result["price_position"] = price_pos
        trend_dir = self._detect_trend_direction(df_sorted)
        result["trend_alignment"] = trend_dir
        fund_flow = self._analyze_fund_flow(ts_code)
        result["fund_flow"] = fund_flow

        # ── 8 维度阶段向量（批次1 可计算 7/8，控盘度批次3） ──
        self._last_dim_insufficient = len(df_sorted) < 60   # 数据不足（unknown 细分）
        dims = {
            "chip":  self._dim_chip(ts_code, df_sorted),   # 1 筹码形态（真实 TradingPhase 评分）
            "fund":  self._dim_fund(fund_flow, ts_code),   # 2 资金流向（方向+连续强度）
            "stage": self._dim_stage(df_sorted),           # 3 量价四阶段（CONSOLIDATION 验证）
            "asr":   self._dim_asr(ts_code, df_sorted),    # 4 ASR 筹码分布（去兜底）
            "trend": self._dim_trend(df_sorted),           # 5 趋势方向（斜率连续）
            "ssrp":  self._dim_ssrp(df_sorted, extra_tags),# 6 主力成本锚定（真实 SSRP，从pre_feat_cache读取）
            "chan":  self._dim_chan(extra_tags),           # 8 缠论买点（标签接入）
        }

        # 加权共识 + 修正/环境调整
        main_phase, confidence, conflict, vote_ratio = self._consensus(dims, extra_tags)

        # 涨停交叉校验（保持 298 号规则）
        main_phase = self._limit_up_cross_check(df_sorted, main_phase, price_pos)

        result["main_force_phase"] = main_phase
        result["phase_confidence"] = round(confidence, 4)
        result["phase_conflict"] = conflict
        result["phase_vote_ratio"] = json.dumps(vote_ratio, ensure_ascii=False)
        return result

    # ═══════════════════════════════════════════════════════════
    # 312号：8 维度阶段向量 + 加权共识
    # ═══════════════════════════════════════════════════════════
    # 维度权重（312号 §3.1）
    _DIM_WEIGHTS = {"chip": 3.0, "fund": 3.0, "stage": 2.5, "asr": 2.0,
                    "trend": 1.5, "ssrp": 2.5, "chan": 2.0}

    def _dim_chip(self, ts_code: str, df: pd.DataFrame) -> dict:
        """维度1 筹码形态：TradingPhaseDetector 五阶段评分 → 阶段分布向量

        判定条件收紧（2026-08-02 校准：原门槛 2.0 = 单条件(+2.0)即投票，
        导致"获利盘<40%"单条件大量投 building）：
          最低门槛 4.0 → 要求 ≥2 个独立条件确认才投票（298号 building 多条件 AND 语义）
        """
        info = self._run_trading_phase_detector_v2(ts_code, df)
        if info is None:
            return {}
        phase, scores = info
        total = sum(scores.values()) or 1.0
        best = max(scores.values())
        if best < 4.0:            # 要求 ≥2 个条件确认（单条件不投票，312 §3.2 维度1 校准）
            return {}
        mapping = {"BUILDING": "building", "WASHING": "washing", "RAISING": "lifting",
                   "SHIPPING": "distributing", "SUPPORT": "washing"}
        vec = {}
        for k, v in scores.items():
            p = mapping.get(k)
            if p and v > 0:
                vec[p] = round(v / total, 3)
        return vec

    def _dim_fund(self, fund_flow: str, ts_code: str) -> dict:
        """维度2 资金流向：方向 + 5日大单净额连续强度（mixed/none 不投票，去 washing 兜底）"""
        strength = 0.0
        try:
            mf_df = self._get_dm().get_cached_moneyflow(ts_code)
            if mf_df is not None and not mf_df.empty:
                mf5 = mf_df.tail(5)
                net = mf5["net_lg_amount"].sum()
                tot = mf5["buy_lg_amount"].sum() + mf5["sell_lg_amount"].sum()
                if tot > 0:
                    strength = min(1.0, abs(net) / tot)
        except Exception:
            pass
        if fund_flow == "5d_inflow":
            return {"lifting": round(0.3 + 0.5 * strength, 3), "building": 0.2}
        if fund_flow == "5d_outflow":
            return {"distributing": round(0.3 + 0.5 * strength, 3)}
        return {}   # mixed/none：方向不明不投票（312 §3.2 维度2）

    def _dim_stage(self, df: pd.DataFrame) -> dict:
        """维度3 量价四阶段：StageDetector + CONSOLIDATION 证据验证（312 §3.2 维度3）"""
        stage_info = self._run_stage_detector_v2(df)
        if stage_info is None:
            return {}
        stage_name, stage_conf = stage_info
        mapping = {"UPTREND_ACTIVE": ("lifting", 0.7), "UPTREND_TOPPING": ("distributing", 0.6),
                   "DOWNTREND_BOTTOMING": ("building", 0.6), "DOWNTREND_ACTIVE": ("washing", 0.4)}
        if stage_name == "CONSOLIDATION":
            # 证据验证：20 日振幅 < 15% 且 5 日均量 < 10 日均量（无证据 → 全 0，去兜底）
            try:
                closes = df["close"].values
                highs = df["high"].values
                lows = df["low"].values
                vols = df["vol"].values if "vol" in df.columns else np.ones(len(closes))
                if len(closes) < 20:
                    return {}
                amp20 = (max(highs[-20:]) - min(lows[-20:])) / closes[-1]
                vol_shrink = sum(vols[-5:]) < sum(vols[-10:-5]) if sum(vols[-10:-5]) > 0 else False
                if amp20 < 0.15 and vol_shrink:
                    return {"washing": 0.5, "building": 0.3}
                return {}
            except Exception:
                return {}
        if stage_name in mapping:
            p, base = mapping[stage_name]
            return {p: round(base * min(stage_conf + 0.2, 1.0), 3)}
        return {}

    def _dim_asr(self, ts_code: str, df: pd.DataFrame) -> dict:
        """维度4 ASR 筹码分布：298 号 4 条规则，else → 全 0（去 washing 兜底）
        2026-08-13 知识库对齐：ASR 0-100 量级（原 0-1，阈值×100）
        """
        chip = self._chip_distribution_analysis(ts_code, df)
        asr = chip.get("asr", 0.0)
        peak_price = chip.get("peak_position", 0.0)
        current = df["close"].values[-1]
        rel = current / peak_price if peak_price > 0 else 1.0
        if asr > 90 and rel < 0.95:
            return {"lifting": 0.5}
        if asr < 15 and abs(rel - 1.0) < 0.10:
            return {"building": 0.6}
        if asr < 15 and rel > 1.2:
            return {"lifting": 0.5}
        if asr > 30 and rel > 1.05:
            return {"distributing": 0.5}
        return {}   # 去 else→washing 兜底（312 §3.2 维度4）

    def _dim_trend(self, df: pd.DataFrame) -> dict:
        """维度5 趋势方向：三周期斜率连续强度"""
        closes = df["close"].values
        if len(closes) < 20:
            return {}
        def _slope(k):
            if len(closes) < k + 1 or closes[k] <= 0:
                return 0.0
            return closes[-1] / closes[-k - 1] - 1
        s5 = _slope(5)
        s20 = _slope(20)
        s60 = _slope(60) if len(closes) >= 60 else _slope(20)
        up = sum(1 for x in (s5, s20, s60) if x > 0.01)
        down = sum(1 for x in (s5, s20, s60) if x < -0.01)
        strength = min(1.0, abs(s5) * 15)
        if up >= 2:
            return {"lifting": round(0.3 + 0.4 * strength, 3)}
        if down >= 2:
            return {"distributing": round(0.3 + 0.4 * strength, 3)}
        return {}

    def _dim_ssrp(self, df: pd.DataFrame, extra_tags: Dict = None) -> dict:
        """维度6 主力成本锚定：现价 vs SSRP（真实主力成本，312 §3.2 维度6）

        367号：改为从 extra_tags（pre_feat_cache）读取 SSRP，不再依赖 _last_chip_indicators。

        规则（2026-08-02 抽样校准：原 rel<0.95→building 触发面过宽 77%，收紧）：
          rel < 0.85          → building（深度成本下方，安全边际大）
          0.85 <= rel < 1.10  → washing（成本区/浅套，蓄势待变）
          rel >= 1.20         → lifting（浮盈，拉升动力）
          1.10 <= rel < 1.20  → 无明确阶段（不投票）
        """
        extra_tags = extra_tags or {}
        ssrp = extra_tags.get("ssrp", 0) or 0
        try:
            ssrp = float(ssrp) if ssrp else 0
        except (TypeError, ValueError):
            ssrp = 0
        if not ssrp:
            return {}
        current = df["close"].values[-1]
        if current <= 0 or ssrp <= 0:
            return {}
        rel = current / ssrp
        dev = abs(rel - 1.0)
        if rel < 0.85:
            # 成本下方 ≠ 建仓（主力可能被套/阴跌），降级为弱支持（校准：原 0.5+ 过宽）
            return {"building": 0.3, "washing": 0.2}
        if rel < 1.10:
            return {"washing": 0.4, "building": 0.2}                        # 成本区/浅套
        if rel >= 1.20:
            return {"lifting": round(0.5 + 0.2 * min(1.0, dev), 3)}         # 浮盈
        return {}                                                           # 1.10-1.20 模糊带

    def _dim_chan(self, extra_tags: Dict) -> dict:
        """维度8 缠论买点：buy_sell_point 标签（312 §3.2 维度8）

        校准（2026-08-02）：单买点 ≠ 主力建仓，first_buy/third_buy 降为弱支持
        （原 building 0.5 过宽，低位一买大量出现）
        """
        bsp = extra_tags.get("buy_sell_point")
        if bsp in ("first_buy", "first_buy_p", "second_buy", "third_buy", "third_buy_a", "third_buy_b"):
            return {"building": 0.3, "lifting": 0.1}
        if bsp in ("first_sell", "first_sell_p", "second_sell", "third_sell"):
            return {"distributing": 0.6}
        return {}

    def _consensus(self, dims: Dict, extra_tags: Dict):
        """加权共识：阶段总分 → 主判定 + 连续置信度 + 分歧标记（312 §3.3/§四/§五）

        修正维度（条件性）：capital_nature 调置信度
        环境加权：情绪 climax 买入证据×0.7；热点板块 washing×0.7
        """
        phases = ["building", "washing", "lifting", "distributing"]
        total = {p: 0.0 for p in phases}
        w_sum = 0.0
        active = 0
        vote_ratio = {}
        sp = extra_tags.get("sentiment_phase")
        sh = extra_tags.get("sector_heat")
        env_buy = 0.7 if sp == "climax" else 1.0
        hot_wash = 0.7 if sh in ("top_10", "top_20") else 1.0
        for name, vec in dims.items():
            if not vec:
                continue
            active += 1
            w = self._DIM_WEIGHTS.get(name, 1.0)
            w_sum += w
            vote_ratio[name] = vec
            for p, v in vec.items():
                f = env_buy if p in ("building", "lifting") else 1.0
                if p == "washing":
                    f *= hot_wash
                total[p] += w * v * f

        insufficient = self._last_dim_insufficient
        if active == 0 or w_sum == 0:
            kind = "unknown_insufficient" if insufficient else "unknown_no_evidence"
            return PHASE_UNKNOWN, 0.0, False, {"unknown_kind": kind}

        order = sorted(phases, key=lambda p: -total[p])
        top, second = order[0], order[1]
        t_sum = sum(total.values()) or 1.0
        confidence = total[top] / t_sum
        # 2026-08-10 325档案修复：冲突阈值 0.15→0.08（实测 gap∈[0.08,0.15)
        # 为噪声伪冲突，原阈值致冲突率 55.5% 失真；0.08 后约 ~35% 保留真正分歧）
        conflict = (total[top] - total[second]) / t_sum < 0.08
        if conflict:
            confidence *= 0.6

        # 主判定确认门槛（2026-08-02 校准：判定条件不足 → 不判定）
        # 支持阶段 p 的维度数 = 向量中 p 强度 > 0.25 的维度（跨维度 AND 确认，298号 ≥3 源思想的加权版）
        def _supporters(p):
            return [name for name, vec in dims.items() if vec.get(p, 0) > 0.25]
        if len(_supporters(top)) < 2:
            sup_second = _supporters(second)
            if len(sup_second) >= 2 and total[second] > 0:
                # 降级到次高阶段（若次高有 ≥2 维度确认）
                top, second = second, top
                confidence = total[top] / t_sum
                conflict = (total[top] - total[second]) / t_sum < 0.15
                if conflict:
                    confidence *= 0.6
            else:
                # 两阶段均无 ≥2 维度确认 → 条件不足，不判定
                return PHASE_UNKNOWN, 0.0, False, {"unknown_kind": "unknown_no_evidence",
                                                   "reason": "support_insufficient"}

        # 修正维度：资金性质（条件性）
        cap_nature = extra_tags.get("capital_nature")
        if cap_nature == "institutional" and not conflict:
            confidence = min(1.0, confidence + 0.05)
        elif cap_nature == "hot_money":
            confidence *= 0.8
        vote_ratio["_conflict"] = bool(conflict)
        vote_ratio["_confidence"] = round(float(confidence), 4)
        vote_ratio["_supporters"] = {top: len(_supporters(top))}
        return top, confidence, conflict, vote_ratio

    def _run_trading_phase_detector_v2(self, ts_code: str, df: pd.DataFrame):
        """TradingPhaseDetector 阶段评分（返回 phase + scores，供维度1 阶段分布）"""
        if len(df) < 60:
            self._last_dim_insufficient = True
            return None
        try:
            from app.data.chip_indicators import ChipIndicators
            from app.engine.chip_strategy_impl import TradingPhaseDetector

            chip_inds = ChipIndicators()
            detector = TradingPhaseDetector(chip_inds)

            estimator = self._get_chip_estimator()
            chip_dist, min_p, max_p, step = estimator.estimate(df)
            chip_bins = []
            if step > 0:
                total = chip_dist.sum() or 1
                chip_bins = [
                    {"price_bin": round(min_p + i * step, 2),
                     "chip_ratio": float(chip_dist[i] / total)}
                    for i in range(len(chip_dist))
                ]

            indicators = chip_inds.calculate_all_indicators(
                chip_bins, df["close"].values[-1], kline_data=df
            )

            moneyflow_data = None
            try:
                moneyflow_data = self._get_dm().get_cached_moneyflow(ts_code)
            except Exception:
                pass

            phase_info = detector.detect_phase(
                df, chip_bins, indicators, moneyflow_data=moneyflow_data
            )
            scores = phase_info.get("scores") or {}
            return phase_info.get("phase", ""), scores
        except Exception:
            return None

    def _run_stage_detector_v2(self, df: pd.DataFrame):
        """StageDetector 阶段（返回 stage 名 + 置信度，供维度3）"""
        try:
            from app.engine.framework.volume_price_strategy import StageDetector
            detector = StageDetector()
            stage = detector.detect(df)
            return stage.name, float(stage.confidence or 0.0)
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════
    # Step 1: 价格位置判定
    # ═══════════════════════════════════════════════════════════
    def _price_position_analysis(self, df: pd.DataFrame) -> tuple:
        """120日价格分位 + 均线排列 → (price_position, ma_alignment)"""
        closes = df["close"].values
        if len(closes) < 20:
            return "mid_zone", "mixed"

        # 近120日价格分位
        lookback = min(120, len(closes))
        recent_low = np.min(df["low"].values[-lookback:])
        recent_high = np.max(df["high"].values[-lookback:])
        current = closes[-1]
        if recent_high - recent_low > 1e-9:
            pos_ratio = (current - recent_low) / (recent_high - recent_low)
        else:
            pos_ratio = 0.5

        if pos_ratio < 0.3:
            price_pos = "low_zone"
        elif pos_ratio > 0.7:
            price_pos = "high_zone"
        else:
            price_pos = "mid_zone"

        # 均线排列
        ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
        ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
        ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
        ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else closes[-1]

        if ma5 > ma10 > ma20 > ma60:
            ma_alignment = "bullish"
        elif ma5 < ma10 < ma20 < ma60:
            ma_alignment = "bearish"
        else:
            ma_alignment = "mixed"

        return price_pos, ma_alignment

    # ═══════════════════════════════════════════════════════════
    # Step 2: 量能模式
    # ═══════════════════════════════════════════════════════════
    def _volume_pattern_analysis(self, df: pd.DataFrame) -> Dict:
        """量能模式识别 → {vol_trend, vol_coordination, signal}"""
        vol = df["vol"].values if "vol" in df.columns else df.get("volume", pd.Series([0])).values
        vol = pd.Series(vol).astype(float)
        result = {"vol_trend": "stable", "vol_coordination": "neutral", "signal": "neutral"}

        if len(vol) < 20:
            return result

        ma5_vol = vol.rolling(5).mean().values
        ma20_vol = vol.rolling(20).mean().values

        latest_ma5 = ma5_vol[-1] if not np.isnan(ma5_vol[-1]) else 0
        latest_ma20 = ma20_vol[-1] if not np.isnan(ma20_vol[-1]) else 0

        # 量比趋势
        if latest_ma20 > 0:
            vol_ratio = latest_ma5 / latest_ma20
        else:
            vol_ratio = 1.0

        if vol_ratio > 1.3:
            result["vol_trend"] = "expanding"
        elif vol_ratio < 0.7:
            result["vol_trend"] = "shrinking"
        else:
            result["vol_trend"] = "stable"

        # 量价协调性：最近5日价格方向与量方向
        if len(df) >= 10:
            price_change = df["close"].values[-1] - df["close"].values[-5]
            vol_change = ma5_vol[-1] - ma5_vol[-5] if len(ma5_vol) >= 5 else 0
            if price_change > 0 and vol_change > 0:
                result["vol_coordination"] = "positive"  # 价涨量增 → 健康
                result["signal"] = "lifting"
            elif price_change > 0 and vol_change < 0:
                result["vol_coordination"] = "divergent_up"  # 价涨量缩 → 可疑
                result["signal"] = "distributing"
            elif price_change < 0 and vol_change > 0:
                result["vol_coordination"] = "divergent_down"  # 价跌量增 → 恐慌
                result["signal"] = "washing"
            else:
                result["vol_coordination"] = "neutral"
                result["signal"] = "building"

        return result

    # ═══════════════════════════════════════════════════════════
    # Step 3: 资金流向
    # ═══════════════════════════════════════════════════════════
    def _analyze_fund_flow(self, ts_code: str) -> str:
        """5日资金流向 → fund_flow 标签"""
        try:
            mf_df = self._get_dm().get_cached_moneyflow(ts_code)
            if mf_df is None or mf_df.empty:
                return "none"
            mf_5 = mf_df.tail(5)
            if mf_5.empty:
                return "none"

            net_sum = mf_5["net_lg_amount"].sum()
            pos_days = (mf_5["net_lg_amount"] > 0).sum()
            neg_days = (mf_5["net_lg_amount"] < 0).sum()

            if net_sum > 0 and pos_days >= 3:
                return "5d_inflow"
            elif net_sum < 0 and neg_days >= 3:
                return "5d_outflow"
            elif net_sum > 0:
                return "mixed"
            elif net_sum < 0:
                return "mixed"
            return "none"
        except Exception:
            return "none"

    def _fund_flow_to_phase(self, fund_flow: str) -> str:
        """资金流向 → 阶段映射"""
        mapping = {
            "5d_inflow": PHASE_LIFTING,
            "5d_outflow": PHASE_DISTRIBUTING,
            "mixed": PHASE_WASHING,
            "none": PHASE_UNKNOWN,
        }
        return mapping.get(fund_flow, PHASE_UNKNOWN)

    # ═══════════════════════════════════════════════════════════
    # Step 4: 筹码分布确认
    # ═══════════════════════════════════════════════════════════
    def _get_chip_estimator(self):
        if self._chip_estimator is None:
            from app.data.chip_distribution_service import ChipDistributionEstimator
            self._chip_estimator = ChipDistributionEstimator()
        return self._chip_estimator

    def _chip_distribution_analysis(self, ts_code: str, df: pd.DataFrame) -> Dict:
        """筹码分布分析 → {asr, peak_positions, signal}"""
        result = {"asr": 0.0, "peak_position": 0.0, "signal": "neutral"}

        estimator = self._get_chip_estimator()
        try:
            chip_dist, min_p, max_p, step = estimator.estimate(df)
            if step <= 0:
                return result
            current_price = df["close"].values[-1]

            # 计算 ASR (±5%)
            band_pct = 0.05
            price_low = current_price * (1 - band_pct)
            price_high = current_price * (1 + band_pct)

            total_chips = chip_dist.sum()
            if total_chips <= 0:
                return result

            asr = sum(
                chip_dist[i]
                for i in range(len(chip_dist))
                if price_low <= min_p + i * step <= price_high
            ) / total_chips
            # 2026-08-13 知识库对齐：ASR 0-100 量级（原 0-1）
            result["asr"] = round(asr * 100, 2)

            # 筹码主峰
            peak_idx = int(np.argmax(chip_dist))
            peak_price = min_p + peak_idx * step
            result["peak_position"] = peak_price

            # ASR 信号（298号§三Step4 ASR量化阈值规则，2026-08-13 阈值×100 对齐 0-100 量级）
            if asr > 90 and current_price < peak_price * 0.95:
                result["signal"] = PHASE_LIFTING  # ASR极高 + 价格低于峰值
            elif asr < 15 and abs(current_price - peak_price) / max(peak_price, 1) < 0.1:
                result["signal"] = PHASE_BUILDING  # ASR极低 + 近峰值（筹码锁定在建仓范围）
            elif asr < 15 and current_price > peak_price * 1.2:
                result["signal"] = PHASE_LIFTING  # ASR极低 + 有浮盈（拉升途中）
            elif asr > 30 and current_price > peak_price * 1.05:
                result["signal"] = PHASE_DISTRIBUTING  # ASR上升 + 高于峰值（筹码扩散）
            else:
                result["signal"] = PHASE_WASHING
        except Exception:
            pass

        return result

    def _asr_to_phase(self, chip_signal: Dict, df: pd.DataFrame) -> str:
        """ASR 信号 → 阶段"""
        return chip_signal.get("signal", PHASE_UNKNOWN)

    # ═══════════════════════════════════════════════════════════
    # 源1: TradingPhaseDetector
    # ═══════════════════════════════════════════════════════════
    def _run_trading_phase_detector(self, ts_code: str, df: pd.DataFrame) -> str:
        """调用 TradingPhaseDetector 获取操盘阶段"""
        if len(df) < 60:
            return PHASE_UNKNOWN
        try:
            from app.data.chip_indicators import ChipIndicators
            from app.engine.chip_strategy_impl import TradingPhaseDetector

            chip_inds = ChipIndicators()
            detector = TradingPhaseDetector(chip_inds)

            # 构造简化的 chip_bins
            self._chip_distribution_analysis(ts_code, df)
            estimator = self._get_chip_estimator()
            chip_dist, min_p, max_p, step = estimator.estimate(df)
            chip_bins = []
            if step > 0:
                total = chip_dist.sum() or 1
                chip_bins = [
                    {"price_bin": round(min_p + i * step, 2),
                     "chip_ratio": float(chip_dist[i] / total)}
                    for i in range(len(chip_dist))
                ]

            indicators = chip_inds.calculate_all_indicators(
                chip_bins, df["close"].values[-1], kline_data=df
            )

            moneyflow_data = None
            try:
                moneyflow_data = self._get_dm().get_cached_moneyflow(ts_code)
            except Exception:
                pass

            phase_info = detector.detect_phase(
                df, chip_bins, indicators, moneyflow_data=moneyflow_data
            )
            phase_raw = phase_info.get("phase", "")
            mapping = {
                "BUILDING": PHASE_BUILDING,
                "WASHING": PHASE_WASHING,
                "RAISING": PHASE_LIFTING,
                "SHIPPING": PHASE_DISTRIBUTING,
                "SUPPORT": PHASE_WASHING,
            }
            return mapping.get(phase_raw, PHASE_UNKNOWN)
        except Exception:
            return PHASE_UNKNOWN

    # ═══════════════════════════════════════════════════════════
    # 源2: StageDetector
    # ═══════════════════════════════════════════════════════════
    def _run_stage_detector(self, df: pd.DataFrame) -> str:
        """调用 StageDetector 获取四阶段"""
        try:
            from app.engine.framework.volume_price_strategy import StageDetector

            detector = StageDetector()
            stage = detector.detect(df)
            name = stage.name
            mapping = {
                "UPTREND_ACTIVE": PHASE_LIFTING,
                "UPTREND_TOPPING": PHASE_DISTRIBUTING,
                "DOWNTREND_BOTTOMING": PHASE_BUILDING,
                "DOWNTREND_ACTIVE": PHASE_BUILDING,
                "CONSOLIDATION": PHASE_WASHING,
            }
            return mapping.get(name, PHASE_UNKNOWN)
        except Exception:
            return PHASE_UNKNOWN

    # ═══════════════════════════════════════════════════════════
    # 趋势方向
    # ═══════════════════════════════════════════════════════════
    def _detect_trend_direction(self, df: pd.DataFrame) -> str:
        """趋势方向判定 (up_aligned / down_aligned / mixed / no_trend)"""
        closes = df["close"].values
        if len(closes) < 20:
            return "no_trend"

        # 三个周期方向一致性
        def _slope(arr):
            return (arr[-1] - arr[0]) / max(arr[0], 1)

        short_up = _slope(closes[-5:]) > 0.01 if len(closes) >= 5 else False
        mid_up = _slope(closes[-20:]) > 0.01 if len(closes) >= 20 else False
        long_up = _slope(closes[-60:]) > 0.01 if len(closes) >= 60 else False

        up_count = sum([short_up, mid_up, long_up])
        if up_count >= 2:
            return "up_aligned"
        elif up_count <= 0:
            return "down_aligned"
        return "mixed"

    # ═══════════════════════════════════════════════════════════
    # 源5: VolumePrice 量价趋势
    # ═══════════════════════════════════════════════════════════
    def _volume_signal_to_phase(self, volume_signal: Dict, trend_dir: str) -> str:
        """量价趋势信号 → 阶段"""
        signal = volume_signal.get("signal", "neutral")
        if signal == "lifting":
            return PHASE_LIFTING
        elif signal == "distributing":
            return PHASE_DISTRIBUTING
        elif signal == "washing":
            return PHASE_WASHING
        elif signal == "building":
            return PHASE_BUILDING
        # 从趋势方向降级
        if trend_dir == "up":
            return PHASE_LIFTING
        elif trend_dir == "down":
            return PHASE_DISTRIBUTING
        return PHASE_UNKNOWN

    # ═══════════════════════════════════════════════════════════
    # 投票决策
    # ═══════════════════════════════════════════════════════════
    def _vote_decision(self, votes: list, source_names: list) -> tuple:
        """
        五源投票 → (final_phase, confidence)

        - ≥3 一致 → 确认
        - 2 一致 → 可疑但采纳最高票
        - 全部不一致 / 无有效票 → unknown
        """
        if not votes:
            return PHASE_UNKNOWN, 0.0

        from collections import Counter
        counter = Counter(votes)
        top_phase, top_count = counter.most_common(1)[0]

        total_sources = len(votes)
        if top_count >= 3:
            # ≥3 源一致 → 确认
            confidence = top_count / max(total_sources, 1)
            return top_phase, min(confidence, 1.0)
        elif top_count == 2 and total_sources >= 4:
            # 4-5源中仅2一致 → 可疑
            confidence = 0.4
            return top_phase, confidence
        elif top_count == 2 and total_sources >= 2:
            confidence = 0.35
            return top_phase, confidence

        # 全部不一致 → unknown
        return PHASE_UNKNOWN, 0.0

    # ═══════════════════════════════════════════════════════════
    # 涨停交叉校验
    # ═══════════════════════════════════════════════════════════
    def _limit_up_cross_check(self, df: pd.DataFrame, current_phase: str,
                              price_position: str) -> str:
        """涨停时校验阶段合理性（298号§三Step5 四种规则）

        基于 price_position + 量价关系对五源投票的初判结果做二次校验。
        '次日低开'检查仅在盘后次日数据可用时生效（非当日第一笔）。
        """
        try:
            if len(df) < 2:
                return current_phase
            latest = df.iloc[-1]
            prev_close = df.iloc[-2]["close"]
            pct_chg = latest.get("pct_chg", None)
            if pct_chg is None:
                pct_chg = (latest["close"] - prev_close) / max(prev_close, 1) * 100

            if not (pct_chg > 9.5):
                return current_phase

            closes = df["close"].values
            volumes = df["vol"].values if "vol" in df.columns else None

            # 价格位置判定
            low_zone = price_position == "low_zone"
            high_zone = price_position == "high_zone"

            # 巨量：当日成交量 > 60日均量 × 2
            huge_vol = False
            shrink_vol = False
            if volumes is not None and len(volumes) >= 60:
                vol_60_avg = np.mean(volumes[-60:])
                today_vol = volumes[-1]
                huge_vol = today_vol > vol_60_avg * 2
                shrink_vol = today_vol < vol_60_avg * 0.6

            # 次日低开（仅在 df 含次日数据时可用）
            next_day_low_open = False
            if len(df) >= 3:
                # latest 是当天（涨停日），df.iloc[-3] 是前一日
                # 涨停日在 df.iloc[-2]，检查 df.iloc[-1] 是否为次日
                limit_up_idx = -2  # 假设涨停在倒数第二天
                # 检查倒数第二天是否涨停，最后一天是否为次日
                pc_2 = (df.iloc[-2]["close"] - df.iloc[-3]["close"]) / max(df.iloc[-3]["close"], 1) * 100
                if pc_2 > 9.5:
                    # 倒数第二天是涨停日
                    next_open = df.iloc[-1].get("open",
                                                df.iloc[-1]["close"])
                    limit_close = df.iloc[-2]["close"]
                    next_day_low_open = next_open < limit_close * 0.97

            # ── 规则1: building + 低位涨停 + not 巨量 → 确认 building
            if current_phase == PHASE_BUILDING and low_zone and not huge_vol:
                return PHASE_BUILDING

            # ── 规则2: building + 高位涨停 → 修正为 distributing
            if current_phase == PHASE_BUILDING and high_zone:
                return PHASE_DISTRIBUTING

            # ── 规则3: lifting + 高位涨停 + 巨量 + 次日低开 → 修正为 distributing
            if current_phase == PHASE_LIFTING and high_zone and huge_vol and next_day_low_open:
                return PHASE_DISTRIBUTING

            # ── 规则4: distributing + 低位涨停 + 缩量 → 修正为 building/washing
            if current_phase == PHASE_DISTRIBUTING and low_zone and shrink_vol:
                return PHASE_BUILDING

            return current_phase
        except Exception:
            return current_phase
