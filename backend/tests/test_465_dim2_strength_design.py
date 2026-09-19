# -*- coding: utf-8 -*-
"""465号：dim2 结构强度打分设计修复（465-1）+ 买卖点 date 回填（465-2）

465-1A（窗口限制）：ChanlunScorer.score 计分限每 type 最近 K 个买卖点（_recent_by_type），
  防最新中枢后历史三卖累计扣分主导（万科 24 三卖 -192 分压到 0）。
465-1B（type 变体匹配）：first_buy_p/second_buy_b/third_buy_a/third_buy_b/first_sell_p/
  third_sell_a 等变体计入每点加减分（原只认基础三型 → 买点变体不加分、卖点照扣不对称）。
465-2（date 回填）：dim2 buy_sell_points_detail.date 空时从 daily_df idx 反查交易日。
"""
import numpy as np
import pandas as pd
from unittest import mock

from app.engine.framework.chanlun_strategy import BuySellPoint, ChanlunScorer, _recent_by_type
from app.opportunity_atlas.dimensions.dim2_structure_engine import (
    Dim2StructureEngine, ChanlunAnalyzer, _resolve_bsp_date,
)


def _bsp(ptype, idx, price=10.0, date=''):
    return BuySellPoint(type=ptype, confidence=0.8,
                        position={'idx': idx, 'price': price, 'date': date},
                        reason='test')


def _mk_df(n=90, with_date=True):
    closes = np.linspace(10, 20, n) + np.sin(np.linspace(0, 8, n)) * 0.5
    df = pd.DataFrame({
        'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes, 'vol': [1e5] * n, 'amount': [3e5] * n,
    })
    if with_date:
        df['trade_date'] = pd.date_range('2025-01-01', periods=n, freq='B')
    return df


def _mk_result(buys=None, sells=None, trend='unknown'):
    return {
        'trend': trend, 'zhongshu': [], 'divergence': None,
        'buy_points': buys or [], 'sell_points': sells or [],
        'theorem_check': {'summary': {'overall_score': 0.7}},
    }


class TestRecentByType:
    """465-1A：按 type 分组取最近 K 个（idx 最大）。"""

    def test_many_third_sell_trimmed(self):
        pts = [_bsp('third_sell', i) for i in range(24)]
        kept = _recent_by_type(pts, k=3)
        assert len(kept) == 3
        assert sorted(p.position['idx'] for p in kept) == [21, 22, 23]

    def test_per_type_independent(self):
        buys = [_bsp('first_buy', 1000)] + [_bsp('third_buy_b', 900 + i) for i in range(10)]
        sells = [_bsp('third_sell', i) for i in range(24)]
        kept_b = _recent_by_type(buys, k=3)
        kept_s = _recent_by_type(sells, k=3)
        # first_buy 仅 1 个全留；third_buy_b 留最近 3 个
        assert len(kept_b) == 4
        assert sum(1 for p in kept_b if p.type == 'first_buy') == 1
        assert sum(1 for p in kept_b if p.type == 'third_buy_b') == 3
        assert len(kept_s) == 3

    def test_empty_and_no_position(self):
        assert _recent_by_type([]) == []
        # idx 缺失视为最新保留
        p = BuySellPoint(type='third_buy', confidence=0.8, position=None, reason='x')
        assert _recent_by_type([p]) == [p]


class TestScoreWindow:
    """465-1A：计分效果——万科场景（1 一买 + 24 三卖）不再压到 0。"""

    def test_vanke_scenario_not_zero(self):
        result = _mk_result(
            buys=[_bsp('first_buy', 1200, price=2.98)],
            sells=[_bsp('third_sell', 200 + i) for i in range(24)],
        )
        sr = ChanlunScorer.score(result)
        # 买 +30+20；卖 -20-8*3；+50 clamp → 应 >0
        assert 0 < sr['score'] < 100

    def test_maotai_scenario_not_zero(self):
        """无买点 + 15 三卖（茅台）→ 只计最近 3 卖：-20-24 → +50 = 6。"""
        result = _mk_result(
            buys=[],
            sells=[_bsp('third_sell', 300 + i) for i in range(15)],
        )
        sr = ChanlunScorer.score(result)
        assert sr['score'] == 6

    def test_few_sells_unchanged(self):
        """招行场景（12 三买b + 1 一卖）——变体买点计入后为正分。"""
        result = _mk_result(
            buys=[_bsp('third_buy_b', 800 + i) for i in range(12)],
            sells=[_bsp('first_sell', 900)],
        )
        sr = ChanlunScorer.score(result)
        # 买 +30+10*3；卖 -20-15；+50 → 30+30-35+50=75
        assert sr['score'] == 75


class TestScoreVariantMatch:
    """465-1B：type 变体计入每点加减分。"""

    def test_third_buy_b_counted(self):
        result = _mk_result(buys=[_bsp('third_buy_b', 10 + i) for i in range(5)])
        sr = ChanlunScorer.score(result)
        # 3 个 third_buy_b：+30 + 10*3 = 60 → +50 = 110 → clamp 100
        assert sr['score'] == 100

    def test_first_buy_p_counted(self):
        result = _mk_result(buys=[_bsp('first_buy_p', 10)])
        sr = ChanlunScorer.score(result)
        assert sr['score'] == 100  # +30+20 → +50 = 100

    def test_third_sell_a_counted(self):
        result = _mk_result(sells=[_bsp('third_sell_a', 10 + i) for i in range(5)])
        sr = ChanlunScorer.score(result)
        assert sr['score'] == 6  # 3 个 third_sell_a：-20-24 → +50 = 6

    def test_second_buy_b_counted(self):
        result = _mk_result(buys=[_bsp('second_buy_b', 10)])
        sr = ChanlunScorer.score(result)
        assert sr['score'] == 95  # +30+15 → +50 = 95


class TestBspDateBackfill:
    """465-2：position.date 空时从 daily_df idx 反查交易日。"""

    def test_backfill_from_idx(self):
        df = _mk_df(n=90, with_date=True)
        assert _resolve_bsp_date({'idx': 5, 'date': ''}, df) == \
            str(df['trade_date'].iloc[5])[:10]

    def test_existing_date_kept(self):
        df = _mk_df(n=90, with_date=True)
        assert _resolve_bsp_date({'idx': 5, 'date': '2024-01-02'}, df) == '2024-01-02'

    def test_idx_out_of_range(self):
        df = _mk_df(n=90, with_date=True)
        assert _resolve_bsp_date({'idx': 99999, 'date': ''}, df) == ''

    def test_no_df(self):
        assert _resolve_bsp_date({'idx': 5, 'date': ''}, None) == ''

    def test_no_trade_date_col(self):
        df = _mk_df(n=90, with_date=False)
        assert _resolve_bsp_date({'idx': 5, 'date': ''}, df) == ''


class TestDim2BspDateIntegration:
    """465-2 集成：evaluate 输出的 buy_sell_points_detail.date 回填。"""

    def test_first_buy_date_backfilled(self):
        df = _mk_df(n=90, with_date=True)
        eng = Dim2StructureEngine()
        first_buy = BuySellPoint(
            type='first_buy', confidence=1.0,
            position={'idx': 60, 'price': 12.0, 'date': ''}, reason='下跌趋势背驰')
        result = _mk_result(buys=[first_buy], sells=[])
        with mock.patch.object(ChanlunAnalyzer, 'analyze', return_value=result):
            out = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={'daily_df': df})
        detail = out['status_description']['buy_sell_points_detail'][0]
        assert detail['date'] == str(df['trade_date'].iloc[60])[:10]
        assert detail['date'] != ''

    def test_second_buy_date_preserved(self):
        df = _mk_df(n=90, with_date=True)
        eng = Dim2StructureEngine()
        sb = BuySellPoint(
            type='second_buy', confidence=0.7,
            position={'idx': 60, 'price': 12.0, 'date': '2024-03-01'}, reason='回调不创新低')
        result = _mk_result(buys=[sb], sells=[])
        with mock.patch.object(ChanlunAnalyzer, 'analyze', return_value=result):
            out = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={'daily_df': df})
        detail = out['status_description']['buy_sell_points_detail'][0]
        assert detail['date'] == '2024-03-01'
