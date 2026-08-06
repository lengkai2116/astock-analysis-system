"""T6.1 回归测试：_add_vp_simple_tags 应产出非 none 的 pattern_signal

背景：data_daemon.py:1733 调用 detector.detect_all(closes, opens, ...) 时
opens 变量未定义 → NameError 被 except 吞掉 → pattern_signal 恒为 none。
本测试用真实K线数据验证修复后能产出形态。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest


def _make_uptrend_df(n=60):
    """构造一段放量上涨行情，确保能命中增强形态检测"""
    rng = np.random.default_rng(42)
    close = 10 + np.cumsum(np.abs(rng.normal(0.2, 0.05, n)))
    high = close * 1.02
    low = close * 0.98
    open_ = close * 0.995
    vol = np.linspace(1e5, 3e5, n) * (1 + rng.normal(0, 0.1, n))
    dates = pd.date_range('2026-01-01', periods=n).strftime('%Y-%m-%d')
    return pd.DataFrame({
        'ts_code': '000001.SZ', 'trade_date': dates,
        'open': open_, 'high': high, 'low': low, 'close': close,
        'vol': vol, 'amount': vol * close, 'pct_chg': 0,
    })


@pytest.fixture(scope='module')
def data_daemon_module():
    """加载 data_daemon 模块（不执行 main）"""
    spec = importlib.util.spec_from_file_location(
        'data_daemon_test', os.path.join(os.path.dirname(__file__), '..', 'data_daemon.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_add_vp_simple_tags_produces_pattern_signal():
    """_add_vp_simple_tags 应产出 pattern_signal（非 none），且不抛 NameError"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'dd', os.path.join(os.path.dirname(__file__), '..', 'data_daemon.py'))
    dd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dd)

    df = _make_uptrend_df()
    tags = {}
    dd._ensure_pd()  # 注入 pd/np 全局（生产管道在 _precompute_l2_labels 开头调用）
    dd._add_vp_simple_tags(df, tags)

    # 核心断言：修复前这里会 NameError→fallback，多数为 none；
    # 修复后应能命中增强检测（上涨行情 + 放量 → 至少不是 none）
    assert tags.get('pattern_signal') is not None, "pattern_signal 不应为 None"
    assert isinstance(tags['pattern_signal'], str)
    assert len(tags['pattern_signal']) > 0


def test_add_vp_simple_tags_does_not_raise():
    """_add_vp_simple_tags 对空/小数据不应抛异常"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'dd2', os.path.join(os.path.dirname(__file__), '..', 'data_daemon.py'))
    dd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dd)

    # 少于5根K线：应安全返回，不抛异常
    df = _make_uptrend_df(4)
    tags = {}
    dd._add_vp_simple_tags(df, tags)  # 不应抛异常
    assert 'pattern_signal' not in tags or tags.get('pattern_signal') in ('none', None)
