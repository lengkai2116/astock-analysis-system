"""2026-10-31：历史 QA 巡检改查归档表（修 10-30 遗留③）

`status_snapshot` / `treemap_snapshot` 是只保留最新一日的 live 表，历史日数据在
`*_history`。原巡检用 live 表名查历史日期，恒得 0 行 → 10-27/28/29 每 tick 假报
`0/5291`。

本测试锁定：
1. 历史日对两张快照表改查 `*_history`；
2. 最新数据日整体跳过（当日 live 表由 QA-CHECK 校验，日终未跑完不应报历史缺失）；
3. 归档表在 QUALITY_RULES 中有校验规则（否则 check_table 会「无规则，跳过」）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture()
def daemon():
    import importlib
    return importlib.import_module('data_daemon')


class _Result:
    def __init__(self, passed=True, issues=None):
        self.passed = passed
        self.issues = issues or []


def _fake_checker(calls, fail_tables=()):
    def check_table(table, date):
        calls.append((table, date))
        if table in fail_tables:
            return _Result(False, [f'{table} 覆盖率不足: 0/5291（0% < 95%）'])
        return _Result(True)
    return type('FakeChecker', (), {'check_table': staticmethod(check_table)})()


def test_patrol_checks_history_tables_and_skips_latest(daemon, monkeypatch):
    calls = []
    monkeypatch.setattr(daemon, '_get_stg_components',
                        lambda: (_fake_checker(calls), None))
    monkeypatch.setattr(daemon, '_shard_fetchall',
                        lambda table, sql, params=None: [
                            ('2026-10-30',), ('2026-10-29',), ('2026-10-28',)])

    daemon._run_history_qa_patrol(3)

    assert calls == [
        ('strategy_signal_detail', '2026-10-29'),
        ('status_snapshot_history', '2026-10-29'),
        ('treemap_snapshot_history', '2026-10-29'),
        ('strategy_signal_detail', '2026-10-28'),
        ('status_snapshot_history', '2026-10-28'),
        ('treemap_snapshot_history', '2026-10-28'),
    ], '历史日必须查 *_history，最新数据日整体跳过'


def test_patrol_warning_names_history_table(daemon, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(daemon, '_get_stg_components',
                        lambda: (_fake_checker(calls, fail_tables=('status_snapshot_history',)), None))
    monkeypatch.setattr(daemon, '_shard_fetchall',
                        lambda table, sql, params=None: [
                            ('2026-10-30',), ('2026-10-29',)])

    with caplog.at_level('WARNING'):
        daemon._run_history_qa_patrol(2)

    assert any('[QA-巡检] 历史日期 2026-10-29 status_snapshot_history 缺失'
               in r.message for r in caplog.records)


def test_quality_rules_cover_history_tables():
    from app.data.stg_quality import QUALITY_RULES

    for table in ('status_snapshot_history', 'treemap_snapshot_history'):
        rule = QUALITY_RULES.get(table)
        assert rule, f'{table} 缺少校验规则'
        assert rule.get('date_col') == 'trade_date'
        assert rule.get('rows_ratio') == 0.95

    assert QUALITY_RULES['status_snapshot_history']['required_fields'] == [
        'dim_states', 'status_bar']
