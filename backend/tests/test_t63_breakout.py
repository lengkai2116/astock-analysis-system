"""T6.3 回归测试：breakout_attempts 不应恒为 10（L9）

根因：volume_price_strategy.py:4101 `(recent_high == recent_high).sum()` 序列与自身比较恒真，
导致 breakout_attempts 永远 = min(20,10) = 10。
修复后应统计"近20日触及20日新高的次数"。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest


def _make_df(closes: list[float]):
    n = len(closes)
    return pd.DataFrame({
        'ts_code': ['000001.SZ'] * n,
        'trade_date': pd.date_range('2026-01-01', periods=n).strftime('%Y-%m-%d'),
        'open': closes, 'high': closes, 'low': closes,
        'close': closes, 'vol': [1e5] * n, 'amount': [1e6] * n, 'pct_chg': [0] * n,
    })


@pytest.fixture(scope='module')
def vps():
    from app.engine.framework.volume_price_strategy import VolumePriceStrategy
    return VolumePriceStrategy()


def test_breakout_attempts_not_always_ten(vps):
    """breakout_attempts 应反映真实突破次数，而非恒为 10"""
    # 单边上涨（每天创新高）→ 应有多次突破
    rising = list(np.linspace(10, 20, 25))
    # 长期横盘（无突破）→ 应为 0 或很小
    flat = [10.0] * 25 + [10.5, 10.2, 10.1, 10.0, 9.9]

    tags_rising = vps.get_tags(_make_df(rising))
    tags_flat = vps.get_tags(_make_df(flat))

    ba_rising = tags_rising.get('breakout_attempts')
    ba_flat = tags_flat.get('breakout_attempts')

    # 恒 10 是 bug 标志；单边上涨应接近 20 次触及新高，横盘应远小于此
    assert ba_rising is not None, "breakout_attempts 应存在"
    assert ba_rising != 10 or ba_flat != 10, f"恒为10是bug: rising={ba_rising}, flat={ba_flat}"
    assert ba_flat < ba_rising, f"横盘突破次数应小于上涨: flat={ba_flat}, rising={ba_rising}"
