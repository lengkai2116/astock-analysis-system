"""
机会图谱因子库
估值/质量/情绪因子 — 基于历史百分位与财务指标
文件路径：backend/app/factors/builtin/opportunity.py
"""
import numpy as np
import pandas as pd

from ..base import BaseFactor

# =============================================
# 估值因子 (Valuation)
# =============================================

class PE_PERCENTILE_5Y(BaseFactor):
    """PE 5年历史百分位"""
    name = "PE_PERCENTILE_5Y"
    name_cn = "PE历史百分位"
    category = "valuation"
    subcategory = "pe"
    description = "PE在近5年历史中的百分位"
    source = "Opportunity"
    source_detail = "机会图谱估值因子"
    required_columns = ["pe_ttm"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['pe_ttm'].rank(pct=True) * 100


class PB_PERCENTILE_5Y(BaseFactor):
    """PB 5年历史百分位"""
    name = "PB_PERCENTILE_5Y"
    name_cn = "PB历史百分位"
    category = "valuation"
    subcategory = "pb"
    description = "PB在近5年历史中的百分位"
    source = "Opportunity"
    source_detail = "机会图谱估值因子"
    required_columns = ["pb"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['pb'].rank(pct=True) * 100


class PS_PERCENTILE_5Y(BaseFactor):
    """PS 5年历史百分位"""
    name = "PS_PERCENTILE_5Y"
    name_cn = "PS历史百分位"
    category = "valuation"
    subcategory = "ps"
    description = "PS在近5年历史中的百分位"
    source = "Opportunity"
    source_detail = "机会图谱估值因子"
    required_columns = ["ps"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['ps'].rank(pct=True) * 100


class DIVIDEND_YIELD(BaseFactor):
    """股息率（近12个月）"""
    name = "DIVIDEND_YIELD"
    name_cn = "股息率"
    category = "valuation"
    subcategory = "dividend"
    description = "近12个月股息率"
    formula = "dividend / price"
    source = "Opportunity"
    source_detail = "机会图谱估值因子（TODO: 待分红数据就绪）"
    required_columns = []  # 暂无数据

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        # TODO: 分红数据就绪后实现
        return pd.Series(np.nan, index=data.index)


# =============================================
# 质量因子 (Quality)
# =============================================

class ROE(BaseFactor):
    """净资产收益率"""
    name = "ROE"
    name_cn = "净资产收益率"
    category = "quality"
    subcategory = "profitability"
    description = "净资产收益率(Return on Equity)"
    source = "Opportunity"
    source_detail = "机会图谱质量因子"
    required_columns = ["roe"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['roe']


class DEBT_RATIO(BaseFactor):
    """资产负债率"""
    name = "DEBT_RATIO"
    name_cn = "资产负债率"
    category = "quality"
    subcategory = "solvency"
    description = "资产负债率"
    source = "Opportunity"
    source_detail = "机会图谱质量因子"
    required_columns = ["debt_ratio"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['debt_ratio']


class REVENUE_GROWTH(BaseFactor):
    """营收增长率"""
    name = "REVENUE_GROWTH"
    name_cn = "营收增长率"
    category = "quality"
    subcategory = "growth"
    description = "营业收入同比增长率"
    source = "Opportunity"
    source_detail = "机会图谱质量因子"
    required_columns = ["revenue_growth"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['revenue_growth']


class PROFIT_GROWTH(BaseFactor):
    """净利润增长率"""
    name = "PROFIT_GROWTH"
    name_cn = "净利润增长率"
    category = "quality"
    subcategory = "growth"
    description = "净利润同比增长率"
    source = "Opportunity"
    source_detail = "机会图谱质量因子"
    required_columns = ["profit_growth"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['profit_growth']


# =============================================
# 情绪因子 (Emotion)
# =============================================

class EMOTION_EXTREME(BaseFactor):
    """情绪极端指标 — 基于BOCIASI快慢线"""
    name = "EMOTION_EXTREME"
    name_cn = "情绪极端指标"
    category = "emotion"
    subcategory = "sentiment"
    description = "基于BOCIASI快慢线的市场情绪极端程度（TODO: 待改造后BOCIASI就绪）"
    source = "Opportunity"
    source_detail = "机会图谱情绪因子（暂缺）"
    required_columns = []

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(np.nan, index=data.index)
