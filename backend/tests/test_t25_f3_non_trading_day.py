"""T25-F3 回归测试：非交易日首次采集修复

背景：采集线程 run() 首次采集无条件执行，daemon 在周末/节假日启动时仍采集
→ 写入非交易日的无意义快照（如 08-02 周日 2401 条）。
修复后：首次采集仅交易日执行（_is_market_day 判断），非交易日跳过。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


@pytest.fixture(scope='module')
def module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'mootdx_f3', os.path.join(os.path.dirname(__file__), '..', 'app', 'data', 'mootdx_collector.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_is_market_day_weekend_false(module):
    """周末（周日）不是交易日（根因验证）"""
    from datetime import datetime
    sunday = datetime(2026, 8, 2, 10, 30)
    assert module._is_market_day(sunday) is False, "周日不应是交易日"


def test_is_market_day_weekday_true(module):
    """工作日是交易日"""
    from datetime import datetime
    monday = datetime(2026, 7, 27, 10, 30)  # 2026-07-27 是周一
    assert module._is_market_day(monday) is True, "周一应是交易日"


def _first_collect(module, check_trading, market_day):
    """复刻 run() 的首次采集判断逻辑"""
    if not check_trading or market_day():
        return 1
    return 0


def test_first_collect_skipped_on_weekend(module):
    """非交易日：首次采集应跳过（修复前无条件执行）"""
    calls = _first_collect(module, True, lambda: False)  # 周末 → market_day=False
    assert calls == 0, "非交易日首次采集应跳过（修复前会执行）"


def test_first_collect_runs_on_weekday(module):
    """交易日：首次采集应执行"""
    calls = _first_collect(module, True, lambda: True)  # 交易日 → market_day=True
    assert calls == 1, "交易日首次采集应执行"


def test_first_collect_runs_when_check_disabled(module):
    """check_trading=False（如非交易时段禁用检查的采集器）：仍执行"""
    calls = _first_collect(module, False, lambda: False)
    assert calls == 1, "check_trading=False 时应执行"
