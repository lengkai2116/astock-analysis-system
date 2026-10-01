"""503号 探针：日终死锁修复（A 管道自愈 _maybe_backfill_daily + B _core_data_stale 行数判断）

隔离/mock 验证（不触 Tushare、不写真库）：
  A-1 门控：data_date==今天 且 _is_today_data_ready()=False（<18:00）→ 不调 _batch_daily
  A-2 历史日：data_date==昨日 → 调 _batch_daily 且传 YYYYMMDD
  A-3 防抖：同日期 10min 内二次调用 → 只调一次；last_n==0 → 冷却 30min
  A-4 异常：_batch_daily 抛错 → 记 warning 不向上抛
  B-1：daily_cache 最新日 96 行 → _core_data_stale()=True
  B-2：最新日 5557 行 → False（日期不滞后时）
"""
import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import data_daemon as dd  # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {msg}")
    else:
        FAIL += 1
        print(f"  ❌ {msg}")


import data_daemon as dd  # noqa: E402

TODAY = '2026-10-01'
YESTERDAY = '2026-09-30'

def reset_state():
    dd._DAILY_BACKFILL_STATE.clear()


print("== A-1 门控：今日 <18:00 不补采 ==")
reset_state()
with mock.patch.object(dd, '_is_today_data_ready', return_value=False), \
     mock.patch.object(dd, '_batch_daily', return_value=5557) as m:
    dd._maybe_backfill_daily(TODAY)
    check(m.call_count == 0, f"_batch_daily 未被调（<18:00 等发布，调用 {m.call_count} 次）")
    check(TODAY in dd._DAILY_BACKFILL_STATE, "状态已记录（30min 冷却）")

print("== A-1b 门控：今日 ≥18:00 补采 ==")
reset_state()
with mock.patch.object(dd, '_is_today_data_ready', return_value=True), \
     mock.patch.object(dd, '_batch_daily', return_value=5557) as m:
    dd._maybe_backfill_daily(TODAY)
    check(m.call_count == 1, "_batch_daily 被调 1 次（≥18:00 发布）")
    check(m.call_args[0][0] == TODAY.replace('-', ''), f"传参 YYYYMMDD={m.call_args[0][0]!r}")

print("== A-2 历史日直接补 ==")
reset_state()
with mock.patch.object(dd, '_is_today_data_ready', return_value=False), \
     mock.patch.object(dd, '_batch_daily', return_value=5557) as m:
    dd._maybe_backfill_daily(YESTERDAY)
    check(m.call_count == 1, f"历史日直接补采（<18:00 不限，调用 {m.call_count} 次）")
    check(m.call_args[0][0] == YESTERDAY.replace('-', ''), f"传参 YYYYMMDD={m.call_args[0][0]!r}")

print("== A-3 防抖 ==")
reset_state()
with mock.patch.object(dd, '_is_today_data_ready', return_value=True), \
     mock.patch.object(dd, '_batch_daily', return_value=5557) as m:
    dd._maybe_backfill_daily(TODAY)
    dd._maybe_backfill_daily(TODAY)  # 立即二次调用
    check(m.call_count == 1, f"10min 冷却内二次调用不重复补采（调用 {m.call_count} 次）")
# 空返回（last_n==0）→ 30min 冷却
reset_state()
with mock.patch.object(dd, '_is_today_data_ready', return_value=True), \
     mock.patch.object(dd, '_batch_daily', return_value=0) as m:
    dd._maybe_backfill_daily(TODAY)
    dd._maybe_backfill_daily(TODAY)
    check(m.call_count == 1, f"空返回后 30min 冷却（调用 {m.call_count} 次）")
# 冷却过期后可重试（伪造 31min 前状态）
reset_state()
dd._DAILY_BACKFILL_STATE[TODAY] = (time.time() - 31 * 60, 0)
with mock.patch.object(dd, '_is_today_data_ready', return_value=True), \
     mock.patch.object(dd, '_batch_daily', return_value=5557) as m:
    dd._maybe_backfill_daily(TODAY)
    check(m.call_count == 1, "冷却过期（31min）后重试补采")

print("== A-4 异常不向上抛 ==")
reset_state()
with mock.patch.object(dd, '_is_today_data_ready', return_value=True), \
     mock.patch.object(dd, '_batch_daily', side_effect=RuntimeError('API 超时')) as m:
    try:
        dd._maybe_backfill_daily(TODAY)
        check(True, "_batch_daily 抛错被捕获（不向上抛）")
    except RuntimeError:
        check(False, "_batch_daily 抛错未捕获")
    check(dd._DAILY_BACKFILL_STATE[TODAY][1] == 0, "失败后状态 last_n=0（30min 冷却）")

print("== B _core_data_stale 行数判断 ==")
# B-1：最新日 96 行（残留）→ 滞后 True（mock 各表 MAX(trade_date) 与行数）
def fake_query(table, sql, params=None):
    if 'SELECT MAX(trade_date)' in sql:
        return TODAY if table == 'daily_cache' else TODAY
    if 'SELECT COUNT(*)' in sql:
        return 96  # 残留 96 行
    return 0

with mock.patch.object(dd, '_query_table', side_effect=fake_query), \
     mock.patch.object(dd, '_lag_trading_days', return_value=0):
    check(dd._core_data_stale() is True, "最新日 96 行（<5000）→ 视为滞后 True")

# B-2：最新日 5557 行且日期不滞后 → False
def fake_query_full(table, sql, params=None):
    if 'SELECT MAX(trade_date)' in sql:
        return TODAY
    if 'SELECT COUNT(*)' in sql:
        return 5557
    return 0

with mock.patch.object(dd, '_query_table', side_effect=fake_query_full), \
     mock.patch.object(dd, '_lag_trading_days', return_value=0):
    check(dd._core_data_stale() is False, "最新日 5557 行（≥5000）且日期不滞后 → False")

print(f"\n结果: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
