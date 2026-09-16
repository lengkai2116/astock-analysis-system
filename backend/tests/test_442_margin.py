"""442号缺陷②：_assess_margin 改读 margin_df 缓存（5日融资余额变化）"""

import pandas as pd
import pytest

from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import _assess_margin


def _margin_df(values):
    """构造 margin_df（trade_date/rzye 两列，升序）"""
    return pd.DataFrame({
        'trade_date': pd.date_range('2026-09-01', periods=len(values), freq='D'),
        'rzye': values,
    })


class TestAssessMargin:
    def test_tags_priority(self):
        """tags['margin_change_5d'] 优先于 margin_df"""
        r = _assess_margin({'margin_change_5d': 12.5})
        assert '增加' in r['detail']
        r2 = _assess_margin({'margin_change_5d': -15.0})
        assert '减少' in r2['detail']

    def test_margin_df_5d_increase(self):
        """margin_df 计算 5 日变化：+15% → 杠杆上升"""
        df = _margin_df([100.0, 101.0, 102.0, 103.0, 104.0, 115.0])
        r = _assess_margin({}, margin_df=df)
        assert '增加15%' in r['detail']

    def test_margin_df_5d_decrease(self):
        """margin_df 计算 5 日变化：-13% → 去杠杆"""
        df = _margin_df([115.0, 114.0, 113.0, 112.0, 111.0, 100.0])
        r = _assess_margin({}, margin_df=df)
        assert '减少13%' in r['detail']

    def test_margin_df_normal(self):
        """margin_df 计算 5 日变化：正常范围"""
        df = _margin_df([100.0, 100.5, 100.2, 100.8, 100.6, 100.5])
        r = _assess_margin({}, margin_df=df)
        assert '正常范围' in r['detail']

    def test_margin_df_short_history(self):
        """margin_df 不足 6 行：用最早一行作基（2 行也可算）"""
        df = _margin_df([100.0, 115.0])
        r = _assess_margin({}, margin_df=df)
        assert '增加' in r['detail']

    def test_margin_df_too_short_fallback(self):
        """margin_df 不足 2 行 / 无 rzye 列 → 融资数据不足"""
        assert _assess_margin({}, margin_df=_margin_df([100.0]))['detail'] == '融资数据不足'
        assert _assess_margin({}, margin_df=pd.DataFrame({'trade_date': ['2026-09-01'], 'x': [1]}))['detail'] == '融资数据不足'

    def test_no_data_fallback(self):
        """无 tags 无 margin_df → 融资数据不足"""
        assert _assess_margin({})['detail'] == '融资数据不足'
