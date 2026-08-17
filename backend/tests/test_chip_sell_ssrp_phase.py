"""S_SELL 的 SSRP 条件与 phase 联动测试（345号 bearish 方向反转修复，T24）

根因（T23 实证 92 条重放）：_check_s_sell 的 SSRP 条件未与 phase 联动——
BUILDING/WASHING（建仓/洗盘期）股价跌破筹码成本（SSRP）被误判卖出，
暴跌末端触发 bearish 信号、随后反弹致看空假阴性（T+5 +3.26%）。

修复约定：SSRP 条件仅 SHIPPING（出货期）触发；BUILDING/WASHING 期
跌破成本不触发 S_SELL（超跌机会，非主力出货）。
"""
import pandas as pd
from app.engine.chip_strategy_impl import ChipDistributionSignalGenerator


def _mk_sell_checker():
    """构造可直接调用 _check_s_sell 的生成器实例（仅依赖 phase_detector.chip_indicators）"""
    class _FakePhaseDetector:
        chip_indicators = None
    return ChipDistributionSignalGenerator(_FakePhaseDetector())


def _mk_kline(closes, trade_dates=None):
    """构造 K 线 DataFrame（close 列，与 _check_s_sell 用法一致）"""
    n = len(closes)
    dates = trade_dates or [f'2026-07-{10 + i:02d}' for i in range(n)]
    return pd.DataFrame({
        'trade_date': dates,
        'open': closes,
        'high': [c * 1.01 for c in closes],
        'low': [c * 0.99 for c in closes],
        'close': closes,
        'vol': [1000] * n,
    })


def test_ssrp_not_trigger_in_building_phase():
    """建仓期（BUILDING）跌破 SSRP：不应触发 S_SELL（超跌机会非出货）"""
    checker = _mk_sell_checker()
    kline = _mk_kline([10.5, 10.3, 10.1, 9.9, 9.7])  # 连续下跌，跌破 SSRP
    indicators = {'ssrp': 12.29, 'profit_ratio': 0.3, 'rsi': 35}
    result = checker._check_s_sell(kline, [], indicators, {'phase': 'BUILDING'})
    assert result['triggered'] is False, \
        f"BUILDING 期跌破 SSRP 不应触发 S_SELL, 实际: {result['conditions']}"


def test_ssrp_not_trigger_in_washing_phase():
    """洗盘期（WASHING）跌破 SSRP：不应触发 S_SELL"""
    checker = _mk_sell_checker()
    kline = _mk_kline([11.0, 10.8, 10.5, 10.2, 9.9])
    indicators = {'ssrp': 10.8, 'profit_ratio': 0.4, 'rsi': 40}
    result = checker._check_s_sell(kline, [], indicators, {'phase': 'WASHING'})
    assert result['triggered'] is False, \
        f"WASHING 期跌破 SSRP 不应触发 S_SELL, 实际: {result['conditions']}"


def test_ssrp_triggers_in_shipping_phase():
    """出货期（SHIPPING）跌破 SSRP：应触发 S_SELL（主力出货确认）"""
    checker = _mk_sell_checker()
    kline = _mk_kline([15.0, 14.5, 13.8, 13.2, 12.5])
    indicators = {'ssrp': 14.0, 'profit_ratio': 0.85, 'rsi': 45}
    result = checker._check_s_sell(kline, [], indicators, {'phase': 'SHIPPING'})
    assert result['triggered'] is True, \
        f"SHIPPING 期跌破 SSRP 应触发 S_SELL, 实际: {result['conditions']}"


def test_ssrp_still_triggers_without_phase_condition():
    """SSRP 条件本身仍独立触发：非出货期但无其他卖出条件时，SSRP 不应单独触发；
    出货期则 SSRP 是有效卖出条件之一。此处验证出货期 SSRP 条件保留。"""
    checker = _mk_sell_checker()
    kline = _mk_kline([13.0, 12.5, 12.0, 11.5, 11.0])
    # SHIPPING + 无 profit_ratio/rsi 条件（仅 SSRP 触发）
    indicators = {'ssrp': 12.0, 'profit_ratio': 0.2, 'rsi': 30}
    result = checker._check_s_sell(kline, [], indicators, {'phase': 'SHIPPING'})
    assert result['triggered'] is True
    assert any('SSRP' in c for c in result['conditions']), \
        f"SHIPPING 期应含 SSRP 条件, 实际: {result['conditions']}"
