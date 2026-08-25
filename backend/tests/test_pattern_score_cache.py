"""测试形态评分缓存（353/358号方案）"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
import sqlite3
import json
import tempfile

from app.data.enhanced_cache_manager import EnhancedCacheManager


@pytest.fixture
def ecm(tmp_path):
    """创建使用临时数据库的 EnhancedCacheManager 实例"""
    # 备份原始 __init__，替换数据库路径
    db_path = str(tmp_path / 'test_cache.db')
    compute_db_path = str(tmp_path / 'test_compute_cache.db')

    # 直接创建 ECM 实例并替换其连接（避免真实数据库锁）
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    import threading
    ecm._lock = threading.RLock()
    ecm._write_lock = threading.RLock()
    ecm._snapshot_write_lock = threading.RLock()

    class _FakeMC:
        def get(self, *a, **k): return None
        def put(self, *a, **k): pass
        def invalidate(self, *a, **k): pass
    ecm.memory_cache = _FakeMC()

    ecm.db_path = db_path
    ecm.conn = sqlite3.connect(db_path)
    ecm.conn.execute("PRAGMA journal_mode=WAL")
    ecm.read_conn = sqlite3.connect(db_path)
    ecm.read_conn.execute("PRAGMA journal_mode=WAL")

    # 356号方案：计算分库连接
    ecm.compute_db_path = compute_db_path
    ecm.compute_conn = sqlite3.connect(compute_db_path)
    ecm.compute_conn.execute("PRAGMA journal_mode=WAL")
    ecm.compute_read_conn = sqlite3.connect(compute_db_path)
    ecm.compute_read_conn.execute("PRAGMA journal_mode=WAL")

    # 建表（主库）
    ecm.conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_score_cache (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            score REAL NOT NULL,
            details_json TEXT NOT NULL,
            computed_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (ts_code, trade_date)
        )
    """)
    ecm.conn.commit()

    # 建表（计算分库）
    ecm.compute_conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_score_cache (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            score REAL NOT NULL,
            details_json TEXT NOT NULL,
            computed_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (ts_code, trade_date)
        )
    """)
    ecm.compute_conn.commit()

    ecm.cache_stats = {'hits_duckdb': 0, 'misses': 0, 'total_requests': 0}
    yield ecm
    ecm.conn.close()
    ecm.read_conn.close()
    ecm.compute_conn.close()
    ecm.compute_read_conn.close()


@pytest.fixture
def sample_score():
    """样本评分数据"""
    return 7.5, {
        'bull_count': 3,
        'bear_count': 1,
        'bull_strength_avg': 0.75,
        'bear_strength_avg': 0.3,
        'pattern_count': 4,
        'patterns': [
            {'name': 'P-1-1', 'direction': 'bullish', 'strength': 0.8},
            {'name': 'P-1-3', 'direction': 'bullish', 'strength': 0.7},
            {'name': 'P-3-1', 'direction': 'bullish', 'strength': 0.75},
            {'name': 'P-2-1', 'direction': 'bearish', 'strength': 0.3},
        ]
    }


class TestCachePatternScore:
    """测试 cache_pattern_score 方法"""

    def test_cache_and_retrieve(self, ecm, sample_score):
        """缓存后能取回完整数据"""
        score, details = sample_score
        ts_code = '000001.SZ'
        trade_date = '2025-08-15'

        ecm.cache_pattern_score(ts_code, trade_date, score, details)

        result = ecm.get_pattern_score(ts_code, trade_date)
        assert result is not None
        assert result['score'] == score
        assert result['details']['bull_count'] == 3
        assert result['details']['pattern_count'] == 4
        assert len(result['details']['patterns']) == 4

    def test_cache_upsert(self, ecm):
        """同一 (ts_code, trade_date) 重复写入应覆盖"""
        ts_code = '000001.SZ'
        trade_date = '2025-08-15'

        ecm.cache_pattern_score(ts_code, trade_date, 5.0, {'bull_count': 0})
        ecm.cache_pattern_score(ts_code, trade_date, 8.0, {'bull_count': 5})

        result = ecm.get_pattern_score(ts_code, trade_date)
        assert result is not None
        assert result['score'] == 8.0
        assert result['details']['bull_count'] == 5

    def test_cache_different_dates(self, ecm):
        """不同日期的缓存互不干扰"""
        ts_code = '000001.SZ'

        ecm.cache_pattern_score(ts_code, '2025-08-14', 3.0, {'bear_count': 2})
        ecm.cache_pattern_score(ts_code, '2025-08-15', 7.0, {'bull_count': 3})

        r1 = ecm.get_pattern_score(ts_code, '2025-08-14')
        r2 = ecm.get_pattern_score(ts_code, '2025-08-15')
        assert r1['score'] == 3.0
        assert r2['score'] == 7.0

    def test_cache_different_stocks(self, ecm):
        """不同股票的缓存互不干扰"""
        trade_date = '2025-08-15'

        ecm.cache_pattern_score('000001.SZ', trade_date, 6.0, {})
        ecm.cache_pattern_score('600000.SH', trade_date, 4.0, {})

        assert ecm.get_pattern_score('000001.SZ', trade_date)['score'] == 6.0
        assert ecm.get_pattern_score('600000.SH', trade_date)['score'] == 4.0


class TestGetPatternScore:
    """测试 get_pattern_score 方法"""

    def test_get_nonexistent_returns_none(self, ecm):
        """不存在的缓存返回 None"""
        result = ecm.get_pattern_score('999999.SZ', '2025-01-01')
        assert result is None

    def test_get_latest_when_no_date(self, ecm, sample_score):
        """不指定日期时返回最新缓存"""
        score, details = sample_score
        ts_code = '000001.SZ'

        ecm.cache_pattern_score(ts_code, '2025-08-10', 4.0, {'old': True})
        ecm.cache_pattern_score(ts_code, '2025-08-15', score, details)

        result = ecm.get_pattern_score(ts_code)
        assert result is not None
        assert result['score'] == score

    def test_details_is_dict(self, ecm):
        """返回的 details 应该是 dict 类型"""
        ts_code = '000001.SZ'
        trade_date = '2025-08-15'
        details = {'patterns': [{'name': 'P-1-1', 'strength': 0.8}]}

        ecm.cache_pattern_score(ts_code, trade_date, 6.5, details)

        result = ecm.get_pattern_score(ts_code, trade_date)
        assert isinstance(result['details'], dict)
        assert result['details']['patterns'][0]['name'] == 'P-1-1'

    def test_score_is_float(self, ecm):
        """返回的 score 应该是 float"""
        ts_code = '000001.SZ'
        trade_date = '2025-08-15'

        ecm.cache_pattern_score(ts_code, trade_date, 5.0, {})

        result = ecm.get_pattern_score(ts_code, trade_date)
        assert isinstance(result['score'], float)


class TestHasPatternScore:
    """测试 has_pattern_score 方法"""

    def test_has_when_exists(self, ecm):
        """存在缓存时返回 True"""
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', 5.0, {})
        assert ecm.has_pattern_score('000001.SZ', '2025-08-15') is True

    def test_has_when_not_exists(self, ecm):
        """不存在缓存时返回 False"""
        assert ecm.has_pattern_score('999999.SZ', '2025-01-01') is False


class TestEdgeCases:
    """边界条件测试"""

    def test_score_zero(self, ecm):
        """评分为 0 的情况"""
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', 0.0, {'bear_count': 10})
        result = ecm.get_pattern_score('000001.SZ', '2025-08-15')
        assert result['score'] == 0.0

    def test_score_ten(self, ecm):
        """评分为 10 的情况"""
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', 10.0, {'bull_count': 10})
        result = ecm.get_pattern_score('000001.SZ', '2025-08-15')
        assert result['score'] == 10.0

    def test_empty_details(self, ecm):
        """空 details 字典"""
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', 5.0, {})
        result = ecm.get_pattern_score('000001.SZ', '2025-08-15')
        assert result['details'] == {}

    def test_nested_details_preserved(self, ecm):
        """嵌套结构的 details 完整保存"""
        details = {
            'patterns': [
                {'name': 'P-1-1', 'category': 'VOLUME_PRICE', 'direction': 'bullish',
                 'strength': 0.8, 'stage': 'COMPLETED', 'completion': 1.0}
            ],
            'bull_count': 1,
            'bear_count': 0,
        }
        ecm.cache_pattern_score('000001.SZ', '2025-08-15', 6.5, details)
        result = ecm.get_pattern_score('000001.SZ', '2025-08-15')
        assert result['details']['patterns'][0]['stage'] == 'COMPLETED'
        assert result['details']['patterns'][0]['completion'] == 1.0


class TestDataManagerFacade:
    """测试 DataManager 门面方法存在性"""

    def test_dm_has_cache_pattern_score(self):
        """DataManager 必须提供 cache_pattern_score 方法"""
        from app.data import DataManager
        assert hasattr(DataManager, 'cache_pattern_score')

    def test_dm_has_get_pattern_score(self):
        """DataManager 必须提供 get_pattern_score 方法"""
        from app.data import DataManager
        assert hasattr(DataManager, 'get_pattern_score')
