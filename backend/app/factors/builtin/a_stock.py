"""
A股市场核心因子库
基于华泰、国泰君安等券商研报及学术研究
文件路径：backend/app/factors/builtin/a_stock.py
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


# =============================================
# 动量因子 (Momentum)
# =============================================

class MOM_5(BaseFactor):
    """5日动量"""
    name = "MOM_5"
    name_cn = "5日动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "5日价格动量"
    formula = "MOM = Close - Close_5"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class MOM_10(BaseFactor):
    """10日动量"""
    name = "MOM_10"
    name_cn = "10日动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "10日价格动量"
    formula = "MOM = Close - Close_10"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class MOM_20(BaseFactor):
    """20日动量"""
    name = "MOM_20"
    name_cn = "20日动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "20日价格动量"
    formula = "MOM = Close - Close_20"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class MOM_60(BaseFactor):
    """60日动量"""
    name = "MOM_60"
    name_cn = "60日动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "60日价格动量"
    formula = "MOM = Close - Close_60"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 60, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class ROC_6(BaseFactor):
    """6日变动率"""
    name = "ROC_6"
    name_cn = "6日变动率"
    category = "momentum"
    subcategory = "price_momentum"
    description = "6日价格变动率"
    formula = "ROC = (Close / Close_6 - 1) * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 6, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class ROC_12(BaseFactor):
    """12日变动率"""
    name = "ROC_12"
    name_cn = "12日变动率"
    category = "momentum"
    subcategory = "price_momentum"
    description = "12日价格变动率"
    formula = "ROC = (Close / Close_12 - 1) * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 12, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class ROC_24(BaseFactor):
    """24日变动率"""
    name = "ROC_24"
    name_cn = "24日变动率"
    category = "momentum"
    subcategory = "price_momentum"
    description = "24日价格变动率"
    formula = "ROC = (Close / Close_24 - 1) * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 24, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class RET_5(BaseFactor):
    """5日收益率"""
    name = "RET_5"
    name_cn = "5日收益率"
    category = "momentum"
    subcategory = "return_momentum"
    description = "5日收益率"
    formula = "RET = (Close / Close_5 - 1) * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class RET_10(BaseFactor):
    """10日收益率"""
    name = "RET_10"
    name_cn = "10日收益率"
    category = "momentum"
    subcategory = "return_momentum"
    description = "10日收益率"
    formula = "RET = (Close / Close_10 - 1) * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class RET_20(BaseFactor):
    """20日收益率"""
    name = "RET_20"
    name_cn = "20日收益率"
    category = "momentum"
    subcategory = "return_momentum"
    description = "20日收益率"
    formula = "RET = (Close / Close_20 - 1) * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class RET_60(BaseFactor):
    """60日收益率"""
    name = "RET_60"
    name_cn = "60日收益率"
    category = "momentum"
    subcategory = "return_momentum"
    description = "60日收益率"
    formula = "RET = (Close / Close_60 - 1) * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 60, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class RSI_6(BaseFactor):
    """6日RSI"""
    name = "RSI_6"
    name_cn = "6日RSI"
    category = "momentum"
    subcategory = "momentum_oscillator"
    description = "6日相对强弱指数"
    formula = "RSI = 100 - 100/(1 + avg_gain/avg_loss)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 6, "int", 2, 50, "RSI周期")]
    
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


class RSI_14(BaseFactor):
    """14日RSI"""
    name = "RSI_14"
    name_cn = "14日RSI"
    category = "momentum"
    subcategory = "momentum_oscillator"
    description = "14日相对强弱指数"
    formula = "RSI = 100 - 100/(1 + avg_gain/avg_loss)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 14, "int", 2, 50, "RSI周期")]
    
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


class RSI_24(BaseFactor):
    """24日RSI"""
    name = "RSI_24"
    name_cn = "24日RSI"
    category = "momentum"
    subcategory = "momentum_oscillator"
    description = "24日相对强弱指数"
    formula = "RSI = 100 - 100/(1 + avg_gain/avg_loss)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 24, "int", 2, 50, "RSI周期")]
    
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


class MACD_DIF(BaseFactor):
    """MACD差离值"""
    name = "MACD_DIF"
    name_cn = "MACD差离值"
    category = "momentum"
    subcategory = "trend_momentum"
    description = "MACD差离值"
    formula = "DIF = EMA12 - EMA26"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
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


class MACD_DEA(BaseFactor):
    """MACD讯号线"""
    name = "MACD_DEA"
    name_cn = "MACD讯号线"
    category = "momentum"
    subcategory = "trend_momentum"
    description = "MACD讯号线"
    formula = "DEA = EMA(DIF, 9)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
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


class MACD_HIST(BaseFactor):
    """MACD柱状图"""
    name = "MACD_HIST"
    name_cn = "MACD柱状图"
    category = "momentum"
    subcategory = "trend_momentum"
    description = "MACD柱状图"
    formula = "HIST = 2 * (DIF - DEA)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
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


# =============================================
# 反转因子 (Reversal)
# =============================================

class REV_1(BaseFactor):
    """1日反转"""
    name = "REV_1"
    name_cn = "1日反转"
    category = "reversal"
    subcategory = "short_term"
    description = "1日收益率反转"
    formula = "REV = -1 * returns"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -1 * data['close'].pct_change(1)


class REV_5(BaseFactor):
    """5日反转"""
    name = "REV_5"
    name_cn = "5日反转"
    category = "reversal"
    subcategory = "short_term"
    description = "5日收益率反转"
    formula = "REV = -1 * (Close / Close_5 - 1)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 1, 20, "反转周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return -1 * (data['close'] / data['close'].shift(period) - 1)


class REV_10(BaseFactor):
    """10日反转"""
    name = "REV_10"
    name_cn = "10日反转"
    category = "reversal"
    subcategory = "short_term"
    description = "10日收益率反转"
    formula = "REV = -1 * (Close / Close_10 - 1)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 1, 30, "反转周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return -1 * (data['close'] / data['close'].shift(period) - 1)


class BIAS_5(BaseFactor):
    """5日乖离率"""
    name = "BIAS_5"
    name_cn = "5日乖离率"
    category = "reversal"
    subcategory = "price_deviation"
    description = "价格偏离5日均线"
    formula = "BIAS = (Close - MA5) / MA5 * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 2, 50, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ma = data['close'].rolling(window=period).mean()
        return (data['close'] - ma) / ma.replace(0, np.nan) * 100


class BIAS_10(BaseFactor):
    """10日乖离率"""
    name = "BIAS_10"
    name_cn = "10日乖离率"
    category = "reversal"
    subcategory = "price_deviation"
    description = "价格偏离10日均线"
    formula = "BIAS = (Close - MA10) / MA10 * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 2, 50, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ma = data['close'].rolling(window=period).mean()
        return (data['close'] - ma) / ma.replace(0, np.nan) * 100


class BIAS_20(BaseFactor):
    """20日乖离率"""
    name = "BIAS_20"
    name_cn = "20日乖离率"
    category = "reversal"
    subcategory = "price_deviation"
    description = "价格偏离20日均线"
    formula = "BIAS = (Close - MA20) / MA20 * 100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 2, 100, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ma = data['close'].rolling(window=period).mean()
        return (data['close'] - ma) / ma.replace(0, np.nan) * 100


class WILLR_14(BaseFactor):
    """14日威廉指标"""
    name = "WILLR_14"
    name_cn = "14日威廉指标"
    category = "reversal"
    subcategory = "overbought_oversold"
    description = "14日威廉指标"
    formula = "WILLR = (High14 - Close) / (High14 - Low14) * -100"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 14, "int", 5, 30, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_n = data['high'].rolling(window=period).max()
        low_n = data['low'].rolling(window=period).min()
        return (high_n - data['close']) / (high_n - low_n).replace(0, np.nan) * -100


class KDJ_K(BaseFactor):
    """KDJ-K值"""
    name = "KDJ_K"
    name_cn = "KDJ-K值"
    category = "reversal"
    subcategory = "overbought_oversold"
    description = "随机指标K值"
    formula = "K = EMA(RSV, 3)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [
        FactorParam("n", 9, "int", 2, 30, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 10, "K值平滑周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        n = self.get_param("n")
        m1 = self.get_param("m1")
        
        low_n = data['low'].rolling(window=n).min()
        high_n = data['high'].rolling(window=n).max()
        rsv = (data['close'] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        
        return rsv.ewm(com=m1-1, adjust=False).mean()


class KDJ_D(BaseFactor):
    """KDJ-D值"""
    name = "KDJ_D"
    name_cn = "KDJ-D值"
    category = "reversal"
    subcategory = "overbought_oversold"
    description = "随机指标D值"
    formula = "D = EMA(K, 3)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [
        FactorParam("n", 9, "int", 2, 30, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 10, "K值平滑周期"),
        FactorParam("m2", 3, "int", 2, 10, "D值平滑周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        n = self.get_param("n")
        m1 = self.get_param("m1")
        m2 = self.get_param("m2")
        
        low_n = data['low'].rolling(window=n).min()
        high_n = data['high'].rolling(window=n).max()
        rsv = (data['close'] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        return k.ewm(com=m2-1, adjust=False).mean()


class KDJ_J(BaseFactor):
    """KDJ-J值"""
    name = "KDJ_J"
    name_cn = "KDJ-J值"
    category = "reversal"
    subcategory = "overbought_oversold"
    description = "随机指标J值"
    formula = "J = 3 * K - 2 * D"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [
        FactorParam("n", 9, "int", 2, 30, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 10, "K值平滑周期"),
        FactorParam("m2", 3, "int", 2, 10, "D值平滑周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        n = self.get_param("n")
        m1 = self.get_param("m1")
        m2 = self.get_param("m2")
        
        low_n = data['low'].rolling(window=n).min()
        high_n = data['high'].rolling(window=n).max()
        rsv = (data['close'] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        return 3 * k - 2 * d


# =============================================
# 波动率因子 (Volatility)
# =============================================

class VOLATILITY_10(BaseFactor):
    """10日波动率"""
    name = "VOLATILITY_10"
    name_cn = "10日波动率"
    category = "volatility"
    subcategory = "price_volatility"
    description = "10日收益率标准差"
    formula = "VOL = std(returns) * sqrt(252)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 5, 60, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class VOLATILITY_20(BaseFactor):
    """20日波动率"""
    name = "VOLATILITY_20"
    name_cn = "20日波动率"
    category = "volatility"
    subcategory = "price_volatility"
    description = "20日收益率标准差"
    formula = "VOL = std(returns) * sqrt(252)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 120, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class VOLATILITY_60(BaseFactor):
    """60日波动率"""
    name = "VOLATILITY_60"
    name_cn = "60日波动率"
    category = "volatility"
    subcategory = "price_volatility"
    description = "60日收益率标准差"
    formula = "VOL = std(returns) * sqrt(252)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 60, "int", 30, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        returns = data['close'].pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)


class ATR_14(BaseFactor):
    """14日ATR"""
    name = "ATR_14"
    name_cn = "14日ATR"
    category = "volatility"
    subcategory = "price_range"
    description = "14日真实波幅"
    formula = "ATR = MA(TR, 14)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 14, "int", 5, 30, "ATR周期")]
    
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


class ATR_20(BaseFactor):
    """20日ATR"""
    name = "ATR_20"
    name_cn = "20日ATR"
    category = "volatility"
    subcategory = "price_range"
    description = "20日真实波幅"
    formula = "ATR = MA(TR, 20)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 50, "ATR周期")]
    
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


class STD_5(BaseFactor):
    """5日标准差"""
    name = "STD_5"
    name_cn = "5日标准差"
    category = "volatility"
    subcategory = "price_std"
    description = "5日收盘价标准差"
    formula = "STD = std(close, 5)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 2, 30, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).std()


class STD_20(BaseFactor):
    """20日标准差"""
    name = "STD_20"
    name_cn = "20日标准差"
    category = "volatility"
    subcategory = "price_std"
    description = "20日收盘价标准差"
    formula = "STD = std(close, 20)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 60, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).std()


class HL_10(BaseFactor):
    """10日高低振幅"""
    name = "HL_10"
    name_cn = "10日高低振幅"
    category = "volatility"
    subcategory = "price_range"
    description = "10日最高价与最低价之比"
    formula = "HL = High10 / Low10"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 5, 30, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_n = data['high'].rolling(window=period).max()
        low_n = data['low'].rolling(window=period).min()
        return high_n / low_n.replace(0, np.nan)


class HL_20(BaseFactor):
    """20日高低振幅"""
    name = "HL_20"
    name_cn = "20日高低振幅"
    category = "volatility"
    subcategory = "price_range"
    description = "20日最高价与最低价之比"
    formula = "HL = High20 / Low20"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 60, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_n = data['high'].rolling(window=period).max()
        low_n = data['low'].rolling(window=period).min()
        return high_n / low_n.replace(0, np.nan)


# =============================================
# 成交量因子 (Volume)
# =============================================

class VOL_MA5(BaseFactor):
    """5日均量"""
    name = "VOL_MA5"
    name_cn = "5日均量"
    category = "volume"
    subcategory = "volume_trend"
    description = "5日成交量均线"
    formula = "VOL_MA = MA(Volume, 5)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 2, 30, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).mean()


class VOL_MA10(BaseFactor):
    """10日均量"""
    name = "VOL_MA10"
    name_cn = "10日均量"
    category = "volume"
    subcategory = "volume_trend"
    description = "10日成交量均线"
    formula = "VOL_MA = MA(Volume, 10)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 5, 50, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).mean()


class VOL_MA20(BaseFactor):
    """20日均量"""
    name = "VOL_MA20"
    name_cn = "20日均量"
    category = "volume"
    subcategory = "volume_trend"
    description = "20日成交量均线"
    formula = "VOL_MA = MA(Volume, 20)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 100, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).mean()


class VOL_RATIO_5(BaseFactor):
    """5日量比"""
    name = "VOL_RATIO_5"
    name_cn = "5日量比"
    category = "volume"
    subcategory = "volume_momentum"
    description = "当前成交量与5日平均成交量的比值"
    formula = "VOL_RATIO = Volume / MA(Volume, 5)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 2, 30, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        vol_ma = data['vol'].rolling(window=period).mean()
        return data['vol'] / vol_ma.replace(0, np.nan)


class VOL_RATIO_10(BaseFactor):
    """10日量比"""
    name = "VOL_RATIO_10"
    name_cn = "10日量比"
    category = "volume"
    subcategory = "volume_momentum"
    description = "当前成交量与10日平均成交量的比值"
    formula = "VOL_RATIO = Volume / MA(Volume, 10)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 5, 50, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        vol_ma = data['vol'].rolling(window=period).mean()
        return data['vol'] / vol_ma.replace(0, np.nan)


class VR_14(BaseFactor):
    """14日成交量比率"""
    name = "VR_14"
    name_cn = "14日成交量比率"
    category = "volume"
    subcategory = "volume_momentum"
    description = "14日成交量上涨日与下跌日的比率"
    formula = "VR = (UpVol + 0.5*FlatVol) / (DownVol + 0.5*FlatVol)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 14, "int", 5, 30, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        close = data['close']
        vol = data['vol']
        
        up_vol = vol.where(close > close.shift(1), 0)
        down_vol = vol.where(close < close.shift(1), 0)
        flat_vol = vol.where(close == close.shift(1), 0)
        
        up_sum = up_vol.rolling(window=period).sum()
        down_sum = down_vol.rolling(window=period).sum()
        flat_sum = flat_vol.rolling(window=period).sum()
        
        return (up_sum + 0.5 * flat_sum) / (down_sum + 0.5 * flat_sum).replace(0, np.nan)


class VR_26(BaseFactor):
    """26日成交量比率"""
    name = "VR_26"
    name_cn = "26日成交量比率"
    category = "volume"
    subcategory = "volume_momentum"
    description = "26日成交量上涨日与下跌日的比率"
    formula = "VR = (UpVol + 0.5*FlatVol) / (DownVol + 0.5*FlatVol)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 26, "int", 10, 60, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        
        close = data['close']
        vol = data['vol']
        
        up_vol = vol.where(close > close.shift(1), 0)
        down_vol = vol.where(close < close.shift(1), 0)
        flat_vol = vol.where(close == close.shift(1), 0)
        
        up_sum = up_vol.rolling(window=period).sum()
        down_sum = down_vol.rolling(window=period).sum()
        flat_sum = flat_vol.rolling(window=period).sum()
        
        return (up_sum + 0.5 * flat_sum) / (down_sum + 0.5 * flat_sum).replace(0, np.nan)


class OBV(BaseFactor):
    """能量潮"""
    name = "OBV"
    name_cn = "能量潮"
    category = "volume"
    subcategory = "volume_accumulation"
    description = "能量潮指标"
    formula = "OBV = cumulative(volume * sign(price_change))"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        close = data['close']
        vol = data['vol']
        
        sign = (close.diff() > 0).astype(int) - (close.diff() < 0).astype(int)
        return (vol * sign).cumsum()


class AMOUNT_5(BaseFactor):
    """5日成交额"""
    name = "AMOUNT_5"
    name_cn = "5日成交额"
    category = "volume"
    subcategory = "amount_trend"
    description = "5日成交额均线"
    formula = "AMOUNT = MA(Close * Volume, 5)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 2, 30, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data['close'] * data['vol']
        return amount.rolling(window=period).mean()


class AMOUNT_20(BaseFactor):
    """20日成交额"""
    name = "AMOUNT_20"
    name_cn = "20日成交额"
    category = "volume"
    subcategory = "amount_trend"
    description = "20日成交额均线"
    formula = "AMOUNT = MA(Close * Volume, 20)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 60, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data['close'] * data['vol']
        return amount.rolling(window=period).mean()


class AMOUNT_60(BaseFactor):
    """60日成交额"""
    name = "AMOUNT_60"
    name_cn = "60日成交额"
    category = "volume"
    subcategory = "amount_trend"
    description = "60日成交额均线"
    formula = "AMOUNT = MA(Close * Volume, 60)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 60, "int", 30, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data['close'] * data['vol']
        return amount.rolling(window=period).mean()


# =============================================
# 趋势因子 (Trend)
# =============================================

class MA_5(BaseFactor):
    """5日均线"""
    name = "MA_5"
    name_cn = "5日均线"
    category = "trend"
    subcategory = "moving_average"
    description = "5日简单移动平均线"
    formula = "MA = MA(Close, 5)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 2, 30, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class MA_10(BaseFactor):
    """10日均线"""
    name = "MA_10"
    name_cn = "10日均线"
    category = "trend"
    subcategory = "moving_average"
    description = "10日简单移动平均线"
    formula = "MA = MA(Close, 10)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 5, 50, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class MA_20(BaseFactor):
    """20日均线"""
    name = "MA_20"
    name_cn = "20日均线"
    category = "trend"
    subcategory = "moving_average"
    description = "20日简单移动平均线"
    formula = "MA = MA(Close, 20)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 100, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class MA_60(BaseFactor):
    """60日均线"""
    name = "MA_60"
    name_cn = "60日均线"
    category = "trend"
    subcategory = "moving_average"
    description = "60日简单移动平均线"
    formula = "MA = MA(Close, 60)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 60, "int", 30, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class EMA_5(BaseFactor):
    """5日指数均线"""
    name = "EMA_5"
    name_cn = "5日指数均线"
    category = "trend"
    subcategory = "moving_average"
    description = "5日指数移动平均线"
    formula = "EMA = EMA(Close, 5)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 5, "int", 2, 30, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class EMA_10(BaseFactor):
    """10日指数均线"""
    name = "EMA_10"
    name_cn = "10日指数均线"
    category = "trend"
    subcategory = "moving_average"
    description = "10日指数移动平均线"
    formula = "EMA = EMA(Close, 10)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 10, "int", 5, 50, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class EMA_20(BaseFactor):
    """20日指数均线"""
    name = "EMA_20"
    name_cn = "20日指数均线"
    category = "trend"
    subcategory = "moving_average"
    description = "20日指数移动平均线"
    formula = "EMA = EMA(Close, 20)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 10, 100, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class BOLL_UPPER(BaseFactor):
    """布林带上轨"""
    name = "BOLL_UPPER"
    name_cn = "布林带上轨"
    category = "trend"
    subcategory = "bollinger_bands"
    description = "布林带上轨"
    formula = "BOLL_UPPER = MA + 2 * STD"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [
        FactorParam("period", 20, "int", 5, 50, "BB周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 4.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        ma = data['close'].rolling(window=period).mean()
        std = data['close'].rolling(window=period).std()
        
        return ma + std_dev * std


class BOLL_MID(BaseFactor):
    """布林带中轨"""
    name = "BOLL_MID"
    name_cn = "布林带中轨"
    category = "trend"
    subcategory = "bollinger_bands"
    description = "布林带中轨"
    formula = "BOLL_MID = MA"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 5, 50, "BB周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class BOLL_LOWER(BaseFactor):
    """布林带下轨"""
    name = "BOLL_LOWER"
    name_cn = "布林带下轨"
    category = "trend"
    subcategory = "bollinger_bands"
    description = "布林带下轨"
    formula = "BOLL_LOWER = MA - 2 * STD"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [
        FactorParam("period", 20, "int", 5, 50, "BB周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 4.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        ma = data['close'].rolling(window=period).mean()
        std = data['close'].rolling(window=period).std()
        
        return ma - std_dev * std


# =============================================
# 位置因子 (Position)
# =============================================

class CLOSE_HIGH_RATIO(BaseFactor):
    """收盘价距高点比例"""
    name = "CLOSE_HIGH_RATIO"
    name_cn = "收盘价距高点比例"
    category = "position"
    subcategory = "price_level"
    description = "收盘价在周期内的相对位置"
    formula = "(high_max - close) / (high_max - low_min)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 5, 60, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_max = data['high'].rolling(window=period).max()
        low_min = data['low'].rolling(window=period).min()
        return (high_max - data['close']) / (high_max - low_min).replace(0, np.nan)


class CLOSE_LOW_RATIO(BaseFactor):
    """收盘价距低点比例"""
    name = "CLOSE_LOW_RATIO"
    name_cn = "收盘价距低点比例"
    category = "position"
    subcategory = "price_level"
    description = "收盘价在周期内的相对位置"
    formula = "(close - low_min) / (high_max - low_min)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [FactorParam("period", 20, "int", 5, 60, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_max = data['high'].rolling(window=period).max()
        low_min = data['low'].rolling(window=period).min()
        return (data['close'] - low_min) / (high_max - low_min).replace(0, np.nan)


class BOLL_PCT(BaseFactor):
    """布林带位置百分比"""
    name = "BOLL_PCT"
    name_cn = "布林带位置百分比"
    category = "position"
    subcategory = "bollinger_position"
    description = "价格在布林带中的位置"
    formula = "(close - lower) / (upper - lower)"
    source = "A-Stock"
    source_detail = "A股常用因子"
    
    params = [
        FactorParam("period", 20, "int", 5, 50, "BB周期"),
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
