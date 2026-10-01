"""
反转类因子
"""
import numpy as np
import pandas as pd

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
    description = "衡量超买超卖，-100..0，越接近 -100 越超卖（502批次1：修正文档与实现一致——Williams %R 标准定义）"
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
        # 502批次5 #R13 同型（登记-3 拍板）：平盘窗口（high==low）WILLR=-50 中性
        denom = high_n - low_n
        willr = (high_n - data["close"]) * (-100) / denom
        return willr.mask(denom == 0, -50.0)


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
        # 502批次5 #R13 同型：平盘窗口（high==low）RSV=50 中性
        denom = high_n - low_n
        rsv = (data["close"] - low_n) * 100 / denom
        return rsv.mask(denom == 0, 50.0)


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
        # 501 #R42：保留 NaN（.where(diff>0) 不带 fill）——原 fill=0 把首行/NaN 缺口
        # 当零动量计入滚动和，偏置 up/down；NaN 应传播（滚动和默认 skipna）
        up = diff.where(diff > 0)
        down = -diff.where(diff < 0)

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
    description = "收益率时序分位（502批次2 #R8：单标的数据流下横截面 Rank 不可实现——与 QLIB_*_RANK 同构，实现为滚动窗口时序分位）"
    formula = "ROC_R = RollingRank(ROC(period))"
    source = "GTJA"
    source_detail = "GTJA191"

    params = [
        FactorParam("period", 5, "int", 1, 252, "收益率周期")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        roc = (data["close"] / data["close"].shift(period) - 1) * 100
        # 502批次2 #R8：rolling rank（时序分位），原返回原始 ROC 与声明不符
        return roc.rolling(window=period).rank(pct=True)


class MOM_R(BaseFactor):
    """
    Momentum Rank - 动量排序
    """
    name = "MOM_R"
    name_cn = "动量排序因子"
    category = "reversal"
    subcategory = "cross_section"
    description = "动量时序分位（502批次2 #R8：单标的数据流下横截面 Rank 不可实现——与 QLIB_*_RANK 同构，实现为滚动窗口时序分位）"
    formula = "MOM_R = RollingRank(MOM(period))"
    source = "GTJA"
    source_detail = "GTJA191"

    params = [
        FactorParam("period", 20, "int", 1, 252, "动量周期")
    ]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        period = self.get_param("period")
        mom = data["close"] - data["close"].shift(period)
        # 502批次2 #R8：rolling rank（时序分位），原返回原始 MOM 与声明不符
        return mom.rolling(window=period).rank(pct=True)
