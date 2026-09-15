"""425号方案：数据端写入优先级调度与STG启动补采闭环测试

故障注入式测试：不依赖真实数据库/daemon 运行——monkeypatch 注入判定与执行函数，
验证 C-1~C-4：优先级状态机、核心滞后判定、HIGH 补采包装、mootdx 降频、
sync_requests HIGH 窗口分级（前端展示类让路）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import data_daemon as dd
import pytest
from app.data.mootdx_collector import MootdxCollector, _MootdxThread


@pytest.fixture(autouse=True)
def _restore_priority():
    """每个测试后复位优先级状态（不经 _set_collect_priority，避免日志/monitor 副作用）"""
    yield
    with dd._collect_priority_lock:
        dd._collect_priority = 'NORMAL'


# ── C-1：优先级状态机 ────────────────────────────────────────

def test_priority_state_machine():
    dd._set_collect_priority('HIGH')
    assert dd._get_collect_priority() == 'HIGH'
    # 非法值忽略，保持原状态
    dd._set_collect_priority('INVALID')
    assert dd._get_collect_priority() == 'HIGH'
    dd._set_collect_priority('LOW')
    assert dd._get_collect_priority() == 'LOW'
    dd._set_collect_priority('NORMAL')
    assert dd._get_collect_priority() == 'NORMAL'


# ── C-1：核心数据滞后判定（复用 _check_data_timeliness 口径）────

def test_core_data_stale_true(monkeypatch):
    """daily_cache 滞后 >1 天 → 需要 HIGH 补采"""
    monkeypatch.setattr(dd, '_query_table', lambda table, sql: '2026-09-01')
    assert dd._core_data_stale() is True


def test_core_data_stale_false(monkeypatch):
    """核心表均为最新 → 无需 HIGH 补采"""
    today = datetime.now().strftime('%Y-%m-%d')
    monkeypatch.setattr(dd, '_query_table', lambda table, sql: today)
    assert dd._core_data_stale() is False


def test_core_data_stale_no_data(monkeypatch):
    """核心表无数据（latest=None）→ 不误判滞后（由 run_integrity_check 正常兜底）"""
    monkeypatch.setattr(dd, '_query_table', lambda table, sql: None)
    assert dd._core_data_stale() is False


# ── C-1：HIGH 补采包装（启动/整点巡检复用）────────────────────

def test_priority_check_high_when_stale(monkeypatch):
    """核心滞后 → HIGH → 降频 → 补采 → 恢复（finally 保证成对）"""
    calls = []
    monkeypatch.setattr(dd, '_core_data_stale', lambda: True)
    monkeypatch.setattr(dd, '_set_mootdx_backoff', lambda active: calls.append(('backoff', active)))
    monkeypatch.setattr(dd, 'run_integrity_check', lambda backfill_days: calls.append(('check', backfill_days)))
    monkeypatch.setattr(dd, '_set_collect_priority', lambda level: calls.append(('priority', level)))
    dd._run_priority_integrity_check(backfill_days=3)
    assert calls == [
        ('priority', 'HIGH'), ('backoff', True),
        ('check', 3),
        ('backoff', False), ('priority', 'NORMAL'),
    ]


def test_priority_check_high_finally_restores_on_error(monkeypatch):
    """补采异常 → finally 仍恢复降频与优先级（不残留 HIGH 窗口）"""
    calls = []
    monkeypatch.setattr(dd, '_core_data_stale', lambda: True)
    monkeypatch.setattr(dd, '_set_mootdx_backoff', lambda active: calls.append(('backoff', active)))
    monkeypatch.setattr(dd, '_set_collect_priority', lambda level: calls.append(('priority', level)))

    def _boom(backfill_days):
        raise RuntimeError('补采失败')

    monkeypatch.setattr(dd, 'run_integrity_check', _boom)
    with pytest.raises(RuntimeError):
        dd._run_priority_integrity_check(backfill_days=1)
    assert calls == [
        ('priority', 'HIGH'), ('backoff', True),
        ('backoff', False), ('priority', 'NORMAL'),
    ]


def test_priority_check_normal_when_fresh(monkeypatch):
    """核心无滞后 → 普通模式执行（不降频、不设 HIGH），保持现状行为"""
    calls = []
    monkeypatch.setattr(dd, '_core_data_stale', lambda: False)
    monkeypatch.setattr(dd, '_set_mootdx_backoff', lambda active: calls.append(('backoff', active)))
    monkeypatch.setattr(dd, 'run_integrity_check', lambda backfill_days: calls.append(('check', backfill_days)))
    monkeypatch.setattr(dd, '_set_collect_priority', lambda level: calls.append(('priority', level)))
    dd._run_priority_integrity_check(backfill_days=1)
    assert calls == [('check', 1)]


# ── C-2：mootdx 采集线程间隔可变属性（set_interval）────────────

def test_mootdx_set_interval():
    def _noop():
        pass

    t = _MootdxThread('market_snapshot', 5, _noop, check_trading_time=False)
    c = MootdxCollector()
    c._threads = [t]
    # 降频 5s→60s
    assert c.set_interval('market_snapshot', 60) is True
    assert t.interval == 60
    # 目标线程不存在 → False
    assert c.set_interval('minute_full', 600) is False
    # 非法间隔钳制到 ≥1
    assert c.set_interval('market_snapshot', 0) is True
    assert t.interval == 1


def test_set_mootdx_backoff(monkeypatch):
    """daemon 侧降频/恢复包装：HIGH 窗口降频、恢复还原频率"""
    import app.data.mootdx_collector as mdc

    calls = []

    class FakeCollector:
        def set_interval(self, name, sec):
            calls.append((name, sec))

    monkeypatch.setattr(mdc, 'mootdx_collector', FakeCollector())
    dd._set_mootdx_backoff(True)
    assert ('market_snapshot', 60) in calls
    assert ('minute_full', 600) in calls
    calls.clear()
    dd._set_mootdx_backoff(False)
    assert ('market_snapshot', 5) in calls
    assert ('minute_full', 300) in calls


# ── C-3：sync_requests 分级（HIGH 窗口前端展示类让路）──────────

class _FakeECM:
    def __init__(self, pending):
        self._pending = pending
        self.done = []
        self.failed = []

    def consume_pending_requests(self):
        return self._pending

    def mark_request_done(self, rid):
        self.done.append(rid)

    def mark_request_failed(self, rid):
        self.failed.append(rid)


def _make_req(rid, task_type):
    return {'id': rid, 'task_type': task_type, 'ts_code': None}


def test_sync_requests_high_skips_display_types(monkeypatch):
    """HIGH 窗口：前端展示类（full_daily）让路，核心依赖类（margin）正常消费"""
    monkeypatch.setattr(dd, '_get_collect_priority', lambda: 'HIGH')
    monkeypatch.setattr(dd, '_batch_margin', lambda *a, **k: 0)
    # 前端展示类若被误消费，_batch_daily 不应被调用
    monkeypatch.setattr(dd, '_batch_daily', lambda *a, **k: pytest.fail('full_daily 不应在 HIGH 下消费'))

    fake = _FakeECM([
        _make_req(1, 'full_daily'),   # 前端展示类
        _make_req(2, 'margin'),       # 核心依赖类
    ])
    monkeypatch.setattr(dd, '_ecm', fake)
    dd._consume_sync_requests_batch()
    assert fake.done == [2]  # 仅核心类被消费


def test_sync_requests_normal_processes_all(monkeypatch):
    """NORMAL：前端展示类正常消费（保持 429 限流行为，回归）"""
    monkeypatch.setattr(dd, '_get_collect_priority', lambda: 'NORMAL')
    monkeypatch.setattr(dd, '_batch_daily', lambda *a, **k: 0)
    monkeypatch.setattr(dd, '_batch_daily_basic', lambda *a, **k: 0)

    fake = _FakeECM([_make_req(1, 'full_daily')])
    monkeypatch.setattr(dd, '_ecm', fake)
    dd._consume_sync_requests_batch()
    assert 1 in fake.done


def test_sync_core_types_cover_finance_dependencies():
    """核心依赖类集合覆盖 SIG/JUD 依赖的财务类请求（目标 financial/history 库）"""
    assert {'finance_report', 'stk_holder', 'margin', 'adj_factor', 'top10_holders'} \
        <= dd._SYNC_CORE_TYPES
    # 前端展示类不在核心集合内（HIGH 下让路）
    assert 'full_daily' not in dd._SYNC_CORE_TYPES
    assert 'per_stock' not in dd._SYNC_CORE_TYPES


# ── C-5：441号D·通道②增强——个股级覆盖巡检 ──────────────────

def test_reconcile_cache_coverage_backfills_missing(monkeypatch):
    """非空表但个股级缺失 → 覆盖核对补采缺失个股（441号D）"""
    # active 池 5 只；三表分别缺 2 / 3 / 1 只
    active = [f'{i:06d}.SZ' for i in range(1, 6)]
    monkeypatch.setattr(dd, '_get_active_codes', lambda: active)
    # 按表返回已覆盖集合（模拟 _shard_fetchall 的 DISTINCT ts_code 行）
    covered_map = {
        'top10_holders_cache': ['000001.SZ', '000002.SZ', '000003.SZ'],  # 缺 2
        'stk_holder_cache':    ['000001.SZ', '000002.SZ'],              # 缺 3
        'finance_report_cache': ['000001.SZ', '000002.SZ', '000003.SZ', '000004.SZ'],  # 缺 1
    }
    called = []
    def _fake_fetchall(table, sql):
        return [[c] for c in covered_map[table]]
    monkeypatch.setattr(dd, '_shard_fetchall', _fake_fetchall)
    # _COVERAGE_RECONCILE 持有函数引用（模块加载时固化），须整体替换为 mock 单只补采
    monkeypatch.setattr(dd, '_COVERAGE_RECONCILE', [
        ('top10_holders_cache',  lambda c: called.append(('top10', c)) or 1, '前十大股东'),
        ('stk_holder_cache',     lambda c: called.append(('stk', c)) or 1, '股东人数'),
        ('finance_report_cache', lambda c: called.append(('fin', c)) or 1, '扩展财务'),
    ])

    res = dd._reconcile_cache_coverage(max_codes=40)
    # 三表均缺，且均在上限内全补
    assert res == {'前十大股东': 2, '股东人数': 3, '扩展财务': 1}
    # 补采的代码应为缺失集
    assert ('top10', '000004.SZ') in called and ('top10', '000005.SZ') in called
    assert ('stk', '000003.SZ') in called and ('stk', '000004.SZ') in called and ('stk', '000005.SZ') in called
    assert ('fin', '000005.SZ') in called
    assert not any(c[0] == 'fin' and c[1] == '000004.SZ' for c in called)  # 已覆盖不补


def test_reconcile_cache_coverage_respects_max_codes(monkeypatch):
    """覆盖巡检受 max_codes 限流（防单 tick 打爆 Tushare 积分）"""
    active = [f'{i:06d}.SZ' for i in range(1, 11)]  # 10 只
    monkeypatch.setattr(dd, '_get_active_codes', lambda: active)
    monkeypatch.setattr(dd, '_shard_fetchall',
        lambda table, sql: [['000001.SZ']])   # 每表仅 1 只已覆盖 → 缺 9
    called = []
    monkeypatch.setattr(dd, '_COVERAGE_RECONCILE', [
        ('top10_holders_cache',  lambda c: called.append(c) or 1, '前十大股东'),
        ('stk_holder_cache',     lambda c: 1, '股东人数'),
        ('finance_report_cache', lambda c: 1, '扩展财务'),
    ])

    res = dd._reconcile_cache_coverage(max_codes=5)
    assert res['前十大股东'] == 5
    assert len(called) == 5  # 限流生效
