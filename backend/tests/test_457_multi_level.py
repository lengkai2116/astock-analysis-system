"""457号：dim2 多周期级联接线（445 §6.1 dim2「级别定理/多周期联立」处置）

三决策（user 拍板）：
- 接入层级：StatusEngine data_context 层（dim1 loader 注入 weekly_df/hourly_df，dim2 消费）
- 配置接线：对齐 bi_zs_mode（各级别统一线段中枢，dim2 日线 446 号意图）
- 缓存串味：本次修复（缓存键加入 ts_code + 最新交易日）

覆盖：
1. MultiLevelConfig 默认 bi_zs_mode=False（对齐）+ enabled 开关
2. chanlun_multi_level 缓存键含 ts_code 与最新交易日（不同行数/股票不串味）
3. multi_level.enabled=False 时正确降级
4. dim1 loader 注入 weekly_df/hourly_df 进 data_context
5. dim2 evaluate 接线：multi_level/multi_level_direction_text 契约键产出 + 降级兜底
6. 各级别分析器统一走线段中枢（bi_zs_mode 对齐）
"""
import logging
from unittest import mock

import numpy as np
import pandas as pd
from app.engine.framework import chanlun_multi_level as cml
from app.engine.framework import chanlun_strategy as _cs
from app.engine.framework.chanlun_config import MultiLevelConfig
from app.engine.framework.chanlun_multi_level import MultiLevelChanlunAnalyzer
from app.opportunity_atlas.dimensions import dim2_structure_engine
from app.opportunity_atlas.dimensions.dim2_structure_engine import Dim2StructureEngine

logging.disable(logging.CRITICAL)

# 避免框架 analyze() 读预计算 MACD 表（DB 依赖，434 autouse mock 先例）——
# 框架内部 ChanlunAnalyzer.analyze -> _load_precomputed_macd（chanlun_strategy 模块级）。
_patch_precompute = mock.patch.object(_cs, '_load_precomputed_macd', lambda *a, **k: {})


def make_klines(rows=260, seed=42, trade_date_col=True):
    """趋势清晰的数据（可形成缠论结构），沿用 test_chanlun 样式。"""
    np.random.seed(seed)
    base = 10.0
    n = rows // 5
    a = np.linspace(0, 2, n)
    A = np.sin(np.linspace(0, 2 * np.pi, n)) * 0.5 + np.ones(n) * 2
    b = np.linspace(2, 4, n)
    B = np.sin(np.linspace(0, 2 * np.pi, n)) * 0.5 + np.ones(n) * 4
    c = np.linspace(4, 6, rows - 4 * n)
    t = np.concatenate([a, A, b, B, c])
    prices = base + t + np.random.randn(rows) * 0.05
    dates = pd.date_range('2024-01-01', periods=rows, freq='B').strftime('%Y%m%d')
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'] * rows,
        'trade_date': dates,
        'open': prices + np.random.randn(rows) * 0.05,
        'high': prices + np.abs(np.random.randn(rows)) * 0.1 + 0.02,
        'low': prices - np.abs(np.random.randn(rows)) * 0.1 - 0.02,
        'close': prices,
        'vol': np.random.randint(500000, 2000000, rows),
    })
    if not trade_date_col:
        df = df.drop(columns=['trade_date'])
    return df


class TestMultiLevelConfig:
    def test_default_bi_zs_mode_false(self):
        """457号：多级别联立默认走线段中枢（对齐 dim2 日线 446 号意图）。"""
        assert MultiLevelConfig().enabled is True
        assert MultiLevelConfig().bi_zs_mode is False

    def test_default_levels(self):
        assert MultiLevelConfig().levels == ('weekly', 'daily', 'hourly')


class TestCacheKey:
    def test_cache_key_includes_ts_and_date(self):
        """缓存键含 ts_code + 最新交易日 + level + 行数（消除仅行数串味）。"""
        analyzer = MultiLevelChanlunAnalyzer()
        # 通过 monkeypatch 捕获实际生成的 cache_key
        captured = {}

        def fake_get(key, layer):
            captured['key'] = key
            return None

        def fake_set(key, val, layer):
            captured['set_key'] = key

        with mock.patch.object(analyzer._cache, 'get', fake_get), \
                mock.patch.object(analyzer._cache, 'set', fake_set), \
                _patch_precompute:
            analyzer.analyze({'daily': make_klines(rows=60, seed=1)})
        key = captured.get('key', '')
        assert '000001.SZ' in key, f"缓存键应含 ts_code，got: {key}"
        # 断言最新交易日（trade_date %Y%m%d 串）出现在键上
        assert ':2024' in key or ':2025' in key, f"键应含日期信息: {key}"

    def test_cache_key_not_shared_across_stocks(self):
        """不同股票（不同 ts_code）即使行数相同，缓存键也须不同。"""
        def _key_for(df):
            analyzer = MultiLevelChanlunAnalyzer()
            captured = {}
            def fake_get(k, layer):
                captured['key'] = k
                return None
            def fake_set(k, v, layer):
                captured['set_key'] = k
            with mock.patch.object(analyzer._cache, 'get', fake_get), \
                    mock.patch.object(analyzer._cache, 'set', fake_set), \
                    _patch_precompute:
                analyzer.analyze({'daily': df})
            return captured.get('key', '')

        k1 = _key_for(make_klines(rows=60, seed=1))
        df2 = make_klines(rows=60, seed=1)
        df2['ts_code'] = ['600000.SH'] * len(df2)
        k2 = _key_for(df2)
        assert k1 != k2, "不同股票缓存键不应相等"


class TestDisabledConfig:
    def test_disabled_returns_graceful(self):
        """multi_level.enabled=False → 优雅降级，不抛异常。"""
        from app.engine.framework.chanlun_config import ChanlunConfig
        cfg = ChanlunConfig.default()
        cfg.multi_level.enabled = False
        analyzer = MultiLevelChanlunAnalyzer(config=cfg)
        with _patch_precompute:
            r = analyzer.analyze({'daily': make_klines(rows=60, seed=1)})
        assert r.get('enabled') is False
        assert r.get('levels') == {}
        assert 'direction_text' in r


class TestBiZsModeAlignment:
    def test_default_config_propagates_bi_zs_mode_false(self):
        """对齐 bi_zs_mode：默认 ChanlunConfig.multi_level.bi_zs_mode=False →
        ChanlunAnalyzer 实例 bi_zs_mode=False（各级别走线段中枢）。"""
        from app.engine.framework.chanlun_config import ChanlunConfig
        from app.engine.framework.chanlun_strategy import ChanlunAnalyzer

        cfg = ChanlunConfig.default()
        a = ChanlunAnalyzer(config=cfg)
        assert a.bi_zs_mode is False

    def test_multi_level_analyzer_passes_config_to_each_level(self):
        """MultiLevelChanlunAnalyzer 内部用同一 ChanlunConfig 实例分析各级别（对齐 bi_zs_mode）。"""
        analyzer = MultiLevelChanlunAnalyzer()
        # 验证 config.multi_level.bi_zs_mode=False（各级别统一线段中枢，dim2 意图）
        assert analyzer.config.multi_level.bi_zs_mode is False


class TestDim1LoaderInjection:
    def test_loader_injects_weekly_and_hourly(self):
        """dim1 loader 注入 weekly_df/hourly_df 进 data_context。"""
        from app.opportunity_atlas.dimensions import dim1_signal_engine

        dm = mock.Mock()
        dm.get_cached_daily_data.return_value = make_klines(rows=100, seed=1)
        dm.get_kline_data = mock.Mock(side_effect=lambda ts, period: {
            'W': make_klines(rows=60, seed=2),
            '60m': make_klines(rows=120, seed=3),
        }.get(period, pd.DataFrame()))
        dm.get_cached_moneyflow.return_value = pd.DataFrame()
        dm.get_cached_daily_basic.return_value = pd.DataFrame()
        dm.get_cached_margin.return_value = pd.DataFrame()
        dm.get_cached_fina_indicator.return_value = pd.DataFrame()
        dm.get_cached_income.return_value = pd.DataFrame()
        dm.get_cached_balancesheet.return_value = pd.DataFrame()
        dm.get_cached_cashflow.return_value = pd.DataFrame()
        dm.get_cached_stk_holder.return_value = pd.DataFrame()
        dm.get_cached_lhb.return_value = pd.DataFrame()
        dm.get_cached_indicators.return_value = pd.DataFrame()
        dm.cache = mock.Mock()
        dm.cache.get_cached_sector_heat.return_value = None
        dm.cache.get_relative_strength.return_value = None

        engine = dim1_signal_engine.Dim1SignalEngine()
        # 屏蔽 _notify_missing_data（DB 写）；loader 内部 `from app.data import DataManager`，Patch app.data.DataManager
        import app.data
        with mock.patch.object(dim1_signal_engine.Dim1SignalEngine, '_notify_missing_data'), \
                mock.patch.object(app.data, 'DataManager', return_value=dm):
            out = engine.evaluate({}, {}, ts_code='000001.SZ')
        ctx = out.get('data_context')
        assert 'weekly_df' in ctx, "应注入 weekly_df"
        assert 'hourly_df' in ctx, "应注入 hourly_df"

    def test_loader_degrades_when_weekly_missing(self):
        """周线缺失不阻塞主链（降级单级别）。"""
        from app.opportunity_atlas.dimensions import dim1_signal_engine

        dm = mock.Mock()
        dm.get_cached_daily_data.return_value = make_klines(rows=100, seed=1)
        dm.get_kline_data = mock.Mock(return_value=pd.DataFrame())
        dm.get_cached_moneyflow.return_value = pd.DataFrame()
        dm.get_cached_daily_basic.return_value = pd.DataFrame()
        dm.get_cached_margin.return_value = pd.DataFrame()
        dm.get_cached_fina_indicator.return_value = pd.DataFrame()
        dm.get_cached_income.return_value = pd.DataFrame()
        dm.get_cached_balancesheet.return_value = pd.DataFrame()
        dm.get_cached_cashflow.return_value = pd.DataFrame()
        dm.get_cached_stk_holder.return_value = pd.DataFrame()
        dm.get_cached_lhb.return_value = pd.DataFrame()
        dm.get_cached_indicators.return_value = pd.DataFrame()
        dm.cache = mock.Mock()
        dm.cache.get_cached_sector_heat.return_value = None
        dm.cache.get_relative_strength.return_value = None

        engine = dim1_signal_engine.Dim1SignalEngine()
        # 屏蔽 _notify_missing_data 的 DB 写（同 test_loader_injects_weekly_and_hourly 理由）
        import app.data
        with mock.patch.object(dim1_signal_engine.Dim1SignalEngine, '_notify_missing_data'), \
                mock.patch.object(app.data, 'DataManager', return_value=dm):
            out = engine.evaluate({}, {}, ts_code='000001.SZ')
        ctx = out.get('data_context')
        assert 'weekly_df' not in ctx
        assert 'daily_df' in ctx, "日线主链不受影响"


class TestDim2EvaluateWiring:
    def _eval(self, data_context):
        eng = Dim2StructureEngine()
        tags = {'ts_code': '000001.SZ', 'ma_alignment': '多头排列',
                'indicator_status': 'ma=bullish', 'chip_concentration': 'concentrating',
                'profit_ratio': 0.5, 'rsi_percentile': 0.7, 'position_vs_zs': '上方'}
        with _patch_precompute:
            out = eng.evaluate({}, tags, data_context=data_context)
        return out['status_description']

    def test_multi_level_keys_present(self):
        """齐全数据 → multi_level dict + direction_text 契约键产出。"""
        sd = self._eval({
            'daily_df': make_klines(rows=260, seed=1),
            'weekly_df': make_klines(rows=130, seed=2),
            'hourly_df': make_klines(rows=160, seed=3),
        })
        ml = sd.get('multi_level')
        assert isinstance(ml, dict), f"应产 multi_level dict, got {type(ml)}"
        assert 'direction_text' in ml
        assert 'direction_map' in ml
        assert 'near_levels' in ml
        assert 'levels' in ml
        assert isinstance(sd.get('multi_level_direction_text'), str)

    def test_daily_only_degrades(self):
        """仅日线 → 仍产 multi_level（含 daily），方向文本走单级别/无跨级兜底。"""
        sd = self._eval({'daily_df': make_klines(rows=260, seed=1)})
        ml = sd.get('multi_level')
        assert isinstance(ml, dict), "仅日线也应产 multi_level"
        assert list(ml.get('levels', {}).keys()) == ['daily']
        assert sd.get('multi_level_direction_text')

    def test_no_data_context(self):
        """无 data_context → multi_level 键缺省不产 dict（保持空壳语义），不抛异常。"""
        eng = Dim2StructureEngine()
        # 无 data_context 时 evaluate 走 _get_dm().cache 读日线——注入 mock，避免 DB 依赖。
        dm = mock.Mock()
        dm.cache.get_cached_daily.return_value = None
        eng._dm = dm
        sd = eng.evaluate({}, {'ts_code': '000001.SZ'}, data_context=None)['status_description']
        assert 'multi_level' in sd

    def test_full_chain_real_run(self):
        """真实数据全链路跑通：完整 status_description/judgment/audit。"""
        eng = Dim2StructureEngine()
        eng._dm = mock.Mock()  # 全链路 data_context 已含 daily/weekly/hourly，不触发 DB 读取
        tags = {'ts_code': '000001.SZ', 'ma_alignment': '多头排列',
                'indicator_status': 'ma=bullish', 'position_vs_zs': '上方'}
        with _patch_precompute:
            out = eng.evaluate({}, tags, data_context={
                'daily_df': make_klines(rows=260, seed=1),
                'weekly_df': make_klines(rows=130, seed=2),
                'hourly_df': make_klines(rows=160, seed=3),
            })
        assert 'status_description' in out
        assert 'judgment' in out
        assert 'audit' in out
        assert out['audit']['total_count'] == 5
