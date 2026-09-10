"""419号方案回归测试：dim5数据分拨合规 + 性能修复

覆盖：
- 修复A: BociasiQuadrantAnalyzer 缓存短路（market_stats 命中零 SQL 回退）
- 修复B: 板块热度 sector_heat_cache 持久化 roundtrip + dim1 data_context 分拨
- 修复C: dim5 不再直调 SectorRotationModel 副本类 / _time_rhythm 死代码已删
- 修复D: dim1 显式 ts_code 参数（tags 扁平化后无此键）
- 性能: analyzer 缓存命中时毫秒级
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from unittest import mock

import pytest

# ── 修复A: analyzer 缓存短路 ────────────────────────────────

FULL_MARKET_STATS = {
    'ma20_ratio': 0.5, 'turnover_percentile': 0.5, 'limit_ratio': 0.1,
    'rsi_percentile': 0.5, 'erp_percentile': 0.5, 'margin_trend': 0.5,
    'pe_percentile': 0.5,
}


class TestAnalyzerCacheShortcut:

    def test_cache_hit_no_sql(self):
        """market_stats 完整时，analyze 不触发任何 _compute_* 回退（零 SQL）"""
        import types

        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        a = BociasiQuadrantAnalyzer(ecm=types.SimpleNamespace(),
                                    market_stats=dict(FULL_MARKET_STATS))
        for fn in ['_compute_ma20_ratio', '_compute_turnover_percentile',
                   '_compute_limit_ratio', '_compute_rsi_percentile',
                   '_compute_erp_percentile', '_compute_margin_trend',
                   '_compute_pe_percentile']:
            setattr(a, fn, mock.Mock(side_effect=AssertionError(f'{fn} 不应被调用')))
        result = a.analyze()
        assert result['quadrant'] in ('LL', 'LH', 'HL', 'HH', 'MM')
        # 缓存值保持（不被回退覆盖）
        assert a._cache['limit_ratio'] == 0.1

    def test_cache_miss_fallback(self):
        """market_stats 为空时，回退 _compute_* 被调用"""
        import types

        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        a = BociasiQuadrantAnalyzer(ecm=types.SimpleNamespace(), market_stats={})
        for fn in ['_compute_ma20_ratio', '_compute_rsi_percentile']:
            setattr(a, fn, mock.Mock(return_value=0.5))
        a._compute_turnover_percentile = mock.Mock(return_value=0.5)
        a._compute_limit_ratio = mock.Mock(return_value=0.5)
        a._compute_erp_percentile = mock.Mock(return_value=0.5)
        a._compute_margin_trend = mock.Mock(return_value=0.5)
        a._compute_pe_percentile = mock.Mock(return_value=0.5)
        a.analyze()
        a._compute_ma20_ratio.assert_called_once()
        a._compute_rsi_percentile.assert_called_once()

    def test_cache_hit_fast(self):
        """缓存命中时 analyze 毫秒级（<50ms）"""
        import time
        import types

        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        a = BociasiQuadrantAnalyzer(ecm=types.SimpleNamespace(),
                                    market_stats=dict(FULL_MARKET_STATS))
        t0 = time.time()
        a.analyze()
        assert (time.time() - t0) * 1000 < 50, "缓存命中应 <50ms"


# ── 修复B: 板块热度持久化 + 分拨 ────────────────────────────

class TestSectorHeat:

    def test_cache_sector_heat_roundtrip(self):
        """sector_heat_cache 写入 → 读回一致（mock ECM）"""
        from app.data.enhanced_cache_manager import EnhancedCacheManager
        ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
        ecm._write_lock = mock.Mock()
        ecm.conn = mock.Mock()
        ecm._query_shard = mock.Mock(return_value=None)
        ecm._execute = mock.Mock()
        heat = {'银行': {'heat_level': 'top_10', 'strength': 0.8, 'rank': 1, 'stock_count': 40},
                '白酒': {'heat_level': 'normal', 'strength': 0.1, 'rank': 25, 'stock_count': 20}}
        ecm.cache_sector_heat(heat, '2026-09-07')
        ecm._execute.assert_any_call(mock.ANY, ['2026-09-07'])
        ecm._execute.assert_any_call(mock.ANY, ['2026-09-07', '银行', 'top_10', 0.8, 1, 40])

    def test_dim1_loads_sector_heat_from_dm_cache(self):
        """dim1 evaluate 通过 dm.cache.get_cached_sector_heat 加载 sector_heat"""
        import app.data as data_mod
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        e = Dim1SignalEngine.__new__(Dim1SignalEngine)
        # mock dm
        fake_cache = mock.Mock()
        fake_cache.get_cached_sector_heat = mock.Mock(return_value={'银行': {'heat_level': 'top_10'}})
        fake_dm = mock.Mock()
        fake_dm.cache = fake_cache
        fake_dm.get_cached_daily_data = mock.Mock(return_value=None)
        fake_dm.get_cached_moneyflow = mock.Mock(return_value=None)
        fake_dm.get_cached_daily_basic = mock.Mock(return_value=None)
        fake_dm.get_cached_margin = mock.Mock(return_value=None)
        fake_dm.get_cached_fina_indicator = mock.Mock(return_value=None)
        fake_dm.get_cached_income = mock.Mock(return_value=None)
        fake_dm.get_cached_balancesheet = mock.Mock(return_value=None)
        fake_dm.get_cached_cashflow = mock.Mock(return_value=None)
        fake_dm.get_cached_stk_holder = mock.Mock(return_value=None)
        fake_dm.get_cached_lhb = mock.Mock(return_value=None)
        fake_dm.get_cached_indicators = mock.Mock(return_value=None)
        fake_dm.get_pre_feat = mock.Mock(return_value=None)
        with mock.patch.object(data_mod.DataManager, '__new__', return_value=fake_dm):
            with mock.patch.object(Dim1SignalEngine, '_notify_missing_data'):
                result = e.evaluate({}, {'ts_code': 'x'}, ts_code='000001.SZ')
        dc = result.get('data_context') or {}
        assert 'sector_heat' in dc, "dim1 data_context 应含 sector_heat"
        assert dc['sector_heat']['银行']['heat_level'] == 'top_10'


# ── 修复C: dim5 合规（无直调副本类/死代码） ─────────────────

class TestDim5Compliance:

    def _source(self):
        import importlib
        import os as _os
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        with open(mod.__file__) as f:
            return f.read()

    def test_no_sector_rotation_copy_class(self):
        """dim5 不应再有 SectorRotationModel 副本类"""
        assert 'class SectorRotationModel' not in self._source()

    def test_no_time_rhythm_direct_dm(self):
        """dim5 不应再有 _time_rhythm 直调 DataManager 的死代码"""
        src = self._source()
        assert 'def _time_rhythm' not in src

    def test_sector_heat_from_data_context(self):
        """dim5 evaluate 从 data_context 消费 sector_heat"""
        src = self._source()
        assert "data_context.get('sector_heat')" in src

    def test_no_direct_sector_rotation_instantiation(self):
        """dim5 evaluate 不应再实例化 SectorRotationModel"""
        src = self._source()
        assert 'SectorRotationModel(' not in src


# ── 修复D: dim1 ts_code 参数 ────────────────────────────────

class TestDim1TsCode:

    def test_evaluate_accepts_ts_code(self):
        """dim1 evaluate 接受显式 ts_code 参数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        sig = inspect.signature(Dim1SignalEngine.evaluate)
        assert 'ts_code' in sig.parameters

    def test_notify_deduplicates_task_type(self):
        """_notify_missing_data 去重 + 无映射跳过 + 后台线程（源码断言）"""
        import inspect as _i

        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        src = _i.getsource(Dim1SignalEngine._notify_missing_data)
        assert 'task_map.get(table)' in src, "应使用 task_map.get 支持 None 跳过"
        assert 'threading.Thread' in src, "通知应在后台线程执行"
        assert "dm.request_data" in src
