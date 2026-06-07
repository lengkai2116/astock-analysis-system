"""
缠论策略适配器 — ChanlunStrategy BuySellPoint → PatternResult
===============================================================
将 chanlun_strategy.py 中 BuySellPointDetector / ChanlunScorer 检测到的
买卖点信号映射为统一 PatternResult。

覆盖 8 种缠论形态：
  一买/二买/三买/类二买、一卖/二卖/三卖/类二卖
"""

from typing import List, Optional, Dict
import pandas as pd

from app.engine.patterns import (
    PatternResult, PatternCategory, PatternStage, PatternLevel
)
from app.engine.patterns.registry import PatternRegistry

# 缠论买卖点 → 模式名映射
_CHANLUN_POINT_MAP = {
    "first_buy": ("first_buy", "bullish"),
    "second_buy": ("second_buy", "bullish"),
    "third_buy": ("third_buy", "bullish"),
    "second_like_buy": ("second_like_buy", "bullish"),
    "first_sell": ("first_sell", "bearish"),
    "second_sell": ("second_sell", "bearish"),
    "third_sell": ("third_sell", "bearish"),
    "second_like_sell": ("second_like_sell", "bearish"),
}


class ChanlunPatternAdapter:
    """
    缠论模式适配器
    接收 BuySellPointDetector 的检测结果，输出 PatternResult 列表
    """

    def __init__(self):
        self.registry = PatternRegistry()

    def from_buy_sell_points(self, points: List[Dict],
                             latest_close: float) -> List[PatternResult]:
        """
        从买卖点检测结果构建 PatternResult

        Args:
            points: BuySellPointDetector 输出的买卖点列表
                    每个点包含: type, price, strength, zhongshu_range, ...
            latest_close: 当前收盘价（用于计算 levels）

        Returns:
            匹配的 PatternResult 列表
        """
        results = []
        seen = set()

        for pt in points:
            point_type = pt.get('type', '')
            if point_type not in _CHANLUN_POINT_MAP:
                continue

            name, direction = _CHANLUN_POINT_MAP[point_type]

            # 避免重复
            if name in seen:
                continue
            seen.add(name)

            meta = self.registry.get(name)
            if meta is None:
                continue

            price = pt.get('price', 0)
            strength = pt.get('strength', 0.5)
            zhongshu_range = pt.get('zhongshu_range', (0, 0))
            zhongshu_low, zhongshu_high = (zhongshu_range if isinstance(
                zhongshu_range, (list, tuple)) else (0, 0))

            # 构建价格层级
            levels = PatternLevel()
            if direction == 'bullish':
                levels.support = zhongshu_low if zhongshu_low > 0 else price * 0.95
                levels.resistance = latest_close * 1.05
                levels.target = price * 1.15 if price > 0 else None
                levels.invalidation = zhongshu_low if zhongshu_low > 0 else price * 0.93
            else:
                levels.support = latest_close * 0.95
                levels.resistance = zhongshu_high if zhongshu_high > 0 else price * 1.05
                levels.target = price * 0.85 if price > 0 else None
                levels.invalidation = zhongshu_high if zhongshu_high > 0 else price * 1.07

            conditions = []
            if zhongshu_low > 0:
                conditions.append(f"中枢区间[{zhongshu_low:.2f},{zhongshu_high:.2f}]")
            if price > 0:
                conditions.append(f"买卖点价格{price:.2f}")

            results.append(PatternResult(
                name=name,
                category=PatternCategory.CHANLUN,
                direction=direction,
                strength=min(strength, 1.0),
                stage=PatternStage.COMPLETED,
                completion=100.0,
                conditions=conditions,
                levels=levels,
                interpretation=meta.description,
                detail={
                    'point_price': float(price),
                    'zhongshu_low': float(zhongshu_low),
                    'zhongshu_high': float(zhongshu_high),
                    'latest_close': float(latest_close),
                },
                source="chanlun_strategy.py",
            ))

        return results

    def from_analysis_result(self, analysis: Dict) -> List[PatternResult]:
        """
        从 ChanlunAnalyzer 分析结果构建所有 PatternResult

        Args:
            analysis: ChanlunAnalyzer 的 analyze() 返回值
                      含 stock_buy_points, stock_sell_points 等字段

        Returns:
            所有检测到的模式列表
        """
        results = []

        buy_points = analysis.get('stock_buy_points', [])
        sell_points = analysis.get('stock_sell_points', [])
        latest_close = analysis.get('latest_close',
                        analysis.get('current_price', 0))

        all_points = buy_points + sell_points
        if all_points and latest_close > 0:
            results.extend(self.from_buy_sell_points(all_points, latest_close))

        return results
