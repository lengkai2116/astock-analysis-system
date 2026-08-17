"""350号维度判定标准修正测试

验证估值五级分档、位置中枢上沿判定、量价五态评分。
"""
import json
import pytest


class TestValuationFiveLevels:
    """估值分档细化：extreme_low→极度低估，extreme_high→极度高估"""

    def test_extreme_low_maps_to_extreme_underestimate(self):
        """extreme_low 应映射为"极度低估"（非"低估"）"""
        from app.opportunity_atlas.status_engine import StatusEngine
        se = StatusEngine()
        tags = {'valuation_level': 'extreme_low', 'right_side_confirm': '强确认'}
        dims = se._build_dimensions('TEST.SZ', tags, {})
        assert dims['valuation']['state'] == '极度低估', \
            f"extreme_low 应为极度低估, 实际: {dims['valuation']['state']}"

    def test_low_maps_to_underestimate(self):
        """low 应映射为"低估"（保持不变）"""
        from app.opportunity_atlas.status_engine import StatusEngine
        se = StatusEngine()
        tags = {'valuation_level': 'low', 'right_side_confirm': '强确认'}
        dims = se._build_dimensions('TEST.SZ', tags, {})
        assert dims['valuation']['state'] == '低估', \
            f"low 应为低估, 实际: {dims['valuation']['state']}"

    def test_extreme_high_maps_to_extreme_overestimate(self):
        """extreme_high 应映射为"极度高估"（非"高估"）"""
        from app.opportunity_atlas.status_engine import StatusEngine
        se = StatusEngine()
        tags = {'valuation_level': 'extreme_high', 'right_side_confirm': '强确认'}
        dims = se._build_dimensions('TEST.SZ', tags, {})
        assert dims['valuation']['state'] == '极度高估', \
            f"extreme_high 应为极度高估, 实际: {dims['valuation']['state']}"

    def test_dim_direction_has_five_levels(self):
        """_DIM_DIRECTION 估值维度应有五级映射"""
        from app.opportunity_atlas.status_engine import _DIM_DIRECTION
        val_map = _DIM_DIRECTION.get('valuation', {})
        assert '极度低估' in val_map, "_DIM_DIRECTION 缺极度低估"
        assert '极度高估' in val_map, "_DIM_DIRECTION 缺极度高估"
        assert val_map['极度低估'] > val_map['低估'], "极度低估应比低估更看多"
        assert val_map['极度高估'] < val_map['高估'], "极度高估应比高估更看空"


class TestPositionZhongshuOverride:
    """位置阈值复核：价格高于中枢上沿→站上防守位"""

    def test_price_above_zhongshu_overrides_to_defense(self):
        """价格高于中枢上沿时，即使 price_position=mid_zone 也应判站上防守位"""
        from app.opportunity_atlas.status_engine import StatusEngine
        import json
        se = StatusEngine()
        tags = {
            'price_position': 'mid_zone',
            'right_side_confirm': '强确认',
            # 模拟中枢上沿标签（resistance=11.3）
            'support_resistance': json.dumps({'support': 10.11, 'resistance': 11.3}),
        }
        # 模拟当前价格高于中枢上沿（12.62 > 11.3）
        # 需要 mock get_cached_daily_data 返回当前价格
        import unittest.mock as mock
        import pandas as pd
        mock_df = pd.DataFrame({'close': [12.62], 'trade_date': ['2026-08-14']})
        with mock.patch.object(se.dm, 'get_cached_daily_data', return_value=mock_df):
            dims = se._build_dimensions('300705.SZ', tags, {})
        state = dims.get('position', {}).get('state', '')
        assert state == '站上防守位', \
            f"价格高于中枢上沿应为站上防守位, 实际: {state}"


class TestVolumePriceFiveLevels:
    """量价评分细化：三态→五态"""

    def test_strong_healthy_maps_to_strong_health(self):
        """strong_healthy 应映射为"强健康"（非"健康"）"""
        from app.opportunity_atlas.status_engine import StatusEngine, _DIM_DIRECTION
        # 验证 _DIM_DIRECTION 有五态映射
        vp_map = _DIM_DIRECTION.get('vp', {})
        assert '强健康' in vp_map, "_DIM_DIRECTION 缺强健康"
        assert '严重背离' in vp_map, "_DIM_DIRECTION 缺严重背离"
        assert vp_map['强健康'] > vp_map['健康'], "强健康应比健康更看多"
        assert vp_map['严重背离'] < vp_map['背离'], "严重背离应比背离更看空"

    def test_derive_vp_state_five_levels(self):
        """_derive_vp_state 应支持五态输出"""
        from app.opportunity_atlas.status_engine import StatusEngine
        se = StatusEngine()
        # 测试 strong_healthy
        tags = {'volume_price_fit': 'strong_healthy'}
        state, _, _ = StatusEngine._derive_vp_state({}, tags)
        assert state == '强健康', f"strong_healthy 应为强健康, 实际: {state}"
        # 测试 severe_diverging
        tags = {'volume_price_fit': 'severe_diverging'}
        state, _, _ = StatusEngine._derive_vp_state({}, tags)
        assert state == '严重背离', f"severe_diverging 应为严重背离, 实际: {state}"
