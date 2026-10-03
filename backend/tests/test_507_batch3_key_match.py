"""507号批次3：键/字符串匹配失效修复验证（#S15）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §四.2。

范围（经活性追踪后的批次3）：
  #S15 dim5 四象限明细键错配——`_QUADRANT_DETAIL_CN` 用 'dv_bond'，但生产者
      `BociasiQuadrantAnalyzer._cache` 实键为 'dv_bond_diff'（bociasi_quadrant.py:189/193）
      → 股债差明细被 _fmt_quadrant 静默丢弃。已改为 'dv_bond_diff'。

**改判批次6（死副本，非生效路径）**：#S13 dim4 SIGNAL_ADJUSTMENT 键错位、
  #S14 dim4 vol_status/cyqkl_status 无生产者——二者均落在 dim4 的平行死副本
  （`ChipPositionManager`/`TradingDomainSignalGenerator` 全仓零实例化；
  生效侧 `chip_strategy_impl`+`chip_indicators`+`framework/chip_position_manager`
  反而无此缺陷）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

_ATLAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'opportunity_atlas')


def test_s15_quadrant_detail_key_aligned():
    """_QUADRANT_DETAIL_CN 含 'dv_bond_diff'（生产者实键），不含旧错键 'dv_bond'"""
    from app.opportunity_atlas.dimensions.dim5_emotion_engine import _QUADRANT_DETAIL_CN
    assert 'dv_bond_diff' in _QUADRANT_DETAIL_CN, '未对齐生产者实键'
    assert 'dv_bond' not in _QUADRANT_DETAIL_CN, '旧错键仍存在'
    assert _QUADRANT_DETAIL_CN['dv_bond_diff'] == '股债差'


def test_s15_fmt_quadrant_renders_dv_bond():
    """_fmt_quadrant 能渲染股债差（构造含 dv_bond_diff 的四象限输入）"""
    from app.opportunity_atlas.dimensions.dim5_emotion_engine import _fmt_quadrant
    qd = {'quadrant': 'MM', 'description': '市场情绪中性',
          'fast_score': 0.5, 'slow_score': 0.5,
          'details': {'dv_bond_diff': 0.35, 'ma20_ratio': 0.56}}
    out = _fmt_quadrant(qd)
    assert '股债差' in out, out
    assert 'MA20强势占比' in out, out


def test_s15_all_7_keys_covered():
    """四象限 7 明细键均能渲染（无错配遗漏）"""
    from app.opportunity_atlas.dimensions.dim5_emotion_engine import (
        _QUADRANT_DETAIL_CN, _fmt_quadrant)
    details = {k: 0.5 for k in _QUADRANT_DETAIL_CN}
    out = _fmt_quadrant({'quadrant': 'LL', 'description': 'x',
                         'fast_score': 0.5, 'slow_score': 0.5, 'details': details})
    for cn in _QUADRANT_DETAIL_CN.values():
        assert cn in out, f'缺 {cn}: {out}'
