"""497号 批次1（P3）：conflict_matrix C5 ATR 阈值 0.7→8.0（百分数语义）

497号要点（详见方案 §九 批次1）：
- C5「ATR高+盈亏比差+低共识→warn」的 atr_pct 阈值由 0.7（小数语义）改为 8.0
  （dim6 产出百分数：3.98=3.98%），对齐 Wiki《ATR止损》高波动 8-12% 与
  495-b6 advice/dim_adapter 折减下限；>8.0 严格大于（8.0 不触发）。
- 文案同步 `ATR{:.2f}%>8.0`（加 % 标识百分数）。
- consensus_rate < 0.5 本批不动（属批次2 P4 换算范围）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.conflict_matrix import detect as conflict_detect  # noqa: E402


def _dr(atr_pct, rr_value):
    """最小 dim_results：仅 risk 维（C5 取数源 risk.status_description.atr_pct/rr_value）"""
    return {
        'risk': {
            'status_description': {
                'risk_level': '高', 'atr_pct': atr_pct, 'rr_value': rr_value,
            },
        },
    }


def _c5s(res):
    return [c for c in res['all_conflicts'] if c.startswith('C5:')]


def test_c5_old_threshold_value_now_does_not_fire():
    """旧阈值 0.71（=0.71%）在 8.0 语义下属低波动 → 不再触发（修复恒真）"""
    res = conflict_detect({}, {}, _dr(0.71, 0.5), consensus_rate=0.0)
    assert _c5s(res) == []


def test_c5_not_fire_below_or_at_8():
    """严格大于：7.5 与 8.0 均不触发"""
    for v in (7.5, 8.0):
        res = conflict_detect({}, {}, _dr(v, 0.5), consensus_rate=0.0)
        assert _c5s(res) == [], f'atr={v} 不应触发 C5'


def test_c5_fire_above_8_with_pct_text():
    """8.5（=8.5% 高波动）触发 C5，文案含 % 与 8.0"""
    res = conflict_detect({}, {}, _dr(8.5, 0.5), consensus_rate=0.0)
    c5 = _c5s(res)
    assert len(c5) == 1
    assert '%>8.0' in c5[0]


def test_c5_still_requires_low_rr_and_low_consensus():
    """其余条件语义不变：rr≥1.0 或 consensus≥0.5 均不触发"""
    assert _c5s(conflict_detect({}, {}, _dr(9.0, 1.5), consensus_rate=0.0)) == []
    assert _c5s(conflict_detect({}, {}, _dr(9.0, 0.5), consensus_rate=0.6)) == []
