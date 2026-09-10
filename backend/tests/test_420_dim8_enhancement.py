"""420号方案回归测试：dim8状态总结引擎消费面增强

覆盖 6 项增强：
- 增强1: 共识率置信度加权（continuous_value 影响权重）
- 增强2: 盈亏比 rr 状态修正（上修/下修）
- 增强3: 信号老化降级（lifecycle_stage 末期 → strong_confirm 降级）
- 增强4: 冲突检测扩展（散户减仓/形态背离/波动率放大 3 条新规则）
- 增强5: 综合文字富化（盈亏比/支撑压力/温度/生命周期锚点）
- 增强6: 数据完整度警示（audit.confidence 均值 <0.7）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    _calc_consensus_rate,
    _derive_status_bar,
    _detect_conflicts,
    _extract_dim_confidence,
    _extract_dim_rr,
    _generate_text,
    _is_signal_decaying,
)

# ── 基础 mock dim_results（对齐 000001.SZ 实测结构）─────────

def _mk_dim_results(overrides=None):
    """构造 dim_results：全部灯色 yellow + continuous_value 0.5 基准"""
    base = {}
    for dim in ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']:
        base[dim] = {
            'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                         'continuous_value': 0.5},
            'status_description': {'plain': ''},
            'audit': {'confidence': 0.8},
        }
    if overrides:
        for dim, patch in overrides.items():
            d = base.get(dim, {})
            if 'judgment' in patch:
                d.setdefault('judgment', {}).update(patch['judgment'])
            if 'status_description' in patch:
                d.setdefault('status_description', {}).update(patch['status_description'])
            if 'audit' in patch:
                d.setdefault('audit', {}).update(patch['audit'])
            base[dim] = d
    return base


# ── 增强1: 共识率置信度加权 ────────────────────────────────

class TestConfidenceWeighted:

    def test_consensus_rate_confidence_weighted(self):
        """连续置信度高的看多维度 → 共识率高于等权"""
        dr = _mk_dim_results({
            'structure': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                       'continuous_value': 0.9}},
            'volume_price': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                          'continuous_value': 0.9}},
            'signal': {'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                                    'continuous_value': 0.5}},
            'chip_fund': {'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                                       'continuous_value': 0.5}},
            'emotion': {'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                                     'continuous_value': 0.5}},
            'risk': {'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                                  'continuous_value': 0.5}},
            'valuation': {'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                                       'continuous_value': 0.5}},
        })
        rate = _calc_consensus_rate(dr)
        # structure+volume_price 高置信度看多 → 应 > 0.5
        assert rate > 0.5, f"高置信度看多应推高共识率，实际 {rate}"

    def test_consensus_rate_low_confidence_bull_penalized(self):
        """看多但置信度低 → 共识率低于高置信度场景"""
        dr_low = _mk_dim_results({
            'structure': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                       'continuous_value': 0.1}},
            'volume_price': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                          'continuous_value': 0.1}},
        })
        dr_high = _mk_dim_results({
            'structure': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                       'continuous_value': 0.9}},
            'volume_price': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                          'continuous_value': 0.9}},
        })
        assert _calc_consensus_rate(dr_high) > _calc_consensus_rate(dr_low)

    def test_consensus_rate_missing_confidence_fallback(self):
        """continuous_value 缺失 → 回退等权等价（全 yellow → 0.5）"""
        dr = _mk_dim_results({})
        for dim in dr:
            dr[dim]['judgment'].pop('continuous_value', None)
        rate = _calc_consensus_rate(dr)
        assert rate == 0.5

    def test_extract_dim_confidence_fallback(self):
        """_extract_dim_confidence 缺失回退 0.5"""
        assert _extract_dim_confidence(_mk_dim_results({}), 'signal') == 0.5
        dr = _mk_dim_results({'signal': {'judgment': {'continuous_value': 0.8}}})
        assert _extract_dim_confidence(dr, 'signal') == 0.8


# ── 增强2: 盈亏比状态修正 ──────────────────────────────────

class TestRRAdjustment:

    @staticmethod
    def _bull_dr(rr_value):
        """4 维看多 + rr → 触发 trend_confirm 场景"""
        return _mk_dim_results({
            'signal': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                    'continuous_value': 0.7}},
            'structure': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                       'continuous_value': 0.7}},
            'volume_price': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                          'continuous_value': 0.7}},
            'chip_fund': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                       'continuous_value': 0.7}},
            'risk': {'status_description': {'rr_value': rr_value}},
        })

    def test_rr_high_upgrades_status(self):
        """rr=2.5 高盈亏比 → 上修到 strong_confirm"""
        dr = self._bull_dr(2.5)
        rate = _calc_consensus_rate(dr)
        bar = _derive_status_bar(dr, rate, [])
        assert bar == 'strong_confirm', f"rr=2.5 应上修 strong_confirm，实际 {bar}"

    def test_rr_low_downgrades_status(self):
        """rr=0.5 低盈亏比 → 高共识下修"""
        dr = self._bull_dr(0.5)
        rate = _calc_consensus_rate(dr)
        bar = _derive_status_bar(dr, rate, [])
        assert bar in ('light_confirm', 'neutral', 'trend_confirm'), \
            f"rr=0.5 应下修，实际 {bar}"
        # 低盈亏比不应出现 strong_confirm
        assert bar != 'strong_confirm'

    def test_rr_mid_no_change(self):
        """rr=1.5（1R-2R 区间）→ 不触发修正"""
        dr = self._bull_dr(1.5)
        rate = _calc_consensus_rate(dr)
        bar = _derive_status_bar(dr, rate, [])
        assert bar == 'strong_confirm'  # 4 维看多高置信 → 自然 strong_confirm

    def test_extract_dim_rr(self):
        """_extract_dim_rr 提取与缺失"""
        dr = _mk_dim_results({'risk': {'status_description': {'rr_value': 1.86}}})
        assert _extract_dim_rr(dr) == 1.86
        assert _extract_dim_rr(_mk_dim_results({})) is None


# ── 增强3: 信号老化降级 ────────────────────────────────────

class TestSignalDecay:

    def test_signal_decaying_blocks_strong_confirm(self):
        """lifecycle_stage=末期 + 强共识 → strong_confirm 降级 light_confirm"""
        dr = _mk_dim_results({
            'signal': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                    'continuous_value': 0.8},
                       'status_description': {'lifecycle_stage': '末期'}},
            'structure': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                       'continuous_value': 0.8}},
            'volume_price': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                          'continuous_value': 0.8}},
            'chip_fund': {'judgment': {'overall_light': 'green', 'overall_direction': 1,
                                       'continuous_value': 0.8}},
        })
        rate = _calc_consensus_rate(dr)
        bar = _derive_status_bar(dr, rate, [])
        assert bar == 'light_confirm', f"信号老化应降级，实际 {bar}"

    def test_is_signal_decaying(self):
        """_is_signal_decaying 识别末期/维护不佳"""
        dr_end = _mk_dim_results({'signal': {'status_description': {'lifecycle_stage': '末期'}}})
        assert _is_signal_decaying(dr_end)
        dr_healthy = _mk_dim_results({'signal': {'status_description': {'lifecycle_stage': '初期'}}})
        assert not _is_signal_decaying(dr_healthy)
        dr_maint = _mk_dim_results({'signal': {'judgment': {'maintenance': {'status': 'decay'}}}})
        assert _is_signal_decaying(dr_maint)


# ── 增强4: 冲突检测扩展 ────────────────────────────────────

class TestNewConflicts:

    def test_retail_overheat_conflict(self):
        """散户减仓 + 结构上升 → 冲突'散户资金在减'"""
        dr = _mk_dim_results({
            'structure': {'judgment': {'overall_direction': 1}},
            'chip_fund': {'status_description': {'retail_institution': '散户减仓'}},
        })
        conflicts = _detect_conflicts(dr)
        descs = [c['description'] for c in conflicts]
        assert any('散户资金在减' in d for d in descs)

    def test_pattern_divergence_conflict(self):
        """量价形态空头 + 信号确认 → 冲突'形态与信号背离'"""
        dr = _mk_dim_results({
            'signal': {'judgment': {'overall_direction': 1}},
            'volume_price': {'status_description': {'pattern': '空头排列'}},
        })
        conflicts = _detect_conflicts(dr)
        descs = [c['description'] for c in conflicts]
        assert any('形态与信号背离' in d for d in descs)

    def test_volatility_accel_conflict(self):
        """波动率 high + 结构下降 → 冲突'下跌可能加速'"""
        dr = _mk_dim_results({
            'structure': {'judgment': {'overall_direction': -1}},
            'risk': {'status_description': {'volatility_level': 'high'}},
        })
        conflicts = _detect_conflicts(dr)
        descs = [c['description'] for c in conflicts]
        assert any('下跌可能加速' in d for d in descs)

    def test_legacy_5_conflicts_kept(self):
        """原 5 条冲突规则仍在（回归）"""
        dr = _mk_dim_results({
            'structure': {'judgment': {'overall_direction': 1}},
            'chip_fund': {'judgment': {'phase': 'distributing'}},
        })
        conflicts = _detect_conflicts(dr)
        descs = [c['description'] for c in conflicts]
        assert any('主力在出货' in d for d in descs), "原规则1丢失"


# ── 增强5: 综合文字富化 ────────────────────────────────────

class TestTextRichness:

    def test_text_anchors_richness(self):
        """_generate_text 含盈亏比/支撑压力锚点"""
        dr = _mk_dim_results({
            'risk': {'status_description': {'rr_value': 1.86,
                                            'support_price': 11.5,
                                            'resistance_price': 12.08}},
            'emotion': {'status_description': {'temperature': '55/100'}},
            'signal': {'status_description': {'lifecycle_days': 15}},
        })
        text = _generate_text(dr, 'neutral', 0.5, [])
        assert '盈亏比1.86' in text, "缺盈亏比锚点"
        assert '支撑11.5/压力12.08' in text, "缺支撑压力锚点"

    def test_text_signal_decay_notice(self):
        """信号老化 → 文字含'信号老化'提示"""
        dr = _mk_dim_results({'signal': {'status_description': {'lifecycle_stage': '末期'}}})
        text = _generate_text(dr, 'neutral', 0.5, [])
        assert '信号老化' in text


# ── 增强6: 数据完整度警示 ──────────────────────────────────

class TestDataWarning:

    def test_audit_data_warning(self):
        """audit.confidence 均值 <0.7 → data_warning 出现"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
        dr = _mk_dim_results({})
        for dim in dr:
            dr[dim]['audit']['confidence'] = 0.5
        result = Dim8SummaryEngine().evaluate({}, {}, {}, {'dim_results': dr})
        sd = result['status_description']
        assert 'data_warning' in sd, "数据完整度低应提示"
        assert '数据完整度偏低' in sd['data_warning']

    def test_audit_no_warning_when_complete(self):
        """audit.confidence 全高 → 无 data_warning"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
        dr = _mk_dim_results({})  # 默认 0.8
        result = Dim8SummaryEngine().evaluate({}, {}, {}, {'dim_results': dr})
        sd = result['status_description']
        assert 'data_warning' not in sd
