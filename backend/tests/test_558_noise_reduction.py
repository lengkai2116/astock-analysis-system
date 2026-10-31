"""2026-10-31：源侧噪声收敛（修 10-30 遗留⑥）

三处「高频但非故障」的噪声改为不再刷 WARNING：
1. 逐只查询空返回（业绩预告/股东增减持多数股票本就没有）→ `_ts(quiet=True)` 降 DEBUG；
2. 分库连接上没有该表时的补列迁移 → 直接跳过（此前 ALTER 抛 no such table）；
3. daemon 内多处 create_app() 重复启动 APScheduler → 已运行时跳过。
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


def test_ts_quiet_suppresses_empty_warning(daemon, caplog):
    import pandas as pd

    empty = lambda **kw: pd.DataFrame()  # noqa: E731

    with caplog.at_level('WARNING'):
        daemon._ts(empty, start_date='20260101', end_date='20260131', quiet=True)
    assert not any('Tushare空返回' in r.message for r in caplog.records)

    with caplog.at_level('WARNING'):
        daemon._ts(empty, start_date='20260101', end_date='20260131')
    assert any('Tushare空返回' in r.message for r in caplog.records), \
        '区间查询（非逐只）仍应保留 WARNING'


def test_provider_ts_quiet_and_no_forwarding(caplog):
    """tushare_provider 有独立 _ts 副本：quiet 必须被吞掉，不能透传给 Tushare API。"""
    import pandas as pd

    from app.data.tushare_provider import _ts as provider_ts

    empty = lambda **kw: pd.DataFrame()  # noqa: E731
    with caplog.at_level('WARNING'):
        provider_ts(empty, start_date='20260101', end_date='20260131', quiet=True)
    assert not any('Tushare空返回' in r.message for r in caplog.records)

    seen = {}

    def probe(**kw):
        seen.update(kw)
        return pd.DataFrame()

    provider_ts(probe, start_date='20260101', end_date='20260131', quiet=True)
    assert 'quiet' not in seen, 'quiet 是本地日志开关，不得传给 Tushare API'


def test_migrate_skips_missing_table_quietly(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    (tmp_path / 'duckdb').mkdir()
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()

    with caplog.at_level('WARNING'):
        ecm._migrate_missing_columns('no_such_table', [('x', 'TEXT')])
    assert not any('补列失败' in r.message for r in caplog.records)

    # 正向：存在的表仍能补齐缺失列
    ecm.conn.execute("CREATE TABLE t_demo (a TEXT)")
    ecm.conn.commit()
    ecm._migrate_missing_columns('t_demo', [('b', 'TEXT')])
    cols = {r[1] for r in ecm.conn.execute("PRAGMA table_info(t_demo)")}
    assert 'b' in cols


def test_scheduler_init_app_is_idempotent():
    from app.scheduler_manager import SchedulerManager

    class _RunningScheduler:
        running = True

    mgr = SchedulerManager()
    mgr._scheduler = _RunningScheduler()
    mgr.init_app(None)  # 已运行 → 直接返回，不应访问 app.app_context()

    assert mgr._initialized is False
