"""
成交量类因子
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


class VOL_MA(BaseFactor):
    """
    Volume MA - 成交量均线
    """
    name = "VOL_MA"
    name_cn = "成交量均线"
    category = "volume"
    subcategory = "volume_trend"
    description = "成交量的移动平均线"
    formula = "VOL_MA = MA(Volume, N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 5, "int", 1, 252, "平均周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data["vol"].rolling(window=period).mean()


class VR(BaseFactor):
    """
    VR (Volume Ratio) - 成交量比率
    """
    name = "VR"
    name_cn = "成交量比率"
    category = "volume"
    subcategory = "volume_momentum"
    description = "衡量成交量比率"
    formula = "VR = (UpVol + 0.5 * FlatVol) / (DownVol + 0.5 * FlatVol)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 26, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        close = data["close"]
        vol = data["vol"]
        
        up_vol = vol.where(close > close.shift(1), 0)
        down_vol = vol.where(close < close.shift(1), 0)
        flat_vol = vol.where(close == close.shift(1), 0)
        
        up_sum = up_vol.rolling(window=period).sum()
        down_sum = down_vol.rolling(window=period).sum()
        flat_sum = flat_vol.rolling(window=period).sum()
        
        vr = (up_sum + 0.5 * flat_sum) / (down_sum + 0.5 * flat_sum).replace(0, np.nan)
        return vr


class OBV(BaseFactor):
    """
    OBV (On Balance Volume) - 能量潮
    """
    name = "OBV"
    name_cn = "能量潮"
    category = "volume"
    subcategory = "volume_momentum"
    description = "累积成交量指标"
    formula = "OBV = OBV_prev + Volume if Close > Close_prev, OBV_prev - Volume if Close < Close_prev"
    source = "Academic"
    source_detail = "Academic"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        vol = data["vol"]
        
        sign = np.where(close > close.shift(1), 1, 
                       np.where(close < close.shift(1), -1, 0))
        obv = (sign * vol).cumsum()
        
        return obv


class AMOUNT(BaseFactor):
    """
    Amount - 成交额
    """
    name = "AMOUNT"
    name_cn = "成交额"
    category = "volume"
    subcategory = "volume_basic"
    description = "成交额 = Close * Volume"
    formula = "Amount = Close * Volume"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data["close"] * data["vol"]


class AMOUNT_MA(BaseFactor):
    """
    Amount MA - 成交额均线
    """
    name = "AMOUNT_MA"
    name_cn = "成交额均线"
    category = "volume"
    subcategory = "volume_trend"
    description = "成交额的移动平均线"
    formula = "AMOUNT_MA = MA(Close * Volume, N)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 5, "int", 1, 252, "平均周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data["close"] * data["vol"]
        return amount.rolling(window=period).mean()


class VOL_RATIO(BaseFactor):
    """
    Volume Ratio - 量比
    """
    name = "VOL_RATIO"
    name_cn = "量比"
    category = "volume"
    subcategory = "volume_momentum"
    description = "当前成交量与过去N日平均成交量的比值"
    formula = "VOL_RATIO = Volume / MA(Volume, N)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 5, "int", 1, 252, "平均周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        vol_ma = data["vol"].rolling(window=period).mean()
        return data["vol"] / vol_ma.replace(0, np.nan)
