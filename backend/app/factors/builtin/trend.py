"""
趋势类因子
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


class MA(BaseFactor):
    """
    MA (Moving Average) - 简单移动平均
    """
    name = "MA"
    name_cn = "简单移动平均"
    category = "trend"
    subcategory = "price_trend"
    description = "简单移动平均线"
    formula = "MA = SUM(Close, N) / N"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 1, 252, "平均周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data["close"].rolling(window=period).mean()


class EMA(BaseFactor):
    """
    EMA (Exponential Moving Average) - 指数移动平均
    """
    name = "EMA"
    name_cn = "指数移动平均"
    category = "trend"
    subcategory = "price_trend"
    description = "指数移动平均线，最近价格权重更高"
    formula = "EMA_t = (Close_t - EMA_{t-1}) * 2/(N+1) + EMA_{t-1}"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 1, 252, "平均周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data["close"].ewm(span=period, adjust=False).mean()


class SMA(BaseFactor):
    """
    SMA (Simple Moving Average) - 另一种简单移动平均
    """
    name = "SMA"
    name_cn = "平滑移动平均"
    category = "trend"
    subcategory = "price_trend"
    description = "平滑移动平均线"
    formula = "SMA_t = (Close_t + SMA_{t-1} * (N-1)) / N"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 20, "int", 1, 252, "平均周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data["close"].ewm(com=period-1, adjust=False).mean()


class ADX(BaseFactor):
    """
    ADX (Average Directional Index) - 平均趋向指数
    """
    name = "ADX"
    name_cn = "平均趋向指数"
    category = "trend"
    subcategory = "trend_strength"
    description = "衡量趋势强度，0-100，越高趋势越强"
    formula = "ADX = MA(ABS(+DI - -DI) / (+DI + -DI) * 100, N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 14, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        high = data["high"]
        low = data["low"]
        close = data["close"]
        
        up = high - high.shift(1)
        down = low.shift(1) - low
        
        plus_dm = up.where((up > 0) & (up > down), 0)
        minus_dm = down.where((down > 0) & (down > up), 0)
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.rolling(window=period).mean()
        
        return adx


class LINEARREG_SLOPE(BaseFactor):
    """
    Linear Regression Slope - 线性回归斜率
    """
    name = "LINEARREG_SLOPE"
    name_cn = "线性回归斜率"
    category = "trend"
    subcategory = "trend_direction"
    description = "价格线性回归的斜率，衡量趋势方向"
    formula = "Slope = Cov(Close, Time) / Var(Time)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "回归周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        def slope_func(x):
            if len(x) < 2:
                return np.nan
            t = np.arange(len(x))
            return np.polyfit(t, x, 1)[0]
        
        return data["close"].rolling(window=period).apply(slope_func, raw=True)


class RET(BaseFactor):
    """
    RET (Return) - 收益率
    """
    name = "RET"
    name_cn = "收益率"
    category = "trend"
    subcategory = "price_trend"
    description = "N期收益率"
    formula = "RET = (Close / Close_N - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 1, "int", 1, 252, "收益周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data["close"] / data["close"].shift(period) - 1) * 100
