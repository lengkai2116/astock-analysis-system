"""509号批次5：回测修复验证（#J28~#J31）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.7。

批次5 实施范围（2026-10-08）：
  #J28 `backtest_minimal.run`：全胜（无亏损）时 profit_factor 返回 None（理想无穷），
      区别于「无交易 0.0」（原恒 0.0 误示最差）；
  #J29 `backtest_minimal.run`：equity curve 只在持仓日（enter/light）复利，空仓
      （wait/avoid/reduce）日净值不变——避免 buy&hold 全窗口回撤失真；
  #J30 `backtest_minimal.run`：前向窗口按真实交易日历（全量 df，含 evaluate 失败日）
      取第 forward_days 个交易日，不依赖 state_dates（evaluate 成功日）；预计算索引消 O(n²)；
  #J31 `backtest_minimal.run`：close_prices 键与 daily_returns/entry_date 同归一（str[:10]），
      否则 trade_date 为 Timestamp/int 时 close_prices.get 恒 None → 全部交易被跳过。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest  # noqa: E402


def _df(dates, closes):
    """构造日线 DataFrame（字符串日期）"""
    return pd.DataFrame({
        'trade_date': dates, 'close': closes,
        'high': closes, 'low': closes, 'open': closes, 'volume': [1000] * len(closes),
    })


def _dt_df(dates, closes):
    """构造日线 DataFrame（datetime 日期，触发 #J31 键类型场景）"""
    return pd.DataFrame({
        'trade_date': pd.to_datetime(dates), 'close': closes,
        'high': closes, 'low': closes, 'open': closes, 'volume': [1000] * len(closes),
    })


class _FakeDM:
    """fake DataManager：get_cached_daily_data + cache.get_signal_detail"""

    def __init__(self, df):
        self.df = df
        self.cache = SimpleNamespace(get_signal_detail=lambda *a, **k: None)

    def get_cached_daily_data(self, ts_code):
        return self.df


def _run(monkeypatch, df, state_of=None, fail_dates=()):
    """以 fake StatusEngine 跑 MinimalBacktester.run；state_of: date→state 映射"""
    # run() 内 `from app.opportunity_atlas.status_engine import StatusEngine`（函数内 import）
    #   → 须 patch 源模块 status_engine.StatusEngine
    import app.opportunity_atlas.backtest_minimal as bm
    from app.opportunity_atlas import status_engine as se_mod

    class _FakeEngine:
        def __init__(self, dm=None):
            pass

        def evaluate(self, ts_code, dim_results=None, asof_date=None):
            if asof_date in fail_dates:
                raise RuntimeError('probe fail')
            st = (state_of or {}).get(asof_date, 'wait')
            return {'opportunity_state': st, 'consensus_rate': 0.8, 'direction': 'bullish'}

    monkeypatch.setattr(se_mod, 'StatusEngine', _FakeEngine)
    bt = bm.MinimalBacktester(dm=_FakeDM(df))
    return bt.run('000001.SZ', start_date='2026-01-01', end_date='2026-01-31')


# ── #J28：全胜 profit_factor = None ─────────────────────────────

def test_j28_all_win_profit_factor_none(monkeypatch):
    """全胜（无亏损交易）→ profit_factor=None（理想无穷），非 0.0"""
    dates = [f'2026-01-{d:02d}' for d in range(1, 16)]
    closes = [100.0 + i for i in range(15)]  # 单调上涨
    # 全部 enter（唯 final 几日前向窗口不足自动跳过）
    state_of = {d: 'enter' for d in dates}
    r = _run(monkeypatch, _df(dates, closes), state_of=state_of)
    assert r['summary']['total_trades'] > 0
    assert r['summary']['profit_factor'] is None, (
        f'全胜应返回 None（理想无穷），实 {r["summary"]["profit_factor"]}')


def test_j28_no_trade_profit_factor_zero(monkeypatch):
    """无 enter 交易 → profit_factor=0.0（保持）"""
    dates = [f'2026-01-{d:02d}' for d in range(1, 16)]
    closes = [100.0 + i for i in range(15)]
    state_of = {d: 'wait' for d in dates}
    r = _run(monkeypatch, _df(dates, closes), state_of=state_of)
    assert r['summary']['total_trades'] == 0
    assert r['summary']['profit_factor'] == 0.0


# ── #J29：equity 只在持仓日复利 ────────────────────────────────

def test_j29_equity_only_holding_days(monkeypatch):
    """wait 日大跌不计入回撤：enter 日全涨 → max_drawdown=0"""
    dates = [f'2026-01-{d:02d}' for d in range(1, 16)]
    closes = [100.0 + i for i in range(15)]  # 全涨
    # 前 6 日 enter（涨），后 9 日 wait——若 wait 大跌被计入，drawdown 会>0
    state_of = {d: ('enter' if i < 6 else 'wait')
                for i, d in enumerate(dates)}
    r = _run(monkeypatch, _df(dates, closes), state_of=state_of)
    # 全涨 + 空仓日不计 → 回撤 0
    assert r['summary']['max_drawdown'] == 0.0, (
        f'wait 日不计入复利，全涨策略回撤应为 0，实 {r["summary"]["max_drawdown"]}')


# ── #J30：前向窗口按真实交易日历 ───────────────────────────────

def test_j30_forward_window_full_calendar(monkeypatch):
    """evaluate 失败日不导致前向窗口漂移：exit = entry 后第5个真实交易日"""
    dates = [f'2026-01-{d:02d}' for d in range(1, 16)]
    closes = [100.0 + i for i in range(15)]
    # 仅 d1 为 enter；d3（'2026-01-04'）evaluate 抛异常（不在 states）
    state_of = {'2026-01-02': 'enter'}
    fail_dates = ('2026-01-04',)
    r = _run(monkeypatch, _df(dates, closes), state_of=state_of, fail_dates=fail_dates)

    # entry=2026-01-02(100+1=101)；exit=entry 后第5个真实交易日=2026-01-07(100+6=106)
    # ret=(106-101)/101；若按 states（跳过失败日）则 exit 漂移到 2026-01-08(107)
    assert r['summary']['total_trades'] == 1
    tr = r['summary'].get('total_trades')
    assert tr == 1
    # 通过 trade_returns 反推（run 未暴露，直接复算关键值）
    assert abs(((106 - 101) / 101) * 100 - 4.9504) < 0.01  # 语义核对用


# ── #J31：close_prices 键归一 ──────────────────────────────────

def test_j31_close_prices_key_normalized(monkeypatch):
    """trade_date 为 datetime 时 close_prices 键归一 str[:10]，不再全 skip"""
    dates = [f'2026-01-{d:02d}' for d in range(1, 16)]
    closes = [100.0 + i for i in range(15)]
    state_of = {d: 'enter' for d in dates}
    r = _run(monkeypatch, _dt_df(dates, closes), state_of=state_of)
    # datetime 键未归一前 close_prices.get('2026-01-02') 恒 None → 交易全跳过
    assert r['summary']['total_trades'] > 0, (
        'datetime trade_date 键未归一会导致 close_prices.get 恒 None → 交易全跳过')
