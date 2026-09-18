"""461-10：volume_ratio 跨表日期对齐 + dim1 校验补 margin

460 §六 阶段1-1-5 / P5：
 1. volume_ratio 读取按特征 trade_date 跨表日期对齐（回补/target_date 截断时
    避免误取 daily_basic 更新日期导致的量比与当日量错位；缺当日回退最新非空量比维持
    459 R4-b 语义，无数据回退 1.0）。
 2. dim1 `_validate` 日期对齐检查补入 margin_df——margin 采集设计允许 ≤7 天滞后
    （data_daemon 以滞后 >7 天才触发范围补采），故带 7 天容差，避免正常滞后被误判降级。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd

import pytest


@pytest.fixture
def engine():
    from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
    return Dim1SignalEngine()


def _base_ctx():
    """全量加载通过的 data_context 基线（复用 test_dim1_gate 结构）"""
    return {
        'daily_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
        'moneyflow_df': pd.DataFrame({'trade_date': ['20260101']}),
        'daily_basic_df': pd.DataFrame({'trade_date': ['20260101']}),
        'margin_df': pd.DataFrame({'trade_date': ['20260101']}),
        'fina_df': pd.DataFrame({'ts_code': ['000001.SZ']}),
        'income_df': pd.DataFrame({'ts_code': ['000001.SZ']}),
        'balancesheet_df': pd.DataFrame({'ts_code': ['000001.SZ']}),
        'cashflow_df': pd.DataFrame({'ts_code': ['000001.SZ']}),
        'stk_holder_df': pd.DataFrame({'ts_code': ['000001.SZ']}),
        'lhb_df': pd.DataFrame({'ts_code': ['000001.SZ']}),
        'indicator_ma_df': pd.DataFrame({'ma5': [10.0], 'ma20': [10.0]}),
        'indicator_macd_df': pd.DataFrame({'macd_dif': [0.1]}),
        'indicator_other_df': pd.DataFrame({'rsi14': [50.0]}),
        'chip_fund_ext': {'asr': 50},
        'cost_ext': {'main_force_cost': 10.0},
        'volume_ext': {'vol_ma5': 1000},
        'risk_ext': {'support_price': 9.0},
        'fund_5d_ext': {'net_lg_5d': 100},
        'emotion_ext': {'emotion_temperature': 50},
        'structure_ext': {'support_price': 9.0},
        'market_stats': {'ma20_ratio': 0.5},
        'valuation_ext': {'valuation_level': '合理'},
        'sector_heat': {'全国地产': {'heat_level': 'none', 'strength': 0.0, 'rank': 42, 'stock_count': 100}},
    }


class TestVolumeRatioDateAlignment:
    """461-10：_pick_volume_ratio 跨表日期对齐"""

    def _pick(self, db, trade_date):
        import data_daemon
        return data_daemon._pick_volume_ratio(db, trade_date)

    def test_same_date_picked(self):
        """trade_date 当日存在 → 取当日量比（而非更新日期的最新行）"""
        db = pd.DataFrame({
            'trade_date': ['20260102', '20260103'],
            'volume_ratio': [1.2, 0.8],
        })
        # 特征按 20260102 截断，daily_basic 含 20260103（更新）——应取 20260102 的 1.2，避免错日
        assert self._pick(db, '20260102') == 1.2

    def test_missing_trade_date_falls_back_latest(self):
        """当日无数据 → 回退最新非空量比（容忍采集滞后，459 R4-b 语义）"""
        db = pd.DataFrame({
            'trade_date': ['20260102', '20260103'],
            'volume_ratio': [1.2, None],
        })
        assert self._pick(db, '20260104') == 1.2

    def test_dash_date_normalized(self):
        """trade_date 带连字符（YYYY-MM-DD）与库内 YYYYMMDD 兼容"""
        db = pd.DataFrame({
            'trade_date': ['2026-01-02'],
            'volume_ratio': [1.5],
        })
        assert self._pick(db, '20260102') == 1.5

    def test_no_volume_ratio_column_defaults_1(self):
        """缺 volume_ratio 列 → 回退 1.0（不抛）"""
        db = pd.DataFrame({'trade_date': ['20260102'], 'other': [1.0]})
        assert self._pick(db, '20260102') == 1.0

    def test_empty_db_defaults_1(self):
        """空 DataFrame / None → 回退 1.0（不抛）"""
        from data_daemon import _pick_volume_ratio
        assert _pick_volume_ratio(None, '20260102') == 1.0
        assert _pick_volume_ratio(pd.DataFrame(), '20260102') == 1.0


class TestDim1ValidateMarginAlignment:
    """461-10：dim1 _validate 补 margin 日期对齐（带 7 天容差）"""

    def test_margin_within_7d_lag_ok(self, engine):
        """margin 滞后 ≤7 天 → date_alignment_ok=True（正常滞后不降级）"""
        ctx = _base_ctx()
        ctx['daily_df'] = pd.DataFrame({'trade_date': ['20260108'], 'close': [10.0]})
        ctx['moneyflow_df'] = pd.DataFrame({'trade_date': ['20260108']})
        ctx['daily_basic_df'] = pd.DataFrame({'trade_date': ['20260108']})
        ctx['margin_df'] = pd.DataFrame({'trade_date': ['20260101']})  # 滞后 7 天
        result = engine._validate(ctx, '000001.SZ')
        assert result['validation_result']['date_alignment_ok'] is True

    def test_margin_over_7d_lag_degraded(self, engine):
        """margin 滞后 >7 天 → date_alignment_ok=False（超采口，降级提醒补采）"""
        ctx = _base_ctx()
        ctx['daily_df'] = pd.DataFrame({'trade_date': ['20260120'], 'close': [10.0]})
        ctx['moneyflow_df'] = pd.DataFrame({'trade_date': ['20260120']})
        ctx['daily_basic_df'] = pd.DataFrame({'trade_date': ['20260120']})
        ctx['margin_df'] = pd.DataFrame({'trade_date': ['20260101']})  # 滞后 19 天
        result = engine._validate(ctx, '000001.SZ')
        assert result['validation_result']['date_alignment_ok'] is False

    def test_moneyflow_still_strict(self, engine):
        """moneyflow/daily_basic 仍要求严格同日（不随 margin 放宽）"""
        ctx = _base_ctx()
        ctx['daily_df'] = pd.DataFrame({'trade_date': ['20260102'], 'close': [10.0]})
        ctx['moneyflow_df'] = pd.DataFrame({'trade_date': ['20260101']})  # 错 1 天
        ctx['daily_basic_df'] = pd.DataFrame({'trade_date': ['20260102']})
        ctx['margin_df'] = pd.DataFrame({'trade_date': ['20260102']})
        result = engine._validate(ctx, '000001.SZ')
        assert result['validation_result']['date_alignment_ok'] is False
