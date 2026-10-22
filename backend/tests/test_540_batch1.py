"""540号 批次1 定向测试。

覆盖：
- P1-1：`value/opportunity` 支持显式 `ts_codes`，缓存键纳入 `ts_codes`；
- P1-2：market 股票池优先取活跃股票（含北交所），不再被 5000 截断；
- P1-4：`get_tags()` 每标签返回最新值（不再被最旧行覆盖）。
"""
import sqlite3

import pandas as pd
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.routes.opportunity_atlas import _collect_ts_codes, _treemap_cache_key


class _FakeCache:
    def __init__(self, active=None, tag_codes=None, snapshot_codes=None):
        self.active = active or []
        self.tag_codes = tag_codes or []
        self.snapshot_codes = snapshot_codes or []

    def get_all_active_codes(self):
        return list(self.active)

    def get_treemap_snapshot_codes(self):
        return list(self.snapshot_codes)

    def query_tags(self, tag_filters):
        return [{'ts_code': c} for c in self.tag_codes]


class _FakeDM:
    def __init__(self, active=None, tag_codes=None, snapshot_codes=None):
        self.cache = _FakeCache(active, tag_codes, snapshot_codes)
        self.last_limit = None

    def get_all_ts_codes(self, limit=5000):
        self.last_limit = limit
        return ['000001.SZ', '920001.BJ']


# ══════════════════════════════════════════════════════════
# P1-1 缓存键 / 显式 ts_codes
# ══════════════════════════════════════════════════════════

def test_cache_key_includes_ts_codes_and_normalizes_order():
    base = _treemap_cache_key('value')
    one = _treemap_cache_key('value', '', '', '000002.SZ')
    assert one != base
    assert one == _treemap_cache_key('value', '', '', ' 000002.SZ ')
    assert _treemap_cache_key('value', '', '', 'B.SZ,A.SZ') == \
        _treemap_cache_key('value', '', '', 'A.SZ,B.SZ')


def test_value_with_ts_codes_returns_only_requested_stock():
    dm = _FakeDM(tag_codes=['000002.SZ', '600000.SH'])
    codes = _collect_ts_codes('value', dm, '000002.SZ', '')
    assert codes == ['000002.SZ']


def test_opportunity_with_ts_codes_returns_only_requested_stock():
    dm = _FakeDM(tag_codes=['000002.SZ', '600000.SH'])
    codes = _collect_ts_codes('opportunity', dm, '000002.SZ', '')
    assert codes == ['000002.SZ']


def test_value_with_tags_intersects_explicit_codes():
    dm = _FakeDM(tag_codes=['000002.SZ', '600000.SH'])
    codes = _collect_ts_codes('value', dm, '000002.SZ', 'valuation_level:low')
    assert codes == ['000002.SZ']


# ══════════════════════════════════════════════════════════
# P1-2 市场股票池
# ══════════════════════════════════════════════════════════

def test_market_uses_snapshot_codes_including_suspended_and_bj():
    dm = _FakeDM(
        active=['000001.SZ'],
        snapshot_codes=['000001.SZ', '601326.SH', '920001.BJ'],
    )
    codes = _collect_ts_codes('market', dm, '', '')
    assert codes == ['000001.SZ', '601326.SH', '920001.BJ']
    assert dm.last_limit is None


def test_market_falls_back_to_active_codes_then_full_list():
    dm = _FakeDM(active=['000001.SZ', '920001.BJ'], snapshot_codes=[])
    assert _collect_ts_codes('market', dm, '', '') == ['000001.SZ', '920001.BJ']
    assert dm.last_limit is None

    dm2 = _FakeDM(active=[], snapshot_codes=[])
    assert _collect_ts_codes('market', dm2, '', '') == ['000001.SZ', '920001.BJ']
    assert dm2.last_limit == 10000


def test_market_explicit_ts_codes_still_honored():
    dm = _FakeDM(active=['000001.SZ'])
    assert _collect_ts_codes('market', dm, '600000.SH', '') == ['600000.SH']


# ══════════════════════════════════════════════════════════
# P1-4 get_tags 取最新值
# ══════════════════════════════════════════════════════════

def test_get_tags_returns_latest_per_tag(monkeypatch, tmp_path):
    db = tmp_path / 'tags.db'
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE opportunity_tags_cache ("
        "id INTEGER PRIMARY KEY, ts_code TEXT, tag_name TEXT, tag_value TEXT, "
        "tag_group TEXT, confidence REAL, source TEXT, updated_at TEXT)"
    )
    rows = [
        (1, '000001.SZ', 'valuation_level', 'low', 'valuation', None, None, '2026-08-18'),
        (2, '000001.SZ', 'valuation_level', 'fair', 'valuation', None, None, '2026-08-19'),
        (3, '000001.SZ', 'main_force_phase', 'washing', 'depth', None, None, '2026-08-18'),
        (4, '000001.SZ', 'main_force_phase', 'unknown', 'depth', None, None, '2026-08-19'),
        # 同一 updated_at，id 更大者应胜出
        (5, '000001.SZ', 'sentiment_phase', 'recovery', 'sentiment', None, None, '2026-08-19'),
        (6, '000001.SZ', 'sentiment_phase', 'ebb', 'sentiment', None, None, '2026-08-19'),
        # 其他股票不得串入
        (7, '000002.SZ', 'valuation_level', 'high', 'valuation', None, None, '2026-08-19'),
    ]
    con.executemany(
        "INSERT INTO opportunity_tags_cache VALUES (?,?,?,?,?,?,?,?)", rows
    )
    con.commit()

    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)

    def fake_query_shard(table, sql, params=None):
        if table != 'opportunity_tags_cache':
            return pd.DataFrame()
        return pd.read_sql_query(sql, con, params=params)

    monkeypatch.setattr(ecm, '_query_shard', fake_query_shard)

    tags = ecm.get_tags('000001.SZ')
    assert tags['valuation_level'] == 'fair'
    assert tags['main_force_phase'] == 'unknown'
    assert tags['sentiment_phase'] == 'ebb'
    # 540号批次2：get_tags 追加 JUD signal_strength（快照无行 → None）
    assert tags['signal_strength'] is None
    assert len(tags) == 4
    con.close()
