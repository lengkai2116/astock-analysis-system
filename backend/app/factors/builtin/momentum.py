"""
动量类因子
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


class ROC(BaseFactor):
    """
    ROC (Rate of Change) - 变动率因子
    """
    name = "ROC"
    name_cn = "变动率"
    category = "momentum"
    subcategory = "price_momentum"
    description = "计算价格变化率，(Close - Close_N) / Close_N"
    formula = "ROC = (Close / Close_N - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 12, "int", 1, 252, "回看周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        close = data["close"]
        roc = (close / close.shift(period) - 1) * 100
        return roc


class RSI(BaseFactor):
    """
    RSI (Relative Strength Index) - 相对强弱指数
    """
    name = "RSI"
    name_cn = "相对强弱指数"
    category = "momentum"
    subcategory = "price_momentum"
    description = "衡量价格涨跌幅度，识别超买超卖"
    formula = "RSI = 100 - 100 / (1 + Avg_Gain / Avg_Loss)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 14, "int", 2, 252, "回看周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        close = data["close"]
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        avg_loss_safe = avg_loss.where(avg_loss != 0, 1e-10)
        rs = avg_gain / avg_loss_safe
        rsi = 100 - (100 / (1 + rs))
        
        return rsi


class CCI(BaseFactor):
    """
    CCI (Commodity Channel Index) - 顺势指标
    """
    name = "CCI"
    name_cn = "顺势指标"
    category = "momentum"
    subcategory = "price_momentum"
    description = "衡量价格偏离平均值的程度"
    formula = "CCI = (Typical_Price - MA_Typical_Price) / (0.015 * Mean_Deviation)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = [
        FactorParam("period", 14, "int", 2, 252, "回看周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        tp = (data["high"] + data["low"] + data["close"]) / 3
        tp_ma = tp.rolling(window=period).mean()
        md = tp.rolling(window=period).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
        
        cci = (tp - tp_ma) / (0.015 * md.replace(0, np.nan))
        return cci


class MOM(BaseFactor):
    """
    MOM (Momentum) - 动量因子
    """
    name = "MOM"
    name_cn = "动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "计算价格绝对变化"
    formula = "MOM = Close - Close_N"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 10, "int", 1, 252, "回看周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data["close"] - data["close"].shift(period)


class MACD_DIF(BaseFactor):
    """
    MACD DIF - MACD差离值
    """
    name = "MACD_DIF"
    name_cn = "MACD差离值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "EMA12 - EMA26"
    formula = "DIF = EMA(Close, 12) - EMA(Close, 26)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("fast_period", 12, "int", 2, 252, "快线周期"),
        FactorParam("slow_period", 26, "int", 2, 252, "慢线周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast_period")
        slow = self.get_param("slow_period")
        
        ema_fast = data["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = data["close"].ewm(span=slow, adjust=False).mean()
        
        return ema_fast - ema_slow


class MACD_DEA(BaseFactor):
    """
    MACD DEA - MACD讯号线
    """
    name = "MACD_DEA"
    name_cn = "MACD讯号线"
    category = "momentum"
    subcategory = "price_momentum"
    description = "EMA(DIF, 9)"
    formula = "DEA = EMA(DIF, 9)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("fast_period", 12, "int", 2, 252, "快线周期"),
        FactorParam("slow_period", 26, "int", 2, 252, "慢线周期"),
        FactorParam("signal_period", 9, "int", 2, 252, "信号周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast_period")
        slow = self.get_param("slow_period")
        signal = self.get_param("signal_period")
        
        ema_fast = data["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = data["close"].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        
        return dea


class KDJ_K(BaseFactor):
    """
    KDJ K值
    """
    name = "KDJ_K"
    name_cn = "KDJ-K值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "随机指标K值"
    formula = "K = EMA(RSV, M1)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("n", 9, "int", 2, 252, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 50, "K值平滑周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        n = self.get_param("n")
        m1 = self.get_param("m1")
        
        low_n = data["low"].rolling(window=n).min()
        high_n = data["high"].rolling(window=n).max()
        rsv = (data["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        return k


class KDJ_D(BaseFactor):
    """
    KDJ D值
    """
    name = "KDJ_D"
    name_cn = "KDJ-D值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "随机指标D值"
    formula = "D = EMA(K, M2)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("n", 9, "int", 2, 252, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 50, "K值平滑周期"),
        FactorParam("m2", 3, "int", 2, 50, "D值平滑周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        n = self.get_param("n")
        m1 = self.get_param("m1")
        m2 = self.get_param("m2")
        
        low_n = data["low"].rolling(window=n).min()
        high_n = data["high"].rolling(window=n).max()
        rsv = (data["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        
        return d


class KDJ_J(BaseFactor):
    """
    KDJ J值
    """
    name = "KDJ_J"
    name_cn = "KDJ-J值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "随机指标J值"
    formula = "J = 3 * K - 2 * D"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("n", 9, "int", 2, 252, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 50, "K值平滑周期"),
        FactorParam("m2", 3, "int", 2, 50, "D值平滑周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        n = self.get_param("n")
        m1 = self.get_param("m1")
        m2 = self.get_param("m2")
        
        low_n = data["low"].rolling(window=n).min()
        high_n = data["high"].rolling(window=n).max()
        rsv = (data["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        j = 3 * k - 2 * d
        
        return j
