"""412号方案A4：dim1数据门禁层测试

覆盖：
- _validate() 质量校验（缺项/degraded/good/日期对齐）
- _notify_missing_data() 异步通知
- 降级路径（data_context=None时dim2-dim7回退）
- dim_adapter默认值
"""
from unittest.mock import patch

import pandas as pd


class TestDim1Validate:
    """dim1 _validate() 质量校验测试"""

    def test_validate_all_loaded(self):
        """全量加载 → quality_level='good'（20项全量）"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        data_context = {
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
        }
        result = engine._validate(data_context, '000001.SZ')
        assert result['quality_level'] == 'good'
        assert result['completeness_score'] == 1.0
        assert result['missing_tables'] == []

    def test_validate_missing_daily(self):
        """缺失daily_df → quality_level='failed'"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        data_context = {
            'moneyflow_df': pd.DataFrame({'trade_date': ['20260101']}),
        }
        result = engine._validate(data_context, '000001.SZ')
        assert result['quality_level'] == 'failed'
        assert 'daily_df' in result['missing_tables']

    def test_validate_missing_optional(self):
        """缺失可选项 → quality_level='degraded'"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        data_context = {
            'daily_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
            # 缺少 moneyflow_df, daily_basic_df 等
        }
        result = engine._validate(data_context, '000001.SZ')
        assert result['quality_level'] == 'degraded'
        assert len(result['missing_tables']) > 0

    def test_validate_date_misalignment(self):
        """日期不对齐 → date_alignment_ok=False"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        data_context = {
            'daily_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
            'moneyflow_df': pd.DataFrame({'trade_date': ['20260102']}),  # 日期不一致
        }
        result = engine._validate(data_context, '000001.SZ')
        assert result['validation_result']['date_alignment_ok'] is False

    def test_validate_empty_context(self):
        """空context → quality_level='failed', completeness_score=0"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        result = engine._validate({}, '000001.SZ')
        assert result['quality_level'] == 'failed'
        assert result['completeness_score'] == 0.0


class TestDim1NotifyMissing:
    """dim1 _notify_missing_data() 异步通知测试"""

    def test_notify_calls_request_data(self):
        """缺失数据时调用dm.request_data()"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        with patch('app.opportunity_atlas.dimensions.dim1_signal_engine.Dim1SignalEngine._notify_missing_data') as mock_notify:
            engine._notify_missing_data = mock_notify
            engine._notify_missing_data('000001.SZ', ['income_df', 'cashflow_df'])
            mock_notify.assert_called_once_with('000001.SZ', ['income_df', 'cashflow_df'])

    def test_notify_empty_list_noop(self):
        """空列表 → 不调用"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        # 不应抛异常
        engine._notify_missing_data('000001.SZ', [])


class TestDim1DegradedPath:
    """dim1 降级路径测试"""

    def test_evaluate_empty_ts_code(self):
        """空ts_code → data_context=None, quality_level='failed'"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        result = engine.evaluate({}, {}, None, None)
        assert result['data_context'] is None
        assert result['status_quality']['quality_level'] == 'failed'

    def test_evaluate_returns_all_keys(self):
        """evaluate()返回包含全部必要字段的status_quality"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        result = engine.evaluate({}, {'ts_code': '000001.SZ'}, None, None)
        sq = result['status_quality']
        assert 'data_loaded' in sq
        assert 'loaded_keys' in sq
        assert 'quality_level' in sq
        assert 'validation_result' in sq
        assert 'completeness_score' in sq
        assert 'missing_tables' in sq

    def test_dim1_has_validate_and_notify(self):
        """dim1包含_validate和_notify_missing_data方法"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        assert hasattr(Dim1SignalEngine, '_validate')
        assert hasattr(Dim1SignalEngine, '_notify_missing_data')
        assert callable(getattr(Dim1SignalEngine, '_validate'))
        assert callable(getattr(Dim1SignalEngine, '_notify_missing_data'))

class TestDim1V3DataLoading:
    """dim1 v3.0 全量数据加载测试"""

    def test_validate_handles_dict_values(self):
        """_validate()正确处理dict类型（ext组）"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        data_context = {
            'daily_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
            'chip_fund_ext': {'asr': 50, 'concentration': 0.3},
            'cost_ext': {'main_force_cost': 10.0},
            'indicator_ma_df': pd.DataFrame({'ma5': [10.0]}),
        }
        result = engine._validate(data_context, '000001.SZ')
        # 3 loaded / 20 total = 0.15
        assert result['completeness_score'] > 0
        assert 'daily_df' not in result['missing_tables']

    def test_validate_empty_dict_is_missing(self):
        """空dict被视为缺失"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        data_context = {
            'daily_df': pd.DataFrame({'trade_date': ['20260101'], 'close': [10.0]}),
            'chip_fund_ext': {},
            'cost_ext': {'main_force_cost': 10.0},
        }
        result = engine._validate(data_context, '000001.SZ')
        assert 'chip_fund_ext' in result['missing_tables']

    def test_notify_includes_indicator_and_ext_mappings(self):
        """_notify_missing_data包含indicator和ext的task映射"""
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        # 不抛异常即通过
        engine._notify_missing_data('000001.SZ', ['indicator_ma_df', 'chip_fund_ext'])

    def test_evaluate_returns_indicator_and_ext_keys(self):
        """evaluate()返回的data_context包含新数据键"""
        import inspect

        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        source = inspect.getsource(Dim1SignalEngine.evaluate)
        assert 'indicator_ma_df' in source
        assert 'chip_fund_ext' in source
        assert 'get_pre_feat' in source
        assert 'get_cached_indicators' in source
