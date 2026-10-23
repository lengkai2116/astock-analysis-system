"""542号：管道新增环节必须登记 pipeline_status

背景（2026-10-23）：532 批次2 在 _drive_pipeline 的 RAW-2B 之后新增
RAW-2D/RAW-2E，但 ensure_pipeline_steps 未登记。mark_step_running 的
UPDATE 命中 0 行返回 False，_run_pipeline_step 静默 return，管道连续
三日卡在 RAW-2B 之后，SIG/JUD/OUT 永不执行。

本测试锁定两条不变量：
1. ensure_pipeline_steps 注册全部 18 个环节（含 RAW-2D/RAW-2E）；
2. _run_pipeline_step 对未登记环节有缺行兜底（补登记 + 重试），不再静默丢失。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture()
def ecm(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    (tmp_path / 'duckdb').mkdir()
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def test_ensure_pipeline_steps_registers_raw2d_raw2e(ecm):
    ecm.ensure_pipeline_steps('20990101')
    rows = dict(ecm.conn.execute(
        "SELECT step_id, status FROM pipeline_status WHERE pipeline_date='20990101'"
    ).fetchall())
    assert len(rows) == 18, f"应登记 18 个环节，实际 {len(rows)}: {sorted(rows)}"
    assert rows.get('RAW-2D') == 'pending'
    assert rows.get('RAW-2E') == 'pending'
    assert rows.get('RAW-2C') == 'pending'
    # 幂等
    ecm.ensure_pipeline_steps('20990101')
    assert ecm.conn.execute(
        "SELECT COUNT(*) FROM pipeline_status WHERE pipeline_date='20990101'"
    ).fetchone()[0] == 18


def test_run_pipeline_step_self_registers_missing_step(ecm, monkeypatch):
    import importlib
    daemon = importlib.import_module('data_daemon')
    monkeypatch.setattr(daemon, '_ecm', ecm)

    called = []
    daemon._run_pipeline_step('20990101', 'RAW-UNREGISTERED', lambda: called.append(1), None)

    assert called == [1], "缺行兜底后应实际执行环节"
    status = ecm.conn.execute(
        "SELECT status FROM pipeline_status WHERE pipeline_date='20990101' AND step_id='RAW-UNREGISTERED'"
    ).fetchone()
    assert status and status[0] == 'done', f"应补登记并标记 done，实际 {status}"
