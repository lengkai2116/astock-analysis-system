"""498号 批次3 并发健壮性验证探针（只读 + 内存对象）
#16 _prev_prices 锁 / #17 _source_stats 锁 / #18 fallback 单例锁 / #19 限流器锁
#20 连接缓存竞态 / #24 init_sharding close_all
"""
import os, sys, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

print("=== #20 连接缓存并发去重（20 线程首次并发 get_connection）===")
import app.data.sharding_manager as sm_mod
tmp_dir = '/tmp/_498b3_shard'
os.makedirs(os.path.join(tmp_dir, 'duckdb'), exist_ok=True)
sm = sm_mod.ShardingManager(tmp_dir)
ids = []
barrier = threading.Barrier(20)
def grab():
    barrier.wait()
    ids.append(id(sm.get_connection('market_cache.db')))
ts = [threading.Thread(target=grab) for _ in range(20)]
[t.start() for t in ts]; [t.join() for t in ts]
print(f"  20 线程拿到的连接对象数 = {len(set(ids))}（期望 1）; _connections 条数 = {len(sm._connections)}（期望 1）")

print()
print("=== #24 init_sharding 替换时 close_all 旧实例 ===")
saved = sm_mod.sharding_manager
old = sm_mod.ShardingManager(tmp_dir)
old.get_connection('market_cache.db')
sm_mod.sharding_manager = old
print(f"  替换前 old._connections = {len(old._connections)}")
sm_mod.init_sharding(tmp_dir)
print(f"  替换后 old._connections = {len(old._connections)}（期望 0=已关闭）")
sm_mod.sharding_manager = saved  # 还原

print()
print("=== #16 _calc_speed 并发（4 线程 × 2000 次）===")
from app.data import mootdx_collector as mc
errs = []
def hammer_speed():
    try:
        for i in range(2000):
            mc._calc_speed('600519.SH', 100.0 + i)
    except Exception as e:
        errs.append(e)
ts = [threading.Thread(target=hammer_speed) for _ in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
print(f"  并发异常数 = {len(errs)}（期望 0）; _prev_prices has key = {'600519.SH' in mc._prev_prices}")

print()
print("=== #17 _record_source_result 并发计数（4 线程 × 5000 次 ok）===")
mc._source_stats['sina'] = {'ok': 0, 'fail': 0}
def hammer_stats():
    for _ in range(5000):
        mc._record_source_result('sina', True)
ts = [threading.Thread(target=hammer_stats) for _ in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
got = mc._source_stats['sina']['ok']
print(f"  sina.ok = {got}（期望 20000=无丢失更新）")

print()
print("=== #18 fallback_manager 并发（4 线程 × 3000 次 update_health_status）===")
from app.data.fallback_manager import FallbackManager
fm = FallbackManager()
def hammer_fb():
    for i in range(3000):
        fm.update_health_status('sina', is_healthy=(i % 2 == 0), response_time=10.0)
ts = [threading.Thread(target=hammer_fb) for _ in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
rep = fm.get_health_report()
print(f"  fail 总数 = {rep['sources']['sina']['total_failures']}（期望 6000=4×3000/2 无丢失）")

print()
print("=== #19 tushare_provider 限流器串行（5 次调用 / 间隔 0.2s）===")
from app.data import tushare_provider as tp
calls = []
def stub(*a, **k):
    calls.append(time.time()); return None
tp._TS_MIN_INTERVAL = 0.2
tp._ts_last_call = 0.0
t0 = time.time()
ts_list = []
def call_ts():
    ts_list.append(tp._ts(stub))
threads = [threading.Thread(target=call_ts) for _ in range(5)]
[t.start() for t in threads]; [t.join() for t in threads]
elapsed = time.time() - t0
print(f"  5 线程并发 _ts 总耗时 = {elapsed:.2f}s（串行应 ≥0.8s；无锁会 <0.2s）")
