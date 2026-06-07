"""
PatternRegistry — 模式注册表
==============================
集中管理所有可用模式的元数据、分类、检测器引用。
实现 PatternRegistry（方案152 §Phase 1 详细任务）。

参考观潮 PatternRouter 的分层组织方式：
  ReversalPatterns / ContinuationPatterns / BreakoutPatterns / ...
"""

from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

from . import PatternCategory


@dataclass
class PatternMeta:
    """模式元数据（注册表条目）"""
    name: str
    category: PatternCategory
    direction: str           # 'bullish' | 'bearish' | 'neutral'
    description: str = ""
    tags: List[str] = field(default_factory=list)
    min_periods: int = 0     # 最少所需K线数
    source: str = ""         # 来源策略

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'category': self.category.value,
            'direction': self.direction,
            'description': self.description,
            'tags': self.tags,
            'min_periods': self.min_periods,
            'source': self.source,
        }


class PatternRegistry:
    """
    模式注册表 — 单例
    提供构建时注册 + 运行时查询能力
    """

    _instance = None
    _patterns: Dict[str, PatternMeta] = {}
    _categories: Dict[PatternCategory, List[str]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def register(self, meta: PatternMeta):
        """注册一个模式"""
        self._patterns[meta.name] = meta
        if meta.category not in self._categories:
            self._categories[meta.category] = []
        self._categories[meta.category].append(meta.name)

    def get(self, name: str) -> Optional[PatternMeta]:
        """按名称查询模式"""
        return self._patterns.get(name)

    def list_by_category(self, category: PatternCategory) -> List[PatternMeta]:
        """按分类列出所有模式"""
        names = self._categories.get(category, [])
        return [self._patterns[n] for n in names if n in self._patterns]

    def list_all(self) -> List[PatternMeta]:
        """列出所有注册的模式"""
        return list(self._patterns.values())

    def search(self, query: str) -> List[PatternMeta]:
        """按名称或描述搜索模式"""
        q = query.lower()
        return [
            p for p in self._patterns.values()
            if q in p.name.lower() or q in p.description.lower()
        ]

    def count_by_category(self) -> Dict[str, int]:
        """按分类统计模式数量"""
        counts = {}
        for meta in self._patterns.values():
            cat = meta.category.value
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def total_count(self) -> int:
        return len(self._patterns)


# ── 内置模式注册（构建时自动执行）──

def _register_builtin():
    """注册所有内置模式元数据"""
    reg = PatternRegistry()

    # K线形态 (12种): 从 kline_pattern.py 扩展
    _candlestick_patterns = [
        ("big_yang", "大阳线", "实体>振幅0.7且涨幅>3%", "bullish"),
        ("big_bear", "大阴线", "实体>振幅0.7且跌幅>3%", "bearish"),
        ("doji", "十字星", "实体<振幅0.1", "neutral"),
        ("hammer", "锤子线", "下影线>实体2倍且上影线短", "bullish"),
        ("hanging_man", "吊颈线", "下影线>实体2倍且上影线短(高位)", "bearish"),
        ("engulfing_bullish", "看涨吞没", "阳线实体完全覆盖前日阴线实体", "bullish"),
        ("engulfing_bearish", "看跌吞没", "阴线实体完全覆盖前日阳线实体", "bearish"),
        ("harami_bullish", "看涨孕线", "小阳线在前日大阴线实体内", "bullish"),
        ("harami_bearish", "看跌孕线", "小阴线在前日大阳线实体内", "bearish"),
        ("shooting_star", "射击之星", "上影线>实体2倍且下影线短(高位)", "bearish"),
        ("spinning_top", "纺锤线", "实体小、上下影线长", "neutral"),
        ("three_crows", "三只乌鸦", "连续3根阴线且每日创新低", "bearish"),
    ]
    for name, label, desc, direction in _candlestick_patterns:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.CANDLESTICK,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["k线形态", label],
            min_periods=3,
            source="kline_pattern.py",
        ))

    # 量价形态 (9种基础): 从 volume_price_strategy._classify_vp_pattern
    _vp_base = [
        ("VP-1", "价涨量增", "价格上涨同时成交量放大", "bullish"),
        ("VP-2", "价涨量平", "价格上涨、成交量持平", "bullish"),
        ("VP-3", "价涨量缩", "价格上涨但成交量萎缩（顶背离预警）", "bearish"),
        ("VP-4", "价平量增", "价格横盘、成交量放大", "neutral"),
        ("VP-5", "价平量平", "价格和成交量均无明显变化", "neutral"),
        ("VP-6", "价平量减", "价格横盘、成交量萎缩", "neutral"),
        ("VP-7", "价跌量增", "价格下跌且成交量放大（底背离信号）", "bullish"),
        ("VP-8", "价跌量平", "价格下跌、成交量持平", "bearish"),
        ("VP-9", "价跌量缩", "价格下跌且成交量萎缩（缩量企稳）", "bullish"),
    ]
    for name, label, desc, direction in _vp_base:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.VOLUME_PRICE,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["量价基础", label],
            min_periods=4,
            source="volume_price_strategy.py",
        ))

    # 增强形态 (5种): 从 EnhancedPatternDetector
    _enhanced = [
        ("chonggao_huiluo_jisuo", "冲高回落急速缩量",
         "当日最高涨幅>3%→收盘回落<最高价2%→次日成交量<前日50%", "bullish"),
        ("dizeng_fangliang_xiajie", "递增式放量下跌",
         "连续3日成交量递增且每日收盘价均低于前日", "bearish"),
        ("huiluo_zhangting_qiangshi", "堆量中跌回启动点",
         "10日累计换手高→价格跌回启动点→量缩至放量区30%", "bullish"),
        ("sanlian_yang_fangliang", "三连阳放量",
         "连续3日阳线+成交量递增", "bullish"),
        ("fangliang_changyin_tupo", "放量长阴破位",
         "实体>振幅0.6且收盘<前低且成交量>均量1.5倍", "bearish"),
    ]
    for name, label, desc, direction in _enhanced:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.VOLUME_PRICE,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["增强形态", label],
            min_periods=10,
            source="volume_price_strategy.py",
        ))

    # 背离形态 (6种)
    _divergence = [
        ("macd_bullish_divergence", "MACD底背离",
         "价格新低但MACD DIF未创新低", "bullish"),
        ("macd_bearish_divergence", "MACD顶背离",
         "价格新高但MACD DIF未创新高", "bearish"),
        ("volume_price_divergence_bullish", "量价底背离",
         "价格新低但成交量萎缩", "bullish"),
        ("volume_price_divergence_bearish", "量价顶背离",
         "价格新高但成交量萎缩", "bearish"),
        ("triple_bullish_divergence", "三重底背离",
         "价格+量+MACD同时底背离", "bullish"),
        ("triple_bearish_divergence", "三重顶背离",
         "价格+量+MACD同时顶背离", "bearish"),
    ]
    for name, label, desc, direction in _divergence:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.DIVERGENCE,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["背离", label],
            min_periods=40,
            source="volume_price_strategy.py",
        ))

    # 缠论形态 (8种): 从 chanlun_strategy BuySellPointDetector
    _chanlun = [
        ("first_buy", "第一类买点", "趋势背驰产生的第一个买入点", "bullish"),
        ("second_buy", "第二类买点", "趋势背驰后的次级别回试不创新低", "bullish"),
        ("third_buy", "第三类买点", "离开中枢后回试不返回中枢区间", "bullish"),
        ("second_like_buy", "类二买", "类第二类买点（中枢震荡中）", "bullish"),
        ("first_sell", "第一类卖点", "趋势背驰产生的第一个卖出点", "bearish"),
        ("second_sell", "第二类卖点", "趋势背驰后的次级别回升不创新高", "bearish"),
        ("third_sell", "第三类卖点", "离开中枢后回升不返回中枢区间", "bearish"),
        ("second_like_sell", "类二卖", "类第二类卖点（中枢震荡中）", "bearish"),
    ]
    for name, label, desc, direction in _chanlun:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.CHANLUN,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["缠论", label],
            min_periods=60,
            source="chanlun_strategy.py",
        ))

    # 趋势形态 (4种): 从 StageDetector
    _trend = [
        ("accumulation", "建仓阶段", "低位量能温和放大，主力逐步吸筹", "bullish"),
        ("markup", "拉升阶段", "价涨量增持续，趋势向上加速", "bullish"),
        ("distribution", "出货阶段", "高位放量滞涨或量价背离", "bearish"),
        ("markdown", "下跌阶段", "趋势向下，空方主导", "bearish"),
    ]
    for name, label, desc, direction in _trend:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.TREND,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["趋势", label],
            min_periods=60,
            source="volume_price_strategy.py",
        ))

    # 量托/量压 (2种)
    _volume_patterns = [
        ("volume_tuo", "量托", "5/10/20日均量线多头排列（放量起点）", "bullish"),
        ("volume_ya", "量压", "5/10/20日均量线空头排列（缩量起点）", "bearish"),
    ]
    for name, label, desc, direction in _volume_patterns:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.VOLUME,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["量能", label],
            min_periods=20,
            source="volume_price_strategy.py",
        ))

    # 突破形态 (新增10种)
    _breakout = [
        ("range_breakout", "区间突破", "价格突破近期整理区间高点", "bullish"),
        ("resistance_breakout", "阻力位突破", "价格突破关键阻力位", "bullish"),
        ("support_breakdown", "支撑位跌破", "价格跌破关键支撑位", "bearish"),
        ("ma_breakout", "均线突破", "价格突破重要均线", "bullish"),
        ("volume_breakout", "放量突破", "突破伴随成交量显著放大", "bullish"),
        ("new_high_breakout", "新高突破", "价格创近期新高", "bullish"),
        ("new_low_breakdown", "新低破位", "价格创近期新低", "bearish"),
        ("boll_upper_breakout", "布林上轨突破", "价格突破布林上轨", "bullish"),
        ("boll_lower_breakdown", "布林下轨破位", "价格跌破布林下轨", "bearish"),
        ("boll_mid_breakout", "布林中轨突破", "价格突破布林中轨（趋势确认）", "bullish"),
    ]
    for name, label, desc, direction in _breakout:
        reg.register(PatternMeta(
            name=name,
            category=PatternCategory.BREAKOUT,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["突破", label],
            min_periods=20,
            source="patterns/builtin",
        ))


# 初始化注册
_register_builtin()
