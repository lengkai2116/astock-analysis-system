"""NLG 自然语言生成模块 — 结构化数据 → 中文描述段落"""

from .chinese_rendering import render_aggregated_status, render_five_dimensions
from .momentum_renderer import render_momentum, render_momentum_with_context
from .risk_renderer import render_consensus, render_risk, render_verification_chains
from .sr_renderer import render_sr_with_price, render_support_resistance
from .templates import (
    BOCIASI_STATE,
    CHANLUN_TERMS,
    CHIP_PHASE,
    CHIP_STATE,
    CONSENSUS_LEVEL,
    EMOTION_CYCLE,
    MOMENTUM_ACTION,
    MOMENTUM_LEVEL,
    RISK_LEVEL,
    TREND_DIRECTION,
    TREND_STAGE,
    TREND_STRENGTH,
    VOLUME_RELATION,
    VOLUME_STATE,
)
from .trend_renderer import render_chanlun_trend, render_trend, render_volume_price_trend
from .volume_renderer import (
    render_chip_volume,
    render_emotion,
    render_volume,
    render_volume_with_relation,
)

__all__ = [
    "render_trend", "render_chanlun_trend", "render_volume_price_trend",
    "render_momentum", "render_momentum_with_context",
    "render_volume", "render_volume_with_relation", "render_chip_volume", "render_emotion",
    "render_support_resistance", "render_sr_with_price",
    "render_risk", "render_verification_chains", "render_consensus",
    "render_five_dimensions", "render_aggregated_status",
    # Templates
    "TREND_DIRECTION", "TREND_STRENGTH", "TREND_STAGE",
    "MOMENTUM_LEVEL", "MOMENTUM_ACTION",
    "VOLUME_STATE", "VOLUME_RELATION",
    "CHIP_PHASE", "CHIP_STATE",
    "BOCIASI_STATE", "EMOTION_CYCLE",
    "CHANLUN_TERMS",
    "RISK_LEVEL", "CONSENSUS_LEVEL",
]
