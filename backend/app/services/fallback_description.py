"""
fallback_description — DeepSeek 不可用时的简略描述降级方案

定位：当 DeepSeek API 不可用时，从 status_recognition 结构化字段
直接拼接三要素描述（走势结构维度），作为前端展示的兜底文本。

与 trend_renderer.py 的关系：
  - trend_renderer.py（计划废弃）: ~300行，覆盖缠论+量价+筹码+情绪
  - fallback_description.py（本文件）: ~20行，仅覆盖走势结构维度
  - 本函数是 trend_renderer 的简化替代，不是增量补充

调用方：
  strategy_analyze.py 中的 _build_chanlun_dimension()
  当 DeepSeek 不可用且 _HAVE_NLG 为 False 时使用
"""

from typing import Dict


def fallback_description(sr: Dict) -> str:
    """当 DeepSeek 不可用时，从 status_recognition 生成走势结构简略描述

    Args:
        sr: status_recognition 字典（缠论信号中的结构化状态字段）

    Returns:
        简略描述文本，格式: "{级别}趋势{方向}，价格处于中枢{位置}。{买卖点信号}。"
        示例: "日线级别上升趋势，价格处于中枢上方。买点:第三类买点。"
    """
    # 级别与趋势方向
    trend = sr.get('trend', {})
    stage = trend.get('stage', '') or ''
    direction = trend.get('direction', '')
    strength = trend.get('strength', '')

    # 从 stage 中提取级别描述（如 "日线"、"30min"）
    level = '--'
    for kw in ('周线', '日线', '60分钟', '30分钟', '15分钟'):
        if kw in stage:
            level = kw + '级别'
            break
    if level == '--':
        level = trend.get('stage', '--') or '--'

    # 方向中文映射
    dir_text = {'up': '上升', 'down': '下降', '': '震荡'}.get(direction, '震荡')

    # 强度修饰
    strength_text = ''
    if strength == 'strong' and direction in ('up', 'down'):
        strength_text = '、强劲'
    elif strength == 'weakening' and direction in ('up', 'down'):
        strength_text = '、减弱'

    # 中枢位置
    ml = sr.get('multi_level', {})
    pos = ml.get('position_vs_zs', '')
    if not pos:
        pos = '未知'

    # 买卖点：只取最新一个，不并列展示
    bp = sr.get('buy_sell_point', {})
    buy_list = bp.get('buy', [])
    sell_list = bp.get('sell', [])
    signal = ''
    if buy_list:
        signal = f'买点:{buy_list[-1]}'
    elif sell_list:
        signal = f'卖点:{sell_list[-1]}'

    base = f'{level}{dir_text}趋势{strength_text}，价格处于中枢{pos}。'
    if signal:
        return f'{base}{signal}。'
    return base
