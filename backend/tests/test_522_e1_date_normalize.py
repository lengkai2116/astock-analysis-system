"""522号 E1：`_normalize_trade_date` 快速路径验证（2026-10-16）。

背景（profiling）：日终 RAW-3 逐行调用 `_normalize_trade_date`（原实现逐行标量
`pd.to_datetime` ≈72µs/行）占 `_batch_cache_factor_series` 的 98.5%、是 RAW-3 唯一
热点。E1 对**已规范**的字符串走快速路径（严格形态 regex + `strptime` 校日历）：
`YYYY-MM-DD` 直接返回、`YYYYMMDD` 加连字符；其余格式回落 `pd.to_datetime`。

覆盖：① 规范形直接返回；② YYYYMMDD → 加连字符；③ datetime/Timestamp → strftime；
④ None/空串/非日期/日历非法 → None；⑤ 非规范但可解析（2026/08/01、2026-8-1）仍解析；
⑥ 快速路径确实**不调用** `pd.to_datetime`（monkeypatch 断言）。
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.data.factor_precompute as fp  # noqa: E402
import pandas as pd  # noqa: E402

norm = fp.FactorPrecomputeManager._normalize_trade_date


def test_canonical_passthrough():
    assert norm('2026-10-15') == '2026-10-15'
    assert norm('1995-08-30') == '1995-08-30'


def test_compact_to_dashed():
    assert norm('20261015') == '2026-10-15'
    assert norm('19950830') == '1995-08-30'


def test_datetime_and_timestamp():
    assert norm(datetime(2026, 10, 15)) == '2026-10-15'
    assert norm(pd.Timestamp('2026-10-15 15:00:00')) == '2026-10-15'


def test_none_and_invalid():
    assert norm(None) is None
    assert norm('') is None
    assert norm('not-a-date') is None
    assert norm('2026-10-15 15:00:00') == '2026-10-15'   # 可被 pd.to_datetime 解析
    assert norm('2026-13-45') is None                    # 形态像但日历非法（保留原语义）
    assert norm('2026-02-30') is None                    # 同上（strptime 拒绝）


def test_other_parseable_formats_still_via_parser():
    assert norm('2026/08/01') == '2026-08-01'
    assert norm('2026-8-1') == '2026-08-01'


def test_fast_path_avoids_pd_to_datetime(monkeypatch):
    calls = {'n': 0}
    real = fp.pd.to_datetime

    def spy(*args, **kwargs):
        calls['n'] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(fp.pd, 'to_datetime', spy)
    assert norm('2026-10-15') == '2026-10-15'     # 规范形：快速路径
    assert norm('20261015') == '2026-10-15'       # 紧凑形：快速路径
    assert norm(datetime(2026, 10, 15)) == '2026-10-15'  # datetime：快速路径
    assert calls['n'] == 0                        # 三者均未触及 pd.to_datetime
