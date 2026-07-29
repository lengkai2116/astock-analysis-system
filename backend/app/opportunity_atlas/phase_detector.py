"""
统一阶段判定引擎 — PhaseDetectionEngine

五源融合：价格位置 / 量能 / 资金流向 / 筹码分布 / 已有阶段检测器
数据不足时静默降级，不抛异常。
"""

import logging
from typing import Dict

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

    # ── 主入口 ──────────────────────────────────────────────
    def compute_tags(self, ts_code: str, df: pd.DataFrame) -> Dict:
        """
        计算阶段标签（五源融合投票）

        Args:
            ts_code: 股票代码
            df: 日线 OHLCV DataFrame（必须含 trade_date, open, high, low, close, vol）

        Returns:
            {main_force_phase, phase_confidence, price_position,
             trend_alignment, fund_flow}
        """
        result = {
            "main_force_phase": PHASE_UNKNOWN,
            "phase_confidence": 0.0,
            "price_position": "mid_zone",
            "trend_alignment": "no_trend",
            "fund_flow": "none",
        }

        if df is None or df.empty or len(df) < 30:
            return result

        try:
            df_sorted = df.sort_values("trade_date").reset_index(drop=True)
        except Exception:
            return result

        # Step 1: 价格位置 & 均线排列
        price_pos, ma_alignment = self._price_position_analysis(df_sorted)
        result["price_position"] = price_pos

        # Step 2: 趋势方向
        trend_dir = self._detect_trend_direction(df_sorted)
        result["trend_alignment"] = trend_dir

        # Step 3: 量能模式
        volume_signal = self._volume_pattern_analysis(df_sorted)

        # Step 4: 资金流向（异步加载）
        fund_flow = self._analyze_fund_flow(ts_code)
        result["fund_flow"] = fund_flow
        moneyflow_direction = self._fund_flow_to_phase(fund_flow)

        # Step 5: 筹码分布
        chip_signal = self._chip_distribution_analysis(ts_code, df_sorted)
        asr_phase = self._asr_to_phase(chip_signal, df_sorted)

        # Step 6: 加载既有阶段检测器结果
        trading_phase = self._run_trading_phase_detector(ts_code, df_sorted)
        stage_phase = self._run_stage_detector(df_sorted)

        # Step 7: 五源投票
        votes = []
        source_names = []

        # 源1: TradingPhaseDetector
        if trading_phase in ALL_PHASES:
            votes.append(trading_phase)
            source_names.append("trading_phase")
        # 源2: MainForceScorer 资金流向
        if moneyflow_direction in ALL_PHASES:
            votes.append(moneyflow_direction)
            source_names.append("moneyflow")
        # 源3: StageDetector
        if stage_phase in ALL_PHASES:
            votes.append(stage_phase)
            source_names.append("stage_detector")
        # 源4: ASR 筹码分布
        if asr_phase in ALL_PHASES:
            votes.append(asr_phase)
            source_names.append("asr")
        # 源5: VolumePrice 量价趋势信号
        vol_phase = self._volume_signal_to_phase(volume_signal, trend_dir)
        if vol_phase in ALL_PHASES:
            votes.append(vol_phase)
            source_names.append("volume_price")

        # 投票决策
        main_phase, confidence = self._vote_decision(votes, source_names)

        # 涨停交叉校验
        main_phase = self._limit_up_cross_check(df_sorted, main_phase, price_pos)

        result["main_force_phase"] = main_phase
        result["phase_confidence"] = round(confidence, 4)
        return result

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
            result["asr"] = round(asr, 4)

            # 筹码主峰
            peak_idx = int(np.argmax(chip_dist))
            peak_price = min_p + peak_idx * step
            result["peak_position"] = peak_price

            # ASR 信号（298号§三Step4 ASR量化阈值规则）
            if asr > 0.9 and current_price < peak_price * 0.95:
                result["signal"] = PHASE_LIFTING  # ASR极高 + 价格低于峰值
            elif asr < 0.15 and abs(current_price - peak_price) / max(peak_price, 1) < 0.1:
                result["signal"] = PHASE_BUILDING  # ASR极低 + 近峰值（筹码锁定在建仓范围）
            elif asr < 0.15 and current_price > peak_price * 1.2:
                result["signal"] = PHASE_LIFTING  # ASR极低 + 有浮盈（拉升途中）
            elif asr > 0.3 and current_price > peak_price * 1.05:
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
