"""498号 批次8 验证探针（只读/内存）：#31 快照TTL / #52 名称兜底 / #41 窗口聚合"""
import os, sys, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

print("=== #31 get_market_snapshot 3s TTL 缓存 ===")
from app.data.akshare_provider import AkshareProvider
p = AkshareProvider()
print("  有 _snapshot_cache/_ts/_lock:", all(hasattr(p, a) for a in ('_snapshot_cache', '_snapshot_ts', '_snapshot_lock')))
src = inspect.getsource(AkshareProvider.get_market_snapshot)
print("  命中 3s 缓存直接返回:", "time.time() - self._snapshot_ts) < 3.0" in src)
print("  分离 _fetch_market_snapshot:", hasattr(AkshareProvider, '_fetch_market_snapshot'))
# 用桩函数验证 TTL 命中（不真连网）
calls = {'n': 0}
def _stub():
    calls['n'] += 1
    return [{'ts_code': 'X'}]
p._fetch_market_snapshot = _stub
p._snapshot_cache = None; p._snapshot_ts = 0.0
r1 = p.get_market_snapshot(); r2 = p.get_market_snapshot(); r3 = p.get_market_snapshot()
print(f"  3 次连续调用 → 真实拉取次数 = {calls['n']}（期望 1=后两次命中缓存）")

print()
print("=== #52 _get_stock_name 快照名称兜底 ===")
from app.data import akshare_provider as ap
print("  已知码命中 map:", ap._get_stock_name('600519.SH') == '贵州茅台')
print("  未注册码回退 ts_code（无快照时）:", ap._get_stock_name('999999.XX') == '999999.XX')
# 注入快照名
from app.data.in_memory_store import store
store.update_snapshot([{'ts_code': '300999.SZ', 'name': '某新股'}])
print("  快照有名称时取快照:", ap._get_stock_name('300999.SZ') == '某新股')

print()
print("=== #41 aggregate_1min_to_60min 窗口读 ===")
from app.data import minute_backfill
sig = inspect.signature(minute_backfill.aggregate_1min_to_60min)
print("  新增 days_back 参数:", 'days_back' in sig.parameters, f"(默认 {sig.parameters.get('days_back')})")
body = inspect.getsource(minute_backfill.aggregate_1min_to_60min)
print("  按日期窗口裁剪:", "trade_dates" in body and "isin(trade_dates)" in body)

print()
print("ALL_CHECKS_DONE")
