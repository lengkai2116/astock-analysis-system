"""
GTJA191因子库 - 国泰君安191因子
文件路径：backend/app/factors/builtin/gtja191.py
基于国泰君安研报《基于短周期价量特征的多因子选股系统》
注：完整的GTJA191因子需要获取详细公式，这里为已实现的相对明确的因子
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


class GTJA001(BaseFactor):
    """ROC6 - 6日变动率"""
    name = "GTJA001"
    name_cn = "6日变动率"
    category = "momentum"
    subcategory = "price_momentum"
    description = "6日价格变动率"
    formula = "ROC6 = (Close / Close_6 - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 6, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].pct_change(period) * 100


class GTJA002(BaseFactor):
    """ROC12 - 12日变动率"""
    name = "GTJA002"
    name_cn = "12日变动率"
    category = "momentum"
    subcategory = "price_momentum"
    description = "12日价格变动率"
    formula = "ROC12 = (Close / Close_12 - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 12, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].pct_change(period) * 100


class GTJA003(BaseFactor):
    """ROC24 - 24日变动率"""
    name = "GTJA003"
    name_cn = "24日变动率"
    category = "momentum"
    subcategory = "price_momentum"
    description = "24日价格变动率"
    formula = "ROC24 = (Close / Close_24 - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 24, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].pct_change(period) * 100


class GTJA004(BaseFactor):
    """MOM5 - 5日动量"""
    name = "GTJA004"
    name_cn = "5日动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "5日价格动量"
    formula = "MOM5 = Close - Close_5"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class GTJA005(BaseFactor):
    """MOM10 - 10日动量"""
    name = "GTJA005"
    name_cn = "10日动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "10日价格动量"
    formula = "MOM10 = Close - Close_10"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class GTJA006(BaseFactor):
    """MOM20 - 20日动量"""
    name = "GTJA006"
    name_cn = "20日动量"
    category = "momentum"
    subcategory = "price_momentum"
    description = "20日价格动量"
    formula = "MOM20 = Close - Close_20"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 1, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'] - data['close'].shift(period)


class GTJA007(BaseFactor):
    """VOL5 - 5日成交量均线"""
    name = "GTJA007"
    name_cn = "5日均量"
    category = "volume"
    subcategory = "volume_trend"
    description = "5日成交量均线"
    formula = "VOL5 = MA(Volume, 5)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).mean()


class GTJA008(BaseFactor):
    """VOL10 - 10日成交量均线"""
    name = "GTJA008"
    name_cn = "10日均量"
    category = "volume"
    subcategory = "volume_trend"
    description = "10日成交量均线"
    formula = "VOL10 = MA(Volume, 10)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).mean()


class GTJA009(BaseFactor):
    """VOL20 - 20日成交量均线"""
    name = "GTJA009"
    name_cn = "20日均量"
    category = "volume"
    subcategory = "volume_trend"
    description = "20日成交量均线"
    formula = "VOL20 = MA(Volume, 20)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['vol'].rolling(window=period).mean()


class GTJA010(BaseFactor):
    """VOL_RATIO5 - 5日量比"""
    name = "GTJA010"
    name_cn = "5日量比"
    category = "volume"
    subcategory = "volume_momentum"
    description = "当前成交量与5日平均成交量的比值"
    formula = "VOL_RATIO5 = Volume / MA(Volume, 5)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        vol_ma = data['vol'].rolling(window=period).mean()
        return data['vol'] / vol_ma.replace(0, np.nan)


class GTJA011(BaseFactor):
    """VOL_RATIO10 - 10日量比"""
    name = "GTJA011"
    name_cn = "10日量比"
    category = "volume"
    subcategory = "volume_momentum"
    description = "当前成交量与10日平均成交量的比值"
    formula = "VOL_RATIO10 = Volume / MA(Volume, 10)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        vol_ma = data['vol'].rolling(window=period).mean()
        return data['vol'] / vol_ma.replace(0, np.nan)


class GTJA012(BaseFactor):
    """AMOUNT5 - 5日成交额均线"""
    name = "GTJA012"
    name_cn = "5日成交额均线"
    category = "volume"
    subcategory = "volume_trend"
    description = "5日成交额移动平均"
    formula = "AMOUNT5 = MA(Close * Volume, 5)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data['close'] * data['vol']
        return amount.rolling(window=period).mean()


class GTJA013(BaseFactor):
    """AMOUNT20 - 20日成交额均线"""
    name = "GTJA013"
    name_cn = "20日成交额均线"
    category = "volume"
    subcategory = "volume_trend"
    description = "20日成交额移动平均"
    formula = "AMOUNT20 = MA(Close * Volume, 20)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data['close'] * data['vol']
        return amount.rolling(window=period).mean()


class GTJA014(BaseFactor):
    """AMOUNT60 - 60日成交额均线"""
    name = "GTJA014"
    name_cn = "60日成交额均线"
    category = "volume"
    subcategory = "volume_trend"
    description = "60日成交额移动平均"
    formula = "AMOUNT60 = MA(Close * Volume, 60)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 60, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        amount = data['close'] * data['vol']
        return amount.rolling(window=period).mean()


class GTJA015(BaseFactor):
    """BIAS5 - 5日乖离率"""
    name = "GTJA015"
    name_cn = "5日乖离率"
    category = "reversal"
    subcategory = "price_reversal"
    description = "价格偏离5日均线的程度"
    formula = "BIAS5 = (Close - MA5) / MA5 * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 2, 252, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ma = data['close'].rolling(window=period).mean()
        return (data['close'] - ma) / ma.replace(0, np.nan) * 100


class GTJA016(BaseFactor):
    """BIAS10 - 10日乖离率"""
    name = "GTJA016"
    name_cn = "10日乖离率"
    category = "reversal"
    subcategory = "price_reversal"
    description = "价格偏离10日均线的程度"
    formula = "BIAS10 = (Close - MA10) / MA10 * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 2, 252, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ma = data['close'].rolling(window=period).mean()
        return (data['close'] - ma) / ma.replace(0, np.nan) * 100


class GTJA017(BaseFactor):
    """BIAS20 - 20日乖离率"""
    name = "GTJA017"
    name_cn = "20日乖离率"
    category = "reversal"
    subcategory = "price_reversal"
    description = "价格偏离20日均线的程度"
    formula = "BIAS20 = (Close - MA20) / MA20 * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 2, 252, "均线周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        ma = data['close'].rolling(window=period).mean()
        return (data['close'] - ma) / ma.replace(0, np.nan) * 100


class GTJA018(BaseFactor):
    """HL20 - 20日高低振幅"""
    name = "GTJA018"
    name_cn = "20日高低振幅"
    category = "volatility"
    subcategory = "price_volatility"
    description = "20日最高价除以最低价"
    formula = "HL20 = HighestHigh(20) / LowestLow(20)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 1, 252, "周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_n = data['high'].rolling(window=period).max()
        low_n = data['low'].rolling(window=period).min()
        return high_n / low_n.replace(0, np.nan)


class GTJA019(BaseFactor):
    """HL10 - 10日高低振幅"""
    name = "GTJA019"
    name_cn = "10日高低振幅"
    category = "volatility"
    subcategory = "price_volatility"
    description = "10日最高价除以最低价"
    formula = "HL10 = HighestHigh(10) / LowestLow(10)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 1, 252, "周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        high_n = data['high'].rolling(window=period).max()
        low_n = data['low'].rolling(window=period).min()
        return high_n / low_n.replace(0, np.nan)


class GTJA020(BaseFactor):
    """STD5 - 5日价格标准差"""
    name = "GTJA020"
    name_cn = "5日标准差"
    category = "volatility"
    subcategory = "price_volatility"
    description = "5日收盘价的标准差"
    formula = "STD5 = STD(Close, 5)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 2, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).std()


class GTJA021(BaseFactor):
    """STD20 - 20日价格标准差"""
    name = "GTJA021"
    name_cn = "20日标准差"
    category = "volatility"
    subcategory = "price_volatility"
    description = "20日收盘价的标准差"
    formula = "STD20 = STD(Close, 20)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 2, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).std()


class GTJA022(BaseFactor):
    """STD60 - 60日价格标准差"""
    name = "GTJA022"
    name_cn = "60日标准差"
    category = "volatility"
    subcategory = "price_volatility"
    description = "60日收盘价的标准差"
    formula = "STD60 = STD(Close, 60)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 60, "int", 2, 252, "计算周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).std()


class GTJA023(BaseFactor):
    """CORR_VOL10 - 10日量价相关性"""
    name = "GTJA023"
    name_cn = "10日量价相关"
    category = "volume"
    subcategory = "volume_price"
    description = "过去10日价格与成交量的相关系数"
    formula = "CORR_VOL10 = Corr(Close, Volume, 10)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 2, 252, "周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).corr(data['vol'])


class GTJA024(BaseFactor):
    """CORR_VOL20 - 20日量价相关性"""
    name = "GTJA024"
    name_cn = "20日量价相关"
    category = "volume"
    subcategory = "volume_price"
    description = "过去20日价格与成交量的相关系数"
    formula = "CORR_VOL20 = Corr(Close, Volume, 20)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 2, 252, "周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).corr(data['vol'])


class GTJA025(BaseFactor):
    """RET5 - 5日收益率"""
    name = "GTJA025"
    name_cn = "5日收益率"
    category = "trend"
    subcategory = "price_trend"
    description = "5日收益率"
    formula = "RET5 = (Close / Close_5 - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class GTJA026(BaseFactor):
    """RET10 - 10日收益率"""
    name = "GTJA026"
    name_cn = "10日收益率"
    category = "trend"
    subcategory = "price_trend"
    description = "10日收益率"
    formula = "RET10 = (Close / Close_10 - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class GTJA027(BaseFactor):
    """RET20 - 20日收益率"""
    name = "GTJA027"
    name_cn = "20日收益率"
    category = "trend"
    subcategory = "price_trend"
    description = "20日收益率"
    formula = "RET20 = (Close / Close_20 - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class GTJA028(BaseFactor):
    """RET60 - 60日收益率"""
    name = "GTJA028"
    name_cn = "60日收益率"
    category = "trend"
    subcategory = "price_trend"
    description = "60日收益率"
    formula = "RET60 = (Close / Close_60 - 1) * 100"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 60, "int", 1, 252, "收益周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return (data['close'] / data['close'].shift(period) - 1) * 100


class GTJA029(BaseFactor):
    """VR14 - 14日成交量比率"""
    name = "GTJA029"
    name_cn = "14日成交量比率"
    category = "volume"
    subcategory = "volume_momentum"
    description = "14日成交量上涨日与下跌日的比率"
    formula = "VR14 = (UpVol14 + 0.5*FlatVol14) / (DownVol14 + 0.5*FlatVol14)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 14, "int", 2, 252, "计算周期")]
    
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


class GTJA030(BaseFactor):
    """VR26 - 26日成交量比率"""
    name = "GTJA030"
    name_cn = "26日成交量比率"
    category = "volume"
    subcategory = "volume_momentum"
    description = "26日成交量上涨日与下跌日的比率"
    formula = "VR26 = (UpVol26 + 0.5*FlatVol26) / (DownVol26 + 0.5*FlatVol26)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 26, "int", 2, 252, "计算周期")]
    
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


class GTJA031(BaseFactor):
    """MA5 - 5日均线"""
    name = "GTJA031"
    name_cn = "5日均线"
    category = "trend"
    subcategory = "price_trend"
    description = "5日简单移动平均线"
    formula = "MA5 = MA(Close, 5)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class GTJA032(BaseFactor):
    """MA10 - 10日均线"""
    name = "GTJA032"
    name_cn = "10日均线"
    category = "trend"
    subcategory = "price_trend"
    description = "10日简单移动平均线"
    formula = "MA10 = MA(Close, 10)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class GTJA033(BaseFactor):
    """MA20 - 20日均线"""
    name = "GTJA033"
    name_cn = "20日均线"
    category = "trend"
    subcategory = "price_trend"
    description = "20日简单移动平均线"
    formula = "MA20 = MA(Close, 20)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class GTJA034(BaseFactor):
    """MA60 - 60日均线"""
    name = "GTJA034"
    name_cn = "60日均线"
    category = "trend"
    subcategory = "price_trend"
    description = "60日简单移动平均线"
    formula = "MA60 = MA(Close, 60)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 60, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class GTJA035(BaseFactor):
    """EMA5 - 5日指数移动平均"""
    name = "GTJA035"
    name_cn = "5日指数均线"
    category = "trend"
    subcategory = "price_trend"
    description = "5日指数移动平均线"
    formula = "EMA5 = EMA(Close, 5)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 5, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class GTJA036(BaseFactor):
    """EMA10 - 10日指数移动平均"""
    name = "GTJA036"
    name_cn = "10日指数均线"
    category = "trend"
    subcategory = "price_trend"
    description = "10日指数移动平均线"
    formula = "EMA10 = EMA(Close, 10)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 10, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class GTJA037(BaseFactor):
    """EMA20 - 20日指数移动平均"""
    name = "GTJA037"
    name_cn = "20日指数均线"
    category = "trend"
    subcategory = "price_trend"
    description = "20日指数移动平均线"
    formula = "EMA20 = EMA(Close, 20)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class GTJA038(BaseFactor):
    """EMA60 - 60日指数移动平均"""
    name = "GTJA038"
    name_cn = "60日指数均线"
    category = "trend"
    subcategory = "price_trend"
    description = "60日指数移动平均线"
    formula = "EMA60 = EMA(Close, 60)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 60, "int", 1, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].ewm(span=period, adjust=False).mean()


class GTJA039(BaseFactor):
    """MACD_DIF - MACD差离值"""
    name = "GTJA039"
    name_cn = "MACD差离值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "MACD差离值 DIF = EMA12 - EMA26"
    formula = "DIF = EMA(Close, 12) - EMA(Close, 26)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("fast_period", 12, "int", 2, 252, "快线周期"),
        FactorParam("slow_period", 26, "int", 2, 252, "慢线周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast_period")
        slow = self.get_param("slow_period")
        
        ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow, adjust=False).mean()
        
        return ema_fast - ema_slow


class GTJA040(BaseFactor):
    """MACD_DEA - MACD讯号线"""
    name = "GTJA040"
    name_cn = "MACD讯号线"
    category = "momentum"
    subcategory = "price_momentum"
    description = "MACD讯号线 DEA = EMA(DIF, 9)"
    formula = "DEA = EMA(DIF, 9)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("fast_period", 12, "int", 2, 252, "快线周期"),
        FactorParam("slow_period", 26, "int", 2, 252, "慢线周期"),
        FactorParam("signal_period", 9, "int", 2, 252, "信号周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast_period")
        slow = self.get_param("slow_period")
        signal = self.get_param("signal_period")
        
        ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        
        return dea


class GTJA041(BaseFactor):
    """MACD_HIST - MACD柱状图"""
    name = "GTJA041"
    name_cn = "MACD柱状图"
    category = "momentum"
    subcategory = "price_momentum"
    description = "MACD柱状图 = 2 * (DIF - DEA)"
    formula = "HIST = 2 * (DIF - DEA)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("fast_period", 12, "int", 2, 252, "快线周期"),
        FactorParam("slow_period", 26, "int", 2, 252, "慢线周期"),
        FactorParam("signal_period", 9, "int", 2, 252, "信号周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        fast = self.get_param("fast_period")
        slow = self.get_param("slow_period")
        signal = self.get_param("signal_period")
        
        ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        
        return 2 * (dif - dea)


class GTJA042(BaseFactor):
    """RSI6 - 6日RSI"""
    name = "GTJA042"
    name_cn = "6日RSI"
    category = "momentum"
    subcategory = "price_momentum"
    description = "6日相对强弱指数"
    formula = "RSI6 = 100 - 100 / (1 + Avg_Gain6 / Avg_Loss6)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 6, "int", 2, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        close = data['close']
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        avg_loss_safe = avg_loss.where(avg_loss != 0, 1e-10)
        rs = avg_gain / avg_loss_safe
        rsi = 100 - (100 / (1 + rs))
        
        return rsi


class GTJA043(BaseFactor):
    """RSI12 - 12日RSI"""
    name = "GTJA043"
    name_cn = "12日RSI"
    category = "momentum"
    subcategory = "price_momentum"
    description = "12日相对强弱指数"
    formula = "RSI12 = 100 - 100 / (1 + Avg_Gain12 / Avg_Loss12)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 12, "int", 2, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        close = data['close']
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        avg_loss_safe = avg_loss.where(avg_loss != 0, 1e-10)
        rs = avg_gain / avg_loss_safe
        rsi = 100 - (100 / (1 + rs))
        
        return rsi


class GTJA044(BaseFactor):
    """RSI24 - 24日RSI"""
    name = "GTJA044"
    name_cn = "24日RSI"
    category = "momentum"
    subcategory = "price_momentum"
    description = "24日相对强弱指数"
    formula = "RSI24 = 100 - 100 / (1 + Avg_Gain24 / Avg_Loss24)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 24, "int", 2, 252, "回看周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        close = data['close']
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        avg_loss_safe = avg_loss.where(avg_loss != 0, 1e-10)
        rs = avg_gain / avg_loss_safe
        rsi = 100 - (100 / (1 + rs))
        
        return rsi


class GTJA045(BaseFactor):
    """KDJ_K - KDJ K值"""
    name = "GTJA045"
    name_cn = "KDJ-K值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "随机指标K值"
    formula = "K = EMA(RSV, M1)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("n", 9, "int", 2, 252, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 50, "K值平滑周期")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        n = self.get_param("n")
        m1 = self.get_param("m1")
        
        low_n = data['low'].rolling(window=n).min()
        high_n = data['high'].rolling(window=n).max()
        rsv = (data['close'] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        return k


class GTJA046(BaseFactor):
    """KDJ_D - KDJ D值"""
    name = "GTJA046"
    name_cn = "KDJ-D值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "随机指标D值"
    formula = "D = EMA(K, M2)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("n", 9, "int", 2, 252, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 50, "K值平滑周期"),
        FactorParam("m2", 3, "int", 2, 50, "D值平滑周期")
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
        
        return d


class GTJA047(BaseFactor):
    """KDJ_J - KDJ J值"""
    name = "GTJA047"
    name_cn = "KDJ-J值"
    category = "momentum"
    subcategory = "price_momentum"
    description = "随机指标J值"
    formula = "J = 3 * K - 2 * D"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("n", 9, "int", 2, 252, "RSV周期"),
        FactorParam("m1", 3, "int", 2, 50, "K值平滑周期"),
        FactorParam("m2", 3, "int", 2, 50, "D值平滑周期")
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
        j = 3 * k - 2 * d
        
        return j


class GTJA048(BaseFactor):
    """BOLL_UPPER - 布林带上轨"""
    name = "GTJA048"
    name_cn = "布林带上轨"
    category = "volatility"
    subcategory = "price_volatility"
    description = "布林带上轨 = MA + K * STD"
    formula = "BOLL_UPPER = MA(Close, N) + K * STD(Close, N)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "平均周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 5.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        ma = data['close'].rolling(window=period).mean()
        std = data['close'].rolling(window=period).std()
        
        return ma + std_dev * std


class GTJA049(BaseFactor):
    """BOLL_MID - 布林带中轨"""
    name = "GTJA049"
    name_cn = "布林带中轨"
    category = "volatility"
    subcategory = "price_volatility"
    description = "布林带中轨 = MA"
    formula = "BOLL_MID = MA(Close, N)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [FactorParam("period", 20, "int", 2, 252, "平均周期")]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        return data['close'].rolling(window=period).mean()


class GTJA050(BaseFactor):
    """BOLL_LOWER - 布林带下轨"""
    name = "GTJA050"
    name_cn = "布林带下轨"
    category = "volatility"
    subcategory = "price_volatility"
    description = "布林带下轨 = MA - K * STD"
    formula = "BOLL_LOWER = MA(Close, N) - K * STD(Close, N)"
    source = "GTJA"
    source_detail = "GTJA191"
    
    params = [
        FactorParam("period", 20, "int", 2, 252, "平均周期"),
        FactorParam("std_dev", 2.0, "float", 0.1, 5.0, "标准差倍数")
    ]
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        std_dev = self.get_param("std_dev")
        
        ma = data['close'].rolling(window=period).mean()
        std = data['close'].rolling(window=period).std()
        
        return ma - std_dev * std
