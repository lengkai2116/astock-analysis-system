"""
量价分析策略 — 完整实现（v3 + P0~P2 优化）
基于 v3 深化设计报告（143号文档）+ 优化评估报告（145号文档）

分析逻辑链（不可逆）:
  Phase 1: 波段四阶段判定 + 三周期价格分位校准
  Phase 2: 成交量状态 + 主力入市阶段推断
  Phase 3: 量价关系分析 + 多空动量评估
  Phase 4: 四维信号校准 + 右侧交易过滤

v3+ 优化（145号报告）:
  P0: 大盘环境过滤 / 动态仓位(R乘数) / 换手率优先量能
  P1: 50种形态择优选入 / MACD双重确认背离 / 多形态共振评分
  P2: 动态止盈(空间目标) / 关键位入场校准

数据依赖: 仅需 OHLCV 日线数据（无需 Level-2）
"""
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, date
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 数据类定义
# ──────────────────────────────────────────────

@dataclass
class ValuationZones:
    """三周期价格分位"""
    short_30d: float = 0.5
    mid_60d: float = 0.5
    long_120d: float = 0.5
    zone: str = "MID"

    @property
    def composite(self) -> float:
        return self.short_30d * 0.5 + self.mid_60d * 0.3 + self.long_120d * 0.2

    @property
    def zone_label(self) -> str:
        return ZONE_LABELS.get(self.zone, "MID")

    def to_dict(self) -> Dict:
        return {
            "short_30d": round(self.short_30d, 4),
            "mid_60d": round(self.mid_60d, 4),
            "long_120d": round(self.long_120d, 4),
            "composite": round(self.composite, 4),
            "zone": self.zone,
            "zone_label": self.zone_label,
        }


@dataclass
class InstitutionalPhase:
    """主力入市阶段推断"""
    phase: str = "UNKNOWN"
    confidence: float = 0.0
    scores: Dict[str, float] = field(default_factory=dict)
    interpretation: str = ""

    def to_dict(self) -> Dict:
        return {
            "likely_phase": self.phase,
            "confidence": round(self.confidence, 4),
            "scores": {k: round(v, 2) for k, v in self.scores.items()},
            "interpretation": self.interpretation,
        }


@dataclass
class MomentumProfile:
    """多空动量评估"""
    score: float = 0.0
    level: str = "NEUTRAL"
    candle_force: str = ""
    volume_direction: str = ""
    price_accel: str = ""
    interpretation: str = ""

    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 4),
            "level": self.level,
            "candle_force": self.candle_force,
            "volume_direction": self.volume_direction,
            "price_accel": self.price_accel,
            "interpretation": self.interpretation,
        }


@dataclass
class Stage:
    """阶段状态"""
    name: str = "CONSOLIDATION"
    confidence: float = 0.0
    valuation: Optional[ValuationZones] = None
    trend_structure: str = ""
    ma_alignment: str = ""
    note: str = ""

    def to_dict(self) -> Dict:
        return {
            "current_stage": self.name,
            "confidence": round(self.confidence, 4),
            "trend_structure": self.trend_structure,
            "ma_alignment": self.ma_alignment,
            "note": self.note,
            "aux_price_position": self.valuation.to_dict() if self.valuation else {},
        }


@dataclass
class VolumeState:
    """成交量状态"""
    trend: str = "STABLE"
    volma_structure: str = "MIXED"
    has_volume_tuo: bool = False
    has_volume_ya: bool = False
    volume_keypoints: List[float] = field(default_factory=list)
    institutional: Optional[InstitutionalPhase] = None

    def to_dict(self) -> Dict:
        return {
            "volume_trend": self.trend,
            "volma_structure": self.volma_structure,
            "has_volume_tuo": self.has_volume_tuo,
            "has_volume_ya": self.has_volume_ya,
            "volume_keypoints": [round(k, 2) for k in self.volume_keypoints],
            "aux_institutional_inference": self.institutional.to_dict() if self.institutional else {},
        }


@dataclass
class RelationResult:
    """量价关系分析结果"""
    pattern_id: str = ""
    pattern_name: str = ""
    enhance_patterns: List[str] = field(default_factory=list)
    divergence_type: str = ""
    divergence_confidence: float = 0.0
    divergence_macd_confirmed: bool = False
    cross_matrix_note: str = ""
    momentum: Optional[MomentumProfile] = None
    resonance_score: int = 0

    def to_dict(self) -> Dict:
        return {
            "current_pattern": f"{self.pattern_id} {self.pattern_name}" if self.pattern_id else "",
            "enhance_patterns": self.enhance_patterns,
            "divergence": self.divergence_type if self.divergence_type != "none" else "无",
            "divergence_macd_confirmed": self.divergence_macd_confirmed,
            "resonance_score": self.resonance_score,
            "aux_momentum": self.momentum.to_dict() if self.momentum else {},
        }


@dataclass
class VolumePriceSignal:
    """最终输出信号"""
    signal_id: str = ""
    direction: str = "HOLD"
    confidence: float = 0.0
    signal_label: str = ""
    entry_zone: Tuple[float, float] = (0.0, 0.0)
    risk_line: float = 0.0
    target_zone: Tuple[float, float] = (0.0, 0.0)
    position_suggestion: str = "0%"
    position_detail: str = ""
    holding_period: str = ""
    evidence: List[str] = field(default_factory=list)
    risk_notes: List[str] = field(default_factory=list)

    def to_output_dict(self, ts_code: str) -> Dict:
        return {
            "strategy_name": "量价分析策略",
            "signal": self._map_signal(),
            "signal_label": self.signal_label,
            "confidence": round(self.confidence, 2),
            "entry_zone": [round(self.entry_zone[0], 2), round(self.entry_zone[1], 2)],
            "risk_line": round(self.risk_line, 2),
            "target_zone": [round(self.target_zone[0], 2), round(self.target_zone[1], 2)],
            "position_suggestion": self.position_suggestion,
            "position_detail": self.position_detail,
            "holding_period": self.holding_period,
            "evidence": self.evidence,
            "risk_notes": self.risk_notes,
        }

    def _map_signal(self) -> str:
        mapping = {"BUY": "BULLISH", "SELL": "BEARISH", "WATCH": "WATCH", "HOLD": "NEUTRAL"}
        return mapping.get(self.direction, "NEUTRAL")


# ──────────────────────────────────────────────
# 常量定义
# ──────────────────────────────────────────────

STAGE_NAMES = {
    "UPTREND_ACTIVE": "多头上涨", "UPTREND_TOPPING": "多头触顶",
    "DOWNTREND_ACTIVE": "空头下跌", "DOWNTREND_BOTTOMING": "空头探底",
    "CONSOLIDATION": "横盘整理",
}
ZONE_LABELS = {"HIGH": "高位区", "MID_HIGH": "中高位区", "MID": "中位区", "MID_LOW": "中低位区", "LOW": "低位区"}
INST_PHASE_LABELS = {"BUILDING": "建仓期", "WASHING": "洗盘期", "RAISING": "拉升期", "SHIPPING": "出货期", "UNKNOWN": "不确定"}
VP_PATTERNS = {"VP-1": "价涨量增", "VP-2": "价涨量平", "VP-3": "价涨量缩", "VP-4": "价平量增",
               "VP-5": "价平量平", "VP-6": "价平量减", "VP-7": "价跌量增", "VP-8": "价跌量平", "VP-9": "价跌量缩"}

# 阶段×量价交叉矩阵
CROSS_MATRIX = {
    ("UPTREND_ACTIVE", "VP-1"): ("强烈买入", 0.80), ("UPTREND_ACTIVE", "VP-2"): ("温和买入", 0.65),
    ("UPTREND_ACTIVE", "VP-3"): ("动力不足，警告", 0.45), ("UPTREND_ACTIVE", "VP-9"): ("健康回调", 0.60),
    ("UPTREND_TOPPING", "VP-1"): ("最后疯狂", 0.40), ("UPTREND_TOPPING", "VP-3"): ("顶背离预警", 0.55),
    ("UPTREND_TOPPING", "VP-4"): ("放量滞涨", 0.60), ("UPTREND_TOPPING", "VP-7"): ("趋势反转预警", 0.55),
    ("DOWNTREND_ACTIVE", "VP-7"): ("恐慌抛售", 0.70), ("DOWNTREND_ACTIVE", "VP-8"): ("阴跌持续", 0.55),
    ("DOWNTREND_ACTIVE", "VP-9"): ("下跌衰竭", 0.50), ("DOWNTREND_ACTIVE", "VP-1"): ("反弹诱多", 0.40),
    ("DOWNTREND_BOTTOMING", "VP-9"): ("底部确认", 0.65), ("DOWNTREND_BOTTOMING", "VP-4"): ("关注转势", 0.55),
    ("DOWNTREND_BOTTOMING", "VP-1"): ("试探建仓", 0.55),
    ("CONSOLIDATION", "VP-6"): ("变盘前兆", 0.50), ("CONSOLIDATION", "VP-4"): ("方向选择", 0.50),
}

# 基础信号表
SIGNAL_TABLE = [
    ("UPTREND_ACTIVE", ["VP-1"], "VP_TREND", "BUY", 0.75),
    ("UPTREND_ACTIVE", ["VP-9"], "VP_PULLBACK", "BUY", 0.65),
    ("UPTREND_ACTIVE", ["VP-1", "VP-2"], "VP_BREAKOUT", "BUY", 0.75),
    ("UPTREND_ACTIVE", ["VP-3"], "VP_WEAKENING", "WATCH", 0.55),
    ("UPTREND_TOPPING", ["VP-3"], "VP_DIV_TOP", "WATCH", 0.65),
    ("UPTREND_TOPPING", ["VP-4"], "VP_STAGNATION", "WATCH", 0.60),
    ("UPTREND_TOPPING", ["VP-7", "VP-8"], "VP_TOPPING", "WATCH", 0.60),
    ("DOWNTREND_ACTIVE", ["VP-7"], "VP_PANIC", "SELL", 0.70),
    ("DOWNTREND_ACTIVE", ["VP-7", "VP-8"], "VP_BREAKDOWN", "SELL", 0.70),
    ("DOWNTREND_BOTTOMING", ["VP-9"], "VP_DIV_BOT", "WATCH", 0.60),
    ("DOWNTREND_BOTTOMING", ["VP-6", "VP-9"], "VP_BOTTOMING", "WATCH", 0.55),
    ("DOWNTREND_BOTTOMING", ["VP-1"], "VP_REVERSAL", "WATCH", 0.60),
    ("CONSOLIDATION", ["VP-5", "VP-6"], "VP_SQUEEZE", "HOLD", 0.50),
]

# P0优化: 大盘环境权重 (未检测到时默认1.0)
DEFAULT_MARKET_MULTIPLIER = 1.0


# ══════════════════════════════════════════════
# P0: 通用辅助工具
# ══════════════════════════════════════════════

def get_best_volume_series(df: pd.DataFrame) -> np.ndarray:
    """
    [P0-优化3] 获取最佳量能序列
    优先顺序: amount(成交额) > turnover_rate×close(换手率估算) > vol(成交量)
    克服送转股导致的成交量失真
    """
    if 'amount' in df.columns:
        return df['amount'].astype(float).values
    if 'vol' in df.columns:
        return df['vol'].astype(float).values
    if 'volume' in df.columns:
        return df['volume'].astype(float).values
    return np.ones(len(df))


def calc_macd(closes: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算MACD: 返回 (dif, dea, macd_hist)"""
    if len(closes) < 26:
        return np.zeros(len(closes)), np.zeros(len(closes)), np.zeros(len(closes))
    s = pd.Series(closes)
    ema12 = s.ewm(span=12).mean().values
    ema26 = s.ewm(span=26).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9).mean().values
    macd_hist = 2 * (dif - dea)
    return dif, dea, macd_hist


# ══════════════════════════════════════════════
# P0: 动态仓位管理器（R乘数）
# ══════════════════════════════════════════════

class PositionManager:
    """
    [P0-优化2] 基于R乘数的动态仓位管理
    公式: 仓位比例 = 账户风险比率 / 个股风险比率
    个股风险R = |入场价 - 止损价| / 入场价
    """

    def __init__(self, account_risk: float = 0.02, max_position: float = 0.30):
        self.account_risk = account_risk
        self.max_position = max_position

    def calc_position(self, entry_price: float, risk_line: float,
                      direction: str, volatility: Optional[float] = None) -> Tuple[str, str]:
        """
        返回: (仓位百分比字符串, 计算明细)
        """
        if direction not in ("BUY",):
            return "0%", "非买入信号"

        if risk_line <= 0 or entry_price <= 0:
            return "10%", "默认仓位(风控数据不足)"

        stop_loss_pct = abs(entry_price - risk_line) / entry_price
        if stop_loss_pct <= 0.001:
            return "10%", "默认仓位(止损过窄)"

        base_pos = self.account_risk / stop_loss_pct

        # 波动率修正: 高波动自动减仓
        if volatility is not None and volatility > 0.03:
            vol_factor = min(1.0, 0.03 / volatility)
            base_pos *= vol_factor

        pos = min(base_pos, self.max_position)
        pct = int(pos * 100)
        detail_parts = []
        detail_parts.append(f"R乘数={self.account_risk:.1%}/{stop_loss_pct:.1%}={pos:.0%}")
        if volatility is not None and volatility > 0.03:
            detail_parts.append(f"波动修正(vol={volatility:.1%})")
        detail_parts.append(f"上限{self.max_position:.0%}")

        return f"{pct}%", " | ".join(detail_parts)


# ══════════════════════════════════════════════
# P1: 增强形态检测器（50种量价形态速查表）
# ══════════════════════════════════════════════

class EnhancedPatternDetector:
    """
    [154-批1] 50种量价形态规则引擎 — 12条纯OHLCV规则
    参考: 154号方案批1候选规则
    """

    def _safe_len(self, *arrays, min_len=5) -> bool:
        return all(len(a) >= min_len for a in arrays)

    def detect_all(self, closes: np.ndarray, opens: np.ndarray,
                   highs: np.ndarray, lows: np.ndarray,
                   volumes: np.ndarray) -> List[str]:
        """检测所有12条OHLCV规则，返回匹配的形态名列表"""
        if len(closes) < 5:
            return []
        matched = []
        checks = [
            # [154-批1] 12条纯OHLCV规则
            ('放量冲高回落(预跌)', '_is_fangliang_chonggao_huiluo'),
            ('天量天价(预跌)', '_is_tianliang_tianjia'),
            ('放量滞涨(预跌)', '_is_fangliang_zhizhang'),
            ('跳空高开低走巨量阴线(预跌)', '_is_tiaokong_goodbye'),
            ('放量下跌恐慌出逃(预跌)', '_is_konghuang_chutao'),
            ('平台破位箱体下沿跌破(预跌)', '_is_pingtai_tupo'),
            ('低位连续小阳线黑马前奏(黑马)', '_is_diwei_xiaoyang'),
            ('地量后倍量启动(黑马)', '_is_diliang_beiliang'),
            ('底部放量长阳黑马首板(黑马)', '_is_dibu_fangliang_changyang'),
            ('地量后的倍量启动(预涨)', '_is_diliang_beiliang_yuzhang'),
            ('平台放量突破(预涨)', '_is_pingtai_fangliang_tupo'),
            ('放量站上60日线(预涨)', '_is_fangliang_zhan60'),
            # [154-批2] 8条均线辅助规则
            ('MA5金叉MA10(预涨)', '_is_ma5_jinchai_ma10'),
            ('MA5死叉MA10(预跌)', '_is_ma5_sicha_ma10'),
            ('均线多头排列(预涨)', '_is_ma_tuo_pailie'),
            ('均线空头排列(预跌)', '_is_ma_ya_pailie'),
            ('连续站上60日线(预涨)', '_is_closes_above_ma60'),
            ('MA5上穿MA20(预涨)', '_is_ma5_tol_ma20_up'),
            ('回踩MA60获支撑(预涨)', '_is_ma60_zhichi'),
            ('MA5上穿MA60(预涨)', '_is_ma5_jiaotou_ma60'),
        ]
        for name, method_name in checks:
            method = getattr(self, method_name, None)
            if method and method(closes, opens, highs, lows, volumes):
                matched.append(name)
        return matched

    # ── 2-4: 放量冲高回落（预跌型） ──
    def _is_fangliang_chonggao_huiluo(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, highs, volumes, min_len=5):
            return False
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        upper_shadow = highs[-1] - max(closes[-1], opens[-1])
        body = abs(closes[-1] - opens[-1])
        if body <= 0:
            return False
        return (highs[-1] > np.max(highs[-21:-1]) and
                upper_shadow > body * 2 and
                volumes[-1] > avg_vol * 2.5)

    # ── 2-5: 天量天价（预跌型） ──
    def _is_tianliang_tianjia(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, highs, volumes, min_len=62):
            return False
        return (volumes[-1] > np.max(volumes[-250:-1]) and
                highs[-1] > np.max(highs[-60:-1]) and
                closes[-1] < highs[-1])

    # ── 2-8: 放量滞涨（预跌型） ──
    def _is_fangliang_zhizhang(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, volumes, min_len=5):
            return False
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        recent3_vol = volumes[-4:-1]
        if not all(v > avg_vol * 1.5 for v in recent3_vol):
            return False
        gains = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(-3, 0)]
        return sum(gains) < 0.01

    # ── 2-9: 跳空高开低走巨量阴线（预跌型） ──
    def _is_tiaokong_goodbye(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, opens, volumes, min_len=3):
            return False
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        gap_up = opens[-1] > highs[-2]
        is_black = closes[-1] < opens[-1]
        drop_pct = (opens[-1] - closes[-1]) / opens[-1]
        return gap_up and is_black and volumes[-1] > avg_vol * 3 and drop_pct > 0.05

    # ── 2-14: 放量下跌恐慌出逃（预跌型） ──
    def _is_konghuang_chutao(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, lows, volumes, min_len=5):
            return False
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        drop_pct = (closes[-2] - closes[-1]) / closes[-2]
        near_low = (closes[-1] - lows[-1]) / (highs[-1] - lows[-1]) if highs[-1] != lows[-1] else 0
        return drop_pct > 0.05 and volumes[-1] > avg_vol * 2.5 and near_low < 0.1

    # ── 2-20: 平台破位箱体下沿跌破（预跌型） ──
    def _is_pingtai_tupo(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, lows, volumes, min_len=25):
            return False
        box_high = np.max(highs[-21:-1])
        box_low = np.min(lows[-21:-1])
        amplitude = (box_high - box_low) / box_low
        if amplitude > 0.20:
            return False
        avg_vol = float(np.mean(volumes[-21:-1]))
        if avg_vol <= 0:
            return False
        if closes[-1] < box_low:
            later_closes = closes[-3:]
            if all(c < box_low for c in later_closes):
                return volumes[-1] > avg_vol * 1.8
        return False

    # ── 3-2: 低位连续小阳线黑马前奏（黑马型） ──
    def _is_diwei_xiaoyang(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, opens, volumes, min_len=10):
            return False
        small_yangs = 0
        for i in range(-10, 0):
            if closes[i] > opens[i]:
                body_pct = (closes[i] - opens[i]) / opens[i]
                if body_pct < 0.03:
                    small_yangs += 1
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        return small_yangs >= 7 and volumes[-1] < avg_vol * 0.5

    # ── 3-4: 地量后倍量启动（黑马型） ──
    def _is_diliang_beiliang(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, volumes, min_len=122):
            return False
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        min_120 = np.min(volumes[-120:])
        gap_3 = (closes[-1] - closes[-2]) / closes[-2]
        return (min_120 <= np.percentile(volumes[-120:], 5) and
                volumes[-1] > avg_vol * 3 and
                gap_3 > 0.04)

    # ── 3-5: 底部放量长阳黑马首板（黑马型） ──
    def _is_dibu_fangliang_changyang(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, opens, lows, volumes, min_len=32):
            return False
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        body_pct = abs(closes[-1] - opens[-1]) / opens[-1]
        bottom_low = np.min(lows[-30:-1])
        return (body_pct > 0.07 and
                volumes[-1] > avg_vol * 4 and
                closes[-1] > bottom_low * 1.05 and
                np.min(lows[-30:-1]) < np.percentile(lows[-120:], 20) if len(lows) >= 120 else False)

    # ── 1-6: 地量后倍量启动（预涨型） ──
    def _is_diliang_beiliang_yuzhang(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, volumes, min_len=22):
            return False
        avg_vol = float(np.mean(volumes[-21:-1]))
        if avg_vol <= 0:
            return False
        min_20 = np.min(volumes[-20:-1])
        gap_3 = (closes[-1] - closes[-2]) / closes[-2]
        return (min_20 <= np.percentile(volumes[-20:-1], 10) and
                volumes[-1] > avg_vol * 2 and
                gap_3 > 0.03)

    # ── 1-7: 平台放量突破（预涨型） ──
    def _is_pingtai_fangliang_tupo(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, highs, volumes, min_len=22):
            return False
        avg_vol = float(np.mean(volumes[-21:-1]))
        if avg_vol <= 0:
            return False
        platform_high = np.max(highs[-21:-1])
        if closes[-1] > platform_high and volumes[-1] > avg_vol * 3:
            next_close = closes[-2] if len(closes) >= 2 else closes[-1]
            return next_close > platform_high
        return False

    # ── 1-15: 放量站上60日线（预涨型，需MA60） ──
    def _is_fangliang_zhan60(self, closes, opens, highs, lows, volumes) -> bool:
        if not self._safe_len(closes, volumes, min_len=62):
            return False
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return False
        ma60 = float(np.mean(closes[-60:]))
        prev_ma60 = float(np.mean(closes[-61:-1]))
        return (closes[-1] > ma60 and
                volumes[-1] > avg_vol * 1.8 and
                ma60 >= prev_ma60)

    # ── 形态1: 冲高回落急速缩量（预涨型）──
    def _is_chonggao_huiluo_jisuo(self, closes, highs, lows, volumes) -> bool:
        """当日最高涨幅>3% → 收盘回落<最高价2% → 次日成交量<前日50%"""
        if len(closes) < 3 or len(highs) < 3 or len(lows) < 3 or len(volumes) < 2:
            return False
        today_high_pct = (highs[-2] / closes[-3] - 1) * 100
        if today_high_pct > 3:
            pullback = (highs[-2] - closes[-2]) / highs[-2]
            if pullback > 0.02:
                if volumes[-1] < volumes[-2] * 0.5:
                    return True
        return False

    # ── 形态2: 递增式放量下跌（预跌型）──
    def _is_dizeng_fangliang_xiajie(self, closes, volumes) -> bool:
        """连续3日成交量递增且每日收盘价均低于前日"""
        if len(closes) < 4 or len(volumes) < 4:
            return False
        for i in range(-3, 0):
            if closes[i] >= closes[i-1]:
                return False
            if volumes[i] <= volumes[i-1]:
                return False
        return True

    # ── 形态3: 堆量中跌回启动点（预涨型/黑马型）──
    def _is_huiluo_zhangting_qiangshi(self, closes, volumes) -> bool:
        """10日累计换手高 → 价格跌回启动点 → 量缩至放量区30%"""
        if len(closes) < 10 or len(volumes) < 10:
            return False
        base = closes[-11]
        current = closes[-1]
        if current < base * 1.02:  # 接近启动点
            vol_peak = np.max(volumes[-10:])
            vol_last = np.mean(volumes[-3:])
            if vol_last < vol_peak * 0.3:
                return True
        return False

    # ── 形态4: 三连阳放量（预涨型）──
    def _is_sanlian_yang_fangliang(self, closes, opens, volumes) -> bool:
        """连续3日阳线 + 成交量递增"""
        if len(closes) < 4 or len(opens) < 4 or len(volumes) < 4:
            return False
        for i in range(-3, 0):
            if closes[i] <= opens[i]:
                return False
            if volumes[i] <= volumes[i-1]:
                return False
        return True

    # ── 形态5: 放量长阴破位（预跌型）──
    def _is_fangliang_changyin_tupo(self, closes, opens, highs, lows, volumes) -> bool:
        if len(closes) < 10 or len(opens) < 10 or len(highs) < 10 or len(lows) < 10 or len(volumes) < 10:
            return False
        body = abs(closes[-1] - opens[-1])
        range_total = highs[-1] - lows[-1]
        if range_total <= 0:
            return False
        body_ratio = body / range_total
        if closes[-1] < closes[-2] and body_ratio > 0.6:
            prev_low = np.min(lows[-10:-1])
            if closes[-1] < prev_low:
                avg_vol = np.mean(volumes[-10:-1])
                if volumes[-1] > avg_vol * 1.5:
                    return True
        return False

    # ── [154-批2] 均线辅助规则（8条） ──

    def _is_ma5_jinchai_ma10(self, closes, opens, highs, lows, volumes) -> bool:
        """MA5金叉MA10（趋势转折信号）"""
        if len(closes) < 11:
            return False
        ma5_p = float(np.mean(closes[-6:-1]))
        ma10_p = float(np.mean(closes[-11:-1]))
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        return ma5 > ma10 and ma5_p <= ma10_p

    def _is_ma5_sicha_ma10(self, closes, opens, highs, lows, volumes) -> bool:
        """MA5死叉MA10（趋势转折预警）"""
        if len(closes) < 11:
            return False
        ma5_p = float(np.mean(closes[-6:-1]))
        ma10_p = float(np.mean(closes[-11:-1]))
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        return ma5 < ma10 and ma5_p >= ma10_p

    def _is_ma_tuo_pailie(self, closes, opens, highs, lows, volumes) -> bool:
        """均线多头排列 MA5>MA10>MA20>MA60（中期多头确认）"""
        if len(closes) < 61:
            return False
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:]))
        return ma5 > ma10 > ma20 > ma60

    def _is_ma_ya_pailie(self, closes, opens, highs, lows, volumes) -> bool:
        """均线空头排列 MA5<MA10<MA20<MA60（中期空头确认）"""
        if len(closes) < 61:
            return False
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:]))
        return ma5 < ma10 < ma20 < ma60

    def _is_closes_above_ma60(self, closes, opens, highs, lows, volumes) -> bool:
        """连续3日收盘价站上MA60（中期走强确认）"""
        if len(closes) < 63:
            return False
        ma60 = float(np.mean(closes[-60:]))
        for i in range(-3, 0):
            if closes[i] <= ma60:
                return False
        return closes[-3] <= float(np.mean(closes[-62:-2])) * 1.005  # 刚刚站上

    def _is_ma5_tol_ma20_up(self, closes, opens, highs, lows, volumes) -> bool:
        """MA5从下方上穿MA20（短线强化信号）"""
        if len(closes) < 21:
            return False
        ma5 = float(np.mean(closes[-5:]))
        ma20 = float(np.mean(closes[-20:]))
        ma5_prev = float(np.mean(closes[-6:-1]))
        ma20_prev = float(np.mean(closes[-21:-1]))
        return ma5 > ma20 and ma5_prev <= ma20_prev

    def _is_ma60_zhichi(self, closes, opens, highs, lows, volumes) -> bool:
        """股价回踩MA60不破并获得支撑（回调低吸信号）"""
        if len(closes) < 63:
            return False
        ma60 = float(np.mean(closes[-60:]))
        lowest_5 = np.min(lows[-5:])
        return lowest_5 >= ma60 * 0.99 and closes[-1] > ma60 and                closes[-1] > np.mean(closes[-6:-1])  # 开始回升

    def _is_ma5_jiaotou_ma60(self, closes, opens, highs, lows, volumes) -> bool:
        """MA5上穿MA60（中期趋势转折关键信号）"""
        if len(closes) < 61:
            return False
        ma5 = float(np.mean(closes[-5:]))
        ma60 = float(np.mean(closes[-60:]))
        ma5_prev = float(np.mean(closes[-6:-1]))
        return ma5 > ma60 and ma5_prev <= ma60



# ══════════════════════════════════════════════
# Phase 1: 阶段判定 + 价格分位
# ══════════════════════════════════════════════

class StageDetector:
    """
    波段四阶段判定 + 三周期价格分位辅助
    主逻辑: MA60方向 → HH/HL序列 → 波段四阶段
    辅助校准: 30/60/120日价格分位 → 阶段置信度微调
    """

    def __init__(self, lookback: int = 120):
        self.lookback = lookback

    def detect(self, df: pd.DataFrame) -> Stage:
        if df.empty or len(df) < 30:
            return Stage(name="CONSOLIDATION", confidence=0.0, note="数据不足")

        closes = self._safe_col(df, 'close').values
        highs = self._safe_col(df, 'high').values
        lows = self._safe_col(df, 'low').values

        ma5 = self._sma(closes, 5)
        ma10 = self._sma(closes, 10)
        ma20 = self._sma(closes, 20)
        ma60 = self._sma(closes, 60)

        ma60_direction = self._calc_direction(ma60, 5)
        hh_hl = self._detect_hh_hl(highs, lows, 20)
        alignment = self._calc_ma_alignment(ma5[-1], ma10[-1], ma20[-1], ma60[-1])
        pos_60 = (closes[-1] - np.min(lows[-60:])) / (np.max(highs[-60:]) - np.min(lows[-60:]) + 1e-9)

        stage_name, stage_confidence = self._classify_stage(
            ma60_direction, hh_hl, alignment, pos_60, closes, highs, lows,
            ma5, ma10, ma20, ma60)

        valuation = self._calc_valuation_zones(closes, highs, lows)
        note = self._calibrate_note(stage_name, valuation, pos_60)

        if valuation.zone in ("HIGH", "MID_HIGH") and stage_name == "UPTREND_ACTIVE":
            stage_confidence *= 0.85
        elif valuation.zone == "LOW" and stage_name == "DOWNTREND_ACTIVE":
            stage_confidence *= 0.80

        return Stage(name=stage_name, confidence=min(stage_confidence, 1.0),
                     valuation=valuation, trend_structure=hh_hl,
                     ma_alignment=alignment, note=note)

    def _safe_col(self, df: pd.DataFrame, col: str) -> pd.Series:
        if col in df.columns:
            return df[col].astype(float)
        alt_map = {'close': 'close', 'high': 'high', 'low': 'low', 'vol': 'vol', 'volume': 'vol'}
        for k, v in alt_map.items():
            if k in df.columns and v == col:
                return df[k].astype(float)
        raise KeyError(f"列 {col} 不存在")

    def _sma(self, arr: np.ndarray, period: int) -> np.ndarray:
        if len(arr) < period:
            return np.full_like(arr, np.mean(arr))
        return pd.Series(arr).rolling(period).mean().values

    def _calc_direction(self, ma: np.ndarray, lookback: int = 5) -> str:
        if len(ma) < lookback + 1:
            return "flat"
        recent = ma[-(lookback + 1):]
        if recent[-1] > recent[0] * 1.005:
            return "up"
        elif recent[-1] < recent[0] * 0.995:
            return "down"
        return "flat"

    def _detect_hh_hl(self, highs: np.ndarray, lows: np.ndarray, window: int = 20) -> str:
        if len(highs) < window * 3:
            return "数据不足"
        mid = len(highs) - window
        h1 = np.max(highs[mid - window:mid]) if mid - window >= 0 else np.max(highs[:mid])
        h2 = np.max(highs[-window:])
        l1 = np.min(lows[mid - window:mid]) if mid - window >= 0 else np.min(lows[:mid])
        l2 = np.min(lows[-window:])
        hh, hl, lh, ll = h2 > h1, l2 > l1, h2 < h1, l2 < l1
        if hh and hl:
            return "HH/HL 序列（上涨趋势）"
        elif lh and ll:
            return "LH/LL 序列（下跌趋势）"
        elif hh and not hl:
            return "HH/LL 序列（均线纠缠）"
        return "趋势不明"

    def _calc_ma_alignment(self, ma5: float, ma10: float, ma20: float, ma60: float) -> str:
        if ma5 > ma10 > ma20 > ma60:
            return "多头排列"
        elif ma5 < ma10 < ma20 < ma60:
            return "空头排列"
        return "均线纠缠"

    def _classify_stage(self, ma60_dir, hh_hl, alignment, pos_60, closes, highs, lows, ma5, ma10, ma20, ma60):
        latest = closes[-1]
        if ma60_dir == "up" and "HH/HL" in hh_hl:
            vol_top_signal = False
            if len(closes) >= 10:
                if latest >= np.max(highs[-20:-10]) and pos_60 > 0.75:
                    vol_top_signal = True
            if vol_top_signal:
                return "UPTREND_TOPPING", 0.70
            return "UPTREND_ACTIVE", 0.80
        if ma60_dir == "down" and "LH/LL" in hh_hl:
            bot_signal = False
            if pos_60 < 0.25 and len(highs) >= 20:
                if not (latest <= np.min(lows[-20:-10])):
                    bot_signal = True
            if bot_signal:
                return "DOWNTREND_BOTTOMING", 0.70
            return "DOWNTREND_ACTIVE", 0.80
        if ma60_dir == "flat" and alignment == "多头排列" and pos_60 > 0.7:
            return "UPTREND_TOPPING", 0.60
        if ma60_dir == "flat" and alignment == "空头排列" and pos_60 < 0.3:
            return "DOWNTREND_BOTTOMING", 0.60
        return "CONSOLIDATION", 0.50

    def _calc_valuation_zones(self, closes, highs, lows) -> ValuationZones:
        def pos_in_range(period: int) -> float:
            start = max(0, len(closes) - period)
            if len(closes) - start < period // 2:
                return 0.5
            lo = np.min(lows[start:])
            hi = np.max(highs[start:])
            return (closes[-1] - lo) / (hi - lo) if hi - lo > 1e-9 else 0.5
        short = pos_in_range(30)
        mid = pos_in_range(60)
        long_ = pos_in_range(120)
        composite = short * 0.5 + mid * 0.3 + long_ * 0.2
        if composite >= 0.75:
            zone = "HIGH"
        elif composite >= 0.60:
            zone = "MID_HIGH"
        elif composite >= 0.40:
            zone = "MID"
        elif composite >= 0.25:
            zone = "MID_LOW"
        else:
            zone = "LOW"
        return ValuationZones(short_30d=short, mid_60d=mid, long_120d=long_, zone=zone)

    def _calibrate_note(self, stage: str, val: ValuationZones, pos_60: float) -> str:
        notes = {
            ("UPTREND_ACTIVE", "HIGH"): "上涨+高位区，关注触顶风险",
            ("UPTREND_ACTIVE", "MID_HIGH"): "上涨+偏高，趋势后段",
            ("UPTREND_ACTIVE", "MID"): "上涨+中位区，趋势中段最安全",
            ("UPTREND_ACTIVE", "MID_LOW"): "上涨+中低位，上行空间充足",
            ("UPTREND_ACTIVE", "LOW"): "上涨+低位区，刚启动潜力大",
        }
        key = (stage, val.zone)
        if key in notes:
            return notes[key]
        if "TOPPING" in stage and val.zone in ("HIGH", "MID_HIGH"):
            return "触顶+高位区，减仓信号确认"
        if "BOTTOMING" in stage and val.zone in ("MID_LOW", "LOW"):
            return "探底+低位区，关注反转信号"
        return f"{STAGE_NAMES.get(stage, stage)}，价格{val.zone_label}"


# ══════════════════════════════════════════════
# Phase 2: 成交量状态 + 主力行为推断
# ══════════════════════════════════════════════

class VolumeStateAnalyzer:
    """
    成交量状态评估 + 主力入市阶段推断
    [P0-优化3] 量能序列优先使用 amount/换手率
    """

    def __init__(self):
        pass

    def analyze(self, df: pd.DataFrame, stage: Stage) -> VolumeState:
        if df.empty or len(df) < 20:
            return VolumeState()

        closes = self._safe_col(df, 'close').values
        # [P0-优化3] 使用最佳量能序列
        volumes = get_best_volume_series(df)

        trend = self._calc_volume_trend(volumes)
        volma5 = self._sma(volumes, 5)
        volma10 = self._sma(volumes, 10)
        volma20 = self._sma(volumes, 20)
        v5, v10, v20 = volma5[-1], volma10[-1], volma20[-1]
        volma_struct = self._calc_volma_structure(v5, v10, v20)
        has_tuo = self._detect_volume_tuo(volma5, volma10, volma20)
        has_ya = self._detect_volume_ya(volma5, volma10, volma20)
        keypoints = self._find_keypoints(volumes, closes)
        inst = self._infer_institutional_phase(closes, volumes, v5, v10, v20,
                                                volma_struct, trend, stage, keypoints)

        return VolumeState(trend=trend, volma_structure=volma_struct,
                           has_volume_tuo=has_tuo, has_volume_ya=has_ya,
                           volume_keypoints=keypoints, institutional=inst)

    def _safe_col(self, df: pd.DataFrame, col: str) -> pd.Series:
        if col in df.columns:
            return df[col].astype(float)
        alt_map = {'close': 'close', 'vol': 'vol', 'volume': 'vol'}
        for k, v in alt_map.items():
            if k in df.columns and v == col:
                return df[k].astype(float)
        raise KeyError(f"列 {col} 不存在")

    def _sma(self, arr: np.ndarray, period: int) -> np.ndarray:
        if len(arr) < period:
            return np.full_like(arr, np.mean(arr))
        return pd.Series(arr).rolling(period).mean().values

    def _calc_volume_trend(self, volumes: np.ndarray) -> str:
        if len(volumes) < 30:
            return "STABLE"
        avg_20 = np.mean(volumes[-20:])
        avg_60 = np.mean(volumes[-60:])
        ratio = avg_20 / max(avg_60, 1)
        return "EXPANDING" if ratio > 1.3 else "CONTRACTING" if ratio < 0.7 else "STABLE"

    def _calc_volma_structure(self, v5: float, v10: float, v20: float) -> str:
        return "BULLISH" if v5 > v10 > v20 else "BEARISH" if v5 < v10 < v20 else "MIXED"

    def _detect_volume_tuo(self, vma5, vma10, vma20) -> bool:
        if len(vma5) < 3:
            return False
        v5_cross_v10 = vma5[-1] > vma10[-1] and vma5[-2] <= vma10[-2]
        v10_above_v20 = vma10[-1] > vma20[-1]
        v5_above_v20 = vma5[-1] > vma20[-1]
        v20_dir = vma20[-1] > vma20[-min(5, len(vma20))]
        cross = v5_cross_v10 or (vma5[-1] > vma10[-1] and vma10[-5] < vma20[-5])
        return cross and v10_above_v20 and v5_above_v20 and v20_dir

    def _detect_volume_ya(self, vma5, vma10, vma20) -> bool:
        if len(vma5) < 3:
            return False
        v5_cross_v10 = vma5[-1] < vma10[-1] and vma5[-2] >= vma10[-2]
        v10_below_v20 = vma10[-1] < vma20[-1]
        v5_below_v20 = vma5[-1] < vma20[-1]
        v20_dir = vma20[-1] < vma20[-min(5, len(vma20))]
        cross = v5_cross_v10 or (vma5[-1] < vma10[-1] and vma10[-5] > vma20[-5])
        return cross and v10_below_v20 and v5_below_v20 and v20_dir

    def _find_keypoints(self, volumes, closes) -> List[float]:
        keypoints = []
        if len(volumes) < 20:
            return keypoints
        avg_vol = np.mean(volumes)
        for i in range(-len(volumes), 0):
            if volumes[i] > avg_vol * 3 and i >= -60:
                keypoints.append(float(closes[i]))
        return keypoints[-5:]

    def _infer_institutional_phase(self, closes, volumes, v5, v10, v20,
                                    volma_struct, vol_trend, stage, keypoints):
        scores = {"BUILDING": 0.0, "WASHING": 0.0, "RAISING": 0.0, "SHIPPING": 0.0}
        latest_close = closes[-1]
        pos_60 = stage.valuation.short_30d if stage.valuation else 0.5

        if pos_60 < 0.30:
            scores["BUILDING"] += 2.0
        if vol_trend == "EXPANDING" and np.mean(volumes[-5:]) < np.mean(volumes[-20:-5]) * 1.5:
            scores["BUILDING"] += 2.0
        if len(closes) >= 10 and abs((closes[-1] / closes[-10] - 1) * 100) < 5:
            scores["BUILDING"] += 2.0

        if vol_trend == "CONTRACTING":
            scores["WASHING"] += 2.0
        if len(closes) >= 20:
            pct_10d = (closes[-1] / closes[-10] - 1) * 100
            low_20 = np.min(closes[-20:])
            if abs(pct_10d) < 5 and latest_close < low_20 * 1.05:
                scores["WASHING"] += 2.0
        if volma_struct == "BEARISH":
            scores["WASHING"] += 1.0

        if vol_trend == "EXPANDING" and volma_struct == "BULLISH":
            scores["RAISING"] += 2.0
        if 0.30 < pos_60 < 0.75:
            scores["RAISING"] += 1.5
        if keypoints and (len(keypoints) >= 3 and latest_close > max(keypoints[-3:])):
            scores["RAISING"] += 2.0
        if self._has_duofang_pao(closes, volumes):
            scores["RAISING"] += 1.5

        if pos_60 > 0.70:
            scores["SHIPPING"] += 2.0
        if vol_trend == "EXPANDING" and volma_struct == "BULLISH":
            if len(closes) >= 5 and (closes[-1] / closes[-5] - 1) * 100 < 3:
                scores["SHIPPING"] += 2.0
        if self._has_kongfang_pao(closes, volumes):
            scores["SHIPPING"] += 1.5

        best_phase = max(scores, key=scores.get)
        best_score = scores[best_phase]
        total = sum(scores.values()) or 1
        confidence = best_score / total
        interpretations = {
            "BUILDING": "低位量能温和放大，量价模式符合建仓特征",
            "WASHING": "缩量企稳，量价模式符合洗盘特征",
            "RAISING": "价涨量增持续，均量线多头排列，符合拉升特征",
            "SHIPPING": "高位放量滞涨或量价背离，符合出货特征",
        }
        return InstitutionalPhase(phase=best_phase, confidence=min(confidence, 1.0),
                                  scores=scores, interpretation=interpretations.get(best_phase, ""))

    def _has_duofang_pao(self, closes, volumes) -> bool:
        if len(closes) < 4:
            return False
        c = closes[-4:]
        is_up = lambda i: c[i] > c[i-1]
        is_down = lambda i: c[i] < c[i-1]
        return is_up(1) and is_down(2) and is_up(3) and c[3] > c[1]

    def _has_kongfang_pao(self, closes, volumes) -> bool:
        if len(closes) < 4:
            return False
        c = closes[-4:]
        is_up = lambda i: c[i] > c[i-1]
        is_down = lambda i: c[i] < c[i-1]
        return is_down(1) and is_up(2) and is_down(3) and c[3] < c[1]


# ══════════════════════════════════════════════
# Phase 3: 量价关系 + 多空动量
# ══════════════════════════════════════════════

class VolumePriceRelationAnalyzer:
    """
    量价关系分析 + 多空动量评估
    [P1-优化4] 增强形态检测
    [P1-优化5] MACD双重确认背离
    """

    def __init__(self):
        self.pattern_detector = EnhancedPatternDetector()

    def analyze(self, df: pd.DataFrame, stage: Stage, vol_state: VolumeState) -> RelationResult:
        if df.empty or len(df) < 10:
            return RelationResult()

        closes = self._safe_col(df, 'close').values
        opens = self._safe_col(df, 'open').values if 'open' in df.columns else closes
        highs = self._safe_col(df, 'high').values
        lows = self._safe_col(df, 'low').values
        volumes = get_best_volume_series(df)

        # 1. 九种基础量价形态
        pattern_id, pattern_name = self._classify_vp_pattern(closes, volumes)

        # 2. [P1-优化4] 增强形态检测
        enhance_pats = self.pattern_detector.detect_all(closes, opens, highs, lows, volumes)

        # 3. [P1-优化5] MACD双重确认为度的背离检测
        div_type, div_conf, macd_confirmed = self._detect_divergence_enhanced(
            closes, volumes, highs, lows, stage.name, df)

        # 4. 交叉矩阵
        cross_note, _ = CROSS_MATRIX.get((stage.name, pattern_id), ("", 0.0))

        # 5. 多空动量
        momentum = self._calc_momentum(closes, opens, highs, lows, volumes, stage.name)

        # 6. [P1-优化6] 共振评分
        resonance = self._calc_resonance_score(pattern_id, enhance_pats, momentum, vol_state, stage)

        return RelationResult(
            pattern_id=pattern_id, pattern_name=pattern_name,
            enhance_patterns=enhance_pats,
            divergence_type=div_type, divergence_confidence=div_conf,
            divergence_macd_confirmed=macd_confirmed,
            cross_matrix_note=cross_note,
            momentum=momentum,
            resonance_score=resonance,
        )

    def _safe_col(self, df, col):
        if col in df.columns:
            return df[col].astype(float)
        alt_map = {'close': 'close', 'open': 'open', 'high': 'high', 'low': 'low', 'vol': 'vol', 'volume': 'vol'}
        for k, v in alt_map.items():
            if k in df.columns and v == col:
                return df[k].astype(float)
        raise KeyError(f"列 {col} 不存在")

    def _classify_vp_pattern(self, closes, volumes):
        if len(closes) < 4 or len(volumes) < 4:
            return "", ""
        price_chg = (closes[-1] - closes[-4]) / max(closes[-4], 1e-9) * 100
        vol_chg = (np.mean(volumes[-3:]) - np.mean(volumes[-7:-3])) / max(np.mean(volumes[-7:-3]), 1e-9) * 100
        price_dir = "up" if price_chg > 2 else "down" if price_chg < -2 else "flat"
        vol_dir = "expand" if vol_chg > 15 else "shrink" if vol_chg < -15 else "stable"
        mapping = {
            ("up", "expand"): ("VP-1", "价涨量增"), ("up", "stable"): ("VP-2", "价涨量平"),
            ("up", "shrink"): ("VP-3", "价涨量缩"), ("flat", "expand"): ("VP-4", "价平量增"),
            ("flat", "stable"): ("VP-5", "价平量平"), ("flat", "shrink"): ("VP-6", "价平量减"),
            ("down", "expand"): ("VP-7", "价跌量增"), ("down", "stable"): ("VP-8", "价跌量平"),
            ("down", "shrink"): ("VP-9", "价跌量缩"),
        }
        return mapping.get((price_dir, vol_dir), ("VP-5", "价平量平"))

    def _detect_divergence_enhanced(self, closes, volumes, highs, lows, stage, df):
        """[P1-优化5] 增强的背离检测（价格+量+MACD三重确认）"""
        div_type = "none"
        div_conf = 0.0
        macd_confirmed = False

        if len(closes) < 40 or len(volumes) < 40 or len(highs) < 40 or len(lows) < 40:
            return div_type, div_conf, macd_confirmed

        # 计算MACD
        dif, dea, hist = calc_macd(closes)

        # 顶背离
        if stage in ("UPTREND_ACTIVE", "UPTREND_TOPPING"):
            p1_idx = len(closes) - 20 - (np.argmax(highs[-20:-10]) if len(highs) >= 20 else 0)
            p2_idx = len(closes) - 10 + (np.argmax(highs[-10:]) if len(highs) >= 10 else 0)
            if 0 <= p1_idx < p2_idx < len(closes):
                p1_price, p2_price = highs[p1_idx], highs[p2_idx]
                v1 = np.mean(volumes[max(0, p1_idx-3):p1_idx+1])
                v2 = np.mean(volumes[max(0, p2_idx-3):p2_idx+1])
                if p2_price > p1_price and v2 < v1 * 0.9:
                    pct_p = (p2_price - p1_price) / p1_price
                    pct_v = (v1 - v2) / max(v1, 1)
                    div_conf = min(1.0, pct_p * 10) * min(1.0, pct_v * 5)
                    div_type = "top"
                    # MACD确认: DIF未创新高
                    if len(dif) > max(p1_idx, p2_idx):
                        d1 = dif[p1_idx]
                        d2 = dif[p2_idx]
                        if d2 < d1:
                            macd_confirmed = True
                            div_conf = min(1.0, div_conf * 1.2)

        # 底背离
        if stage in ("DOWNTREND_ACTIVE", "DOWNTREND_BOTTOMING"):
            t1_idx = len(lows) - 20 - (np.argmin(lows[-20:-10]) if len(lows) >= 20 else 0)
            t2_idx = len(lows) - 10 + (np.argmin(lows[-10:]) if len(lows) >= 10 else 0)
            if 0 <= t1_idx < t2_idx < len(lows):
                t1_price, t2_price = lows[t1_idx], lows[t2_idx]
                v1 = np.mean(volumes[max(0, t1_idx-3):t1_idx+1])
                v2 = np.mean(volumes[max(0, t2_idx-3):t2_idx+1])
                if t2_price < t1_price and v2 > v1 * 1.1:
                    pct_p = (t1_price - t2_price) / t1_price
                    pct_v = (v2 - v1) / max(v1, 1)
                    div_conf = min(1.0, pct_p * 10) * min(1.0, pct_v * 5)
                    div_type = "bottom"
                    # MACD确认: DIF未创新低
                    if len(dif) > max(t1_idx, t2_idx):
                        d1 = dif[t1_idx]
                        d2 = dif[t2_idx]
                        if d2 > d1:
                            macd_confirmed = True
                            div_conf = min(1.0, div_conf * 1.2)

        return div_type, div_conf, macd_confirmed

    def _calc_resonance_score(self, pattern_id, enhance_pats, momentum, vol_state, stage) -> int:
        """[P1-优化6] 多形态共振评分"""
        score = 0
        # 基础形态评分（看多方向）
        if pattern_id in ("VP-1", "VP-2", "VP-9"):
            score += 1
        elif pattern_id in ("VP-7", "VP-8", "VP-3"):
            score -= 1
        # 增强形态
        for p in enhance_pats:
            if "预涨" in p:
                score += 2
            elif "预跌" in p:
                score -= 2
        # 动量
        if momentum and momentum.level in ("BULL_STRONG", "BULL_MODERATE"):
            score += 1
        elif momentum and momentum.level in ("BEAR_STRONG", "BEAR_MODERATE"):
            score -= 1
        # 量托量压
        if vol_state.has_volume_tuo:
            score += 1
        if vol_state.has_volume_ya:
            score -= 1
        return score

    def _calc_momentum(self, closes, opens, highs, lows, volumes, stage):
        """多空动量（同v3不变）"""
        if len(closes) < 10:
            return MomentumProfile()
        candle_score = self._calc_candle_force(closes, opens, highs, lows)
        vol_mom = self._calc_volume_momentum(closes, volumes)
        accel_score, accel_label = self._calc_price_acceleration(closes)
        total = candle_score * 0.30 + vol_mom * 0.35 + accel_score * 0.35
        total = max(-1.0, min(1.0, total))
        if total >= 0.5:
            level, interp = "BULL_STRONG", "多方动能充足，趋势健康"
        elif total >= 0.2:
            level, interp = "BULL_MODERATE", "多方偏强，趋势可持续"
        elif total > -0.2:
            level, interp = "NEUTRAL", "多空均衡"
        elif total > -0.5:
            level, interp = "BEAR_MODERATE", "空方偏强"
        else:
            level, interp = "BEAR_STRONG", "空方主导，回避"
        candle_desc = "多方主导" if candle_score > 0.3 else "空方主导" if candle_score < -0.3 else "均衡"
        vol_ratio = sum(volumes[-5:][closes[-5:] > closes[-6:-1]]) / max(sum(volumes[-5:]), 1)
        vr = vol_ratio / (1 - vol_ratio + 1e-9)
        vol_desc = "上涨有量" if vr > 1.2 else "下跌放量" if vr < 0.8 else "量能均衡"
        return MomentumProfile(score=total, level=level, candle_force=candle_desc,
                               volume_direction=vol_desc, price_accel=accel_label, interpretation=interp)

    def _calc_candle_force(self, closes, opens, highs, lows) -> float:
        if len(closes) < 10:
            return 0.0
        bodies = []
        for i in range(-10, 0):
            body = abs(closes[i] - opens[i]) / max(highs[i] - lows[i], 1e-9)
            bodies.append(body * (1 if closes[i] > opens[i] else -1))
        return max(-1.0, min(1.0, np.mean(bodies) * 2))

    def _calc_volume_momentum(self, closes, volumes) -> float:
        if len(closes) < 10:
            return 0.0
        up_vols, down_vols = [], []
        for i in range(-10, 0):
            (up_vols if closes[i] > closes[i-1] else down_vols).append(volumes[i])
        avg_up = np.mean(up_vols) if up_vols else 1
        avg_down = np.mean(down_vols) if down_vols else 1
        ratio = avg_up / max(avg_down, 1)
        if ratio > 1.2:
            return min(1.0, (ratio - 1.2) * 1.5)
        elif ratio < 0.8:
            return max(-1.0, (ratio - 0.8) * 2.5)
        return 0.0

    def _calc_price_acceleration(self, closes) -> Tuple[float, str]:
        if len(closes) < 20:
            return 0.0, "数据不足"
        pct_5 = (closes[-1] / closes[-5] - 1) * 100
        pct_20 = (closes[-1] / closes[-20] - 1) * 100
        if abs(pct_20) < 2:
            return 0.0, "均衡"
        ratio = abs(pct_5) / max(abs(pct_20), 0.5)
        if pct_20 > 0:
            if ratio > 1.3:
                return min(1.0, ratio * 0.3), "加速上涨"
            elif ratio < 0.5:
                return max(-0.5, ratio - 1), "减速上涨"
            return 0.3, "温和上涨"
        else:
            if ratio > 1.3:
                return max(-1.0, -ratio * 0.3), "加速下跌"
            elif ratio < 0.5:
                return min(0.5, 1 - ratio), "减速下跌"
            return -0.3, "温和下跌"


# ══════════════════════════════════════════════
# P2: 动态止盈/入场计算工具
# ══════════════════════════════════════════════

class EntryTargetCalculator:
    """
    [P2-优化7] 动态止盈 — 基于空间目标（前高/波动率）
    [P2-优化8] 关键位入场校准 — 基于倍量关键位
    """

    @staticmethod
    def calc_target(stage: Stage, keypoints: List[float], latest_close: float) -> Tuple[float, float]:
        """(低位目标, 高位目标) 基于前高/波动率"""
        # 找到高于当前价最近的前高
        candidates = [k for k in keypoints if k > latest_close * 1.02]
        if candidates:
            nearest_high = min(candidates)
            # 前高作为目标参考
            return round(nearest_high * 0.98, 2), round(nearest_high * 1.05, 2)
        # 无前高参考: 固定比例
        return round(latest_close * 1.05, 2), round(latest_close * 1.15, 2)

    @staticmethod
    def calc_risk_line(stage: Stage, keypoints: List[float], latest_close: float) -> float:
        """止损: 基于支撑位"""
        # 找到低于当前价最近的关键位
        supports = [k for k in keypoints if k < latest_close * 0.98]
        if supports:
            nearest_support = max(supports)
            # 支撑位下方2%
            return round(nearest_support * 0.98, 2)
        # 无支撑参考: 固定-8%
        return round(latest_close * 0.92, 2)

    @staticmethod
    def calc_entry_zone(keypoints: List[float], latest_close: float) -> Tuple[float, float]:
        """[P2-优化8] 入场区间: 基于倍量关键位校准"""
        # 找到低于当前价最近的关键位
        supports = [k for k in keypoints if k < latest_close * 1.05 and k > latest_close * 0.85]
        if supports:
            nearest_kp = max(supports)
            return round(nearest_kp * 0.97, 2), round(nearest_kp * 1.03, 2)
        return round(latest_close * 0.97, 2), round(latest_close * 1.02, 2)


# ══════════════════════════════════════════════
# Phase 4: 四维信号生成
# ══════════════════════════════════════════════

class VolumePriceSignalGenerator:
    """
    信号生成 + 四维校准 + 右侧交易过滤
    [P1-优化6] 多形态共振评分校准
    """

    def __init__(self):
        self.position_mgr = PositionManager()  # [P0-优化2]
        self.entry_target = EntryTargetCalculator()  # [P2-优化7&8]

    def generate(self, stage: Stage, vol_state: VolumeState,
                 relation: RelationResult, df: pd.DataFrame,
                 market_multiplier: float = DEFAULT_MARKET_MULTIPLIER) -> VolumePriceSignal:
        if df.empty or len(df) < 5:
            return VolumePriceSignal()

        closes = self._safe_col(df, 'close').values
        latest_close = float(closes[-1])

        # 1. 匹配基础信号
        base_signal = self._match_base_signal(stage.name, relation.pattern_id)
        if not base_signal:
            return VolumePriceSignal(direction="HOLD", signal_label="持仓等待",
                                     confidence=0.45, evidence=["信号不匹配"])

        signal_id, direction, base_conf = base_signal

        # 2. 辅助维度校准
        conf = base_conf

        # [P0-优化1] 大盘环境校准
        conf *= market_multiplier

        # 价格分位校准
        if stage.valuation:
            val = stage.valuation
            if val.zone in ("LOW", "MID_LOW") and direction == "BUY":
                conf += 0.05
            elif val.zone in ("HIGH", "MID_HIGH") and direction == "BUY":
                conf -= 0.10
                direction = "WATCH"
            elif val.zone in ("HIGH", "MID_HIGH") and direction == "SELL":
                conf += 0.05

        # 主力阶段校准
        if vol_state.institutional and vol_state.institutional.confidence > 0.5:
            inst = vol_state.institutional
            if inst.phase == "RAISING" and direction == "BUY":
                conf += 0.05
            elif inst.phase == "SHIPPING" and direction == "BUY":
                direction = "WATCH"
                conf = min(conf, 0.55)

        # 动量校准
        if relation.momentum and relation.momentum.score != 0:
            mom = relation.momentum
            if mom.level in ("BULL_STRONG", "BULL_MODERATE") and direction == "BUY":
                conf += 0.05
            elif mom.level in ("BEAR_STRONG", "BEAR_MODERATE") and direction == "BUY":
                direction = "WATCH"
                conf = min(conf, 0.55)
            elif mom.level in ("BEAR_STRONG", "BEAR_MODERATE") and direction == "SELL":
                conf += 0.05

        # [P1-优化6] 共振评分校准
        if relation.resonance_score >= 3 and direction == "BUY":
            conf += 0.05
        elif relation.resonance_score <= -3 and direction == "SELL":
            conf += 0.05

        # [P1-优化5] MACD确认背离加分
        if relation.divergence_type != "none" and relation.divergence_macd_confirmed:
            conf += 0.05

        # 3. 右侧交易铁律
        if direction == "BUY" and stage.name in ("DOWNTREND_ACTIVE",):
            direction = "WATCH"
            conf = min(conf, 0.50)
        if direction == "SELL" and stage.name in ("UPTREND_ACTIVE",):
            direction = "WATCH"
            conf = min(conf, 0.50)
        if relation.divergence_type != "none" and direction in ("BUY", "SELL"):
            direction = "WATCH"
            conf = min(conf, 0.55)

        conf = max(0.0, min(1.0, conf))

        # 4. [P2-优化8] 入场/止损计算（基于关键位）
        entry_low, entry_high = self.entry_target.calc_entry_zone(
            vol_state.volume_keypoints, latest_close)
        risk_line = self.entry_target.calc_risk_line(
            stage, vol_state.volume_keypoints, latest_close)

        # [P2-优化7] 目标计算（基于前高/波动率）
        target_low, target_high = self.entry_target.calc_target(
            stage, vol_state.volume_keypoints, latest_close)

        # [P0-优化2] 动态仓位
        volatility = relation.momentum.score if relation.momentum else None
        pos_suggestion, pos_detail = self.position_mgr.calc_position(
            latest_close, risk_line, direction, volatility)

        # 证据链
        evidence = self._build_evidence(stage, vol_state, relation, signal_id, direction)
        risk_notes = self._build_risk_notes(stage, vol_state, relation)

        signal_label_map = {"BUY": "买入", "SELL": "卖出", "WATCH": "观察", "HOLD": "持仓等待"}
        hold_map = {"BUY": "2-4周（波段持有）", "SELL": "立即", "WATCH": "观察等待", "HOLD": "继续持仓"}

        return VolumePriceSignal(
            signal_id=signal_id, direction=direction, confidence=conf,
            signal_label=signal_label_map.get(direction, "等待"),
            entry_zone=(entry_low, entry_high), risk_line=risk_line,
            target_zone=(target_low, target_high),
            position_suggestion=pos_suggestion, position_detail=pos_detail,
            holding_period=hold_map.get(direction, "观望"),
            evidence=evidence, risk_notes=risk_notes,
        )

    def _safe_col(self, df, col):
        if col in df.columns:
            return df[col].astype(float)
        alt_map = {'close': 'close', 'vol': 'vol', 'volume': 'vol'}
        for k, v in alt_map.items():
            if k in df.columns and v == col:
                return df[k].astype(float)
        raise KeyError(f"列 {col} 不存在")

    def _match_base_signal(self, stage, pattern_id):
        """匹配基础信号 + 同阶段兜底"""
        best = None
        for stg, pid_list, sid, dr, cf in SIGNAL_TABLE:
            for pid in pid_list:
                if stg == stage and pid == pattern_id:
                    if best is None or cf > best[2]:
                        best = (sid, dr, cf)
        if best:
            return best
        for stg, pid_list, sid, dr, cf in SIGNAL_TABLE:
            if stg == stage:
                if best is None or cf > best[2]:
                    best = (sid, dr, cf)
        return best

    def _build_evidence(self, stage, vol_state, relation, signal_id, direction):
        ev = []
        ev.append(f"【阶段】{STAGE_NAMES.get(stage.name, stage.name)}")
        if stage.note:
            ev.append(f"【分位】{stage.note}")
        if relation.pattern_id:
            ev.append(f"【量价】{relation.pattern_id} {relation.pattern_name}")
        if relation.cross_matrix_note:
            ev.append(f"【矩阵】{relation.cross_matrix_note}")
        # [P1-优化4] 增强形态
        for ep in relation.enhance_patterns:
            ev.append(f"【增强形态】{ep}")

        vol_trend_cn = {"EXPANDING": "放量", "CONTRACTING": "缩量", "STABLE": "平量"}
        volma_cn = {"BULLISH": "多头排列", "BEARISH": "空头排列", "MIXED": "交叉"}
        ev.append(f"【量】{vol_trend_cn.get(vol_state.trend, '平量')}趋势，均量线{volma_cn.get(vol_state.volma_structure, '')}")
        if vol_state.has_volume_tuo:
            ev.append("【量】量托已形成")
        if vol_state.has_volume_ya:
            ev.append("【量】量压已形成")
        if vol_state.institutional and vol_state.institutional.confidence > 0.3:
            label = INST_PHASE_LABELS.get(vol_state.institutional.phase, vol_state.institutional.phase)
            ev.append(f"【主力】推断为{label}({vol_state.institutional.confidence:.0%})")
        if relation.momentum and relation.momentum.level != "NEUTRAL":
            ev.append(f"【动量】{relation.momentum.interpretation}({relation.momentum.level})")
        if relation.divergence_type != "none":
            div_cn = {"top": "顶背离", "bottom": "底背离"}
            macd_tag = "✓MACD" if relation.divergence_macd_confirmed else ""
            ev.append(f"【背离】{div_cn.get(relation.divergence_type, '')}确认({relation.divergence_confidence:.0%}){macd_tag}")
        # [P1-优化6] 共振评分
        if relation.resonance_score != 0:
            ev.append(f"【共振】多形态评分={relation.resonance_score:+d}")
        sig_cn = {"BUY": "买入", "SELL": "卖出", "WATCH": "预警", "HOLD": "观望"}
        ev.append(f"【信号】{signal_id}: {sig_cn.get(direction, '')}")
        return ev

    def _build_risk_notes(self, stage, vol_state, relation):
        notes = []
        if stage.name in ("UPTREND_TOPPING", "DOWNTREND_ACTIVE"):
            notes.append("趋势转折风险，量价策略信号滞后")
        elif stage.name == "CONSOLIDATION":
            notes.append("横盘整理，方向不明")
        if stage.valuation and stage.valuation.zone in ("HIGH", "MID_HIGH"):
            notes.append("估值处于高位区间")
        if vol_state.institutional and vol_state.institutional.phase == "SHIPPING":
            notes.append("主力出货风险")
        # [P0-优化1] 大盘风险提示（由外部传入，此处预留）
        if not notes:
            notes.append("量价策略基于趋势跟随，趋势反转时信号会滞后")
        return notes


# ══════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════

class VolumePriceStrategy:
    """
    量价策略主入口
    执行完整的四阶段分析链
    [P0-优化1] 支持大盘环境过滤
    """

    def __init__(self, market_env: Optional[Dict] = None):
        self.stage_detector = StageDetector()
        self.volume_analyzer = VolumeStateAnalyzer()
        self.relation_analyzer = VolumePriceRelationAnalyzer()
        self.signal_generator = VolumePriceSignalGenerator()
        self.market_env = market_env  # [P0-优化1]

    def analyze(self, df: pd.DataFrame) -> Dict:
        if df.empty or len(df) < 30:
            return {"error": "数据不足", "success": False}

        # [P0-优化1] 大盘环境权重计算
        market_mult = DEFAULT_MARKET_MULTIPLIER
        env_note = ""
        if self.market_env:
            condition = self.market_env.get('condition', 'UNKNOWN')
            if condition == 'POOR':
                market_mult = 0.70
                env_note = "大盘环境偏弱，信号乘数0.7"
            elif condition == 'UNKNOWN':
                market_mult = 0.85
                env_note = "大盘环境未知，保守处理"

        try:
            stage = self.stage_detector.detect(df)
        except Exception as e:
            logger.error(f"阶段判定异常: {e}")
            return {"error": f"阶段判定异常: {e}", "success": False}

        try:
            vol_state = self.volume_analyzer.analyze(df, stage)
        except Exception as e:
            logger.error(f"成交量分析异常: {e}")
            vol_state = VolumeState()

        try:
            relation = self.relation_analyzer.analyze(df, stage, vol_state)
        except Exception as e:
            logger.error(f"量价关系异常: {e}")
            relation = RelationResult()

        try:
            signal = self.signal_generator.generate(
                stage, vol_state, relation, df, market_mult)
        except Exception as e:
            logger.error(f"信号生成异常: {e}")
            signal = VolumePriceSignal(direction="HOLD", signal_label="分析异常", confidence=0.0)

        # 大盘环境提示加入evidence
        if env_note and signal.evidence:
            signal.evidence.insert(1, f"【大盘】{env_note}")

        return {
            "success": True,
            "stage": stage.to_dict(),
            "volume_state": vol_state.to_dict(),
            "relation": relation.to_dict(),
            "signal_output": signal.to_output_dict(""),
            "volume_price_detail": self._build_detail(stage, vol_state, relation),
        }

    def _build_detail(self, stage, vol_state, relation):
        return {"阶段判定": stage.to_dict(), "成交量状态": vol_state.to_dict(), "量价关系": relation.to_dict()}


# ══════════════════════════════════════════════
# 快捷函数
# ══════════════════════════════════════════════

def compute_volume_price_signal(ts_code: str, df: pd.DataFrame,
                                market_env: Optional[Dict] = None) -> Optional[Dict]:
    """
    计算量价信号（供 SignalComputationService 调用）
    [P0-优化1] 支持大盘环境参数传入
    """
    strategy = VolumePriceStrategy(market_env=market_env)
    result = strategy.analyze(df)
    if not result.get("success"):
        return None
    signal = result["signal_output"]
    signal["ts_code"] = ts_code
    signal["volume_price_detail"] = result["volume_price_detail"]
    return signal
