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


    # ── Wiki 50 种量价形态（预涨型/预跌型/黑马型）+ 四类八种状态 ──

    # 预涨型 20 种 (P-1-1 到 P-1-20)
    _bullish_wiki = [
        ("P-1-1",  "缩量十字星",       "低位连续缩量后出现十字星，多空力量趋于平衡，反转信号"),
        ("P-1-2",  "底部温和放量",     "底部区域成交量温和放大，主力开始试探性建仓"),
        ("P-1-3",  "量价齐升启动",     "价格与成交量同步上升，多方力量逐步增强"),
        ("P-1-4",  "缩量回踩均线",     "上升趋势中缩量回踩重要均线不破，洗盘结束信号"),
        ("P-1-5",  "底部堆量蓄势",     "低位成交量持续堆积但价格未大幅上涨，主力暗中吸筹"),
        ("P-1-6",  "放量突破平台",     "成交量显著放大突破长期整理平台，突破确认信号"),
        ("P-1-7",  "阳线放量反包",     "阳线实体完全覆盖前日阴线且伴随放量，多头强势反转"),
        ("P-1-8",  "缩量洗盘后放量",   "经历缩量回调后首次出现放量阳线，洗盘结束主力重新发力"),
        ("P-1-9",  "量比递增上涨",     "连续多日量比递增且价格上涨，增量资金持续入场"),
        ("P-1-10", "底部放量长阳",     "低位出现大实体阳线伴随显著放量，底部反转强烈信号"),
        ("P-1-11", "均线多头放量",     "均线呈多头排列且成交量放大，趋势与量能共振向上"),
        ("P-1-12", "W底放量突破",     "W底形态颈线位伴随放量突破，底部形态确认"),
        ("P-1-13", "缺口放量突破",     "向上跳空缺口伴随放量，突破力度强"),
        ("P-1-14", "量能潮汐启动",     "成交量由持续萎缩转为逐步放大，量能周期拐点"),
        ("P-1-15", "主力吸筹放量",     "低位异常放量但价格波动小，主力隐蔽建仓特征"),
        ("P-1-16", "圆弧底放量",       "圆弧底形态右侧成交量逐步放大，底部反转确认"),
        ("P-1-17", "三阳开泰放量",     "连续三根阳线且成交量递增，多头力量全面释放"),
        ("P-1-18", "旗形整理突破",     "旗形形态结束后放量向上突破，趋势延续信号"),
        ("P-1-19", "三角收敛突破",     "三角形收敛末端放量向上突破，整理结束信号"),
        ("P-1-20", "箱体突破放量",     "箱体震荡区间向上突破伴随成交量放大，主升浪起点"),
    ]
    for code, label, desc in _bullish_wiki:
        reg.register(PatternMeta(
            name=code,
            category=PatternCategory.BULLISH_PATTERNS,
            direction='bullish',
            description=f"{label}: {desc}",
            tags=["预涨型", label, "Wiki"],
            min_periods=10,
            source="wiki_volume_price",
        ))

    # 预跌型 20 种 (P-2-1 到 P-2-20)
    _bearish_wiki = [
        ("P-2-1",  "高位量价背离",     "价格创新高但成交量递减，上涨动力衰竭"),
        ("P-2-2",  "放量滞涨",         "成交量显著放大但价格未能上涨，主力出货迹象"),
        ("P-2-3",  "顶部缩量反弹",     "下跌趋势中缩量反弹，反弹力度弱不可持续"),
        ("P-2-4",  "天量见天价",       "出现异常巨量后价格见顶，换手率极高主力出逃"),
        ("P-2-5",  "连续缩量下跌",     "连续多日成交量萎缩价格下跌，买盘枯竭"),
        ("P-2-6",  "高位放量十字星",   "高位出现放量十字星，多空分歧加大见顶信号"),
        ("P-2-7",  "断头铡刀放量",     "大阴线直接跌破多条均线伴随放量，趋势反转"),
        ("P-2-8",  "M顶放量跌破",     "M顶形态颈线位放量跌破，顶部形态确认"),
        ("P-2-9",  "头肩顶放量破位",   "头肩顶形态右肩放量跌破颈线，经典顶部反转"),
        ("P-2-10", "高位阴线放量",     "高位连续阴线伴随放量，空方力量主导"),
        ("P-2-11", "均线空头放量",     "均线呈空头排列且成交量放大，趋势与量能共振向下"),
        ("P-2-12", "反弹受阻缩量",     "反弹至重要阻力位成交量萎缩，上涨动能不足"),
        ("P-2-13", "放量跌破平台",     "成交量放大跌破整理平台，破位确认信号"),
        ("P-2-14", "向下缺口放量",     "向下跳空缺口伴随放量，下跌力度强"),
        ("P-2-15", "高换手率暴跌",     "高位换手率异常高伴随大幅下跌，筹码快速换手"),
        ("P-2-16", "乌云盖顶放量",     "高位阴线覆盖前日阳线大半伴随放量，见顶信号"),
        ("P-2-17", "黄昏之星放量",     "高位三根K线形成黄昏之星且放量，反转信号"),
        ("P-2-18", "下跌三浪放量",     "下跌过程中三浪推进且每浪放量，空方力量完整释放"),
        ("P-2-19", "圆弧顶缩量",       "圆弧顶形态右侧成交量逐步缩小，顶部反转确认"),
        ("P-2-20", "旗形下跌破位",     "下降旗形整理结束后放量向下破位，下跌趋势延续"),
    ]
    for code, label, desc in _bearish_wiki:
        reg.register(PatternMeta(
            name=code,
            category=PatternCategory.BEARISH_PATTERNS,
            direction='bearish',
            description=f"{label}: {desc}",
            tags=["预跌型", label, "Wiki"],
            min_periods=10,
            source="wiki_volume_price",
        ))

    # 黑马型 10 种 (P-3-1 到 P-3-10)
    _blackhorse_wiki = [
        ("P-3-1",  "压缩放量突破",     "长期窄幅震荡后突然大幅放量突破，爆发力强"),
        ("P-3-2",  "跳空高开放量",     "大幅跳空高开且成交量激增，重大利好或主力强势介入"),
        ("P-3-3",  "底部巨量长阳",     "低位出现异常巨量大阳线，主力大举建仓信号"),
        ("P-3-4",  "突破创新高放量",   "价格突破历史或近期新高伴随放量，新行情启动"),
        ("P-3-5",  "钥匙形态放量",     "V型反转伴随成交量急剧放大，快速反转信号"),
        ("P-3-6",  "涨停板封板放量",   "涨停板伴随巨量封单，主力强势控盘特征"),
        ("P-3-7",  "主力试盘放量",     "盘中快速拉升后回落伴随异常放量，主力试盘动作"),
        ("P-3-8",  "连板强势放量",     "连续涨停且每板成交量合理放大，强势股特征"),
        ("P-3-9",  "三兵突进放量",     "三根连续大阳线依次放量，多方力量集中爆发"),
        ("P-3-10", "游资抢筹放量",     "盘后龙虎榜显示游资席位大额买入伴随放量，短线资金抢筹"),
    ]
    for code, label, desc in _blackhorse_wiki:
        reg.register(PatternMeta(
            name=code,
            category=PatternCategory.BLACKHORSE,
            direction='bullish',
            description=f"{label}: {desc}",
            tags=["黑马型", label, "Wiki"],
            min_periods=5,
            source="wiki_volume_price",
        ))

    # 四类八种状态 (S-1 到 S-8)
    _states = [
        ("S-1", "建仓状态",   "低位成交量温和持续放大，价格波动收窄，主力建仓阶段", "bullish"),
        ("S-2", "拉升状态",   "价格持续上涨伴随成交量递增，趋势加速阶段", "bullish"),
        ("S-3", "出货状态",   "高位成交量放大但价格滞涨或量价背离，主力出货阶段", "bearish"),
        ("S-4", "下跌状态",   "价格持续下跌，成交量逐步萎缩或恐慌放量，空方主导阶段", "bearish"),
        ("S-5", "建仓转拉升", "建仓末期成交量突然放大突破整理区间，进入拉升阶段", "bullish"),
        ("S-6", "拉升转出货", "拉升末期成交量异常放大但涨幅缩小，开始转向出货", "bearish"),
        ("S-7", "出货转下跌", "出货末期成交量萎缩价格跌破支撑，进入下跌阶段", "bearish"),
        ("S-8", "下跌转建仓", "下跌末期恐慌盘涌出后成交量极度萎缩，底部形成中", "bullish"),
    ]
    for code, label, desc, direction in _states:
        reg.register(PatternMeta(
            name=code,
            category=PatternCategory.STATE,
            direction=direction,
            description=f"{label}: {desc}",
            tags=["四类八种状态", label],
            min_periods=20,
            source="wiki_volume_price",
        ))


# 初始化注册
_register_builtin()
