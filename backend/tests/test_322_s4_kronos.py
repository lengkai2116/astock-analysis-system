"""322号 S4：Kronos 可选修正情景概率（AI预测仅供参考，非实证）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)


from app.opportunity_atlas.advice_builder import build_operation_advice  # noqa: E402


def test_kronos_bullish_boosts_trend_continuation():
    dims = {'factor': {'trend': 'up'}}
    kronos = {'direction': 'bullish', 'confidence': 0.8}
    a1 = build_operation_advice('T.SZ', dims, [], None)
    a2 = build_operation_advice('T.SZ', dims, [], None, kronos=kronos)
    p_a1 = next(s['prob'] for s in a1['scenarios'] if s['id'] == 'a')
    p_a2 = next(s['prob'] for s in a2['scenarios'] if s['id'] == 'a')
    assert p_a2 > p_a1, "Kronos 看多应提升趋势延续概率"
    assert 'kronos_note' in a2, "应标注 AI 预测仅供参考"


def test_kronos_bearish_boosts_breakdown():
    """Kronos 看空（规则中性/看多冲突）→ 破位下行概率应上移"""
    dims = {'factor': {'trend': 'up'}}
    kronos = {'direction': 'bearish', 'confidence': 0.9}
    a1 = build_operation_advice('T.SZ', dims, [], None)
    a2 = build_operation_advice('T.SZ', dims, [], None, kronos=kronos)
    p_c1 = next(s['prob'] for s in a1['scenarios'] if s['id'] == 'c')
    p_c2 = next(s['prob'] for s in a2['scenarios'] if s['id'] == 'c')
    assert p_c2 > p_c1, "Kronos 看空应提升破位下行概率"


def test_kronos_bearish_multi_dim_strong():
    """Kronos 看空 + 多维看空 → 破位下行概率显著（>30%）"""
    dims = {
        'chanlun': {'direction': 'down'}, 'volume_price': {'direction': 'down'},
        'chip': {'direction': 'down'}, 'emotion': {'direction': 'down'},
        'factor': {'trend': 'down'},
    }
    a = build_operation_advice('T.SZ', dims, [], None,
                               kronos={'direction': 'bearish', 'confidence': 0.9})
    p_c = next(s['prob'] for s in a['scenarios'] if s['id'] == 'c')
    assert p_c > 0.3, f"多维看空+Kronos 看空应显著提升破位概率，实际 {p_c}"


def test_no_kronos_no_note():
    a = build_operation_advice('T.SZ', {'factor': {'trend': 'up'}}, [], None)
    assert 'kronos_note' not in a
