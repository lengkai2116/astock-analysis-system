"""502 登记-2：PE/PB/PS_PERCENTILE_5Y 真 5Y 窗口接线测试

背景：原实现 `rank(pct=True)` 为全输入区间分位（随传入区间漂移）；
502 登记-2 接线后以数据内最新 trade_date 为基准取最近 5 年窗口内分位，
窗口外返回 NaN；窗口有效样本 <120 或无 trade_date 列时退回全输入区间分位。
"""
import pytest
import pandas as pd
import numpy as np

from app.factors.builtin.opportunity import (
    PE_PERCENTILE_5Y,
    PB_PERCENTILE_5Y,
    PS_PERCENTILE_5Y,
    _percentile_5y_window,
    _5Y_WINDOW_MIN_SAMPLES,
)

CUTOFF = '2021-10-09'  # 2026-10-09（数据内最新日）往前 5 年


def _mk_df(dates, col='pe_ttm', values=None):
    n = len(dates)
    if values is None:
        values = list(range(1, n + 1))
    return pd.DataFrame({'trade_date': dates.strftime('%Y-%m-%d'), col: values})


class Test5YWindow:
    def test_window_cutoff_and_rank(self):
        """6 年数据：窗口外（<2021-10-09）为 NaN，窗口内单调分位，末行=100"""
        dates = pd.bdate_range('2020-10-09', '2026-10-09')
        df = _mk_df(dates, 'pe_ttm')
        res = PE_PERCENTILE_5Y().calculate(df)

        assert len(res) == len(df), "返回序列须与输入等长"
        outside = df['trade_date'] < CUTOFF
        inside = ~outside
        assert res[outside].isna().all(), "窗口外（更早历史）应无近5年分位"
        assert res[inside].notna().all(), "窗口内应全有分位"
        assert res.iloc[-1] == pytest.approx(100.0), "窗口内最大值应为 100 分位"
        assert res[inside].iloc[0] < 1.0, "窗口内最小值应接近 0 分位"
        assert (res[inside].diff().dropna() > 0).all(), "单调递增序列的分位应单调"

    def test_three_factors_share_logic(self):
        """PB/PS 因子与 PE 同一窗口逻辑（冒烟）"""
        dates = pd.bdate_range('2020-10-09', '2026-10-09')
        for cls, col in ((PB_PERCENTILE_5Y, 'pb'), (PS_PERCENTILE_5Y, 'ps')):
            df = _mk_df(dates, col)
            res = cls().calculate(df)
            outside = df['trade_date'] < CUTOFF
            assert res[outside].isna().all()
            assert res.iloc[-1] == pytest.approx(100.0)

    def test_returns_same_as_rank_on_window_only(self):
        """窗口内分位 == 对窗口内子序列直接 rank（语义等价验证）"""
        dates = pd.bdate_range('2020-10-09', '2026-10-09')
        df = _mk_df(dates, 'pe_ttm')
        res = PE_PERCENTILE_5Y().calculate(df)
        inside = df['trade_date'] >= CUTOFF
        expected = df.loc[inside, 'pe_ttm'].rank(pct=True) * 100
        # 窗口内值逐位与子序列 rank 一致（含 NaN 位置由 mask 保证）
        assert res[inside].reset_index(drop=True).equals(
            expected.reset_index(drop=True)), "窗口内分位应等于窗口子序列 rank"


class TestFallback:
    def test_no_trade_date_column(self):
        """无 trade_date 列 → 退回全输入区间分位（原行为）"""
        df = pd.DataFrame({'pe_ttm': [10.0, 20.0, 30.0, 40.0]})
        res = PE_PERCENTILE_5Y().calculate(df)
        expected = df['pe_ttm'].rank(pct=True) * 100
        pd.testing.assert_series_equal(res, expected)

    def test_insufficient_window_samples(self):
        """6 年数据但窗口内有效样本 <120 → 退回全输入区间分位（无 NaN）"""
        dates = pd.bdate_range('2020-10-09', '2026-10-09')
        n = len(dates)
        df = pd.DataFrame({'trade_date': dates.strftime('%Y-%m-%d')})
        vals = [np.nan] * n
        outside_mask = dates < pd.Timestamp(CUTOFF)
        # 窗口外 30 个有效值 + 窗口内 50 个有效值（<120 下限）
        idxs = np.where(outside_mask)[0][:30].tolist() + \
            np.where(~outside_mask)[0][:50].tolist()
        for i, v in zip(idxs, range(1, len(idxs) + 1)):
            vals[i] = float(v)
        df['pe_ttm'] = vals
        res = PE_PERCENTILE_5Y().calculate(df)
        # 退化路径：全部有效值（窗口外 30 + 窗口内 50 = 80）参与全输入 rank，
        # 产出分位数 = 有效值数（数据自身的 NaN 仍保持 NaN）
        assert res.notna().sum() == len(idxs), "退化路径应对全部有效值产出分位"
        expected = df['pe_ttm'].rank(pct=True) * 100
        pd.testing.assert_series_equal(res, expected)

    def test_min_samples_constant_exists(self):
        """下限常量存在且合理（供维护参考）"""
        assert _5Y_WINDOW_MIN_SAMPLES == 120

    def test_constant_values_stable(self):
        """常量序列：窗口内分位恒等（无漂移）"""
        dates = pd.bdate_range('2020-10-09', '2026-10-09')
        df = _mk_df(dates, 'pe_ttm', values=[50.0] * len(dates))
        res = PE_PERCENTILE_5Y().calculate(df)
        inside = df['trade_date'] >= CUTOFF
        assert res[inside].nunique() == 1, "常量序列分位应恒为同一值"

    def test_helper_rejects_bad_trade_date(self):
        """trade_date 不可解析 → 退化全输入分位"""
        df = pd.DataFrame({'trade_date': ['bad', 'also_bad', 'x'], 'pe_ttm': [1.0, 2.0, 3.0]})
        res = _percentile_5y_window(df, 'pe_ttm')
        expected = df['pe_ttm'].rank(pct=True) * 100
        pd.testing.assert_series_equal(res, expected)
