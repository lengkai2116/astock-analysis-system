"""491号：情绪方向口径统一（用户 2026-09-27 拍板「统一逆势」）+ C3 判据改按阶段

覆盖：
  1. 两处 DIM_DIRECTION 的 emotion 行与生效表 _EMOTION_DIRECTION 完全一致（逆势口径）；
  2. C3 判据由 `emotion_direction == -1`（顺势）改为按 dim5 sd.market_phase ∈ 冷区（ice/ebb）
     —— 沿用 490 号修复后 C3 可达，且不再与「冰点」文案矛盾；
  3. R9：情绪极端档（退潮/高潮）触发 extreme_panic 权重切换保持现状（决策 ①）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas import dim_adapter  # noqa: E402
from app.opportunity_atlas import status_engine as se_mod  # noqa: E402
from app.opportunity_atlas.conflict_matrix import detect as conflict_detect  # noqa: E402

# 统一后的逆势口径（与 _EMOTION_DIRECTION 生效表一致）
_UNIFIED = {'冰点': 1, '萌芽': 1, '发酵': 1, '复苏': 1, '正常': 0, '中性': 0,
            '回归': 0, '退潮': 0, '退潮·高潮': 0, '消极': 0, '高潮': -1, '积极': -1}


def test_emotion_rows_unified_contrarian():
    assert dim_adapter.DIM_DIRECTION['emotion'] == _UNIFIED
    assert se_mod._DIM_DIRECTION['emotion'] == _UNIFIED
    # 逆势口径的三个关键点（原顺势表为反向/不同）
    assert _UNIFIED['冰点'] == 1 and _UNIFIED['高潮'] == -1 and _UNIFIED['退潮'] == 0


def test_engine_state_to_cn_covers_all_phases():
    """dim5 PHASE_MAP 全量阶段都能映射到中文键且在统一表中有方向"""
    for en in ('ice', 'sprout', 'ferment', 'climax', 'ebb', 'regression', 'neutral'):
        cn_val = dim_adapter.ENGINE_STATE_TO_CN['emotion'].get(en)
        assert cn_val, f'{en} 缺中文映射'
        assert cn_val in _UNIFIED, f'{en}→{cn_val} 应在统一表中有方向'


def _dr(market_phase, divergence_type='top', composite=0.8):
    return {
        'structure': {'status_description': {'multi_level': None}},
        'volume_price': {'status_description': {'divergence_type': divergence_type,
                                                'vol_ratio_value': 1.0}},
        'chip_fund': {'status_description': {}, 'judgment': {}},
        'emotion': {'status_description': {'market_phase': market_phase}, 'judgment': {}},
        'risk': {'status_description': {'atr_pct': 0.2, 'rr_value': 2.0}},
        'valuation': {'status_description': {'composite_rating': composite,
                                             'asset_anchor_rating': 0,
                                             'earnings_anchor_rating': 0}},
    }


def test_c3_fires_on_cold_zone_phase():
    """C3：情绪冷区(ice/ebb) + 低估 + 顶部背离 → warn（原顺势判据下不可达）"""
    dims_factor = {'valuation': {'direction': 1}}
    for phase in ('ice', 'ebb'):
        res = conflict_detect(dims_factor, {}, _dr(phase), consensus_rate=0.5)
        assert any(c.startswith('C3:') for c in res['all_conflicts']), (phase, res)


def test_c3_not_fire_on_warm_or_hot_phase():
    dims_factor = {'valuation': {'direction': 1}}
    for phase in ('ferment', 'climax', 'regression', 'neutral'):
        res = conflict_detect(dims_factor, {}, _dr(phase), consensus_rate=0.5)
        assert not any(c.startswith('C3:') for c in res['all_conflicts']), (phase, res)


def test_c3_requires_low_valuation_and_top_divergence():
    """C3 的三个必要条件：冷区 + 估值看多(L1 direction=1) + 量价顶背离"""
    # 估值非看多（direction=0）→ 不触发
    assert not any(c.startswith('C3:') for c in
                   conflict_detect({'valuation': {'direction': 0}}, {}, _dr('ice'),
                                   consensus_rate=0.5)['all_conflicts'])
    # 非顶背离 → 不触发
    assert not any(c.startswith('C3:') for c in
                   conflict_detect({'valuation': {'direction': 1}}, {}, _dr('ice', divergence_type='bottom'),
                                   consensus_rate=0.5)['all_conflicts'])


def test_r9_extreme_panic_weights_kept():
    """R9 决策①：退潮/高潮 → extreme_panic 权重档保持现状（值可经 yaml 调，属 485-5）"""
    regimes = se_mod.StatusEngine.MARKET_REGIME_WEIGHTS
    assert 'extreme_panic' in regimes
    assert regimes['extreme_panic']['risk'] == 0.40
    assert regimes['extreme_panic']['valuation'] == 0.25
    # 触发面：仅「退潮/高潮」（冰点不切档）
    assert se_mod.StatusEngine._detect_market_regime({}, {'emotion': {'state': '退潮'}}) == 'extreme_panic'
    assert se_mod.StatusEngine._detect_market_regime({}, {'emotion': {'state': '高潮'}}) == 'extreme_panic'
    assert se_mod.StatusEngine._detect_market_regime({}, {'emotion': {'state': '冰点'}}) == 'ranging'
