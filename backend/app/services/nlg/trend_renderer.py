"""
趋势维度 NLG 渲染器 — 缠论/量价趋势 → 中文描述

根据 status_recognition.trend 字段组合生成趋势描述段落。
"""

from .templates import TREND_DIRECTION, TREND_STRENGTH, TREND_STAGE


def render_trend(trend: dict) -> str:
    """渲染趋势维度中文描述。

    Args:
        trend: {direction, strength, stage}

    Returns:
        中文趋势描述段落（30-80 字）
    """
    direction = trend.get("direction", "")
    strength = trend.get("strength", "")
    stage = trend.get("stage", "")

    parts = []

    if stage:
        # 含级别信息的 stage（如"日线up_延续"）
        if "日线" in stage:
            # 解析级别+状态
            stage_clean = stage.replace("日线", "")
            stage_cn = _stage_to_cn(stage_clean)
            dir_cn = TREND_DIRECTION.get(direction, "")
            strength_cn = TREND_STRENGTH.get(strength, "")
            if dir_cn:
                prefix = f"{dir_cn}趋势"
                if strength_cn:
                    prefix += f"、{strength_cn}"
                parts.append(f"日线级别{prefix}，{stage_cn}")
            else:
                parts.append(f"日线{stage_cn}")
        else:
            # 无级别信息，用 TREND_STAGE 映射
            stage_cn = TREND_STAGE.get(stage)
            if stage_cn:
                parts.append(stage_cn)
            else:
                parts.append(stage)
    elif direction:
        dir_cn = TREND_DIRECTION.get(direction, direction)
        strength_cn = TREND_STRENGTH.get(strength, "")
        if strength_cn:
            parts.append(f"{dir_cn}趋势，{strength_cn}")
        else:
            parts.append(f"{dir_cn}趋势")

    return "，".join(parts) + "。" if parts else "趋势方向不明。"


def render_chanlun_trend(status: dict) -> str:
    """渲染缠论趋势中文描述（含买卖点和背驰信息）。"""
    trend = status.get("trend", {})
    momentum = status.get("momentum", {})
    sr = status.get("support_resistance", {})
    bp = status.get("buy_sell_point", {})

    parts = []

    # 趋势描述
    trend_text = render_trend(trend)
    parts.append(trend_text)

    # 买卖点
    buy_list = bp.get("buy", [])
    sell_list = bp.get("sell", [])
    if buy_list or sell_list:
        bp_parts = []
        if buy_list:
            bp_parts.append("买点: " + "/".join(buy_list))
        if sell_list:
            bp_parts.append("卖点: " + "/".join(sell_list))
        parts.append("当前" + "，".join(bp_parts))

    # 背驰信息
    div_level = momentum.get("level", "")
    if div_level and div_level not in ("none", "unknown", ""):
        div_cn = {"bullish": "底背驰", "bearish": "顶背驰"}.get(div_level, div_level)
        parts.append(f"存在{div_cn}信号")

    # 支撑压力
    support = sr.get("support", 0)
    resistance = sr.get("resistance", 0)
    if support or resistance:
        sp = []
        if resistance:
            sp.append(f"上方压力 {resistance}")
        if support:
            sp.append(f"下方支撑 {support}")
        if sp:
            parts.append("，".join(sp))

    return "".join(parts)


def render_volume_price_trend(status: dict) -> str:
    """渲染量价趋势中文描述（含形态和量价关系）。"""
    trend = status.get("trend", {})
    volume = status.get("volume", {})
    sr = status.get("support_resistance", {})

    parts = []

    # 趋势
    trend_text = render_trend(trend)
    parts.append(trend_text)

    # 量价形态
    vol_state = volume.get("state", "")
    vol_struct = volume.get("structure", "")
    if vol_struct:
        if vol_state:
            parts.append(f"成交量{vol_state}，均线{vol_struct}")
        else:
            parts.append(f"均线{vol_struct}")
    elif vol_state:
        parts.append(f"成交量{vol_state}")

    # 支撑压力
    support = sr.get("support", 0)
    resistance = sr.get("resistance", 0)
    if support or resistance:
        sp = []
        if resistance:
            sp.append(f"上方压力 {resistance}")
        if support:
            sp.append(f"下方支撑 {support}")
        if sp:
            parts.append("，".join(sp))

    # 去掉各子部分自带的句号（避免双句号）
    cleaned = [p.rstrip('。') for p in parts if p.strip()]
    return "。".join(cleaned) + "。" if cleaned else "量价趋势分析数据不足。"


def _stage_to_cn(stage: str) -> str:
    """笔状态 → 中文"""
    mapping = {
        "up_延续": "上升笔延续中",
        "up_结束_回调": "上升笔结束，当前处于回调阶段",
        "down_延续": "下降笔延续中",
        "down_结束_反弹": "下降笔结束，当前处于反弹阶段",
        "": "方向待定",
    }
    return mapping.get(stage, stage)
