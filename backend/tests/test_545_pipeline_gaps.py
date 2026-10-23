"""545号：日终缺口两处不变量

1. `_is_pipeline_complete` 的环节清单必须来自 PIPELINE_STEPS（单一来源），
   不能硬编码 16 项——否则 532 批次2 新增的 RAW-2D/RAW-2E 漏判。
2. `_check_limit_detail_completeness`：基础表（stk_limit_cache）已完整但
   limit_detail_cache 当日为空时必须补采（10-22 实证：5655 行 vs 0 行）。
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


def _mark_done(ecm, date: str, step_ids) -> None:
    for sid in step_ids:
        ecm.conn.execute(
            "UPDATE pipeline_status SET status='done' WHERE pipeline_date=? AND step_id=?",
            [date, sid])
    ecm.conn.commit()


def test_pipeline_complete_requires_all_registered_steps(ecm, monkeypatch):
    import importlib
    from app.data.enhanced_cache_manager import PIPELINE_STEPS

    daemon = importlib.import_module('data_daemon')
    monkeypatch.setattr(daemon, '_ecm', ecm)

    date = '20990202'
    ecm.ensure_pipeline_steps(date)
    all_ids = [sid for sid, _ in PIPELINE_STEPS]

    # 旧口径的 16 项全 done（缺 RAW-2D/RAW-2E）→ 不得判完成
    legacy = [s for s in all_ids if s not in ('RAW-2D', 'RAW-2E')]
    _mark_done(ecm, date, legacy)
    assert daemon._is_pipeline_complete(date) is False

    _mark_done(ecm, date, ['RAW-2D', 'RAW-2E'])
    assert daemon._is_pipeline_complete(date) is True


def test_limit_detail_backfill_when_detail_empty(monkeypatch):
    import importlib
    daemon = importlib.import_module('data_daemon')
    calls = []

    monkeypatch.setattr(daemon, '_is_trading_day', lambda d: True)
    monkeypatch.setattr(daemon, '_is_today_data_ready', lambda: True)
    monkeypatch.setattr(daemon, '_query_table',
                        lambda table, sql, params=None: {
                            'stk_limit_cache': 5655,
                            'limit_detail_cache': 0,
                        }[table])
    monkeypatch.setattr(daemon, '_batch_limit_detail',
                        lambda d: calls.append(d) or 37)

    daemon._check_limit_detail_completeness(1)

    assert len(calls) == 1
    assert len(calls[0]) == 8 and calls[0].isdigit(), f"应为 YYYYMMDD，实际 {calls[0]}"


def test_limit_detail_skips_when_detail_present(monkeypatch):
    import importlib
    daemon = importlib.import_module('data_daemon')
    calls = []

    monkeypatch.setattr(daemon, '_is_trading_day', lambda d: True)
    monkeypatch.setattr(daemon, '_is_today_data_ready', lambda: True)
    monkeypatch.setattr(daemon, '_query_table',
                        lambda table, sql, params=None: {
                            'stk_limit_cache': 5655,
                            'limit_detail_cache': 69,
                        }[table])
    monkeypatch.setattr(daemon, '_batch_limit_detail',
                        lambda d: calls.append(d) or 0)

    daemon._check_limit_detail_completeness(3)

    assert calls == []


def test_limit_detail_skips_when_base_incomplete(monkeypatch):
    import importlib
    daemon = importlib.import_module('data_daemon')
    calls = []

    monkeypatch.setattr(daemon, '_is_trading_day', lambda d: True)
    monkeypatch.setattr(daemon, '_is_today_data_ready', lambda: True)
    monkeypatch.setattr(daemon, '_query_table',
                        lambda table, sql, params=None: {
                            'stk_limit_cache': 96,
                            'limit_detail_cache': 0,
                        }[table])
    monkeypatch.setattr(daemon, '_batch_limit_detail',
                        lambda d: calls.append(d) or 0)

    daemon._check_limit_detail_completeness(3)

    assert calls == []
