"""emotion_temperature.py — 情绪温度0-100计算器

365号批次B / 364d Phase 4：将市场情绪量化为0-100温度值。

计算公式：加权7维度
  - market_phase_score (25%): 六段论阶段得分
  - limit_up_score (15%): 涨停家数得分
  - blast_rate_score (10%): 炸板率得分
  - sector_heat_score (15%): 板块热度得分
  - volume_price_score (15%): 个股量价状态
  - margin_score (10%): 融资情绪
  - breadth_score (10%): 市场广度
"""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 六段论阶段→温度基准分
PHASE_BASE_TEMP = {
    'ice': 10,
    'sprout': 30,
    'regression': 40,
    'ferment': 60,
    'climax': 85,
    'ebb': 25,
    'neutral': 50,
}

# 权重
WEIGHTS = {
    'market_phase': 0.25,
    'limit_up': 0.15,
    'blast_rate': 0.10,
    'sector_heat': 0.15,
    'volume_price': 0.15,
    'margin': 0.10,
    'breadth': 0.10,
}


def calc_emotion_temperature(
    sentiment_phase: str = 'neutral',
    limit_up_count: int = 0,
    sealing_rate: float = 50.0,
    sector_rank: Optional[int] = None,
    volume_price_fit: str = 'neutral',
    margin_change_pct: Optional[float] = None,
    breadth: Optional[float] = None,
) -> float:
    """计算情绪温度 0-100

    Args:
        sentiment_phase: 六段论阶段标签
        limit_up_count: 涨停家数
        sealing_rate: 封板率 (0-100)
        sector_rank: 板块排名（越小越热，None=无数据）
        volume_price_fit: 个股量价状态 ('healthy'/'diverging'/'neutral')
        margin_change_pct: 融资余额5日变化率（如0.08=+8%）
        breadth: 市场广度（上涨家数/总家数，0-1）

    Returns:
        float: 0-100 温度值
    """
    scores = {}

    # 1. 市场阶段基准分 (25%)
    scores['market_phase'] = PHASE_BASE_TEMP.get(sentiment_phase, 50)

    # 2. 涨停家数得分 (15%): 0家→0分, 100家→100分
    scores['limit_up'] = min(100, max(0, limit_up_count))

    # 3. 封板率得分 (10%): 封板率直接映射
    scores['blast_rate'] = min(100, max(0, sealing_rate))

    # 4. 板块热度得分 (15%): 排名1→100分, 排名50→0分
    if sector_rank is not None:
        scores['sector_heat'] = max(0, min(100, 100 - sector_rank * 2))
    else:
        scores['sector_heat'] = 50  # 无数据用中性

    # 5. 个股量价状态 (15%)
    vp_map = {'healthy': 80, 'diverging': 20, 'neutral': 50}
    scores['volume_price'] = vp_map.get(volume_price_fit, 50)

    # 6. 融资情绪 (10%): 变化率-5%→20分, 0→50分, +5%→80分
    if margin_change_pct is not None:
        scores['margin'] = min(100, max(0, 50 + margin_change_pct * 600))
    else:
        scores['margin'] = 50

    # 7. 市场广度 (10%): 上涨占比直接映射
    if breadth is not None:
        scores['breadth'] = min(100, max(0, breadth * 100))
    else:
        scores['breadth'] = 50

    # 加权求和
    total = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    temperature = round(min(100, max(0, total)), 1)

    return temperature
