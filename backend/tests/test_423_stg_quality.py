"""423号方案：STG 仓储质量体系测试（WriteGateway/QualityChecker/RecomputeScheduler）

故障注入式测试：不依赖真实数据库——校验判定逻辑经 monkeypatch 注入，
避免污染生产数据（data/ 下真实分库）。覆盖 423 号方案 C-7 用例：
写前校验、SIG JSON 损坏（G3）、跨表不对齐、补算调度、多轮核查汇总。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

from app.data.stg_quality import (
    CheckResult,
    QualityChecker,
    RecomputeScheduler,
    WriteGateway,
    run_quality_round,
)


def _make_signal_row(ts_code='000001.SZ', trade_date='2026-09-10', good=True):
    """构造 SIG 批量写入行（对齐 _SIG_ROW_IDX：ts_code/trade_date/signal_json/schema_version/seven_dim_json/dim_results_json）"""
    if good:
        signal = json.dumps({'direction': 'up', 'score': 0.8})
        dim_results = json.dumps({'dim2': {'judgment': {'state': '盘整'}}})
        # seven_dim_json 条件性产出（仅 summary 恒有，其余维按引擎信号存在与否）
        seven_dim = json.dumps({
            'structure': {'light': 'green', 'text': '结构: up'}, 'summary': {'light': 'green', 'text': '整体偏多'},
        })
    else:
        signal = '{bad json'
        dim_results = 'null'
        seven_dim = '{}'
    return (ts_code, trade_date, signal, 1, seven_dim, dim_results)


# ── G3：SIG 结果自检（423号 §2.3 专项）─────────────────────────

def test_validate_signal_rows_good():
    checker = QualityChecker()
    rows = [_make_signal_row() for _ in range(3)]
    assert checker.validate_signal_rows(rows) == []


def test_validate_signal_rows_bad_json():
    """故障注入：signal_json 非法 → 检出"""
    checker = QualityChecker()
    rows = [_make_signal_row(good=False)]
    issues = checker.validate_signal_rows(rows)
    assert any('signal_json 非法' in i for i in issues)


def test_validate_signal_rows_seven_dim_missing_summary():
    """故障注入：seven_dim_json 缺恒产出的 summary 键 → 检出"""
    checker = QualityChecker()
    row = list(_make_signal_row())
    row[4] = json.dumps({'structure': {'light': 'green'}})
    issues = checker.validate_signal_rows([tuple(row)])
    assert any('缺 summary 键' in i for i in issues)


def test_validate_signal_rows_seven_dim_ok_conditional():
    """seven_dim_json 条件性产出（2 键，含 summary）应通过"""
    checker = QualityChecker()
    row = list(_make_signal_row())
    row[4] = json.dumps({'emotion': {'light': 'yellow'}, 'summary': {'light': 'yellow'}})
    assert checker.validate_signal_rows([tuple(row)]) == []


def test_validate_signal_rows_empty_signal():
    """故障注入：signal_json 为空 dict → 检出"""
    checker = QualityChecker()
    row = list(_make_signal_row())
    row[2] = '{}'
    issues = checker.validate_signal_rows([tuple(row)])
    assert any('signal_json 为空' in i for i in issues)


def test_validate_signal_rows_dim_results_bad():
    checker = QualityChecker()
    row = list(_make_signal_row())
    row[5] = '{bad'
    issues = checker.validate_signal_rows([tuple(row)])
    assert any('dim_results_json 非法' in i for i in issues)


# ── WriteGateway：写前格式校验 ─────────────────────────────────

def test_validate_before_write_empty():
    wg = WriteGateway()
    issues = wg.validate_before_write('strategy_signal_detail', [])
    assert issues and '空写入' in issues[0]


def test_validate_before_write_non_sequence():
    wg = WriteGateway()
    issues = wg.validate_before_write('strategy_signal_detail', [{'ts_code': 'x'}])
    assert issues and '不是序列类型' in issues[0]


# ── QualityChecker：单表校验判定（monkeypatch 计数，不碰真实库）──

def test_check_table_pass(monkeypatch):
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5000)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 4900)
    r = checker.check_table('indicator_ma', '2026-09-10')
    assert r.passed
    assert r.table == 'indicator_ma'


def test_check_table_fail_coverage(monkeypatch):
    """故障注入：行数不足 → 覆盖率不足检出"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5000)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 1000)
    r = checker.check_table('indicator_ma', '2026-09-10')
    assert not r.passed
    assert any('覆盖率不足' in i for i in r.issues)


def test_check_table_unknown_rule():
    checker = QualityChecker()
    r = checker.check_table('nonexistent_table', '2026-09-10')
    assert r.passed  # 无规则表跳过（不做硬失败）


def test_check_table_no_base(monkeypatch):
    """基准行数=0（数据未就绪）→ 不通过且提示基准缺失"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 0)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 0)
    r = checker.check_table('indicator_ma', '2026-09-10')
    assert not r.passed
    assert any('基准行数=0' in i for i in r.issues)


# ── 跨表对齐校验（423号 §2.3 check_cross_table）────────────────

def test_check_cross_table_alignment_fail(monkeypatch):
    """故障注入：indicator_ma 与 daily_cache 不对齐 → 检出"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5000)
    monkeypatch.setattr(checker, '_count_by_date',
                        lambda t, d: 4000 if t == 'indicator_ma' else 5000)
    results = checker.check_cross_table('2026-09-10')
    failed = [r for r in results if not r.passed]
    assert any(r.table == 'indicator_ma' and r.kind == 'cross' for r in failed)


def test_check_cross_table_alignment_pass(monkeypatch):
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5000)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 4950)
    results = checker.check_cross_table('2026-09-10')
    assert all(r.passed for r in results)


# ── RecomputeScheduler：问题→环节映射（423号 §2.4）─────────────

def test_step_for_issue():
    sched = RecomputeScheduler()
    assert sched.step_for_issue('indicator_ma 覆盖率不足') == 'RAW-1'
    assert sched.step_for_issue('indicator_macd 缺失') == 'RAW-1'
    assert sched.step_for_issue('pre_feat_cache 缺失') == 'RAW-2'
    assert sched.step_for_issue('factor_cache 缺失') == 'RAW-3'
    assert sched.step_for_issue('strategy_signal_detail 缺失') == 'SIG'
    assert sched.step_for_issue('status_snapshot 缺失') == 'JUD'
    assert sched.step_for_issue('treemap_snapshot 缺失') == 'JUD'
    # daily_cache 缺失不映射 COL（COL-1..6 为跳过模式，补采由 run_integrity_check 负责）
    assert sched.step_for_issue('daily_cache 缺失') is None
    assert sched.step_for_issue('未知问题类型') is None


def test_issues_from_checks():
    sched = RecomputeScheduler()
    results = [
        CheckResult(False, 'indicator_ma', '2026-09-10',
                    issues=['indicator_ma 覆盖率不足: 1000/4750']),
        CheckResult(False, 'status_snapshot', '2026-09-10',
                    issues=['status_snapshot 覆盖率不足: 0/4750']),
        CheckResult(True, 'treemap_snapshot', '2026-09-10'),
    ]
    issues = sched.issues_from_checks(results)
    assert any('indicator_ma' in i for i in issues)
    assert any('status_snapshot' in i for i in issues)


# ── run_quality_round：多轮核查单轮执行体（423号 §3 事件驱动）──

def test_run_quality_round_failed_schedules_recompute(monkeypatch):
    """故障注入：校验失败 → 触发补算调度"""
    checker = QualityChecker()
    sched = RecomputeScheduler()
    monkeypatch.setattr(checker, 'check_pipeline_date', lambda d: [
        CheckResult(True, 'indicator_ma', d),
        CheckResult(False, 'status_snapshot', d,
                    issues=['status_snapshot 覆盖率不足: 0/4750']),
    ])
    scheduled = []

    def _fake_schedule(issue, d):
        scheduled.append(issue)
        return True

    monkeypatch.setattr(sched, 'schedule_recompute', _fake_schedule)
    out = run_quality_round('2026-09-10', checker, sched)
    assert out['passed'] is False
    assert out['failed_count'] == 1
    assert scheduled, '校验失败必须触发补算调度'


def test_run_quality_round_all_passed(monkeypatch):
    checker = QualityChecker()
    sched = RecomputeScheduler()
    monkeypatch.setattr(checker, 'check_pipeline_date', lambda d: [
        CheckResult(True, 'indicator_ma', d),
        CheckResult(True, 'status_snapshot', d),
    ])
    out = run_quality_round('2026-09-10', checker, sched)
    assert out['passed'] is True
    assert out['failed_count'] == 0


def test_quality_round_non_blocking(monkeypatch):
    """423号 §3 事件驱动非阻塞回归：单轮核查立即返回，无 sleep（补算等待由主循环 tick 驱动）"""
    import time
    checker = QualityChecker()
    sched = RecomputeScheduler()
    monkeypatch.setattr(checker, 'check_pipeline_date', lambda d: [
        CheckResult(False, 'indicator_ma', d, issues=['indicator_ma 覆盖率不足: 0/4750']),
    ])
    monkeypatch.setattr(sched, 'schedule_recompute', lambda issue, d: True)
    t0 = time.time()
    out = run_quality_round('2026-09-10', checker, sched)
    elapsed = time.time() - t0
    assert out['passed'] is False
    assert elapsed < 2.0, f'事件驱动核查必须非阻塞（实测 {elapsed:.2f}s，存在 sleep?）'


def test_quality_round_continuous_failure_for_escalation(monkeypatch):
    """423号 告警升级前置：连续 3 轮失败 → 每轮都触发补算调度（上层据此递增 retry 至超限告警）"""
    checker = QualityChecker()
    sched = RecomputeScheduler()
    monkeypatch.setattr(checker, 'check_pipeline_date', lambda d: [
        CheckResult(False, 'strategy_signal_detail', d,
                    issues=['strategy_signal_detail 覆盖率不足: 0/4750']),
    ])
    calls = []

    def _fake_schedule(issue, d):
        calls.append(issue)
        return True

    monkeypatch.setattr(sched, 'schedule_recompute', _fake_schedule)
    for _ in range(3):  # 模拟管道重试 3 轮（补算未生效场景）
        out = run_quality_round('2026-09-10', checker, sched)
        assert out['passed'] is False
    # 3 轮失败 = 上层可递增 retry_count 至 3 → 触发 _alert_qa_failure（L2 告警升级）
    assert len(calls) == 3, '连续失败必须持续触发补算调度（供上层计数升级告警）'
