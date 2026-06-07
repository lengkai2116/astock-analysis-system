"""
ComboEngine — 多模式组合推荐引擎
==================================
实现方案152 §4.4 策略四：AI Combo Card 系统（P2）

将单个股票上检测到的多个独立模式，
按方向/置信度/逻辑关系智能组合为操作建议卡片。
参考观潮 ai-combo-card 体系。

ComboCard 数据模型（对应前端 ai-combo-card）：
  name / strength / resolution / expires / patterns / dim_tags
  sr_tag / vol_tag / interpretation / hint / invalidation / levels
"""

from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engine.patterns import PatternResult, PatternCategory, PatternStage, PatternLevel


@dataclass
class PatternTag:
    """模式标签"""
    name: str
    label: str
    direction: str  # 'bullish' | 'bearish' | 'neutral'

    def to_dict(self) -> Dict:
        return {'name': self.name, 'label': self.label, 'direction': self.direction}


@dataclass
class ComboCard:
    """
    组合推荐卡片
    对应观潮 ai-combo-card 的完整结构
    """
    name: str                          # 组合名称
    direction: str                     # 'bullish' | 'bearish' | 'neutral'
    strength: float                    # 综合强度 0~100
    resolution: str                    # 时间周期
    expires: str                       # 有效期限
    patterns: List[PatternTag]         # 触发的模式标签列表
    dim_tags: List[str]                # 维度标签
    sr_tag: Dict                       # {'label': str, 'direction': str}
    vol_confirmed: bool                # 成交量确认
    interpretation: str                # 综合分析解读
    hint: str                          # 操作提示
    invalidation: str                  # 失效条件
    levels: Optional[PatternLevel] = None  # 关键价格层级

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'direction': self.direction,
            'strength': self.strength,
            'resolution': self.resolution,
            'expires': self.expires,
            'patterns': [p.to_dict() for p in self.patterns],
            'dim_tags': self.dim_tags,
            'sr_tag': self.sr_tag,
            'vol_confirmed': self.vol_confirmed,
            'interpretation': self.interpretation,
            'hint': self.hint,
            'invalidation': self.invalidation,
            'levels': self.levels.to_dict() if self.levels else None,
        }


class ComboEngine:
    """
    多模式组合推荐引擎

    组合逻辑:
    1. 按方向分组 (bullish / bearish)
    2. 同一方向多个模式 -> 加权综合评分
    3. 模式间有逻辑关联 -> 组合叠加评分
    4. 冲突方向 -> 分离为不同卡片

    使用方式:
        engine = ComboEngine()
        cards = engine.build_combos(patterns, resolution="日线")
    """

    # 维度映射：模式分类 -> 维度标签
    CATEGORY_DIM_MAP = {
        PatternCategory.CANDLESTICK: "K线形态",
        PatternCategory.VOLUME_PRICE: "量价形态",
        PatternCategory.VOLUME: "量能结构",
        PatternCategory.DIVERGENCE: "背离信号",
        PatternCategory.TREND: "趋势分析",
        PatternCategory.CHANLUN: "缠论信号",
        PatternCategory.BREAKOUT: "突破形态",
        PatternCategory.REVERSAL: "反转形态",
        PatternCategory.GAP: "缺口形态",
        PatternCategory.COMBO: "组合信号",
    }

    # 高关联组合：两个模式同时出现时强度倍增
    SYNERGY_PAIRS = [
        (("macd_bullish_divergence", "volume_tuo"), "bullish"),
        (("macd_bullish_divergence", "sanlian_yang_fangliang"), "bullish"),
        (("macd_bullish_divergence", "huiluo_zhangting_qiangshi"), "bullish"),
        (("macd_bearish_divergence", "volume_ya"), "bearish"),
        (("macd_bearish_divergence", "dizeng_fangliang_xiajie"), "bearish"),
        (("macd_bearish_divergence", "fangliang_changyin_tupo"), "bearish"),
        (("chonggao_huiluo_jisuo", "VP-9"), "bullish"),
        (("sanlian_yang_fangliang", "VP-1"), "bullish"),
        (("volume_tuo", "VP-1"), "bullish"),
        (("volume_ya", "VP-7"), "bearish"),
    ]

    def __init__(self):
        self.synergy_map = self._build_synergy_map()

    def _build_synergy_map(self) -> Dict[Tuple[str, str], float]:
        """构建协同效应映射表"""
        m = {}
        for (a, b), direction in self.SYNERGY_PAIRS:
            m[(a, b)] = 1.3
            m[(b, a)] = 1.3
        return m

    def build_combos(self, patterns: List[PatternResult],
                     resolution: str = "日线",
                     latest_close: Optional[float] = None) -> List[ComboCard]:
        """
        根据模式列表构建组合卡片

        Args:
            patterns: 所有检测到的模式
            resolution: 时间周期说明
            latest_close: 当前收盘价（用于 levels）

        Returns:
            ComboCard 列表（按强度降序排列）
        """
        if not patterns:
            return []

        cards = []

        # 按方向分组
        bull_patterns = [p for p in patterns if p.direction == 'bullish']
        bear_patterns = [p for p in patterns if p.direction == 'bearish']

        if bull_patterns:
            cards.append(self._build_combo(bull_patterns, 'bullish', resolution, latest_close))

        if bear_patterns:
            cards.append(self._build_combo(bear_patterns, 'bearish', resolution, latest_close))

        # 按强度降序排列
        cards.sort(key=lambda c: c.strength, reverse=True)
        return cards

    def _build_combo(self, patterns: List[PatternResult],
                     direction: str, resolution: str,
                     latest_close: Optional[float] = None) -> ComboCard:
        """构建单张组合卡片"""
        # 1. 计算综合强度
        base_strength = sum(p.strength for p in patterns) / max(len(patterns), 1)
        synergy_bonus = self._calc_synergy(patterns)
        strength = min(100, base_strength * 100 * synergy_bonus)
        strength = round(strength, 1)

        # 2. 维度标签
        dims = set()
        for p in patterns:
            dim = self.CATEGORY_DIM_MAP.get(p.category, "其他")
            dims.add(dim)

        # 3. 模式标签
        tags = []
        for p in patterns:
            label_map = {m.name: m.description.split(":")[0]
                        for m in [__import__('app.engine.patterns.registry',
                                             fromlist=['PatternRegistry']).PatternRegistry().get(p.name)]
                        if m}
            label = p.name
            tags.append(PatternTag(name=p.name, label=label, direction=p.direction))

        # 4. 支撑/阻力评估
        support = min((p.levels.support for p in patterns if p.levels and p.levels.support),
                     default=latest_close * 0.95 if latest_close else None)
        resistance = max((p.levels.resistance for p in patterns if p.levels and p.levels.resistance),
                        default=latest_close * 1.05 if latest_close else None)

        sr_label = self._build_sr_label(support, resistance, direction, latest_close)
        sr_direction = direction

        # 5. 成交量确认
        vol_patterns = [p for p in patterns if p.category in (
            PatternCategory.VOLUME, PatternCategory.VOLUME_PRICE)]
        vol_confirmed = any(
            v.name in ('VP-1', 'volume_tuo', 'sanlian_yang_fangliang')
            for v in vol_patterns
        ) if direction == 'bullish' else any(
            v.name in ('VP-7', 'volume_ya', 'fangliang_changyin_tupo')
            for v in vol_patterns
        )

        # 6. 有效期限
        expires = (datetime.now() + timedelta(days=5)).strftime("%m/%d")

        # 7. 组合名称
        combo_name = self._generate_combo_name(patterns, direction)

        # 8. 解读
        interpretation = self._build_interpretation(patterns, direction, strength, vol_confirmed)

        # 9. 操作提示
        hint = self._build_hint(direction, strength)

        # 10. 失效条件
        invalidation = self._build_invalidation(patterns, direction, latest_close)

        # 11. 价格层级
        levels = None
        if support or resistance:
            levels = PatternLevel(
                support=support,
                resistance=resistance,
                target=resistance * 1.1 if resistance and direction == 'bullish'
                       else support * 0.9 if support and direction == 'bearish'
                       else None,
                invalidation=support * 0.97 if support and direction == 'bullish'
                            else resistance * 1.03 if resistance and direction == 'bearish'
                            else None,
            )

        return ComboCard(
            name=combo_name,
            direction=direction,
            strength=strength,
            resolution=resolution,
            expires=expires,
            patterns=tags,
            dim_tags=sorted(dims),
            sr_tag={'label': sr_label, 'direction': sr_direction},
            vol_confirmed=vol_confirmed,
            interpretation=interpretation,
            hint=hint,
            invalidation=invalidation,
            levels=levels,
        )

    def _calc_synergy(self, patterns: List[PatternResult]) -> float:
        """计算模式间的协同效应加成"""
        names = [p.name for p in patterns]
        bonus = 1.0
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                mult = self.synergy_map.get((names[i], names[j]), 1.0)
                bonus *= mult
        return bonus

    def _generate_combo_name(self, patterns: List[PatternResult],
                             direction: str) -> str:
        """根据模式自动生成组合名称"""
        has_divergence = any(p.category == PatternCategory.DIVERGENCE for p in patterns)
        has_breakout = any(p.category == PatternCategory.BREAKOUT for p in patterns)
        has_volume = any(p.category in (PatternCategory.VOLUME, PatternCategory.VOLUME_PRICE)
                        for p in patterns)

        prefix = ""
        if has_divergence and has_breakout:
            prefix = "背离+突破"
        elif has_divergence and has_volume:
            prefix = "背离+量价"
        elif has_breakout and has_volume:
            prefix = "突破放量"
        elif has_divergence:
            prefix = "背离信号"
        elif has_breakout:
            prefix = "突破信号"
        else:
            prefix = "多形态"

        suffix = "共振" if len(patterns) >= 3 else "组合"
        return f"{prefix}{suffix}"

    def _build_sr_label(self, support: Optional[float], resistance: Optional[float],
                       direction: str, latest_close: Optional[float]) -> str:
        """构建支撑/阻力评估"""
        if support and resistance:
            return f"支撑{support:.2f} / 阻力{resistance:.2f}"
        if direction == 'bullish' and support:
            return f"支撑位{support:.2f}"
        if direction == 'bearish' and resistance:
            return f"阻力位{resistance:.2f}"
        return "关键位待确认"

    def _build_interpretation(self, patterns: List[PatternResult],
                             direction: str, strength: float,
                             vol_confirmed: bool) -> str:
        """构建综合分析解读"""
        pattern_names = []
        for p in patterns[:4]:
            label_map = {
                'big_yang': '大阳线', 'doji': '十字星',
                'macd_bullish_divergence': 'MACD底背离',
                'macd_bearish_divergence': 'MACD顶背离',
                'triple_bullish_divergence': '三重底背离',
                'triple_bearish_divergence': '三重顶背离',
                'volume_tuo': '量托', 'volume_ya': '量压',
                'sanlian_yang_fangliang': '三连阳放量',
                'chonggao_huiluo_jisuo': '冲高回落缩量',
                'dizeng_fangliang_xiajie': '递增放量下跌',
                'huiluo_zhangting_qiangshi': '堆量跌回起点',
                'fangliang_changyin_tupo': '放量长阴破位',
                'first_buy': '一买', 'second_buy': '二买',
                'third_buy': '三买', 'first_sell': '一卖',
                'second_sell': '二卖', 'third_sell': '三卖',
            }
            cn = label_map.get(p.name, p.name)
            pattern_names.append(cn)

        vol_note = "成交量确认" if vol_confirmed else "量能待确认"
        dir_cn = "看多" if direction == 'bullish' else "看空"
        return f"检测到{'、'.join(pattern_names)}等{len(patterns)}个{dir_cn}模式，" \
               f"综合强度{strength:.0f}/100，{vol_note}"

    def _build_hint(self, direction: str, strength: float) -> str:
        """构建操作提示"""
        if direction == 'bullish':
            if strength >= 70:
                return "多信号共振确认，可重点关注买入时机"
            elif strength >= 50:
                return "信号偏多，纳入观察清单，等待右侧确认"
            else:
                return "有初步看多信号，继续观察"
        elif direction == 'bearish':
            if strength >= 70:
                return "空信号共振确认，注意风险，考虑减仓或观望"
            elif strength >= 50:
                return "信号偏空，注意下行风险"
            else:
                return "有初步看空信号，保持警惕"
        return "等待方向明确"

    def _build_invalidation(self, patterns: List[PatternResult],
                           direction: str,
                           latest_close: Optional[float]) -> str:
        """构建失效条件"""
        conditions = []
        for p in patterns:
            if p.levels and direction == 'bullish' and p.levels.invalidation:
                conditions.append(f"跌破{p.levels.invalidation:.2f}")
            elif p.levels and direction == 'bearish' and p.levels.invalidation:
                conditions.append(f"突破{p.levels.invalidation:.2f}")

        if conditions:
            return " 或 ".join(conditions[:2])
        if latest_close and direction == 'bullish':
            return f"跌破{latest_close * 0.95:.2f}失效"
        elif latest_close and direction == 'bearish':
            return f"突破{latest_close * 1.05:.2f}失效"
        return "市场方向反转"


def build_combos(patterns: List[PatternResult],
                 resolution: str = "日线") -> List[ComboCard]:
    """快捷函数"""
    return ComboEngine().build_combos(patterns, resolution)
