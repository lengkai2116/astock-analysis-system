"""
NLG 中文金融术语映射表 — 5 维度核心术语统一管理

所有维度渲染器应引用此模块的术语，避免中文术语在各处重复定义。
"""

# ── 趋势维度 ──
TREND_DIRECTION = {
    "up": "上升",
    "down": "下降",
    "sideways": "横盘",
    "unknown": "不明",
}

TREND_STRENGTH = {
    "strong": "强劲",
    "moderate": "温和",
    "weak": "疲弱",
    "unknown": "",
}

TREND_STAGE = {
    "UPTREND_EARLY": "上升初期",
    "UPTREND_ACTIVE": "上升中期",
    "UPTREND_LATE": "上升末期",
    "DOWNTREND_EARLY": "下降初期",
    "DOWNTREND_ACTIVE": "下降中期",
    "DOWNTREND_LATE": "下降末期",
    "RANGING": "横盘震荡",
    "REVERSAL_UP": "筑底反弹",
    "REVERSAL_DOWN": "见顶回落",
    "ACCELERATING": "加速阶段",
    "DECELERATING": "减速阶段",
    "": "",
}

# ── 动量维度 ──
MOMENTUM_LEVEL = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "strong_bullish": "强烈看多",
    "strong_bearish": "强烈看空",
}

MOMENTUM_ACTION = {
    "BUY": "买入",
    "SELL": "卖出",
    "HOLD": "观望",
    "ADD": "加仓",
    "REDUCE": "减仓",
}

# ── 成交量和形态维度 ──
VOLUME_STATE = {
    "expanding": "放量",
    "shrinking": "缩量",
    "stable": "平量",
    "extreme": "巨量",
    "unknown": "",
}

VOLUME_RELATION = {
    "价升量增": "价升量增，上涨有量配合",
    "价升量缩": "价升量缩，上涨动能不足",
    "价跌量增": "价跌量增，下跌有量确认",
    "价跌量缩": "价跌量缩，下跌动能减弱",
    "价平量增": "价平量增，多空分歧加大",
    "价平量缩": "价平量缩，市场观望情绪浓",
    "放量突破": "放量突破，趋势确认",
    "缩量回调": "缩量回调，洗盘特征",
}

# ── 筹码维度 ──
CHIP_PHASE = {
    "accumulating": "建仓期",
    "markup": "拉升期",
    "washing": "洗盘期",
    "distributing": "出货期",
    "neutral": "中性",
    "unknown": "未知",
}

CHIP_STATE = {
    "ACCUMULATING": "主力建仓",
    "DISTRIBUTING": "主力出货",
    "RANGING": "筹码换手",
}

# ── 情绪维度 ──
BOCIASI_STATE = {
    "ACCUMULATING": "情绪积累",
    "BEARISH": "情绪偏空",
    "RANGING": "情绪中性",
}

EMOTION_CYCLE = {
    "ice": "情绪冰点",
    "recovery": "情绪复苏",
    "climax": "情绪高潮",
    "recession": "情绪衰退",
    "neutral": "情绪中性",
}

# ── 缠论专用术语 ──
CHANLUN_TERMS = {
    "first_buy": "第一类买点",
    "second_buy": "第二类买点",
    "third_buy": "第三类买点",
    "first_sell": "第一类卖点",
    "second_sell": "第二类卖点",
    "third_sell": "第三类卖点",
    "zhongshu": "中枢",
    "beichi": "背驰",
    "pishu_beichi": "盘整背驰",
    "qushi_beichi": "趋势背驰",
    "stroke": "笔",
    "fengxing": "分型",
}

# ── 风险等级 ──
RISK_LEVEL = {
    "LOW": "低风险",
    "MEDIUM": "中等风险",
    "HIGH": "高风险",
    "CRITICAL": "极高风险",
}

# ── 共识等级 ──
CONSENSUS_LEVEL = {
    "高度一致": "高度一致",
    "基本一致": "基本一致",
    "分歧明显": "分歧明显",
    "严重分歧": "严重分歧",
}
