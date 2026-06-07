"""
PatternTracker — 模式生命周期追踪器
====================================
跨 K 线追踪模式演变，实现观潮 evolving 机制。
参考方案152 §4.2 策略二：模式生命周期追踪（P1）

适用场景：
  - 三角整理（ascending_triangle_evolving）
  - 双底/双顶（double_bottom_evolving）
  - 头肩顶底形成
  - 缺口回补
"""

from typing import Dict, List, Optional, Callable
import pandas as pd
import numpy as np

from . import PatternResult, PatternStage
from .registry import PatternRegistry


class PatternTracker:
    """
    跨 K 线追踪模式演变的管理器
    每来一根新 K 线，更新所有活跃模式的状态。
    """

    def __init__(self):
        self.registry = PatternRegistry()
        self.active_patterns: Dict[str, PatternResult] = {}
        self.history: List[PatternResult] = []
        self._prev_df: Optional[pd.DataFrame] = None

    def update(self, df: pd.DataFrame) -> List[PatternResult]:
        """
        根据最新数据更新所有活跃模式

        流程：
          1. 对活跃中的模式，检查确认/失效/完成度
          2. 回收集成失效的模式到历史记录
          3. 返回状态变化的模式列表
        """
        if df.empty or len(df) < 5:
            return []

        updates = []
        to_remove = []

        for name, pattern in self.active_patterns.items():
            if pattern.stage == PatternStage.FORMING:
                # 检查是否满足确认条件
                if self._check_confirmed(df, pattern):
                    pattern.stage = PatternStage.CONFIRMING
                    pattern.completion = 60.0
                elif self._check_invalidated(df, pattern):
                    pattern.stage = PatternStage.INVALIDATED
                    pattern.completion = 100.0
                    to_remove.append(name)
                else:
                    pattern.completion = min(95.0,
                        self._calc_completion(df, pattern))
                    pattern.eta = self._calc_eta(df, pattern)
                updates.append(pattern)

            elif pattern.stage == PatternStage.CONFIRMING:
                if self._check_completed(df, pattern):
                    pattern.stage = PatternStage.COMPLETED
                    pattern.completion = 100.0
                    to_remove.append(name)
                elif self._check_invalidated(df, pattern):
                    pattern.stage = PatternStage.INVALIDATED
                    pattern.completion = 100.0
                    to_remove.append(name)
                else:
                    pattern.completion = 85.0
                updates.append(pattern)

        # 回收已完成/失效的模式
        for name in to_remove:
            p = self.active_patterns.pop(name)
            self.history.append(p)

        self._prev_df = df.copy() if df is not None else None
        return updates

    def track(self, pattern: PatternResult):
        """开始追踪一个新模式"""
        if pattern.name not in self.active_patterns:
            pattern.stage = PatternStage.FORMING
            pattern.completion = 10.0
            self.active_patterns[pattern.name] = pattern

    def untrack(self, name: str):
        """停止追踪一个模式"""
        if name in self.active_patterns:
            p = self.active_patterns.pop(name)
            self.history.append(p)

    def get_active(self) -> List[PatternResult]:
        """获取当前活跃（形成中/确认中）的模式列表"""
        return [
            p for p in self.active_patterns.values()
            if p.stage in (PatternStage.FORMING, PatternStage.CONFIRMING)
        ]

    def get_completed(self, limit: int = 20) -> List[PatternResult]:
        """获取最近完成的模式"""
        completed = [p for p in self.history
                     if p.stage == PatternStage.COMPLETED]
        return completed[-limit:]

    def reset(self):
        """重置追踪器状态"""
        self.active_patterns.clear()
        self.history.clear()
        self._prev_df = None

    # ── 内部方法（子类可覆盖） ──

    def _check_confirmed(self, df: pd.DataFrame, pattern: PatternResult) -> bool:
        """检查模式是否已确认（子类可覆写具体逻辑）"""
        return False

    def _check_completed(self, df: pd.DataFrame, pattern: PatternResult) -> bool:
        """检查模式是否已完成（子类可覆写）"""
        return False

    def _check_invalidated(self, df: pd.DataFrame, pattern: PatternResult) -> bool:
        """检查模式是否已失效（子类可覆写）"""
        return False

    def _calc_completion(self, df: pd.DataFrame, pattern: PatternResult) -> float:
        """估算模式完成度（子类可覆写）"""
        return pattern.completion + 5.0

    def _calc_eta(self, df: pd.DataFrame, pattern: PatternResult) -> Optional[int]:
        """估算还需多少根 K 线完成（子类可覆写）"""
        return None
