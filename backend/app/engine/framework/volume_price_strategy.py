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
    """三周期价格分位，含MA120/MA250均线参考"""
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

    @property
    def zone_label(self) -> str:
        return ZONE_LABELS.get(self.zone, "MID")

    def to_dict(self) -> Dict:
        return {
            "short_30d": round(self.short_30d, 4),
            "mid_60d": round(self.mid_60d, 4),
            "long_120d": round(self.long_120d, 4),
            "ma120": getattr(self, 'ma120', None),
            "ma250": getattr(self, 'ma250', None),
            "composite": round(self.composite, 4),
            "zone": self.zone,
            "zone_label": self.zone_label,
            "three_bloom": self.three_bloom,
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
    vol_pattern: Dict = field(default_factory=dict)  # [P1-#17] 放量缩量模式

    def to_dict(self) -> Dict:
        return {
            "volume_trend": self.trend,
            "volma_structure": self.volma_structure,
            "has_volume_tuo": self.has_volume_tuo,
            "has_volume_ya": self.has_volume_ya,
            "volume_keypoints": [round(k, 2) for k in self.volume_keypoints],
            "aux_institutional_inference": self.institutional.to_dict() if self.institutional else {},
            "vol_pattern": self.vol_pattern,  # [P1-#17]
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
    three_laws: Dict = field(default_factory=dict)
    ma_cross_area: Dict = field(default_factory=dict)
    fake_breakout: Dict = field(default_factory=dict)  # [P1-#14]
    supply_demand: Dict = field(default_factory=dict)  # [P1-#15]

    def to_dict(self) -> Dict:
        return {
            "current_pattern": f"{self.pattern_id} {self.pattern_name}" if self.pattern_id else "",
            "enhance_patterns": self.enhance_patterns,
            "divergence": self.divergence_type if self.divergence_type != "none" else "无",
            "divergence_macd_confirmed": self.divergence_macd_confirmed,
            "resonance_score": self.resonance_score,
            "aux_momentum": self.momentum.to_dict() if self.momentum else {},
            "three_laws": self.three_laws,
            "ma_cross_area": self.ma_cross_area,
            "fake_breakout": self.fake_breakout,
            "supply_demand": self.supply_demand,
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
    status: Optional['StatusRecognition'] = None

    def to_output_dict(self, ts_code: str) -> Dict:
        d = {
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
        if self.status:
            d["status_recognition"] = self.status.to_dict()
        return d

    def _map_signal(self) -> str:
        mapping = {"BUY": "BULLISH", "SELL": "BEARISH", "WATCH": "WATCH", "HOLD": "NEUTRAL"}
        return mapping.get(self.direction, "NEUTRAL")


@dataclass
class StatusRecognition:
    """现状识别 — 描述当前市场状态，非买卖建议"""
    state: str = "UNKNOWN"           # BULLISH / BEARISH / RANGING / ACCUMULATING / DISTRIBUTING
    state_label: str = ""
    trend: Dict = field(default_factory=lambda: {"direction": "", "strength": "", "stage": ""})
    momentum: Dict = field(default_factory=lambda: {"level": "", "score": 0.0})
    volume: Dict = field(default_factory=lambda: {"state": "", "structure": ""})
    support_resistance: Dict = field(default_factory=lambda: {"support": 0.0, "resistance": 0.0})
    risk_level: str = "MEDIUM"

    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)


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

# 三层周期常量
PRIMARY_CYCLE = 60     # 主决策周期（日线60日）
SECONDARY_CYCLE = 120  # 背景层周期（120日/周线）
EXECUTION_CYCLE = 20   # 执行层周期（20日）


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
    [154-批1] 50种量价形态规则引擎 — 12条纯OHLCV规则 + 8条均线规则 + 11种看涨反转 + 14种新增形态(9看跌+5整理)
    参考: 154号方案批1候选规则
    """

    def _safe_len(self, *arrays, min_len=5) -> bool:
        return all(len(a) >= min_len for a in arrays)

    def detect_all(self, closes: np.ndarray, opens: np.ndarray,
                   highs: np.ndarray, lows: np.ndarray,
                   volumes: np.ndarray) -> List[str]:
        """检测所有OHLCV规则，返回匹配的形态名列表"""
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
            # [任务-27] 11种标准K线形态(看涨反转)
            ('锤子线(预涨)', '_is_hammer'),
            ('刺透形态(预涨)', '_is_piercing_line'),
            ('晨星(预涨)', '_is_morning_star'),
            ('看涨吞没(预涨)', '_is_bullish_engulfing'),
            ('看涨孕线(预涨)', '_is_bullish_harami'),
            ('十字晨星(预涨)', '_is_doji_morning_star'),
            ('三白兵(预涨)', '_is_three_white_soldiers'),
            ('看涨捉腰带(预涨)', '_is_bullish_belt_hold'),
            ('倒锤子(预涨)', '_is_inverted_hammer'),
            ('看涨踢开(预涨)', '_is_bullish_kick'),
            ('镊子底(预涨)', '_is_tweezers_bottom'),
            # 9种看跌反转形态
            ('上吊线(预跌)', '_is_hanging_man'),
            ('乌云盖顶(预跌)', '_is_dark_cloud_cover'),
            ('黄昏星(预跌)', '_is_evening_star'),
            ('看跌吞没(预跌)', '_is_bearish_engulfing'),
            ('看跌孕线(预跌)', '_is_bearish_harami'),
            ('射击之星(预跌)', '_is_shooting_star'),
            ('三乌鸦(预跌)', '_is_three_black_crows'),
            ('看跌捉腰带(预跌)', '_is_bearish_belt_hold'),
            ('看跌踢开(预跌)', '_is_bearish_kick'),
            # 5种持续整理形态
            ('下降三法(持续)', '_is_falling_three_methods'),
            ('上升三法(持续)', '_is_rising_three_methods'),
            ('孕线十字(持续)', '_is_harami_cross'),
            ('陀螺线(持续)', '_is_spinning_top'),
            ('光头光脚(持续)', '_is_marubozu'),
            # 15种实战战法形态
            ('连续小阳盘升(黑马)', '_is_continuous_small_yang_pushup'),
            ('灼阳形态(预涨)', '_is_zhuoyang'),
            ('双针探底(预涨)', '_is_double_needle_bottom'),
            ('低位横盘突破(预涨)', '_is_low_level_break'),
            ('阳吞阴反击(预涨)', '_is_yang_swallow_yin'),
            ('低位崛起反击(预涨)', '_is_low_level_rise'),
            ('密底放量(预涨)', '_is_dense_bottom_volume'),
            ('三阳开泰(预涨)', '_is_three_yang_kaitai'),
            ('双阳缺口(预涨)', '_is_double_yang_gap'),
            ('震仓向上(预涨)', '_is_shake_up'),
            ('三连阴缩量(预涨)', '_is_three_yin_shrink'),
            ('放量跳空阴阳(预涨)', '_is_volume_jump'),
            ('振幅收敛趋稳(预涨)', '_is_amplitude_converge'),
            ('低位伏击反击(预涨)', '_is_low_ambush'),
            ('连续低位反复(预涨)', '_is_continuous_low_repeat'),
            # [Batch-C] MA30/MA120/MA250 辅助规则
            ('三线开花多头(预涨)', '_is_ma_tuo_pailie_ma30'),
            ('三线开花空头(预跌)', '_is_ma_ya_pailie_ma30'),
            ('MA30>MA60(预涨)', '_is_ma30_above_ma60'),
            ('站上MA120(预涨)', '_is_price_above_ma120'),
            ('站上MA250(预涨)', '_is_price_above_ma250'),
            # [P1-#12] 格兰维尔8法则位置版
            ('格兰维尔买点1-突破买(预涨)', '_is_granville_buy1'),
            ('格兰维尔买点2-回踩买(预涨)', '_is_granville_buy2'),
            ('格兰维尔买点3-偏离买(预涨)', '_is_granville_buy3'),
            ('格兰维尔买点4-新低买(预涨)', '_is_granville_buy4'),
            ('格兰维尔卖点1-跌破卖(预跌)', '_is_granville_sell1'),
            ('格兰维尔卖点2-反抽卖(预跌)', '_is_granville_sell2'),
            ('格兰维尔卖点3-偏离卖(预跌)', '_is_granville_sell3'),
            ('格兰维尔卖点4-新高卖(预跌)', '_is_granville_sell4'),
            # [#31] 10种新量价形态
            ('涨停形态(预涨)', '_is_limit_up'),
            ('头肩顶(预跌)', '_is_head_and_shoulders'),
            ('W底(预涨)', '_is_w_double_bottom'),
            ('上升楔形(预跌)', '_is_rising_wedge'),
            ('下降楔形(预涨)', '_is_falling_wedge'),
            ('收敛三角形(待变盘)', '_is_sym_triangle'),
            ('扩散三角形(预跌)', '_is_exp_triangle'),
            ('M顶(预跌)', '_is_m_top'),
            ('突破缺口(预涨)', '_is_gap_breakout'),
            ('衰竭缺口(预跌)', '_is_gap_exhaustion'),
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

    def _is_ma_tuo_pailie_ma30(self, closes, opens, highs, lows, volumes) -> bool:
        """均线多头排列 MA5>MA10>MA30>MA60（三线开花短线S级）"""
        if len(closes) < 61:
            return False
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        ma30 = float(np.mean(closes[-30:]))
        ma60 = float(np.mean(closes[-60:]))
        return ma5 > ma10 > ma30 > ma60

    def _is_ma_ya_pailie(self, closes, opens, highs, lows, volumes) -> bool:
        """均线空头排列 MA5<MA10<MA20<MA60（中期空头确认）"""
        if len(closes) < 61:
            return False
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:]))
        return ma5 < ma10 < ma20 < ma60

    def _is_ma_ya_pailie_ma30(self, closes, opens, highs, lows, volumes) -> bool:
        """均线空头排列 MA5<MA10<MA30<MA60（三线开花空头S级）"""
        if len(closes) < 61:
            return False
        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        ma30 = float(np.mean(closes[-30:]))
        ma60 = float(np.mean(closes[-60:]))
        return ma5 < ma10 < ma30 < ma60

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

    def _is_price_above_ma120(self, closes, opens, highs, lows, volumes) -> bool:
        """价格站上MA120（长期趋势转多）"""
        if len(closes) < 121:
            return False
        ma120 = float(np.mean(closes[-120:]))
        return closes[-1] > ma120 and closes[-2] > ma120

    def _is_price_above_ma250(self, closes, opens, highs, lows, volumes) -> bool:
        """价格站上MA250（牛熊分界线）"""
        if len(closes) < 251:
            return False
        ma250 = float(np.mean(closes[-250:]))
        return closes[-1] > ma250

    def _is_ma30_above_ma60(self, closes, opens, highs, lows, volumes) -> bool:
        """MA30 > MA60（中期趋势走多）"""
        if len(closes) < 61:
            return False
        ma30 = float(np.mean(closes[-30:]))
        ma60 = float(np.mean(closes[-60:]))
        return ma30 > ma60

    # ── [P1-#12] 格兰维尔8法则（位置版） ──

    def _is_granville_buy1(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔买点1: 突破买 — MA走平后价格上穿MA"""
        if len(closes) < 11:
            return False
        ma10 = np.mean(closes[-10:])
        ma10_prev = np.mean(closes[-11:-1])
        return ma10 > ma10_prev and closes[-1] > ma10 and closes[-2] <= ma10_prev

    def _is_granville_buy2(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔买点2: 回踩买 — 价格上穿后回踩MA不破"""
        if len(closes) < 11:
            return False
        ma10 = np.mean(closes[-10:])
        return closes[-1] > ma10 and np.min(lows[-3:]) > ma10 * 0.99 and closes[-1] > np.mean(closes[-4:-1])

    def _is_granville_buy3(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔买点3: 偏离买 — 价格在MA下方但远离MA(超卖反弹)"""
        if len(closes) < 11:
            return False
        ma10 = np.mean(closes[-10:])
        deviation = (ma10 - closes[-1]) / ma10
        return deviation > 0.08 and closes[-1] > closes[-2]  # 偏离>8%且开始反弹

    def _is_granville_buy4(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔买点4: 新低买 — 价格创新低但MA已走平"""
        if len(closes) < 21:
            return False
        ma20 = np.mean(closes[-20:])
        ma20_prev = np.mean(closes[-21:-1])
        return closes[-1] < np.min(closes[-10:-1]) and ma20 > ma20_prev * 0.998

    def _is_granville_sell1(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔卖点1: 跌破卖 — MA走平后价格下穿MA"""
        if len(closes) < 11:
            return False
        ma10 = np.mean(closes[-10:])
        ma10_prev = np.mean(closes[-11:-1])
        return ma10 < ma10_prev and closes[-1] < ma10 and closes[-2] >= ma10_prev

    def _is_granville_sell2(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔卖点2: 反抽卖 — 价格下穿后反抽MA不过"""
        if len(closes) < 11:
            return False
        ma10 = np.mean(closes[-10:])
        return closes[-1] < ma10 and closes[-2] < ma10 and            (closes[-1] > closes[-2] or closes[-2] > closes[-3])  # 正在反抽

    def _is_granville_sell3(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔卖点3: 偏离卖 — 价格在MA上方但远离MA(超买回调)"""
        if len(closes) < 11:
            return False
        ma10 = np.mean(closes[-10:])
        deviation = (closes[-1] - ma10) / ma10
        return deviation > 0.10 and closes[-1] < closes[-2]  # 偏离>10%且开始回调

    def _is_granville_sell4(self, closes, opens, highs, lows, volumes) -> bool:
        """格兰维尔卖点4: 新高卖 — 价格创新高但MA已走平"""
        if len(closes) < 21:
            return False
        ma20 = np.mean(closes[-20:])
        ma20_prev = np.mean(closes[-21:-1])
        return closes[-1] > np.max(closes[-10:-1]) and ma20 < ma20_prev * 1.002

    # ──────────────────────────────────────────────
    # 11种看涨反转K线形态（标准技术分析形态）
    # ──────────────────────────────────────────────

    # —— 1. 锤子线 (hammer) ——
    # 判定逻辑:
    #   1. 出现在下跌趋势后（近5日收盘整体走低）
    #   2. 下影线 > 实体 * 2
    #   3. 上影线 < 实体 / 3
    #   4. 实体位于K线上部（收盘在K线上半部）
    def _is_hammer(self, closes, opens, highs, lows, volumes) -> bool:
        """锤子线 — 低位长下影反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        body = abs(closes[-1] - opens[-1])
        if body <= 0:
            return False
        lower = min(opens[-1], closes[-1]) - lows[-1]
        upper = highs[-1] - max(opens[-1], closes[-1])
        # 下跌趋势背景
        downtrend = closes[-1] < closes[-6] and closes[-2] < closes[-6]
        return (lower > body * 2 and upper < body / 3 and
                closes[-1] > (highs[-1] + lows[-1]) / 2 and downtrend)

    # —— 2. 刺透形态 (piercing_line) ——
    # 判定逻辑:
    #   1. 前日：长阴线（实体 > 前5日均实体 * 1.5）
    #   2. 今日：低开（开盘 < 前日收盘）
    #   3. 今日收盘 > 前日实体中点（即前日阴线实体的50%位置）
    def _is_piercing_line(self, closes, opens, highs, lows, volumes) -> bool:
        """刺透形态 — 两日看涨反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=7):
            return False
        body1 = abs(closes[-2] - opens[-2])
        body0 = abs(closes[-1] - opens[-1])
        if body1 <= 0 or body0 <= 0:
            return False
        avg_body = float(np.mean([abs(closes[i] - opens[i]) for i in range(-6, 0)]))
        # 前日长阴
        prev_is_bear = closes[-2] < opens[-2] and body1 > avg_body * 1.5
        # 今日低开 + 收盘深入前日实体过半
        mid1 = (opens[-2] + closes[-2]) / 2
        return (prev_is_bear and opens[-1] < closes[-2] and
                closes[-1] > mid1 and closes[-1] > opens[-1])

    # —— 3. 晨星 (morning_star) ——
    # 判定逻辑:
    #   1. 第1日：长阴线
    #   2. 第2日：跳空低开小实体（可十字星），实体与前日阴线不重叠
    #   3. 第3日：跳空高开长阳，收盘 > 第1日阴线实体的50%
    def _is_morning_star(self, closes, opens, highs, lows, volumes) -> bool:
        """晨星 — 三日看涨反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=5):
            return False
        body = [abs(closes[i] - opens[i]) for i in range(-3, 0)]
        if any(b <= 0 for b in body):
            return False
        avg_body = float(np.mean(body))
        # 第1日长阴
        d1_bear = closes[-3] < opens[-3] and body[0] > avg_body * 1.2
        # 第2日小实体（晨星中间线要求实体很短，十字星可）
        d2_small = body[1] < avg_body * 0.6
        # 第2日跳空低于第1日（不重叠）
        d2_gap_down = max(closes[-2], opens[-2]) < min(closes[-3], opens[-3])
        # 第3日阳线 + 跳空高开（不重叠第2日实体）
        d3_bull = closes[-1] > opens[-1]
        d3_gap_up = min(closes[-1], opens[-1]) > max(closes[-2], opens[-2])
        # 第3日收盘 > 第1日实体中点
        mid1 = (opens[-3] + closes[-3]) / 2
        return (d1_bear and d2_small and d2_gap_down and
                d3_bull and d3_gap_up and closes[-1] > mid1)

    # —— 4. 看涨吞没 (bullish_engulfing) ——
    # 判定逻辑:
    #   1. 前日：阴线
    #   2. 今日：阳线实体完全覆盖前日实体（收盘 > 前日收盘 且 开盘 < 前日开盘）
    def _is_bullish_engulfing(self, closes, opens, highs, lows, volumes) -> bool:
        """看涨吞没 — 两日反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=4):
            return False
        prev_body_low = min(closes[-2], opens[-2])
        prev_body_high = max(closes[-2], opens[-2])
        curr_body_low = min(closes[-1], opens[-1])
        curr_body_high = max(closes[-1], opens[-1])
        return (closes[-2] < opens[-2] and          # 前日阴线
                closes[-1] > opens[-1] and            # 今日阳线
                curr_body_low < prev_body_low and     # 今日低点低于前日实体低
                curr_body_high > prev_body_high)      # 今日高点高于前日实体高

    # —— 5. 看涨孕线 (bullish_harami) ——
    # 判定逻辑:
    #   1. 前日：长阴线
    #   2. 今日：小阳线，实体完全在前日实体内部
    #     （今日开盘 > 前日收盘，今日收盘 < 前日开盘）
    def _is_bullish_harami(self, closes, opens, highs, lows, volumes) -> bool:
        """看涨孕线 — 两日反转信号"""
        if not self._safe_len(closes, opens, highs, lows, min_len=5):
            return False
        body1 = abs(closes[-2] - opens[-2])
        body0 = abs(closes[-1] - opens[-1])
        if body1 <= 0:
            return False
        avg_body = float(np.mean([abs(closes[i] - opens[i]) for i in range(-4, 0)]))
        return (closes[-2] < opens[-2] and            # 前日阴线
                body1 > avg_body * 1.2 and             # 前日长阴
                closes[-1] > opens[-1] and              # 今日阳线
                body0 < body1 * 0.6 and                 # 今日实体小
                opens[-1] > closes[-2] and              # 今日开 > 前日收
                closes[-1] < opens[-2])                 # 今日收 < 前日开

    # —— 6. 十字晨星 (doji_morning_star) ——
    # 判定逻辑:
    #   1. 第1日：长阴线
    #   2. 第2日：十字星（实体极小）+ 跳空低于第1日
    #   3. 第3日：长阳跳空高开，收盘 > 第1日阴线中点
    def _is_doji_morning_star(self, closes, opens, highs, lows, volumes) -> bool:
        """十字晨星 — 三日看涨（中间为十字星）"""
        if not self._safe_len(closes, opens, highs, lows, min_len=5):
            return False
        body = [abs(closes[i] - opens[i]) for i in range(-3, 0)]
        total_range = [highs[i] - lows[i] for i in range(-3, 0)]
        if any(b <= 0 for b in body) or any(r <= 0 for r in total_range):
            return False
        avg_body = float(np.mean(body))
        # 第1日长阴
        d1_bear = closes[-3] < opens[-3] and body[0] > avg_body * 1.2
        # 第2日十字星（实体 <= 全幅的10%）
        d2_doji = body[1] <= total_range[1] * 0.1
        d2_gap_down = max(closes[-2], opens[-2]) < min(closes[-3], opens[-3])
        # 第3日阳线 + 跳空
        d3_bull = closes[-1] > opens[-1]
        d3_gap_up = min(closes[-1], opens[-1]) > max(closes[-2], opens[-2])
        mid1 = (opens[-3] + closes[-3]) / 2
        return (d1_bear and d2_doji and d2_gap_down and
                d3_bull and d3_gap_up and closes[-1] > mid1)

    # —— 7. 三白兵 (three_white_soldiers) ——
    # 判定逻辑:
    #   1. 连续3根阳线
    #   2. 每根收盘在当日高点附近（上影线 < 实体）
    #   3. 实体长度递增或持平（不显著缩小）
    #   4. 出现在下跌或盘整后
    def _is_three_white_soldiers(self, closes, opens, highs, lows, volumes) -> bool:
        """三白兵 — 连续三阳稳步推进"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        bodies = [closes[i] - opens[i] for i in range(-3, 0)]
        if any(b <= 0 for b in bodies):
            return False
        for i in range(-3, 0):
            body = closes[i] - opens[i]
            upper = highs[i] - closes[i]
            if upper > body:
                return False
        # 实体不显著缩小
        if bodies[-3] > 0 and bodies[-2] > 0 and bodies[-1] > 0:
            return bodies[-2] >= bodies[-3] * 0.7 and bodies[-1] >= bodies[-2] * 0.7
        return False

    # —— 8. 看涨捉腰带 (bullish_belt_hold) ——
    # 判定逻辑:
    #   1. 开盘 = 最低价（或接近，差距 < 全幅的5%）
    #   2. 长阳实体
    #   3. 无明显上影线（上影线 < 实体）
    def _is_bullish_belt_hold(self, closes, opens, highs, lows, volumes) -> bool:
        """看涨捉腰带 — 开盘即最低的长阳"""
        if not self._safe_len(closes, opens, highs, lows, min_len=3):
            return False
        body = closes[-1] - opens[-1]
        if body <= 0:
            return False
        total_range = highs[-1] - lows[-1]
        if total_range <= 0:
            return False
        lower_waste = opens[-1] - lows[-1]
        upper = highs[-1] - closes[-1]
        return (lower_waste <= total_range * 0.05 and
                body > total_range * 0.6 and
                upper < body)

    # —— 9. 倒锤子 (inverted_hammer) ——
    # 判定逻辑:
    #   1. 出现在下跌趋势后
    #   2. 上影线 > 实体 * 2
    #   3. 下影线 < 实体 / 3
    def _is_inverted_hammer(self, closes, opens, highs, lows, volumes) -> bool:
        """倒锤子 — 低位长上影反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        body = abs(closes[-1] - opens[-1])
        if body <= 0:
            return False
        upper = highs[-1] - max(opens[-1], closes[-1])
        lower = min(opens[-1], closes[-1]) - lows[-1]
        downtrend = closes[-1] < closes[-6] and closes[-2] < closes[-6]
        return (upper > body * 2 and lower < body / 3 and downtrend)

    # —— 10. 看涨踢开 (bullish_kick) ——
    # 判定逻辑:
    #   1. 前日：下跌（收盘 < 开盘）
    #   2. 今日：跳空高开（开盘 > 前日最高价）且高走
    #   3. 今日收盘远离开盘价（阳线实体足够大）
    def _is_bullish_kick(self, closes, opens, highs, lows, volumes) -> bool:
        """看涨踢开 — 跳空反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=4):
            return False
        body0 = closes[-1] - opens[-1]
        if body0 <= 0:
            return False
        avg_body = float(np.mean([abs(closes[i] - opens[i]) for i in range(-3, 0)]))
        return (closes[-2] < opens[-2] and              # 前日下跌
                opens[-1] > highs[-2] and                # 跳空高开（高于前日最高）
                body0 > avg_body * 1.2)                  # 阳线实体大于近期均值

    # —— 11. 镊子底 (tweezers_bottom) ——
    # 判定逻辑:
    #   1. 连续2日最低价相同（差异在0.5%以内）
    #   2. 至少第2根为阳线
    #   3. 出现在下跌趋势末端
    def _is_tweezers_bottom(self, closes, opens, highs, lows, volumes) -> bool:
        """镊子底 — 双底测试支撑"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        low_diff = abs(lows[-1] - lows[-2]) / max(lows[-2], 1e-9)
        downtrend = closes[-1] < closes[-6] and closes[-2] < closes[-6]
        return (low_diff < 0.005 and            # 最低价近乎相同（0.5%以内）
                closes[-1] > opens[-1] and        # 第2根阳线
                downtrend)                        # 下跌背景

    # ──────────────────────────────────────────────
    # 14种新增形态（9看跌反转 + 5持续整理）
    # ──────────────────────────────────────────────

    # —— 12. 上吊线 (hanging_man) · 看跌反转 ——
    # 判定逻辑:
    #   1. 出现在连续上涨后（近5日整体走高）
    #   2. 下影线 > 实体 * 2
    #   3. 上影线 < 实体 / 3
    #   4. 实体位于K线下部（收盘靠近低点）
    def _is_hanging_man(self, closes, opens, highs, lows, volumes) -> bool:
        """上吊线 — 高位长下影见顶"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        body = abs(closes[-1] - opens[-1])
        if body <= 0:
            return False
        lower = min(opens[-1], closes[-1]) - lows[-1]
        upper = highs[-1] - max(opens[-1], closes[-1])
        # 上涨趋势背景
        uptrend = closes[-1] > closes[-6] and closes[-2] > closes[-6]
        return (lower > body * 2 and upper < body / 3 and uptrend)

    # —— 13. 乌云盖顶 (dark_cloud_cover) · 看跌反转 ——
    # 判定逻辑:
    #   1. 前日：长阳线（实体 > 前5日均实体 * 1.5）
    #   2. 今日：高开（开盘 > 前日收盘）
    #   3. 今日收盘跌破前日阳线实体的50%（即低于前日实体中点）
    def _is_dark_cloud_cover(self, closes, opens, highs, lows, volumes) -> bool:
        """乌云盖顶 — 两日看跌反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=7):
            return False
        body1 = abs(closes[-2] - opens[-2])
        body0 = abs(closes[-1] - opens[-1])
        if body1 <= 0 or body0 <= 0:
            return False
        avg_body = float(np.mean([abs(closes[i] - opens[i]) for i in range(-6, 0)]))
        # 前日长阳
        prev_is_bull = closes[-2] > opens[-2] and body1 > avg_body * 1.5
        # 今日高开 + 收盘破前日实体中点
        mid1 = (opens[-2] + closes[-2]) / 2
        return (prev_is_bull and opens[-1] > closes[-2] and
                closes[-1] < mid1 and closes[-1] < opens[-1])

    # —— 14. 黄昏星 (evening_star) · 看跌反转 ——
    # 判定逻辑:
    #   1. 第1日：长阳线
    #   2. 第2日：跳空高开小实体（与第1日不重叠）
    #   3. 第3日：跳空低开长阴，收盘 < 第1日阳线实体的50%
    def _is_evening_star(self, closes, opens, highs, lows, volumes) -> bool:
        """黄昏星 — 三日看跌反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=5):
            return False
        body = [abs(closes[i] - opens[i]) for i in range(-3, 0)]
        if any(b <= 0 for b in body):
            return False
        avg_body = float(np.mean(body))
        # 第1日长阳
        d1_bull = closes[-3] > opens[-3] and body[0] > avg_body * 1.2
        # 第2日小实体
        d2_small = body[1] < avg_body * 0.6
        d2_gap_up = min(closes[-2], opens[-2]) > max(closes[-3], opens[-3])
        # 第3日阴线 + 跳空低开
        d3_bear = closes[-1] < opens[-1]
        d3_gap_down = max(closes[-1], opens[-1]) < min(closes[-2], opens[-2])
        # 第3日收盘 < 第1日实体中点
        mid1 = (opens[-3] + closes[-3]) / 2
        return (d1_bull and d2_small and d2_gap_up and
                d3_bear and d3_gap_down and closes[-1] < mid1)

    # —— 15. 看跌吞没 (bearish_engulfing) · 看跌反转 ——
    # 判定逻辑:
    #   1. 前日：阳线
    #   2. 今日：阴线实体完全覆盖前日实体（收盘 < 前日收盘 且 开盘 > 前日开盘）
    def _is_bearish_engulfing(self, closes, opens, highs, lows, volumes) -> bool:
        """看跌吞没 — 两日反转"""
        if not self._safe_len(closes, opens, highs, lows, min_len=4):
            return False
        prev_body_low = min(closes[-2], opens[-2])
        prev_body_high = max(closes[-2], opens[-2])
        curr_body_low = min(closes[-1], opens[-1])
        curr_body_high = max(closes[-1], opens[-1])
        return (closes[-2] > opens[-2] and          # 前日阳线
                closes[-1] < opens[-1] and            # 今日阴线
                curr_body_low < prev_body_low and     # 今日低点低于前日实体
                curr_body_high > prev_body_high)      # 今日高点高于前日实体

    # —— 16. 看跌孕线 (bearish_harami) · 看跌反转 ——
    # 判定逻辑:
    #   1. 前日：长阳线
    #   2. 今日：小阴线，实体完全在前日实体内部
    #     （今日开盘 < 前日收盘，今日收盘 > 前日开盘）
    def _is_bearish_harami(self, closes, opens, highs, lows, volumes) -> bool:
        """看跌孕线 — 两日反转信号"""
        if not self._safe_len(closes, opens, highs, lows, min_len=5):
            return False
        body1 = abs(closes[-2] - opens[-2])
        body0 = abs(closes[-1] - opens[-1])
        if body1 <= 0:
            return False
        avg_body = float(np.mean([abs(closes[i] - opens[i]) for i in range(-4, 0)]))
        return (closes[-2] > opens[-2] and            # 前日阳线
                body1 > avg_body * 1.2 and             # 前日长阳
                closes[-1] < opens[-1] and              # 今日阴线
                body0 < body1 * 0.6 and                 # 今日实体小
                opens[-1] < closes[-2] and              # 今日开 < 前日收
                closes[-1] > opens[-2])                 # 今日收 > 前日开

    # —— 17. 射击之星 (shooting_star) · 看跌反转 ——
    # 判定逻辑:
    #   1. 出现在上涨趋势后
    #   2. 上影线 > 实体 * 2
    #   3. 下影线 < 实体 / 3
    def _is_shooting_star(self, closes, opens, highs, lows, volumes) -> bool:
        """射击之星 — 高位长上影见顶"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        body = abs(closes[-1] - opens[-1])
        if body <= 0:
            return False
        upper = highs[-1] - max(opens[-1], closes[-1])
        lower = min(opens[-1], closes[-1]) - lows[-1]
        uptrend = closes[-1] > closes[-6] and closes[-2] > closes[-6]
        return (upper > body * 2 and lower < body / 3 and uptrend)

    # —— 18. 三乌鸦 (three_black_crows) · 看跌反转 ——
    # 判定逻辑:
    #   1. 连续3根阴线
    #   2. 每根收盘在当日低点附近（下影线 < 实体）
    #   3. 实体长度相近（不显著缩小）
    #   4. 出现在上涨后
    def _is_three_black_crows(self, closes, opens, highs, lows, volumes) -> bool:
        """三乌鸦 — 连续三阴下跌"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        bodies = [opens[i] - closes[i] for i in range(-3, 0)]  # 阴线实体为正
        if any(b <= 0 for b in bodies):
            return False
        for i in range(-3, 0):
            body = opens[i] - closes[i]
            lower = closes[i] - lows[i]
            if lower > body:
                return False
        # 实体不显著缩小
        if bodies[-3] > 0 and bodies[-2] > 0 and bodies[-1] > 0:
            return bodies[-2] >= bodies[-3] * 0.7 and bodies[-1] >= bodies[-2] * 0.7
        return False

    # —— 19. 看跌捉腰带 (bearish_belt_hold) · 看跌反转 ——
    # 判定逻辑:
    #   1. 开盘 = 最高价（或接近，差距 < 全幅的5%）
    #   2. 长阴实体
    #   3. 无明显下影线（下影线 < 实体）
    def _is_bearish_belt_hold(self, closes, opens, highs, lows, volumes) -> bool:
        """看跌捉腰带 — 开盘即最高的长阴"""
        if not self._safe_len(closes, opens, highs, lows, min_len=3):
            return False
        body = opens[-1] - closes[-1]  # 阴线实体
        if body <= 0:
            return False
        total_range = highs[-1] - lows[-1]
        if total_range <= 0:
            return False
        upper_waste = highs[-1] - opens[-1]
        lower = closes[-1] - lows[-1]
        return (upper_waste <= total_range * 0.05 and
                body > total_range * 0.6 and
                lower < body)

    # —— 20. 看跌踢开 (bearish_kick) · 看跌反转 ——
    # 判定逻辑:
    #   1. 前日：上涨（收盘 > 开盘）
    #   2. 今日：跳空低开（开盘 < 前日最低价）且低走
    #   3. 今日阴线实体足够大（> 近3日均实体1.2倍）
    def _is_bearish_kick(self, closes, opens, highs, lows, volumes) -> bool:
        """看跌踢开 — 跳空反转下杀"""
        if not self._safe_len(closes, opens, highs, lows, min_len=4):
            return False
        body0 = opens[-1] - closes[-1]  # 阴线实体
        if body0 <= 0:
            return False
        avg_body = float(np.mean([abs(closes[i] - opens[i]) for i in range(-3, 0)]))
        return (closes[-2] > opens[-2] and              # 前日上涨
                opens[-1] < lows[-2] and                # 跳空低开（低于前日最低）
                body0 > avg_body * 1.2)                 # 阴线实体大于近期均值

    # —— 21. 下降三法 (falling_three_methods) · 持续整理 ——
    # 判定逻辑:
    #   1. 第1日：长阴线
    #   2. 第2-4日：3根小阳线，实体均在首日阴线范围内（不创新高不创新低）
    #   3. 第5日：长阴线跌破前4日低点，确认趋势
    def _is_falling_three_methods(self, closes, opens, highs, lows, volumes) -> bool:
        """下降三法 — 持续下跌中继"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        # 第1日长阴
        d1_body = opens[-5] - closes[-5]
        if d1_body <= 0:
            return False
        d1_range = highs[-5] - lows[-5]
        if d1_range <= 0:
            return False
        if d1_body < d1_range * 0.6:
            return False
        # 中间3日小阳线（部分可以阴线，但以阳线为主；实体在前日阴线范围内）
        d1_low = lows[-5]
        d1_high = highs[-5]
        for i in range(-4, -1):
            body_i = closes[i] - opens[i]
            if body_i <= 0:
                return False
            if highs[i] > d1_high or lows[i] < d1_low:
                return False
        # 第5日长阴破低
        d5_body = opens[-1] - closes[-1]
        if d5_body <= 0:
            return False
        d5_range = highs[-1] - lows[-1]
        if d5_range <= 0:
            return False
        if d5_body < d5_range * 0.6:
            return False
        return closes[-1] < d1_low

    # —— 22. 上升三法 (rising_three_methods) · 持续整理 ——
    # 判定逻辑:
    #   1. 第1日：长阳线
    #   2. 第2-4日：3根小阴线，实体均在首日阳线范围内（不创新低不创新高）
    #   3. 第5日：长阳线突破前4日高点，确认趋势
    def _is_rising_three_methods(self, closes, opens, highs, lows, volumes) -> bool:
        """上升三法 — 持续上涨中继"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        # 第1日长阳
        d1_body = closes[-5] - opens[-5]
        if d1_body <= 0:
            return False
        d1_range = highs[-5] - lows[-5]
        if d1_range <= 0:
            return False
        if d1_body < d1_range * 0.6:
            return False
        # 中间3日小阴线（实体在首日阳线范围内）
        d1_low = lows[-5]
        d1_high = highs[-5]
        for i in range(-4, -1):
            body_i = opens[i] - closes[i]
            if body_i <= 0:
                return False
            if highs[i] > d1_high or lows[i] < d1_low:
                return False
        # 第5日长阳破高
        d5_body = closes[-1] - opens[-1]
        if d5_body <= 0:
            return False
        d5_range = highs[-1] - lows[-1]
        if d5_range <= 0:
            return False
        if d5_body < d5_range * 0.6:
            return False
        return closes[-1] > d1_high

    # —— 23. 孕线十字 (harami_cross) · 持续整理 ——
    # 判定逻辑:
    #   1. 前日：长实体（阳或阴均可，实体 > 均值的1.2倍）
    #   2. 今日：十字星（实体极小，<= 全幅的10%；收盘接近开盘）
    def _is_harami_cross(self, closes, opens, highs, lows, volumes) -> bool:
        """孕线十字 — 趋势犹豫信号"""
        if not self._safe_len(closes, opens, highs, lows, min_len=5):
            return False
        body1 = abs(closes[-2] - opens[-2])
        body0 = abs(closes[-1] - opens[-1])
        total_range = highs[-1] - lows[-1]
        if body1 <= 0 or total_range <= 0:
            return False
        avg_body = float(np.mean([abs(closes[i] - opens[i]) for i in range(-4, 0)]))
        # 前日长实体
        prev_long = body1 > avg_body * 1.2
        # 今日十字星：实体 < 全幅的10%
        doji = body0 <= total_range * 0.1
        # 今日实体在前日实体内部
        prev_high = max(opens[-2], closes[-2])
        prev_low = min(opens[-2], closes[-2])
        curr_high = max(opens[-1], closes[-1])
        curr_low = min(opens[-1], closes[-1])
        return prev_long and doji and curr_high < prev_high and curr_low > prev_low

    # —— 24. 陀螺线 (spinning_top) · 持续整理 ——
    # 判定逻辑:
    #   1. 实体小（实体 < 全幅的33%）
    #   2. 上影线和下影线均较长（都 > 实体 * 2）
    #   3. 上下影线长度相近（长的那根不超过短的2倍）
    def _is_spinning_top(self, closes, opens, highs, lows, volumes) -> bool:
        """陀螺线 — 多空平衡犹豫"""
        if not self._safe_len(closes, opens, highs, lows, min_len=3):
            return False
        body = abs(closes[-1] - opens[-1])
        total_range = highs[-1] - lows[-1]
        if total_range <= 0:
            return False
        # 实体小
        if body > total_range * 0.33:
            return False
        upper = highs[-1] - max(opens[-1], closes[-1])
        lower = min(opens[-1], closes[-1]) - lows[-1]
        if body <= 0:
            return upper > 0 and lower > 0 and upper >= total_range * 0.2 and lower >= total_range * 0.2
        # 上下影线均 > 实体 * 2
        if upper < body * 2 or lower < body * 2:
            return False
        # 上下影长度相近
        max_shadow = max(upper, lower)
        min_shadow = min(upper, lower)
        return max_shadow <= min_shadow * 2 if min_shadow > 0 else False

    # —— 25. 光头光脚 (marubozu) · 持续整理/确认 ——
    # 判定逻辑:
    #   1. 阳线：开盘 = 最低价且收盘 = 最高价（上下影线均极短 < 全幅的3%）
    #   2. 阴线：开盘 = 最高价且收盘 = 最低价（上下影线均极短 < 全幅的3%）
    def _is_marubozu(self, closes, opens, highs, lows, volumes) -> bool:
        """光头光脚 — 单边强趋势"""
        if not self._safe_len(closes, opens, highs, lows, min_len=3):
            return False
        total_range = highs[-1] - lows[-1]
        if total_range <= 0:
            return False
        lower_shadow = min(opens[-1], closes[-1]) - lows[-1]
        upper_shadow = highs[-1] - max(opens[-1], closes[-1])
        shadow_threshold = total_range * 0.03
        if lower_shadow > shadow_threshold or upper_shadow > shadow_threshold:
            return False
        # 阳线或阴线均可
        return closes[-1] != opens[-1]

    # ──────────────────────────────────────────────
    # 15种实战战法形态
    # ──────────────────────────────────────────────

    # —— 1. 连续小阳盘升 (continuous_small_yang_pushup) ——
    # 判定逻辑:
    #   1. 5日内至少4根小阳线（涨幅<2%）
    #   2. 成交量温和放大（逐日递增）
    def _is_continuous_small_yang_pushup(self, closes, opens, highs, lows, volumes) -> bool:
        """连续小阳盘升 — 小阳线渐次推升+量能递增"""
        if not self._safe_len(closes, opens, volumes, min_len=6):
            return False
        small_yang_count = 0
        for i in range(-5, 0):
            if closes[i] > opens[i]:
                pct = (closes[i] - opens[i]) / opens[i]
                if pct < 0.02:
                    small_yang_count += 1
        if small_yang_count < 4:
            return False
        # 成交量逐日递增
        for i in range(-4, 0):
            if volumes[i] <= volumes[i-1]:
                return False
        return True

    # —— 2. 灼阳形态 (zhuoyang) ——
    # 判定逻辑:
    #   1. 横盘整理后出现（前10日振幅<25%）
    #   2. 今日放量长阳（实体>5%）
    #   3. 成交量>5日均量的2倍
    def _is_zhuoyang(self, closes, opens, highs, lows, volumes) -> bool:
        """灼阳形态 — 横盘整理后放量长阳突破"""
        if not self._safe_len(closes, opens, highs, lows, volumes, min_len=11):
            return False
        # 前10日横盘判断
        range_10 = (np.max(highs[-11:-1]) - np.min(lows[-11:-1])) / np.min(lows[-11:-1])
        if range_10 > 0.25:
            return False
        body_pct = (closes[-1] - opens[-1]) / opens[-1]
        if body_pct <= 0.05:
            return False
        vol_ma5 = float(np.mean(volumes[-6:-1]))
        if vol_ma5 <= 0:
            return False
        return volumes[-1] > vol_ma5 * 2

    # —— 3. 双针探底 (double_needle_bottom) ——
    # 判定逻辑:
    #   1. 连续2日长下影线（下影>实体2倍）
    #   2. 两日最低价差值<1%
    #   3. 出现在下跌后（近日整体走低）
    def _is_double_needle_bottom(self, closes, opens, highs, lows, volumes) -> bool:
        """双针探底 — 连续2日长下影试探底部支撑"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        for i in range(-2, 0):
            body = abs(closes[i] - opens[i])
            if body <= 0:
                return False
            lower = min(opens[i], closes[i]) - lows[i]
            if lower <= body * 2:
                return False
        low_diff = abs(lows[-1] - lows[-2]) / max(lows[-2], 1e-9)
        if low_diff >= 0.01:
            return False
        # 下跌后
        downtrend = closes[-1] < closes[-6] and closes[-2] < closes[-3]
        return downtrend

    # —— 4. 低位横盘突破 (low_level_break) ——
    # 判定逻辑:
    #   1. 20日振幅<15%（横盘整理）
    #   2. 今日收盘创20日新高
    #   3. 成交量>20日均量2倍
    def _is_low_level_break(self, closes, opens, highs, lows, volumes) -> bool:
        """低位横盘突破 — 窄幅整理后放量创新高"""
        if not self._safe_len(closes, highs, lows, volumes, min_len=22):
            return False
        amplitude = (np.max(highs[-21:-1]) - np.min(lows[-21:-1])) / np.min(lows[-21:-1])
        if amplitude >= 0.15:
            return False
        if closes[-1] <= np.max(highs[-21:-1]):
            return False
        vol_ma20 = float(np.mean(volumes[-21:-1]))
        if vol_ma20 <= 0:
            return False
        return volumes[-1] > vol_ma20 * 2

    # —— 5. 阳吞阴反击 (yang_swallow_yin) ——
    # 判定逻辑:
    #   1. 前日：阴线
    #   2. 今日：阳线实体完全覆盖前日阴线实体
    #   3. 今日成交量>前日1.5倍
    def _is_yang_swallow_yin(self, closes, opens, highs, lows, volumes) -> bool:
        """阳吞阴反击 — 阳线实体完全吞没前日阴线实体+放量"""
        if not self._safe_len(closes, opens, volumes, min_len=3):
            return False
        if closes[-2] >= opens[-2]:
            return False
        prev_low = min(closes[-2], opens[-2])
        prev_high = max(closes[-2], opens[-2])
        curr_low = min(closes[-1], opens[-1])
        curr_high = max(closes[-1], opens[-1])
        if closes[-1] <= opens[-1]:
            return False
        if curr_low > prev_low or curr_high < prev_high:
            return False
        if volumes[-2] <= 0:
            return False
        return volumes[-1] > volumes[-2] * 1.5

    # —— 6. 低位崛起反击 (low_level_rise) ——
    # 判定逻辑:
    #   1. 股价在60日低位（<30%分位）
    #   2. 今日长阳实体>5%
    #   3. 成交量>5日均量3倍
    def _is_low_level_rise(self, closes, opens, highs, lows, volumes) -> bool:
        """低位崛起反击 — 低位放巨量长阳启动"""
        if not self._safe_len(closes, opens, highs, lows, volumes, min_len=62):
            return False
        # 60日分位
        pos_60 = (closes[-1] - np.min(lows[-60:])) / max(np.max(highs[-60:]) - np.min(lows[-60:]), 1e-9)
        if pos_60 >= 0.30:
            return False
        body_pct = (closes[-1] - opens[-1]) / opens[-1]
        if body_pct <= 0.05:
            return False
        vol_ma5 = float(np.mean(volumes[-6:-1]))
        if vol_ma5 <= 0:
            return False
        return volumes[-1] > vol_ma5 * 3

    # —— 7. 密底放量 (dense_bottom_volume) ——
    # 判定逻辑:
    #   1. 10日内价格波动<8%（密底窄幅）
    #   2. 成交量逐5日放大
    #   3. 今日收阳
    def _is_dense_bottom_volume(self, closes, opens, highs, lows, volumes) -> bool:
        """密底放量 — 窄幅震荡后逐量放大+收阳"""
        if not self._safe_len(closes, opens, highs, lows, volumes, min_len=11):
            return False
        density = (np.max(highs[-11:-1]) - np.min(lows[-11:-1])) / np.min(lows[-11:-1])
        if density >= 0.08:
            return False
        # 成交量逐5日放大
        for i in range(-4, 0):
            if volumes[i] <= volumes[i-1]:
                return False
        return closes[-1] > opens[-1]

    # —— 8. 三阳开泰 (three_yang_kaitai) ——
    # 判定逻辑:
    #   1. 连续3阳线
    #   2. 实体依次增大
    #   3. 成交量依次增大
    #   4. 3日总涨幅>6%
    def _is_three_yang_kaitai(self, closes, opens, highs, lows, volumes) -> bool:
        """三阳开泰 — 连续三阳实体和量能递次放大"""
        if not self._safe_len(closes, opens, volumes, min_len=4):
            return False
        bodies = [closes[i] - opens[i] for i in range(-3, 0)]
        if any(b <= 0 for b in bodies):
            return False
        # 实体依次增大
        if not (bodies[-3] < bodies[-2] < bodies[-1]):
            return False
        # 成交量依次增大
        for i in range(-2, 0):
            if volumes[i] <= volumes[i-1]:
                return False
        total_gain = (closes[-1] - closes[-4]) / closes[-4]
        return total_gain > 0.06

    # —— 9. 双阳缺口 (double_yang_gap) ——
    # 判定逻辑:
    #   1. 连续2阳
    #   2. 第2日开盘>第1日收盘（向上缺口）
    #   3. 缺口未被回补（第2日最低>=第1日收盘）
    #   4. 成交量>5日均量
    def _is_double_yang_gap(self, closes, opens, highs, lows, volumes) -> bool:
        """双阳缺口 — 连续两阳+向上跳空缺口未回补"""
        if not self._safe_len(closes, opens, lows, volumes, min_len=7):
            return False
        if closes[-2] <= opens[-2] or closes[-1] <= opens[-1]:
            return False
        if opens[-1] <= closes[-2]:
            return False
        if lows[-1] < closes[-2]:
            return False
        vol_ma5 = float(np.mean(volumes[-6:-1]))
        if vol_ma5 <= 0:
            return False
        return volumes[-1] > vol_ma5

    # —— 10. 震仓向上 (shake_up) ——
    # 判定逻辑:
    #   1. 前日长阴（跌幅>3%）
    #   2. 今日长阳收复全部失地（涨幅>前日跌幅）
    #   3. 今日成交量放大（>5日均量）
    def _is_shake_up(self, closes, opens, highs, lows, volumes) -> bool:
        """震仓向上 — 前日长阴今日长阳完全反包+放量"""
        if not self._safe_len(closes, opens, volumes, min_len=4):
            return False
        prev_drop = (closes[-2] - opens[-2]) / opens[-2]
        if prev_drop >= -0.03:
            return False
        today_gain = (closes[-1] - opens[-1]) / opens[-1]
        if today_gain <= abs(prev_drop):
            return False
        vol_ma5 = float(np.mean(volumes[-6:-1]))
        if vol_ma5 <= 0:
            return False
        return volumes[-1] > vol_ma5

    # —— 11. 三连阴缩量 (three_yin_shrink) ——
    # 判定逻辑:
    #   1. 连续3阴线
    #   2. 成交量逐日递减
    #   3. 3日总跌幅<5%（非恐慌性）
    def _is_three_yin_shrink(self, closes, opens, highs, lows, volumes) -> bool:
        """三连阴缩量 — 连续3阴+量能递减+跌幅有限"""
        if not self._safe_len(closes, opens, volumes, min_len=4):
            return False
        for i in range(-3, 0):
            if closes[i] >= opens[i]:
                return False
        # 成交量逐日递减
        for i in range(-2, 0):
            if volumes[i] >= volumes[i-1]:
                return False
        total_drop = (closes[-4] - closes[-1]) / closes[-4]
        return total_drop < 0.05

    # —— 12. 放量跳空阴阳 (volume_jump) ——
    # 判定逻辑:
    #   1. 跳空缺口（开盘>前日最高 或 开盘<前日最低）
    #   2. 成交量>10日均量2倍
    #   3. 阴阳均可
    def _is_volume_jump(self, closes, opens, highs, lows, volumes) -> bool:
        """放量跳空阴阳 — 跳空缺口+巨量（方向不限）"""
        if not self._safe_len(closes, opens, highs, lows, volumes, min_len=12):
            return False
        gap_up = opens[-1] > highs[-2]
        gap_down = opens[-1] < lows[-2]
        if not gap_up and not gap_down:
            return False
        vol_ma10 = float(np.mean(volumes[-11:-1]))
        if vol_ma10 <= 0:
            return False
        return volumes[-1] > vol_ma10 * 2

    # —— 13. 振幅收敛趋稳 (amplitude_converge) ——
    # 判定逻辑:
    #   1. 5日振幅逐日递减
    #   2. 今日振幅<5日均幅的50%
    #   3. 收盘在中位（收盘在当日区间中位附近）
    def _is_amplitude_converge(self, closes, opens, highs, lows, volumes) -> bool:
        """振幅收敛趋稳 — 波动率逐日递减+收盘在中位"""
        if not self._safe_len(closes, opens, highs, lows, min_len=6):
            return False
        # 5日振幅逐日递减
        amps = [(highs[i] - lows[i]) / max(lows[i], 1e-9) for i in range(-5, 0)]
        for i in range(1, 5):
            if amps[i] >= amps[i-1]:
                return False
        today_amp = amps[-1]
        avg_amp = float(np.mean(amps))
        if today_amp >= avg_amp * 0.5:
            return False
        # 收盘在中位
        mid = (highs[-1] + lows[-1]) / 2
        pos = (closes[-1] - lows[-1]) / max(highs[-1] - lows[-1], 1e-9)
        return 0.35 <= pos <= 0.65

    # —— 14. 低位伏击反击 (low_ambush) ——
    # 判定逻辑:
    #   1. 连续5日窄幅波动（每日振幅<3%）
    #   2. 处于60日低位（分位<30%）
    #   3. 今日放量收阳
    def _is_low_ambush(self, closes, opens, highs, lows, volumes) -> bool:
        """低位伏击反击 — 窄幅横盘低位+放量收阳"""
        if not self._safe_len(closes, opens, highs, lows, volumes, min_len=62):
            return False
        # 连续5日窄幅
        for i in range(-5, 0):
            amp = (highs[i] - lows[i]) / max(lows[i], 1e-9)
            if amp >= 0.03:
                return False
        # 60日低位
        pos_60 = (closes[-1] - np.min(lows[-60:])) / max(np.max(highs[-60:]) - np.min(lows[-60:]), 1e-9)
        if pos_60 >= 0.30:
            return False
        if closes[-1] <= opens[-1]:
            return False
        vol_ma5 = float(np.mean(volumes[-6:-1]))
        if vol_ma5 <= 0:
            return False
        return volumes[-1] > vol_ma5 * 1.5

    # —— 15. 连续低位反复 (continuous_low_repeat) ——
    # 判定逻辑:
    #   1. 10日内3次以上触及同一支撑位（最低价差值<1.5%）
    #   2. 每次触及后反弹
    #   3. 成交量逐步萎缩后今日放大
    def _is_continuous_low_repeat(self, closes, opens, highs, lows, volumes) -> bool:
        """连续低位反复 — 多次探底同一支撑+量能萎缩后放大"""
        if not self._safe_len(closes, opens, highs, lows, volumes, min_len=11):
            return False
        # 找10日内最低价
        lows_10 = lows[-11:-1]
        min_low = np.min(lows_10)
        touch_count = 0
        for i in range(-10, 0):
            if abs(lows[i] - min_low) / max(min_low, 1e-9) < 0.015:
                touch_count += 1
                # 检查每次触及后是否反弹（次日收阳或跌幅<触及日跌幅）
                if i < -1:
                    if closes[i+1] > opens[i+1]:
                        touch_count += 0
        if touch_count < 3:
            return False
        # 成交量逐步萎缩后今日放大
        vol_decreasing = True
        for i in range(-5, -1):
            if volumes[i] >= volumes[i-1]:
                vol_decreasing = False
                break
        if not vol_decreasing:
            return False
        return volumes[-1] > np.mean(volumes[-6:-1]) * 1.5

    # ── [#31] 新10种量价形态 ──

    def _is_limit_up(self, closes, opens, highs, lows, volumes) -> bool:
        """涨停形态(近似)：当日收盘=最高价*0.995且涨幅>9.5%"""
        if not self._safe_len(closes, opens, highs, min_len=3):
            return False
        # 当日收盘接近最高价（允许0.5%误差）
        close_equals_high = closes[-1] >= highs[-1] * 0.995
        # 涨幅>9.5%
        gain = (closes[-1] - closes[-2]) / max(closes[-2], 1e-9)
        return close_equals_high and gain > 0.095

    def _is_head_and_shoulders(self, closes, opens, highs, lows, volumes) -> bool:
        """头肩顶(近似)：三峰中间最高+两侧低+跌破颈线"""
        if not self._safe_len(closes, highs, lows, min_len=30):
            return False
        # 取最近30日分成3个10日窗口找高点
        left_high = np.max(highs[-30:-20])
        head_high = np.max(highs[-20:-10])
        right_high = np.max(highs[-10:])
        # 头比左右肩高
        if not (head_high > left_high and head_high > right_high):
            return False
        # 左右肩接近（相差<5%）
        shoulder_diff = abs(left_high - right_high) / max(left_high, 1e-9)
        if shoulder_diff > 0.05:
            return False
        # 颈线取左右肩之间最低点
        neckline = np.min(lows[-20:-10])
        # 跌破颈线
        return closes[-1] < neckline

    def _is_w_double_bottom(self, closes, opens, highs, lows, volumes) -> bool:
        """W底：两个相近低点+中间反弹+突破颈线"""
        if not self._safe_len(closes, highs, lows, min_len=30):
            return False
        # 最近20日找两个低点
        left_low = np.min(lows[-20:-10])
        right_low = np.min(lows[-10:])
        # 两低点接近（相差<3%）
        low_diff = abs(left_low - right_low) / max(left_low, 1e-9)
        if low_diff > 0.03:
            return False
        # 中间有反弹（10-15日高点 > 低点*1.05）
        middle_high = np.max(highs[-15:-5])
        if middle_high < left_low * 1.05:
            return False
        # 颈线取中间高点
        neckline = middle_high
        return closes[-1] > neckline

    def _is_rising_wedge(self, closes, opens, highs, lows, volumes) -> bool:
        """上升楔形：高点渐高+低点渐高+幅度收窄"""
        if not self._safe_len(closes, highs, lows, min_len=15):
            return False
        # 分2段各取高低点
        h1 = np.max(highs[-15:-7])
        h2 = np.max(highs[-7:])
        l1 = np.min(lows[-15:-7])
        l2 = np.min(lows[-7:])
        # 高点升高、低点升高
        if h2 <= h1 or l2 <= l1:
            return False
        # 幅度收窄（第二段振幅 < 第一段振幅*0.8）
        range1 = (h1 - l1) / max(l1, 1e-9)
        range2 = (h2 - l2) / max(l2, 1e-9)
        return range2 < range1 * 0.8

    def _is_falling_wedge(self, closes, opens, highs, lows, volumes) -> bool:
        """下降楔形：高点渐低+低点渐低+幅度收窄"""
        if not self._safe_len(closes, highs, lows, min_len=15):
            return False
        h1 = np.max(highs[-15:-7])
        h2 = np.max(highs[-7:])
        l1 = np.min(lows[-15:-7])
        l2 = np.min(lows[-7:])
        # 高点降低、低点降低
        if h2 >= h1 or l2 >= l1:
            return False
        # 幅度收窄
        range1 = (h1 - l1) / max(l1, 1e-9)
        range2 = (h2 - l2) / max(l2, 1e-9)
        return range2 < range1 * 0.8

    def _is_sym_triangle(self, closes, opens, highs, lows, volumes) -> bool:
        """收敛三角形：高点降低+低点升高"""
        if not self._safe_len(closes, highs, lows, min_len=15):
            return False
        h1 = np.max(highs[-15:-7])
        h2 = np.max(highs[-7:])
        l1 = np.min(lows[-15:-7])
        l2 = np.min(lows[-7:])
        # 高点降低、低点升高
        if h2 >= h1 or l2 <= l1:
            return False
        # 确认幅度明显收敛（第二段振幅 < 第一段振幅）
        range1 = (h1 - l1) / max(l1, 1e-9)
        range2 = (h2 - l2) / max(l2, 1e-9)
        return range2 < range1

    def _is_exp_triangle(self, closes, opens, highs, lows, volumes) -> bool:
        """扩散三角形：高点升高+低点降低"""
        if not self._safe_len(closes, highs, lows, min_len=15):
            return False
        h1 = np.max(highs[-15:-7])
        h2 = np.max(highs[-7:])
        l1 = np.min(lows[-15:-7])
        l2 = np.min(lows[-7:])
        # 高点升高、低点降低（喇叭口）
        if h2 <= h1 or l2 >= l1:
            return False
        # 幅度明显扩大
        range1 = (h1 - l1) / max(l1, 1e-9)
        range2 = (h2 - l2) / max(l2, 1e-9)
        return range2 > range1 * 1.2

    def _is_m_top(self, closes, opens, highs, lows, volumes) -> bool:
        """M顶：两个相近高点+中间回落+跌破颈线"""
        if not self._safe_len(closes, highs, lows, min_len=30):
            return False
        left_high = np.max(highs[-30:-15])
        right_high = np.max(highs[-15:])
        # 两高点接近（相差<3%）
        high_diff = abs(left_high - right_high) / max(left_high, 1e-9)
        if high_diff > 0.03:
            return False
        # 中间有回落
        mid_low = np.min(lows[-22:-8])
        if mid_low > left_high * 0.97:
            return False
        # 颈线取中间最低点
        neckline = mid_low
        return closes[-1] < neckline

    def _is_gap_breakout(self, closes, opens, highs, lows, volumes) -> bool:
        """突破缺口：跳空高开且当日未回补"""
        if not self._safe_len(closes, opens, highs, lows, min_len=3):
            return False
        # 今日最低 > 昨日最高 = 向上跳空未回补
        gap_up = lows[-1] > highs[-2]
        if not gap_up:
            return False
        # 确认今日收阳（力度）
        body_pct = (closes[-1] - opens[-1]) / max(opens[-1], 1e-9)
        return body_pct > 0.02

    def _is_gap_exhaustion(self, closes, opens, highs, lows, volumes) -> bool:
        """衰竭缺口：跳空高开但当日缩量+收盘回补部分缺口"""
        if not self._safe_len(closes, opens, highs, lows, volumes, min_len=5):
            return False
        gap_up = opens[-1] > highs[-2]
        if not gap_up:
            return False
        # 当日成交量小于5日均量
        vol_ma5 = float(np.mean(volumes[-6:-1])) if len(volumes) > 6 else float(np.mean(volumes[:-1]))
        if vol_ma5 <= 0:
            return False
        vol_shrink = volumes[-1] < vol_ma5 * 0.85
        if not vol_shrink:
            return False
        # 收盘回补了部分缺口（收盘价 < 今日最高价 且 收盘 < 开盘价 的一部分）
        gap_partial_fill = closes[-1] < highs[-1] and closes[-1] < opens[-1] * 0.995
        return gap_partial_fill

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

        # [P1-#11] 三线开花判定
        if len(closes) >= 31:
            three_bloom = self.recognize_three_bloom(closes)
        else:
            three_bloom = {'bloom': False, 'cross_state': '数据不足'}

        valuation = self._calc_valuation_zones(closes, highs, lows)
        valuation.three_bloom = three_bloom
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
        # MA120/MA250 辅助参考
        ma120_val = float(np.mean(closes[-120:])) if len(closes) >= 120 else None
        ma250_val = float(np.mean(closes[-250:])) if len(closes) >= 250 else None
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
        return ValuationZones(short_30d=short, mid_60d=mid, long_120d=long_,
                              ma120=ma120_val, ma250=ma250_val, zone=zone)

    def recognize_three_bloom(self, closes: np.ndarray) -> Dict:
        """[P1-#11] 三线开花状态判定

        均线多头排列(MA5>MA10>MA30)构成"三线开花"

        Returns:
            dict with 'bloom' (bool), 'cross_state', 'ma_values', position info
        """
        if len(closes) < 31:
            return {'bloom': False, 'cross_state': '数据不足'}

        ma5 = float(np.mean(closes[-5:]))
        ma10 = float(np.mean(closes[-10:]))
        ma30 = float(np.mean(closes[-30:]))
        ma60 = float(np.mean(closes[-60:])) if len(closes) >= 60 else None
        ma120 = float(np.mean(closes[-120:])) if len(closes) >= 120 else None
        ma250 = float(np.mean(closes[-250:])) if len(closes) >= 250 else None

        # 三线开花核心判定
        if ma5 > ma10 > ma30:
            bloom = True
            cross_state = '多头三线开花'
        elif ma5 < ma10 < ma30:
            bloom = False
            cross_state = '空头三线收拢'
        else:
            bloom = False
            cross_state = '均线缠绕'

        # 价格相对位置
        latest_close = float(closes[-1])
        above_ma30 = latest_close > ma30
        above_ma60 = latest_close > ma60 if ma60 is not None else False

        return {
            'bloom': bloom,
            'cross_state': cross_state,
            'ma5': round(ma5, 2),
            'ma10': round(ma10, 2),
            'ma30': round(ma30, 2),
            'ma60': round(ma60, 2) if ma60 else None,
            'above_ma30': above_ma30,
            'above_ma60': above_ma60,
            'position': '上方' if above_ma30 else '下方' if ma30 else '附近',
        }

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

    def recognize_market_condition(self, df: pd.DataFrame) -> Dict:
        """识别基础市场状态: TRENDING_BULL/TRENDING_BEAR/RANGING/HIGH_VOL"""
        closes = df['close'].astype(float).values if 'close' in df.columns else df['close'].values
        highs = df['high'].astype(float).values if 'high' in df.columns else np.array([])
        lows = df['low'].astype(float).values if 'low' in df.columns else np.array([])

        if len(closes) < 60:
            return {'market_state': 'UNKNOWN', 'confidence': 0.0}

        # 1. 均线排列判断趋势方向
        ma5 = np.mean(closes[-5:])
        ma10 = np.mean(closes[-10:])
        ma20 = np.mean(closes[-20:])
        ma60 = np.mean(closes[-60:])
        ma120 = np.mean(closes[-120:]) if len(closes) >= 120 else ma60

        ma_trend = 'neutral'
        if ma5 > ma10 > ma20 > ma60:  # 多头排列
            ma_trend = 'bullish'
        elif ma5 < ma10 < ma20 < ma60:  # 空头排列
            ma_trend = 'bearish'

        # 2. 布林带宽度判定波动性
        if len(highs) >= 20 and len(lows) >= 20:
            bb_width = (np.mean(highs[-20:]) - np.mean(lows[-20:])) / np.mean(closes[-20:]) * 100
        else:
            bb_width = 0

        # 3. ATR相对值判定波动性
        if len(closes) >= 14:
            tr_values = []
            for i in range(-14, 0):
                hl = highs[i] - lows[i] if len(highs) > abs(i) > 0 else 0
                hc = abs(highs[i] - closes[i-1]) if len(highs) > abs(i) > 0 and i > -14 else 0
                lc = abs(lows[i] - closes[i-1]) if len(lows) > abs(i) > 0 and i > -14 else 0
                tr_values.append(max(hl, hc, lc))
            atr = np.mean(tr_values)
            atr_pct = atr / closes[-1] * 100
        else:
            atr_pct = 0

        # ================================================================
        # FMZ 10-state expansion: RSI, MACD, EMA55, volume means, daily return
        # ================================================================

        # --- RSI(14) ---
        if len(closes) >= 15:
            gains, losses = 0.0, 0.0
            for i in range(-14, 0):
                change = closes[i] - closes[i - 1]
                if change > 0:
                    gains += change
                else:
                    losses -= change
            avg_gain = gains / 14
            avg_loss = losses / 14
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50.0

        # --- MACD(12,26) & Signal(9) ---
        if len(closes) >= 26:
            ema12 = np.mean(closes[-12:])
            ema26 = np.mean(closes[-26:])
            macd_line = ema12 - ema26
            # signal: 9-period EMA of MACD line — use SMA as proxy
            macd_values = []
            for i in range(-9, 0):
                e12 = np.mean(closes[-12 + i:i]) if len(closes[-12 + i:i]) >= 12 else np.mean(closes[-12:])
                e26 = np.mean(closes[-26 + i:i]) if len(closes[-26 + i:i]) >= 26 else np.mean(closes[-26:])
                macd_values.append(e12 - e26)
            macd_signal = np.mean(macd_values)
        else:
            macd_line = 0.0
            macd_signal = 0.0

        # --- EMA55 (SMA approximation) ---
        ema55 = np.mean(closes[-55:]) if len(closes) >= 55 else np.mean(closes[-min(55, len(closes)):])

        # --- Volume means ---
        volume = df['volume'].astype(float).values if 'volume' in df.columns else np.ones(len(closes))
        mean_volume_20 = np.mean(volume[-20:]) if len(volume) >= 20 else np.mean(volume)
        mean_volume_5 = np.mean(volume[-5:]) if len(volume) >= 5 else np.mean(volume)

        # --- Daily return ---
        daily_return_pct = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

        # --- 20-day ATR mean for comparison ---
        if len(closes) >= 34:
            atr_values = []
            for j in range(-20, 0):
                idx = j
                hl = highs[idx] - lows[idx] if len(highs) > abs(idx) > 0 else 0
                hc = abs(highs[idx] - closes[idx - 1]) if len(highs) > abs(idx) > 0 and idx > -20 else 0
                lc = abs(lows[idx] - closes[idx - 1]) if len(lows) > abs(idx) > 0 and idx > -20 else 0
                atr_values.append(max(hl, hc, lc))
            mean_atr_20 = np.mean(atr_values)
            mean_atr_20_pct = mean_atr_20 / closes[-1] * 100 if closes[-1] != 0 else atr_pct
        else:
            mean_atr_20_pct = atr_pct

        # --- Price range for BOX detection ---
        price_range_20d = np.max(highs[-20:]) - np.min(lows[-20:]) if len(highs) >= 20 and len(lows) >= 20 else 0
        mean_20d_range_pct = price_range_20d / closes[-1] * 100 if closes[-1] != 0 else 0

        # ================================================================
        # Priority-based 10-state detection (highest = first match)
        # ================================================================

        price_change_pct = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0

        market_state = None
        market_state_detail = None
        confidence = 0.5

        # Priority 1: WOLF — panic sell
        if daily_return_pct < -3.0 and closes[-1] < ema55:
            market_state = 'WOLF'
            market_state_detail = '恐慌性杀跌'
            confidence = 0.75

        # Priority 2: MACRO — large macro-level move
        if market_state is None and abs(daily_return_pct) > atr_pct * 2.5:
            market_state = 'MACRO'
            market_state_detail = '宏观事件驱动'
            confidence = 0.70

        # Priority 3: MEAN_REV — overbought/oversold
        if market_state is None and (rsi > 70 or rsi < 30):
            market_state = 'MEAN_REV'
            market_state_detail = '超买超卖(均值回归)'
            confidence = 0.65

        # Priority 4: MOMENTUM — strong breakout with volume
        if market_state is None and abs(price_change_pct) > atr_pct * 1.5 and volume[-1] > mean_volume_20 * 1.5:
            market_state = 'MOMENTUM'
            market_state_detail = '放量突破(动量)'
            confidence = 0.70

        # Priority 5: BOX — tight range within RANGING
        if market_state is None and mean_20d_range_pct > 0 and \
           abs(closes[-1] - ema55) < atr_pct * closes[-1] * 0.5 / 100 and \
           atr_pct < mean_atr_20_pct and \
           price_range_20d / closes[-1] * 100 < mean_20d_range_pct * 0.8:
            market_state = 'BOX'
            market_state_detail = '箱体震荡'
            confidence = 0.60

        # Priority 6: HIGH_VOL — elevated ATR
        if market_state is None and atr_pct > mean_atr_20_pct * 1.2:
            market_state = 'HIGH_VOL'
            market_state_detail = '高波动率'
            confidence = 0.60

        # Priority 7: RANGING — price near EMA55 with low ATR
        if market_state is None and \
           abs(closes[-1] - ema55) < atr_pct * closes[-1] * 0.5 / 100 and \
           atr_pct < mean_atr_20_pct:
            market_state = 'RANGING'
            market_state_detail = '震荡盘整'
            confidence = 0.55

        # Priority 8: EAGLE — healthy bull with low ATR
        if market_state is None and \
           closes[-1] > ema55 and macd_line > macd_signal and rsi > 50 and \
           volume[-1] > mean_volume_20 and atr_pct < mean_atr_20_pct * 0.8:
            market_state = 'EAGLE'
            market_state_detail = '健康上行(鹰)'
            confidence = 0.70

        # Priority 9: TRENDING_BULL
        if market_state is None and \
           closes[-1] > ema55 and macd_line > macd_signal and rsi > 50 and \
           volume[-1] > mean_volume_20:
            market_state = 'TRENDING_BULL'
            market_state_detail = '趋势上行'
            confidence = 0.65

        # Priority 10: TRENDING_BEAR
        if market_state is None and \
           closes[-1] < ema55 and macd_line < macd_signal and rsi < 50:
            market_state = 'TRENDING_BEAR'
            market_state_detail = '趋势下行'
            confidence = 0.65

        # Fallback: if nothing matched, use RANGING
        if market_state is None:
            market_state = 'RANGING'
            market_state_detail = '震荡盘整'
            confidence = 0.40

        return {
            'market_state': market_state,
            'market_state_detail': market_state_detail,
            'ma_trend': ma_trend,
            'bb_width': round(bb_width, 2),
            'atr_pct': round(atr_pct, 2),
            'confidence': confidence,
        }


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
        # [P1-#17] 放量缩量模式分类
        vol_pattern = self._classify_volume_pattern(volumes)

        return VolumeState(trend=trend, volma_structure=volma_struct,
                           has_volume_tuo=has_tuo, has_volume_ya=has_ya,
                           volume_keypoints=keypoints, institutional=inst,
                           vol_pattern=vol_pattern)

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

    # ── [P1-#17] 四种放量+两种缩量模式分类 ──

    def _classify_volume_pattern(self, volumes: np.ndarray) -> Dict:
        """[P1-#17] 四种放量+两种缩量模式分类"""
        if len(volumes) < 10:
            return {'pattern': 'UNKNOWN', 'detail': '数据不足'}

        avg_vol = float(np.mean(volumes[-10:-1])) if len(volumes) > 10 else float(np.mean(volumes[:-1]))
        if avg_vol <= 0:
            return {'pattern': 'UNKNOWN', 'detail': '无成交量数据'}

        latest_vol = volumes[-1] if len(volumes) >= 1 else 0
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 0

        # 检测放量模式
        if vol_ratio > 3 and vol_ratio < 5:
            pattern = '山峰放量'
            detail = f'量比{vol_ratio:.1f}, 突兀放量预警'
        elif vol_ratio >= 5:
            pattern = '突兀放量'
            detail = f'量比{vol_ratio:.1f}, 极端放量警惕出货'
        elif 1.5 <= vol_ratio <= 3:
            # 检查是否为持续放量
            if len(volumes) >= 5 and all(volumes[-i] > avg_vol * 1.2 for i in range(1, 4)):
                pattern = '温和放量'
                detail = '连续多日放量, 资金持续流入'
            else:
                pattern = '堆量放量'
                detail = '阶段性放量'
        elif vol_ratio < 0.5:
            pattern = '极度缩量'
            detail = f'量比{vol_ratio:.1f}, 市场交投极度萎缩'
        elif vol_ratio < 0.8:
            pattern = '相对缩量'
            detail = f'量比{vol_ratio:.1f}, 量能萎缩'
        else:
            pattern = '正常量能'
            detail = '量能无明显异动'

        return {'pattern': pattern, 'detail': detail, 'vol_ratio': round(vol_ratio, 2)}


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

    def _get_adaptive_windows(self, market_state=None) -> dict:
        """[#43] 量价窗口自适应 — 根据市场状态返回自适应回看值

        Args:
            market_state: 市场状态标识，如 'TRENDING_BULL' / 'TRENDING_BEAR' / 'HIGH_VOL'

        Returns:
            dict: {'lookback': int, 'reason': str}
        """
        if market_state == 'TRENDING_BULL':
            return {'lookback': 15, 'reason': '多头趋势，缩短窗口快速响应'}
        elif market_state == 'TRENDING_BEAR':
            return {'lookback': 30, 'reason': '空头趋势，延长窗口过滤噪音'}
        elif market_state == 'HIGH_VOL':
            return {'lookback': 15, 'reason': '高波动环境，缩短窗口减少滞后'}
        else:
            return {'lookback': 20, 'reason': '默认窗口(横盘/未知状态)'}

    def analyze(self, df: pd.DataFrame, stage: Stage, vol_state: VolumeState) -> RelationResult:
        if df.empty or len(df) < 10:
            return RelationResult()

        closes = self._safe_col(df, 'close').values
        opens = self._safe_col(df, 'open').values if 'open' in df.columns else closes
        highs = self._safe_col(df, 'high').values
        lows = self._safe_col(df, 'low').values
        volumes = get_best_volume_series(df)

        # [#43] 集成点：可在此处调用 _get_adaptive_windows 获取自适应窗口
        # 示例：adaptive = self._get_adaptive_windows(market_state)

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

        # 7. [P2-#16] 量价三定律验证
        three_laws = self._apply_three_laws(closes, volumes, stage.name, pattern_id)

        # 8. [P1-#13] 均线相交面积法
        ma_cross_area = self._calc_ma_cross_area(closes)

        # [P1-#14/#15] 主力行为分析
        fake_breakout = self._detect_fake_breakout(closes, volumes, highs, lows, opens)
        supply_demand = self._detect_supply_demand(closes, volumes)

        return RelationResult(
            pattern_id=pattern_id, pattern_name=pattern_name,
            enhance_patterns=enhance_pats,
            divergence_type=div_type, divergence_confidence=div_conf,
            divergence_macd_confirmed=macd_confirmed,
            cross_matrix_note=cross_note,
            momentum=momentum,
            resonance_score=resonance,
            three_laws=three_laws,
            ma_cross_area=ma_cross_area,
            fake_breakout=fake_breakout,
            supply_demand=supply_demand,
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
        # [P2-#9] 多形态共振 — 按增强形态数量计算额外的共振加分
        bull_count = sum(1 for p in enhance_pats if "预涨" in p)
        bear_count = sum(1 for p in enhance_pats if "预跌" in p)
        if bull_count >= 2 and bear_count < 1:
            score += 1  # +0.1 实际上必须是整数, 用+1视为0.1级
        if bear_count >= 2 and bull_count < 1:
            score -= 1
        if bull_count >= 3:
            score += 2  # +0.15, 用+2视为更强共振
        if bear_count >= 3:
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

    # ── [P1-#14] 养套杀假信号识别 ──

    def _detect_fake_breakout(self, closes, volumes, highs, lows, opens) -> Dict:
        """[P1-#14] 养套杀假信号识别

        特征：脉冲式放量(放量1-2天)后快速缩量 + 突破后价格无力维持 + 分时特征

        Returns: {'is_fake': bool, 'confidence': float, 'notes': list}
        """
        notes = []
        if len(volumes) < 10 or len(closes) < 10:
            return {'is_fake': False, 'confidence': 0.0, 'notes': ['数据不足']}

        avg_vol_10 = float(np.mean(volumes[-11:-1]))
        if avg_vol_10 <= 0:
            return {'is_fake': False, 'confidence': 0.0, 'notes': []}

        # 特征1: 脉冲放量 — 最近1-2日量突增但前几日量很低
        pulse_days = 0
        for i in range(-3, 0):
            if volumes[i] > avg_vol_10 * 2.5:
                pulse_days += 1
        pulse_vol = pulse_days >= 1

        # 特征2: 快速缩量 — 放量日后一日量骤降50%以上
        vol_drop = False
        if len(volumes) >= 3:
            if volumes[-2] > avg_vol_10 * 2 and volumes[-1] < volumes[-2] * 0.5:
                vol_drop = True

        # 特征3: 价格无力维持 — 当日收盘低于开盘或收长上影
        price_weak = False
        if highs[-1] - lows[-1] > 0:
            body = abs(closes[-1] - opens[-1])
            upper_shadow = highs[-1] - max(closes[-1], opens[-1])
            if closes[-1] < opens[-1]:  # 阴线
                price_weak = True
                notes.append('冲高回落收阴')
            elif body > 0 and upper_shadow > body * 1.5:  # 长上影
                price_weak = True
                notes.append('长上影显示抛压')

        # 综合判定
        signals = [pulse_vol, vol_drop, price_weak]
        confidence = sum(signals) / 3.0
        is_fake = confidence >= 0.5

        if pulse_vol:
            notes.append(f'脉冲放量(峰值>均量{volumes[-2]/avg_vol_10:.1f}倍)')
        if vol_drop:
            notes.append('放量后次日急速缩量>50%')
        if is_fake:
            notes.append('⚠️ 养套杀假突破信号')

        return {'is_fake': is_fake, 'confidence': round(confidence, 2), 'notes': notes}

    # ── [P1-#15] 主力测试检测（供给/需求）──

    def _detect_supply_demand(self, closes, volumes) -> Dict:
        """[P1-#15] 主力测试检测（供给/需求）

        特征：双回抽且第二次比第一次缩量 = 主力控盘良好

        Returns: {'has_test': bool, 'type': str, 'confidence': float, 'notes': list}
        """
        notes = []
        if len(closes) < 20 or len(volumes) < 20:
            return {'has_test': False, 'type': 'unknown', 'confidence': 0.0, 'notes': ['数据不足']}

        # 找最近两个低点（回抽点）
        # 回抽1: 最近10-15日的最低点
        r1_idx = np.argmin(closes[-15:-5])
        r1_price = closes[-15 + r1_idx]
        r1_vol = volumes[-15 + r1_idx] if len(volumes) > 15 + r1_idx else 0

        # 回抽2: 最近5日的最低点
        r2_idx = np.argmin(closes[-5:])
        r2_price = closes[-5 + r2_idx]
        r2_vol = volumes[-5 + r2_idx]

        # 检测两次回抽
        if r1_price <= 0 or r2_price <= 0:
            return {'has_test': False, 'type': 'unknown', 'confidence': 0.0, 'notes': []}

        # 两次回抽的支撑位一致（相差<3%）
        support_diff = abs(r2_price - r1_price) / r1_price

        if support_diff < 0.03 and r2_vol > 0 and r1_vol > 0:
            vol_ratio = r2_vol / r1_vol
            if vol_ratio < 0.7:
                notes.append(f'双回抽缩量确认(第二次量={r2_vol:.0f}, 第一次={r1_vol:.0f}, 比={vol_ratio:.2f})')
                notes.append('主力控盘良好，二次回抽抛压减弱')
                return {
                    'has_test': True,
                    'type': 'supply_test_passed',
                    'confidence': 0.75,
                    'support_level': round(float(r2_price), 2),
                    'vol_ratio': round(vol_ratio, 2),
                    'notes': notes,
                }
            elif vol_ratio > 1.5:
                notes.append(f'双回抽放量(第二次量={r2_vol:.0f} > 第一次={r1_vol:.0f})')
                notes.append('⚠️ 抛压未减，需求不足')
                return {
                    'has_test': True,
                    'type': 'supply_test_failed',
                    'confidence': 0.60,
                    'support_level': round(float(r2_price), 2),
                    'vol_ratio': round(vol_ratio, 2),
                    'notes': notes,
                }

        return {'has_test': False, 'type': 'no_test', 'confidence': 0.0, 'notes': ['未检测到主力测试信号']}

    def _apply_three_laws(self, closes, volumes, stage_name, pattern_id) -> Dict:
        """[P2-#16] 量价三定律验证

        Returns:
            dict with 'sync_score' (int) and 'notes' (list)
        """
        notes = []

        # 定律1: 量价同步=趋势健康
        sync_score = 0
        if len(closes) >= 5 and len(volumes) >= 5:
            price_up = closes[-1] > closes[-5]
            vol_up = volumes[-1] > np.mean(volumes[-5:-1]) if len(volumes) >= 6 else False
            if price_up and vol_up:
                sync_score += 1
                notes.append("量价同步: 价涨量增, 趋势健康")
            elif not price_up and not vol_up:
                notes.append("量价同步: 价跌量缩, 缩量调整")
            else:
                notes.append("量价背离: 价量反向运行, 趋势可能反转")
                sync_score -= 1

        # 定律2: 天量天价见顶
        if len(volumes) >= 60 and len(closes) >= 60:
            if volumes[-1] > np.max(volumes[-60:-1]) * 0.95:
                notes.append("天量警示: 成交量接近60日最大值")
                if closes[-1] >= np.max(closes[-60:-1]):
                    notes.append("天量天价: 量价同时见顶, 警惕反转")

        # 定律3: 地量地价见底
        if len(volumes) >= 60 and len(closes) >= 60:
            if volumes[-1] <= np.percentile(volumes[-60:], 10):
                notes.append("地量观察: 成交量处于60日内最低10%分位")

        return {'sync_score': sync_score, 'notes': notes}

    def _calc_ma_cross_area(self, closes: np.ndarray, lookback: int = 20) -> Dict:
        """[P1-#13] 均线相交面积法

        MA5与MA10之间的累计面积：
        - 面积 > 0 = MA5在MA10上方 = 多头趋势加强
        - 面积 < 0 = MA5在MA10下方 = 空头趋势加强
        - 面积变化率 = 趋势加速度

        Returns:
            dict with 'area', 'area_change_rate', 'verdict'
        """
        if len(closes) < lookback + 5:
            return {'area': 0.0, 'area_change_rate': 0.0, 'verdict': '数据不足'}

        import numpy as np
        # 计算每日MA5和MA10差值
        gaps = []
        for i in range(-lookback, 0):
            ma5_i = np.mean(closes[i-4:i+1])  # 当前日+前4日
            ma10_i = np.mean(closes[i-9:i+1])  # 当前日+前9日
            gaps.append(ma5_i - ma10_i)

        # 最近一半和先前一半的面积对比
        mid = len(gaps) // 2
        area_recent = sum(gaps[mid:])
        area_prev = sum(gaps[:mid])
        area_total = sum(gaps)

        change_rate = ((area_recent - area_prev) / abs(area_prev) * 100) if abs(area_prev) > 0.01 else 0

        if area_total > 0:
            verdict = '多头强势' if area_total > 2 else '多头渐起'
            if change_rate > 20:
                verdict += '加速'
            elif change_rate < -20:
                verdict += '减速'
        elif area_total < 0:
            verdict = '空头强势' if area_total < -2 else '空头渐起'
            if change_rate > 20:
                verdict += '减速(空头减弱)'
            elif change_rate < -20:
                verdict += '加速(空头增强)'
        else:
            verdict = '均线粘合'

        return {
            'area': round(area_total, 4),
            'area_change_rate': round(change_rate, 2),
            'verdict': verdict,
        }


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

    def _adjust_confidence_by_structure(self, base_confidence: float, direction: str,
                                          zhongshu_position: Optional[str] = None) -> float:
        """[P1-#10] 结构感知的形态因子

        根据缠论中枢位置调整形态置信度：
        - 中枢内：置信度降低（均值回归特征）
        - 中枢外上方：看涨形态置信度提升（趋势延续）
        - 中枢外下方：看跌形态置信度提升（趋势延续）

        Args:
            base_confidence: 基础置信度
            direction: BUY/SELL/HOLD
            zhongshu_position: None/'above'/'inside'/'below'

        Returns:
            调整后的置信度
        """
        if zhongshu_position is None:
            return base_confidence

        conf = base_confidence

        if zhongshu_position == 'inside':
            # 中枢内：形态不可靠，降低置信度
            if direction == 'BUY':
                conf *= 0.85
            elif direction == 'SELL':
                conf *= 0.85
        elif zhongshu_position == 'above':
            # 中枢上方：看涨形态可信，看跌形态不可信
            if direction == 'BUY':
                conf *= 1.10
            elif direction == 'SELL':
                conf *= 0.70
        elif zhongshu_position == 'below':
            # 中枢下方：看跌形态可信，看涨形态不可信
            if direction == 'BUY':
                conf *= 0.70
            elif direction == 'SELL':
                conf *= 1.10

        return min(1.0, max(0.0, conf))

    def generate(self, stage: Stage, vol_state: VolumeState,
                 relation: RelationResult, df: pd.DataFrame,
                 market_multiplier: float = DEFAULT_MARKET_MULTIPLIER) -> VolumePriceSignal:
        if df.empty or len(df) < 5:
            return VolumePriceSignal()

        closes = self._safe_col(df, 'close').values
        latest_close = float(closes[-1])
        highs = self._safe_col(df, 'high').values if 'high' in df.columns else closes
        volumes = get_best_volume_series(df)

        # [P1-#18] 真实突破判断
        breakout_check = self._verify_breakout(closes, highs, volumes)

        # 1. 匹配基础信号
        base_signal = self._match_base_signal(stage.name, relation.pattern_id)
        if not base_signal:
            return VolumePriceSignal(direction="HOLD", signal_label="持仓等待",
                                     confidence=0.45, evidence=["信号不匹配"])

        signal_id, direction, base_conf = base_signal

        # [P1-#10] 结构感知形态因子：SignalComputationService 调用处设置 zhongshu_position
        # 在 compute_for_stock 中通过 market_context 传入

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
        # [P1-#18] 真实突破判断加入证据
        for note in breakout_check.get('notes', []):
            evidence.append(f"【突破验证】{note}")
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
            status=self._build_status(stage, vol_state, relation, latest_close),
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

    def _build_status(self, stage, vol_state, relation, latest_close: float) -> StatusRecognition:
        """构建量价策略的现状识别"""
        # 状态判定
        stage_to_state = {
            "UPTREND_ACTIVE": ("ACCUMULATING", "上升趋势"),
            "UPTREND_TOPPING": ("DISTRIBUTING", "上升筑顶"),
            "DOWNTREND_ACTIVE": ("BEARISH", "下降趋势"),
            "DOWNTREND_BOTTOMING": ("ACCUMULATING", "下降筑底"),
            "CONSOLIDATION": ("RANGING", "横盘整理"),
        }
        state, state_label = stage_to_state.get(stage.name, ("UNKNOWN", "待定"))

        # 趋势信息
        direction_map = {"UPTREND_ACTIVE": "up", "UPTREND_TOPPING": "up",
                         "DOWNTREND_ACTIVE": "down", "DOWNTREND_BOTTOMING": "down"}
        strength_map = {"UPTREND_ACTIVE": "strong", "UPTREND_TOPPING": "weakening",
                        "DOWNTREND_ACTIVE": "strong", "DOWNTREND_BOTTOMING": "weakening"}
        trend = {
            "direction": direction_map.get(stage.name, ""),
            "strength": strength_map.get(stage.name, ""),
            "stage": stage.name,
        }

        # 动量信息
        mom_level = relation.momentum.level if relation.momentum else "NEUTRAL"
        momentum = {
            "level": mom_level,
            "score": round(relation.momentum.score, 4) if relation.momentum else 0.0,
        }

        # 量能信息
        vol_state_map = {"EXPANDING": "放量", "CONTRACTING": "缩量", "STABLE": "平量"}
        volma_map = {"BULLISH": "多头排列", "BEARISH": "空头排列", "MIXED": "交叉"}
        volume = {
            "state": vol_state_map.get(vol_state.trend, "平量"),
            "structure": volma_map.get(vol_state.volma_structure, ""),
        }

        # 支撑/阻力
        kps = vol_state.volume_keypoints
        resistance = max(kps) if kps else 0.0
        support = min(kps) if kps else 0.0

        support_resistance = {"support": round(support, 2), "resistance": round(resistance, 2)}

        # 风险等级
        if state in ("DISTRIBUTING", "BEARISH"):
            risk_level = "HIGH"
        elif state in ("RANGING",):
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return StatusRecognition(
            state=state, state_label=state_label,
            trend=trend, momentum=momentum,
            volume=volume, support_resistance=support_resistance,
            risk_level=risk_level,
        )

    # ── [P1-#18] 真实突破判断 ──

    def _verify_breakout(self, closes, highs, volumes) -> Dict:
        """[P1-#18] 真实突破判断

        条件: 放量>20日均量1.5倍 + 收盘站稳>3日 + 回调不破突破位

        Returns: {'is_valid': bool, 'notes': list}
        """
        notes = []
        if len(closes) < 25 or len(highs) < 25 or len(volumes) < 25:
            return {'is_valid': False, 'notes': ['数据不足']}

        avg_vol_20 = float(np.mean(volumes[-21:-1]))
        if avg_vol_20 <= 0:
            return {'is_valid': False, 'notes': ['无成交量数据']}

        # 条件1: 放量
        vol_ok = volumes[-1] > avg_vol_20 * 1.5
        if vol_ok:
            notes.append(f'放量: 今日量>{avg_vol_20*1.5:.0f}(20日均量1.5倍)')

        # 条件2: 站稳 (最近3日收盘 > 突破位)
        break_level = np.max(highs[-22:-1]) if len(highs) >= 23 else closes[-1]
        hold_ok = all(closes[-i] > break_level for i in range(1, 4))
        if hold_ok:
            notes.append(f'站稳: 连续3日收盘在突破位{break_level:.2f}之上')

        # 条件3: 回调不破 (如果有回调)
        pullback_ok = True
        if len(closes) >= 5:
            pullback_low = np.min(closes[-5:])
            if pullback_low < break_level:
                pullback_ok = False
                notes.append(f'回调破位: 最低{pullback_low:.2f}跌破突破位{break_level:.2f}')

        is_valid = vol_ok and hold_ok and pullback_ok
        if is_valid:
            notes.append('✅ 真实突破确认')

        return {'is_valid': is_valid, 'notes': notes}


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
