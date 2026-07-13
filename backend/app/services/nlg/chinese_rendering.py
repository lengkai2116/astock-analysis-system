"""
ChineseNLRenderer — 中文自然语言渲染器主入口

将各策略的 status_recognition 结构化数据转换为中文描述段落。

分层架构：
  层 1（同步·零依赖）: 规则句子组合器（本模块）
  层 2（异步·可选）  : LLM 润色（外部调用）
"""

from typing import Dict, List, Optional

from .trend_renderer import render_trend, render_chanlun_trend, render_volume_price_trend
from .momentum_renderer import render_momentum, render_momentum_with_context


def render_five_dimensions(strategies_detail: List[Dict]) -> Dict[str, str]:
    """将多策略的 status_recognition 转换为各维度的中文描述。

    Args:
        strategies_detail: 策略详情列表，每项含 {strategy_name, status_recognition}

    Returns:
        {维度名称: 中文描述段落, ...}
    """
    descriptions = {}

    for sd in strategies_detail:
        name = sd.get("strategy_name", sd.get("name", ""))
        status = sd.get("status_recognition", {})
        if not status or not isinstance(status, dict):
            continue

        if "缠论" in name:
            desc = _render_chanlun(status)
        elif "量价" in name:
            desc = _render_volume_price(status)
        elif "筹码" in name:
            desc = _render_chip(status)
        elif "BOCIASI" in name or "情绪" in name:
            desc = _render_bociasi(status, name)
        elif "因子" in name:
            desc = _render_factor(status)
        else:
            desc = _render_generic(status)

        if desc:
            descriptions[name] = desc

    return descriptions


def render_aggregated_status(aggregated_status: Dict) -> str:
    """将聚合状态渲染为完整中文描述（供 interpret_status prompt 使用）。

    Args:
        aggregated_status: 来自 /api/v3/strategy/status-aggregate 的响应

    Returns:
        完整中文描述段落
    """
    lines = []
    state_consensus = aggregated_status.get("state_consensus", {})
    risk_aggregation = aggregated_status.get("risk_aggregation", {})
    momentum_consensus = aggregated_status.get("momentum_consensus", {})
    dimensions = aggregated_status.get("dimensions", [])

    # 总体共识
    state = state_consensus.get("state", "UNKNOWN")
    consensus_pct = state_consensus.get("consensus_pct", 0)
    lines.append(f"【总体状态】{state}（共识度: {consensus_pct*100:.0f}%）")

    # 风险等级
    risk_level = risk_aggregation.get("risk_level", "MEDIUM")
    lines.append(f"【风险等级】{risk_level}")

    # 动量共识
    momentum = momentum_consensus.get("momentum", "NEUTRAL")
    lines.append(f"【动量共识】{momentum}")

    # 各维度描述
    for dim in dimensions:
        dim_name = dim.get("name", "未知维度")
        status = dim.get("status_recognition", {})
        if isinstance(status, dict):
            trend = status.get("trend", {})
            vol = status.get("volume", {})
            sr = status.get("support_resistance", {})
            part = f"{dim_name}："
            part += render_trend(trend)
            vol_state = vol.get("state", "")
            vol_struct = vol.get("structure", "")
            if vol_struct:
                part += f"成交量{vol_state}，均线{vol_struct}。"
            support = sr.get("support", 0)
            resistance = sr.get("resistance", 0)
            if support or resistance:
                part += f"支撑{support} 压力{resistance}。"
            lines.append(part)

    return "\n".join(lines)


def _render_chanlun(status: dict) -> str:
    """缠论策略 → 中文描述"""
    return render_chanlun_trend(status)


def _render_volume_price(status: dict) -> str:
    """量价策略 → 中文描述"""
    return render_volume_price_trend(status)


def _render_chip(status: dict) -> str:
    """筹码策略 → 中文描述（基础版，批次3扩充）"""
    parts = []
    state = status.get("state", "")
    state_label = status.get("state_label", "")
    if state_label:
        parts.append(f"主力{state_label}")
    elif state:
        from .templates import CHIP_STATE
        parts.append(CHIP_STATE.get(state, state))

    momentum = status.get("momentum", {})
    if momentum.get("score", 0) > 0:
        parts.append(f"信号强度{momentum['score']:.0%}")

    return "，".join(parts) + "。" if parts else ""


def _render_bociasi(status: dict, name: str) -> str:
    """BOCIASI 情绪策略 → 中文描述"""
    parts = []
    state_label = status.get("state_label", "")
    if state_label:
        parts.append(state_label)
    else:
        state = status.get("state", "")
        from .templates import BOCIASI_STATE
        parts.append(BOCIASI_STATE.get(state, state))

    momentum = status.get("momentum", {})
    level = momentum.get("level", "")
    score = momentum.get("score", 0)
    if level and score > 0:
        from .templates import MOMENTUM_LEVEL
        cn = MOMENTUM_LEVEL.get(level, level)
        parts.append(f"情绪{cn}（{score:.0%}）")

    vol = status.get("volume", {})
    vol_state = vol.get("state", "")
    if vol_state:
        parts.append(f"成交量{vol_state}")

    return "，".join(parts) + "。" if parts else ""


def _render_factor(status: dict) -> str:
    """因子策略 → 中文描述"""
    parts = []
    state = status.get("state", "")
    state_label = status.get("state_label", "")
    if state_label:
        parts.append(f"因子{state_label}")
    elif state:
        from .templates import CHIP_STATE
        parts.append(CHIP_STATE.get(state, state))

    momentum = status.get("momentum", {})
    if momentum.get("score", 0) > 0:
        parts.append(f"综合评分{momentum['score']:.0%}")

    trend = status.get("trend", {})
    trend_text = render_trend(trend)
    if trend_text and trend_text != "趋势方向不明。" and trend.get("direction"):
        parts.append(trend_text)

    return "，".join(parts) + "。" if parts else ""


def _render_generic(status: dict) -> str:
    """通用渲染（兜底）"""
    parts = []
    state = status.get("state", "")
    state_label = status.get("state_label", "")
    if state_label:
        parts.append(state_label)
    elif state:
        parts.append(state)

    trend_text = render_trend(status.get("trend", {}))
    if trend_text != "趋势方向不明。":
        parts.append(trend_text)

    return "，".join(parts) + "。" if parts else ""
