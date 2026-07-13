"""
动量维度 NLG 渲染器 — 动量/背驰 → 中文描述

根据 status_recognition.momentum 字段生成动量描述段落。
"""

from .templates import MOMENTUM_LEVEL


def render_momentum(momentum: dict) -> str:
    """渲染动量维度中文描述。

    Args:
        momentum: {level, score}

    Returns:
        中文动量描述段落（20-50 字）
    """
    level = momentum.get("level", "")
    score = momentum.get("score", 0.0)

    if not level or level in ("none", "unknown", ""):
        return ""

    level_cn = MOMENTUM_LEVEL.get(level, level)
    if score > 0:
        return f"短期动能{level_cn}（强度{score:.0%}）。"
    return f"短期动能{level_cn}。"


def render_momentum_with_context(momentum: dict, volume: dict = None, trend: dict = None) -> str:
    """渲染带上下文的动量描述（含量价配合判断）。"""
    parts = []

    # 基础动量
    level = momentum.get("level", "")
    score = momentum.get("score", 0.0)
    if level and level not in ("none", "unknown", ""):
        level_cn = MOMENTUM_LEVEL.get(level, level)
        parts.append(f"短期动能{level_cn}")

    # 量价配合
    if volume:
        vol_state = volume.get("state", "")
        if vol_state:
            if "放量" in vol_state and level == "bullish":
                parts.append("放量上攻，量价配合良好")
            elif "放量" in vol_state and level == "bearish":
                parts.append("放量下跌，空头释放中")
            elif "缩量" in vol_state:
                parts.append("量能萎缩，动能减弱")

    # 趋势验证
    if trend:
        trend_dir = trend.get("direction", "")
        if trend_dir == "up" and level == "bearish":
            parts.append("注意：上升趋势中出现偏空信号")
        elif trend_dir == "down" and level == "bullish":
            parts.append("注意：下降趋势中出现偏多信号")

    if not parts:
        return ""

    return "。".join(parts) + "。" if len(parts) > 1 else parts[0] + "。"
