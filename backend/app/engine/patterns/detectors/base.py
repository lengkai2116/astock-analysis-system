"""
形态检测器基类
定义统一的检测接口
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
import pandas as pd

from app.engine.patterns import PatternResult


class PatternDetector(ABC):
    """形态检测器基类"""

    @abstractmethod
    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """
        检测形态

        Args:
            df: K线数据，至少包含 open/high/low/close/volume
            context: 上下文信息，如均线、筹码分布等

        Returns:
            List[PatternResult]: 检测到的形态列表
        """
        pass

    def _calculate_ma(self, series: pd.Series, window: int) -> pd.Series:
        """计算移动平均"""
        return series.rolling(window=window, min_periods=1).mean()

    def _calculate_volume_ma(self, df: pd.DataFrame, window: int) -> pd.Series:
        """计算成交量均线"""
        return df['volume'].rolling(window=window, min_periods=1).mean()
