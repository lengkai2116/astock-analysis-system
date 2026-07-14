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


def render_chanlun_trend(status: dict, latest_close: float = None) -> str:
    """渲染缠论趋势中文描述（三段式连贯叙事）。
    
    第一句：多级别趋势结论
    第二句：买卖点+背驰信息
    第三句：关键价位与距离
    """
    trend = status.get("trend", {})
    momentum = status.get("momentum", {})
    sr = status.get("support_resistance", {})
    bp = status.get("buy_sell_point", {})
    multi_level = status.get("multi_level", {})

    parts = []
    
    # === 第一句：趋势结论（优先使用多级别描述）===
    direction_text = multi_level.get('direction_text', '')
    if direction_text:
        parts.append(direction_text)
    else:
        # 降级到原有的 render_trend
        trend_text = render_trend(trend)
        parts.append(trend_text.rstrip('。'))

    # === 第二句：买卖点+背驰 ===
    extra = []
    buy_list = bp.get("buy", [])
    sell_list = bp.get("sell", [])
    if buy_list:
        extra.append("买点:" + "/".join(buy_list))
    if sell_list:
        extra.append("卖点:" + "/".join(sell_list))
    
    div_level = momentum.get("level", "")
    if div_level and div_level not in ("none", "unknown", ""):
        div_cn = {"bullish": "底背驰", "bearish": "顶背驰"}.get(div_level, div_level)
        extra.append(f"存在{div_cn}信号")
    
    if extra:
        parts.append("；".join(extra))

    # === 第三句：关键价位与距离 ===
    level_parts = []
    
    # 优先使用 multi_level 中的 near_levels
    near_levels = multi_level.get('near_levels', [])
    if near_levels:
        for nl in near_levels[:2]:  # 最多2个级别
            lv = nl.get('level', '')
            sup = nl.get('support', 0)
            res = nl.get('resistance', 0)
            if lv and (sup or res):
                if latest_close and sup > 0:
                    dist = (latest_close - sup) / sup * 100
                    level_parts.append(f"{lv}支撑{sup:.2f}(距当前{dist:+.1f}%)")
                if latest_close and res > 0:
                    dist = (res - latest_close) / latest_close * 100
                    level_parts.append(f"{lv}压力{res:.2f}(距当前+{dist:.1f}%)")
    else:
        # 降级：原有的 support/resistance，加距离
        support = sr.get("support", 0)
        resistance = sr.get("resistance", 0)
        if support or resistance:
            sp = []
            if resistance:
                if latest_close and latest_close > 0:
                    dist = (resistance - latest_close) / latest_close * 100
                    sp.append(f"上方压力{resistance:.2f}(距当前+{dist:.1f}%)")
                else:
                    sp.append(f"上方压力{resistance:.2f}")
            if support:
                if latest_close and latest_close > 0:
                    dist = (latest_close - support) / latest_close * 100
                    sp.append(f"下方支撑{support:.2f}(距当前-{abs(dist):.1f}%)")
                else:
                    sp.append(f"下方支撑{support:.2f}")
            if sp:
                level_parts = sp
    
    if level_parts:
        parts.append("，".join(level_parts))

    return "。".join(parts) + "。" if parts else "走势结构分析数据不足。"


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
