"""dim4_chip_fund_engine.py — 第4维资金筹码集中引擎

364h Phase 8：收敛moneyflow从6处查询为1处。
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class Dim4ChipFundEngine:
    """第4维资金筹码引擎"""

    def evaluate(self, dims: dict, tags: dict, signals: dict = None, lifecycle: dict = None) -> dict:
        from app.opportunity_atlas.fund_chip_builder import build_fund_chip
        return build_fund_chip(dims, tags, signals)
