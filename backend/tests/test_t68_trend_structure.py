"""T6.8 回归测试：S7 趋势线/123法则检测器（308号 P3）

设计依据（308号§3.2）：
- 123法则做多三步：
  假设1：价格向上突破下降趋势线 → 下跌趋势结束
  假设2：回调但不创新低 → 底部抬高
  假设3：向上突破前期反弹高点 → 反向推动浪形成
- 趋势线突破二日原则：当日收盘突破 + 次日仍在外 = 突破确认
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest


def make_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        'ts_code': ['000001.SZ'] * n,
        'trade_date': pd.date_range('2026-01-01', periods=n).strftime('%Y-%m-%d'),
        'open': closes, 'high': [c * 1.03 for c in closes],
        'low': [c * 0.97 for c in closes], 'close': closes,
        'vol': [1e5] * n, 'amount': [1e6] * n, 'pct_chg': [0] * n,
    })


def test_detect_123_breakout():
    """下降趋势→反转：应检测到 123 法则（假设1突破下降趋势线）"""
    from app.engine.framework.trend_structure_detector import TrendStructureDetector
    det = TrendStructureDetector()

    # 构造"近20日高点递减"的下降趋势线 + 最后反转突破：
    # 前段 22 日缓跌（高点递减到 ~12），底部 5 日（制造更低低点），最后 6 日反转突破
    highs_seq = list(np.linspace(20, 12, 22))
    bottom = [11.4, 11.0, 10.6, 10.3, 10.0]   # 底部（近40日最低 = 9.7）
    reversal = [10.6, 11.4, 12.3, 13.2, 14.2, 15.3]  # 反转：突破趋势线 + 突破前段次高(12.36)
    closes = highs_seq + bottom + reversal
    df = make_df(closes)

    result = det.detect(df)
    assert result is not None
    # 反转突破 → 至少不应是 none，且应命中 123 法则或 higher_low
    assert result.get('signal') in ('123_buy_breakout', 'higher_low'), \
        f"应检测到趋势反转信号: {result}"
    assert result.get('strength') == 'strong', f"三假设齐备应为强信号: {result}"


def test_no_signal_on_flat():
    """横盘震荡：不应误报 123 法则"""
    from app.engine.framework.trend_structure_detector import TrendStructureDetector
    det = TrendStructureDetector()

    flat = [10.0] * 40
    df = make_df(flat)

    result = det.detect(df)
    assert result is None or result.get('signal') == 'none', f"横盘不应误报: {result}"


def test_trendline_breakout_two_day_rule():
    """趋势线突破应满足二日原则（连续两日收在趋势线上方）"""
    from app.engine.framework.trend_structure_detector import TrendStructureDetector
    det = TrendStructureDetector()

    # 下跌趋势后单日反弹（未确认）→ 不应算突破
    downtrend = list(np.linspace(20, 10, 25))
    single_spike = [10.5, 10.1, 10.2, 10.0, 9.9]  # 单日脉冲后回落
    df = make_df(downtrend + single_spike)

    result = det.detect(df)
    # 单日脉冲不满足二日原则，不应报强信号
    if result:
        assert result.get('strength') != 'strong', f"单日脉冲不应强信号: {result}"
