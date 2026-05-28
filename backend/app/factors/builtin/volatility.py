"""
波动率类因子
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


class ATR(BaseFactor):
    """
    ATR (Average True Range) - 平均真实波幅
    """
    name = "ATR"
    name_cn = "平均真实波幅"
    category = "volatility"
    subcategory = "price_volatility"
    description = "衡量价格波动率，考虑缺口"
    formula = "TR = MAX(High-Low, |High-PrevClose|, |Low-PrevClose|), ATR = MA(TR, N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 14, "int", 2, 252, "平均周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        prev_close = data["close"].shift(1)
        tr1 = data["high"] - data["low"]
        tr2 = abs(data["high"] - prev_close)
        tr3 = abs(data["low"] - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr


class STD(BaseFactor):
    """
    STD (Standard Deviation) - 价格标准差
    """
    name = "STD"
    name_cn = "价格标准差"
    category = "volatility"
    subcategory = "price_volatility"
    description = "计算价格的标准差"
    formula = "STD = STD(Close, N)"
    source = "Academic"
    source_detail = "Academic"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data["close"].rolling(window=period).std()


class BOLL_UPPER(BaseFactor):
    """
    BOLL Upper - 布林带上轨
    """
    name = "BOLL_UPPER"
    name_cn = "布林带上轨"
    category = "volatility"
    subcategory = "price_volatility"
    description = "布林带上轨 = MA + K * STD"
    formula = "BOLL_UPPER = MA(Close, N) + K * STD(Close, N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "平均周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 5.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        ma = data["close"].rolling(window=period).mean()
        std = data["close"].rolling(window=period).std()
        
        return ma + std_dev * std


class BOLL_LOWER(BaseFactor):
    """
    BOLL Lower - 布林带下轨
    """
    name = "BOLL_LOWER"
    name_cn = "布林带下轨"
    category = "volatility"
    subcategory = "price_volatility"
    description = "布林带下轨 = MA - K * STD"
    formula = "BOLL_LOWER = MA(Close, N) - K * STD(Close, N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "平均周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 5.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        ma = data["close"].rolling(window=period).mean()
        std = data["close"].rolling(window=period).std()
        
        return ma - std_dev * std


class VOLATILITY(BaseFactor):
    """
    Volatility - 波动率（年化）
    """
    name = "VOLATILITY"
    name_cn = "年化波动率"
    category = "volatility"
    subcategory = "price_volatility"
    description = "计算收益率的年化波动率"
    formula = "Volatility = STD(Returns, N) * sqrt(252)"
    source = "Academic"
    source_detail = "Academic"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data["close"].pct_change()
        vol = returns.rolling(window=period).std() * np.sqrt(252)
        return vol


class HV(BaseFactor):
    """
    HV (Historical Volatility) - 历史波动率
    """
    name = "HV"
    name_cn = "历史波动率"
    category = "volatility"
    subcategory = "price_volatility"
    description = "对数收益率的标准差"
    formula = "HV = STD(Ln(Close/PrevClose), N) * sqrt(252)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        log_returns = np.log(data["close"] / data["close"].shift(1))
        hv = log_returns.rolling(window=period).std() * np.sqrt(252)
        return hv
