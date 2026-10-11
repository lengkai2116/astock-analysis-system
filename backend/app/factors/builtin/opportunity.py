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

# 502 登记-2（2026-10-11）：PE/PB/PS_PERCENTILE_5Y「真 5Y 窗口」接线。
# 数据源 = daily_basic_cache（pe_ttm/pb/ps，每日，2021-07-07 起 ≈5.25 年）——
# 对 ~70-78% 股票可做满 5 年窗口；次新股/短区间退化回全输入区间分位（原行为）。
_5Y_WINDOW_MIN_SAMPLES = 120  # 窗口内有效样本下限（≈半年交易日），低于则分位不稳定


def _percentile_5y_window(data: pd.DataFrame, col: str) -> pd.Series:
    """最近 5 年窗口内分位（502 登记-2 接线）

    以 data 内最新 trade_date 为基准取最近 5 年（日历窗口）内的有效样本做
    `rank(pct=True)*100`；窗口外行返回 NaN（历史更早数据无「近 5 年分位」概念，
    factor_precompute 会跳过 NaN 不写库）。退化路径（保持原「全输入区间分位」
    行为）：data 无 trade_date 列 / 窗口内有效样本 < 下限。
    """
    s = data[col]
    if 'trade_date' not in data.columns:
        return s.rank(pct=True) * 100
    try:
        latest = pd.to_datetime(data['trade_date']).max()
        cutoff = latest - pd.DateOffset(years=5)
        mask = pd.to_datetime(data['trade_date']) >= cutoff
    except Exception:
        return s.rank(pct=True) * 100
    window = s[mask]
    if window.notna().sum() < _5Y_WINDOW_MIN_SAMPLES:
        return s.rank(pct=True) * 100
    result = pd.Series(np.nan, index=data.index)
    result[mask] = window.rank(pct=True) * 100
    return result


class PE_PERCENTILE_5Y(BaseFactor):
    """PE 5年历史百分位"""
    name = "PE_PERCENTILE_5Y"
    name_cn = "PE历史百分位"
    category = "valuation"
    subcategory = "pe"
    description = ("PE历史百分位（502登记-2：真 5Y 窗口——以数据内最新日为基准取最近 5 年"
                   "窗口内分位，窗口外为 NaN；窗口有效样本<120 或无 trade_date 时退回全输入区间分位）")
    source = "Opportunity"
    source_detail = "机会图谱估值因子"
    required_columns = ["pe_ttm"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return _percentile_5y_window(data, 'pe_ttm')


class PB_PERCENTILE_5Y(BaseFactor):
    """PB 5年历史百分位"""
    name = "PB_PERCENTILE_5Y"
    name_cn = "PB历史百分位"
    category = "valuation"
    subcategory = "pb"
    description = ("PB历史百分位（502登记-2：真 5Y 窗口——以数据内最新日为基准取最近 5 年"
                   "窗口内分位，窗口外为 NaN；窗口有效样本<120 或无 trade_date 时退回全输入区间分位）")
    source = "Opportunity"
    source_detail = "机会图谱估值因子"
    required_columns = ["pb"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return _percentile_5y_window(data, 'pb')


class PS_PERCENTILE_5Y(BaseFactor):
    """PS 5年历史百分位"""
    name = "PS_PERCENTILE_5Y"
    name_cn = "PS历史百分位"
    category = "valuation"
    subcategory = "ps"
    description = ("PS历史百分位（502登记-2：真 5Y 窗口——以数据内最新日为基准取最近 5 年"
                   "窗口内分位，窗口外为 NaN；窗口有效样本<120 或无 trade_date 时退回全输入区间分位）")
    source = "Opportunity"
    source_detail = "机会图谱估值因子"
    required_columns = ["ps"]

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return _percentile_5y_window(data, 'ps')


class DIVIDEND_YIELD(BaseFactor):
    """股息率（近12个月）——501 #R54 登记：设计态因子（required_columns=[] 恒 NaN），
    非缺陷；待分红数据就绪后实现（见 source_detail TODO）"""
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
