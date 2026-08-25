"""
K线形态适配器 — 重构版
=======================
使用 PatternEngine 统一调度，保持向后兼容。

原版在本类内硬编码 16 种 K 线形态的检测逻辑（~380 行）。
重构后内部调用 PatternEngine.detect_all()，由引擎分发至各 Detector。

原有接口保持不变：
  - detect(df) → List[PatternResult]  （新增可选 context 参数）
"""
from typing import List, Optional, Dict
import pandas as pd

from app.engine.patterns import PatternResult
from app.engine.patterns.engine import PatternEngine


class KLinePatternAdapter:
    """
    K 线形态检测适配器（重构版）

    内部使用 PatternEngine 统一调度，
    外部接口保持向后兼容。
    """

    def __init__(self):
        self.engine = PatternEngine()

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """
        检测所有匹配的形态，返回 PatternResult 列表。

        Parameters
        ----------
        df : pd.DataFrame
            K 线数据（需含 open/high/low/close/volume 等列）
        context : dict, optional
            附加上下文（如 stock_code, market 等）

        Returns
        -------
        List[PatternResult]
        """
        return self.engine.detect_all(df, context)

    def evaluate(self, df: pd.DataFrame, context: Optional[Dict] = None) -> tuple:
        """
        一站式评估：检测 + 聚合评分。

        Returns
        -------
        tuple
            (score: float, details: dict)
        """
        return self.engine.evaluate(df, context)
