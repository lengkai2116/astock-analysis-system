"""497号 批次2（P4）：conflict_matrix 共识率 [-1,1] 带符号口径修正

497号要点（详见方案 §九 批次2 + Q2 拍板=方案A 最小语义修正）：
实测共识率由 consensus_engine 的「主导分/总分」得出，**带符号且幅值恒 ≥ 0.5**
（负=空头主导、正=多头主导），不存在 |cr|<0.5 的样本。据此：
- **C5**：原 `consensus_rate < 0.5` 对全部空头恒真（退化「ATR高+RR差+空头」，实测
  1967 次全为 bear）、对多头恒不可达 → 改按幅值 `abs(cr) < 0.6` 判「低共识/分歧」。
- **C10 / 语义类型（追高警示/确认型）**：`>0.7` / `>=0.8` / `>=0.7` 在带符号正区间
  语义自洽 → 数字保持不动（不按 [0,1] 折算）。
- docstring 更正为 [-1,1] 带符号语义。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.conflict_matrix import detect as conflict_detect  # noqa: E402

_SRC = (Path(__file__).resolve().parent.parent / 'app' / 'opportunity_atlas'
        / 'conflict_matrix.py').read_text(encoding='utf-8')


def _dr(atr_pct, rr_value):
    return {'risk': {'status_description': {'risk_level': '高',
                                            'atr_pct': atr_pct, 'rr_value': rr_value}}}


def _c5s(res):
    return [c for c in res['all_conflicts'] if c.startswith('C5:')]


# ── 源码级：docstring 口径更正 ──

def test_docstring_declares_signed_range():
    assert '市场共识度 [-1, 1]' in _SRC
    assert '市场共识度 [0, 1]' not in _SRC


# ── C5：幅值判低共识（不再对全部空头恒真） ──

def test_c5_fires_on_low_magnitude_consensus():
    """|cr| < 0.6（共识接近 0.5 下界 = 分歧最大）→ 触发，正负皆可"""
    for cr in (-0.55, -0.5, 0.5, 0.55):
        assert len(_c5s(conflict_detect({}, {}, _dr(9.0, 0.5), consensus_rate=cr))) == 1, cr


def test_c5_not_fire_on_strong_consensus():
    """|cr| ≥ 0.6（共识明确）→ 不触发（原 <0.5 对全部空头恒真的问题消除）"""
    for cr in (-0.6, -0.8, -1.0, 0.6, 0.8, 1.0):
        assert _c5s(conflict_detect({}, {}, _dr(9.0, 0.5), consensus_rate=cr)) == [], cr


def test_c5_old_bear_universal_behavior_gone():
    """回归：旧口径下「空头 + ATR高 + RR差」恒触发；新口径下强空头共识不触发"""
    # 强空头共识（-0.9）→ 旧逻辑 `-0.9 < 0.5` 恒真触发；新逻辑 |−0.9|≥0.6 → 不触发
    assert _c5s(conflict_detect({}, {}, _dr(9.0, 0.5), consensus_rate=-0.9)) == []


# ── C10 / 语义类型：数字保持（带符号正区间自洽） ──

def test_c10_threshold_unchanged_and_fires_on_positive_consensus():
    # C10 的 divergence_type 取自 structure 维（dim2 status_description）
    dr = {'structure': {'status_description': {'divergence_type': '趋势背驰'}}}
    # 正共识 > 0.7 → 触发（数字未折算）
    res = conflict_detect({}, {}, dr, consensus_rate=0.85)
    assert any(c.startswith('C10:') for c in res['all_conflicts'])
    # ≤ 0.7 → 不触发
    res2 = conflict_detect({}, {}, dr, consensus_rate=0.7)
    assert not any(c.startswith('C10:') for c in res2['all_conflicts'])


def test_semantic_type_thresholds_kept():
    """源码级：语义类型阈值仍为 >=0.8 / >=0.7（未按 [0,1] 折算）"""
    assert 'consensus_rate >= 0.8 and dist_to_prev_high_pct > -3' in _SRC
    assert 'aligned_count >= 4 and consensus_rate >= 0.7' in _SRC
