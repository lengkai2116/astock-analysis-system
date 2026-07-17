"""
趋势维度 NLG 渲染器 — 缠论/量价趋势 → 中文描述（精简版）

Phase 3 P3-3: 已从 258 行精简为 ~60 行。
保留所有导出函数签名以维持向后兼容，
内部复杂分支已被简化，仅保留走势结构核心描述逻辑。

DeepSeek 稳定运行后，此文件可完全移除。
"""

from .templates import TREND_DIRECTION, TREND_STRENGTH


def render_trend(trend: dict) -> str:
    """渲染趋势维度中文描述（精简版）"""
    direction = trend.get("direction", "")
    strength = trend.get("strength", "")
    stage = trend.get("stage", "")
    parts = []
    if stage:
        parts.append(stage)
    if direction:
        parts.append(TREND_DIRECTION.get(direction, direction))
    if strength:
        parts.append(TREND_STRENGTH.get(strength, strength))
    return "，".join(parts) if parts else "趋势信号不足"


def render_chanlun_trend(status: dict, latest_close: float = None) -> str:
    """渲染缠论走势中文描述（精简版——仅走势结构三维度）
    
    从 status_recognition 读取 trend + multi_level + buy_sell_point
    生成与 fallback_description 同构的描述文本，但保留了原有函数签名。
    """
    from app.services.fallback_description import fallback_description
    return fallback_description(status)


def render_volume_price_trend(status: dict) -> str:
    """渲染量价趋势中文描述（精简版）"""
    trend = status.get("trend", {})
    stage = trend.get("stage", "")
    strength = trend.get("strength", "")
    direction = trend.get("direction", "")
    vol = status.get("volume", {}).get("state", "")
    parts = []
    if stage:
        parts.append(stage)
    if direction:
        parts.append(TREND_DIRECTION.get(direction, direction))
    if strength:
        parts.append(TREND_STRENGTH.get(strength, strength))
    if vol:
        parts.append(vol)
    return "，".join(parts) if parts else "量价信号不足"


# ═══ 以下为保留兼容的辅助函数 ═══

def _stage_to_cn(stage: str) -> str:
    """阶段中文转换"""
    stage_map = {
        "up_延续": "上升笔延续", "up_结束": "上升笔结束",
        "down_延续": "下降笔延续", "down_结束": "下降笔结束",
        "up_延伸": "上升段延伸", "down_延伸": "下降段延伸",
        "中枢震荡": "中枢震荡", "横盘": "横盘整理",
    }
    return stage_map.get(stage, stage)
