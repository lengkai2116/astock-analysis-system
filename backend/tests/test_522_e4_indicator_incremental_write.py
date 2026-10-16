"""522号 E4：RAW-1 指标增量写（`cache_indicators_wide(only_latest=True)`）验证。

背景：原 RAW-1 每日把每只股票的**整条历史指标**写入 indicator_ma/macd/other
（三表各 840 万行 ⇒ ≈2520 万行/日）。E4 加显式 `only_latest` 参数：RAW-1 日终传 True
只写最新交易日；迁移/批量脚本默认 False 仍写全历史。

覆盖：① only_latest=True → 三表各只写最新交易日 1 行；② 默认 False → 全历史（兼容）；
③ 单日 df → 正常写；④ 无 trade_date 列 → 不受 only_latest 影响（按原样写）。
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
from app.data.enhanced_cache_manager import EnhancedCacheManager  # noqa: E402

_MA = ['trade_date', 'ma5', 'ma10', 'ma20', 'ma30', 'ma60', 'vol_ma5', 'vol_ma10']
_MACD = ['trade_date', 'macd_dif', 'macd_dea', 'macd_hist']
_OTHER = ['trade_date', 'rsi14', 'kdj_k', 'kdj_d', 'kdj_j',
          'boll_upper', 'boll_mid', 'boll_lower', 'bbi', 'ene_upper', 'ene_lower',
          'nine_buy', 'nine_sell']


class _FakeECM:
    def __init__(self):
        self.writes = []          # [(table, df)]
        self._write_lock = threading.Lock()

    def _insert_from_df(self, table, df):
        self.writes.append((table, df.copy()))
        return len(df)


def _wide_df(dates):
    rows = []
    for i, d in enumerate(dates):
        row = {c: float(i + 1) for c in set(_MA + _MACD + _OTHER) - {'trade_date'}}
        row['trade_date'] = d
        rows.append(row)
    return pd.DataFrame(rows)


def _call(fake, df, only_latest):
    EnhancedCacheManager.cache_indicators_wide(fake, '000001.SZ', df, only_latest=only_latest)


def test_only_latest_writes_single_date_per_table():
    fake = _FakeECM()
    _call(fake, _wide_df(['2026-10-13', '2026-10-14', '2026-10-15']), True)
    tables = [t for t, _ in fake.writes]
    assert set(tables) == {'indicator_ma', 'indicator_macd', 'indicator_other'}
    for _t, wdf in fake.writes:
        assert list(wdf['trade_date']) == ['2026-10-15']
        assert len(wdf) == 1


def test_default_writes_full_history():
    fake = _FakeECM()
    _call(fake, _wide_df(['2026-10-13', '2026-10-14', '2026-10-15']), False)
    for _t, wdf in fake.writes:
        assert list(wdf['trade_date']) == ['2026-10-13', '2026-10-14', '2026-10-15']


def test_single_date_written_normally():
    fake = _FakeECM()
    _call(fake, _wide_df(['2026-10-15']), True)
    assert fake.writes
    for _t, wdf in fake.writes:
        assert list(wdf['trade_date']) == ['2026-10-15']


def test_no_trade_date_column_unaffected():
    fake = _FakeECM()
    df = _wide_df(['2026-10-13', '2026-10-15']).drop(columns=['trade_date'])
    # 缺 trade_date → ma/macd/other 核心列守卫不满足 → 不产生任何写入（原行为）
    _call(fake, df, True)
    assert fake.writes == []
