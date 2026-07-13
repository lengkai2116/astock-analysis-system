"""
支撑压力维度 NLG 渲染器 — 关键价位 → 中文描述
"""


def render_support_resistance(sr: dict) -> str:
    """渲染支撑压力维度中文描述。

    Args:
        sr: {support, resistance}

    Returns:
        中文支撑压力描述（20-40 字）
    """
    support = sr.get("support", 0)
    resistance = sr.get("resistance", 0)

    parts = []
    if resistance:
        parts.append(f"上方压力 {resistance}")
    if support:
        parts.append(f"下方支撑 {support}")

    if not parts:
        return ""

    return "，".join(parts) + "。" if len(parts) > 1 else parts[0] + "。"


def render_sr_with_price(sr: dict, current_price: float = None) -> str:
    """渲染含当前价位的支撑压力描述。"""
    support = sr.get("support", 0)
    resistance = sr.get("resistance", 0)

    parts = []
    if resistance and current_price:
        gap_pct = (resistance / current_price - 1) * 100
        if gap_pct > 0:
            parts.append(f"上方压力 {resistance}（距当前 {gap_pct:+.1f}%）")
        else:
            parts.append(f"上方压力 {resistance}")
    elif resistance:
        parts.append(f"上方压力 {resistance}")

    if support and current_price:
        gap_pct = (support / current_price - 1) * 100
        if gap_pct < 0:
            parts.append(f"下方支撑 {support}（距当前 {gap_pct:+.1f}%）")
        else:
            parts.append(f"下方支撑 {support}")
    elif support:
        parts.append(f"下方支撑 {support}")

    if not parts:
        return ""

    return "，".join(parts) + "。" if len(parts) > 1 else parts[0] + "。"
