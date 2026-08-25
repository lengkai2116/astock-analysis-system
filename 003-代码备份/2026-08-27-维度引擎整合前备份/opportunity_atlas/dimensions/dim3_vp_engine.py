"""dim3_vp_engine.py — 第3维量价健康集中引擎

364h Phase 8：收敛vol_ratio从6处计算为1处。
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class Dim3VPEngine:
    """第3维量价健康引擎"""

    def evaluate(self, dims: dict, tags: dict, signals: dict = None, lifecycle: dict = None) -> dict:
        from app.opportunity_atlas.vp_health_builder import build_volume_price
        return build_volume_price(dims, tags, signals)
