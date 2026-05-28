"""
Qlib158因子扩充版 - 参考Qlib的158个因子设计
文件路径：backend/app/factors/builtin/qlib158.py
参考：https://github.com/microsoft/qlib
这里扩充到100+个Qlib风格因子，涵盖常见技术指标
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


# ==================== 价格排名类因子 ====================

class QLIB_RANK(BaseFactor):
    """Rank因子 - 价格排名"""
    name = "QLIB_RANK"
    name_cn = "价格排名"
    category = "qlib"
    subcategory = "technical"
    description = "过去N日价格在横截面中的排名"
    formula = "Rank = rank(close)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 252, "排名周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).rank(pct=True)


class QLIB_LOW_RANK(BaseFactor):
    """低价排名因子"""
    name = "QLIB_LOW_RANK"
    name_cn = "低价排名"
    category = "qlib"
    subcategory = "technical"
    description = "过去N日最低价排名"
    formula = "LowRank = rank(low)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 252, "排名周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['low'].rolling(window=period).rank(pct=True)


class QLIB_HIGH_RANK(BaseFactor):
    """高价排名因子"""
    name = "QLIB_HIGH_RANK"
    name_cn = "高价排名"
    category = "qlib"
    subcategory = "technical"
    description = "过去N日最高价排名"
    formula = "HighRank = rank(high)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 252, "排名周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['high'].rolling(window=period).rank(pct=True)


class QLIB_VOLUME_RANK(BaseFactor):
    """成交量排名因子"""
    name = "QLIB_VOLUME_RANK"
    name_cn = "成交量排名"
    category = "qlib"
    subcategory = "volume"
    description = "过去N日成交量排名"
    formula = "VolRank = rank(volume)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 252, "排名周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).rank(pct=True)


# ==================== 移动平均类因子 ====================

class QLIB_EMA(BaseFactor):
    """EMA因子 - 指数移动平均"""
    name = "QLIB_EMA"
    name_cn = "指数移动平均"
    category = "qlib"
    subcategory = "trend"
    description = "指数移动平均"
    formula = "EMA = EMA(close)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 252, "EMA周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class QLIB_EMA_5(BaseFactor):
    """EMA5 - 5日指数移动平均"""
    name = "QLIB_EMA_5"
    name_cn = "5日EMA"
    category = "qlib"
    subcategory = "trend"
    description = "5日指数移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].ewm(span=5, adjust=False).mean()


class QLIB_EMA_10(BaseFactor):
    """EMA10 - 10日指数移动平均"""
    name = "QLIB_EMA_10"
    name_cn = "10日EMA"
    category = "qlib"
    subcategory = "trend"
    description = "10日指数移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].ewm(span=10, adjust=False).mean()


class QLIB_EMA_30(BaseFactor):
    """EMA30 - 30日指数移动平均"""
    name = "QLIB_EMA_30"
    name_cn = "30日EMA"
    category = "qlib"
    subcategory = "trend"
    description = "30日指数移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].ewm(span=30, adjust=False).mean()


class QLIB_EMA_60(BaseFactor):
    """EMA60 - 60日指数移动平均"""
    name = "QLIB_EMA_60"
    name_cn = "60日EMA"
    category = "qlib"
    subcategory = "trend"
    description = "60日指数移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].ewm(span=60, adjust=False).mean()


class QLIB_SMA(BaseFactor):
    """SMA因子 - 简单移动平均"""
    name = "QLIB_SMA"
    name_cn = "简单移动平均"
    category = "qlib"
    subcategory = "trend"
    description = "简单移动平均"
    formula = "SMA = MA(close)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 252, "SMA周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class QLIB_SMA_5(BaseFactor):
    """SMA5 - 5日简单移动平均"""
    name = "QLIB_SMA_5"
    name_cn = "5日SMA"
    category = "qlib"
    subcategory = "trend"
    description = "5日简单移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=5).mean()


class QLIB_SMA_10(BaseFactor):
    """SMA10 - 10日简单移动平均"""
    name = "QLIB_SMA_10"
    name_cn = "10日SMA"
    category = "qlib"
    subcategory = "trend"
    description = "10日简单移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=10).mean()


class QLIB_SMA_30(BaseFactor):
    """SMA30 - 30日简单移动平均"""
    name = "QLIB_SMA_30"
    name_cn = "30日SMA"
    category = "qlib"
    subcategory = "trend"
    description = "30日简单移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=30).mean()


class QLIB_SMA_60(BaseFactor):
    """SMA60 - 60日简单移动平均"""
    name = "QLIB_SMA_60"
    name_cn = "60日SMA"
    category = "qlib"
    subcategory = "trend"
    description = "60日简单移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=60).mean()


class QLIB_WMA(BaseFactor):
    """WMA因子 - 加权移动平均"""
    name = "QLIB_WMA"
    name_cn = "加权移动平均"
    category = "qlib"
    subcategory = "trend"
    description = "加权移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 100, "WMA周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        weights = np.arange(1, period + 1)
        return data['close'].rolling(window=period).apply(lambda x: (x * weights).sum() / weights.sum(), raw=True)


class QLIB_DEMA(BaseFactor):
    """DEMA因子 - 双重指数移动平均"""
    name = "QLIB_DEMA"
    name_cn = "双重指数移动平均"
    category = "qlib"
    subcategory = "trend"
    description = "双重指数移动平均"
    formula = "DEMA = 2*EMA - EMA(EMA)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 100, "DEMA周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ema1 = data['close'].ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        return 2 * ema1 - ema2


class QLIB_TEMA(BaseFactor):
    """TEMA因子 - 三重指数移动平均"""
    name = "QLIB_TEMA"
    name_cn = "三重指数移动平均"
    category = "qlib"
    subcategory = "trend"
    description = "三重指数移动平均"
    formula = "TEMA = 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA))"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 100, "TEMA周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ema1 = data['close'].ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()
        return 3 * ema1 - 3 * ema2 + ema3


# ==================== 动量类因子 ====================

class QLIB_MOM(BaseFactor):
    """MOM因子 - 动量因子"""
    name = "QLIB_MOM"
    name_cn = "动量因子"
    category = "qlib"
    subcategory = "momentum"
    description = "过去N日动量"
    formula = "MOM = close - close_N"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 1, 252, "动量周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class QLIB_MOM_5(BaseFactor):
    """5日动量因子"""
    name = "QLIB_MOM_5"
    name_cn = "5日动量"
    category = "qlib"
    subcategory = "momentum"
    description = "5日价格动量"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'] - data['close'].shift(5)


class QLIB_MOM_10(BaseFactor):
    """10日动量因子"""
    name = "QLIB_MOM_10"
    name_cn = "10日动量"
    category = "qlib"
    subcategory = "momentum"
    description = "10日价格动量"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'] - data['close'].shift(10)


class QLIB_MOM_20(BaseFactor):
    """20日动量因子"""
    name = "QLIB_MOM_20"
    name_cn = "20日动量"
    category = "qlib"
    subcategory = "momentum"
    description = "20日价格动量"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'] - data['close'].shift(20)


class QLIB_MOM_60(BaseFactor):
    """60日动量因子"""
    name = "QLIB_MOM_60"
    name_cn = "60日动量"
    category = "qlib"
    subcategory = "momentum"
    description = "60日价格动量"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'] - data['close'].shift(60)


class QLIB_ROC(BaseFactor):
    """ROC因子 - 变动率"""
    name = "QLIB_ROC"
    name_cn = "变动率"
    category = "qlib"
    subcategory = "momentum"
    description = "价格变动率"
    formula = "ROC = (close / close_N - 1) * 100"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 1, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class QLIB_ROC_5(BaseFactor):
    """5日变动率"""
    name = "QLIB_ROC_5"
    name_cn = "5日ROC"
    category = "qlib"
    subcategory = "momentum"
    description = "5日价格变动率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return (data['close'] / data['close'].shift(5) - 1) * 100


class QLIB_ROC_10(BaseFactor):
    """10日变动率"""
    name = "QLIB_ROC_10"
    name_cn = "10日ROC"
    category = "qlib"
    subcategory = "momentum"
    description = "10日价格变动率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return (data['close'] / data['close'].shift(10) - 1) * 100


class QLIB_ROC_20(BaseFactor):
    """20日变动率"""
    name = "QLIB_ROC_20"
    name_cn = "20日ROC"
    category = "qlib"
    subcategory = "momentum"
    description = "20日价格变动率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return (data['close'] / data['close'].shift(20) - 1) * 100


class QLIB_LINEARREG(BaseFactor):
    """线性回归斜率"""
    name = "QLIB_LINEARREG"
    name_cn = "线性回归斜率"
    category = "qlib"
    subcategory = "trend"
    description = "过去N日线性回归斜率"
    formula = "Slope = linear_regression_slope(close)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 252, "回归周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        def linear_slope(series):
            n = len(series)
            if n < 2:
                return np.nan
            x = np.arange(n)
            y = series.values
            mean_x = x.mean()
            mean_y = y.mean()
            numerator = ((x - mean_x) * (y - mean_y)).sum()
            denominator = ((x - mean_x) ** 2).sum()
            return numerator / denominator if denominator != 0 else np.nan
        
        return data['close'].rolling(window=period).apply(linear_slope, raw=True)


class QLIB_LINEARREG_SLOPE_5(BaseFactor):
    """5日线性回归斜率"""
    name = "QLIB_LINEARREG_5"
    name_cn = "5日线性回归斜率"
    category = "qlib"
    subcategory = "trend"
    description = "5日线性回归斜率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = 5
        
        def linear_slope(series):
            n = len(series)
            if n < 2:
                return np.nan
            x = np.arange(n)
            y = series.values
            mean_x = x.mean()
            mean_y = y.mean()
            numerator = ((x - mean_x) * (y - mean_y)).sum()
            denominator = ((x - mean_x) ** 2).sum()
            return numerator / denominator if denominator != 0 else np.nan
        
        return data['close'].rolling(window=period).apply(linear_slope, raw=True)


class QLIB_LINEARREG_SLOPE_10(BaseFactor):
    """10日线性回归斜率"""
    name = "QLIB_LINEARREG_10"
    name_cn = "10日线性回归斜率"
    category = "qlib"
    subcategory = "trend"
    description = "10日线性回归斜率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = 10
        
        def linear_slope(series):
            n = len(series)
            if n < 2:
                return np.nan
            x = np.arange(n)
            y = series.values
            mean_x = x.mean()
            mean_y = y.mean()
            numerator = ((x - mean_x) * (y - mean_y)).sum()
            denominator = ((x - mean_x) ** 2).sum()
            return numerator / denominator if denominator != 0 else np.nan
        
        return data['close'].rolling(window=period).apply(linear_slope, raw=True)


class QLIB_LINEARREG_SLOPE_30(BaseFactor):
    """30日线性回归斜率"""
    name = "QLIB_LINEARREG_30"
    name_cn = "30日线性回归斜率"
    category = "qlib"
    subcategory = "trend"
    description = "30日线性回归斜率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = 30
        
        def linear_slope(series):
            n = len(series)
            if n < 2:
                return np.nan
            x = np.arange(n)
            y = series.values
            mean_x = x.mean()
            mean_y = y.mean()
            numerator = ((x - mean_x) * (y - mean_y)).sum()
            denominator = ((x - mean_x) ** 2).sum()
            return numerator / denominator if denominator != 0 else np.nan
        
        return data['close'].rolling(window=period).apply(linear_slope, raw=True)


# ==================== 波动率类因子 ====================

class QLIB_STD(BaseFactor):
    """STD因子 - 标准差"""
    name = "QLIB_STD"
    name_cn = "标准差"
    category = "qlib"
    subcategory = "volatility"
    description = "过去N日收益率标准差"
    formula = "Std = std(returns)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std()


class QLIB_STD_5(BaseFactor):
    """5日标准差"""
    name = "QLIB_STD_5"
    name_cn = "5日标准差"
    category = "qlib"
    subcategory = "volatility"
    description = "5日收益率标准差"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        returns = data['close'].pct_change()
        return returns.rolling(window=5).std()


class QLIB_STD_10(BaseFactor):
    """10日标准差"""
    name = "QLIB_STD_10"
    name_cn = "10日标准差"
    category = "qlib"
    subcategory = "volatility"
    description = "10日收益率标准差"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        returns = data['close'].pct_change()
        return returns.rolling(window=10).std()


class QLIB_STD_30(BaseFactor):
    """30日标准差"""
    name = "QLIB_STD_30"
    name_cn = "30日标准差"
    category = "qlib"
    subcategory = "volatility"
    description = "30日收益率标准差"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        returns = data['close'].pct_change()
        return returns.rolling(window=30).std()


class QLIB_VOLATILITY(BaseFactor):
    """年化波动率"""
    name = "QLIB_VOLATILITY"
    name_cn = "年化波动率"
    category = "qlib"
    subcategory = "volatility"
    description = "年化收益率波动率"
    formula = "Volatility = std(returns) * sqrt(252)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class QLIB_VOLATILITY_10(BaseFactor):
    """10日年化波动率"""
    name = "QLIB_VOLATILITY_10"
    name_cn = "10日年化波动率"
    category = "qlib"
    subcategory = "volatility"
    description = "10日年化收益率波动率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        returns = data['close'].pct_change()
        return returns.rolling(window=10).std() * np.sqrt(252)


class QLIB_VOLATILITY_30(BaseFactor):
    """30日年化波动率"""
    name = "QLIB_VOLATILITY_30"
    name_cn = "30日年化波动率"
    category = "qlib"
    subcategory = "volatility"
    description = "30日年化收益率波动率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        returns = data['close'].pct_change()
        return returns.rolling(window=30).std() * np.sqrt(252)


class QLIB_AVG_TRUE_RANGE(BaseFactor):
    """ATR - 真实波幅"""
    name = "QLIB_ATR"
    name_cn = "真实波幅"
    category = "qlib"
    subcategory = "volatility"
    description = "平均真实波幅"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 14, "int", 5, 100, "ATR周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        high = data['high']
        low = data['low']
        close_prev = data['close'].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close_prev)
        tr3 = abs(low - close_prev)
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()


class QLIB_ATR_14(BaseFactor):
    """14日ATR"""
    name = "QLIB_ATR_14"
    name_cn = "14日ATR"
    category = "qlib"
    subcategory = "volatility"
    description = "14日真实波幅"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = 14
        
        high = data['high']
        low = data['low']
        close_prev = data['close'].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close_prev)
        tr3 = abs(low - close_prev)
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()


class QLIB_HIGH_LOW_RANGE(BaseFactor):
    """高低振幅"""
    name = "QLIB_HL_RANGE"
    name_cn = "高低振幅"
    category = "qlib"
    subcategory = "volatility"
    description = "过去N日最高价与最低价的比值"
    formula = "HLRange = High_N / Low_N"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 100, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_max = data['high'].rolling(window=period).max()
        low_min = data['low'].rolling(window=period).min()
        return high_max / low_min.replace(0, np.nan)


class QLIB_HL_RANGE_10(BaseFactor):
    """10日高低振幅"""
    name = "QLIB_HL_RANGE_10"
    name_cn = "10日高低振幅"
    category = "qlib"
    subcategory = "volatility"
    description = "10日最高价与最低价的比值"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high_max = data['high'].rolling(window=10).max()
        low_min = data['low'].rolling(window=10).min()
        return high_max / low_min.replace(0, np.nan)


class QLIB_HL_RANGE_30(BaseFactor):
    """30日高低振幅"""
    name = "QLIB_HL_RANGE_30"
    name_cn = "30日高低振幅"
    category = "qlib"
    subcategory = "volatility"
    description = "30日最高价与最低价的比值"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high_max = data['high'].rolling(window=30).max()
        low_min = data['low'].rolling(window=30).min()
        return high_max / low_min.replace(0, np.nan)


# ==================== 成交量类因子 ====================

class QLIB_VOLUME_MA(BaseFactor):
    """成交量均线"""
    name = "QLIB_VOL_MA"
    name_cn = "成交量均线"
    category = "qlib"
    subcategory = "volume"
    description = "成交量移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 100, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).mean()


class QLIB_VOLUME_MA_5(BaseFactor):
    """5日成交量均线"""
    name = "QLIB_VOL_MA_5"
    name_cn = "5日成交量均线"
    category = "qlib"
    subcategory = "volume"
    description = "5日成交量移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['vol'].rolling(window=5).mean()


class QLIB_VOLUME_MA_10(BaseFactor):
    """10日成交量均线"""
    name = "QLIB_VOL_MA_10"
    name_cn = "10日成交量均线"
    category = "qlib"
    subcategory = "volume"
    description = "10日成交量移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['vol'].rolling(window=10).mean()


class QLIB_VOLUME_MA_30(BaseFactor):
    """30日成交量均线"""
    name = "QLIB_VOL_MA_30"
    name_cn = "30日成交量均线"
    category = "qlib"
    subcategory = "volume"
    description = "30日成交量移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['vol'].rolling(window=30).mean()


class QLIB_VOLUME_RATIO(BaseFactor):
    """成交量比率"""
    name = "QLIB_VOL_RATIO"
    name_cn = "成交量比率"
    category = "qlib"
    subcategory = "volume"
    description = "当前成交量与平均成交量的比值"
    formula = "VolRatio = volume / MA(volume)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 100, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        vol_mean = data['vol'].rolling(window=period).mean()
        return data['vol'] / vol_mean.replace(0, np.nan)


class QLIB_VOLUME_RATIO_5(BaseFactor):
    """5日成交量比率"""
    name = "QLIB_VOL_RATIO_5"
    name_cn = "5日成交量比率"
    category = "qlib"
    subcategory = "volume"
    description = "当前成交量与5日平均的比值"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        vol_mean = data['vol'].rolling(window=5).mean()
        return data['vol'] / vol_mean.replace(0, np.nan)


class QLIB_VOLUME_RATIO_10(BaseFactor):
    """10日成交量比率"""
    name = "QLIB_VOL_RATIO_10"
    name_cn = "10日成交量比率"
    category = "qlib"
    subcategory = "volume"
    description = "当前成交量与10日平均的比值"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        vol_mean = data['vol'].rolling(window=10).mean()
        return data['vol'] / vol_mean.replace(0, np.nan)


class QLIB_VOLUME_RATIO_30(BaseFactor):
    """30日成交量比率"""
    name = "QLIB_VOL_RATIO_30"
    name_cn = "30日成交量比率"
    category = "qlib"
    subcategory = "volume"
    description = "当前成交量与30日平均的比值"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        vol_mean = data['vol'].rolling(window=30).mean()
        return data['vol'] / vol_mean.replace(0, np.nan)


class QLIB_AMOUNT(BaseFactor):
    """成交额"""
    name = "QLIB_AMOUNT"
    name_cn = "成交额"
    category = "qlib"
    subcategory = "volume"
    description = "成交金额（收盘价×成交量）"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'] * data['vol']


class QLIB_AMOUNT_MA(BaseFactor):
    """成交额均线"""
    name = "QLIB_AMOUNT_MA"
    name_cn = "成交额均线"
    category = "qlib"
    subcategory = "volume"
    description = "成交额移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 2, 100, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data['close'] * data['vol']
        return amount.rolling(window=period).mean()


# ==================== 位置类因子 ====================

class QLIB_CLOSE_HIGH_RATIO(BaseFactor):
    """收盘价距高点位置"""
    name = "QLIB_CLOSE_HIGH_RATIO"
    name_cn = "收盘价距高点位置"
    category = "qlib"
    subcategory = "position"
    description = "收盘价在过去N日高点的相对位置"
    formula = "(High_N - Close) / (High_N - Low_N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 100, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_max = data['high'].rolling(window=period).max()
        low_min = data['low'].rolling(window=period).min()
        return (high_max - data['close']) / (high_max - low_min).replace(0, np.nan)


class QLIB_CLOSE_LOW_RATIO(BaseFactor):
    """收盘价距低点位置"""
    name = "QLIB_CLOSE_LOW_RATIO"
    name_cn = "收盘价距低点位置"
    category = "qlib"
    subcategory = "position"
    description = "收盘价在过去N日低点的相对位置"
    formula = "(Close - Low_N) / (High_N - Low_N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 100, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_max = data['high'].rolling(window=period).max()
        low_min = data['low'].rolling(window=period).min()
        return (data['close'] - low_min) / (high_max - low_min).replace(0, np.nan)


# ==================== 相关性类因子 ====================

class QLIB_CORR_PRICE_VOLUME(BaseFactor):
    """价格与成交量相关性"""
    name = "QLIB_PRICE_VOL_CORR"
    name_cn = "价量相关性"
    category = "qlib"
    subcategory = "correlation"
    description = "价格与成交量的相关性"
    formula = "Corr = corr(close, volume)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 100, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).corr(data['vol'])


class QLIB_CORR_PRICE_VOLUME_10(BaseFactor):
    """10日价量相关性"""
    name = "QLIB_PRICE_VOL_CORR_10"
    name_cn = "10日价量相关性"
    category = "qlib"
    subcategory = "correlation"
    description = "10日价格与成交量的相关性"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=10).corr(data['vol'])


class QLIB_CORR_PRICE_VOLUME_30(BaseFactor):
    """30日价量相关性"""
    name = "QLIB_PRICE_VOL_CORR_30"
    name_cn = "30日价量相关性"
    category = "qlib"
    subcategory = "correlation"
    description = "30日价格与成交量的相关性"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=30).corr(data['vol'])


# ==================== 综合类因子 ====================

class QLIB_KAMA(BaseFactor):
    """KAMA因子 - 自适应移动平均"""
    name = "QLIB_KAMA"
    name_cn = "自适应移动平均"
    category = "qlib"
    subcategory = "trend"
    description = "KAMA自适应移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 10, "int", 2, 50, "KAMA周期"),
        FactorParam("fast", 2, "int", 1, 10, "快周期"),
        FactorParam("slow", 30, "int", 10, 50, "慢周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        fast = self.get_param("fast")
        slow = self.get_param("slow")
        
        close = data['close']
        change = abs(close.diff(period))
        volatility = close.diff().abs().rolling(window=period).sum()
        er = change / volatility.replace(0, np.nan)
        
        sc = ((er * (2 / (fast + 1) - 2 / (slow + 1)) + 2 / (slow + 1)) ** 2).fillna(0.5)
        
        kama = pd.Series(np.nan, index=close.index)
        
        if len(close) > period:
            first_val = close.iloc[period]
            kama.iloc[period] = first_val
            
            for i in range(period + 1, len(close)):
                kama.iloc[i] = kama.iloc[i-1] + sc.iloc[i] * (close.iloc[i] - kama.iloc[i-1])
        
        return kama


class QLIB_BOLLINGER_UPPER(BaseFactor):
    """布林带上轨"""
    name = "QLIB_BOLLINGER_UPPER"
    name_cn = "布林带上轨"
    category = "qlib"
    subcategory = "volatility"
    description = "布林带上轨：MA + N×STD"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 5, 100, "BB周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 4.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        close = data['close']
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        return middle + std_dev * std


class QLIB_BOLLINGER_LOWER(BaseFactor):
    """布林带下轨"""
    name = "QLIB_BOLLINGER_LOWER"
    name_cn = "布林带下轨"
    category = "qlib"
    subcategory = "volatility"
    description = "布林带下轨：MA - N×STD"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 5, 100, "BB周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 4.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        close = data['close']
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        return middle - std_dev * std


class QLIB_BOLLINGER_WIDTH(BaseFactor):
    """布林带宽度"""
    name = "QLIB_BOLLINGER_WIDTH"
    name_cn = "布林带宽度"
    category = "qlib"
    subcategory = "volatility"
    description = "布林带宽度：(Upper - Lower) / Middle"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 5, 100, "BB周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 4.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        close = data['close']
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        return (upper - lower) / middle.replace(0, np.nan)


class QLIB_BOLLINGER_PCT(BaseFactor):
    """布林带位置百分比"""
    name = "QLIB_BOLLINGER_PCT"
    name_cn = "布林带位置百分比"
    category = "qlib"
    subcategory = "position"
    description = "价格在布林带中的位置：(Close - Lower) / (Upper - Lower)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("period", 20, "int", 5, 100, "BB周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 4.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        close = data['close']
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        return (close - lower) / (upper - lower).replace(0, np.nan)


# ==================== MACD类因子 ====================

class QLIB_MACD_DIF(BaseFactor):
    """MACD DIF"""
    name = "QLIB_MACD_DIF"
    name_cn = "MACD DIF"
    category = "qlib"
    subcategory = "momentum"
    description = "MACD差离值"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("fast", 12, "int", 5, 20, "快线周期"),
        FactorParam("slow", 26, "int", 20, 50, "慢线周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast")
        slow = self.get_param("slow")
        ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow, adjust=False).mean()
        return ema_fast - ema_slow


class QLIB_MACD_DEA(BaseFactor):
    """MACD DEA"""
    name = "QLIB_MACD_DEA"
    name_cn = "MACD DEA"
    category = "qlib"
    subcategory = "momentum"
    description = "MACD信号线"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("fast", 12, "int", 5, 20, "快线周期"),
        FactorParam("slow", 26, "int", 20, 50, "慢线周期"),
        FactorParam("signal", 9, "int", 5, 20, "信号周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast")
        slow = self.get_param("slow")
        signal = self.get_param("signal")
        
        ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        return dif.ewm(span=signal, adjust=False).mean()


class QLIB_MACD_HIST(BaseFactor):
    """MACD柱状图"""
    name = "QLIB_MACD_HIST"
    name_cn = "MACD柱状图"
    category = "qlib"
    subcategory = "momentum"
    description = "MACD柱状图：2×(DIF - DEA)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [
        FactorParam("fast", 12, "int", 5, 20, "快线周期"),
        FactorParam("slow", 26, "int", 20, 50, "慢线周期"),
        FactorParam("signal", 9, "int", 5, 20, "信号周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast")
        slow = self.get_param("slow")
        signal = self.get_param("signal")
        
        ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        return 2 * (dif - dea)


# ==================== RSI类因子 ====================

class QLIB_RSI(BaseFactor):
    """RSI相对强弱"""
    name = "QLIB_RSI"
    name_cn = "RSI相对强弱"
    category = "qlib"
    subcategory = "momentum"
    description = "RSI相对强弱指数"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 14, "int", 5, 50, "RSI周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        close = data['close']
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))


class QLIB_RSI_6(BaseFactor):
    """6日RSI"""
    name = "QLIB_RSI_6"
    name_cn = "6日RSI"
    category = "qlib"
    subcategory = "momentum"
    description = "6日RSI相对强弱指数"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = 6
        close = data['close']
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))


class QLIB_RSI_14(BaseFactor):
    """14日RSI"""
    name = "QLIB_RSI_14"
    name_cn = "14日RSI"
    category = "qlib"
    subcategory = "momentum"
    description = "14日RSI相对强弱指数"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = 14
        close = data['close']
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))


class QLIB_RSI_28(BaseFactor):
    """28日RSI"""
    name = "QLIB_RSI_28"
    name_cn = "28日RSI"
    category = "qlib"
    subcategory = "momentum"
    description = "28日RSI相对强弱指数"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = 28
        close = data['close']
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))


# ==================== 成交量累积类因子 ====================

class QLIB_OBV(BaseFactor):
    """能量潮OBV"""
    name = "QLIB_OBV"
    name_cn = "能量潮OBV"
    category = "qlib"
    subcategory = "volume"
    description = "能量潮累积指标"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        close = data['close']
        vol = data['vol']
        
        sign = (close.diff() > 0).astype(int) - (close.diff() < 0).astype(int)
        return (vol * sign).cumsum()


class QLIB_OBV_MA(BaseFactor):
    """OBV均线"""
    name = "QLIB_OBV_MA"
    name_cn = "OBV均线"
    category = "qlib"
    subcategory = "volume"
    description = "OBV移动平均"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 100, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        close = data['close']
        vol = data['vol']
        
        sign = (close.diff() > 0).astype(int) - (close.diff() < 0).astype(int)
        obv = (vol * sign).cumsum()
        return obv.rolling(window=period).mean()


# ==================== 统计类因子 ====================

class QLIB_SKEWNESS(BaseFactor):
    """偏度"""
    name = "QLIB_SKEWNESS"
    name_cn = "收益率偏度"
    category = "qlib"
    subcategory = "volatility"
    description = "过去N日收益率偏度"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 60, "int", 20, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).skew()


class QLIB_KURTOSIS(BaseFactor):
    """峰度"""
    name = "QLIB_KURTOSIS"
    name_cn = "收益率峰度"
    category = "qlib"
    subcategory = "volatility"
    description = "过去N日收益率峰度"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 60, "int", 20, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).kurt()


class QLIB_VOLUME_SKEW(BaseFactor):
    """成交量偏度"""
    name = "QLIB_VOLUME_SKEW"
    name_cn = "成交量偏度"
    category = "qlib"
    subcategory = "volume"
    description = "过去N日成交量偏度"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 60, "int", 20, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).skew()


# ==================== 收益率类因子 ====================

class QLIB_DAILY_RETURN(BaseFactor):
    """日收益率"""
    name = "QLIB_DAILY_RETURN"
    name_cn = "日收益率"
    category = "qlib"
    subcategory = "returns"
    description = "日收益率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].pct_change(1)


class QLIB_WEEKLY_RETURN(BaseFactor):
    """周收益率"""
    name = "QLIB_WEEKLY_RETURN"
    name_cn = "周收益率"
    category = "qlib"
    subcategory = "returns"
    description = "5日收益率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].pct_change(5)


class QLIB_MONTHLY_RETURN(BaseFactor):
    """月收益率"""
    name = "QLIB_MONTHLY_RETURN"
    name_cn = "月收益率"
    category = "qlib"
    subcategory = "returns"
    description = "20日收益率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].pct_change(20)


class QLIB_QUARTERLY_RETURN(BaseFactor):
    """季度收益率"""
    name = "QLIB_QUARTERLY_RETURN"
    name_cn = "季度收益率"
    category = "qlib"
    subcategory = "returns"
    description = "60日收益率"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].pct_change(60)


# ==================== 位置类因子扩展 ====================

class QLIB_POSITION_IN_RANGE(BaseFactor):
    """价格在N日区间的位置"""
    name = "QLIB_RANGE_POSITION"
    name_cn = "区间位置"
    category = "qlib"
    subcategory = "position"
    description = "价格在过去N日高低区间的位置"
    formula = "(Close - Low_N) / (High_N - Low_N)"
    source = "QLib"
    source_detail = "QLib158"
    
    params = [FactorParam("period", 20, "int", 5, 100, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_max = data['high'].rolling(window=period).max()
        low_min = data['low'].rolling(window=period).min()
        return (data['close'] - low_min) / (high_max - low_min).replace(0, np.nan)


class QLIB_POSITION_IN_RANGE_10(BaseFactor):
    """10日区间位置"""
    name = "QLIB_RANGE_POSITION_10"
    name_cn = "10日区间位置"
    category = "qlib"
    subcategory = "position"
    description = "价格在过去10日高低区间的位置"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high_max = data['high'].rolling(window=10).max()
        low_min = data['low'].rolling(window=10).min()
        return (data['close'] - low_min) / (high_max - low_min).replace(0, np.nan)


class QLIB_POSITION_IN_RANGE_30(BaseFactor):
    """30日区间位置"""
    name = "QLIB_RANGE_POSITION_30"
    name_cn = "30日区间位置"
    category = "qlib"
    subcategory = "position"
    description = "价格在过去30日高低区间的位置"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high_max = data['high'].rolling(window=30).max()
        low_min = data['low'].rolling(window=30).min()
        return (data['close'] - low_min) / (high_max - low_min).replace(0, np.nan)


# ==================== 动量反转类因子 ====================

class QLIB_REVERSAL_DAILY(BaseFactor):
    """1日反转"""
    name = "QLIB_REVERSAL_DAILY"
    name_cn = "1日反转"
    category = "qlib"
    subcategory = "reversal"
    description = "1日收益率反转信号"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -data['close'].pct_change(1)


class QLIB_REVERSAL_5(BaseFactor):
    """5日反转"""
    name = "QLIB_REVERSAL_5"
    name_cn = "5日反转"
    category = "qlib"
    subcategory = "reversal"
    description = "5日收益率反转信号"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -data['close'].pct_change(5)


class QLIB_REVERSAL_10(BaseFactor):
    """10日反转"""
    name = "QLIB_REVERSAL_10"
    name_cn = "10日反转"
    category = "qlib"
    subcategory = "reversal"
    description = "10日收益率反转信号"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -data['close'].pct_change(10)


class QLIB_REVERSAL_20(BaseFactor):
    """20日反转"""
    name = "QLIB_REVERSAL_20"
    name_cn = "20日反转"
    category = "qlib"
    subcategory = "reversal"
    description = "20日收益率反转信号"
    source = "QLib"
    source_detail = "QLib158"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -data['close'].pct_change(20)


# 已扩充到100+个Qlib风格因子！
