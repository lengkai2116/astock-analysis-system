"""第4维 资金筹码引擎 — 独立完整文件

369号方案 P1 维度引擎整合：物理合并以下文件为独立完整文件：
  - phase_detector.py — PhaseDetectionEngine 7维度加权共识
  - chip_strategy_impl.py — TradingPhaseDetector 五阶段 + ChipDistributionSignalGenerator 6信号
  - chip_strategy.py — ChipScorer 6维评分
  - chip_position_manager.py — 筹码位置管理
  - chip_pre_filter.py — 筹码预筛选
  - chip_risk_executor.py — 筹码风险执行
  - crowding_factor.py — 拥挤度评估
  - tag_extractor.py — 筹码深度标签提取
  - fund_chip_builder 输出格式 + 条件稽核

统一接口：Dim4ChipFundEngine.evaluate() → {status_description, judgment, audit}
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date
import json
import logging
import math
from typing import Optional, List, Dict, Tuple, Any
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# === ChipDistributionEstimator (app/data/chip_distribution_service.py) ===
# 物理合入：避免外部依赖，符合369号方案"独立文件"要求

class ChipDistributionEstimator:
    """基于OHLCV的筹码估算器"""

    def __init__(self, num_bins=150, decay_rate=0.005):
        self.num_bins = num_bins
        self.decay_rate = decay_rate

    def adjust_decay_rate(self, turnover_rates):
        """根据换手率调整衰减率"""
        if turnover_rates is None or turnover_rates.empty:
            return
        avg_tr = turnover_rates.mean() / 100.0
        if avg_tr > 0:
            self.decay_rate = max(min(avg_tr * 0.3, 0.02), 0.003)

    def _allocate_volume_triangular(self, chip_dist, vol, price_low, price_high,
                                    price_close, min_price, price_step):
        """三角分布分配当日成交量"""
        import math as _math
        start_bin = max(0, int((price_low - min_price) / price_step))
        end_bin = min(self.num_bins - 1, _math.ceil((price_high - min_price) / price_step) - 1)
        if start_bin > end_bin:
            chip_dist[start_bin] += vol
            return
        n = end_bin - start_bin + 1
        if n <= 1:
            chip_dist[start_bin] += vol
            return
        peak_pos = (price_close - price_low) / (price_high - price_low)
        peak_pos = max(0.0, min(1.0, peak_pos))
        peak_idx = int(peak_pos * (n - 1))
        weights = np.zeros(n)
        for i in range(n):
            if i <= peak_idx:
                weights[i] = (i + 1) / (peak_idx + 1) if peak_idx >= 0 else 1.0
            else:
                weights[i] = (n - i) / (n - peak_idx) if peak_idx < n - 1 else 1.0
        total_w = weights.sum()
        if total_w > 0:
            weights /= total_w
            for i in range(n):
                chip_dist[start_bin + i] += weights[i] * vol

    def estimate(self, df_ohlcv, turnover_rates=None):
        """估算筹码分布"""
        if df_ohlcv is None or df_ohlcv.empty:
            return np.zeros(self.num_bins), 0, 0, 0
        if turnover_rates is not None and not turnover_rates.empty:
            self.adjust_decay_rate(turnover_rates)
        df_sorted = df_ohlcv.sort_values('trade_date').reset_index(drop=True)
        min_price = df_sorted['low'].min()
        max_price = df_sorted['high'].max()
        if max_price <= min_price:
            max_price = min_price * 1.1
            min_price = min_price * 0.9
        price_step = (max_price - min_price) / self.num_bins
        chip_dist = np.zeros(self.num_bins)
        for _, row in df_sorted.iterrows():
            vol = row.get('vol', 0)
            if vol <= 0:
                continue
            chip_dist *= (1 - self.decay_rate)
            price_high = row['high']
            price_low = row['low']
            if np.isnan(price_high) or np.isnan(price_low) or price_high <= price_low:
                continue
            close = row.get('close')
            if close is None or np.isnan(close):
                close = (price_high + price_low) / 2
            self._allocate_volume_triangular(chip_dist, vol, price_low, price_high, close, min_price, price_step)
        total = chip_dist.sum()
        if total > 0:
            chip_dist = chip_dist / total
        return chip_dist, min_price, max_price, price_step


# === ChipIndicators (app/data/chip_indicators.py) ===
# 物理合入：避免外部依赖

class ChipIndicators:
    """筹码因子计算器"""

    def calculate_all_indicators(self, chip_bins, current_price, kline_data=None, turnover_rate=None):
        """计算所有筹码因子"""
        if not chip_bins:
            return {}
        result = {}
        result['ssrp'] = self._calculate_ssrp(chip_bins)
        result['asr'] = self._calculate_asr(chip_bins, current_price)
        result['concentration'] = self._calculate_concentration(chip_bins)
        result['profit_ratio'] = self._calculate_profit_ratio(chip_bins, current_price)
        if kline_data is not None and not kline_data.empty:
            result['cyqkl'] = self._calculate_cyqkl(chip_bins, kline_data)
        if kline_data is not None and len(kline_data) >= 15:
            result['rsi'] = self._calculate_rsi(kline_data)
        return result

    def _calculate_ssrp(self, chip_bins):
        """计算SSRP - 市场平均成本"""
        total = sum(b['chip_ratio'] for b in chip_bins)
        if total <= 0:
            return 0
        weighted = sum(b['price_bin'] * b['chip_ratio'] for b in chip_bins)
        return round(weighted / total, 2)

    def _calculate_asr(self, chip_bins, current_price, band_pct=0.05):
        """计算ASR - 活跃浮筹比例"""
        price_low = current_price * (1 - band_pct)
        price_high = current_price * (1 + band_pct)
        ratio = sum(b['chip_ratio'] for b in chip_bins if price_low <= b['price_bin'] <= price_high)
        return round(ratio * 100, 2)

    def _calculate_concentration(self, chip_bins):
        """计算筹码集中度"""
        if not chip_bins:
            return 0
        sorted_bins = sorted(chip_bins, key=lambda x: x['price_bin'])
        total = sum(b['chip_ratio'] for b in sorted_bins)
        if total <= 0:
            return 0
        top_20 = sorted_bins[int(len(sorted_bins) * 0.8):]
        top_ratio = sum(b['chip_ratio'] for b in top_20)
        return round(top_ratio / total, 4) if total > 0 else 0

    def _calculate_profit_ratio(self, chip_bins, current_price):
        """计算筹码获利率"""
        return sum(b['chip_ratio'] for b in chip_bins if b['price_bin'] <= current_price)

    def _calculate_cyqkl(self, chip_bins, kline_data):
        """计算CYQKL - K线实体穿越筹码强度"""
        if kline_data is None or kline_data.empty:
            return 0
        latest = kline_data.iloc[-1]
        entity_min = min(latest['open'], latest['close'])
        entity_max = max(latest['open'], latest['close'])
        if entity_max <= entity_min:
            return 0
        sorted_bins = sorted(chip_bins, key=lambda x: x['price_bin'])
        if not sorted_bins:
            return 0
        step = sorted_bins[1]['price_bin'] - sorted_bins[0]['price_bin'] if len(sorted_bins) > 1 else 0.1
        crossed = 0.0
        for b in sorted_bins:
            bin_min = b['price_bin'] - step / 2
            bin_max = b['price_bin'] + step / 2
            overlap = min(entity_max, bin_max) - max(entity_min, bin_min)
            if overlap > 0:
                crossed += b['chip_ratio'] * (overlap / step)
        return round(crossed * 100, 2)

    def _calculate_rsi(self, kline_data, period=14):
        """计算RSI"""
        if len(kline_data) < period + 1:
            return 50
        closes = kline_data['close'].values
        deltas = np.diff(closes)
        if len(deltas) < period:
            return 50
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)


# === StageDetector (app/engine/framework/volume_price_strategy.py) ===
# 物理合入：避免外部依赖

@dataclass
class ValuationZones:
    """三周期价格分位"""
    short_30d: float = 0.5
    mid_60d: float = 0.5
    long_120d: float = 0.5
    ma120: Optional[float] = None
    ma250: Optional[float] = None
    zone: str = "MID"
    three_bloom: Dict = field(default_factory=dict)

    @property
    def composite(self) -> float:
        return self.short_30d * 0.5 + self.mid_60d * 0.3 + self.long_120d * 0.2


@dataclass
class Stage:
    """阶段状态"""
    name: str = "CONSOLIDATION"
    confidence: float = 0.0
    valuation: Optional[ValuationZones] = None
    trend_structure: str = ""
    ma_alignment: str = ""
    note: str = ""


class StageDetector:
    """波段四阶段判定"""

    def __init__(self, lookback: int = 120):
        self.lookback = lookback

    def detect(self, df: pd.DataFrame) -> Stage:
        if df is None or df.empty or len(df) < 30:
            return Stage(name="CONSOLIDATION", confidence=0.0, note="数据不足")
        closes = df['close'].astype(float).values
        highs = df['high'].astype(float).values
        lows = df['low'].astype(float).values
        ma60 = pd.Series(closes).rolling(60).mean().values
        ma60_dir = self._calc_direction(ma60)
        pos_60 = (closes[-1] - np.min(lows[-60:])) / (np.max(highs[-60:]) - np.min(lows[-60:]) + 1e-9)
        if ma60_dir == "up" and pos_60 > 0.6:
            return Stage(name="UPTREND_ACTIVE", confidence=0.7)
        if ma60_dir == "down" and pos_60 < 0.4:
            return Stage(name="DOWNTREND_ACTIVE", confidence=0.7)
        return Stage(name="CONSOLIDATION", confidence=0.5)

    def _calc_direction(self, ma: np.ndarray, lookback: int = 5) -> str:
        if len(ma) < lookback + 1:
            return "flat"
        recent = ma[-(lookback + 1):]
        if recent[-1] > recent[0] * 1.005:
            return "up"
        elif recent[-1] < recent[0] * 0.995:
            return "down"
        return "flat"


# === DataAwareMixin (app/data/mixins.py) ===

from app.data.mixins import DataAwareMixin



# === engine/framework/__init__.py 基类 ===

from abc import ABC, abstractmethod

class UniverseSelectionModel(ABC):
    @abstractmethod
    def select(self, date_time, data):
        pass

class AlphaModel(ABC):
    @abstractmethod
    def generate_insights(self, data):
        pass

class PortfolioConstructionModel(ABC):
    @abstractmethod
    def create_targets(self, insights, current_targets):
        pass

class RiskManagementModel(ABC):
    def on_data(self, insights, targets, current_holdings):
        pass

class ExecutionModel(ABC):
    @abstractmethod
    def execute(self, targets, current_holdings):
        pass

class Insight:
    def __init__(self, symbol='', direction=0, magnitude=0.0, confidence=0.0, period=None):
        self.symbol = symbol
        self.direction = direction
        self.magnitude = magnitude
        self.confidence = confidence
        self.period = period


# === 缺失的依赖补充 ===

# BenchmarkIndex 常量（简化版，避免依赖 benchmark_service）
class BenchmarkIndex:
    HS300 = '000300.SH'
    CSI500 = '000905.SH'

# DataManager 延迟导入（通过 DataAwareMixin._get_dm() 获取）

# OpportunityLibrary ORM 类（简化版）
class OpportunityLibrary:
    pass

# StrategyPipeline 常量
class StrategyPipeline:
    pass

# === phase_detector.py ===

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
            # 使用内部定义的 ChipIndicators（物理合入）
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
            # 使用内部定义的 StageDetector（物理合入）
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
            # 使用内部定义的 ChipDistributionEstimator（物理合入）
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
            # 使用内部定义的 ChipIndicators 和 TradingPhaseDetector（物理合入）
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
            # 使用内部定义的 StageDetector（物理合入）
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


# === chip_strategy_impl.py ===

class TradingPhaseDetector:
    """
    操盘阶段检测器
    识别：建仓期 / 洗盘期 / 拉升期 / 出货期 / 下跌期

    V2改进: 资金流向集成 — 各阶段评分加入 moneyflow 大单维度
    """

    def __init__(self, chip_indicators: ChipIndicators):
        self.chip_indicators = chip_indicators

    def detect_phase(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                    chip_bins_history: Optional[List[List[Dict]]] = None,
                    moneyflow_data: Optional[pd.DataFrame] = None) -> Dict:
        """
        检测当前操盘阶段

        Args:
            kline_data: K线数据
            chip_bins: 筹码分布数据
            indicators: 筹码指标
            chip_bins_history: 历史筹码分布（用于筹码转移方向检测）
            moneyflow_data: 资金流向数据（V2方向5新增）

        Returns:
            阶段信息字典
        """
        if len(kline_data) < 60:
            return {'phase': 'UNKNOWN', 'confidence': 0.0, 'reason': '数据不足'}

        # 计算筹码转移信息（如提供历史数据）
        transfer_info = None
        if chip_bins_history is not None:
            try:
                transfer_info = self.chip_indicators.detect_chip_transfer(chip_bins_history, lookback=20)
            except Exception:
                pass

        # 计算资金流向评分（V2方向5）
        moneyflow_score = self._calc_moneyflow_score(moneyflow_data)

        # 计算各阶段得分
        scores = {
            'BUILDING': self._score_building(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'WASHING': self._score_washing(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'RAISING': self._score_raising(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'SHIPPING': self._score_shipping(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'SUPPORT': self._score_support(kline_data, chip_bins, indicators, transfer_info, moneyflow_score)
        }

        best_phase = max(scores.items(), key=lambda x: x[1])
        total_score = sum(scores.values())

        confidence = best_phase[1] / max(total_score, 1)

        return {
            'phase': best_phase[0],
            'confidence': round(confidence, 4),
            'scores': scores,
            'moneyflow_score': moneyflow_score
        }

    def _calc_moneyflow_score(self, moneyflow_data: Optional[pd.DataFrame], period: int = 5) -> Dict:
        """
        计算资金流向评分 (V2方向5)

        Returns:
            {'avg_net_lg': float, 'positive_ratio': float,
             'is_positive_streak': bool, 'is_negative_streak': bool,
             'direction': int}  # 1=净流入, -1=净流出, 0=中性
        """
        default = {
            'avg_net_lg': 0, 'positive_ratio': 0.0,
            'is_positive_streak': False, 'is_negative_streak': False,
            'direction': 0, 'available': False
        }
        if moneyflow_data is None or moneyflow_data.empty:
            return default
        try:
            recent = moneyflow_data.tail(period)
            net_lg = recent['net_lg_amount'].values
            if len(net_lg) == 0:
                return default
            avg_net = float(np.mean(net_lg))
            positive_days = sum(1 for v in net_lg if v > 0)
            return {
                'avg_net_lg': avg_net,
                'positive_ratio': positive_days / len(net_lg),
                'is_positive_streak': bool(all(v > 0 for v in net_lg)),
                'is_negative_streak': bool(all(v < 0 for v in net_lg)),
                'direction': 1 if avg_net > 0 else (-1 if avg_net < 0 else 0),
                'available': True
            }
        except Exception:
            return default

    def _score_building(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                        transfer_info: Optional[Dict] = None,
                        moneyflow_score: Optional[Dict] = None) -> float:
        """建仓期评分"""
        score = 0.0

        if indicators.get('profit_ratio', 0) < 0.4:
            score += 2.0
        # 2026-08-13 知识库对齐：ASR 0-100 量级（原 0.7）
        if indicators.get('asr', 0) >= 70:
            score += 2.0
        conc_status = indicators.get('concentration_status', '')
        if conc_status == '高度集中' or conc_status == '较集中':
            score += 2.0
        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            min_60, max_60 = np.min(closes[-60:]), np.max(closes[-60:])
            if max_60 - min_60 > 0 and (closes[-1] - min_60) / (max_60 - min_60) < 0.4:
                score += 2.0

        # V2方向5: 大单净额持续为正但股价不涨 => 建仓吸筹
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_positive_streak']:
                closes = kline_data['close'].values
                price_up = (closes[-1] / closes[-min(5, len(closes))] - 1) < 0.03 if len(closes) >= 5 else False
                if price_up:
                    score += 2.0  # 持续净流入但股价不涨 -> 建仓痕迹
                else:
                    score += 1.5  # 持续净流入且慢涨 -> 建仓偏拉升

        return score

    def _score_washing(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """洗盘期评分"""
        score = 0.0

        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('缩量', '地量'):
            score += 2.0
        asr = indicators.get('asr', 0)
        # 2026-08-13 知识库对齐：ASR 0-100 量级（原 0.3-0.6）
        if 30 <= asr <= 60:
            score += 1.5
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if ssrp * 0.9 < cp < ssrp * 1.05:
                score += 1.5

        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            low_chg = transfer_info.get('low_chips_change', 0)
            if tr_type == '稳定' and low_chg >= -0.02:
                score += 2.0
            elif tr_type == '向下转移' and low_chg > 0:
                score += 2.0

        # V2方向5: 大单净额为负后转正企稳 => 洗盘尾声
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['direction'] == 1 and moneyflow_score['positive_ratio'] >= 0.6:
                score += 1.5  # 净流入转正 -> 洗盘结束征兆

        return score

    def _score_raising(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """拉升期评分"""
        score = 0.0

        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if cp > ssrp * 1.05:
                score += 2.0
        if indicators.get('profit_ratio', 0) >= 0.6:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('放量', '显著放量', '天量'):
            score += 2.0
        if indicators.get('cyqkl_status', '') in ('强', '很强', '极强'):
            score += 1.5

        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            if tr_type == '向上转移':
                score += 2.0
            elif tr_type == '稳定' and indicators.get('profit_ratio', 0) >= 0.5:
                score += 1.0

        # V2方向5: 大单净额持续为正且放大 => 拉升
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_positive_streak'] and abs(moneyflow_score['avg_net_lg']) > 0:
                score += 2.0

        return score

    def _score_shipping(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                        transfer_info: Optional[Dict] = None,
                        moneyflow_score: Optional[Dict] = None) -> float:
        """出货期评分"""
        score = 0.0

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7 and len(kline_data) >= 5:
            closes = kline_data['close'].values
            if closes[-1] < closes[-5]:
                score += 2.5
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('缩量', '地量'):
            score += 2.0
        rsi = indicators.get('rsi', 0)
        if rsi >= 70:
            score += 1.5

        # V2方向5: 大单净额为负且小单为正 => 出货
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_negative_streak']:
                score += 2.0

        return score

    def _score_support(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """下跌支撑期评分"""
        score = 0.0
        if indicators.get('profit_ratio', 0) < 0.35:
            score += 2.0
        if indicators.get('rsi', 50) < 30:
            score += 2.0
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if cp < ssrp * 0.9:
                score += 2.0
        return score


class ChipDistributionSignalGenerator:
    """
    筹码分布信号生成器
    生成 S_BUY / S_WASH_END / S_BOUNCE / S_SELL / S_WASH_STOP / S_DIVERG_SELL

    V1: 假突破过滤器前置 / S_DIVERG_SELL 改用 detect_rsi_divergence / 金字塔建仓
    V2: 主力测试识别 / 7种筹码形态匹配 / 洗盘结束增强
    """

    def __init__(self, phase_detector: TradingPhaseDetector):
        self.phase_detector = phase_detector
        self.chip_indicators = phase_detector.chip_indicators

    def generate_signals(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                         indicators: Dict, phase_info: Dict, moneyflow_data: Optional[pd.DataFrame] = None) -> Dict:
        """生成完整信号集合"""
        result = {}

        result['S_BUY'] = self._check_s_buy(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_END'] = self._check_s_wash_end(kline_data, chip_bins, indicators, phase_info)
        result['S_BOUNCE'] = self._check_s_bounce(kline_data, chip_bins, indicators, phase_info)
        result['S_SELL'] = self._check_s_sell(kline_data, chip_bins, indicators, phase_info)
        result['S_WASH_STOP'] = self._check_s_wash_stop(kline_data, chip_bins, indicators, phase_info)
        result['S_DIVERG_SELL'] = self._check_s_diverg_sell(kline_data, chip_bins, indicators, phase_info)

        # V2方向7: 主力测试行为检测 -> 增强S_BUY / S_WASH_END
        test_result = self._detect_mainforce_test(kline_data, chip_bins, indicators)
        result['mainforce_test'] = test_result
        if test_result.get('test_success'):
            # 测试成功 -> 强化买入信号
            if result['S_BUY'].get('triggered'):
                result['S_BUY']['position'] = max(result['S_BUY'].get('position', 0.7), 0.9)
                result['S_BUY']['mainforce_test_boost'] = '测试成功，确认突破'
            elif not result['S_BUY'].get('triggered') and test_result.get('confidence', 0) >= 0.6:
                # 测试成功但其他条件不足，仍可作为参与信号
                result['S_BUY']['triggered'] = True
                result['S_BUY']['position'] = 0.5
                result['S_BUY']['conditions'] = result['S_BUY'].get('conditions', []) + ['✓ 主力测试成功']
                result['S_BUY']['mainforce_test_boost'] = '测试成功'
        if test_result.get('test_failure'):
            # 测试失败 -> 强化洗盘结束（洗盘结束后测试突破）
            if result['S_WASH_END'].get('triggered'):
                result['S_WASH_END']['mainforce_test_boost'] = '测试失败后企稳'
                result['S_WASH_END']['position'] = min(result['S_WASH_END'].get('position', 0.5), 0.5)

        # V2方向8: 7种筹码形态匹配 -> 置信度调整
        chip_patterns = self._match_chip_pattern(chip_bins, kline_data, indicators)
        result['chip_patterns'] = chip_patterns
        for pat in chip_patterns:
            sig = pat.get('target_signal', '')
            boost = pat.get('confidence_boost', 0)
            if sig and boost > 0 and result.get(sig, {}).get('triggered'):
                cur_conf = result[sig].get('confidence', 0.5)
                result[sig]['confidence'] = min(1.0, cur_conf + boost)
                result[sig]['chip_pattern_boost'] = pat.get('pattern_name', '')
                # 仓位提升
                cur_pos = result[sig].get('position', 0.5)
                result[sig]['position'] = min(1.0, cur_pos + boost)

        # 确定最终操作建议
        recommendation = self._combine_signals(result, phase_info, indicators)
        result['recommendation'] = recommendation

        return result

    # ==============================
    # V1: 假突破前置 + S_DIVERG_SELL (已实现)
    # ==============================

    def _check_false_breakout(self, kline_data: pd.DataFrame, indicators: Dict) -> Dict:
        """假突破前置检测 — 三维确认"""
        if kline_data.empty or len(kline_data) < 5:
            return {'passed': True, 'reason': '数据不足', 'is_breakout': False}

        closes = kline_data['close'].values
        latest = float(closes[-1])

        if len(closes) >= 20:
            max_20 = float(np.max(closes[-20:]))
            min_20 = float(np.min(closes[-20:]))
            if max_20 - min_20 <= 0:
                return {'passed': True, 'reason': '价格无波动', 'is_breakout': False}

            is_breakout_high = latest >= max_20 * 0.98
            is_breakout_low = latest <= min_20 * 1.02

            if not is_breakout_high and not is_breakout_low:
                return {'passed': True, 'reason': '非突破状态', 'is_breakout': False}
        else:
            return {'passed': True, 'reason': '数据不足', 'is_breakout': False}

        breakout_level = max_20 * 0.98 if is_breakout_high else min_20 * 1.02

        breakout_days = 0
        for i in range(len(closes) - 1, -1, -1):
            if (is_breakout_high and closes[i] >= breakout_level) or \
               (is_breakout_low and closes[i] <= breakout_level):
                breakout_days += 1
            else:
                break

        vol_ratio = indicators.get('vol_ratio', 0)
        if vol_ratio < 1.5 and is_breakout_high:
            return {'passed': False, 'is_breakout': True,
                    'reason': f'量能不足(vol_ratio={vol_ratio:.2f}<1.5, 突破{breakout_days}日)'}

        if breakout_days < 3 and is_breakout_high:
            return {'passed': False, 'is_breakout': True,
                    'reason': f'突破时间不足({breakout_days}<3日)'}

        cyqkl = indicators.get('cyqkl', 0)
        if cyqkl < 0.2 and is_breakout_high:
            return {'passed': False, 'is_breakout': True,
                    'reason': f'穿透深度不足(cyqkl={cyqkl:.2f}<0.2)'}

        return {'passed': True, 'reason': '三维确认通过', 'is_breakout': True}

    def _check_s_diverg_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                              indicators: Dict, phase_info: Dict) -> Dict:
        """高位背离减仓信号 — 使用 detect_rsi_divergence()"""
        conditions = []
        triggered = False
        position_adjustment = 1.0

        if len(kline_data) < 40:
            return {'triggered': False, 'position_adjustment': 1.0, 'conditions': ['数据不足']}

        try:
            divergence = self.chip_indicators.detect_rsi_divergence(kline_data, period=14, lookback=20)
        except Exception:
            return {'triggered': False, 'position_adjustment': 1.0, 'conditions': ['背离检测异常']}

        top_div = divergence.get('top_divergence', {})

        if top_div.get('detected', False):
            count = top_div.get('count', 1)

            if count >= 3:
                triggered = True
                position_adjustment = 0.1
                conditions.append(
                    f'✓ 三重顶背离确认 → 减仓至10% '
                    f'(前次RSI{top_div["prev_high_rsi"]:.1f} > 最新RSI{top_div["latest_high_rsi"]:.1f})'
                )
            elif count == 2:
                triggered = True
                position_adjustment = 0.3
                conditions.append(
                    f'✓ 二次顶背离确认 → 减仓至30% '
                    f'(最新RSI{top_div["latest_high_rsi"]:.1f} < 前次RSI{top_div["prev_high_rsi"]:.1f})'
                )
            else:
                triggered = True
                position_adjustment = 0.7
                conditions.append(
                    f'▶ 初次顶背离 → 减仓至70% '
                    f'(价格{top_div["latest_high_price"]:.2f}新高, '
                    f'RSI{top_div["latest_high_rsi"]:.1f}低于前次{top_div["prev_high_rsi"]:.1f})'
                )

        return {
            'triggered': triggered,
            'position_adjustment': position_adjustment,
            'top_divergence_count': top_div.get('count', 0),
            'conditions': conditions
        }

    # ==============================
    # V2方向9: 洗盘结束增强 — 均线支撑 / 黄金坑 / 缩量企稳
    # ==============================

    def _check_s_wash_end(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                          indicators: Dict, phase_info: Dict) -> Dict:
        """
        洗盘结束买入信号 S_WASH_END
        条件（V1）:
          1. 操盘阶段=洗盘期
          2. 成交量降至地量
          3. RSI在30-55区间企稳
          4. 收盘价>=低位筹码峰下限（主力成本区）
          5. 当日涨幅>0%且成交量较前日放大>=20%
        条件（V2方向9新增）:
          6. 均线支撑(MA20/MA60)
          7. 黄金坑(V形反转+缩量底部)
          8. 放量下跌转缩量企稳
        """
        conditions = []
        all_met = True

        # 条件1：洗盘期
        if phase_info.get('phase') == 'WASHING':
            conditions.append('✓ 处于洗盘期')
        else:
            conditions.append('✗ 非洗盘期')
            all_met = False

        # 条件2：地量
        vol_status = indicators.get('vol_status', '')
        if vol_status == '地量':
            conditions.append('✓ 成交量地量')
        else:
            conditions.append('✗ 非地量')
            all_met = False

        # 条件3：RSI回调到位
        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            conditions.append('✓ RSI回调到位')
        else:
            conditions.append('✗ RSI未到位')
            all_met = False

        # 条件4：企稳
        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.3:
            conditions.append('✓ 获利率合理')
        else:
            conditions.append('✗ 获利率过低')
            all_met = False

        # === V2方向9新增条件 ===

        # 条件5：均线支撑 — 价格在MA20或MA60附近（±3%）
        ma20 = indicators.get('ma20')
        ma60 = indicators.get('ma60')
        if len(kline_data) > 0:
            cp = float(kline_data['close'].iloc[-1])
            if ma20 is not None and ma60 is not None and ma20 > 0 and ma60 > 0:
                near_ma20 = abs(cp - ma20) / ma20 <= 0.03
                near_ma60 = abs(cp - ma60) / ma60 <= 0.03
                if near_ma20 or near_ma60:
                    conditions.append(f'✓ 均线支撑(MA20={ma20:.2f}, MA60={ma60:.2f})')
                else:
                    conditions.append('✗ 未获均线支撑')
                    all_met = False
            else:
                # 自己算
                closes = kline_data['close'].values
                if len(closes) >= 20:
                    calc_ma20 = np.mean(closes[-20:])
                    near_ma20 = abs(cp - calc_ma20) / calc_ma20 <= 0.03
                    if near_ma20:
                        conditions.append(f'✓ 均线支撑(MA20={calc_ma20:.2f})')
                    else:
                        calc_ma60 = np.mean(closes[-min(60, len(closes)):]) if len(closes) >= 60 else 0
                        near_ma60 = calc_ma60 > 0 and abs(cp - calc_ma60) / calc_ma60 <= 0.03
                        if near_ma60:
                            conditions.append(f'✓ 均线支撑(MA60={calc_ma60:.2f})')
                        else:
                            conditions.append('✗ 未获均线支撑')
                            all_met = False

        # 条件6：黄金坑检测 — V形反转形态（先跌后涨，缩量底部）
        golden_pit = self._detect_golden_pit(kline_data)
        if golden_pit.get('detected'):
            conditions.append(f'✓ 黄金坑形态确认(跌幅{golden_pit["drop_pct"]:.1f}%, 反弹{golden_pit["rebound_pct"]:.1f}%)')
        else:
            conditions.append('✗ 无黄金坑形态')
            all_met = False

        # 条件7：放量下跌转缩量企稳
        volume_stabilize = self._detect_volume_stabilization(kline_data)
        if volume_stabilize.get('detected'):
            conditions.append('✓ 放量下跌转缩量企稳')
        else:
            conditions.append('✗ 量能未企稳')
            all_met = False

        # 金字塔仓位（V1方向4）
        ok_count = sum(1 for c in conditions if c.startswith('✓'))
        position = self._compute_pyramid_position(ok_count, 4, tier_map={3: 0.5, 5: 0.7, 7: 1.0})

        return {
            'triggered': all_met,
            'position': position,
            'conditions': conditions,
            'ok_count': ok_count
        }

    def _detect_golden_pit(self, kline_data: pd.DataFrame, lookback: int = 30) -> Dict:
        """
        黄金坑检测（V2方向9）

        特征:
          1. X日前出现阶段低点（挖坑）
          2. 从低点至坑底跌幅 >= 8%
          3. 坑底缩量（低于均量的50%）
          4. 从低点至今反弹 >= 5%（填坑）
          5. 当前价格仍在坑口下方（未填满坑）
        """
        if kline_data.empty or len(kline_data) < 10:
            return {'detected': False}
        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None or len(closes) < lookback:
            return {'detected': False}

        window = min(lookback, len(closes))
        recent = closes[-window:]
        vol_recent = volumes[-window:]

        # 找到窗口内的最低点
        min_idx = np.argmin(recent)
        min_price = recent[min_idx]

        # 坑口 = 最低点之前的高点
        pre_high = np.max(recent[:min_idx+1]) if min_idx >= 3 else recent[min_idx]

        drop_pct = (pre_high - min_price) / pre_high * 100
        if drop_pct < 8 or min_idx == len(recent) - 1:
            # 跌幅不足8%或最低点就是最后一天
            return {'detected': False, 'drop_pct': drop_pct}

        # 坑底成交量是否萎缩
        bottom_vol = vol_recent[min_idx]
        avg_vol = np.mean(vol_recent[:max(min_idx, 1)])
        vol_shrink = bottom_vol < avg_vol * 0.5 if avg_vol > 0 else False

        # 从低点至今的反弹幅度
        rebound_pct = (recent[-1] - min_price) / min_price * 100
        rebound_ok = rebound_pct >= 5

        # 是否仍在坑内（未回到坑口）
        still_in_pit = recent[-1] < pre_high * 0.98

        detected = drop_pct >= 8 and vol_shrink and rebound_ok and still_in_pit

        return {
            'detected': detected,
            'drop_pct': drop_pct,
            'rebound_pct': rebound_pct,
            'low_price': min_price,
            'pit_top': pre_high,
            'vol_shrink': vol_shrink
        }

    def _detect_volume_stabilization(self, kline_data: pd.DataFrame, lookback: int = 20) -> Dict:
        """
        放量下跌转缩量企稳检测（V2方向9）

        特征:
          1. 前期有一段放量下跌（跌幅>3%且量>均量*1.3）
          2. 近期转为缩量企稳（量<均量*0.8，价格波动<2%）
        """
        if kline_data.empty or len(kline_data) < 10:
            return {'detected': False}
        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None:
            return {'detected': False}

        window = min(lookback, len(closes))
        vol_window = volumes[-window:]
        close_window = closes[-window:]

        mid = window // 2
        left_vol = vol_window[:mid]
        right_vol = vol_window[mid:]
        left_close = close_window[:mid]
        right_close = close_window[mid:]

        if len(left_vol) < 3 or len(right_vol) < 3:
            return {'detected': False}

        # 前期：放量下跌
        left_drop = (left_close[0] - left_close[-1]) / left_close[0]
        avg_left_vol = np.mean(left_vol[:2]) if len(left_vol) >= 2 else left_vol[0]
        left_vol_ratio = np.mean(left_vol) / (avg_left_vol + 1e-9)

        # 近期：缩量企稳
        right_vol_ratio = np.mean(right_vol) / (np.mean(left_vol) + 1e-9)
        right_stable = (np.max(right_close) - np.min(right_close)) / np.mean(right_close)

        detected = left_drop > 0.03 and left_vol_ratio > 1.3 and right_vol_ratio < 0.8 and right_stable < 0.02

        return {
            'detected': detected,
            'left_drop': left_drop * 100,
            'left_vol_ratio': left_vol_ratio,
            'right_vol_ratio': right_vol_ratio,
            'right_stability': right_stable
        }

    # ==============================
    # V2方向7: 主力测试识别
    # ==============================

    def _detect_mainforce_test(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                                indicators: Dict, lookback: int = 30) -> Dict:
        """
        主力测试(试盘)行为检测

        特征（知识库依据）:
          - 主力突破前测试抛压，打到一个价位后不参与换手，观察盘面
          - 放量上攻 -> 缩量回落 -> 再次放量突破（测试成功）
          - 放量上攻 -> 缩量回落 -> 无法突破（测试失败）

        检测逻辑:
          1. 找到近N日最高价和最高量（测试动作）
          2. 测试后价格回落，成交量萎缩（观察盘面）
          3. 测试后如果放量突破测试高点 => 成功
          4. 测试后如果无法突破 => 失败
        """
        if kline_data.empty or len(kline_data) < 10:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        window = min(lookback, len(closes))
        close_w = closes[-window:]
        vol_w = volumes[-window:]

        # 找到测试动作（最高点 + 对应放量）
        test_idx = np.argmax(close_w)
        # 测试点必须是窗口的前半段（不能是最近几天），因为测试后需要观察期
        if test_idx >= len(close_w) - 5 or test_idx < 2:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        test_price = close_w[test_idx]
        test_vol = vol_w[test_idx]

        # 测试日必须放量
        avg_vol_before = np.mean(vol_w[:max(test_idx, 1)])
        if test_vol < avg_vol_before * 1.3:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        # 观察期：测试后至当前
        observe = close_w[test_idx + 1:]
        observe_vol = vol_w[test_idx + 1:]

        if len(observe) < 3:
            return {'detected': False, 'test_success': False, 'test_failure': False}

        # 测试后回落
        post_test_low = np.min(observe)
        pullback_pct = (test_price - post_test_low) / test_price
        pullback_ok = pullback_pct > 0.01  # 至少回落1%

        # 观察期缩量
        avg_vol_observe = np.mean(observe_vol)
        vol_shrink = avg_vol_observe < test_vol * 0.6

        if not pullback_ok or not vol_shrink:
            return {'detected': False, 'test_success': False, 'test_failure': False,
                    'reason': '未满足回落或缩量条件'}

        # 判断测试结果：当前价格是否突破测试高点
        current_price = close_w[-1]
        test_success = current_price >= test_price * 0.98
        test_failure = current_price <= post_test_low * 1.02 and \
                       close_w[-1] <= close_w[-min(3, len(close_w))] if len(close_w) >= 3 else False

        # 最近放量突破测试高点？
        recent_vol = vol_w[-min(3, len(vol_w)):]
        recent_close = close_w[-min(3, len(close_w)):]
        recent_breakout = recent_close[-1] >= test_price * 0.98 and \
                          np.mean(recent_vol) > avg_vol_observe * 1.2 if avg_vol_observe > 0 else False

        if recent_breakout:
            test_success = True
            test_failure = False

        confidence = pullback_pct  # 回落幅度作为置信度参考

        return {
            'detected': True,
            'test_success': test_success,
            'test_failure': test_failure,
            'confidence': min(confidence * 10, 0.9),
            'test_price': test_price,
            'current_price': current_price,
            'pullback_pct': pullback_pct * 100,
            'vol_shrink_ratio': avg_vol_observe / (test_vol + 1e-9)
        }

    # ==============================
    # V2方向8: 7种筹码形态匹配
    # ==============================

    def _match_chip_pattern(self, chip_bins: List[Dict], kline_data: pd.DataFrame,
                            indicators: Dict) -> List[Dict]:
        """
        7种经典筹码形态模式匹配

        参考:
          1. 放量突破单峰密集 -> 强化S_BUY
          2. 缩量回踩密集峰 -> 强化S_WASH_END
          3. 缩量振荡快移动 -> 建仓期早期信号
          4. 高点放量单峰 -> 强化S_SELL
          5. 密集峰快移 -> 趋势确认
          6. 回探滞涨 -> 减仓预警
          7. 缩量上穿密集峰 -> 买入信号
        """
        patterns = []

        if not chip_bins or len(chip_bins) < 10 or kline_data.empty or len(kline_data) < 5:
            return patterns

        try:
            peaks = self.chip_indicators.find_peak_positions(chip_bins)
            levels = self.chip_indicators.find_support_resistance_levels(chip_bins)
        except Exception:
            peaks = []
            levels = []

        closes = kline_data['close'].values
        volumes = kline_data['vol'].values if 'vol' in kline_data.columns else \
                  kline_data['amount'].values if 'amount' in kline_data.columns else None
        if volumes is None:
            return patterns

        current_price = float(closes[-1])
        vol_ratio = indicators.get('vol_ratio', 1.0)
        profit_ratio = indicators.get('profit_ratio', 0)
        cyqkl = indicators.get('cyqkl', 0)
        single_peak = len(peaks) <= 1

        # Pattern 1: 放量突破单峰密集
        if single_peak and vol_ratio >= 1.5 and profit_ratio >= 0.6:
            main_peak = peaks[0] if peaks else None
            if main_peak:
                peak_price = main_peak.get('price', 0)
                if peak_price > 0 and current_price >= peak_price * 0.98:
                    patterns.append({
                        'pattern_id': 1,
                        'pattern_name': '放量突破单峰',
                        'description': '放量突破筹码单峰密集区，拉升确认',
                        'target_signal': 'S_BUY',
                        'confidence_boost': 0.15,
                        'direction': 'bullish'
                    })

        # Pattern 2: 缩量回踩密集峰
        if vol_ratio < 1.2 and profit_ratio >= 0.3 and profit_ratio < 0.6:
            if peaks:
                # 价格回踩到主峰附近
                main_peak = peaks[0]
                peak_price = main_peak.get('price', 0)
                if peak_price > 0 and abs(current_price - peak_price) / peak_price <= 0.03:
                    patterns.append({
                        'pattern_id': 2,
                        'pattern_name': '缩量回踩密集',
                        'description': '缩量回踩筹码密集峰，洗盘结束信号',
                        'target_signal': 'S_WASH_END',
                        'confidence_boost': 0.15,
                        'direction': 'bullish'
                    })

        # Pattern 3: 缩量振荡快移动（筹码从分散到快速集中）
        if vol_ratio < 1.0 and cyqkl > 0.3:
            patterns.append({
                'pattern_id': 3,
                'pattern_name': '缩量振荡集中',
                'description': '缩量振荡中筹码快速集中',  # 修正：concentration -> 集中
                'target_signal': 'S_BUY',
                'confidence_boost': 0.10,
                'direction': 'bullish'
            })

        # Pattern 4: 高点放量单峰
        if single_peak and vol_ratio >= 1.5 and profit_ratio >= 0.7:
            patterns.append({
                'pattern_id': 4,
                'pattern_name': '高点放量单峰',
                'description': '高价位放量形成单峰密集，出货预警',
                'target_signal': 'S_SELL',
                'confidence_boost': 0.20,
                'direction': 'bearish'
            })

        # Pattern 5: 密集峰快移（筹码加速转移）
        try:
            transfer_rate = self.chip_indicators.calculate_transfer_rate([chip_bins], window=5)
        except Exception:
            transfer_rate = 0
        if transfer_rate > 0.15:
            direction = 'up' if profit_ratio >= 0.5 else 'down'
            if direction == 'up':
                patterns.append({
                    'pattern_id': 5,
                    'pattern_name': '密集峰快移向上',
                    'description': '筹码密集峰快速上移，拉升趋势确认',
                    'target_signal': 'S_BUY',
                    'confidence_boost': 0.15,
                    'direction': 'bullish'
                })
            else:
                patterns.append({
                    'pattern_id': 5,
                    'pattern_name': '密集峰快移向下',
                    'description': '筹码密集峰快速下移，下跌趋势确认',
                    'target_signal': 'S_SELL',
                    'confidence_boost': 0.15,
                    'direction': 'bearish'
                })

        # Pattern 6: 回探滞涨
        if len(closes) >= 10:
            recent_range = (np.max(closes[-10:]) - np.min(closes[-10:])) / np.mean(closes[-10:])
            if recent_range < 0.05 and profit_ratio >= 0.6:
                # 高位横盘，获利盘多 — 滞涨预警
                patterns.append({
                    'pattern_id': 6,
                    'pattern_name': '回探滞涨',
                    'description': '高位横盘滞涨，警惕出货',
                    'target_signal': 'S_DIVERG_SELL',
                    'confidence_boost': 0.10,
                    'direction': 'bearish'
                })

        # Pattern 7: 缩量上穿密集峰
        if vol_ratio < 1.3 and profit_ratio >= 0.4 and profit_ratio < 0.7:
            if peaks:
                main_peak = peaks[0]
                peak_price = main_peak.get('price', 0)
                if peak_price > 0 and current_price > peak_price * 1.01 and current_price < peak_price * 1.08:
                    patterns.append({
                        'pattern_id': 7,
                        'pattern_name': '缩量上穿密集',
                        'description': '缩量温和上穿筹码密集峰，主力控盘',
                        'target_signal': 'S_BUY',
                        'confidence_boost': 0.20,
                        'direction': 'bullish'
                    })

        return patterns

    # ==============================
    # V1方向4: 金字塔建仓（改写为分档逻辑）
    # ==============================

    def _compute_pyramid_position(self, ok_count: int, total_conditions: int,
                                   tier_map: Dict[int, float] = None) -> float:
        """
        金字塔仓位计算

        Args:
            ok_count: 满足的条件数
            total_conditions: 总条件数
            tier_map: {min_ok: position} 映射，按ok_count升序

        默认:
          <50%满足 -> 0.3（初始试探）
          50-70%   -> 0.5（基础仓位）
          70-90%   -> 0.7（加仓）
          >=90%    -> 1.0（满仓）
        """
        if tier_map is None:
            tier_map = {}

        # 默认3档金字塔
        ratios = [t for t in sorted(tier_map.keys())]
        if not ratios:
            # 默认: <50% = 0.3, 50-70% = 0.5, 70-90% = 0.8, >=90% = 1.0
            ratio = ok_count / max(total_conditions, 1)
            if ratio >= 0.9:
                return 1.0
            elif ratio >= 0.7:
                return 0.8
            elif ratio >= 0.5:
                return 0.5
            else:
                return 0.3

        ok_ratio = ok_count / max(total_conditions, 1)
        for min_ok in sorted(tier_map.keys()):
            if ok_count >= min_ok:
                return tier_map[min_ok]
        return 0.3

    def _combine_signals(self, signals: Dict, phase_info: Optional[Dict] = None,
                         indicators: Optional[Dict] = None) -> Dict:
        """
        综合各信号 -> 金字塔建仓推荐

        V1方向4: 金字塔仓位 — 根据信号满足条件数分档
        """
        # 止损/卖出 > 买入
        if signals.get('S_WASH_STOP', {}).get('triggered', False):
            return {
                'action': 'SELL', 'reason': '洗盘止损',
                'target_position': 0.0, 'priority': 1
            }

        if signals.get('S_SELL', {}).get('triggered', False):
            return {
                'action': 'SELL', 'reason': '主卖出信号',
                'target_position': 0.0, 'priority': 2
            }

        if signals.get('S_DIVERG_SELL', {}).get('triggered', False):
            sd = signals['S_DIVERG_SELL']
            adj = sd.get('position_adjustment', 1.0)
            return {
                'action': 'REDUCE', 'reason': '高位背离减仓',
                'target_position': adj, 'position_adjustment': adj, 'priority': 3
            }

        # 买入信号 -> 金字塔仓位
        if signals.get('S_BUY', {}).get('triggered', False):
            detail = signals['S_BUY']
            conditions = detail.get('conditions', [])
            ok_count = sum(1 for c in conditions if c.startswith('✓'))
            # 含K线形态增强
            total = max(len(conditions), 1)
            boost = 1 if signals.get('chip_patterns') else 0
            ok_count += boost
            position = self._compute_pyramid_position(ok_count, total + boost)
            conf = ok_count / max(total, 1)
            return {
                'action': 'BUY', 'reason': '主买入信号',
                'target_position': round(position, 2),
                'confidence': round(min(conf + 0.1, 1.0), 3),
                'priority': 4
            }

        if signals.get('S_WASH_END', {}).get('triggered', False):
            detail = signals['S_WASH_END']
            conditions = detail.get('conditions', [])
            ok_count = sum(1 for c in conditions if c.startswith('✓'))
            total = max(len(conditions), 1)
            boost = 1 if signals.get('chip_patterns') else 0
            ok_count += boost
            position = self._compute_pyramid_position(ok_count, total + boost,
                                                       tier_map={3: 0.3, 5: 0.5, 7: 0.8})
            conf = ok_count / max(total, 1)
            return {
                'action': 'BUY', 'reason': '洗盘结束',
                'target_position': round(position, 2),
                'confidence': round(min(conf + 0.1, 1.0), 3),
                'priority': 5
            }

        if signals.get('S_BOUNCE', {}).get('triggered', False):
            return {
                'action': 'BUY', 'reason': '超跌反弹',
                'target_position': 0.3, 'priority': 6
            }

        return {
            'action': 'HOLD', 'reason': '无明确信号',
            'target_position': None, 'priority': 99
        }

    # ==============================
    # 以下为 V1 已有信号 (保留原实现)
    # ==============================

    def _check_s_buy(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                     indicators: Dict, phase_info: Dict) -> Dict:
        """主买入信号 S_BUY"""
        conditions = []
        all_met = True

        # 假突破前置过滤
        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0,
                    'conditions': ['假突破过滤: ' + false_break['reason']]}

        if phase_info.get('phase') == 'RAISING':
            conditions.append('✓ 处于拉升期')
        else:
            conditions.append('✗ 非拉升期')
            all_met = False

        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            max_60 = np.max(closes[-60:])
            if closes[-1] > max_60 * 0.98:
                conditions.append('✓ 价格高位')
            else:
                conditions.append('✗ 未突破')
                all_met = False

        if indicators.get('vol_ratio', 0) >= 1.5:
            conditions.append('✓ 成交量放大')
        else:
            conditions.append('✗ 成交量不足')
            all_met = False

        if indicators.get('cyqkl', 0) >= 0.2:
            conditions.append('✓ CYQKL达标')
        else:
            conditions.append('✗ CYQKL不足')
            all_met = False

        ssrp = indicators.get('ssrp', 0)
        current_price = float(kline_data['close'].iloc[-1]) if len(kline_data) > 0 and ssrp > 0 else 0
        if current_price > 0 and ssrp > 0 and current_price > ssrp:
            conditions.append(f'✓ SSRP穿越确认: {current_price:.2f} > SSRP {ssrp:.2f}')
        else:
            conditions.append('✗ SSRP未突破')
            all_met = False

        if indicators.get('profit_ratio', 0) >= 0.6:
            conditions.append('✓ 获利率达标')
        else:
            conditions.append('✗ 获利率不足')
            all_met = False

        ok_count = sum(1 for c in conditions if c.startswith('✓'))
        position = self._compute_pyramid_position(ok_count, len(conditions))

        return {
            'triggered': all_met,
            'position': position,
            'conditions': conditions,
            'ok_count': ok_count
        }

    def _check_s_bounce(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                        indicators: Dict, phase_info: Dict) -> Dict:
        """超跌反弹买入信号 S_BOUNCE"""
        conditions = []
        all_met = True

        if phase_info.get('phase') == 'SUPPORT':
            conditions.append('✓ 处于支撑期')
        else:
            conditions.append('✗ 非支撑期')
            all_met = False

        rsi = indicators.get('rsi', 50)
        if rsi < 30:
            conditions.append('✓ RSI超卖')
        else:
            conditions.append('✗ RSI未超卖')
            all_met = False

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio < 0.2:
            conditions.append('✓ 低获利率')
        else:
            conditions.append('✗ 获利率过高')
            all_met = False

        return {
            'triggered': all_met,
            'position': 0.3,
            'conditions': conditions
        }

    def _check_s_sell(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                      indicators: Dict, phase_info: Dict) -> Dict:
        """主卖出信号 S_SELL"""
        conditions = []
        triggered = False

        false_break = self._check_false_breakout(kline_data, indicators)
        if false_break['is_breakout'] and not false_break['passed']:
            return {'triggered': False, 'position': 0.0,
                    'conditions': ['假突破过滤: ' + false_break['reason']]}

        if phase_info.get('phase') == 'SHIPPING':
            conditions.append('✓ 出货期确认')
            triggered = True

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7 and len(kline_data) >= 5:
            closes = kline_data['close'].values
            if closes[-1] < closes[-5] * 0.95:
                conditions.append('✓ 高位回落')
                triggered = True

        rsi = indicators.get('rsi', 50)
        if rsi >= 80:
            conditions.append('✓ RSI超买')
            triggered = True

        ssrp = indicators.get('ssrp', 0)
        # 2026-08-16 修复（345号 bearish 方向反转 / T23 实证）：SSRP 条件仅
        # SHIPPING（出货期）触发——建仓/洗盘期（BUILDING/WASHING）股价跌破
        # 筹码成本是超跌机会（主力吸筹区）而非出货，原实现无条件触发致弱市
        # 暴跌末端误判卖出（92 条重放 64% 触发，看空后 T+5 +3.26% 假阴性）。
        if ssrp > 0 and len(kline_data) >= 3 and phase_info.get('phase') == 'SHIPPING':
            closes = kline_data['close'].values
            if len(closes) >= 2 and closes[-1] < ssrp and closes[-2] < ssrp:
                conditions.append(f'✓ 连续2日低于SSRP({ssrp:.2f})')
                triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,
            'conditions': conditions
        }

    def _check_s_wash_stop(self, kline_data: pd.DataFrame, chip_bins: List[Dict],
                           indicators: Dict, phase_info: Dict) -> Dict:
        """洗盘止损信号 S_WASH_STOP"""
        conditions = []
        triggered = False

        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            current_price = kline_data['close'].iloc[-1]
            if current_price < ssrp * 0.9:
                conditions.append('✓ 跌破主力成本')
                triggered = True

        return {
            'triggered': triggered,
            'position': 0.0,
            'conditions': conditions
        }


# === chip_strategy.py ===

class ChipUniverseSelectionModel(UniverseSelectionModel):
    """
    筹码分布股票池选择模型
    筛选出具备主力资金条件的股票
    """
    
    def __init__(self, lookback_period: int = 120, top_n: int = 50):
        """
        Args:
            lookback_period: 回看周期
            top_n: 返回前N只股票
        """
        self.lookback_period = lookback_period
        self.top_n = top_n
        self.chip_scorer = ChipScorer()
    
    def select(self, date_time: datetime, data: Any) -> List[str]:
        """
        筛选股票池
        
        Args:
            date_time: 时间戳
            data: 市场数据，格式为 {symbol: DataFrame}
        
        Returns:
            股票代码列表，按分数降序排列
        """
        if not isinstance(data, dict):
            return []
        
        results = []
        for symbol, df in data.items():
            try:
                if len(df) < 60:
                    continue
                
                # 计算筹码评分
                score = self.chip_scorer.score(df)
                if score > 0:
                    results.append((symbol, score))
            
            except Exception as e:
                logger.error(f"筛选股票 {symbol} 时出错: {e}")
        
        # 按分数排序，返回前N只
        results.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in results[:self.top_n]]


class ChipAlphaModel(AlphaModel):
    """
    筹码分布信号生成模型
    生成交易信号洞察
    """
    
    def __init__(self, lookback_period: int = 120):
        self.lookback_period = lookback_period
        # 简化实现，移除外部依赖
        self.chip_service = None
        self.chip_indicators = None
    
    def generate_insights(self, data: any) -> List[Insight]:
        """
        生成筹码分布交易信号洞察
        
        Args:
            data: 可以是DataFrame或字典格式的OHLCV数据
        
        Returns:
            洞察信号列表
        """
        insights = []
        
        # 处理不同类型的数据输入
        data_dict = data if isinstance(data, dict) else {'data': data}
        
        for symbol, df in data_dict.items():
            try:
                if isinstance(df, pd.DataFrame):
                    if df.empty or len(df) < 120:
                        continue
                    
                    # 使用评分器分析
                    scorer = ChipScorer()
                    score = scorer.score(df)
                    
                    # 根据评分生成信号
                    if score >= 7.0:
                        # 高分 - 强力买入
                        direction = Insight.LONG
                        confidence = min(0.9, score / 10.0)
                        weight = 0.8
                        reason = f"高评分筹码策略信号: {symbol} (评分: {score:.2f})"
                    elif score >= 5.0:
                        # 中分 - 买入
                        direction = Insight.LONG
                        confidence = min(0.7, score / 10.0)
                        weight = 0.5
                        reason = f"中等评分筹码策略信号: {symbol} (评分: {score:.2f})"
                    elif score >= 3.0:
                        # 低分 - 观望
                        direction = Insight.FLAT
                        confidence = 0.5
                        weight = 0.0
                        reason = f"观望信号: {symbol} (评分: {score:.2f})"
                    else:
                        # 极低分 - 做空
                        direction = Insight.SHORT
                        confidence = min(0.6, (10.0 - score) / 10.0)
                        weight = 0.3
                        reason = f"卖出信号: {symbol} (评分: {score:.2f})"
                    
                    insights.append(
                        Insight(
                            symbol=symbol,
                            direction=direction,
                            confidence=confidence,
                            weight=weight,
                            reason=reason
                        )
                    )
            except Exception as e:
                logger.error(f"处理 {symbol} 时失败: {e}")
        
        return insights


class ChipRiskManagementModel(RiskManagementModel):
    """
    筹码分布风险管理模型
    提供止损止盈和风险控制逻辑
    """
    
    def __init__(self, 
                 stop_loss_pct: float = 0.08,  # 止损8%
                 take_profit_pct: float = 0.15,  # 止盈15%
                 max_single_position_pct: float = 0.2,  # 单只股票最大20%仓位
                 max_total_exposure: float = 0.8):  # 总仓位不超过80%
        """
        Args:
            stop_loss_pct: 止损百分比
            take_profit_pct: 止盈百分比
            max_single_position_pct: 单只股票最大仓位比例
            max_total_exposure: 总暴露风险上限
        """
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_single_position_pct = max_single_position_pct
        self.max_total_exposure = max_total_exposure
        self.entry_prices: Dict[str, float] = {}  # 记录入场价格
    
    def on_data(self, insights: List[Insight], targets: Dict[str, float], 
                current_portfolio: Dict[str, float]) -> Dict[str, float]:
        """
        应用风险管理规则
        
        Args:
            insights: 洞察信号列表
            targets: 目标仓位
            current_portfolio: 当前持仓 {symbol: position_pct}
        
        Returns:
            调整后的目标仓位
        """
        adjusted_targets = targets.copy()
        
        # 1. 检查止损止盈
        for symbol, entry_price in self.entry_prices.items():
            if symbol not in current_portfolio:
                continue
            
            # 这里简化实现，实际需要获取当前价格
            # 假设通过某种方式获取当前价格，这里简化逻辑
            position = current_portfolio.get(symbol, 0)
            
            if position != 0:
                # 有持仓的情况下，检查是否需要止损或止盈
                # 这里需要真实的价格数据，暂时简化逻辑
                pass
        
        # 2. 控制单只股票最大仓位
        for symbol, target in adjusted_targets.items():
            if target > self.max_single_position_pct:
                adjusted_targets[symbol] = self.max_single_position_pct
            elif target < -self.max_single_position_pct:
                adjusted_targets[symbol] = -self.max_single_position_pct
        
        # 3. 控制总仓位风险
        total_exposure = sum(abs(t) for t in adjusted_targets.values())
        if total_exposure > self.max_total_exposure:
            # 按比例缩减所有仓位
            scale_factor = self.max_total_exposure / total_exposure
            for symbol in adjusted_targets:
                adjusted_targets[symbol] *= scale_factor
        
        return adjusted_targets
    
    def set_entry_price(self, symbol: str, price: float):
        """记录入场价格"""
        self.entry_prices[symbol] = price
    
    def clear_entry_price(self, symbol: str):
        """清仓时移除价格记录"""
        if symbol in self.entry_prices:
            del self.entry_prices[symbol]


class ChipScorer:
    """
    筹码分布选股评分器 — V2 方向正确版

    用于 L2 批量筛选 4000+ 只股票的场景。
    通过四维 OHLCV-only 评分评估主力资金吸引力。

    Returns:
        float: 0-10 评分，越高越看多
    """

    def get_available_windows(self) -> list:
        """返回筹码分析支持的回看周期"""
        return [60, 120]

    def score(self, data: pd.DataFrame) -> float:
        if data.empty or len(data) < 120:
            return 0.0

        try:
            return self._calculate_v2_score(data)
        except Exception as e:
            logger.error(f"ChipScorer V2 评分失败: {e}")
            return 0.0

    def _calculate_v2_score(self, data: pd.DataFrame) -> float:
        closes = data['close'].values
        volumes = data['vol'].values if 'vol' in data.columns else (
            data['amount'].values if 'amount' in data.columns
            else np.ones(len(data))
        )

        score = 0.0
        details = {}

        # ─── 维度1: 成本位置 (0-3分) ───
        # VWAP(120) 作为主力平均成本代理
        # 价格在成本附近 → 安全；价格远离成本 → 谨慎
        vwap_120 = np.average(closes, weights=volumes) if len(closes) >= 20 else closes[-1]
        current_price = closes[-1]
        cost_deviation = (current_price - vwap_120) / vwap_120 if vwap_120 > 0 else 0

        if -0.05 <= cost_deviation <= 0.10:
            # 价格在成本 ±10% 内 → 安全区，主力未大幅盈利
            cost_score = 3.0
        elif -0.10 <= cost_deviation < -0.05:
            # 略低于成本 → 洗盘/建仓末期，机会
            cost_score = 2.5
        elif 0.10 < cost_deviation <= 0.25:
            # 已脱离成本区 10-25% → 拉升中段
            cost_score = 2.0
        elif cost_deviation < -0.10:
            # 深跌低于成本
            cost_score = 1.0
        else:
            # 大幅高于成本 > 25% → 出货风险区
            cost_score = 0.5
        details['cost_position'] = round(cost_deviation, 4)
        score += cost_score

        # ─── 维度2: 量能剖面 (0-3分) ───
        # 比较 5日 → 20日 → 60日 均量，判断量能趋势
        # 低位放量 = 建仓 ✓  高位放量 = 出货 ✗
        vol_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
        vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 0
        vol_60 = np.mean(volumes[-60:]) if len(volumes) >= 60 else 0

        # 计算价格在 120 日区间的位置
        price_high = np.max(closes[-120:])
        price_low = np.min(closes[-120:])
        price_range = price_high - price_low if price_high > price_low else 1.0
        price_position = (current_price - price_low) / price_range

        # 量比指标
        vol_ratio_5_20 = vol_5 / vol_20 if vol_20 > 0 else 1.0
        vol_ratio_20_60 = vol_20 / vol_60 if vol_60 > 0 else 1.0

        if price_position < 0.4 and 1.0 <= vol_ratio_5_20 <= 2.0:
            # 低位放量（非暴量）→ 建仓特征
            volume_score = 3.0
        elif price_position >= 0.7 and vol_ratio_5_20 >= 1.5:
            # 高位放量 → 出货特征
            volume_score = 0.5
        elif price_position < 0.3 and vol_ratio_20_60 < 1.0:
            # 低位缩量 → 洗盘后期
            volume_score = 2.5
        elif vol_ratio_5_20 < 0.7:
            # 短期极度缩量 → 交投不活跃
            volume_score = 1.0
        elif price_position >= 0.8 and vol_ratio_5_20 < 1.0:
            # 高位缩量 → 追高意愿不足
            volume_score = 0.5
        else:
            # 中性
            volume_score = 2.0
        details['volume_signal'] = round(vol_ratio_5_20, 2)
        score += volume_score

        # ─── 维度3: 趋势健康度 (0-2分) ───
        # 短中期趋势方向一致性
        if len(closes) >= 60:
            ma_5 = np.mean(closes[-5:])
            ma_20 = np.mean(closes[-20:])
            ma_60 = np.mean(closes[-60:])
            # 多头排列: MA5 > MA20 > MA60
            if ma_5 > ma_20 > ma_60:
                trend_score = 2.0
            # 空头排列: MA5 < MA20 < MA60
            elif ma_5 < ma_20 < ma_60:
                # 但价格已靠近底部 → 可能底部区域
                if price_position < 0.3:
                    trend_score = 1.5  # 底部区域空头排列是机会
                else:
                    trend_score = 0.5
            # 短期上穿中期 → 拐点
            elif ma_5 > ma_20 and ma_20 <= ma_60:
                trend_score = 1.5
            # 短期下穿中期 → 调整
            elif ma_5 < ma_20 and ma_20 > ma_60:
                if price_position < 0.4:
                    trend_score = 1.0  # 回调但未破位
                else:
                    trend_score = 0.5
            else:
                trend_score = 1.0
        else:
            trend_score = 1.0
        score += trend_score

        # ─── 维度4: 价格稳定性 (0-2分) ───
        # 窄幅震荡在低位 = 吸筹  |  宽幅波动在高位 = 出货
        if len(closes) >= 20:
            recent_volatility = np.std(closes[-20:]) / np.mean(closes[-20:])
            if price_position < 0.4 and recent_volatility < 0.05:
                # 低位窄幅 → 吸筹特征
                stability_score = 2.0
            elif price_position >= 0.7 and recent_volatility > 0.08:
                # 高位宽幅 → 出货特征
                stability_score = 0.5
            elif recent_volatility < 0.03:
                # 极低波动 → 变盘前兆
                stability_score = 1.5
            else:
                stability_score = 1.0
        else:
            stability_score = 1.0
        score += stability_score

        return min(10.0, max(0.0, score))


class MainForceScorer:
    """
    主力资金关注度评分器 — 替代 ChipScorer 用于 L2 筛选

    =================================================================
    设计理念：L2 的目标是识别「市场主力资金正在关注的股票」。
    
    主力资金的典型行为特征：
      1. 大单持续净流入（资金流向）
      2. 低位吸筹（价平量增，窄幅震荡）
      3. 筹码集中（股东户数减少）

    数据源优先级：
      [P0] moneyflow_cache — 大单/超大单净流入（核心指标）
      [P1] daily_cache — 价量特征（OHLCV）
      [P2] stk_holder_cache — 股东户数变化（辅助）

    评分范围 0-10，阈值建议 ≥6 分视为"有主力关注"。
    =================================================================
    """

    def __init__(self):
        self._dm = None
        self._chip_indicators: Optional[dict] = None
        self._chip_bins: Optional[list] = None

    @property
    def dm(self):
        if self._dm is None:
            from app.data import DataManager
            self._dm = DataManager()
        return self._dm

    def score(self, data: pd.DataFrame, symbol: str = None) -> float:
        """
        综合评分：0-10，越高代表主力关注度越强

        Args:
            data: OHLCV DataFrame（120 天以上）
            symbol: 股票代码（传入后可获取资金流向和股东数据）

        Returns:
            0-10 分
        """
        if data.empty or len(data) < 60:
            return 0.0

        try:
            closes = data['close'].values
            volumes = data['vol'].values if 'vol' in data.columns else (
                data['amount'].values if 'amount' in data.columns
                else np.ones(len(data))
            )
            price_high = np.max(closes[-120:])
            price_low = np.min(closes[-120:])
            price_range = price_high - price_low if price_high > price_low else 1.0
            price_position = (closes[-1] - price_low) / price_range

            score_a = self._score_moneyflow(symbol)
            score_b = self._score_volume_price(closes, volumes, price_position)
            score_c = self._score_concentration(symbol, closes, price_position)
            score_d = self._score_retail_contrarian(symbol, price_position)

            # E: 龙虎榜席位加分（包含假机构识别）
            score_e = self._score_lhb(symbol, data)

            # F: 筹码分布维度（新增 — 真实筹码分布计算，与渠道二共享 ChipDistributionService）
            score_f = self._score_chip_distribution(symbol, data)

            total = score_a + score_b + score_c + score_d + score_e + score_f
            return min(10.0, max(0.0, total))
        except Exception as e:
            logger.error(f"MainForceScorer 评分失败 {symbol}: {e}")
            return 0.0

    def get_sub_scores(self, data: pd.DataFrame, symbol: str = None) -> dict:
        """返回各子维度独立评分（364c Phase 3）"""
        if data.empty or len(data) < 60:
            return {'total': 0.0, 'moneyflow': 0.0, 'volume_price': 0.0,
                    'concentration': 0.0, 'retail_contrarian': 0.0,
                    'lhb': 0.0, 'chip_distribution': 0.0, 'sub_details': {}}
        try:
            closes = data['close'].values
            volumes = data['vol'].values if 'vol' in data.columns else np.ones(len(data))
            price_high = np.max(closes[-120:]) if len(closes) >= 120 else np.max(closes)
            price_low = np.min(closes[-120:]) if len(closes) >= 120 else np.min(closes)
            price_range = price_high - price_low if price_high > price_low else 1.0
            price_position = (closes[-1] - price_low) / price_range

            score_a = self._score_moneyflow(symbol)
            score_b = self._score_volume_price(closes, volumes, price_position)
            score_c = self._score_concentration(symbol, closes, price_position)
            score_d = self._score_retail_contrarian(symbol, price_position)
            score_e = self._score_lhb(symbol, data)
            score_f = self._score_chip_distribution(symbol, data)
            total = score_a + score_b + score_c + score_d + score_e + score_f

            return {
                'total': round(min(10.0, max(0.0, total)), 2),
                'moneyflow': round(score_a, 2),
                'volume_price': round(score_b, 2),
                'concentration': round(score_c, 2),
                'retail_contrarian': round(score_d, 2),
                'lhb': round(score_e, 2),
                'chip_distribution': round(score_f, 2),
                'sub_details': {},
            }
        except Exception:
            return {'total': 0.0, 'moneyflow': 0.0, 'volume_price': 0.0,
                    'concentration': 0.0, 'retail_contrarian': 0.0,
                    'lhb': 0.0, 'chip_distribution': 0.0, 'sub_details': {}}

    def get_fund_flow_strength(self, symbol: str) -> dict:
        """资金流向5级强度分层（364c Phase 3）"""
        if not symbol:
            return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '无数据'}
        try:
            mf_df = self._dm.get_cached_moneyflow(symbol)
            if mf_df is None or mf_df.empty:
                return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '无资金数据'}
            mf_5 = mf_df.tail(5)
            net_lg_5d = float(mf_5['net_lg_amount'].sum())
            pos_days = int((mf_5['net_lg_amount'] > 0).sum())
            positive_ratio = pos_days / max(len(mf_5), 1)

            if pos_days >= 3 and net_lg_5d > 100000000:
                return {'level': 'very_strong', 'level_cn': '极强', 'direction': 'inflow',
                        'detail': f'连续{pos_days}日净流入，累计{net_lg_5d/1e8:.1f}亿'}
            elif positive_ratio > 0.6:
                return {'level': 'strong', 'level_cn': '强', 'direction': 'inflow',
                        'detail': f'多数日净流入（{pos_days}/5日）'}
            elif positive_ratio > 0.4:
                return {'level': 'medium', 'level_cn': '中等', 'direction': 'mixed',
                        'detail': f'流入流出交替（{pos_days}/5日净流入）'}
            elif net_lg_5d < 0:
                return {'level': 'weak', 'level_cn': '弱', 'direction': 'outflow',
                        'detail': f'净流出（累计{net_lg_5d/1e4:.0f}万）'}
            else:
                return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral',
                        'detail': '无明确资金方向'}
        except Exception:
            return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '计算异常'}

    def get_chip_transfer(self, symbol: str) -> dict:
        """筹码转移方向检测（364c Phase 3）"""
        if not symbol:
            return {'direction': 'unknown', 'speed': 'unknown', 'detail': '无数据'}
        try:
            indicators = self._chip_indicators or {}
            asr = indicators.get('asr') or indicators.get('ASR')
            concentration = indicators.get('concentration')
            if asr is not None:
                asr_val = float(asr)
                if asr_val > 70:
                    return {'direction': '集中', 'speed': '快速', 'detail': f'筹码高度集中（ASR={asr_val:.0f}）'}
                elif asr_val > 50:
                    return {'direction': '集中', 'speed': '中等', 'detail': f'筹码中等集中（ASR={asr_val:.0f}）'}
                else:
                    return {'direction': '分散', 'speed': '中等', 'detail': f'筹码分散（ASR={asr_val:.0f}）'}
        except Exception:
            pass
        return {'direction': 'unknown', 'speed': 'unknown', 'detail': '筹码数据不足'}

    def get_control_degree(self, symbol: str) -> dict:
        """控盘度计算（364c Phase 3：三维度加权）"""
        if not symbol:
            return {'level': 'unknown', 'score': 0, 'detail': '无数据'}
        try:
            indicators = self._chip_indicators or {}
            asr = float(indicators.get('asr') or indicators.get('ASR') or 0)
            concentration = float(indicators.get('concentration') or 0)
            main_flow = 1.0 if str(tags.get('fund_flow', '')) == '5d_inflow' else 0.5
            score = (asr / 100 * 0.4) + (concentration * 0.3 if concentration else 0.5 * 0.3) + (main_flow * 0.3)
            if score > 0.7:
                level = '高控盘'
            elif score > 0.4:
                level = '中等控盘'
            else:
                level = '低控盘'
            return {'level': level, 'score': round(score, 2), 'detail': f'{level}（{score:.2f}）'}
        except Exception:
            return {'level': 'unknown', 'score': 0, 'detail': '计算异常'}

    # ─── A: 资金流向维度 (0-3分) ───────────────────────────────
    # Wiki 核心思想：大单连续性 > 单日强度；融资暴增+股价不动=危险信号
    def _score_moneyflow(self, symbol: str) -> float:
        """
        评估主力资金净流入强度（基于 LLM Wiki 主力行为分析）

        使用 moneyflow_cache 分析：
          1. 5日累积大单净额（净流入率）
          2. 大单成交占比（大单主导程度）
          3. **资金连续性**（Wiki: "连续买超+股价上涨=机构看多"）

        Returns: 0-3 分（无数据时返回 0）
        """
        if not symbol:
            return 0.0

        try:
            end_str = datetime.now().strftime('%Y-%m-%d')
            start_str = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            mf_df = self.dm.get_cached_moneyflow(
                symbol, start_date=start_str, end_date=end_str
            )
            if mf_df.empty:
                mf_df = self.dm.get_cached_moneyflow(symbol)
                if mf_df.empty:
                    return 0.0
            mf_5 = mf_df.tail(5)

            # 1. 5日累积大单净额 (0-1.0分)
            net_lg_sum = mf_5['net_lg_amount'].sum()
            abs_big = (mf_5['buy_lg_amount'].abs().sum()
                       + mf_5['sell_lg_amount'].abs().sum()
                       + mf_5['buy_elg_amount'].abs().sum()
                       + mf_5['sell_elg_amount'].abs().sum())
            net_ratio = net_lg_sum / max(abs_big, 1)
            flow_score = min(1.0, max(0, net_ratio * 4))

            # 2. 大单成交占比 (0-0.5分) — Wiki: 机构主导程度
            total_small = (mf_5['buy_sm_amount'].abs().sum()
                           + mf_5['sell_sm_amount'].abs().sum())
            if abs_big + total_small > 0:
                lg_ratio = abs_big / (abs_big + total_small)
                ratio_score = min(0.5, lg_ratio * 1.0)  # 大单占50%得0.5
            else:
                ratio_score = 0.0

            # 3. 资金连续性 (0-1.5分) — Wiki 重点：连续性比绝对量更重要
            pos_days = (mf_5['net_lg_amount'] > 0).sum()
            neg_days = (mf_5['net_lg_amount'] < 0).sum()
            # 连续净流入加分：连续2天以上净流入+0.5
            streak = 0
            max_streak = 0
            for _, row in mf_5.iterrows():
                if row['net_lg_amount'] > 0:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else:
                    streak = 0
            continuity = min(1.0, max_streak * 0.3)
            # 净胜天数
            net_days_score = min(0.5, max(0, pos_days - neg_days) * 0.15)

            return min(3.0, flow_score + ratio_score + continuity + net_days_score)
        except Exception:
            return 0.0

    # ─── B: 价量主力信号 (0-3分) ───────────────────────────────
    # Wiki 核心思想：主力四阶段（建仓/洗盘/拉升/出货）各有专属价量特征
    def _score_volume_price(self, closes, volumes, price_position) -> float:
        """
        从价量关系识别主力操盘阶段（Wiki: 筹码分析+主力行为四阶段）

        建仓: 低位价平量增        → 高分
        洗盘: 价跌量减，缩量企稳  → 中分（即将结束）
        拉升: 价涨量增，多头排列  → 最高分
        出货: 高位放量滞涨/量价背离 → 低分/负分

        Returns: 0-3 分
        """
        if len(closes) < 20:
            return 1.0

        vol_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
        vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 0
        vol_60 = np.mean(volumes[-60:]) if len(volumes) >= 60 else 0
        vol_ratio_5_20 = vol_5 / max(vol_20, 1)
        vol_ratio_20_60 = vol_20 / max(vol_60, 1) if vol_60 > 0 else 1.0

        # 均线排列
        ma_5 = np.mean(closes[-5:])
        ma_20 = np.mean(closes[-20:])
        ma_60 = np.mean(closes[-60:]) if len(closes) >= 60 else closes[-1]
        bull_market = ma_5 > ma_20 > ma_60
        bear_market = ma_5 < ma_20 < ma_60

        # ── 拉升阶段 (2.5-3分) — 价涨量增 + 多头排列
        if bull_market and vol_ratio_5_20 >= 1.1:
            return 3.0 if price_position < 0.7 else 2.5

        # ── 建仓阶段 (1.5-2.5分) — 低位价平量增
        if price_position < 0.5 and 1.1 <= vol_ratio_5_20 <= 2.0:
            if vol_ratio_20_60 >= 1.15:
                return 2.5  # 低位放量且有持续增量
            return 2.0

        # ── 洗盘后期 (1.0-1.5分) — 价跌量减后缩量企稳
        if price_position < 0.4 and vol_ratio_5_20 < 0.8:
            if vol_ratio_20_60 < 0.9:
                return 1.5  # 长期缩量→洗盘临近结束
            return 1.0

        # ── 出货嫌疑 (0-0.5分) — 高位放量不涨
        if price_position >= 0.7 and vol_ratio_5_20 >= 1.5:
            return 0.0
        if price_position >= 0.8 and vol_ratio_5_20 < 0.7:
            return 0.5  # 高位缩量→追高意愿不足

        # ── 中性 (1.0分)
        return 1.0

    # ─── C: 筹码集中度 (0-2分) ───────────────────────────────
    # Wiki 核心思想：筹码从分散到集中=建仓；股东户数下降+稳定价格=吸筹
    def _score_concentration(self, symbol: str, closes, price_position) -> float:
        """
        评估筹码集中度

        Wiki 核心理念：
          - 大户比例上升+散户比例下降=筹码集中→后续拉升
          - 低位窄幅震荡=吸筹特征
          也可参考"主力集中价"概念：VWAP(仅大单日)与当前价的偏离

        Returns: 0-2 分
        """
        # 1. 优先使用股东户数数据
        if symbol:
            try:
                holder_df = self.dm.get_cached_stk_holder(symbol)
                if not holder_df.empty and 'holder_number' in holder_df.columns:
                    h = holder_df.dropna(subset=['holder_number']).sort_values('end_date')
                    if len(h) >= 2:
                        latest = float(h['holder_number'].iloc[-1])
                        earliest = float(h['holder_number'].iloc[0])
                        if earliest > 0 and latest > 0:
                            change = (latest - earliest) / earliest
                            if change <= -0.05: return 2.0
                            elif change <= -0.02: return 1.5
                            elif change <= 0: return 1.0
                            else: return 0.5
            except Exception:
                pass

        # 2. 回退：OHLCV 稳定性评估
        if len(closes) < 20:
            return 1.0
        recent_vol = np.std(closes[-20:]) / max(np.mean(closes[-20:]), 1e-9)
        if price_position < 0.5 and recent_vol < 0.05:
            return 1.5
        elif price_position >= 0.7 and recent_vol > 0.08:
            return 0.0
        elif recent_vol < 0.03:
            return 1.0
        else:
            return 0.5

    # ─── D: 散户反向指标 (0-2分) ───────────────────────────────
    # Wiki 核心思想：散户接盘=危险信号；融资暴增+股价不涨=出货
    def _score_retail_contrarian(self, symbol: str, price_position) -> float:
        """
        散户反向指标（Wiki: "散户行为模式通常是追涨杀跌，其集体行为常被用作反向指标"）
        含融资融券信号（Wiki: "融资余额过高是危险的，而非繁荣的信号"）

        逻辑：
          - 散户净买入（small_order）偏高且价格在高位 → 散户接盘 → 负分
          - 散户净卖出且价格在低位 → 散户割肉 → 正分
          - 融资余额暴增+股价横盘 → 散户杠杆接盘 → 负分
          - 融资余额骤降+股价下跌 → 恐慌杀跌 → 正分

        Returns: 0-2 分
        """
        if not symbol:
            return 1.0
        try:
            mf_df = self.dm.get_cached_moneyflow(symbol)
            if mf_df.empty or len(mf_df) < 3:
                return 1.0
            mf_5 = mf_df.tail(5)

            # 散户5日累积净额（buy_sm - sell_sm）
            retail_net = (mf_5['buy_sm_amount'].sum()
                          - mf_5['sell_sm_amount'].sum())
            total_flow = (mf_5['buy_sm_amount'].abs().sum()
                          + mf_5['sell_sm_amount'].abs().sum())

            if total_flow < 1:
                return 1.0

            retail_ratio = retail_net / total_flow  # -1 ~ 1

            score = 1.0  # 基础分

            # 散户在高位大量买入 → 危险
            if price_position >= 0.7 and retail_ratio > 0.2:
                score = 0.0
            # 散户在低位大量卖出 → 机会
            elif price_position < 0.4 and retail_ratio < -0.2:
                score = 2.0
            elif retail_ratio < -0.1:
                score = 1.5
            elif retail_ratio > 0.1:
                score = 0.5

            # ── 融资融券反向信号（D1 margin_detail 修复后可用）──
            try:
                mrg = self.dm.get_cached_margin(symbol)
                if mrg is not None and len(mrg) >= 5:
                    mrg_5 = mrg.tail(5)
                    rzye_series = mrg_5['rzye'].dropna().values
                    if len(rzye_series) >= 3:
                        # 融资余额趋势
                        margin_change = (rzye_series[-1] - rzye_series[0]) / max(rzye_series[0], 1)
                        # 融资暴增(>10%) + 股价不涨 → 散户杠杆接盘
                        if margin_change > 0.10 and price_position >= 0.5:
                            score -= 0.5  # 扣分
                        # 融资骤降(<-10%) + 股价下跌 → 恐慌杀跌，中期底部
                        elif margin_change < -0.10 and price_position <= 0.3:
                            score += 0.3  # 加分的左侧机会
            except Exception:
                pass  # margin数据不可用时不调整

            return max(0.0, min(2.0, score))
        except Exception:
            return 1.0


    def _score_lhb(self, symbol: str, data: pd.DataFrame = None) -> float:
        """龙虎榜席位加分（-0.5 至 +1.0 分）

        使用 _detect_fake_institution 识别假机构信号，
        真机构大额买入加分，假机构信号扣分。
        """
        if not symbol:
            return 0.0
        try:
            # 假机构检测
            fake_result = self._detect_fake_institution(symbol, data)
            if fake_result['suspected']:
                return -fake_result['confidence']  # 假机构扣分

            # 真机构加分
            lhb = self.dm.get_cached_lhb(symbol)
            if lhb is not None and not lhb.empty and len(lhb) > 0:
                recent = lhb.tail(10)
                buy_amounts = recent['buy_amount'].dropna()
                if len(buy_amounts) > 0:
                    total_buy = buy_amounts.sum()
                    if total_buy > 1e7:  # 千万级买入
                        return min(1.0, total_buy / 5e8 * 1.0)  # 5亿→1.0分
            return 0.0
        except Exception:
            return 0.0

    def _detect_fake_institution(self, symbol: str, data: pd.DataFrame) -> dict:
        """假机构识别（基于 LLM Wiki 假机构识别概念）

        检查龙虎榜数据中疑似假机构的行为特征：
        1. 买入金额占比过高（>30%）→ 警惕
        2. 价格处于高位/下跌反弹途中 → 警惕
        3. 机构集中单日大额买入 → 警惕

        Returns:
            {"suspected": bool, "reason": str, "confidence": float}
        """
        result = {"suspected": False, "reason": "", "confidence": 0.0}
        try:
            # 优先使用股票级 lhb_cache；若为空则回退到席位级 lhb_detail_cache
            lhb = self.dm.get_cached_lhb(symbol)
            use_detail_only = False
            if lhb is not None and not lhb.empty and len(lhb) > 0:
                recent = lhb.tail(10)
                if 'buy_amount' not in recent.columns or 'sell_amount' not in recent.columns:
                    use_detail_only = True
                    recent = None
            else:
                use_detail_only = True
                recent = None

            # 价格位置（低位=0.0, 高位=1.0）
            closes = data['close'].values if data is not None and not data.empty else None
            price_pos = None
            if closes is not None and len(closes) >= 60:
                p_high = np.max(closes[-120:])
                p_low = np.min(closes[-120:])
                p_range = p_high - p_low if p_high > p_low else 1.0
                price_pos = (closes[-1] - p_low) / p_range

            if not use_detail_only and recent is not None:
                for _, row in recent.iterrows():
                    buy_amt = row.get('buy_amount', 0) or 0
                    sell_amt = row.get('sell_amount', 0) or 0
                    total = buy_amt + sell_amt
                    if total <= 0:
                        continue
                    buy_ratio = buy_amt / total

                    # 买入占比 > 30% + 高位 → 假机构信号
                    if buy_ratio > 0.3 and price_pos is not None and price_pos > 0.6:
                        result['suspected'] = True
                        result['reason'] = f'高位(分位{price_pos:.0%})买入占比{buy_ratio:.0%}>30%'
                        result['confidence'] = min(1.0, result['confidence'] + 0.5)

                    # 2026-08-10 修复：单日买入占比 >40% 仅在高位才判疑似
                    # （原无论位置裸阈值误伤低位吸筹真机构——000426 低位55%买入被误判；
                    #  低位高买入占比是机构吸筹特征，由 :772 连续买入缓解逻辑处理）
                    if buy_ratio > 0.4 and price_pos is not None and price_pos > 0.6:
                        result['suspected'] = True
                        detail = f'高位(分位{price_pos:.0%})买入占比{buy_ratio:.0%}>40%'
                        result['reason'] = result['reason'] + ('; ' + detail if result['reason'] else detail)
                        result['confidence'] = min(1.0, result['confidence'] + 0.3)

                # 多日连续买入+价格未涨 → 可能是真机构吸货，降低怀疑
                if result['suspected'] and len(recent) >= 3:
                    buy_days = (recent['buy_amount'].fillna(0) > 1e6).sum()
                    if buy_days >= 3 and price_pos is not None and price_pos < 0.5:
                        result['confidence'] = max(0.0, result['confidence'] - 0.3)
                        result['reason'] += '（连续买入+低位，可能真机构）'

            # 278号方案：席位级数据增强检测
            try:
                detail_df = self.dm.get_lhb_detail(symbol)
                if detail_df is not None and not detail_df.empty:
                    detail_recent = detail_df.tail(50)
                    if 'seat_type' in detail_recent.columns and 'buy_amount' in detail_recent.columns:
                        inst_mask = detail_recent['seat_type'] == 'institution'
                        inst_buy = detail_recent[inst_mask]['buy_amount'].sum()
                        broker_buy = detail_recent[~inst_mask]['buy_amount'].sum()
                        total_buy_seat = inst_buy + broker_buy
                        if total_buy_seat > 1e6:
                            inst_ratio = inst_buy / total_buy_seat
                            # 机构买入占比极低 + 买入额很大 → 可能是营业部冒充
                            if inst_ratio < 0.15 and inst_buy < broker_buy * 0.2:
                                result['suspected'] = True
                                result['confidence'] = min(1.0, result['confidence'] + 0.4)
                                detail_msg = f'机构买入仅{inst_ratio:.0%}(席位明细)'
                                result['reason'] = result['reason'] + ('; ' + detail_msg if result['reason'] else detail_msg)
                            # 机构买入占比高 → 真机构，降低怀疑
                            elif inst_ratio > 0.6 and result['suspected']:
                                result['confidence'] = max(0.0, result['confidence'] - 0.3)
                                result['reason'] += '（机构买入占比高，真机构可能大）'
            except Exception:
                pass

            return result
        except Exception:
            return result

    def _score_chip_distribution(self, symbol: str, data: pd.DataFrame) -> float:
        """
        筹码分布维度（0-1.5分）：基于真实筹码分布计算的评分

        使用 ChipDistributionService（与渠道二共享）分析筹码集中度：
          - ASR > 50% → 浮筹比例适中，有利于上涨
          - SSRP 接近当前价 → 平均成本附近，抛压小
          - CYQKL 高 → 当前K线实体穿越筹码密集区，突破确认
          - 筹码单峰密集 → 主力控盘度高

        Returns: 0-1.5 分
        """
        if not symbol or data is None or len(data) < 30:
            return 0.0
        try:
            from app.data.chip_distribution_service import ChipDistributionService
            cds = ChipDistributionService()
            result = cds.calculate_chip_distribution(symbol, data)
            if not result or not result.get('success'):
                return 0.0
            indicators = result.get('indicators', {})
            chip_bins = result.get('chip_bins', [])
            # 缓存筹码数据供 identify_phase 使用
            self._chip_indicators = indicators
            self._chip_bins = chip_bins

            score = 0.5  # 基础分

            # ASR 评估（浮筹比例）
            asr = indicators.get('asr', indicators.get('ASR', 50))
            if 30 <= asr <= 70:
                score += 0.2  # 适中的浮筹比例
            elif asr > 80:
                score -= 0.2  # 浮筹过多，抛压大
            elif asr < 20:
                score += 0.1  # 浮筹极低，筹码锁定良好

            # SSRP 评估：当前价接近市场平均成本时加分
            ssrp = indicators.get('ssrp', indicators.get('SSRP', 0))
            current_price = float(data['close'].iloc[-1])
            if ssrp > 0:
                ssrp_deviation = abs(current_price - ssrp) / ssrp
                if ssrp_deviation < 0.03:
                    score += 0.3  # 价格在SSRP ±3%内 → 成本附近，抛压小
                elif ssrp_deviation < 0.1:
                    score += 0.1  # 价格在SSRP ±10%内
                # 价格在SSRP上方且未远离 → 做多信号
                if current_price > ssrp and ssrp_deviation < 0.15:
                    score += 0.1

            # CYQKL 评估：高CYQKL = 突破确认信号
            cyqkl = indicators.get('cyqkl', indicators.get('CYQKL', 0))
            if cyqkl >= 0.5:
                score += 0.3  # 极强穿越
            elif cyqkl >= 0.3:
                score += 0.2  # 强穿越
            elif cyqkl >= 0.2:
                score += 0.1  # 中等穿越（达标）

            # 筹码峰检测（单峰密集=主力控盘）
            if chip_bins and len(chip_bins) > 0:
                ratios = [b.get('chip_ratio', 0) for b in chip_bins]
                max_ratio = max(ratios) if ratios else 0
                if max_ratio > 0.15:
                    score += 0.3  # 单峰密集

            return max(0.0, min(1.5, score))
        except Exception as e:
            logger.debug(f"筹码分布评分失败 {symbol}: {e}")
            return 0.0

    def _calc_main_force_cost(self, symbol: str, latest_close: float) -> dict:
        """
        主力集中价计算（Wiki: 主力集中价是大户平均买入成本）

        基于 moneyflow_cache 大单买入金额估算主力加权成本价。
        当股价接近主力集中价时加分，远离时扣分。

        Returns:
            {"cost_price": float, "distance_pct": float, "near_cost": bool}
        """
        try:
            mf = self.dm.get_cached_moneyflow(symbol)
            if mf is None or mf.empty or len(mf) < 3:
                return {"cost_price": 0, "distance_pct": 0, "near_cost": False}
            recent = mf.tail(20)
            # 估算主力买入总金额和总成交量
            buy_total = (recent['buy_lg_amount'].sum() + recent['buy_elg_amount'].sum())
            sell_total = (recent['sell_lg_amount'].sum() + recent['sell_elg_amount'].sum())
            net_buy = buy_total - sell_total
            if net_buy <= 0:
                return {"cost_price": 0, "distance_pct": 0, "near_cost": False}
            # 从 moneyflow_cache 估算主力加权均价
            # Tushare moneyflow 字段单位：
            #   buy_lg_vol: 手（1手=100股）
            #   buy_lg_amount / buy_elg_amount: 万元（需×10000转元）
            has_lg_vol = 'buy_lg_vol' in recent.columns
            has_lg_amt = 'buy_lg_amount' in recent.columns
            has_elg_amt = 'buy_elg_amount' in recent.columns

            if has_lg_vol and has_lg_amt:
                lg_sum_vol = recent['buy_lg_vol'].sum() * 100  # 手→股
                lg_sum_amt = recent['buy_lg_amount'].sum() * 10000  # 万元→元
                if lg_sum_vol > 0 and lg_sum_amt > 0:
                    # 大单均价（元/股）
                    unit_price = lg_sum_amt / lg_sum_vol
                    # 超大单成交量 = 金额 / 大单均价
                    elg_sum_amt = recent['buy_elg_amount'].sum() * 10000  # 万元→元
                    est_elg_vol = elg_sum_amt / unit_price if unit_price > 0 else 0
                    total_vol = lg_sum_vol + est_elg_vol
                    avg_price = (lg_sum_amt + elg_sum_amt) / total_vol if total_vol > 0 else latest_close
                else:
                    avg_price = latest_close
            else:
                # 退回到用 open/high/low/close 均值估算
                avg_prices = (recent['open'] + recent['high'] + recent['low'] + recent['close']) / 4
                avg_price = float(avg_prices.tail(5).mean()) if not avg_prices.empty else latest_close
            avg_price = float(avg_price) if avg_price > 0 else latest_close
            distance = (latest_close - avg_price) / avg_price if avg_price > 0 else 0
            return {
                "cost_price": round(avg_price, 2),
                "distance_pct": round(distance * 100, 2),
                "near_cost": abs(distance) < 0.05,  # 5%内视为接近主力成本
            }
        except Exception:
            return {"cost_price": 0, "distance_pct": 0, "near_cost": False}

    def identify_phase(self, data: pd.DataFrame, symbol: str = None,
                       chip_data: dict = None) -> str:
        """
        识别主力操盘阶段（Wiki: "建仓→洗盘→拉升→出货" 四阶段）

        当 chip_data 提供 ASR/筹码峰信息时，使用筹码数据增强判断。

        Args:
            data: OHLCV DataFrame
            symbol: 股票代码
            chip_data: 可选筹码数据字典，包含 asr, chip_peak, concentration 等
        """
        try:
            if data.empty or len(data) < 60:
                return 'unknown'
            closes = data['close'].values
            volumes = data['vol'].values if 'vol' in data.columns else data.get('amount', closes)
            price_high = np.max(closes[-120:])
            price_low = np.min(closes[-120:])
            price_range = price_high - price_low if price_high > price_low else 1.0
            price_pos = (closes[-1] - price_low) / price_range

            vol_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
            vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 0
            vol_ratio_5_20 = vol_5 / max(vol_20, 1)

            ma_5 = np.mean(closes[-5:])
            ma_20 = np.mean(closes[-20:])
            ma_60 = np.mean(closes[-60:]) if len(closes) >= 60 else closes[-1]

            # ASR 数据（从 chip_data 或上次筹码评分缓存中获取）
            asr = None
            chip_peak = None
            concentration = None
            if chip_data:
                asr = chip_data.get('asr')
                chip_peak = chip_data.get('chip_peak')
                concentration = chip_data.get('concentration')
            elif self._chip_indicators:
                asr = self._chip_indicators.get('asr') or self._chip_indicators.get('ASR')
                concentration = self._chip_indicators.get('concentration')
                # 从 chip_bins 中提取 chip_peak（最大峰值对应的价格）
                if self._chip_bins:
                    peaks = sorted(self._chip_bins, key=lambda b: b.get('chip_ratio', 0), reverse=True)
                    chip_peak = peaks[0].get('price', 0) if peaks else None

            # CYQKL（筹码盈亏比例）：(现价 - 筹码峰) / 筹码峰
            cyqkl = None
            if chip_peak and chip_peak > 0:
                cyqkl = (closes[-1] - chip_peak) / chip_peak

            # RSI 背离检测（用于出货/建仓阶段识别）
            rsi_bearish_div = False  # 价格新高但RSI未新高 → 顶背离
            rsi_bullish_div = False  # 价格新低但RSI未新低 → 底背离
            if len(closes) >= 30:
                try:
                    # 计算 RSI(14)
                    deltas = np.diff(closes)
                    gains = np.where(deltas > 0, deltas, 0)
                    losses = np.where(deltas < 0, -deltas, 0)
                    avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
                    avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
                    rsi = 100 - (100 / (1 + avg_gain / max(avg_loss, 1e-10))) if avg_loss > 0 else 100

                    # 前一段 RSI
                    avg_gain_prev = np.mean(gains[-28:-14]) if len(gains) >= 28 else avg_gain
                    avg_loss_prev = np.mean(losses[-28:-14]) if len(losses) >= 28 else avg_loss
                    rsi_prev = 100 - (100 / (1 + avg_gain_prev / max(avg_loss_prev, 1e-10))) if avg_loss_prev > 0 else 100

                    # 价格两段高点
                    high_recent = np.max(closes[-14:])
                    high_prev = np.max(closes[-28:-14]) if len(closes) >= 28 else high_recent
                    low_recent = np.min(closes[-14:])
                    low_prev = np.min(closes[-28:-14]) if len(closes) >= 28 else low_recent

                    # 顶背离：价格新高但RSI未新高
                    if high_recent >= high_prev and rsi < rsi_prev - 5:
                        rsi_bearish_div = True

                    # 底背离：价格新低但RSI未新低
                    if low_recent <= low_prev and rsi > rsi_prev + 5:
                        rsi_bullish_div = True
                except Exception:
                    pass

            # 阶段 1: 出货 — 高位 + 放量/量缩 + RSI顶背离 + 浮筹高企
            if rsi_bearish_div and price_pos >= 0.5:
                # RSI顶背离是最强的出货信号
                return 'distributing'
            if price_pos >= 0.7 and vol_ratio_5_20 >= 1.5:
                return 'distributing'
            if price_pos >= 0.8 and vol_ratio_5_20 < 0.7:
                return 'distributing'
            if price_pos >= 0.6 and asr is not None and asr > 60:
                return 'distributing'
            if price_pos >= 0.6 and cyqkl is not None and cyqkl > 0.3:
                # CYQKL > 30% + 中高位 → 获利盘丰厚, 出货迹象
                return 'distributing'

            # 阶段 2: 拉升 — 多头排列 + 放量 + CYQKL达标(>20%) + SSRP穿越
            if ma_5 > ma_20 > ma_60 and vol_ratio_5_20 >= 1.0:
                if cyqkl is not None and cyqkl >= 0.2:
                    return 'markup'  # CYQKL达标确认拉升
                if asr is None or asr < 50:
                    return 'markup'
                return 'markup'

            # 阶段 3: 洗盘 — 价跌缩量 + 中低位 + 低位筹码峰稳定
            if price_pos < 0.5 and vol_ratio_5_20 < 0.85:
                return 'washing'
            if price_pos < 0.4 and asr is not None and asr > 50 and vol_ratio_5_20 < 1.0:
                return 'washing'
            if price_pos < 0.4 and cyqkl is not None and cyqkl < -0.1 and vol_ratio_5_20 < 1.0:
                # CYQKL < -10% (深度亏损) + 低位缩量 → 洗盘特征
                return 'washing'

            # 阶段 4: 建仓 — 低位 + 温和放量 + 浮筹锁定的迹象
            if rsi_bullish_div and price_pos <= 0.5:
                # RSI底背离是最强的建仓/见底信号
                return 'accumulating'
            if price_pos < 0.5 and 1.1 <= vol_ratio_5_20 <= 2.0:
                return 'accumulating'
            if price_pos < 0.4 and asr is not None and asr < 40 and vol_ratio_5_20 >= 0.8:
                return 'accumulating'
            if price_pos < 0.3 and cyqkl is not None and cyqkl < -0.15 and concentration is not None and concentration > 0.1:
                # 低位 + 深度亏损 + 筹码集中 → 建仓尾声
                return 'accumulating'

            return 'neutral'
        except Exception:
            return 'unknown'

    def _calc_margin_cost_price(self, symbol: str, latest_close: float) -> dict:
        """计算融资成本价（散户融资买入的平均成本）
        基于 margin_cache 的 rzmje(融资买入额) 和当日均价估算。
        Returns:
            {"cost_price": float | None, "distance_pct": float | None}
        """
        try:
            margin_df = self.dm.get_cached_margin(symbol)
            if margin_df is None or margin_df.empty:
                return {"cost_price": None, "distance_pct": None}
            df = margin_df.tail(60).copy()
            if 'rzye' not in df.columns:
                return {"cost_price": None, "distance_pct": None}
            buy_mask = df['rzmje'].fillna(0) > 0 if 'rzmje' in df.columns else None
            if buy_mask is None or buy_mask.sum() < 3:
                return {"cost_price": None, "distance_pct": None}
            df_buy = df[buy_mask].copy()
            avg_prices = (df_buy['open'].fillna(latest_close)
                         + df_buy['high'].fillna(latest_close)
                         + df_buy['low'].fillna(latest_close)
                         + df_buy['close'].fillna(latest_close)) / 4
            weights = df_buy['rzmje'].fillna(0)
            if weights.sum() <= 0:
                return {"cost_price": None, "distance_pct": None}
            cost_price = (weights * avg_prices).sum() / weights.sum()
            distance_pct = (latest_close - cost_price) / cost_price * 100 if cost_price > 0 else None
            return {
                "cost_price": round(float(cost_price), 2),
                "distance_pct": round(float(distance_pct), 2) if distance_pct is not None else None,
            }
        except Exception:
            return {"cost_price": None, "distance_pct": None}

    def get_tags(self, symbol: str) -> dict:
        """返回主力资金标签"""
        tags = {}
        try:
            mf_score = self._score_moneyflow(symbol)
            if mf_score >= 2.0:
                tags['fund_flow'] = '5d_inflow'
            elif mf_score >= 1.0:
                tags['fund_flow'] = 'mixed'
            else:
                tags['fund_flow'] = 'none'

            # 2026-08-10 修复：传入真实 K 线（原传空 DataFrame 致 price_pos=None，
            # 假机构检测的"高位"约束失效 + 连续买入缓解逻辑失效 → capital_nature 全 unknown）
            try:
                _df = self.dm.get_cached_daily_data(symbol)
            except Exception:
                _df = pd.DataFrame()
            lhb_score = self._score_lhb(symbol, _df)
            if lhb_score >= 0.5:
                tags['capital_nature'] = 'institutional'
            elif lhb_score >= 0.2:
                tags['capital_nature'] = 'hot_money'
            elif lhb_score > -0.5:
                # 2026-08-10 修复：轻微怀疑（-0.5~0.2）给 hot_money（营业部/游资特征），
                # 不再一律 unknown——保留区分度（原 suspected 扣分后全落 unknown）
                tags['capital_nature'] = 'hot_money'
            else:
                tags['capital_nature'] = 'unknown'
        except Exception:
            pass
        return tags


def _phase_to_status(phase: str, score: float) -> dict:
    """将 MainForceScorer 的操盘阶段 phase 映射为标准 status_recognition 格式。

    Args:
        phase: 操盘阶段（accumulating/markup/washing/distributing/neutral/unknown）
        score: MainForceScorer 评分（0-10）

    Returns:
        status_recognition 结构化字典（7 字段统一格式）
    """
    state_map = {
        "accumulating": "ACCUMULATING",
        "markup": "ACCUMULATING",
        "washing": "RANGING",
        "distributing": "DISTRIBUTING",
        "neutral": "RANGING",
        "unknown": "RANGING",
    }
    state_label_map = {
        "ACCUMULATING": "主力建仓",
        "DISTRIBUTING": "主力出货",
        "RANGING": "筹码换手",
    }
    state = state_map.get(phase, "RANGING")
    state_label = state_label_map.get(state, "中性")

    # 用评分映射动量和趋势强度
    if score >= 7:
        momentum_level, strength = "bullish", "strong"
    elif score >= 4:
        momentum_level, strength = "neutral", "moderate"
    else:
        momentum_level, strength = "bearish", "weak"

    return {
        "state": state,
        "state_label": state_label,
        "trend": {"direction": "", "strength": strength, "stage": phase},
        "momentum": {"level": momentum_level, "score": round(score / 10, 2)},
        "volume": {"state": "", "structure": ""},
        "support_resistance": {"support": 0.0, "resistance": 0.0},
        "risk_level": "MEDIUM",
    }


class MainForceFilter:
    """
    主力关注度过滤器 — 用于 L2 筛选

    对股票列表使用 MainForceScorer 评分，
    返回评分 ≥ min_score 的股票（若无达到阈值则取 top_k 兜底）。
    """

    def __init__(self, min_score: float = 6.0, min_data_days: int = 60, top_k: int = 20):
        self.min_score = min_score
        self.min_data_days = min_data_days
        self.top_k = top_k
        self.scorer = MainForceScorer()

    def filter(self, stock_list: list, data_dict: dict) -> list:
        """
        执行主力关注度筛选

        Args:
            stock_list: [{ts_code, name}, ...] 或 [ts_code, ...]
            data_dict: {ts_code: DataFrame}

        Returns:
            [{symbol, name, mf_score, phase}, ...] 按评分降序
        """
        results = []
        for item in stock_list:
            ts_code = item if isinstance(item, str) else item.get('ts_code', '')
            name = '' if isinstance(item, str) else item.get('name', '')
            if not ts_code or ts_code not in data_dict:
                continue
            df = data_dict[ts_code]
            if df.empty or len(df) < self.min_data_days:
                continue
            try:
                score = self.scorer.score(df, symbol=ts_code)
                phase = self.scorer.identify_phase(df, symbol=ts_code)
                if score > 0:
                    # phase → status_recognition 映射
                    sr = _phase_to_status(phase, score)
                    results.append({
                        'symbol': ts_code,
                        'name': name,
                        'mf_score': round(score, 2),
                        'phase': phase,
                        'status_recognition': sr,
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x['mf_score'], reverse=True)

        # 阈值筛选：≥ min_score 通过，若无则取 top_k 兜底
        passed = [r for r in results if r['mf_score'] >= self.min_score]
        if not passed:
            top_score = results[0]["mf_score"] if results else 0
            passed = results[:self.top_k]
            logger.warning(
                f"无股票达到阈值 {self.min_score}，取 top {self.top_k} 兜底 "
                f"(最高分 {top_score})"
            )

        return passed


# === chip_position_manager.py ===

class ChipPositionManager:
    """基于操盘阶段+多层风控的仓位管理器（含金字塔建仓）"""

    # 每个操盘阶段的基础仓位上限
    PHASE_BASE_POSITION = {
        'BUILDING': 0.30,   # 建仓期：最大30%
        'WASHING': 0.50,    # 洗盘期：最大50%
        'RAISING': 0.70,    # 拉升期：最大70%
        'SHIPPING': 0.00,   # 出货期：清仓
        'SUPPORT': 0.30,    # 支撑/下跌期：最大30%
    }

    # 信号类型与仓位调整乘数
    SIGNAL_ADJUSTMENT = {
        'S_BUY': 1.0,
        'S_WASH_END': 0.8,
        'S_BOUNCE': 0.5,
        'S_SELL': 0.0,
        'S_WASH_STOP': 0.0,
        'S_DIVERG_SELL': 0.0,  # 由信号自身的 position_adjustment 决定
        'HOLD': 0.0,
    }

    # 大盘环境乘数
    MARKET_MULTIPLIER = {
        'GOOD': 1.0,
        'POOR': 0.5,
        'UNKNOWN': 0.7,
    }

    # 金字塔建仓参数
    PYRAMID_CONFIG = {
        'tier1_ratio': 0.5,      # 首次入场：目标仓位的50%
        'tier2_ratio': 0.8,      # 二次加仓：目标仓位的80%
        'tier3_ratio': 1.0,      # 三次加仓：目标仓位的100%
        'tier1_confirm_days': 0,  # Tier1 立即执行
        'tier2_confirm_days': 3,  # Tier2 需3日后确认
        'tier3_confirm_days': 6,  # Tier3 需6日后确认
        'price_up_threshold': 0.01,  # 确认条件：价格不低于入场价99%
        'price_up_strong': 0.02,     # 强确认条件：涨幅超过2%
    }

    def __init__(self):
        self._current_position = 0.0
        # 金字塔建仓状态跟踪 {symbol: {'entry_price': float, 'tier': int,
        #                           'entry_date': int, 'phase': str}}
        self._pyramid_state: Dict[str, Dict] = {}

    def set_current_position(self, position: float):
        """设置当前仓位（由外部调用更新）"""
        self._current_position = max(0.0, min(1.0, position))

    def reset_pyramid(self, symbol: str):
        """清空指定股票的金字塔建仓状态"""
        self._pyramid_state.pop(symbol, None)

    def _get_pyramid_tier_info(self, symbol: str, signal_action: str,
                                entry_price: float, date_idx: int,
                                current_price: float) -> Dict:
        """
        获取金字塔建仓层级信息

        金字塔规则（短线风险控制 仓位控制）：
          Tier1: 首批入场 50%，立即执行
          Tier2: +30%(累计80%)，需3日后价格不破入场价
          Tier3: +20%(累计100%)，需6日后价格不破入场价

        如果价格下跌：停留在当前层级不再加仓
        如果卖出信号：重置状态
        """
        state = self._pyramid_state.get(symbol)
        config = self.PYRAMID_CONFIG

        # 首次买入：初始状态
        if state is None:
            self._pyramid_state[symbol] = {
                'entry_price': entry_price,
                'tier': 1,
                'entry_date': date_idx,
                'phase': 'init'
            }
            return {
                'current_tier': 1,
                'tier_ratio': config['tier1_ratio'],
                'confirm_needed': False,
                'status': '金字塔Tier1:首仓50%'
            }

        # 已有持仓 - 检查是否可以加仓
        current_tier = state.get('tier', 1)
        holding_days = date_idx - state.get('entry_date', date_idx)
        entry = state.get('entry_price', entry_price)
        price_change = (current_price - entry) / entry if entry > 0 else 0

        # 如果价格已跌破入场价95%，不再加仓
        if price_change < -0.05:
            return {
                'current_tier': current_tier,
                'tier_ratio': [0.5, 0.8, 1.0][min(current_tier - 1, 2)],
                'confirm_needed': False,
                'status': f'价格已跌{price_change*100:.1f}%,暂停加仓,Tier{current_tier}'
            }

        # Tier1→Tier2：3日后确认
        if current_tier == 1 and holding_days >= config['tier2_confirm_days']:
            if price_change >= 0:
                # 价格未跌破入场价，加仓至80%
                state['tier'] = 2
                state['entry_date'] = date_idx  # 重置计数
                return {
                    'current_tier': 2,
                    'tier_ratio': config['tier2_ratio'],
                    'confirm_needed': True,
                    'confirm_passed': True,
                    'status': f'金字塔Tier2:加仓至80%(确认Tier1涨幅{price_change*100:.1f}%)'
                }

        # Tier2→Tier3：又3日后确认
        if current_tier == 2 and holding_days >= config['tier3_confirm_days'] - config['tier2_confirm_days']:
            if price_change >= config['price_up_threshold']:
                state['tier'] = 3
                return {
                    'current_tier': 3,
                    'tier_ratio': config['tier3_ratio'],
                    'confirm_needed': True,
                    'confirm_passed': True,
                    'status': f'金字塔Tier3:加仓至满仓(确认涨幅{price_change*100:.1f}%)'
                }

        return {
            'current_tier': current_tier,
            'tier_ratio': [0.5, 0.8, 1.0][min(current_tier - 1, 2)],
            'confirm_needed': current_tier < 3,
            'confirm_passed': False,
            'status': f'金字塔Tier{current_tier}:等待确认(持仓{holding_days}日,涨幅{price_change*100:.1f}%)'
        }

    def calculate_target_position(
        self,
        phase: str,                     # 操盘阶段
        signal_result: Dict,            # _combine_signals 的输出
        market_condition: str = 'GOOD', # 'GOOD' / 'POOR' / 'UNKNOWN'
        circuit_breaker: Optional[Dict] = None,  # CircuitBreaker.check() 输出
        symbol: Optional[str] = None,   # 股票代码（金字塔建仓用）
        entry_price: Optional[float] = None,  # 入场价格
        current_price: Optional[float] = None, # 当前价格
        date_idx: int = 0,              # 交易日索引
    ) -> Dict:
        """
        计算目标仓位

        Args:
            phase: 操盘阶段 'BUILDING'/'WASHING'/'RAISING'/'SHIPPING'/'SUPPORT'
            signal_result: _combine_signals 的输出
                {'action': str, 'reason': str, 'target_position': float, 'priority': int}
            market_condition: 大盘环境 'GOOD'/'POOR'/'UNKNOWN'
            circuit_breaker: CircuitBreaker 输出的熔断信息

        Returns:
            {'target_position': float, 'action': str, 'reason': str,
             'breakdown': Dict}  # 分步计算明细
        """
        breakdown = {}

        # ---- 步骤1: 基础仓位 ----
        base = self.PHASE_BASE_POSITION.get(phase, 0.30)
        breakdown['base_position'] = base
        breakdown['phase'] = phase

        # ---- 步骤2: 信号调整 ----
        signal_action = signal_result.get('action', 'HOLD')
        signal_adjust = self.SIGNAL_ADJUSTMENT.get(signal_action, 0.0)

        # S_DIVERG_SELL 特殊处理：使用信号自身的 position_adjustment
        if signal_action == 'REDUCE' and 'position_adjustment' in signal_result:
            signal_adjust = signal_result['position_adjustment']

        # 卖出/止损信号直接覆盖为0
        if signal_action in ('SELL',):
            signal_adjust = 0.0

        breakdown['signal_action'] = signal_action
        breakdown['signal_adjustment'] = signal_adjust

        # 信号调整后的目标仓位
        if signal_action == 'BUY':
            # 买入：基础仓位 * 信号乘数
            position = base * signal_adjust
            # 如果是 BUY 信号且有明确 target_position，使用它
            if 'target_position' in signal_result and signal_result['target_position'] is not None:
                position = signal_result['target_position']
            # 金字塔建仓：用多级入场替代一次性满仓
            if symbol is not None:
                tier_info = self._get_pyramid_tier_info(
                    symbol, signal_action,
                    entry_price or current_price or 0,
                    date_idx,
                    current_price or 0
                )
                position *= tier_info['tier_ratio']
                breakdown['pyramid'] = tier_info
        elif signal_action == 'SELL' or signal_action == 'REDUCE':
            # 卖出/减仓：使用信号的 target_position
            position = signal_result.get('target_position', 0.0)
            # target_position=None 时默认为0
            if position is None:
                position = 0.0
            # 清仓时重置金字塔状态
            if symbol is not None:
                self.reset_pyramid(symbol)
        else:
            # HOLD / 无信号
            position = self._current_position

        breakdown['after_signal'] = position

        # ---- 步骤3: 大盘环境调整 ----
        market_mult = self.MARKET_MULTIPLIER.get(market_condition, 0.7)
        position *= market_mult
        breakdown['market_condition'] = market_condition
        breakdown['market_multiplier'] = market_mult
        breakdown['after_market'] = position

        # ---- 步骤4: 熔断检查 ----
        if circuit_breaker and circuit_breaker.get('triggered', False):
            breaker_action = circuit_breaker.get('action', 'NONE')
            if breaker_action == 'LIQUIDATE_ALL':
                position = 0.0
                breakdown['circuit_breaker'] = 'LIQUIDATE_ALL'
            elif breaker_action == 'LIQUIDATE_50':
                position *= 0.5
                breakdown['circuit_breaker'] = 'LIQUIDATE_50'
            else:
                breakdown['circuit_breaker'] = 'NONE'
        else:
            breakdown['circuit_breaker'] = 'NONE'

        breakdown['after_circuit_breaker'] = position

        # ---- 步骤5: 限仓 ----
        max_allowed = self.PHASE_BASE_POSITION.get(phase, 0.30)

        # 大盘差时额外限仓40%
        if market_condition == 'POOR':
            max_allowed = min(max_allowed, 0.40)

        # 卖出/止损信号不限制（可以直接清仓）
        if signal_action not in ('SELL', 'REDUCE'):
            position = min(position, max_allowed)

        position = max(0.0, min(1.0, position))
        breakdown['max_allowed'] = max_allowed
        breakdown['final_position'] = position

        # 确定操作方向
        if position > self._current_position + 0.01:
            action = 'BUY'
        elif position < self._current_position - 0.01:
            action = 'SELL'
        else:
            action = 'HOLD'

        reasons = []
        if signal_result.get('reason'):
            reasons.append(signal_result['reason'])
        if breakdown.get('circuit_breaker', 'NONE') != 'NONE':
            reasons.append(f"熔断: {breakdown['circuit_breaker']}")
        if not reasons:
            reasons.append('仓位维持')

        return {
            'target_position': round(position, 4),
            'action': action,
            'reason': '; '.join(reasons),
            'breakdown': breakdown,
        }

    def get_phase_base(self, phase: str) -> float:
        """获取指定阶段的基准仓位"""
        return self.PHASE_BASE_POSITION.get(phase, 0.30)


# === chip_pre_filter.py ===

class MarketEnvironmentFilter:
    """大盘环境判断器 - 书本第7章§7.4"""

    def __init__(self, benchmark_service: Optional[BenchmarkService] = None):
        self.benchmark = benchmark_service or BenchmarkService()

    def check(self, index_code: str = BenchmarkIndex.HS300) -> Dict:
        """
        检查大盘环境

        规则（书本§7.4）：
          沪深300在60日均线上方 → GOOD, 仓位上限70%
          沪深300在60日均线下方 → POOR, 仓位上限40%

        Returns:
            {'condition': 'GOOD'|'POOR',
             'max_position': 0.7|0.4,
             'position_multiplier': 1.0|0.5,
             'ma60': float,
             'current_close': float,
             'days_since_cross': int}  # 突破/跌破60日线持续天数
        """
        df = self.benchmark.get_index_daily(
            ts_code=index_code,
            start_date=(datetime.now() - pd.Timedelta(days=365)).strftime('%Y%m%d')
        )

        if df.empty or len(df) < 60:
            return {
                'condition': 'UNKNOWN',
                'max_position': 0.5,
                'position_multiplier': 0.7,
                'ma60': 0,
                'current_close': 0,
                'days_since_cross': 0,
                'sentiment': self.check_sentiment(),
                'reason': '数据不足'
            }

        closes = df['close'].values
        ma60 = pd.Series(closes).rolling(60).mean().values
        current_close = float(closes[-1])
        current_ma60 = float(ma60[-1])

        # 计算突破/跌破60日线的持续天数
        days_since = 0
        for i in range(len(closes) - 1, -1, -1):
            if (current_close > current_ma60 and closes[i] > ma60[i]) or \
               (current_close <= current_ma60 and closes[i] <= ma60[i]):
                days_since += 1
            else:
                break

        if current_close > current_ma60:
            return {
                'condition': 'GOOD',
                'max_position': 0.7,
                'position_multiplier': 1.0,
                'ma60': round(current_ma60, 2),
                'current_close': current_close,
                'days_since_cross': days_since,
                'sentiment': self.check_sentiment(),
                'reason': f'沪深300({current_close:.0f}) > 60日均线({current_ma60:.0f})，持续{days_since}日'
            }
        else:
            return {
                'condition': 'POOR',
                'max_position': 0.4,
                'position_multiplier': 0.5,
                'ma60': round(current_ma60, 2),
                'current_close': current_close,
                'days_since_cross': days_since,
                'sentiment': self.check_sentiment(),
                'reason': f'沪深300({current_close:.0f}) ≤ 60日均线({current_ma60:.0f})，持续{days_since}日'
            }



    def check_sentiment(self) -> Dict:
        """
        情绪周期辅助大盘过滤 (V2方向6)
        知识库依据: 六段论(筑底/复苏/确认/冲顶/钟摆/探底)
                    华泰非对称买卖策略

        使用全市场 daily_basic 数据的平均换手率作为代理情绪指标：
          恐慌(x0.5) / 正常(x1.0) / 活跃(x1.0) / 过热(x0.7)

        Returns:
            {'sentiment': 'PANIC'|'NORMAL'|'ACTIVE'|'OVERHEAT',
             'position_multiplier': float,
             'reason': str}
        """
        try:
            from app.data import DataManager
            dm = DataManager()
            # 获取最近2个交易日的全市场换手率
            df = dm.get_cached_daily_basic(
                ts_code='000300.SH',
                start_date=(datetime.now() - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
            )
            if df.empty or 'turnover_rate' not in df.columns:
                return {'sentiment': 'NORMAL', 'position_multiplier': 1.0, 'reason': '无数据，默认正常'}

            recent = df['turnover_rate'].dropna().tail(5)
            if len(recent) == 0:
                return {'sentiment': 'NORMAL', 'position_multiplier': 1.0, 'reason': '无换手率数据'}

            avg_turnover = float(recent.mean())

            # 以历史经验阈值划分情绪周期
            if avg_turnover < 0.5:
                sentiment = 'PANIC'
                multiplier = 0.5
                reason = f'全市场换手率{avg_turnover:.2f}% < 0.5%，恐慌，仓位x0.5'
            elif avg_turnover < 1.5:
                sentiment = 'NORMAL'
                multiplier = 1.0
                reason = f'全市场换手率{avg_turnover:.2f}%，正常，仓位x1.0'
            elif avg_turnover < 3.0:
                sentiment = 'ACTIVE'
                multiplier = 1.0
                reason = f'全市场换手率{avg_turnover:.2f}%，活跃，仓位x1.0'
            else:
                sentiment = 'OVERHEAT'
                multiplier = 0.7
                reason = f'全市场换手率{avg_turnover:.2f}% > 3%，过热，仓位x0.7'

            return {
                'sentiment': sentiment,
                'position_multiplier': multiplier,
                'avg_turnover': round(avg_turnover, 2),
                'reason': reason
            }
        except Exception as e:
            return {'sentiment': 'NORMAL', 'position_multiplier': 1.0, 'reason': f'检测异常: {e}'}


class CircuitBreaker:
    """熔断检查器 - 书本第9章§9.5"""

    def __init__(self, benchmark_service: Optional[BenchmarkService] = None):
        self.benchmark = benchmark_service or BenchmarkService()

    def check(self, index_code: str = BenchmarkIndex.HS300) -> Dict:
        """
        熔断检查

        规则（书本§9.5）：
          大盘单日跌幅>5% → 平仓50%
          大盘连续3日下跌且累计>8% → 清空所有仓位

        Returns:
            {'triggered': True|False,
             'action': 'LIQUIDATE_50'|'LIQUIDATE_ALL'|'NONE',
             'reason': str}
        """
        df = self.benchmark.get_index_daily(
            ts_code=index_code,
            start_date=(datetime.now() - pd.Timedelta(days=30)).strftime('%Y%m%d')
        )

        if df.empty or len(df) < 5:
            return {'triggered': False, 'action': 'NONE', 'reason': '数据不足'}

        closes = df['close'].values
        pct_chg = df.get('pct_chg', df['close'].pct_change() * 100).values

        # 最近5日数据
        recent_pct = pct_chg[-5:]
        recent_closes = closes[-5:]

        # 规则1：单日跌幅>5%
        latest_pct = recent_pct[-1] if not np.isnan(recent_pct[-1]) else 0
        if latest_pct < -5:
            return {
                'triggered': True,
                'action': 'LIQUIDATE_50',
                'reason': f'大盘单日跌幅{abs(latest_pct):.1f}% > 5%，触发熔断，减仓50%'
            }

        # 规则2：连续3日下跌且累计>8%
        consecutive_days = 0
        cumulative = 0
        for p in reversed(recent_pct):
            if np.isnan(p):
                break
            if p < 0:
                consecutive_days += 1
                cumulative += abs(p)
            else:
                break

        if consecutive_days >= 3 and cumulative > 8:
            return {
                'triggered': True,
                'action': 'LIQUIDATE_ALL',
                'reason': f'大盘连续{consecutive_days}日下跌，累计跌幅{cumulative:.1f}% > 8%，清空仓位'
            }

        return {'triggered': False, 'action': 'NONE', 'reason': '正常'}


class EligibilityFilter:
    """新股过滤器 - 书本第9章§9.6"""

    def __init__(self, data_manager: Optional[DataManager] = None):
        self.data_manager = data_manager or DataManager()
        self._stock_info_cache = {}

    def check(self, ts_code: str) -> Dict:
        """
        检查股票是否满足上市时间要求

        规则（书本§9.6）：
          上市不满250个交易日的股票排除

        Returns:
            {'passed': True|False, 'reason': str, 'days_listed': int}
        """
        # 优先从缓存获取
        if ts_code in self._stock_info_cache:
            list_date = self._stock_info_cache[ts_code]
        else:
            list_date = self._fetch_list_date(ts_code)
            if list_date:
                self._stock_info_cache[ts_code] = list_date

        if list_date is None:
            return {'passed': True, 'reason': '无法获取上市日期，默认通过', 'days_listed': 0}

        days_listed = (date.today() - list_date).days

        if days_listed < 250:
            return {
                'passed': False,
                'reason': f'上市仅{days_listed}天，不足250个交易日标准',
                'days_listed': days_listed
            }

        return {'passed': True, 'reason': '', 'days_listed': days_listed}

    def _fetch_list_date(self, ts_code: str) -> Optional[date]:
        """从多种来源获取上市日期"""
        # 1. 从 Stock ORM 模型获取（如果表存在且有数据）
        try:
            from app.models import Stock
            stock = Stock.query.get(ts_code)
            if stock is not None and stock.list_date is not None:
                if isinstance(stock.list_date, str):
                    return datetime.strptime(stock.list_date, '%Y-%m-%d').date()
                return stock.list_date
        except Exception:
            pass

        # 2. 从 DataManager stock_list 获取（akshare/tushare）
        try:
            stock_list = self.data_manager.get_stock_list()
            for s in stock_list:
                if s.get('ts_code') == ts_code:
                    ipo_date = s.get('list_date') or s.get('ipo_date')
                    if ipo_date:
                        if isinstance(ipo_date, str):
                            return datetime.strptime(ipo_date[:10], '%Y-%m-%d').date()
                        return ipo_date
        except Exception:
            pass

        return None


class LiquidityFilter:
    """流动性过滤器 - 书本第3章§3.6"""

    def __init__(self, data_manager: Optional[DataManager] = None):
        self.data_manager = data_manager or DataManager()

    def check(self, ts_code: str) -> Dict:
        """
        检查股票流动性

        规则（书本§3.6）：
          换手率<2% → 低活跃度，排除
          换手率2%~5% → 正常
          换手率5%~10% → 活跃
          换手率≥10% → 极高活跃，出货期警惕

        使用最近20个交易日的平均换手率作为判断依据

        Returns:
            {'passed': bool, 'turnover_rate': float, 'status': str}
        """
        df = self.data_manager.get_cached_daily_basic(
            ts_code,
            start_date=(datetime.now() - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
        )

        if df.empty or 'turnover_rate' not in df.columns:
            return {
                'passed': True,
                'turnover_rate': 0,
                'status': '未知',
                'reason': '无换手率数据，默认通过'
            }

        recent = df['turnover_rate'].dropna().tail(20)
        if len(recent) == 0:
            return {
                'passed': True,
                'turnover_rate': 0,
                'status': '未知',
                'reason': '换手率数据为空，默认通过'
            }

        avg_turnover = float(recent.mean())

        if avg_turnover < 2.0:
            return {
                'passed': False,
                'turnover_rate': round(avg_turnover, 2),
                'status': '低活跃度',
                'reason': f'20日平均换手率{avg_turnover:.2f}% < 2%，流动性不足'
            }
        elif avg_turnover < 5.0:
            return {
                'passed': True,
                'turnover_rate': round(avg_turnover, 2),
                'status': '正常',
                'reason': ''
            }
        elif avg_turnover < 10.0:
            return {
                'passed': True,
                'turnover_rate': round(avg_turnover, 2),
                'status': '活跃',
                'reason': ''
            }
        else:
            return {
                'passed': True,
                'turnover_rate': round(avg_turnover, 2),
                'status': '极高',
                'reason': '换手率极高，注意出货风险'
            }


class MarketCapAdapter:
    """市值适配器 - 书本第9章§9.4"""

    def __init__(self, data_manager: Optional[DataManager] = None):
        self.data_manager = data_manager or DataManager()

    def get_parameters(self, ts_code: str) -> Dict:
        """
        根据市值获取适配参数集

        规则（书本§9.4）：
          <50亿(小盘)     → 标准参数
          50~200亿(中盘)  → 放宽成交量倍数0.2
          200~1000亿(大盘) → CYQKL阈值降低5
          >1000亿(超大盘) → 不作为主策略

        Returns:
            {'cap_level': str, 'param_adjustments': Dict, 'circ_mv': float}
        """
        df = self.data_manager.get_cached_daily_basic(
            ts_code,
            start_date=(datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
        )

        if df.empty or 'circ_mv' not in df.columns:
            return {'cap_level': 'UNKNOWN', 'circ_mv': 0, 'param_adjustments': {}}

        circ_mv = float(df['circ_mv'].dropna().iloc[-1])

        if circ_mv < 50:  # 亿
            return {
                'cap_level': 'SMALL',
                'circ_mv': circ_mv,
                'param_adjustments': {}
            }
        elif circ_mv < 200:
            return {
                'cap_level': 'MID',
                'circ_mv': circ_mv,
                'param_adjustments': {'vol_multiplier_boost': 0.2}
            }
        elif circ_mv < 1000:
            return {
                'cap_level': 'LARGE',
                'circ_mv': circ_mv,
                'param_adjustments': {'cyqkl_threshold_reduction': -5}
            }
        else:
            return {
                'cap_level': 'MEGA',
                'circ_mv': circ_mv,
                'param_adjustments': {'is_secondary': True}
            }


class ChipPreFilter:
    """
    筹码策略前置过滤器（主入口）
    
    按书本第0层-第9章的过滤逻辑，串联所有前置检查。
    输出一个统一的过滤结果，供后续策略模块使用。
    """

    def __init__(self):
        self.market_filter = MarketEnvironmentFilter()
        self.circuit_breaker = CircuitBreaker()
        self.eligibility_filter = EligibilityFilter()
        self.liquidity_filter = LiquidityFilter()
        self.cap_adapter = MarketCapAdapter()

        # Phase 2: 财务风险过滤 + ROCE 指标
        self.financial_risk_filter = FinancialRiskFilter()
        self.roce_indicator = ROCEIndicator()

    def filter_market(self) -> Dict:
        """大盘环境过滤"""
        env = self.market_filter.check()
        breaker = self.circuit_breaker.check()

        result = {
            'environment': env,
            'circuit_breaker': breaker,
            'overall_position_multiplier': env['position_multiplier'],
            'overall_max_position': env['max_position']
        }

        # 情绪周期覆盖
        sentiment_info = env.get('sentiment', {})
        if isinstance(sentiment_info, dict) and sentiment_info.get('position_multiplier', 1.0) < 1.0:
            result['overall_position_multiplier'] *= sentiment_info['position_multiplier']
            result['overall_max_position'] *= sentiment_info['position_multiplier']

        # 熔断覆盖大盘环境
        if breaker['triggered']:
            if breaker['action'] == 'LIQUIDATE_ALL':
                result['overall_position_multiplier'] = 0.0
                result['overall_max_position'] = 0.0
            elif breaker['action'] == 'LIQUIDATE_50':
                result['overall_position_multiplier'] *= 0.5
                result['overall_max_position'] *= 0.5

        return result

    def filter_stock(self, ts_code: str) -> Dict:
        """
        对单只股票执行完整的过滤检查

        Returns:
            {
                'passed': True|False,   # 是否通过所有检查
                'reasons': [str],       # 未通过原因列表
                'turnover_rate': float,  # 换手率
                'cap_level': str,        # 市值等级
                'circ_mv': float,        # 流通市值
                'days_listed': int,      # 上市天数
                'param_adjustments': {}  # 参数调整
            }
        """
        reasons = []
        passed = True

        # 1. 新股排除（数据有效性硬约束：上市初期筹码分布不可靠）
        elig = self.eligibility_filter.check(ts_code)
        if not elig['passed']:
            passed = False
            reasons.append(elig['reason'])

        # 2. 流动性过滤（332号 P0：改为风险标注不硬剔除——335号 L0b 可逆不否决，流动性差=操作提示）
        liq = self.liquidity_filter.check(ts_code)
        if not liq['passed']:
            reasons.append(liq['reason'])

        # 3. 市值适配（不排除股票，只调整参数）
        cap = self.cap_adapter.get_parameters(ts_code)
        if cap.get('cap_level') == 'MEGA':
            reasons.append('超大盘股，仅作为次要策略')

        # 整理换手率
        turnover_rate = 0.0
        if 'turnover_rate' in liq:
            turnover_rate = liq['turnover_rate']


        # Phase 2: 财务风险检查（332号 P0：仅 ST/退市 硬过滤，其余标注——335号 L0b 可逆不否决；
        # 原 ROCE<5%/财务异常硬剔除大量误杀（fina 数据缺失/单位问题），覆盖度 5%→目标≥90%）
        fin_risk = self.financial_risk_filter.check(ts_code)
        if not fin_risk['passed']:
            for _r in fin_risk['reasons']:
                if ('退市' in _r) or ('ST' in _r):
                    passed = False
                reasons.append(_r)

        # ROCE 指标（不排除股票，仅作为辅助参考）
        roce_result = self.roce_indicator.get_roce(ts_code)

        return {
            'passed': passed,
            'reasons': reasons,
            'turnover_rate': turnover_rate,
            'cap_level': cap.get('cap_level', 'UNKNOWN'),
            'circ_mv': cap.get('circ_mv', 0),
            'days_listed': elig.get('days_listed', 0),
            'param_adjustments': cap.get('param_adjustments', {}),
            'financial_risk': fin_risk,
            'roce': roce_result,
        }

    def filter_batch(self, ts_codes: list) -> Dict:
        """
        批量过滤股票，返回通过/未通过列表

        Returns:
            {
                'passed': [ts_code, ...],
                'failed': {ts_code: [reason, ...], ...},
                'market': {...}
            }
        """
        market = self.filter_market()

        passed = []
        failed = {}

        for code in ts_codes:
            result = self.filter_stock(code)
            if result['passed']:
                passed.append(code)
            else:
                failed[code] = result['reasons']

        return {
            'passed': passed,
            'failed': failed,
            'market': market
        }


# ═══════════════════════════════════════════════
# Phase 2: 六大禁区过滤器 + ROCE 指标接入
# ═══════════════════════════════════════════════

class FinancialRiskFilter:
    """
    财务风险过滤器 — 覆盖六大禁区
    
    六大禁区：
      1. 业绩雷：净利润连续2年下滑或亏损
      2. 退市雷：ST/*ST/退市预警
      3. 财务雷：资产负债率异常/现金流为负
      4. 监管雷：被证监会立案调查/行政处罚
      5. 行业雷：行业政策风险（如双减/房地产三条红线）
      6. 流动性雷：日均成交额<500万（补充 LiquidityFilter）
    
    注：完整财务数据依赖 Tushare fina_vip 接口（需>=5000积分），
    当前在有限数据下优先使用 daily_basic 已有字段做初步过滤。
    """

    def __init__(self, data_manager=None):
        from app.data import DataManager
        self.data_manager = data_manager or DataManager()

    def check(self, ts_code: str) -> Dict:
        """
        执行六大禁区检查

        Returns:
            {'passed': bool, 'reasons': [str], 'details': Dict}
        """
        reasons = []
        details = {}

        # 1. 退市雷（ST/*ST/退市名称）检测已迁移至 event_monitor（335号 §4：
        #    机会图谱链路 L0a 硬否决拦截；本处不再重复检测，原 _check_st_status 已删除）

        # 2. 业绩雷：基于PE和daily_basic数据做初步判断
        profit_check = self._check_profit_risk(ts_code)
        if not profit_check['passed']:
            reasons.append(profit_check['reason'])
        details['profit_risk'] = profit_check

        # 3. 财务雷：基于资产负债率初步判断
        debt_check = self._check_debt_risk(ts_code)
        if not debt_check['passed']:
            reasons.append(debt_check['reason'])
        details['debt_risk'] = debt_check

        # 4. 流动性雷（补充）：成交额过滤
        liquid_check = self._check_liquidity_risk(ts_code)
        if not liquid_check['passed']:
            reasons.append(liquid_check['reason'])
        details['liquidity_risk'] = liquid_check

        # 5. 监管雷：从数据库/缓存中查找监管标记
        reg_check = self._check_regulatory_risk(ts_code)
        if not reg_check['passed']:
            reasons.append(reg_check['reason'])
        details['regulatory_risk'] = reg_check

        # 6. ROCE 硬性门槛（Wiki: ROCE≥15%为基本门槛）
        roce_check = self._check_roce(ts_code)
        if not roce_check['passed']:
            reasons.append(roce_check['reason'])
        details['roce'] = roce_check

        # 6. 行业雷：基于行业分类做初步判断
        industry_check = self._check_industry_risk(ts_code)
        if not industry_check['passed']:
            reasons.append(industry_check['reason'])
        details['industry_risk'] = industry_check


        return {
            'passed': len(reasons) == 0,
            'reasons': reasons,
            'details': details,
        }

    def _check_profit_risk(self, ts_code: str) -> Dict:
        """检查业绩雷：基于PE和daily_basic"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_basic(
                ts_code,
                start_date=None
            )
            if df.empty or 'pe' not in df.columns and 'pe_ttm' not in df.columns:
                return {'passed': True, 'reason': '', 'detail': 'PE数据不足，默认通过'}

            pe_col = 'pe_ttm' if 'pe_ttm' in df.columns else 'pe'
            recent_pe = df[pe_col].dropna()

            if len(recent_pe) == 0:
                return {'passed': True, 'reason': '', 'detail': 'PE数据为空，默认通过'}

            latest_pe = float(recent_pe.iloc[-1])

            # PE为0：可能亏损（0 < PE < 合理值通常表示盈利）
            # PE为负：净利润为负 → 业绩雷
            if latest_pe < 0:
                return {
                    'passed': False,
                    'reason': f'业绩雷: PE={latest_pe:.2f}<0，净利润为负',
                    'detail': {'pe': latest_pe}
                }

            # PE极高（>300）：可能业绩剧烈波动
            if latest_pe > 300:
                return {
                    'passed': False,
                    'reason': f'业绩雷: PE={latest_pe:.2f}>300，业绩异常',
                    'detail': {'pe': latest_pe}
                }

            return {'passed': True, 'reason': '', 'detail': {'pe': latest_pe}}

        except Exception as e:
            return {'passed': True, 'reason': '', 'detail': f'检测异常: {e}'}

    def _check_debt_risk(self, ts_code: str) -> Dict:
        """检查财务雷：基于PE/市值辅助判断"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_basic(
                ts_code,
                start_date=None
            )
            if df.empty:
                return {'passed': True, 'reason': '', 'detail': '数据不足，默认通过'}

            # 使用市值判断是否有财务雷嫌疑
            # 小市值+PE异常的组合
            if 'circ_mv' in df.columns:
                mv = float(df['circ_mv'].dropna().iloc[-1]) if not df['circ_mv'].dropna().empty else 0
                if mv < 5:  # 流通市值<5亿
                    return {
                        'passed': True,
                        'warning': True,
                        'reason': f'财务雷预警: 流通市值仅{mv:.1f}亿，需关注',
                        'detail': {'circ_mv': mv}
                    }

            return {'passed': True, 'reason': '', 'detail': {}}

        except Exception as e:
            return {'passed': True, 'reason': '', 'detail': f'检测异常: {e}'}

    def _check_liquidity_risk(self, ts_code: str) -> Dict:
        """检查流动性雷：日均成交额<500万"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_data(ts_code)
            if df.empty:
                return {'passed': True, 'reason': '', 'detail': '数据不足，默认通过'}

            # 使用amount字段判断成交额
            amount_col = 'amount' if 'amount' in df.columns else 'vol'
            recent_amount = df[amount_col].dropna().tail(20)
            if len(recent_amount) == 0:
                return {'passed': True, 'reason': '', 'detail': '无成交额数据'}

            avg_amount = float(recent_amount.mean())
            # 332号 P0 修复：daily_cache.amount 单位为千元（Tushare 口径），
            # 原代码按"元"与 500 万比较（avg_amount < 5000000）误杀全部正常成交股
            # （603897 实测 avg_amount=33万 千元 ≈ 3.3 亿元，实为正常流动性）。
            if avg_amount * 1000 < 5000000:  # 500万（元）
                return {
                    'passed': False,
                    'reason': f'流动性雷: 20日日均成交额{avg_amount/10000:.0f}万 < 500万',
                    'detail': {'avg_amount': avg_amount}
                }

            return {'passed': True, 'reason': '', 'detail': {'avg_amount': avg_amount}}

        except Exception as e:
            return {'passed': True, 'reason': '', 'detail': f'检测异常: {e}'}

    def _check_regulatory_risk(self, ts_code: str) -> Dict:
        """检查监管雷：从数据库/缓存中查找监管标记"""
        # 当前无监管数据API接入，返回默认通过
        return {'passed': True, 'reason': '', 'detail': '监管数据未接入，默认通过'}

    def _check_roce(self, ts_code: str) -> Dict:
        """
        ROCE硬性门槛（Wiki: ROCE筛选法）

        ROCE = EBIT / (总资产 - 流动负债)
        使用规则：
          - ROCE ≥ 15% → 通过（优秀）
          - 5% ≤ ROCE < 15% → 需关注（软警告，不硬性拒绝）
          - ROCE < 5% 或 为负 → 硬性拒绝

        数据来源：优先 fina_indicator_cache 的 ROE（D2 修复后可用），
                  后备 daily_basic 的 PE 倒数估算。
        """
        try:
            dm = self.data_manager
            roce_val = None

            # 方法1: 从 fina_indicator_cache 获取 ROE（更准确）
            try:
                fi = dm.get_cached_fina_indicator(ts_code)
                if fi is not None and not fi.empty and 'roe' in fi.columns:
                    roe_val = float(fi['roe'].dropna().iloc[-1])
                    if roe_val > 0:
                        # ROCE 通常略高于 ROE（加杠杆效应），经验系数 ×1.2
                        roce_val = roe_val * 1.2
            except Exception:
                pass

            # 方法2: 从 income_cache + balancesheet_cache 计算
            if roce_val is None:
                try:
                    income = dm.get_cached_income(ts_code)
                    bs = dm.get_cached_balancesheet(ts_code)
                    if (income is not None and not income.empty
                            and bs is not None and not bs.empty):
                        op_profit = float(income['operating_profit'].dropna().iloc[-1]) \
                            if 'operating_profit' in income.columns else 0
                        total_assets = float(bs['total_assets'].dropna().iloc[-1]) \
                            if 'total_assets' in bs.columns else 0
                        current_liab = float(bs['current_liabilities'].dropna().iloc[-1]) \
                            if 'current_liabilities' in bs.columns else 0
                        capital_employed = total_assets - current_liab
                        if capital_employed > 0 and op_profit > 0:
                            roce_val = (op_profit / capital_employed) * 100
                except Exception:
                    pass

            # 方法3: PE 倒数估算（后备）
            if roce_val is None:
                indicator = ROCEIndicator(dm)
                est = indicator.get_roce(ts_code)
                if est['available'] and est['roce'] is not None:
                    roce_val = est['roce']

            if roce_val is None:
                return {'passed': True, 'reason': '', 'detail': '无ROCE数据，默认通过'}

            if roce_val >= 15:
                return {'passed': True, 'reason': '',
                        'detail': {'roce': round(roce_val, 2), 'level': 'EXCELLENT'}}
            elif roce_val >= 5:
                return {'passed': True, 'warning': True,
                        'reason': f'ROCE={roce_val:.1f}% < 15%，需关注资本回报效率',
                        'detail': {'roce': round(roce_val, 2), 'level': 'FAIR'}}
            else:
                return {'passed': False,
                        'reason': f'ROCE={roce_val:.1f}% < 5%，资本回报率过低，剔除',
                        'detail': {'roce': round(roce_val, 2), 'level': 'POOR'}}

        except Exception as e:
            return {'passed': True, 'reason': '', 'detail': f'检测异常: {e}'}

    def _check_industry_risk(self, ts_code: str) -> Dict:
        """检查行业雷：基于行业分类"""
        # 当前无行业分类数据API
        # TODO: 接入行业分类数据后，检查:
        #   - 政策限制行业（如房地产三条红线）
        #   - 产能过剩行业
        #   - 衰退期行业
        return {'passed': True, 'reason': '', 'detail': '行业分类数据未接入，默认通过'}


class ROCEIndicator:
    """
    ROCE（资本回报率）指标接入
    
    ROCE = EBIT / (总资产 - 流动负债)
    用于评估公司资本使用效率。
    
    数据来源：Tushare fina_vip（需>=5000积分），当前为占位实现。
    可用的替代数据源：akshare 财务指标接口。
    """

    def __init__(self, data_manager=None):
        from app.data import DataManager
        self.data_manager = data_manager or DataManager()

    def get_roce(self, ts_code: str) -> Dict:
        """
        计算ROCE指标

        Returns:
            {
                'roce': float or None,
                'available': bool,     # 数据是否可用
                'level': str,          # 'EXCELLENT'/'GOOD'/'FAIR'/'POOR'/'UNKNOWN'
                'reason': str,
                'detail': Dict
            }
        """
        # 尝试从daily_basic的pe/roe字段估算
        roce_est = self._estimate_roce(ts_code)
        if roce_est['available']:
            return roce_est

        # 尝试通过akshare获取（如果已安装）
        return self._fetch_from_akshare(ts_code)

    def _estimate_roce(self, ts_code: str) -> Dict:
        """从daily_basic的PE字段估算ROCE"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_basic(ts_code)
            if df.empty:
                return {'roce': None, 'available': False,
                        'level': 'UNKNOWN', 'reason': '数据不足', 'detail': {}}

            # PE的倒数可作为ROE的粗略估算
            # ROCE ≈ EBIT/(总资产-流动负债)，比ROE更宽泛
            if 'pe_ttm' in df.columns:
                pe = float(df['pe_ttm'].dropna().iloc[-1]) if not df['pe_ttm'].dropna().empty else 0
            elif 'pe' in df.columns:
                pe = float(df['pe'].dropna().iloc[-1]) if not df['pe'].dropna().empty else 0
            else:
                return {'roce': None, 'available': False,
                        'level': 'UNKNOWN', 'reason': '无PE数据', 'detail': {}}

            if pe > 0:
                # ROCE ≈ 1/PE × 1.5（经验系数，ROCE通常略高于PE倒数）
                roce_est = (1.0 / pe) * 100 * 1.5
                level = self._classify_roce(roce_est)
                return {
                    'roce': round(roce_est, 2),
                    'available': True,
                    'level': level,
                    'reason': f'基于PE估算ROCE={roce_est:.1f}%',
                    'detail': {'method': 'pe_estimate', 'pe': pe}
                }
            else:
                return {'roce': None, 'available': False,
                        'level': 'UNKNOWN', 'reason': f'PE={pe}，无法估算', 'detail': {'pe': pe}}

        except Exception as e:
            return {'roce': None, 'available': False,
                    'level': 'UNKNOWN', 'reason': f'估算异常: {e}', 'detail': {}}

    def _fetch_from_akshare(self, ts_code: str) -> Dict:
        """尝试通过akshare获取财务指标"""
        try:
            import akshare as ak
            # akshare 的财务指标接口
            symbol = ts_code.split('.')[0]
            # 尝试获取利润表/资产负债表
            df = ak.stock_profit_sheet_by_report_em(symbol)
            if df is not None and not df.empty:
                # 提取EBIT和资本数据
                return {
                    'roce': None,
                    'available': True,
                    'level': 'UNKNOWN',
                    'reason': 'akshare数据可用，需进一步对接',
                    'detail': {'method': 'akshare_available'}
                }
        except ImportError:
            pass
        except Exception:
            pass

        return {'roce': None, 'available': False,
                'level': 'UNKNOWN', 'reason': '财务数据接口未接入', 'detail': {}}

    def get_risk_tags(self, symbol) -> dict:
        """返回财务风险标签"""
        tags = {}
        try:
            from app.data import DataManager
            dm = DataManager()
            fina_df = dm.get_cached_fina_indicator(symbol)
            if fina_df is not None and not fina_df.empty:
                latest = fina_df.iloc[-1]
                roce = latest.get('roce', 0) or 0
                debt = latest.get('debt_ratio', 0) or 0

                tags['roce_pass'] = roce >= 15
                if roce >= 15 and debt < 70:
                    tags['fina_health'] = 'pass'
                elif roce < 5 or debt > 80:
                    tags['fina_health'] = 'fail'
                else:
                    tags['fina_health'] = 'suspicious'
        except Exception:
            tags.update({'fina_health': 'suspicious', 'roce_pass': False})
        return tags

    @staticmethod
    def _classify_roce(roce: float) -> str:
        """ROCE等级分类"""
        if roce >= 20:
            return 'EXCELLENT'
        elif roce >= 12:
            return 'GOOD'
        elif roce >= 6:
            return 'FAIR'
        elif roce > 0:
            return 'POOR'
        return 'NEGATIVE'




# === chip_risk_executor.py ===

class ChipRiskExecutor:
    """止损止盈执行引擎"""

    def __init__(self):
        # 持仓状态跟踪
        self.entry_prices: Dict[str, float] = {}
        self.entry_dates: Dict[str, int] = {}
        self.peak_prices: Dict[str, float] = {}
        self.rsi_high_count: Dict[str, int] = {}
        self.holding_days: Dict[str, int] = {}

    def reset(self, symbol: str):
        """清空单只股票的跟踪状态"""
        self.entry_prices.pop(symbol, None)
        self.entry_dates.pop(symbol, None)
        self.peak_prices.pop(symbol, None)
        self.rsi_high_count.pop(symbol, None)
        self.holding_days.pop(symbol, None)

    def set_entry(self, symbol: str, price: float, date_idx: int = 0):
        """记录入场信息"""
        self.entry_prices[symbol] = price
        self.entry_dates[symbol] = date_idx
        self.peak_prices[symbol] = price
        self.rsi_high_count[symbol] = 0
        self.holding_days[symbol] = 0

    # ==================== 风险检查入口 ====================

    def execute_stop_loss(
        self,
        symbol: str,
        current_price: float,
        date_idx: int = 0,
    ) -> List[Dict]:
        """
        对所有持仓执行止损检查

        Args:
            symbol: 股票代码
            current_price: 当前价格
            date_idx: 当前交易日索引（用于计算持仓天数）

        Returns:
            止损动作列表，每个元素 {'action': str, 'reason': str}
        """
        actions = []
        entry_price = self.entry_prices.get(symbol)
        if entry_price is None or entry_price <= 0:
            return actions

        # 更新持仓天数
        if date_idx > 0 and symbol in self.entry_dates:
            self.holding_days[symbol] = date_idx - self.entry_dates[symbol]

        # 更新最高价
        peak = self.peak_prices.get(symbol, entry_price)
        if current_price > peak:
            self.peak_prices[symbol] = current_price
            peak = current_price

        # --- 8.1 硬止损（书本第7章§7.2.1）---
        if current_price < entry_price * 0.92:
            actions.append({
                'action': 'SELL_ALL',
                'reason': "硬止损(8%): 入场价{:.2f} 当前{:.2f}".format(entry_price, current_price)
            })
            self.reset(symbol)
            return actions  # 硬止损优先，不再检查其他

        # --- 8.2 跟踪止损（书本第7章§7.2.2）---
        if peak > entry_price:
            drawdown = (peak - current_price) / peak
            if drawdown > 0.15:
                actions.append({
                    'action': 'SELL_50',
                    'reason': "跟踪止损(回撤{:.1f}%>15%): 最高{:.2f} 当前{:.2f}".format(
                        drawdown * 100, peak, current_price)
                })

        # --- 8.3 时间止损（书本第7章§7.2.4）---
        holding = self.holding_days.get(symbol, 0)
        if holding >= 20 and current_price <= entry_price * 1.01:
            actions.append({
                'action': 'SELL_50',
                'reason': "时间止损({}日未盈利): 入场价{:.2f} 当前{:.2f}".format(
                    holding, entry_price, current_price)
            })

        return actions

    def check_take_profit(
        self,
        symbol: str,
        current_price: float,
        indicators: Dict,
        chip_bins: Optional[List[Dict]] = None,
        rsi: Optional[float] = None,
    ) -> List[Dict]:
        """
        止盈检查

        Args:
            symbol: 股票代码
            current_price: 当前价格
            indicators: 筹码指标字典
            chip_bins: 筹码分布数据（用于筹码止盈）
            rsi: RSI值

        Returns:
            止盈动作列表
        """
        actions = []
        entry_price = self.entry_prices.get(symbol)
        if entry_price is None:
            return actions

        peak = self.peak_prices.get(symbol, current_price)

        # --- 8.4 筹码止盈（书本第7章§7.3.1）---
        if chip_bins is not None:
            chip_action = self._chip_take_profit(symbol, chip_bins, entry_price)
            if chip_action:
                actions.append(chip_action)

        # --- 8.5 RSI止盈（书本第7章§7.3.2）---
        rsi_val = rsi or indicators.get('rsi', 50)
        if rsi_val >= 85:
            count = self.rsi_high_count.get(symbol, 0) + 1
            self.rsi_high_count[symbol] = count
            if count >= 3:
                actions.append({
                    'action': 'SELL_50',
                    'reason': "RSI止盈(>=85持续{}日)".format(count)
                })
        else:
            self.rsi_high_count[symbol] = 0

        # --- 8.6 放量滞涨止盈（书本第7章§7.3.3）---
        vol_ratio = indicators.get('vol_ratio', 0)
        recent_return = indicators.get('recent_return', 0)
        # 如果indicators中没有recent_return，从价格位置推算
        if recent_return == 0:
            recent_return = abs(indicators.get('pct_chg', 0)) if 'pct_chg' in indicators else 0

        if vol_ratio >= 2.0 and recent_return < 0.005:
            actions.append({
                'action': 'SELL_30',
                'reason': "放量滞涨止盈: 量比{:.2f} 涨幅{:.3f}".format(vol_ratio, recent_return)
            })

        # --- 8.7 移动止盈（书本第7章§7.3.4）---
        if peak > entry_price * 1.05:
            drawdown = (peak - current_price) / peak
            if drawdown > 0.10:
                actions.append({
                    'action': 'SELL_50',
                    'reason': "移动止盈(回撤{:.1f}%>10%): 最高{:.2f} 当前{:.2f}".format(
                        drawdown * 100, peak, current_price)
                })

        return actions

    # ==================== 子方法 ====================

    def _chip_take_profit(self, symbol: str, chip_bins: List[Dict],
                          entry_price: float) -> Optional[Dict]:
        """
        筹码止盈检查（书本第7章§7.3.1）

        条件：低位筹码峰消失（底部30%价格区间筹码比例<10%）
        -> 说明主力已完成出货，减仓70%
        """
        if not chip_bins:
            return None

        prices = [b['price_bin'] for b in chip_bins]
        if not prices:
            return None

        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price
        if price_range <= 0:
            return None

        # 底部30%区间
        low_threshold = min_price + price_range * 0.3
        low_chips = sum(
            b['chip_ratio'] for b in chip_bins
            if b['price_bin'] <= low_threshold
        )

        if low_chips < 0.10:
            return {
                'action': 'SELL_70',
                'reason': "筹码止盈: 低位筹码仅{:.1f}%<10%(主力出货)".format(low_chips * 100)
            }

        return None

    # ==================== 批量检查 ====================

    def execute_batch(
        self,
        portfolio: Dict[str, Dict],
        current_prices: Dict[str, float],
        indicators_map: Dict[str, Dict],
        date_idx: int = 0,
    ) -> Dict[str, List[Dict]]:
        """
        对全部持仓批量执行止损止盈检查

        Args:
            portfolio: 持仓字典 {symbol: {'entry_price': float, 'position': float, ...}}
            current_prices: 当前价格 {symbol: price}
            indicators_map: 筹码指标 {symbol: indicators_dict}
            date_idx: 当前交易日索引

        Returns:
            {symbol: [action, ...]}
        """
        results = {}

        for symbol, pos_info in portfolio.items():
            entry_price = pos_info.get('entry_price', 0)
            current_price = current_prices.get(symbol, 0)
            indicators = indicators_map.get(symbol, {})

            if entry_price <= 0 or current_price <= 0:
                continue

            # 如果还未记录入场，则记录
            if symbol not in self.entry_prices:
                self.set_entry(symbol, entry_price, date_idx)
            else:
                self.entry_prices[symbol] = entry_price

            actions = []

            # 止损
            stop_actions = self.execute_stop_loss(symbol, current_price, date_idx)
            actions.extend(stop_actions)

            # 止盈（如果没有触发止损）
            if not stop_actions or all(a.get('action') != 'SELL_ALL' for a in stop_actions):
                profit_actions = self.check_take_profit(
                    symbol, current_price, indicators,
                    chip_bins=pos_info.get('chip_bins')
                )
                actions.extend(profit_actions)

            if actions:
                results[symbol] = actions

        return results


# === crowding_factor.py ===

class CrowdingFactor:
    """
    拥挤度因子模型

    从三个维度评估股票的筹码拥挤程度：
    1. 融资余额占比（融资余额/流通市值）
    2. 换手率异常（当前换手率 vs 20日均值）
    3. 波动率压缩（布林带宽度 vs 历史分位）

    综合判断结果为 HIGH_CROWDING / MODERATE / LOW_CROWDING。
    """

    HIGH_CROWDING = 'HIGH_CROWDING'
    MODERATE = 'MODERATE'
    LOW_CROWDING = 'LOW_CROWDING'

    def __init__(self):
        self._name = 'CrowdingFactor'

    @property
    def name(self) -> str:
        return self._name

    def calc_margin_ratio(self, ts_code: str) -> Optional[float]:
        """
        计算融资余额占比。
        融资余额占比 = 融资余额 / 流通市值。

        Args:
            ts_code: 股票代码

        Returns:
            Optional[float]: 融资余额占比，数据不可用时返回 None
        """
        try:
            from app.data import DataManager
            dm = DataManager()
            margin_df = dm.get_margin(ts_code)

            if margin_df is None or margin_df.empty:
                return None

            # 取最新一条融资数据
            latest = margin_df.iloc[-1]

            # 尝试获取融资余额和流通市值
            margin_balance = None
            circ_mv = None

            if isinstance(latest, (dict, pd.Series)):
                for col in ('marge_balance', '融资余额', 'marge', 'balance'):
                    if col in latest:
                        try:
                            val = float(latest[col])
                            if pd.notna(val) and val > 0:
                                margin_balance = val
                                break
                        except (ValueError, TypeError, KeyError):
                            continue

                for col in ('circ_mv', '流通市值', 'circulating_mv', 'mv'):
                    if col in latest:
                        try:
                            val = float(latest[col])
                            if pd.notna(val) and val > 0:
                                circ_mv = val
                                break
                        except (ValueError, TypeError, KeyError):
                            continue

            if margin_balance is not None and circ_mv is not None and circ_mv > 0:
                ratio = margin_balance / circ_mv
                return min(1.0, max(0.0, ratio))

            return None

        except Exception:
            return None

    def calc_turnover_crowding(
        self,
        df: pd.DataFrame,
        turnover_data: Optional[pd.Series] = None,
    ) -> str:
        """
        通过换手率评估拥挤度。

        Args:
            df: 行情数据 DataFrame（需含 turnover_rate 或 turn 列）
            turnover_data: 可选的换手率序列，优先使用

        Returns:
            str: 'HIGH_TURNOVER' / 'NORMAL_TURNOVER' / 'LOW_TURNOVER'
        """
        if turnover_data is not None and not turnover_data.empty:
            turn_series = turnover_data
        elif df is not None and not df.empty:
            # 尝试从 df 中获取换手率列
            turn_col = None
            for col in ('turnover_rate', 'turn', 'turnover', '换手率'):
                if col in df.columns:
                    turn_col = col
                    break
            if turn_col is None:
                return 'NORMAL_TURNOVER'
            turn_series = df[turn_col]
        else:
            return 'NORMAL_TURNOVER'

        try:
            # 清理缺失值
            turn_series = turn_series.dropna()
            if len(turn_series) < 5:
                return 'NORMAL_TURNOVER'

            current_turnover = float(turn_series.iloc[-1])
            # 使用最近 20 个交易日计算均值
            lookback = min(20, len(turn_series))
            avg_turnover = float(turn_series.iloc[-lookback:].mean())

            if avg_turnover <= 0:
                return 'NORMAL_TURNOVER'

            ratio = current_turnover / avg_turnover

            if ratio > 1.5:
                return 'HIGH_TURNOVER'
            elif ratio < 0.5:
                return 'LOW_TURNOVER'
            else:
                return 'NORMAL_TURNOVER'

        except Exception:
            return 'NORMAL_TURNOVER'

    def calc_volatility_crowding(self, df: pd.DataFrame) -> str:
        """
        通过波动率（布林带宽度）评估拥挤度。
        压缩窄带 = 潜在的筹码集中（拥挤），
        宽带 = 筹码分散（不拥挤）。

        Args:
            df: 行情数据 DataFrame（需含 close 列，至少 60 个交易日）

        Returns:
            str: 'HIGH_CROWDING' / 'MODERATE_CROWDING' / 'LOW_CROWDING'
        """
        if df is None or df.empty or 'close' not in df.columns:
            return 'MODERATE_CROWDING'

        try:
            close = df['close'].values
            if len(close) < 60:
                return 'MODERATE_CROWDING'

            # 计算 20 日布林带宽度
            bb_widths = []
            for i in range(20, len(close)):
                window = close[i - 20:i]
                mean = np.mean(window)
                std = np.std(window, ddof=1)
                if mean != 0:
                    # 布林带宽度 = (上轨 - 下轨) / 中轨 = 4 * std / mean
                    width = 4.0 * std / mean
                    bb_widths.append(width)

            if len(bb_widths) < 40:
                return 'MODERATE_CROWDING'

            # 当前带宽
            current_width = bb_widths[-1]

            # 历史分位（取最近 60 个交易日的历史窗口）
            history_window = bb_widths[:]
            p20 = np.percentile(history_window, 20)
            p80 = np.percentile(history_window, 80)

            if current_width < p20:
                return 'HIGH_CROWDING'
            elif current_width > p80:
                return 'LOW_CROWDING'
            else:
                return 'MODERATE_CROWDING'

        except Exception:
            return 'MODERATE_CROWDING'

    def evaluate(
        self,
        ts_code: str,
        df: pd.DataFrame,
        market_context: Optional[Dict] = None,
    ) -> Dict:
        """
        综合评估股票筹码拥挤度。

        规则：
        - 至少满足 2/3 条件（高融资比 / 高换手 / 低波动）= HIGH_CROWDING
        - 至少满足 2/3 条件（低融资比 / 低换手 / 高波动）= LOW_CROWDING
        - 否则 MODERATE

        Args:
            ts_code: 股票代码
            df: 行情数据 DataFrame
            market_context: 市场上下文（可选）

        Returns:
            Dict: {
                'crowding_level': str,
                'crowding_score': float,       # 0-1，越高越拥挤
                'risk_advice': str,
                'details': dict,
            }
        """
        details: Dict = {}
        evidence: List[str] = []

        # 1. 融资余额占比
        margin_ratio = None
        try:
            margin_ratio = self.calc_margin_ratio(ts_code)
        except Exception:
            pass

        margin_signals = {'high': False, 'low': False}
        if margin_ratio is not None:
            details['margin_ratio'] = round(margin_ratio, 6)
            # 融资余额 > 流通市值 5% 视为偏高
            if margin_ratio > 0.05:
                margin_signals['high'] = True
                evidence.append(f'融资余额占比 {margin_ratio:.4%} > 5%，偏高')
            elif margin_ratio < 0.01:
                margin_signals['low'] = True
                evidence.append(f'融资余额占比 {margin_ratio:.4%} < 1%，偏低')
            else:
                evidence.append(f'融资余额占比 {margin_ratio:.4%}，适中')
        else:
            details['margin_ratio'] = None
            evidence.append('融资数据不可用')

        # 2. 换手率拥挤
        turnover_data = None
        if market_context:
            turnover_data = market_context.get('turnover_data', None)

        turnover_state = 'NORMAL_TURNOVER'
        try:
            turnover_state = self.calc_turnover_crowding(df, turnover_data)
        except Exception:
            pass

        turnover_signals = {'high': False, 'low': False}
        details['turnover_state'] = turnover_state
        if turnover_state == 'HIGH_TURNOVER':
            turnover_signals['high'] = True
            evidence.append('换手率偏高（> 20日均值1.5倍），筹码集中')
        elif turnover_state == 'LOW_TURNOVER':
            turnover_signals['low'] = True
            evidence.append('换手率偏低（< 20日均值0.5倍），筹码分散')
        else:
            evidence.append('换手率正常')

        # 3. 波动率拥挤
        vol_state = 'MODERATE_CROWDING'
        try:
            vol_state = self.calc_volatility_crowding(df)
        except Exception:
            pass

        vol_signals = {'high': False, 'low': False}
        details['volatility_state'] = vol_state
        if vol_state == self.HIGH_CROWDING:
            vol_signals['high'] = True
            evidence.append('波动率压缩（布林带窄），筹码可能集中')
        elif vol_state == self.LOW_CROWDING:
            vol_signals['low'] = True
            evidence.append('波动率扩张（布林带宽），筹码分散')
        else:
            evidence.append('波动率正常')

        # 4. 综合判定
        high_count = sum([margin_signals['high'], turnover_signals['high'], vol_signals['high']])
        low_count = sum([margin_signals['low'], turnover_signals['low'], vol_signals['low']])

        # 有效信号计数（排除数据不可用的维度）
        valid_signals = sum([
            1 if margin_ratio is not None else 0,
            1,  # 换手率总有结果
            1,  # 波动率总有结果
        ])

        if valid_signals < 3:
            evidence.append(f'有效信号维度数 {valid_signals}/3')

        # 至少 2/3 的拥挤信号
        if high_count >= 2 and valid_signals >= 2:
            crowding_level = self.HIGH_CROWDING
            crowding_score = 0.7 + 0.1 * min(high_count, 3)
            risk_advice = '拥挤度高，建议谨慎参与，注意回调风险'
        # 至少 2/3 的低拥挤信号
        elif low_count >= 2 and valid_signals >= 2:
            crowding_level = self.LOW_CROWDING
            crowding_score = 0.1 + 0.1 * max(0, 2 - low_count)
            risk_advice = '拥挤度低，可关注介入机会'
        else:
            crowding_level = self.MODERATE
            crowding_score = 0.5
            risk_advice = '拥挤度适中，正常关注'

        details['margin_signals'] = margin_signals
        details['turnover_signals'] = turnover_signals
        details['volatility_signals'] = vol_signals
        details['valid_signals'] = valid_signals
        details['evidence'] = evidence

        # 裁剪 crowding_score 到 [0, 1]
        crowding_score = max(0.0, min(1.0, crowding_score))

        return {
            'crowding_level': crowding_level,
            'crowding_score': round(crowding_score, 4),
            'risk_advice': risk_advice,
            'details': details,
        }


# === tag_extractor.py ===

def extract_chanlun_deep_tags(ts_code: str) -> dict:
    """从 strategy_signal_detail 缠论信号提取深度字段（缠论结构组）

    Returns:
        {support_resistance: JSON, zhongshu_strength: str, multi_level: JSON,
         near_levels_filtered: JSON, active_signal: str, active_signal_label: str,
         level_upper_limit: str, momentum: JSON, state_label: str, risk_level: str}
        信号缺失时返回空 dict。
    """
    try:
        dm = DataManager()
        cached = dm.cache.get_latest_signal_detail(ts_code)
        if not cached:
            return {}
        signals = cached.get('signals', {})
        chanlun = None
        for name, s in signals.items():
            if '缠论' in name:
                chanlun = s
                break
        if not chanlun:
            return {}
        sr = chanlun.get('status_recognition', {})
        out = {}
        # 缠论结构深度字段（structure 组）
        # 2026-08-10 核查修复：None 值跳过（原 str(None) 产生字面 "None" 假值）
        def _mk(v, is_json=False):
            if v is None:
                return None
            return (json.dumps(v, ensure_ascii=False) if is_json else str(v))
        if 'support_resistance' in sr:
            _v = _mk(sr['support_resistance'], is_json=True)
            if _v is not None:
                out['support_resistance'] = _v
        if 'zhongshu_strength' in sr:
            _v = _mk(sr['zhongshu_strength'])
            if _v is not None:
                out['zhongshu_strength'] = _v
        if 'multi_level' in sr:
            _v = _mk(sr['multi_level'], is_json=True)
            if _v is not None:
                out['multi_level'] = _v
        if 'near_levels_filtered' in sr:
            _v = _mk(sr['near_levels_filtered'], is_json=True)
            if _v is not None:
                out['near_levels_filtered'] = _v
        if 'active_signal' in sr:
            _v = _mk(sr['active_signal'])
            if _v is not None:
                out['active_signal'] = _v
        if 'active_signal_label' in sr:
            _v = _mk(sr['active_signal_label'])
            if _v is not None:
                out['active_signal_label'] = _v
        if 'level_upper_limit' in sr:
            _v = _mk(sr['level_upper_limit'])
            if _v is not None:
                out['level_upper_limit'] = _v
        if 'momentum' in sr:
            _v = _mk(sr['momentum'], is_json=True)
            if _v is not None:
                out['momentum'] = _v
        if 'state_label' in sr:
            _v = _mk(sr['state_label'])
            if _v is not None:
                out['state_label'] = _v
        if 'risk_level' in sr:
            _v = _mk(sr['risk_level'])
            if _v is not None:
                out['risk_level'] = _v
        return out
    except Exception as e:
        logger.debug(f"extract_chanlun_deep_tags 失败 ({ts_code}): {e}")
        return {}


def extract_chip_deep_tags(ts_code: str) -> dict:
    """独立提取筹码深度字段（筹码分布组）——不依赖 phase_detector

    直接调用 ChipDistributionEstimator + ChipIndicators 计算筹码指标，
    产出 asr/cyqkl/concentration/profit_ratio/ssrp/chip_peak 等深度字段。

    重构依据：357号方案决策1（深度字段解耦），消除对 phase_detector._last_chip_indicators 的依赖。

    Returns:
        {chip_peak, asr, cyqkl, concentration, profit_ratio, ssrp, ...}
        计算失败时返回空 dict。
    """
    try:
        from app.data import DataManager
        dm = DataManager()
        df = dm.get_cached_daily_data(ts_code)
        if df is None or df.empty or len(df) < 30:
            return {}

        # 1. 估算筹码分布（使用内部定义的 ChipDistributionEstimator）
        estimator = ChipDistributionEstimator()
        chip_dist, min_p, max_p, step = estimator.estimate(df)
        if step <= 0:
            return {}

        # 2. 构建 chip_bins
        total = chip_dist.sum() or 1
        chip_bins = [
            {"price_bin": round(min_p + i * step, 2),
             "chip_ratio": float(chip_dist[i] / total)}
            for i in range(len(chip_dist))
        ]

        # 3. 计算筹码指标
        chip_inds = ChipIndicators()
        current_price = float(df["close"].values[-1])
        ind = chip_inds.calculate_all_indicators(
            chip_bins, current_price, kline_data=df
        ) or {}

        # 4. 提取深度字段
        out = {}
        if 'main_peak' in ind and isinstance(ind['main_peak'], dict):
            pk_price = ind['main_peak'].get('price')
            if pk_price is not None:
                try:
                    out['chip_peak'] = str(round(float(pk_price), 2))
                except (TypeError, ValueError):
                    pass
        for key in ('asr', 'cyqkl', 'concentration', 'profit_ratio', 'ssrp',
                    'sandwich_zone', 'retail_vs_institutional',
                    'sentiment_crowding', 'sentiment_crowding_label', 'fake_institution',
                    'asr_status', 'concentration_status', 'cyqkl_status',
                    'peak_count', 'peak_type', 'avg_vol_100', 'vol_ratio'):
            if key in ind and ind[key] is not None:
                val = ind[key]
                out[key] = (json.dumps(val, ensure_ascii=False)
                            if isinstance(val, (dict, list)) else str(val))
        return out
    except Exception as e:
        logger.debug(f"extract_chip_deep_tags 失败 ({ts_code}): {e}")
        return {}


# 深度字段 → tag_group 映射（323号 §二 2.2/2.1 清单校准）
DEEP_TAG_GROUPS = {
    # structure 组（缠论结构）
    'support_resistance': 'structure', 'zhongshu_strength': 'structure',
    'multi_level': 'structure', 'near_levels_filtered': 'structure',
    'active_signal': 'structure', 'active_signal_label': 'structure',
    'level_upper_limit': 'structure', 'momentum': 'structure',
    'state_label': 'structure',
    # chip_deep 组（筹码分布）
    'chip_peak': 'chip_deep', 'asr': 'chip_deep', 'cyqkl': 'chip_deep',
    'concentration': 'chip_deep', 'profit_ratio': 'chip_deep', 'ssrp': 'chip_deep',
    'sandwich_zone': 'chip_deep',
    'retail_vs_institutional': 'chip_deep', 'sentiment_crowding': 'chip_deep',
    'sentiment_crowding_label': 'chip_deep', 'fake_institution': 'chip_deep',
    'asr_status': 'chip_deep', 'concentration_status': 'chip_deep', 'cyqkl_status': 'chip_deep',
    'peak_count': 'chip_deep', 'peak_type': 'chip_deep',
    'avg_vol_100': 'chip_deep', 'vol_ratio': 'chip_deep',
    # fund_risk 组（资金/风险）
    'net_lg_amount_5d': 'fund_risk', 'margin_cost_price': 'fund_risk',
    'risk_level': 'fund_risk',
}


def extract_fund_risk_tags(ts_code: str) -> dict:
    """提取资金/风险深度字段（fund_risk 组）

    2026-08-10 325档案修复：弃用 P2 筹码信号路径（覆盖仅 0.77% 致组近空），
    改从 ECM 全市场表直接提取：
    - net_lg_amount_5d：moneyflow_cache 近5日 net_lg_amount 求和（覆盖 5558 只）
    - margin_cost_price：margin_cache rzmje(融资买入额) 加权成本价（覆盖 4414 只）
    Returns: {net_lg_amount_5d, margin_cost_price}，缺失返回空 dict。
    """
    try:
        dm = DataManager()
        out = {}
        # net_lg_amount_5d：moneyflow_cache 近5日大单净额求和
        try:
            mf = dm.cache.get_cached_moneyflow(ts_code)
            if mf is not None and not mf.empty and 'net_lg_amount' in mf.columns:
                net5 = mf['net_lg_amount'].dropna().tail(5).sum()
                if abs(net5) > 0:
                    out['net_lg_amount_5d'] = str(round(float(net5), 2))
        except Exception:
            pass
        # margin_cost_price：margin_cache rzmje 加权均价（近60日融资买入日）
        try:
            margin_df = dm.get_cached_margin(ts_code)
            if margin_df is not None and not margin_df.empty and 'rzmje' in margin_df.columns:
                _df = margin_df.tail(60)
                _buy = _df[_df['rzmje'].fillna(0) > 0]
                if len(_buy) >= 3:
                    # margin 表无 K 线列——用 daily_cache 收盘价近似当日均价
                    _k = dm.get_cached_daily_data(ts_code)
                    _close_map = {}
                    if _k is not None and not _k.empty and 'trade_date' in _k.columns:
                        _close_map = dict(zip(_k['trade_date'].astype(str), _k['close']))
                    _weights = []
                    _prices = []
                    for _i, _row in _buy.iterrows():
                        _w = float(_row.get('rzmje') or 0)
                        if _w <= 0:
                            continue
                        _p = _close_map.get(str(_row.get('trade_date')))
                        if _p is None:
                            continue
                        _weights.append(_w)
                        _prices.append(float(_p))
                    if len(_weights) >= 3 and sum(_weights) > 0:
                        out['margin_cost_price'] = str(round(
                            sum(w * p for w, p in zip(_weights, _prices)) / sum(_weights), 2))
        except Exception:
            pass
        return out
    except Exception as e:
        logger.debug(f"extract_fund_risk_tags 失败 ({ts_code}): {e}")
        return {}

# ═══════════════════════════════════════════════════════════
# 第4维 引擎
# ═══════════════════════════════════════════════════════════

def _assess_phase(tags, dims):
    mfp = str(tags.get('main_force_phase', ''))
    pm = {'building': ('建仓期', '低位吸筹'), 'washing': ('洗盘期', '清洗浮筹'),
          'raising': ('拉升期', '快速上涨'), 'distributing': ('出货期', '高位派发'), 'support': ('护盘期', '支撑维护')}
    if mfp in pm:
        cn, desc = pm[mfp]
        light = 'green' if mfp in ('building', 'raising') else ('red' if mfp == 'distributing' else 'yellow')
        return {'phase': mfp, 'phase_cn': cn, 'detail': desc, 'light': light}
    return {'phase': 'unknown', 'phase_cn': '未知', 'detail': '主力阶段数据缺失', 'light': 'yellow'}

def _assess_fund_flow(tags):
    ff = str(tags.get('fund_flow', ''))
    if ff == '5d_inflow': return {'level': 'strong', 'level_cn': '强流入', 'direction': 'inflow', 'detail': '大单5日净流入'}
    elif ff == '5d_outflow': return {'level': 'strong_out', 'level_cn': '强流出', 'direction': 'outflow', 'detail': '大单5日净流出'}
    return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '无明确资金流向'}

def _assess_cost_structure(tags):
    """成本分布结构（Wiki筹码分布知识库验证）

    增强：ASR（活跃筹码比率）+ CYQKL（筹码穿透力）+ profit_ratio 综合评估
    """
    parts = []
    c = str(tags.get('chip_concentration', ''))
    if c: parts.append(f"筹码{c}")

    # ASR（活跃筹码比率）：Wiki定义 - 衡量筹码活跃程度
    asr = tags.get('asr')
    asr_val = None
    if asr is not None:
        try:
            asr_val = float(asr)
            parts.append(f"ASR={asr_val:.0f}")
        except: pass

    # CYQKL（筹码穿透力指标）：Wiki定义 - 衡量价格穿透筹码的能力
    cyqkl = tags.get('cyqkl')
    if cyqkl is not None:
        try:
            cyqkl_val = float(cyqkl)
            parts.append(f"CYQKL={cyqkl_val:.1f}")
        except: pass

    pr = tags.get('profit_ratio')
    if pr is not None:
        try: parts.append(f"获利盘{float(pr):.0%}")
        except: pass

    # 资金筹码质量评估（综合ASR+CYQKL）
    quality = '中性'
    if asr_val is not None:
        if asr_val > 80:
            quality = '活跃'  # 高ASR → 筹码活跃度高
        elif asr_val < 30:
            quality = '沉寂'  # 低ASR → 筹码沉寂

    return {'detail': '，'.join(parts) if parts else '筹码数据不足',
            'concentration': c, 'quality': quality}

def _assess_signal(tags):
    bsp = str(tags.get('buy_sell_point', ''))
    sm = {'first_buy': '一买信号', 'second_buy': '二买信号', 'third_buy': '三买信号', 'first_sell': '一卖信号', 'second_sell': '二卖信号'}
    if bsp in sm: return {'detail': sm[bsp], 'signal': bsp}
    return {'detail': '无明确筹码信号', 'signal': 'none'}

def _assess_retail_institution(tags):
    mfp = str(tags.get('main_force_phase', ''))
    ff = str(tags.get('fund_flow', ''))
    if mfp == 'building' and ff == '5d_inflow': return {'detail': '主力建仓+资金流入（机构买入）'}
    elif mfp == 'distributing': return {'detail': '主力出货（抛压风险）'}
    return {'detail': '散户与机构博弈中性'}

def _assess_margin(tags):
    mc = tags.get('margin_change_5d')
    if mc is not None:
        try:
            mc = float(mc)
            if mc > 10: return {'detail': f'融资余额5日增加{mc:.0f}%（散户杠杆在上升）'}
            elif mc < -10: return {'detail': f'融资余额5日减少{abs(mc):.0f}%（散户在去杠杆）'}
            else: return {'detail': f'融资余额5日变化{mc:+.0f}%（正常范围）'}
        except: pass
    return {'detail': '融资数据不足'}

def _fund_chip_plain(phase, fund_flow, cost, signal, retail_inst, margin):
    parts = []
    pn = phase.get('phase', 'unknown')
    if pn == 'building': parts.append(f'大资金在逐步建仓（{phase.get("detail", "")}）')
    elif pn == 'raising': parts.append(f'主力正在拉升（{phase.get("detail", "")}）')
    elif pn == 'washing': parts.append('主力在洗盘（清洗浮筹）')
    elif pn == 'distributing': parts.append('主力在高位派发（出货风险）')
    fd = fund_flow.get('direction', '')
    if fd == 'inflow': parts.append(f'资金净流入（{fund_flow.get("detail", "")}）')
    elif fd == 'outflow': parts.append(f'资金净流出（{fund_flow.get("detail", "")}）')
    cd = cost.get('detail', '')
    if cd and '数据不足' not in cd: parts.append(f'筹码{cost.get("concentration", "")}（{cd}）')
    md = margin.get('detail', '')
    if md and '数据不足' not in md: parts.append(md)
    return '，'.join(parts) if parts else '资金筹码数据不足，无法判断主力动向'


class Dim4ChipFundEngine(DataAwareMixin):
    """第4维 资金筹码引擎 — 阶段判定 + 6信号 + 拥挤度 + 标签提取"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims, tags, signals=None, lifecycle=None):
        phase_info = _assess_phase(tags, dims)
        fund_flow_info = _assess_fund_flow(tags)
        cost_structure = _assess_cost_structure(tags)
        signal_info = _assess_signal(tags)
        retail_inst = _assess_retail_institution(tags)
        margin_info = _assess_margin(tags)

        # PhaseDetectionEngine 真实阶段分析（如果df可用）
        ts_code = tags.get('ts_code', '')
        phase_engine_result = None
        try:
            ecm = self._get_dm().cache
            if ts_code:
                df = ecm.get_cached_daily(ts_code)
                if df is not None and not df.empty and len(df) >= 30:
                    pde = PhaseDetectionEngine()
                    phase_engine_result = pde.compute_tags(ts_code, df)
                    # 用引擎结果覆盖tags读取的阶段判定
                    if phase_engine_result and phase_engine_result.get('main_force_phase') != 'unknown':
                        phase_info = {
                            'phase': phase_engine_result['main_force_phase'],
                            'phase_cn': PHASE_MAP.get(phase_engine_result['main_force_phase'], {}).get('name', phase_engine_result['main_force_phase']),
                            'detail': f"PhaseDetector分析（置信度{phase_engine_result.get('phase_confidence', 0):.2f}）",
                            'light': 'green' if phase_engine_result['main_force_phase'] in ('building', 'raising') else ('red' if phase_engine_result['main_force_phase'] == 'distributing' else 'yellow'),
                        }
                    if phase_engine_result and phase_engine_result.get('fund_flow') != 'none':
                        ff = phase_engine_result['fund_flow']
                        fund_flow_info = {
                            'level': 'strong' if 'inflow' in ff else 'strong_out',
                            'level_cn': '强流入' if 'inflow' in ff else '强流出',
                            'direction': 'inflow' if 'inflow' in ff else 'outflow',
                            'detail': f"PhaseDetector资金流向={ff}",
                        }

        except Exception as e:
            logger.debug(f"PhaseDetectionEngine调用跳过: {e}")

        # 拥挤度（真实计算）
        crowding = {'level': 'unknown', 'detail': '拥挤度数据不足', 'score': 0.5}
        try:
            if ts_code:
                df = ecm.get_cached_daily(ts_code) if not phase_engine_result else df
                if df is not None and not df.empty:
                    cf = CrowdingFactor()
                    cr = cf.evaluate(ts_code, df)
                    crowding = {'level': cr.get('crowding_level', 'MODERATE_CROWDING'), 'detail': cr.get('risk_advice', ''),
                                 'score': cr.get('crowding_score', 0.5)}
        except: pass

        plain = _fund_chip_plain(phase_info, fund_flow_info, cost_structure, signal_info, retail_inst, margin_info)
        status_description = {
            'phase': f"{phase_info['phase_cn']}（{phase_info['detail']}）",
            'fund_flow': f"{fund_flow_info['level_cn']}（{fund_flow_info['detail']}）",
            'cost_structure': cost_structure['detail'], 'signal': signal_info['detail'],
            'retail_institution': retail_inst['detail'], 'margin': margin_info['detail'],
            'crowding': f"拥挤度={crowding['level']}（{crowding['detail']}）",
            'plain': plain,
        }
        judgment = {
            'phase': phase_info['phase'], 'direction': fund_flow_info['direction'], 'light': phase_info['light'],
            'overall_light': phase_info['light'],
            'overall_direction': 1 if phase_info['phase'] in ('building', 'raising') else (-1 if phase_info['phase'] == 'distributing' else 0),
            'continuous_value': round(1.0 - crowding.get('score', 0.5), 4),  # P2: 拥挤度越低越好 [0,1]
        }
        conditions = [
            {'name': '主力阶段', 'satisfied': bool(phase_info['phase']), 'actual': phase_info['phase_cn'], 'threshold': '有明确阶段判定'},
            {'name': '资金流向', 'satisfied': fund_flow_info['level'] != 'none', 'actual': fund_flow_info['level_cn'], 'threshold': '有明确流向'},
            {'name': '筹码集中', 'satisfied': bool(cost_structure.get('concentration')), 'actual': cost_structure.get('concentration', '未知') or '未知', 'threshold': '有集中度数据'},
            {'name': '拥挤度合理', 'satisfied': crowding['level'] not in ('HIGH_CROWDING', 'unknown'), 'actual': crowding['level'], 'threshold': '非高拥挤'},
        ]
        sc = sum(1 for c in conditions if c['satisfied'])
        audit = {'conditions': conditions, 'satisfied_count': sc, 'total_count': len(conditions), 'confidence': sc / len(conditions) if conditions else 0}
        return {'status_description': status_description, 'judgment': judgment, 'audit': audit}

    def get_data_dependencies(self):
        return ['tags (pre_feat_cache)', 'dims (StatusEngine)', 'daily_cache (market_cache.db)', 'moneyflow_cache (market_cache.db)']
