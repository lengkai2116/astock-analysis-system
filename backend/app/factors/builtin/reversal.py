"""
反转类因子
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


class BIAS(BaseFactor):
    """
    BIAS - 乖离率
    """
    name = "BIAS"
    name_cn = "乖离率"
    category = "reversal"
    subcategory = "price_reversal"
    description = "价格偏离均线的程度"
    formula = "BIAS = (Close - MA) / MA * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 12, "int", 2, 252, "均线周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ma = data["close"].rolling(window=period).mean()
        bias = (data["close"] - ma) / ma.replace(0, np.nan) * 100
        return bias


class WILLR(BaseFactor):
    """
    Williams %R - 威廉指标
    """
    name = "WILLR"
    name_cn = "威廉指标"
    category = "reversal"
    subcategory = "price_reversal"
    description = "衡量超买超卖，0-100，越高越超卖"
    formula = "WILLR = (HighestHigh - Close) / (HighestHigh - LowestLow) * (-100)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 14, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        high_n = data["high"].rolling(window=period).max()
        low_n = data["low"].rolling(window=period).min()
        willr = (high_n - data["close"]) / (high_n - low_n).replace(0, np.nan) * (-100)
        return willr


class RSV(BaseFactor):
    """
    RSV (Raw Stochastic Value) - 未成熟随机值
    """
    name = "RSV"
    name_cn = "未成熟随机值"
    category = "reversal"
    subcategory = "price_reversal"
    description = "KDJ的基础指标"
    formula = "RSV = (Close - LowestLow) / (HighestHigh - LowestLow) * 100"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 9, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        low_n = data["low"].rolling(window=period).min()
        high_n = data["high"].rolling(window=period).max()
        rsv = (data["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        return rsv


class CMO(BaseFactor):
    """
    CMO (Chande Momentum Oscillator) - 钱德动量摆动指标
    """
    name = "CMO"
    name_cn = "钱德动量摆动指标"
    category = "reversal"
    subcategory = "price_reversal"
    description = "改进的RSI，-100到100"
    formula = "CMO = (UpSum - DownSum) / (UpSum + DownSum) * 100"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = [
        FactorParam("period", 14, "int", 2, 252, "计算周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        close = data["close"]
        diff = close.diff()
        up = diff.where(diff > 0, 0)
        down = -diff.where(diff < 0, 0)
        
        up_sum = up.rolling(window=period).sum()
        down_sum = down.rolling(window=period).sum()
        
        cmo = (up_sum - down_sum) / (up_sum + down_sum).replace(0, np.nan) * 100
        return cmo


class ROC_R(BaseFactor):
    """
    ROC Rank - 收益率排序
    """
    name = "ROC_R"
    name_cn = "收益率排序因子"
    category = "reversal"
    subcategory = "cross_section"
    description = "横截面收益率排序（用于选股）"
    formula = "ROC_R = Rank(ROC(5))"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 5, "int", 1, 252, "收益率周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        roc = (data["close"] / data["close"].shift(period) - 1) * 100
        return roc


class MOM_R(BaseFactor):
    """
    Momentum Rank - 动量排序
    """
    name = "MOM_R"
    name_cn = "动量排序因子"
    category = "reversal"
    subcategory = "cross_section"
    description = "横截面动量排序（用于选股）"
    formula = "MOM_R = Rank(MOM(20))"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 20, "int", 1, 252, "动量周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        mom = data["close"] - data["close"].shift(period)
        return mom
