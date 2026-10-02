"""506号：RAW 预计算管道性能缺陷修复验证

根因（2026-10-02 只读诊断）：
  RAW-2 逐股路径 `_raw2_one → PhaseDetectionEngine.compute_tags → ChipIndicators()`
  → `ChipDistributionService()` → **非单例 `EnhancedCacheManager()`**，每次构造
  跑 `_init_tables()`（全量 DDL + 5 连接 + 34 表空壳扫描）→ 全市场 ≈5559 次/轮
  （日志「总库空壳表自清理」10-01 共 8379 次）；次因 `_precompute_market_stats`
  每 tick 重跑（10-01 218 次）；后果：单只 0.34s→2.4~9s、tick 30s→95s、
  factor_cache 09-30 distinct 恒 4126 不涨（无断点续算）。

覆盖 5 项修复：
  F1 `_init_tables` 按 db_path 幂等；F2 非单例默认构造改单例；
  F3 market_stats 当日节流；F4 删死代码 `_run_trading_phase_detector`；
  F5 RAW-2/3 断点续算（跳过已有当日行）。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_daemon as dd  # noqa: E402
import pytest  # noqa: E402


# ── F1：_init_tables 按 db_path 幂等 ──────────────────────────

def test_f1_init_tables_once_per_dbpath(tmp_path, monkeypatch):
    """同一库文件多次构造 ECM，_init_tables 只执行一次"""
    import app.data.enhanced_cache_manager as E

    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setattr(E, '_tables_initialized_paths', set())
    calls = {'n': 0}
    orig = E.EnhancedCacheManager._init_tables

    def _counting(self):
        calls['n'] += 1
        return orig(self)

    monkeypatch.setattr(E.EnhancedCacheManager, '_init_tables', _counting)
    e1 = E.EnhancedCacheManager()
    e2 = E.EnhancedCacheManager()
    e3 = E.EnhancedCacheManager()
    assert calls['n'] == 1, '同库第二个实例起应跳过 _init_tables'
    assert e1.db_path == e2.db_path == e3.db_path


# ── F2：非单例默认构造改单例 ──────────────────────────────────

def test_f2_chip_service_default_uses_singleton(tmp_path, monkeypatch):
    """ChipDistributionService 默认 cache_manager 为全局单例（曾逐股新建 ECM）"""
    import app.data.enhanced_cache_manager as E
    from app.data.chip_distribution_service import ChipDistributionService

    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setattr(E, '_ecm_instance', None)
    a = ChipDistributionService()
    b = ChipDistributionService()
    assert a.cache_manager is b.cache_manager, '多次构造应共享同一 ECM'
    assert a.cache_manager is E.get_ecm_instance()
    assert a.cache_manager is not None


def test_f2_factor_manager_default_uses_singleton(tmp_path, monkeypatch):
    """FactorPrecomputeManager 默认 cache_manager 为全局单例"""
    import app.data.enhanced_cache_manager as E
    from app.data.factor_precompute import FactorPrecomputeManager

    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setattr(E, '_ecm_instance', None)
    assert FactorPrecomputeManager().cache_manager is E.get_ecm_instance()


# ── F3：market_stats 当日节流 ─────────────────────────────────

class _FakeECM:
    def __init__(self):
        self.persisted = []

    def cache_market_stats(self, stats):
        self.persisted.append(dict(stats))


GOOD_SHARD_ROWS = {
    'SMA_20': [(100, 60)],
    'turnover_rate': [(0.05,), (0.08,)],
    'high_limit': [(5, 2)],
    'rsi14': [(55.0,), (50.0,)],
    'pe_ttm) AS pe FROM (': [('2026-09-01', 12.0), ('2026-09-10', 15.0)],
    'pe_ttm': [(15.0,), (12.0,)],
    'rzye': [('2026-09-10', 110.0), ('2026-09-09', 100.0),
             ('2026-09-08', 95.0), ('2026-09-07', 90.0), ('2026-09-06', 85.0)],
}


def _fake_dispatcher(rows_by_fragment):
    def _fake(table, sql, params=None):
        for frag, rows in rows_by_fragment.items():
            if frag in sql:
                return rows
        return []
    return _fake


def test_f3_market_stats_throttled_per_day(monkeypatch):
    """同一目标交易日重复调用 → 第二次直接跳过（不重复落库）"""
    fake_ecm = _FakeECM()
    monkeypatch.setattr(dd, '_ensure_ecm', lambda: None)
    monkeypatch.setattr(dd, '_ecm', fake_ecm)
    monkeypatch.setattr(dd, '_market_stats_cache', {})
    monkeypatch.setattr(dd, '_market_stats_last_done_date', None)
    monkeypatch.setattr(dd, '_shard_fetchall', _fake_dispatcher(GOOD_SHARD_ROWS))
    import app.data.sharding_manager as sm
    monkeypatch.setattr(sm.sharding_manager, 'get_table_row_count', lambda t: 1000)

    dd._precompute_market_stats(target_date='2026-09-10')
    dd._precompute_market_stats(target_date='2026-09-10')
    assert len(fake_ecm.persisted) == 1, '同日第二次应被节流跳过'

    # force=True 强制重算
    dd._precompute_market_stats(target_date='2026-09-10', force=True)
    assert len(fake_ecm.persisted) == 2, 'force=True 应绕过节流'

    # 不同日期 → 不受节流影响
    fake_ecm.persisted.clear()
    monkeypatch.setattr(dd, '_market_stats_last_done_date', '2026-09-09')
    dd._precompute_market_stats(target_date='2026-09-10')
    assert len(fake_ecm.persisted) == 1, '新日期应正常计算'


def test_f3_source_has_throttle_guard():
    """源码断言：_precompute_market_stats 含当日节流早退"""
    src = inspect.getsource(dd._precompute_market_stats)
    assert '_market_stats_last_done_date' in src
    assert 'force' in src


# ── F4：死代码 _run_trading_phase_detector 已删除 ─────────────

def test_f4_dead_trading_phase_detector_removed():
    from app.opportunity_atlas.phase_detector import PhaseDetectionEngine
    assert not hasattr(PhaseDetectionEngine, '_run_trading_phase_detector'), \
        '死代码 _run_trading_phase_detector 应已删除'
    assert hasattr(PhaseDetectionEngine, '_run_trading_phase_detector_v2'), \
        'live 路径 _run_trading_phase_detector_v2 应保留'


# ── F5：RAW-2/3 断点续算 ──────────────────────────────────────

def test_f5_raw3_source_has_resume_skip():
    src = inspect.getsource(dd._precompute_preset_combos)
    assert '断点续算' in src
    assert 'factor_cache' in src


def test_f5_raw2_source_has_resume_skip():
    src = inspect.getsource(dd._precompute_raw_features)
    assert '断点续算' in src
    assert 'pre_feat_cache' in src


def test_f5_raw3_skips_done_stocks(monkeypatch):
    """RAW-3：已存在当日因子的股票被跳过（只对缺口股票调用单只计算）"""
    def _fake_fetch(table, sql, params=None):
        if table == 'daily_cache':
            return [('2026-09-30',)]
        if table == 'factor_cache':
            return [('000001.SZ',), ('000002.SZ',)]
        return []

    monkeypatch.setattr(dd, '_shard_fetchall', _fake_fetch)
    monkeypatch.setattr(dd, '_ensure_ecm', lambda: None)

    class _FakeECM:
        def get_cached_daily(self, code):
            return None  # len<30 → 'skip'，但仍逐只调用

    monkeypatch.setattr(dd, '_ecm', _FakeECM())

    seen = []
    monkeypatch.setattr(dd, '_run_with_timeout',
                        lambda func, timeout_sec=30.0, desc='': seen.append(desc))

    dd._precompute_preset_combos(['000001.SZ', '000002.SZ', '600000.SH'])
    # 已完成两只是否被跳过：只剩 600000.SH 进入单只计算
    assert any('600000.SH' in d for d in seen)
    assert not any('000001.SZ' in d for d in seen), '已完成股票不应重复计算'
    assert not any('000002.SZ' in d for d in seen), '已完成股票不应重复计算'
