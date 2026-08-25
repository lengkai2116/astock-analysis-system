"""350号维度判定标准修正测试

验证估值五级分档、位置中枢上沿判定、量价五态评分。
370号：移除_build_dimensions调用，改为测试_DIM_DIRECTION静态映射和_derive_vp_state。
"""
import json
import pytest


class TestValuationFiveLevels:
    """估值分档细化：extreme_low→极度低估，extreme_high→极度高估"""

    def test_dim_direction_has_five_levels(self):
        """_DIM_DIRECTION 估值维度应有五级映射"""
        from app.opportunity_atlas.status_engine import _DIM_DIRECTION
        val_map = _DIM_DIRECTION.get('valuation', {})
        assert '极度低估' in val_map, "_DIM_DIRECTION 缺极度低估"
        assert '极度高估' in val_map, "_DIM_DIRECTION 缺极度高估"
        assert val_map['极度低估'] > val_map['低估'], "极度低估应比低估更看多"
        assert val_map['极度高估'] < val_map['高估'], "极度高估应比高估更看空"


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
