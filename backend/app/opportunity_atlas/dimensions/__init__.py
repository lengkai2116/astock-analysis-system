"""dimensions/__init__.py — 维度引擎注册表

364h Phase 8：6个集中维度引擎 + 2个共享服务
"""

from app.opportunity_atlas.dimensions.shared_vol_ratio import calc_vol_ratio
from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
from app.opportunity_atlas.dimensions.dim2_structure_engine import Dim2StructureEngine
from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import Dim4ChipFundEngine
from app.opportunity_atlas.dimensions.dim5_emotion_engine import Dim5EmotionEngine
from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine

__all__ = [
    'calc_vol_ratio',
    'calc_support_resistance',
    'Dim1SignalEngine',
    'Dim2StructureEngine',
    'Dim3VPEngine',
    'Dim4ChipFundEngine',
    'Dim5EmotionEngine',
    'Dim6RiskEngine',
]
