"""461-14：dim1 completeness_score 口径越界修复

来源 482-7（482 方案 §九）转入。原实现：
    completeness_score = len(loaded_keys) / (len(required) + len(optional))
分子 `loaded_keys` 取自 data_context 全部有效键，但 data_context 另载有
非契约辅助键（weekly_df/hourly_df/relative_strength，457/445 产，设计内可降级/尽力而为）
→ 分子 > 分母 → 完整度 >1.0 不自洽（实测 1.0435=24/23、1.0870=25/23）。

修复：分子只计期望清单(required+optional)中已载的键，分母保持 len(required+optional)。
辅助键不进契约 → 不影响 missing_tables/quality_level（延续 457「可降级单级别」）。
"""
import pandas as pd

from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine


def _full_expected_context() -> dict:
    """构造全量 data_context。

    契约键（required+optional）= 22：'lhb_df' 已由 483号 ① 移出契约（稀疏事件表），
    故此处含 23 键但契约内仅 22 键（lhb_df 视为非契约的辅助键）。
    """
    return {
        # ECM原料表（10项）
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
        # indicator预计算表（3项）
        'indicator_ma_df': pd.DataFrame({'ma5': [10.0], 'ma20': [10.0]}),
        'indicator_macd_df': pd.DataFrame({'macd_dif': [0.1]}),
        'indicator_other_df': pd.DataFrame({'rsi14': [50.0]}),
        # pre_feat_cache ext组（8项）
        'chip_fund_ext': {'asr': 50},
        'cost_ext': {'main_force_cost': 10.0},
        'volume_ext': {'vol_ma5': 1000},
        'risk_ext': {'support_price': 9.0},
        'fund_5d_ext': {'net_lg_5d': 100},
        'emotion_ext': {'emotion_temperature': 50},
        'structure_ext': {'support_price': 9.0},
        'market_stats': {'ma20_ratio': 0.5},
        # 442/461-8 配置完善：optional 含 valuation_ext/sector_heat
        'valuation_ext': {'valuation_level': '合理'},
        'sector_heat': {'全国地产': {'heat_level': 'none'}},
    }


def _aux_keys() -> dict:
    """非契约辅助键（457 周/60min + 445 RPS），设计内可降级/尽力而为。"""
    return {
        'weekly_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
        'hourly_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
        'relative_strength': {'rps_20d': 88.0, 'rps_60d': 75.0, 'asof_date': '20260101'},
    }


class TestCompletenessClamp:
    """完整度口径：期望清单内占比，辅助键不入契约。"""

    def test_full_expected_and_aux_capped_at_one(self):
        """23 期望键 + 3 辅助键 → 1.0（旧口径为 26/23=1.1304）"""
        engine = Dim1SignalEngine()
        ctx = _full_expected_context()
        ctx.update(_aux_keys())
        result = engine._validate(ctx, '000001.SZ')
        assert result['completeness_score'] == 1.0
        assert result['quality_level'] == 'good'
        assert result['missing_tables'] == []

    def test_aux_keys_not_in_missing_tables(self):
        """仅缺辅助键（无 weekly/hourly/relative_strength）→ 不进 missing、不降级"""
        engine = Dim1SignalEngine()
        result = engine._validate(_full_expected_context(), '000001.SZ')
        for k in ('weekly_df', 'hourly_df', 'relative_strength'):
            assert k not in result['missing_tables']
        assert result['quality_level'] == 'good'
        assert result['completeness_score'] == 1.0

    def test_observed_10435_case(self):
        """复现实测 1.0435（23 期望键 + 1 辅助键）→ 修复后恒 ≤1.0"""
        engine = Dim1SignalEngine()
        ctx = _full_expected_context()
        ctx['weekly_df'] = pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]})
        result = engine._validate(ctx, '000001.SZ')
        assert result['completeness_score'] == 1.0

    def test_missing_expected_key_lowers_score(self):
        """缺 1 个契约键 → 21/22（483号 ① 后 lhb_df 已非契约键，契约基数 22）"""
        engine = Dim1SignalEngine()
        ctx = _full_expected_context()
        ctx.pop('cashflow_df')
        result = engine._validate(ctx, '000001.SZ')
        assert result['completeness_score'] == round(21 / 22, 4)
        assert 'cashflow_df' in result['missing_tables']
        assert result['quality_level'] == 'degraded'

    def test_empty_context_zero(self):
        """空 context → 0.0"""
        engine = Dim1SignalEngine()
        assert engine._validate({}, '000001.SZ')['completeness_score'] == 0.0

    def test_score_never_exceeds_one(self):
        """任意加载组合下完整度不越界 >1.0"""
        engine = Dim1SignalEngine()
        ctx = _full_expected_context()
        ctx.update(_aux_keys())
        # 再塞若干未知键，仍不得抬高分子
        ctx['unknown_key_a'] = {'x': 1}
        ctx['unknown_key_b'] = pd.DataFrame({'c': [1]})
        result = engine._validate(ctx, '000001.SZ')
        assert result['completeness_score'] <= 1.0
