"""
多级别缠论联立分析器

每个级别独立运行完整分析链（K线包含→分型→笔→线段→中枢），
然后通过区间套策略进行跨级别关联。

参考: chan.py CChan.lv_list 参数机制
知识库: 缠中说禅买卖点级别定理 — 大级别买卖点必然是次级别以下某一级别买卖点
"""
import logging
from collections import OrderedDict
from typing import Dict, List, Optional

from app.data.memory_cache import TieredMemoryCache
from app.engine.framework.chanlun_config import ChanlunConfig
from app.engine.framework.chanlun_strategy import (
    ChanlunAnalyzer,
    Zhongshu,
)

logger = logging.getLogger(__name__)


class MultiLevelChanlunAnalyzer:
    """多级别缠论联立分析器。"""

    LEVEL_ORDER = OrderedDict({
        'weekly':  {'lookback': 260, 'min_segments': 3},
        'daily':   {'lookback': 130, 'min_segments': 3},
        'hourly':  {'lookback': 60,  'min_segments': 2},
    })

    def __init__(self, config: Optional[ChanlunConfig] = None):
        self.config = config or ChanlunConfig.default()
        self.results: Dict[str, dict] = {}
        # 进程级内存缓存（批次4c）
        self._cache = TieredMemoryCache()

    def analyze(self, df_dict: Dict[str, 'pd.DataFrame']) -> Dict:
        """对每个级别独立运行缠论分析链。
        
        Args:
            df_dict: {级别名: OHLCV DataFrame} 如
                     {'daily': df_daily, 'hourly': df_hourly}
                     至少需要 daily 级别
        Returns:
            多级别联立分析结果
        """
        levels = self.config.multi_level.levels
        results = {}

        for level in levels:
            df = df_dict.get(level)
            if df is None or df.empty:
                logger.debug(f"{level} 级别数据不可用，跳过")
                continue

            # 使用缓存的级别分析结果（TieredMemoryCache，TTL=3600s）
            cache_key = f"chanlun:{level}:{len(df)}"
            cached = self._cache.get(cache_key, 'analysis')
            if cached is not None:
                results[level] = cached
            else:
                analyzer = ChanlunAnalyzer(config=self.config)
                result = analyzer.analyze(df)
                if 'error' not in result:
                    self._cache.set(cache_key, result, 'analysis')
                    results[level] = result

        self.results = results
        return self._cross_level_validate()

    def _cross_level_validate(self) -> Dict:
        """区间套验证 + 方向一致性检查。
        
        参考: 缠中说禅买卖点级别定理，缠论级别的绝对位置定位.md
        """
        levels_data = {}
        direction_map = {}

        for level_name, result in self.results.items():
            strokes = result.get('strokes', [])
            segments = result.get('segments', [])
            zhongshu_list = result.get('zhongshu', [])
            summary = result.get('summary', {})
            trend = summary.get('trend', 'unknown')

            levels_data[level_name] = {
                'stroke_count': len(strokes),
                'segment_count': len(segments),
                'zhongshu_count': len(zhongshu_list),
                'zhongshu_list': [
                    {'low': zs.low, 'high': zs.high, 'type': zs.type,
                     'level': zs.level, 'duration': zs.duration}
                    for zs in zhongshu_list[-3:]  # 最多展示最近3个
                ],
                'latest_zhongshu': zhongshu_list[-1] if zhongshu_list else None,
            }
            direction_map[level_name] = trend

        # 级别间方向一致性检查
        direction_text = self._build_direction_text(direction_map)

        # 最接近的关键价位（从最近的中枢取）
        near_levels = self._find_near_levels(levels_data)

        return {
            'enabled': True,
            'levels': levels_data,
            'direction_map': direction_map,
            'direction_text': direction_text,
            'near_levels': near_levels,
        }

    def _build_direction_text(self, direction_map: Dict[str, str]) -> str:
        """构建多级别方向描述，消除"上升趋势+下降笔"矛盾。"""
        weekly_dir = direction_map.get('weekly', '')
        daily_dir = direction_map.get('daily', '')
        hourly_dir = direction_map.get('hourly', '')

        # 周线决定大方向
        if weekly_dir == '上升':
            if daily_dir == '上升':
                base = '周线/日线同步上升趋势'
            elif daily_dir == '下降':
                base = '周线上升趋势中的日线回调'
            else:
                base = '周线上升趋势'
        elif weekly_dir == '下降':
            if daily_dir == '下降':
                base = '周线/日线同步下降趋势'
            elif daily_dir == '上升':
                base = '周线下降趋势中的日线反弹'
            else:
                base = '周线下降趋势'
        else:
            if daily_dir == '上升':
                base = '日线上升趋势'
            elif daily_dir == '下降':
                base = '日线下降趋势'
            else:
                base = '方向待定'

        if hourly_dir:
            if hourly_dir == '上升':
                base += '，60分钟级别向上'
            elif hourly_dir == '下降':
                base += '，60分钟级别向下'

        return base

    @staticmethod
    def _find_near_levels(levels_data: Dict) -> List[Dict]:
        """从各级别中提取最近的关键价位。"""
        near_levels = []
        for level_name, data in levels_data.items():
            zs = data.get('latest_zhongshu')
            if zs:
                near_levels.append({
                    'level': level_name,
                    'support': round(zs.low, 2),
                    'resistance': round(zs.high, 2),
                    'center': round(zs.center, 2) if zs.center else None,
                })
        return near_levels

    def get_zhongshu_list(self, level: str = 'daily') -> List[Zhongshu]:
        """获取指定级别的最新中枢列表。"""
        result = self.results.get(level, {})
        return result.get('zhongshu', [])
