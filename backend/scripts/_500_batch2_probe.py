"""500号 批次2 探针——分库路由收口（#4/#5/#6）

只读/临时隔离验证，不触真实生产库：
  #4 get_write_lock 并发首次建锁 → 同一 db_name 必须返回同一把锁
  #5 get_connection 初始化失败 → 连接关闭且不入缓存，下次重建
  #6 get_table_row_count 前缀动态表（adj_factor_cache_YYYY）→ 走 is_registered，不再恒 0（返真实行数或 0 但路由一致）
     且非法标识符被拒
"""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.data.sharding_manager import ShardingManager, _is_valid_identifier  # noqa: E402

FAIL = []


def _mkroot():
    """构造含 duckdb 子目录的临时数据根（ShardingManager 要求 <data_dir>/duckdb）"""
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, 'duckdb'), exist_ok=True)
    return root


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


# ── #4 写锁并发首次建锁：两线程必须拿到同一把锁 ──────────────────────────
print("=== #4 get_write_lock 并发首次建锁 ===")
sm = ShardingManager(_mkroot())
barrier = threading.Barrier(8)
locks = []
lk = threading.Lock()


def _grab():
    barrier.wait()
    lock = sm.get_write_lock('market_cache.db')
    with lk:
        locks.append(lock)


ts = [threading.Thread(target=_grab) for _ in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
check(len({id(x) for x in locks}) == 1, f"8 线程并发首次取锁 → 同一把锁（唯一 id 数={len({id(x) for x in locks})}）")
check(sm.get_write_lock('market_cache.db') is locks[0], "二次取锁与首次相同")

# ── #5 连接初始化失败：关闭且不入缓存 ────────────────────────────────────
print("=== #5 get_connection 错误路径不泄漏 ===")
sm2 = ShardingManager(_mkroot())


class _FakeConn:
    closed = False

    def execute(self, *a, **k):
        raise RuntimeError("模拟 PRAGMA 失败")

    def close(self):
        self.closed = True


_fake = _FakeConn()
_orig_connect = __import__('sqlite3').connect
__import__('sqlite3').connect = lambda *a, **k: _fake   # type: ignore
try:
    try:
        sm2.get_connection('market_cache.db')
        check(False, "应抛出初始化异常")
    except RuntimeError:
        check(True, "初始化异常向上传播")
finally:
    __import__('sqlite3').connect = _orig_connect  # type: ignore
check(_fake.closed, "失败连接已关闭（无句柄泄漏）")
check('market_cache.db' not in sm2._connections, "失败连接未入缓存")

# ── #6 前缀动态表路由一致 ───────────────────────────────────────────────
print("=== #6 get_table_row_count 前缀路由 ===")
sm3 = ShardingManager(_mkroot())
check(sm3.is_registered('adj_factor_cache_2026'), "前缀表 adj_factor_cache_2026 视为已登记")
check(sm3.get_db_for_table('adj_factor_cache_2026') == 'history_cache.db', "前缀表路由到 history_cache.db")
# 未登记表返 0（不触发 DB 访问）
check(sm3.get_table_row_count('no_such_table_xyz') == 0, "未登记表返 0")
# 建表后验证真实行数：普通注册表 + 前缀动态表均可正确计数（路由一致的关键证据）
_dc = sm3.get_connection('market_cache.db')
_dc.execute("CREATE TABLE daily_cache(ts_code TEXT)")
_dc.executemany("INSERT INTO daily_cache VALUES(?)", [('a',), ('b',), ('c',)])
_dc.commit()
check(sm3.get_table_row_count('daily_cache') == 3, "注册表 daily_cache 计数=3")

_hc = sm3.get_connection('history_cache.db')
_hc.execute("CREATE TABLE adj_factor_cache_2026(ts_code TEXT)")
_hc.executemany("INSERT INTO adj_factor_cache_2026 VALUES(?)", [('a',), ('b',)])
_hc.commit()
check(sm3.get_table_row_count('adj_factor_cache_2026') == 2,
      "前缀动态表 adj_factor_cache_2026 计数=2（原实现恒 0＝缺陷）")

check(_is_valid_identifier('adj_factor_cache_2026'), "合法标识符通过")
check(not _is_valid_identifier('a; DROP TABLE x'), "非法标识符被拒")
check(not _is_valid_identifier('1abc'), "数字开头被拒")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次2 探针全绿（#4/#5/#6）")
