"""498号 批次4 验证探针（只读/纯逻辑）
#4 午休时间戳 / #15 连续成功恢复 / #32 _safe_int / #6 递归上限 / #43 腾讯全量 / #14 北京时间
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

print("=== #4 1min trade_time 午休映射（复现 _get_mootdx_minutes_safe 的 _bar_time）===")
def bar_time(target_date, i):
    if i < 120:
        h, m = 9 + (30 + i) // 60, (30 + i) % 60
    else:
        j = i - 120
        h, m = 13 + j // 60, j % 60
    return f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]} {h:02d}:{m:02d}:00"
checks = [(0, '09:30'), (119, '11:29'), (120, '13:00'), (239, '14:59')]
for i, exp in checks:
    got = bar_time('20260929', i)[-8:-3]
    print(f"  idx={i}: {got} (期望 {exp})  {'OK' if got == exp else 'FAIL'}")
print(f"  旧逻辑 idx=120: {9 + (120+30)//60:02d}:{(120+30)%60:02d} → 穿过午休(错)")

print()
print("=== #15 自恢复用连续成功计数（非累计）===")
from app.data.data_source_manager import DataSourceHealth, DataSourceStatus
h = DataSourceHealth('sina', priority=0)
h.auto_recovery_successes = 3
# 造 5 次历史成功（累计=5），再置 FALLBACK
for _ in range(5):
    h.record_success(10.0)
h.status = DataSourceStatus.FALLBACK
h.consecutive_successes = 0  # 进入降级时连续计数应已归零
h.record_success(10.0)  # 单次成功
print(f"  累计 successes={h.successes} 连续 successes={h.consecutive_successes} 状态={h.status.value}")
print(f"  旧逻辑(累计>=3)会误恢复；新逻辑状态={h.status.value}（期望 fallback，需连续3次才恢复）")
h.record_success(10.0); h.record_success(10.0)
print(f"  连续 3 次后状态={h.status.value}（期望 normal）")

print()
print("=== #32 _safe_int 容错 ===")
from app.data.akshare_collector import _safe_int
for v in ['', None, float('nan'), 'abc', '12', 34.6]:
    print(f"  _safe_int({v!r}) = {_safe_int(v)}")

print()
print("=== #6 降级递归上限 ===")
from app.data.data_source_manager import DataSourceManager
import inspect
sig = inspect.signature(DataSourceManager.get_data)
print(f"  get_data 参数: {list(sig.parameters)}（含 _retry={'_retry' in sig.parameters}）")

print()
print("=== #43 腾讯源全量（去 min(len,2000)）===")
import re
src = open(os.path.join(os.path.dirname(__file__), '..', 'app/data/mootdx_collector.py')).read()
_tencent_loop_truncated = bool(re.search(r'range\(0,\s*min\(len\(codes\),\s*2000\)', src))
print(f"  腾讯循环仍截断 range(0, min(len(codes),2000)): {_tencent_loop_truncated}（期望 False）")

print()
print("=== #14 分钟聚合用北京时间 ===")
print(f"  _feed_minute_aggregator 用 trading_hours._now: {'_now as _cn_now' in src}（期望 True）")

print()
print("=== #5 时间感知快路径记账 ===")
dssrc = open(os.path.join(os.path.dirname(__file__), '..', 'app/data/data_source_manager.py')).read()
print(f"  data_source_manager 快路径 record_success: {'health.record_success((time.time() - t0)' in dssrc}（期望 True）")
