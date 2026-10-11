"""shared_vol_ratio.py — 量比统一计算服务

364h Phase 8：收敛vol_ratio从6处计算为1处，统一使用5日均量基准。
"""
from __future__ import annotations

import math

# 431号 F2/485-7：分级阈值收敛到 backend/config/dim_engine.yaml（值不变，零行为变更；
# yaml 缺失回退代码默认值）。取值属「果」侧（445 冻结），调整须独立号+全链路验证。
from app.services.status_config import get_dim_engine_config

_VOL_RATIO_CFG = get_dim_engine_config().get('shared_vol_ratio', {})
_VR_EXTREME_EXPAND = float(_VOL_RATIO_CFG.get('extreme_expand', 3.0))
_VR_SIGNIFICANT_EXPAND = float(_VOL_RATIO_CFG.get('significant_expand', 2.0))
_VR_MODERATE_EXPAND = float(_VOL_RATIO_CFG.get('moderate_expand', 1.2))
_VR_NORMAL_MIN = float(_VOL_RATIO_CFG.get('normal_min', 0.8))
_VR_SHRINK_MIN = float(_VOL_RATIO_CFG.get('shrink_min', 0.5))


def calc_vol_ratio(current_vol: float, avg_vol_5d: float) -> float:
    """统一量比计算（5日均量基准）

    收敛当前散落在6个文件中的独立计算，统一为单一入口。

    Args:
        current_vol: 当日成交量
        avg_vol_5d: 近5日均量

    Returns:
        量比值（0-∞）；输入非法（None/NaN）→ 中性 1.0
    """
    if avg_vol_5d is None or avg_vol_5d <= 0:
        return 1.0
    # 507批次4 #S16：current_vol 为 None/NaN 时原 `current_vol/avg` 抛 TypeError 或产 NaN
    if current_vol is None or (isinstance(current_vol, float) and math.isnan(current_vol)):
        return 1.0
    return round(current_vol / avg_vol_5d, 2)


def classify_vol_ratio(vol_ratio: float) -> str:
    """量比分级

    Returns:
        6级分类：极度放量/显著放量/温和放量/正常/缩量/极度缩量
    """
    # 507批次4 #S17：NaN 时所有比较 False → 原落 else「极度缩量」误标；缺数据改中性
    if vol_ratio is None or (isinstance(vol_ratio, float) and math.isnan(vol_ratio)):
        return '正常'
    if vol_ratio >= _VR_EXTREME_EXPAND:
        return '极度放量'
    elif vol_ratio >= _VR_SIGNIFICANT_EXPAND:
        return '显著放量'
    elif vol_ratio >= _VR_MODERATE_EXPAND:
        return '温和放量'
    elif vol_ratio >= _VR_NORMAL_MIN:
        return '正常'
    elif vol_ratio >= _VR_SHRINK_MIN:
        return '缩量'
    else:
        return '极度缩量'
