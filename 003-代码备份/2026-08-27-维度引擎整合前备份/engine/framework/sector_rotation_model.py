"""
板块轮动模型 — 缠中说禅板块强弱指标法
评估全市场申万一级行业的板块热度
"""

import logging

import pandas as pd
from cachetools import TTLCache

logger = logging.getLogger(__name__)


class SectorRotationModel:
    """板块轮动模型

    核心算法 —— 缠中说禅板块强弱指标法：
    1. 对每个申万一级行业，取该行业下全部个股列表
    2. 统计各股的 MA5 > MA20（女上位=上涨）或 MA5 < MA20（男上位=下跌）
    3. 板块强弱值 = (女上位数量 - 男上位数量) / 板块总股数
    4. 对所有板块的强弱值排序
    5. top_10(前10名) / top_20(11-20名) / normal(21-40名) / none(40名以外)
    """

    HEAT_TOP10 = 'top_10'
    HEAT_TOP20 = 'top_20'
    HEAT_NORMAL = 'normal'
    HEAT_NONE = 'none'

    def __init__(self, data_manager=None):
        self._dm = data_manager
        self._cache = TTLCache(maxsize=1, ttl=1800)  # 30分钟缓存

    @property
    def dm(self):
        if self._dm is None:
            from app.data import DataManager
            self._dm = DataManager()
        return self._dm

    def compute_all_heat(self, all_data: dict[str, pd.DataFrame]) -> dict:
        """全量预计算，返回 {行业: 排序结果}

        Args:
            all_data: 全市场日线数据 {ts_code: df}

        Returns:
            {industry_name: {'heat_level': ..., 'strength': ..., 'rank': ..., 'stock_count': ...}}
        """
        ts_codes = list(all_data.keys())
        industry_map = self.dm.get_stock_industry_batch(ts_codes)

        # 按行业分组
        industry_stocks: dict[str, list[str]] = {}
        for ts_code, ind in industry_map.items():
            if ind:
                industry_stocks.setdefault(ind, []).append(ts_code)

        industry_strength: dict[str, float] = {}
        industry_counts: dict[str, int] = {}

        for ind, codes in industry_stocks.items():
            if len(codes) < 3:
                continue
            up_count = 0
            down_count = 0
            for code in codes:
                df = all_data.get(code)
                if df is None or df.empty or 'close' not in df.columns:
                    continue
                close = df['close']
                if len(close) < 20:
                    continue
                ma5 = close.rolling(window=5).mean().iloc[-1]
                ma20 = close.rolling(window=20).mean().iloc[-1]
                if pd.isna(ma5) or pd.isna(ma20):
                    continue
                if ma5 > ma20:
                    up_count += 1
                else:
                    down_count += 1

            total = up_count + down_count
            if total == 0:
                continue
            strength = (up_count - down_count) / total
            industry_strength[ind] = strength
            industry_counts[ind] = total

        sorted_industries = sorted(industry_strength.items(), key=lambda x: x[1], reverse=True)

        result = {}
        for rank, (ind, strength) in enumerate(sorted_industries, 1):
            if rank <= 10:
                heat = self.HEAT_TOP10
            elif rank <= 20:
                heat = self.HEAT_TOP20
            elif rank <= 40:
                heat = self.HEAT_NORMAL
            else:
                heat = self.HEAT_NONE
            result[ind] = {
                'heat_level': heat,
                'strength': round(strength, 4),
                'rank': rank,
                'stock_count': industry_counts.get(ind, 0),
            }

        self._cache['all_heat'] = result
        return result

    def evaluate(self, ts_code: str) -> dict:
        """评估目标股票所在行业的板块热度（需先调用 compute_all_heat 预热缓存）

        Args:
            ts_code: 目标股票代码

        Returns:
            {'sector_heat': ..., 'sector_name': ..., 'strength': ..., 'rank': ...}
        """
        industry = self.dm.get_stock_industry(ts_code)
        if not industry:
            return {'sector_heat': self.HEAT_NONE, 'sector_name': '', 'strength': 0.0, 'rank': -1}

        all_heat = self._cache.get('all_heat')
        if all_heat is None:
            return {
                'sector_heat': self.HEAT_NONE, 'sector_name': industry,
                'strength': 0.0, 'rank': -1,
            }

        sector_info = all_heat.get(industry)
        if sector_info is None:
            return {
                'sector_heat': self.HEAT_NONE, 'sector_name': industry,
                'strength': 0.0, 'rank': -1,
            }

        return {
            'sector_heat': sector_info['heat_level'],
            'sector_name': industry,
            'strength': sector_info['strength'],
            'rank': sector_info['rank'],
        }
