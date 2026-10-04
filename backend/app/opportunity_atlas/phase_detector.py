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

# ===== 508批次5：PhaseDetectionEngine 演进版迁入（dim4 内嵌为权威）=====
# 原外部 3 参旧版（daemon RAW 用）被演进版覆盖：8 参 data_context 全部默认 None，
# 3 参调用向后兼容；差异见 002-方案存档/508-dim4双副本收敛（物理合入清理）.md §〇·五。

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
                     extra_tags: Optional[Dict] = None,
                     chip_fund_ext: Optional[Dict] = None,
                     moneyflow_df=None,
                     indicator_ma_df=None,
                     indicator_other_df=None,
                     cost_ext: Optional[Dict] = None) -> Dict:
        """计算阶段标签（312号方案：8 维度加权共识，替代原五源等权投票）

        412号方案C1/C3 v3.0：全部数据由dim1通过data_context提供。
        443号R2：新增cost_ext（main_force_cost/margin_cost_price），透传_ssrp维度做洗盘增强。

        Args:
            ts_code: 股票代码
            df: 日线 OHLCV DataFrame
            extra_tags: 可选下游标签
            chip_fund_ext: 筹码预计算值，由data_context提供
            moneyflow_df: 资金流向数据，由data_context提供
            indicator_ma_df: 预计算MA数据，由data_context提供
            indicator_other_df: 预计算RSI/KDJ/BOLL数据，由data_context提供
            cost_ext: 成本价预计算值（main_force_cost/margin_cost_price），由data_context提供

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
        price_pos, ma_alignment = self._price_position_analysis(df_sorted, ts_code=ts_code, indicator_ma_df=indicator_ma_df)
        result["price_position"] = price_pos
        trend_dir = self._detect_trend_direction(df_sorted)
        result["trend_alignment"] = trend_dir
        fund_flow = self._analyze_fund_flow(ts_code, moneyflow_df)
        result["fund_flow"] = fund_flow

        # ── 8 维度阶段向量（批次1 可计算 7/8，控盘度批次3） ──
        self._last_dim_insufficient = len(df_sorted) < 60   # 数据不足（unknown 细分）
        dims = {
            "chip":  self._dim_chip(ts_code, df_sorted, chip_fund_ext=chip_fund_ext, moneyflow_df=moneyflow_df, indicator_other_df=indicator_other_df),   # 1 筹码形态
            "fund":  self._dim_fund(fund_flow, ts_code, extra_tags),   # 2 资金流向（方向+连续强度）
            "stage": self._dim_stage(df_sorted),           # 3 量价四阶段（CONSOLIDATION 验证）
            "asr":   self._dim_asr(ts_code, df_sorted),    # 4 ASR 筹码分布（去兜底）
            "trend": self._dim_trend(df_sorted),           # 5 趋势方向（斜率连续）
            "ssrp":  self._dim_ssrp(df_sorted, extra_tags, cost_ext=cost_ext),# 6 主力成本锚定（真实 SSRP，从pre_feat_cache读取）
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
    # 431号 G1 标注（批次13，2026-09-13）：本 8 维权重与
    # phase_detector.py 的同名 _DIM_WEIGHTS 逐字节重复，且**双方均 live**
    # （各由本模块内部共识消费）。收敛需先定权威源并改 import，属行为变更，
    # 本批**仅标注，不改值**。
    _DIM_WEIGHTS = {"chip": 3.0, "fund": 3.0, "stage": 2.5, "asr": 2.0,
                    "trend": 1.5, "ssrp": 2.5, "chan": 2.0}

    def _dim_chip(self, ts_code: str, df: pd.DataFrame,
                  chip_fund_ext: dict = None, moneyflow_df=None,
                  indicator_other_df=None) -> dict:
        """维度1 筹码形态：TradingPhaseDetector 五阶段评分 → 阶段分布向量

        412号方案C1 v3.0：chip_fund_ext和moneyflow_df由data_context提供。

        判定条件收紧（2026-08-02 校准）：
          最低门槛 4.0 → 要求 ≥2 个独立条件确认才投票
        """
        info = self._run_trading_phase_detector_v2(
            ts_code, df, chip_fund_ext=chip_fund_ext, moneyflow_df=moneyflow_df,
            indicator_other_df=indicator_other_df)
        if info is None:
            return {}
        phase, scores = info
        total = sum(scores.values()) or 1.0
        best = max(scores.values())
        if best < 4.0:
            return {}
        mapping = {"BUILDING": "building", "WASHING": "washing", "RAISING": "lifting",
                   "SHIPPING": "distributing", "SUPPORT": "washing"}
        vec = {}
        for k, v in scores.items():
            p = mapping.get(k)
            if p and v > 0:
                vec[p] = round(v / total, 3)
        return vec

    def _dim_fund(self, fund_flow: str, ts_code: str, extra_tags: dict = None) -> dict:
        """维度2 资金流向：方向 + 5日大单净额连续强度（mixed/none 不投票，去 washing 兜底）

        411号Phase 8：优先从extra_tags读取预计算5日资金聚合，回退raw计算。
        """
        strength = 0.0
        # 411号Phase 8：优先使用预计算数据
        extra_tags = extra_tags or {}
        net_lg_5d = extra_tags.get('net_lg_5d')
        if net_lg_5d is not None:
            try:
                net_lg_5d = float(net_lg_5d)
                # 464-15：net_lg_5d 单位为万元（moneyflow net_lg_amount 万元列聚合），
                # ÷1e4 归一化到亿；原 /1e8 按"元"算 → strength≈0（茅台 -16037万→0.0002）
                strength = min(1.0, abs(net_lg_5d) / 1e4)
            except (TypeError, ValueError):
                pass
        else:
            # ponytail: raw计算作为fallback
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
        """维度4 ASR 筹码分布：统一高 ASR=筹码集中蓄势语义（451 号）

        wiki《ASR指标》权威：ASR 高=筹码集中/突破前蓄势状态，价格脱离
        高浮筹区/ASR 高位滑落才是拉升信号；出货须「高位+放量+浮筹高企」
        组合，孤立高 ASR 不直接判出货。据此：
          - asr>90（高浮筹集中）=筹码集中蓄势 → building（不再直接 lifting）
          - 剔除孤立 'asr>30 高于峰值→distributing'（445「三处三义」相悖分支）
          - asr<15 近峰值=筹码锁定在建仓范围 → building
          - asr<15 大幅高于峰值=脱离密集区、筹码锁定充分 → lifting
        """
        chip = self._chip_distribution_analysis(ts_code, df)
        asr = chip.get("asr", 0.0)
        peak_price = chip.get("peak_position", 0.0)
        current = df["close"].values[-1]
        rel = current / peak_price if peak_price > 0 else 1.0
        # 高浮筹集中 = 筹码集中/突破前蓄势（不直接判拉升）
        if asr > 90:
            return {"building": 0.6}
        # 低浮筹 + 价格锁定在密集峰值附近：主力仍处建仓锁仓蓄势
        if asr < 15 and abs(rel - 1.0) < 0.10:
            return {"building": 0.6}
        # 低浮筹 + 大幅高于峰值：筹码锁定充分、脱离密集区 → 拉升
        if asr < 15 and rel > 1.2:
            return {"lifting": 0.5}
        return {}

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

    def _dim_ssrp(self, df: pd.DataFrame, extra_tags: Dict = None, cost_ext: Dict = None) -> dict:
        """维度6 主力成本锚定：现价 vs SSRP（真实主力成本，312 §3.2 维度6）

        367号：改为从 extra_tags（pre_feat_cache）读取 SSRP，不再依赖 _last_chip_indicators。
        443号R2：新增 cost_ext 主力成本近距增强（对齐 MainForceScorer.identify_phase 洗盘判定）。
        456号：新增 margin_cost_price（融资成本价）进阶段投票——wiki《融资成本价》：
          融资成本价 = 散户融资平均成本 = 解套压力位；现价在下方→反弹至该位受解套抛压（承压蓄势）；
          站上/突破→上方抛压释放、阻力锐减（做多）。作弱补充投票叠加，不覆盖主规则。

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
        # 443号R2：现价距主力成本 5% 内 → 洗盘特征增强（成本区蓄势待变）
        near_cost = False
        if cost_ext:
            mfc = self._cost_value(cost_ext.get("main_force_cost"))
            if mfc and mfc > 0:
                cost_distance = abs(current - mfc) / mfc
                near_cost = cost_distance < 0.05
        if near_cost:
            vec = {"washing": 0.5, "building": 0.2}
            return self._apply_margin_signal(vec, current, cost_ext) if cost_ext else vec
        rel = current / ssrp
        dev = abs(rel - 1.0)
        if rel < 0.85:
            # 成本下方 ≠ 建仓（主力可能被套/阴跌），降级为弱支持（校准：原 0.5+ 过宽）
            vec = {"building": 0.3, "washing": 0.2}
        elif rel < 1.10:
            vec = {"washing": 0.4, "building": 0.2}                         # 成本区/浅套
        elif rel >= 1.20:
            vec = {"lifting": round(0.5 + 0.2 * min(1.0, dev), 3)}          # 浮盈
        else:
            return {}                                                       # 1.10-1.20 模糊带
        return self._apply_margin_signal(vec, current, cost_ext) if cost_ext else vec

    def _cost_value(self, cost_raw) -> float:
        """456号：归一化 cost_ext 成本值。真实库 precompute_raw 存完整返回 dict
        （main_force_cost={'cost_price','distance_pct','near_cost'}，
          margin_cost_price={'cost_price','distance_pct'}），单测用标量。二者取数值。
        """
        if cost_raw is None:
            return 0.0
        if isinstance(cost_raw, dict):
            v = cost_raw.get("cost_price")
            return float(v) if v else 0.0
        try:
            return float(cost_raw)
        except (TypeError, ValueError):
            return 0.0

    def _apply_margin_signal(self, vec: dict, current: float, cost_ext: dict) -> dict:
        """456号：融资成本价（margin_cost_price）进阶段投票——弱补充信号

        wiki《融资成本价》：融资成本价 = 散户融资平均成本价 = 解套压力位。
          - 现价 ≥ 融资成本价×1.05（站上/突破）→ 上方抛压基本释放、阻力锐减 → lifting +
          - 现价 ≤ 融资成本价×0.85（融资盘深套）→ 安全边际大/远期机会 → building +
          - 中间区（成本位下方/附近承压）→ 反弹将遇散户解套抛压 → washing +
        融资方向（暴增+滞涨=危险）属余额方向信号，framework _score_retail_contrarian /
        _assess_margin 已消费，本方法只做成本锚定的压力位弱投票。
        """
        mcp = self._cost_value((cost_ext or {}).get("margin_cost_price"))
        if not mcp or mcp <= 0 or current <= 0:
            return vec
        vec = dict(vec)
        rel_m = current / mcp
        if rel_m >= 1.05:
            vec["lifting"] = vec.get("lifting", 0) + 0.2
        elif rel_m <= 0.85:
            vec["building"] = vec.get("building", 0) + 0.1
        else:
            vec["washing"] = vec.get("washing", 0) + 0.2
        return vec

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
        # 464-17：主力在场软修正（与 phase_detector.py 同步）——有在场证据提信、
        # 无在场证据（none）降信
        presence = extra_tags.get("main_force_presence")
        if presence in ("strong", "moderate"):
            confidence = min(1.0, confidence + 0.05)
        elif presence == "none":
            confidence *= 0.8
        vote_ratio["_conflict"] = bool(conflict)
        vote_ratio["_confidence"] = round(float(confidence), 4)
        vote_ratio["_supporters"] = {top: len(_supporters(top))}
        return top, confidence, conflict, vote_ratio

    def _run_trading_phase_detector_v2(self, ts_code: str, df: pd.DataFrame,
                                        chip_fund_ext: dict = None,
                                        moneyflow_df=None,
                                        indicator_other_df=None):
        """TradingPhaseDetector 阶段评分（返回 phase + scores，供维度1 阶段分布）

        412号方案C1 v3.0：chip_fund_ext由dim1通过data_context提供，
        moneyflow_df由dim1通过data_context提供。不再直接调用DataManager。
        """
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
                chip_bins, df["close"].values[-1], kline_data=df)
            # 412号C3 v3.0 RSI 预计算覆写（原 dim4 ChipIndicators 子类能力，508批次5 迁入；
            # 外部权威 ChipIndicators 无 indicator_other_df 参数，覆写在此内联）
            if indicator_other_df is not None and not indicator_other_df.empty \
                    and 'rsi14' in indicator_other_df.columns and len(df) >= 15:
                _rsi_series = indicator_other_df['rsi14'].dropna()
                if not _rsi_series.empty:
                    indicators['rsi'] = float(_rsi_series.iloc[-1])

            # 412号方案C1 v3.0：用data_context中的chip_fund_ext覆盖raw计算结果
            if chip_fund_ext:
                precomputed_map = {
                    'asr': 'asr',
                    'concentration': 'concentration',
                    'profit_ratio': 'profit_ratio',
                    'cyqkl': 'cyqkl',
                }
                for tag_key, ind_key in precomputed_map.items():
                    val = chip_fund_ext.get(tag_key)
                    if val is not None and ind_key in indicators:
                        indicators[ind_key] = val

            # moneyflow_data：优先从data_context，保留ecm fallback
            moneyflow_data = moneyflow_df  # 由调用方从data_context传入
            if moneyflow_data is None:
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
        """StageDetector 阶段（返回 stage 名 + 置信度，供维度3；508批次3 收敛外部完整版）"""
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
    def _price_position_analysis(self, df: pd.DataFrame, ts_code: str = None,
                                  indicator_ma_df=None) -> tuple:
        """120日价格分位 + 均线排列 → (price_position, ma_alignment)

        412号方案C3 v3.0：MA5/10/20/60优先从indicator_ma_df读取（dim1通过data_context提供），
        不再直接调用DataManager。
        """
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

        # 均线排列：从indicator_ma_df读取，保留raw fallback
        def _read_ma(period):
            if indicator_ma_df is not None and not indicator_ma_df.empty:
                col = f'ma{period}'
                if col in indicator_ma_df.columns:
                    val = indicator_ma_df[col].iloc[-1]
                    if val is not None:
                        return float(val)
            return None

        ma5 = _read_ma(5)
        if ma5 is None:
            ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
        ma10 = _read_ma(10)
        if ma10 is None:
            ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
        ma20 = _read_ma(20)
        if ma20 is None:
            ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
        ma60 = _read_ma(60)
        if ma60 is None:
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
    def _analyze_fund_flow(self, ts_code: str, moneyflow_df=None) -> str:
        """5日资金流向 → fund_flow 标签"""
        try:
            # 464-9：优先用 dim1 已注入的 moneyflow_df（与 443/dim2 同构接线），
            # 避免 ECM 直读 get_cached_moneyflow 在 daemon 写锁时失败导致整体降级。
            mf_df = moneyflow_df
            if mf_df is None or (hasattr(mf_df, 'empty') and mf_df.empty):
                mf_df = self._get_dm().get_cached_moneyflow(ts_code)
            if mf_df is None or (hasattr(mf_df, 'empty') and mf_df.empty):
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
            # 508批次3：外部权威 ChipDistributionEstimator（算法等价收敛）
            self._chip_estimator = ChipDistributionEstimator()
        return self._chip_estimator

    def _chip_distribution_analysis(self, ts_code: str, df: pd.DataFrame) -> Dict:
        """筹码分布分析 → {asr, peak_position}"""
        result = {"asr": 0.0, "peak_position": 0.0}

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

        except Exception:
            pass

        return result

    # ═══════════════════════════════════════════════════════════
    # 源2: StageDetector
    # ═══════════════════════════════════════════════════════════
    def _run_stage_detector(self, df: pd.DataFrame) -> str:
        """调用 StageDetector 获取四阶段"""
        try:
            from app.engine.framework.volume_price_strategy import StageDetector
            # 508批次3：外部权威 StageDetector（完整版四阶段）
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

        规则1/2/4：当日(T)涨停触发，用当日位置/量。
        规则3（464-12 改窗口）：前一日(T-1)高位涨停巨量 + 当日(T)低开≥3% → 当日初判
        lifting 修正为 distributing。忠实 298「放量涨停次日低开=诱多出货」在日终日频
        节奏下的近似——T 结论形成时 T+1 数据尚不存在，故"次日"取 T、涨停日取 T-1，
        **当日无需涨停**（单涨停+次日低开场景不再漏检；双涨停低开高走被本规则覆盖）。
        """
        try:
            if len(df) < 2:
                return current_phase
            latest = df.iloc[-1]
            prev_close = df.iloc[-2]["close"]
            pct_chg = latest.get("pct_chg", None)
            if pct_chg is None:
                pct_chg = (latest["close"] - prev_close) / max(prev_close, 1) * 100

            volumes = df["vol"].values if "vol" in df.columns else None

            # ── 规则3（464-12）：前一日(T-1)高位涨停巨量 + 当日(T)低开≥3% ──
            # 独立于当日涨停（T 无需涨停）；T 涨停时同样适用（双涨停+第二日低开被覆盖）。
            if current_phase == PHASE_LIFTING and len(df) >= 3 and volumes is not None and len(volumes) >= 61:
                pc_prev = (df.iloc[-2]["close"] - df.iloc[-3]["close"]) / max(df.iloc[-3]["close"], 1) * 100
                prev_limit_up = pc_prev > 9.5
                vol_60_avg_prev = np.mean(volumes[-61:-1])  # T-1 之前的 60 日均量
                prev_huge_vol = volumes[-2] > vol_60_avg_prev * 2
                low_open_today = float(latest.get("open", latest["close"])) < prev_close * 0.97
                # 高位以当日 price_position 近似前一日涨停日位置（两日间隔位置变化小）
                if prev_limit_up and prev_huge_vol and price_position == "high_zone" and low_open_today:
                    return PHASE_DISTRIBUTING

            # 以下规则1/2/4：当日(T)涨停才触发
            if not (pct_chg > 9.5):
                return current_phase

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

            # ── 规则1: building + 低位涨停 + not 巨量 → 确认 building
            if current_phase == PHASE_BUILDING and low_zone and not huge_vol:
                return PHASE_BUILDING

            # ── 规则2: building + 高位涨停 → 修正为 distributing
            if current_phase == PHASE_BUILDING and high_zone:
                return PHASE_DISTRIBUTING

            # ── 规则4: distributing + 低位涨停 + 缩量 → 修正为 building/washing
            if current_phase == PHASE_DISTRIBUTING and low_zone and shrink_vol:
                return PHASE_BUILDING

            return current_phase
        except Exception:
            return current_phase


# === chip_strategy_impl.py (508批次4 收敛：外部 app/engine/chip_strategy_impl.py 为权威) ===
# 差异审计：8 方法中 7 个逐行一致，仅 _score_building 集中度分支差异——dim4 内嵌
# concentration>0.3 系 451 号按简单法「高=集中」语义接入；508 批次2 切 P95-P5 后
# 数值语义反转（高=分散）→ 收敛外部 concentration_status 枚举（<0.2=集中）修复回归。
