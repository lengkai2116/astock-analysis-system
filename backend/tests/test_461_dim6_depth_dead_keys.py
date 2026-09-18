"""461-6：depth 组 8 死键接线（真实生产者）回归测试

460 §五 P1 / 阶段1-1：`features['depth']` 8 键从 extractor 错位键名读取 → 恒 None →
`_flatten_pre_feat` 丢弃 → dim6/status_engine 的 main_force_phase/main_force_presence 缺省，
「主力风险/出货/在场」判定永不触发。

用户拍板（2026-09-17）：接线真生产者（PhaseDetectionEngine 产 main_force_phase/phase_confidence、
MainForceScorer 产 fund_flow/capital_nature、_compute_main_force_presence 产主在场证据）+ hold_float_ratio
补生产（top10_holders_cache）+ turnover_rate 接 daily_basic。

本测试聚焦"扁平化能否把 depth 真实键带到下游 tags"（旧死键全 None → 被 _flatten_pre_feat 丢弃的根因），
以及消费方判定值域对齐（'distributing'/'none' 能命中 dim6/status_engine 检查）。
"""
import pytest

from app.opportunity_atlas.status_engine import StatusEngine as _SE
from app.opportunity_atlas.dimensions.dim6_risk_engine import _assess_risk_level


def _flatten(pre_feat: dict) -> dict:
    """复刻 status_engine._flatten_pre_feat 语义（仅保留非 None 值）"""
    flat = {}
    for _g, _data in pre_feat.items():
        if not isinstance(_data, dict):
            continue
        for _k, _v in _data.items():
            if _v is not None:
                flat[_k] = _v
    return flat


class TestFlattenKeepsRealDepthKeys:
    def test_old_dead_depth_all_none_dropped(self):
        """旧实现：depth 8 键全 None → 扁平化整组丢弃（460 死键根因复现）"""
        pre = {'depth': {k: None for k in (
            'hold_float_ratio', 'turnover_rate', 'main_force_phase', 'phase_confidence',
            'fund_flow', 'capital_nature', 'main_force_presence', 'presence_evidence')}}
        flat = _flatten(pre)
        assert 'main_force_phase' not in flat
        assert 'main_force_presence' not in flat

    def test_wired_depth_kept_in_flat(self):
        """接线后：真值进 depth → 扁平化保留，下游 tags 可取到（460 死键修复）"""
        pre = {'depth': {
            'hold_float_ratio': '0.185', 'turnover_rate': '3.20',
            'main_force_phase': 'distributing', 'phase_confidence': '0.72',
            'fund_flow': '5d_outflow', 'capital_nature': 'hot_money',
            'main_force_presence': 'risk', 'presence_evidence': '["融资余额暴增 >50%"]',
        }}
        flat = _flatten(pre)
        assert flat['main_force_phase'] == 'distributing'
        assert flat['main_force_presence'] == 'risk'
        assert flat['capital_nature'] == 'hot_money'
        assert flat['hold_float_ratio'] == '0.185'


class TestConsumerValueDomainAligned:
    def test_dim6_main_force_phase_distributing_rises_high_count(self):
        """dim6 `main_force_phase=='distributing'` → 主力风险 level=高 → high_count≥1（此前恒缺省低）"""
        tags = {'main_force_phase': 'distributing', 'risk_level': 'LOW',
                'fina_health': 'healthy', 'catalyst_event': 'none',
                'valuation_level': 'fair'}
        res = _assess_risk_level(tags)
        mr = next((s for s in res.get('risk_sources', []) if s['name'] == '主力风险'), None)
        assert mr and mr['level'] == '高'
        assert res['level'] in ('中', '高')

    def test_dim6_main_force_phase_absent_low(self):
        """旧死键缺省态：main_force_phase 缺失 → 主力风险 level=低（基线）"""
        tags = {'risk_level': 'LOW', 'fina_health': 'healthy',
                'catalyst_event': 'none', 'valuation_level': 'fair'}
        res = _assess_risk_level(tags)
        mr = next((s for s in res.get('risk_sources', []) if s['name'] == '主力风险'), None)
        assert mr and mr['level'] == '低'

    def test_producer_phase_domain_in_known_enum(self):
        """PhaseDetectionEngine 产 main_force_phase 值域 ∈ {building,washing,lifting,distributing,unknown}，
        消费方检查仅用 'distributing'，对齐"""
        from app.opportunity_atlas.phase_detector import (
            PHASE_BUILDING, PHASE_WASHING, PHASE_LIFTING, PHASE_DISTRIBUTING, PHASE_UNKNOWN,
        )
        domain = {PHASE_BUILDING, PHASE_WASHING, PHASE_LIFTING, PHASE_DISTRIBUTING, PHASE_UNKNOWN}
        assert 'distributing' in domain
        assert 'shipping' not in domain  # 旧 data_daemon risk_level 判 'shipping' 是错值域
        assert 'accumulating' not in domain  # 旧 chip_transfer 判 'accumulating' 是错值域
