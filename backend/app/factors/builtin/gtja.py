"""
GTJA191 - 国泰君安191因子框架
注：完整的GTJA191因子需要获取详细公式，这里为框架
"""
import numpy as np
import pandas as pd

from ..base import BaseFactor, FactorParam


class GTJA_Base(BaseFactor):
    """
    GTJA因子基类（抽象基类，不注册到注册表）
    """
    name = ""
    name_cn = ""
    category = ""
    subcategory = ""
    description = ""
    formula = ""
    source = "GTJA"
    source_detail = "GTJA191"

    # 标记为抽象基类，注册表自动加载时跳过
    _is_abstract = True

    params = []

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series([], index=data.index)


# 以下为GTJA191因子占位符，需要补充实现
class GTJA_FACTOR_001(GTJA_Base):
    name = "GTJA_PLACEHOLDER_001"
    name_cn = "GTJA001因子"
    category = "trend"
    subcategory = "price_trend"
    description = "GTJA191因子001"
    formula = ""


class GTJA_FACTOR_002(GTJA_Base):
    name = "GTJA_PLACEHOLDER_002"
    name_cn = "GTJA002因子"
    category = "momentum"
    subcategory = "price_momentum"
    description = "GTJA191因子002"
    formula = ""


class GTJA_FACTOR_003(GTJA_Base):
    name = "GTJA_PLACEHOLDER_003"
    name_cn = "GTJA003因子"
    category = "volatility"
    subcategory = "price_volatility"
    description = "GTJA191因子003"
    formula = ""


class GTJA_FACTOR_004(GTJA_Base):
    name = "GTJA_PLACEHOLDER_004"
    name_cn = "GTJA004因子"
    category = "volume"
    subcategory = "volume_trend"
    description = "GTJA191因子004"
    formula = ""


class GTJA_FACTOR_005(GTJA_Base):
    name = "GTJA_PLACEHOLDER_005"
    name_cn = "GTJA005因子"
    category = "reversal"
    subcategory = "price_reversal"
    description = "GTJA191因子005"
    formula = ""


# 成交额相关因子
class GTJA_AMOUNT20(GTJA_Base):
    name = "GTJA_AMOUNT20"
    name_cn = "20日成交额均值"
    category = "volume"
    subcategory = "volume_trend"
    description = "20日成交额移动平均"
    formula = "Amount20 = MA(Close * Volume, 20)"

    params = [
        FactorParam("period", 20, "int", 1, 252, "平均周期")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        # 501 #R24：走基类 check_data 契约（缺失列报契约错误而非裸 KeyError）
        if not self.check_data(data):
            raise ValueError(f"{self.name} 数据缺少必需列（required_columns={self._required_columns}）")
        period = self.get_param("period")
        # 501 #R55：短输入显式报错（原 rolling 满窗口前全 NaN 静默）
        if len(data) < period:
            raise ValueError(f"{self.name} 数据长度 {len(data)} < period {period}")
        amount = data["close"] * data["vol"]
        return amount.rolling(window=period).mean()


class GTJA_AMOUNT60(GTJA_Base):
    name = "GTJA_AMOUNT60"
    name_cn = "60日成交额均值"
    category = "volume"
    subcategory = "volume_trend"
    description = "60日成交额移动平均"
    formula = "Amount60 = MA(Close * Volume, 60)"

    params = [
        FactorParam("period", 60, "int", 1, 252, "平均周期")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        # 501 #R24：走基类 check_data 契约
        if not self.check_data(data):
            raise ValueError(f"{self.name} 数据缺少必需列（required_columns={self._required_columns}）")
        period = self.get_param("period")
        # 501 #R55：短输入显式报错
        if len(data) < period:
            raise ValueError(f"{self.name} 数据长度 {len(data)} < period {period}")
        amount = data["close"] * data["vol"]
        return amount.rolling(window=period).mean()


class GTJA_HL20(GTJA_Base):
    name = "GTJA_HL20"
    name_cn = "20日高低振幅"
    category = "volatility"
    subcategory = "price_volatility"
    description = "20日最高价除以最低价"
    formula = "HL20 = HighestHigh(20) / LowestLow(20)"

    params = [
        FactorParam("period", 20, "int", 1, 252, "周期")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        # 501 #R24：走基类 check_data 契约
        if not self.check_data(data):
            raise ValueError(f"{self.name} 数据缺少必需列（required_columns={self._required_columns}）")
        period = self.get_param("period")
        # 501 #R55：短输入显式报错
        if len(data) < period:
            raise ValueError(f"{self.name} 数据长度 {len(data)} < period {period}")
        high_n = data["high"].rolling(window=period).max()
        low_n = data["low"].rolling(window=period).min()
        # 501 #R21：分母仅接受正值——replace(0) 无法拦截负/NaN 低值，会透传 inf/NaN
        return high_n / low_n.where(low_n > 0)


class GTJA_CORR_VOL10(GTJA_Base):
    name = "GTJA_CORR_VOL10"
    name_cn = "10日量价相关性"
    category = "volume"
    subcategory = "volume_price"
    description = "过去10日价格与成交量的相关系数"
    formula = "CorrVol10 = Corr(Close, Volume, 10)"

    params = [
        FactorParam("period", 10, "int", 2, 252, "周期")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        # 501 #R24：走基类 check_data 契约
        if not self.check_data(data):
            raise ValueError(f"{self.name} 数据缺少必需列（required_columns={self._required_columns}）")
        period = self.get_param("period")
        # 501 #R55：短输入显式报错
        if len(data) < period:
            raise ValueError(f"{self.name} 数据长度 {len(data)} < period {period}")
        return data["close"].rolling(window=period).corr(data["vol"])
