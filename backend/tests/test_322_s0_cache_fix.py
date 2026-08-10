"""322号 S0 测试：analyze 缓存读取修复——非交易日应命中最新一条缓存而非实时计算

背景：strategy_analyze.py 使用 get_signal_detail（严格查当日 trade_date）。
非交易日/新交易日（如周六）→ 所有股票缓存 miss → 触发 UnifiedStrategyCore
实时计算（实测单只 4.5-6.1 秒）。对策1：优先当日缓存，miss 回退
get_latest_signal_detail（320号 F3 已实现，取最新一条），毫秒级。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)



def test_read_signal_cached_falls_back_to_latest():
    """get_signal_detail 当日 miss 时应回退 get_latest_signal_detail（非交易日场景）"""
    from app.data import DataManager
    from app.routes import strategy_analyze as sa

    dm = DataManager()
    signals, signal_date = sa._read_signal_cached(dm, '600519.SH')
    assert signals, "非交易日应命中最新缓存（600519 有 08-07 缓存）"
    assert signal_date, "应返回实际数据日期"
    # 关键：不应触发实时计算（有缓存即为通过）


def test_read_signal_cached_unknown_stock_returns_none():
    """完全无缓存股票应返回 (None, None)（允许回退实时计算）"""
    from app.data import DataManager
    from app.routes import strategy_analyze as sa

    dm = DataManager()
    signals, signal_date = sa._read_signal_cached(dm, '000000.SZ')
    assert signals is None and signal_date is None
