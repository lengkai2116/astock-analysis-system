"""518号 定向测试：分库读写分离（get_read_connection 与写连接分离）。

- **Q1=A / Q2=A**：`sharding_manager` 新增 `get_read_connection`（每分库独立只读连接）；
  通用读 helper（`execute_query`/`table_exists`/`get_table_row_count`/`list_unmapped_tables`）
  与 ECM `_query_shard` 改走只读连接 —— 杜绝「同一连接被读（不持锁）与写
  （`execute_batch_insert`，持库级 RLock）并发使用」导致的
  `database is locked` / `another row available`。
"""
import inspect

from app.data.sharding_manager import ShardingManager


def _mgr(tmp_path):
    (tmp_path / 'duckdb').mkdir(exist_ok=True)
    return ShardingManager(str(tmp_path))


def test_read_connection_separate_from_write_connection(tmp_path):
    sm = _mgr(tmp_path)
    w = sm.get_connection('compute_cache.db')
    r = sm.get_read_connection('compute_cache.db')
    assert w is not r, "读连接必须与写连接分离（518 号读写分离）"
    assert sm.get_read_connection('compute_cache.db') is r, "读连接应缓存复用"
    assert sm.get_read_connection('compute_cache.db') is not sm.get_connection('compute_cache.db')
    sm.close_all()


def test_execute_query_uses_read_connection(tmp_path):
    src = inspect.getsource(ShardingManager.execute_query)
    assert 'get_read_connection' in src, "execute_query 应走独立只读连接"
    assert 'get_connection(' not in src, "execute_query 不应再使用写连接"


def test_read_helpers_use_read_connection():
    for name in ('table_exists', 'get_table_row_count', 'list_unmapped_tables'):
        src = inspect.getsource(getattr(ShardingManager, name))
        assert 'get_read_connection' in src, f"{name} 应走独立只读连接"


def test_query_shard_uses_read_connection():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    src = inspect.getsource(EnhancedCacheManager._query_shard)
    assert 'get_read_connection' in src, "_query_shard 应走独立只读连接"


def test_read_after_write_sees_committed_data(tmp_path):
    """读写分离后行为一致：写提交的数据，读连接可见。"""
    sm = _mgr(tmp_path)
    sm.create_table('indicator_ma',
                    'CREATE TABLE IF NOT EXISTS indicator_ma (ts_code TEXT, val REAL)')
    sm.execute_batch_insert(
        'indicator_ma',
        'INSERT OR REPLACE INTO indicator_ma (ts_code, val) VALUES (?, ?)',
        [('000001.SZ', 1.5)])
    rows = sm.execute_query(
        'indicator_ma', 'SELECT val FROM indicator_ma WHERE ts_code=?', ['000001.SZ'])
    assert rows == [(1.5,)], f"读连接应见写提交数据: {rows}"
    sm.close_all()
