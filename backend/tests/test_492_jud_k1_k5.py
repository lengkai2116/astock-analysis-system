"""492号 K1-K5 定向测试（JUD 五通路「键名/API 错位致机制空转」修复回归）

覆盖：
  K1  advice_engine 2% 风险预算仓位（entry_price 传入 → risk_budget_position 生效）
  K2  status_engine._normalize_emotion_phase 读 sentiment_phase + 就近归并
  K3  consensus_engine.compute weights 形参生效（市场状态族权重接线）
  K4  status_engine._assemble advice 白名单含 entry_zone/target_zone
  K5  dim_adapter.convert_to_factors 的 classify_attribute 真实执行（无 NameError）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.opportunity_atlas.advice_engine import compute_advice  # noqa: E402
from app.opportunity_atlas.consensus_engine import compute as consensus_compute  # noqa: E402
from app.opportunity_atlas.dim_adapter import convert_to_factors  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine, _normalize_emotion_phase  # noqa: E402

_L0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
       'hard_veto': False, 'emotion_position_cap': None}


def _dim_results_with_risk(close_support=10.2, entry=11.0):
    return {
        'risk': {'status_description': {'support_price': close_support,
                                        'resistance_price': 13.0, 'rr_value': 2.5},
                 'judgment': {'risk_level': '低', 'continuous_value': 0.5}},
        'volume_price': {'status_description': {'entry_zone': [10.5, 11.0],
                                                'target_zone': [12.0, 13.0]},
                         'judgment': {'state': '健康', 'continuous_value': 0.7}},
    }


# ── K1：2% 风险预算仓位 ──────────────────────────────────────────────

def test_k1_risk_budget_position_active():
    """entry_price 传入 → 仓位 = min(0.30, 100万×2% /(11.0-10.2) ×11.0 /100万)"""
    advice = compute_advice(60.0, {}, _L0, _dim_results_with_risk(),
                            '000001.SZ', entry_price=11.0)
    assert advice.get('risk_budget_position') is not None
    expect = min(0.30, (1000000.0 * 0.02) / 0.8 * 11.0 / 1000000.0)  # 0.275
    assert abs(advice['risk_budget_position'] - expect) < 1e-9
    assert advice['max_position_ratio'] <= advice['risk_budget_position']


def test_k1_risk_budget_none_without_entry_price():
    """入口价缺失（无 daily_df、调用方未传）→ risk_budget_position 不产，且不触发数据访问"""
    advice = compute_advice(60.0, {}, _L0, _dim_results_with_risk(), '000001.SZ')
    assert 'risk_budget_position' not in advice


# ── K2：情绪阶段归一化 ───────────────────────────────────────────────

def test_k2_reads_sentiment_phase_not_emotion_phase():
    """真实生产键 sentiment_phase 生效；emotion_phase（无生产者）不再被优先读取"""
    assert _normalize_emotion_phase({'sentiment_phase': 'ice'}) == 'ice'
    assert _normalize_emotion_phase({'sentiment_phase': 'ebb'}) == 'ebb'
    assert _normalize_emotion_phase({'sentiment_phase': 'climax'}) == 'climax'


def test_k2_nearby_merge_mapping():
    """就近归并：sprout→recovery、ferment→positive、regression/neutral→normal"""
    assert _normalize_emotion_phase({'sentiment_phase': 'sprout'}) == 'recovery'
    assert _normalize_emotion_phase({'sentiment_phase': 'ferment'}) == 'positive'
    assert _normalize_emotion_phase({'sentiment_phase': 'regression'}) == 'normal'
    assert _normalize_emotion_phase({'sentiment_phase': 'neutral'}) == 'normal'


def test_k2_fallback_and_legacy_key():
    """未命中/空值回落 normal；兼容旧键 emotion_phase"""
    assert _normalize_emotion_phase({}) == 'normal'
    assert _normalize_emotion_phase({'sentiment_phase': ''}) == 'normal'
    assert _normalize_emotion_phase({'sentiment_phase': 'unknown_xxx'}) == 'normal'
    assert _normalize_emotion_phase({'emotion_phase': 'ice'}) == 'ice'


def test_k2_l0_emotion_cap_uses_sentiment_phase():
    """L0b2 情绪仓位上限随 sentiment_phase 变化（原恒 normal=0.60）"""
    eng = StatusEngine.__new__(StatusEngine)
    eng.cfg = {'l0': {'emotion_position_cap': {'ice': 0.10, 'ebb': 0.30, 'normal': 0.60,
                                              'recovery': 0.60, 'positive': 0.80}}}
    class _DM:  # 避免真读日线缓存
        def get_cached_daily_basic(self, *a, **k):
            return None
    eng.dm = _DM()
    eng.registry = {}
    ice = eng._apply_l0('000001.SZ', {'sentiment_phase': 'ice'}, None)
    normal = eng._apply_l0('000001.SZ', {'sentiment_phase': 'neutral'}, None)
    assert ice['emotion_position_cap'] == 0.10
    assert normal['emotion_position_cap'] == 0.60


# ── K3：consensus weights 形参生效 ───────────────────────────────────

_F = {'chip_fund': {'direction': 1, 'strength': 0.8},
      'structure': {'direction': -1, 'strength': 0.8},
      'signal_confirm': {'direction': 1, 'strength': 0.6},
      'vp': {'direction': 1, 'strength': 0.8},
      'valuation': {'direction': 1, 'strength': 0.5},
      'emotion': {'direction': 1, 'strength': 0.5},
      'risk': {'direction': 1, 'strength': 0.5},
      'factor': {'direction': 1, 'strength': 0.5}}
_REL = {k: 0.7 for k in _F}

_UP = {'signal': 0.15, 'structure': 0.20, 'vp': 0.15, 'chip_fund': 0.10,
       'emotion': 0.10, 'risk': 0.15, 'valuation': 0.15}
_DOWN = {'signal': 0.10, 'structure': 0.10, 'vp': 0.10, 'chip_fund': 0.10,
         'emotion': 0.10, 'risk': 0.30, 'valuation': 0.20}


def test_k3_regime_weights_take_effect():
    """不同 MARKET_REGIME_WEIGHTS 档 → consensus_rate 不同（原 weights 形参被忽略）"""
    up = consensus_compute(_F, _REL, _UP, 'normal')['consensus_rate']
    down = consensus_compute(_F, _REL, _DOWN, 'normal')['consensus_rate']
    assert up != down


def test_k3_weights_none_equals_legacy():
    """weights=None → 族权重等权，result 与「仅 STATE_WEIGHTS + 等权」等价"""
    r = consensus_compute(_F, _REL, None, 'normal')
    # reliability_factor 独立于权重（=族可靠性均值）
    assert r['reliability_factor'] == 0.7
    # 与显式等权 0.1 的 regime dict 等价
    eq = {k: 0.1 for k in ('signal', 'structure', 'vp', 'chip_fund',
                           'emotion', 'risk', 'valuation', 'factor')}
    assert abs(r['consensus_rate']
               - consensus_compute(_F, _REL, eq, 'normal')['consensus_rate']) < 1e-9


def test_k3_state_weight_recorded_is_family_weight():
    """group_details.state_weight 记录族级权重（state × regime），非裸 STATE_WEIGHTS"""
    r = consensus_compute(_F, _REL, _UP, 'normal')
    gd = r['group_details']['valuation_quality']
    assert abs(gd['state_weight'] - round(0.15 * 0.15, 4)) < 1e-9


# ── K4：advice 白名单 ────────────────────────────────────────────────

def test_k4_assemble_advice_whitelist_includes_zones():
    """_assemble 将 entry_zone/target_zone/risk_budget_position 并入 advice_params（原白名单截断）"""
    l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [], 'hard_veto': False}
    l2 = {'opportunity_state': 'wait', 'state_evidence': [], 'consensus_rate': 0.5,
          'direction': 'neutral', 'bullish_dims': 0.0, 'bearish_dims': 0.0,
          'conflict_evidence': [], 'final_score': 60.0, 'semantic_type': '',
          'reliability_summary': {}, 'consensus_detail': {},
          'advice': {'max_position_ratio': 0.4, 'stop_loss_price': 10.2,
                     'target_price': 13.0, 'risk_reward_ratio': 2.5,
                     'invalidation_conditions': [],
                     'entry_zone': [10.5, 11.0], 'target_zone': [12.0, 13.0],
                     'risk_budget_position': 0.275}}
    eng = StatusEngine.__new__(StatusEngine)
    eng.registry = {}
    row = eng._assemble('000001.SZ', {}, None, l0, l2, [], None)
    ap = __import__('json').loads(row['advice_params'])
    assert ap.get('entry_zone') == [10.5, 11.0]
    assert ap.get('target_zone') == [12.0, 13.0]
    assert ap.get('risk_budget_position') == 0.275


# ── K5：signal_confirm 真实执行 ──────────────────────────────────────

def test_k5_signal_confirm_no_nameerror():
    """convert_to_factors 不再因未定义 dims 恒走 except（evidence 非空路径可达）"""
    dr = {
        'structure': {'status_description': {},
                      'judgment': {'structure': '上升', 'overall_direction': 1,
                                   'continuous_value': 0.65}},
        'volume_price': {'status_description': {},
                         'judgment': {'state': '健康', 'continuous_value': 0.7}},
        'chip_fund': {'status_description': {},
                      'judgment': {'direction': 'inflow', 'continuous_value': 0.6}},
        'emotion': {'status_description': {'market_phase': 'recovery'},
                    'judgment': {'continuous_value': 0.5}},
        'risk': {'status_description': {},
                 'judgment': {'risk_level': '低', 'continuous_value': 0.5}},
        'valuation': {'status_description': {},
                      'judgment': {'valuation_level': {'value': 'low'},
                                   'continuous_value': 0.6}},
    }
    tags = {'right_side_confirm': '强确认', 'buy_sell_point': 'none',
            'price_position': 'mid'}
    f = convert_to_factors(dr, tags)
    # classify_attribute 真实运行 → evidence 携带分类 detail（原恒 []）
    assert f['signal_confirm']['evidence']
    assert f['signal_confirm']['evidence'][0]
