"""508号批次2：ChipIndicators 收敛验证（dim4 内嵌 → 外部 app/data/chip_indicators.py 权威）

方案档：`002-方案存档/508-dim4双副本收敛（物理合入清理）.md` §〇 批次2。

覆盖：
  - dim4 的 ChipIndicators 是外部版子类（内嵌 10 方法已删）
  - concentration 切外部 P95-P5 口径（508 Q2 拍板，行为变更）
  - 412 C3 v3.0 RSI 预计算保留（dim4 特化适配层）
  - 内部键兼容（asr/cyqkl/vol_status/rsi 与收敛前一致）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from app.data.chip_indicators import ChipIndicators as ExtChipIndicators  # noqa: E402
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (  # noqa: E402
    ChipIndicators,
)


def _mk_chip_bins():
    """6 档非均匀筹码（验证 P95-P5 与简单 top20% 差异可辨）"""
    return [
        {'price_bin': 8.0, 'chip_ratio': 0.10},
        {'price_bin': 9.0, 'chip_ratio': 0.25},
        {'price_bin': 10.0, 'chip_ratio': 0.30},
        {'price_bin': 11.0, 'chip_ratio': 0.20},
        {'price_bin': 12.0, 'chip_ratio': 0.10},
        {'price_bin': 13.0, 'chip_ratio': 0.05},
    ]


def _mk_kline(n=120):
    idx = pd.date_range('2026-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'open': 10.0, 'high': 10.5, 'low': 9.5, 'close': 10.2,
        'vol': 1000.0, 'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
    })


def test_b2_dim4_chip_indicators_is_external_subclass():
    """dim4 ChipIndicators 为外部版子类（内嵌副本已删）"""
    assert issubclass(ChipIndicators, ExtChipIndicators), '应继承外部权威'
    src = open(ChipIndicators.__module__.replace('.', '/') + '.py',
               encoding='utf-8').read() if False else ''
    import inspect
    m = sys.modules['app.opportunity_atlas.dimensions.dim4_chip_fund_engine']
    # 内嵌私有方法不应残留
    assert not hasattr(m.ChipIndicators, '_calculate_ssrp'), '内嵌 _calculate_ssrp 应已删'
    assert not hasattr(m.ChipIndicators, '_calculate_concentration'), '内嵌 concentration 应已删'
    assert not hasattr(m.ChipIndicators, '_calculate_cyqkl'), '内嵌 cyqkl 应已删'


def test_b2_concentration_p95_aligned_with_external():
    """concentration 切外部 P95-P5（两版同值）"""
    c = ChipIndicators()
    ext = ExtChipIndicators()
    r = c.calculate_all_indicators(_mk_chip_bins(), 10.0, kline_data=_mk_kline())
    r_ext = ext.calculate_all_indicators(_mk_chip_bins(), 10.0, kline_data=_mk_kline())
    assert r['concentration'] == r_ext['concentration'], 'concentration 应与外部一致'
    assert 'concentration_status' in r, '外部 status 族应产出'


def test_b2_rsi_precompute_preserved():
    """412 C3 v3.0 RSI 预计算保留（indicator_other_df 读 rsi14 覆盖本地计算）"""
    c = ChipIndicators()
    kline = _mk_kline()
    other = pd.DataFrame({'rsi14': [55.0]})
    r = c.calculate_all_indicators(_mk_chip_bins(), 10.0, kline_data=kline,
                                   ts_code='000001.SZ', indicator_other_df=other)
    assert r['rsi'] == 55.0, f'应读预计算 RSI: {r["rsi"]}'
    # 无预计算 → 本地计算（外部版 calculate_rsi；平盘可能返回 int 100）
    r2 = c.calculate_all_indicators(_mk_chip_bins(), 10.0, kline_data=kline)
    assert 'rsi' in r2 and isinstance(r2['rsi'], (int, float))


def test_b2_internal_keys_compatible():
    """收敛后内部消费键兼容（asr/cyqkl/vol_status/profit_ratio/ssrp）"""
    c = ChipIndicators()
    r = c.calculate_all_indicators(_mk_chip_bins(), 10.0, kline_data=_mk_kline(),
                                   ts_code='000001.SZ')
    for k in ('ssrp', 'asr', 'concentration', 'profit_ratio', 'cyqkl',
              'cyqkl_status', 'rsi', 'vol_status'):
        assert k in r, f'缺内部消费键 {k}'
    # 值域检查
    assert 0 <= r['asr'] <= 100
    assert r['cyqkl'] >= 0
