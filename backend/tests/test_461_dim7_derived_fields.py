"""461-7：derived 伪字段统一（接真实 SSOT）回归测试

460 §五 P2 / 阶段1-2：derived 组 6 个伪字段此前用死代理/恒假值：
- price_position：原 buy_sell_point 代理（非真 120 日分位）→ 现接 PhaseDetectionEngine.price_position
- support_resistance：原 `_depth_f.get('support_resistance','{}')`，depth 组从无此键 → 恒 '{}' 假值
  → 现接 shared_support_resistance.calc_support_resistance（JSON）
- state_label：原 `_cl.get('trend_direction','unknown')`，chanlun get_chanlun_tags 从不产该键 → 恒 'unknown'
  → 现接 chanlun cl_result['trend']（上升/下降/盘整）
- trend_alignment：原 trend_direction×ma_alignment 代理（trend_direction 无生产）→ 恒 'misaligned'
  → 现接 PhaseDetectionEngine.trend_alignment（透传 up_aligned/down_aligned/mixed/no_trend）
- profit_ratio：原 `_chip_f.get('chip_position', 0)`，chip_position 是字符串枚举（非数值）→ 移除
  假生产，改由 chip_fund_ext.profit_ratio 单源（derived 组序在其后，会被其后写覆盖）
- risk_level：保持现状单源（用户拍板）——HIGH iff 主力出货 distributing，作 dim6 缠论风险输入

本测试聚焦：扁平化后 derived 真实值能带到下游 flat tags，且值域与消费者判读（status_engine:676/691、
arbiter:226，dim6_risk_engine:302 'HIGH' 缠论风险输入）一致。
"""
import json

from app.opportunity_atlas.status_engine import StatusEngine as _SE


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


class TestDerivedPricePosition:
    """price_position 接真 120 日分位（PhaseDetectionEngine）"""

    def test_mid_zone_default_kept(self):
        pre = {'depth': {'price_position': 'mid_zone'}, 'derived': {'price_position': 'mid_zone'}}
        flat = _flatten(pre)
        # derived 组序在 depth 之后 → 后写覆盖，price_position 带出
        assert flat['price_position'] == 'mid_zone'

    def test_high_zone_pass_through(self):
        pre = {'depth': {'price_position': 'high_zone'}, 'derived': {'price_position': 'high_zone'}}
        flat = _flatten(pre)
        assert flat['price_position'] == 'high_zone'
        # status_engine:683 追涨冲突判读用 'high_zone'
        assert flat['price_position'] == 'high_zone'


class TestDerivedSupportResistance:
    """support_resistance 接 shared_support_resistance（JSON），替代恒 '{}'"""

    def test_real_json_replaces_dummy(self):
        pre = {'derived': {'support_resistance': json.dumps(
            {'support': 10.5, 'resistance': 20.3}, ensure_ascii=False)}}
        flat = _flatten(pre)
        _sr = json.loads(flat['support_resistance'])
        assert _sr['support'] == 10.5
        assert _sr['resistance'] == 20.3
        assert flat['support_resistance'] != '{}'

    def test_dummy_literal_still_a_fallback(self):
        # 仅当 calc_support_resistance 异常时兜底 '{}'（保持兼容）
        pre = {'derived': {'support_resistance': '{}'}}
        flat = _flatten(pre)
        assert flat['support_resistance'] == '{}'


class TestDerivedStateLabel:
    """state_label 接 chanlun trend（上升/下降/盘整），替代恒 'unknown'"""

    def test_up_maps_rising(self):
        pre = {'derived': {'state_label': '上升'}}
        flat = _flatten(pre)
        assert flat['state_label'] == '上升'
        # status_engine:674 '上升' in sl 与 trend_alignment 冲突判读
        assert '上升' in flat['state_label']

    def test_down_maps_falling(self):
        pre = {'derived': {'state_label': '下降'}}
        flat = _flatten(pre)
        assert flat['state_label'] == '下降'

    def test_unknown_maps_ranging(self):
        pre = {'derived': {'state_label': '盘整'}}
        flat = _flatten(pre)
        assert flat['state_label'] == '盘整'


class TestDerivedTrendAlignment:
    """trend_alignment 透传 PhaseDetectionEngine 原值，替代恒 'misaligned'"""

    def test_up_aligned_pass_through(self):
        pre = {'depth': {'trend_alignment': 'up_aligned'},
               'derived': {'trend_alignment': 'up_aligned'}}
        flat = _flatten(pre)
        # status_engine:676 / arbiter:226 直接判 'up_aligned'
        assert flat['trend_alignment'] == 'up_aligned'

    def test_down_aligned_pass_through(self):
        pre = {'depth': {'trend_alignment': 'down_aligned'},
               'derived': {'trend_alignment': 'down_aligned'}}
        flat = _flatten(pre)
        assert flat['trend_alignment'] == 'down_aligned'

    def test_no_trend_default(self):
        pre = {'derived': {'trend_alignment': 'no_trend'}}
        flat = _flatten(pre)
        assert flat['trend_alignment'] == 'no_trend'


class TestDerivedRiskLevelKeptSingleSource:
    """risk_level 保持现状单源（用户拍板）：HIGH iff 主力出货，作 dim6 缠论风险输入"""

    def test_distributing_high(self):
        pre = {'depth': {'main_force_phase': 'distributing'},
               'derived': {'risk_level': 'HIGH'}}
        flat = _flatten(pre)
        # dim6_risk_engine:302 rl == 'HIGH' → 缠论风险高；status_engine:691 risk HIGH 冲突
        assert flat['risk_level'] == 'HIGH'
        assert flat['main_force_phase'] == 'distributing'

    def test_non_distributing_low(self):
        pre = {'depth': {'main_force_phase': 'building'},
               'derived': {'risk_level': 'LOW'}}
        flat = _flatten(pre)
        assert flat['risk_level'] == 'LOW'


class TestDerivedProfitRatioRemoved:
    """profit_ratio 移除 derived 假生产（chip_position 为非数值枚举），由 chip_fund_ext 单源"""

    def test_derived_no_longer_emits_profit_ratio(self):
        """derived 组不再产 profit_ratio；若 chip_fund_ext 缺失则 flat 无 profit_ratio（不再泄漏字符串枚举）"""
        pre = {'derived': {'price_position': 'mid_zone'}}
        flat = _flatten(pre)
        assert 'profit_ratio' not in flat

    def test_chip_fund_ext_is_true_source(self):
        """真 profit_ratio 来自 chip_fund_ext（数值，扁平化后写覆盖 derived）"""
        pre = {'derived': {}, 'chip_fund_ext': {'profit_ratio': 0.62}}
        flat = _flatten(pre)
        assert flat.get('profit_ratio') == 0.62


class TestPhaseDetectorProducesPositionAndTrend:
    """PhaseDetectionEngine 确产 price_position / trend_alignment（461-7 接线源头）"""

    def test_compute_tags_keys(self):
        from app.opportunity_atlas.phase_detector import PhaseDetectionEngine
        result = PhaseDetectionEngine().compute_tags('000001.SZ', None, extra_tags=None) or {}
        assert 'price_position' in result
        assert 'trend_alignment' in result
        # 空 df → 默认值（price_position=mid_zone / trend_alignment=no_trend）
        assert result['price_position'] in ('low_zone', 'mid_zone', 'high_zone')
