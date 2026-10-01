"""505号 探针：RAW 步骤 fut.done 等待制（428 P1-2 线程累积缺陷修复）

mock 主循环上下文驱动 _drive_pipeline 到 RAW 段，验证状态机：
  ① 首次调用提交一轮（_RAW_ROUND 非空）
  ② fut 未 done 再调用 → 不重复提交（futures 数不变，pool 同引用）
  ③ fut done → mark_step_done + 该 step 移除
  ④ 全部 done → _RAW_ROUND=None（下 tick 可新轮）
  ⑤ fut 异常 → 保持 pending + 移除（不 mark，下轮可重试）
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


COL = ['COL-1', 'COL-2', 'COL-3', 'COL-4', 'COL-5', 'COL-6']
RAW = ['RAW-1', 'RAW-2', 'RAW-3']


class _FakeECM:
    def __init__(self):
        self.marked = []

    def ensure_pipeline_steps(self, d):
        pass

    def load_pipeline_status(self, d):
        st = {k: {'status': 'done'} for k in COL + ['COL-7']}
        st.update({k: {'status': 'pending'} for k in RAW})
        return st

    def mark_step_done(self, d, s, msg):
        self.marked.append((d, s))

    class _Conn:
        @staticmethod
        def execute(*a, **k):
            return _FakeECM._Conn

        @staticmethod
        def commit():
            pass

    @property
    def conn(self):
        return _FakeECM._Conn


def setup(fast=None, slow=None, boom=None):
    """安装 mock：依赖 + RAW 步骤函数"""
    dd._recover_stale_running = lambda: None
    dd._get_latest_data_date = lambda: '2026-09-30'
    dd._is_market_day = lambda: False
    dd._is_pipeline_complete = lambda d: False
    dd._get_active_codes = lambda d: ['600519.SH', '000001.SZ']
    dd._precompute_market_stats = lambda: None
    dd._maybe_backfill_daily = lambda d: None
    dd._ecm = _FakeECM()
    # _query_table：data_date（MAX）与 has_data（COUNT）两用
    dd._query_table = lambda table, sql, params=None: (
        '2026-09-30' if 'MAX(trade_date)' in sql else 5000)
    fns = {
        'RAW-1': fast or (lambda codes: None),
        'RAW-2': slow or (lambda codes: None),
        'RAW-3': boom or (lambda codes: None),
    }
    dd._precompute_indicators = fns['RAW-1']
    dd._precompute_raw_features = fns['RAW-2']
    dd._precompute_preset_combos = fns['RAW-3']
    dd._RAW_ROUND = None


# ── ① 首次提交一轮 ───────────────────────────────
print("== ① 首次提交一轮 ==")
setup()
dd._drive_pipeline()
check(dd._RAW_ROUND is not None, "首次调用 → _RAW_ROUND 非空（提交一轮）")
check(set(dd._RAW_ROUND['futures']) == set(RAW), f"提交 3 步骤: {list(dd._RAW_ROUND['futures'])}")
first_pool = dd._RAW_ROUND['pool']

# ── ③④ 全部 done → 清理 ──────────────────────────
print("== ③④ fut 全 done → mark + 清空 ==")
time.sleep(0.3)
dd._drive_pipeline()
check(len(dd._ecm.marked) == 3, f"3 步骤 mark done: {dd._ecm.marked}")
check(dd._RAW_ROUND is None, "全完成 → _RAW_ROUND=None")

# ── ② fut 未 done → 不重复提交 ────────────────────
print("== ② fut 未 done → 不重复提交 ==")
setup(slow=lambda codes: time.sleep(3))
dd._drive_pipeline()
pool1 = dd._RAW_ROUND['pool']
dd._drive_pipeline()  # 立即再调（RAW-2 未 done；RAW-1/3 已 done 被移除）
check(set(dd._RAW_ROUND['futures']) == {'RAW-2'}, f"快的步骤已 done 移除，慢的 RAW-2 保留: {list(dd._RAW_ROUND['futures'])}")
check(dd._RAW_ROUND['pool'] is pool1, "pool 同引用（未重新提交）")
time.sleep(3.2)
dd._drive_pipeline()
check(dd._RAW_ROUND is None, "慢步骤完成后清理 → _RAW_ROUND=None")

# ── ⑤ fut 异常 → 保持 pending + 移除 ──────────────
print("== ⑤ fut 异常 → 保持 pending + 移除 ==")
setup(boom=lambda codes: (_ for _ in ()).throw(RuntimeError('RAW 失败')))
dd._drive_pipeline()
time.sleep(0.3)
dd._drive_pipeline()
check(dd._RAW_ROUND is None, "异常 fut 移除 → _RAW_ROUND=None")
marked_raw = [m[1] for m in dd._ecm.marked]
check('RAW-3' not in marked_raw, f"异常步骤 RAW-3 不 mark done（保持 pending）: {marked_raw}")
check(sorted(marked_raw) == ['RAW-1', 'RAW-2'], "正常步骤 RAW-1/2 mark done")
# 下轮可重试（RAW 仍 pending → 重新提交）
dd._drive_pipeline()
check(dd._RAW_ROUND is not None, "下轮重新提交（异常步骤保持 pending → 可重试）")

print(f"\n结果: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
