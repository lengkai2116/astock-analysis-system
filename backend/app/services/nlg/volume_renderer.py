"""
量价/筹码维度 NLG 渲染器 — 成交量、形态、筹码峰 → 中文描述
"""

from .templates import VOLUME_STATE, VOLUME_RELATION


def render_volume(volume: dict) -> str:
    """渲染量价维度中文描述。

    Args:
        volume: {state, structure}

    Returns:
        中文量价描述段落（20-60 字）
    """
    vol_state = volume.get("state", "")
    structure = volume.get("structure", "")

    parts = []
    if vol_state:
        parts.append(f"成交量{vol_state}")
    if structure:
        parts.append(structure)

    return "，".join(parts) + "。" if parts else ""


def render_volume_with_relation(volume: dict, trend: dict = None) -> str:
    """渲染带量价因果关系的描述（含形态和均线排列）。"""
    vol_state = volume.get("state", "")
    structure = volume.get("structure", "")
    trend_dir = trend.get("direction", "") if trend else ""
    trend_strength = trend.get("strength", "") if trend else ""

    parts = []
    if vol_state and trend_dir:
        # 量价配合关系 — 因果关系描述
        if vol_state == "放量" and trend_dir == "up":
            if trend_strength == "strong":
                parts.append("放量上攻，量价配合良好，上涨动能充足")
            else:
                parts.append("放量上攻，量价配合良好")
        elif vol_state == "放量" and trend_dir == "down":
            parts.append("放量下跌，空头力量集中释放，短期趋势偏空")
        elif vol_state == "缩量" and trend_dir == "up":
            parts.append("缩量上涨，上攻动能不足，需警惕量价背离")
        elif vol_state == "缩量" and trend_dir == "down":
            parts.append("缩量回调，下跌动能减弱，关注止跌信号")
        elif vol_state == "平量" and trend_dir == "up":
            parts.append("平量上行，趋势延续性待观察")
        elif vol_state == "平量" and trend_dir == "down":
            parts.append("平量下行，下跌趋势延续中")
        else:
            parts.append(f"成交量{vol_state}")
    elif vol_state:
        parts.append(f"成交量{vol_state}")

    if structure:
        parts.append(f"均线{structure}")

    return "，".join(parts) + "。" if parts else ""


def render_emotion(status: dict) -> str:
    """渲染情绪维度中文描述（含情绪周期和市场温度）。"""
    parts = []
    # 情绪周期阶段（来自FMZ→四阶段映射，如"情绪冰点""情绪复苏"）
    state_label = status.get("state_label", "")
    if state_label:
        parts.append(state_label)
    # 市场温度（volume.state作为补充）
    market_temp = status.get("volume", {}).get("state", "")
    if market_temp and market_temp != state_label:
        parts.append(f"市场情绪{market_temp}")
    # 风险等级
    risk = status.get("risk_level", "")
    if risk:
        risk_cn = {"LOW": "低", "MEDIUM": "中等", "HIGH": "高"}.get(risk, risk)
        parts.append(f"风险等级{risk_cn}")
    return "，".join(parts) + "。" if parts else "情绪数据不足。"


def render_chip_volume(chip_status: dict) -> str:
    """渲染筹码维度量价描述（含筹码峰/ASR信息）。"""
    parts = []

    chip_peak = chip_status.get("chip_peak", 0)
    asr_val = chip_status.get("asr")
    concentration = chip_status.get("concentration", 0)
    mf_cost = chip_status.get("main_force_cost", {})

    if chip_peak > 0:
        parts.append(f"筹码主峰位于 {chip_peak} 附近")

    if asr_val is not None:
        asr_pct = asr_val if isinstance(asr_val, (int, float)) and asr_val <= 1 else (asr_val / 100 if asr_val > 1 else asr_val)
        parts.append(f"浮筹比例 {asr_pct:.0%}")

    if concentration > 0:
        parts.append(f"集中度 {concentration:.1%}")

    cost_price = mf_cost.get("cost_price", 0)
    if cost_price > 0:
        distance = mf_cost.get("distance_pct", 0)
        near = mf_cost.get("near_cost", False)
        if near:
            parts.append(f"主力成本价约 {cost_price}，当前价接近主力成本")
        else:
            parts.append(f"主力成本价约 {cost_price}，偏离 {distance:+.1f}%")

    return "，".join(parts) + "。" if parts else ""
