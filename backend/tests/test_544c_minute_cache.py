"""544-C：60m 批量预取内存缓存测试（假分库连接，不触库）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.data import enhanced_cache_manager as em  # noqa: E402


@pytest.fixture()
def ecm(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    (tmp_path / 'duckdb').mkdir()
    em._tables_initialized_paths.add(str(tmp_path / 'duckdb' / 'stock_cache.db'))
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def _frame():
    return pd.DataFrame({
        'ts_code': ['A', 'A', 'B', 'B'],
        'freq': ['60min'] * 4,
        'trade_date': ['2026-10-21', '2026-10-22', '2026-10-21', '2026-10-22'],
        'trade_time': ['2026-10-21 15:00', '2026-10-22 15:00',
                       '2026-10-21 15:00', '2026-10-22 15:00'],
        'close': [10.0, 11.0, 20.0, 21.0],
    })


def _patch_prime(monkeypatch, frame):
    from app.data import sharding_manager as sm
    monkeypatch.setattr(sm.sharding_manager, 'get_db_for_table',
                        lambda table: 'market_cache.db')
    monkeypatch.setattr(sm.sharding_manager, 'get_read_connection',
                        lambda db: object())
    monkeypatch.setattr(pd, 'read_sql_query',
                        lambda sql, conn, params=None: frame)


def test_prime_and_hit(ecm, monkeypatch):
    _patch_prime(monkeypatch, _frame())
    n = ecm.prime_minute_cache(['A', 'B'], freq='60min')
    assert n == 2
    out = ecm.get_cached_minute_kline('A', freq='60min')
    assert len(out) == 2
    one = ecm.get_cached_minute_kline('A', trade_date='2026-10-22', freq='60min')
    assert len(one) == 1 and one.iloc[0]['close'] == 11.0


def test_codes_filter(ecm, monkeypatch):
    _patch_prime(monkeypatch, _frame())
    n = ecm.prime_minute_cache(['A'], freq='60min')
    assert n == 1
    assert ('B', '60min') not in ecm._minute_cache


def test_clear_and_ttl_fallback(ecm, monkeypatch):
    _patch_prime(monkeypatch, _frame())
    ecm.prime_minute_cache(['A'], freq='60min')
    ecm.clear_minute_cache()
    monkeypatch.setattr(ecm, '_query_shard', lambda *a, **k: pd.DataFrame())
    out = ecm.get_cached_minute_kline('A', freq='60min')
    assert out is None or out.empty
