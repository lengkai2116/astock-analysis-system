"""
MarketSentimentService — 市场情绪聚合服务

273a 方案：基于涨停池数据计算全市场情绪指标，映射四阶段。

数据流:
  sentiment_pool_cache (ECM) → 聚合 → 四阶段映射 → snapshot.verification
"""
import logging
from datetime import datetime, date
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MarketSentimentService:
    """市场情绪聚合服务 — 涨跌停数据 → 四阶段映射"""

    def __init__(self, data_manager=None):
        if data_manager is None:
            from app.data import DataManager
            data_manager = DataManager()
        self.data_manager = data_manager

    def get_sentiment_phase(self, trade_date: str = None) -> Dict:
        """获取当前市场情绪阶段

        Args:
            trade_date: 交易日期 YYYYMMDD，默认今天

        Returns:
            {
                'phase': 'ice'|'recovery'|'high'|'ebb'|'neutral',
                'phase_label': '情绪冰点'|'情绪复苏'|'情绪高潮'|'情绪退潮'|'情绪中性',
                'metrics': {...},
                'data_available': bool,
            }
        """
        if not trade_date:
            trade_date = datetime.now().strftime('%Y%m%d')

        df = self.data_manager.get_cached_sentiment_pool(trade_date)

        if df is None or df.empty:
            return {
                'phase': 'neutral',
                'phase_label': '情绪中性',
                'metrics': {},
                'data_available': False,
            }

        # 涨停/跌停分类
        up_df = df[df['limit_type'] == 'up']
        down_df = df[df['limit_type'] == 'down']

        limit_up_count = len(up_df)
        limit_down_count = len(down_df)
        up_down_ratio = round(limit_up_count / max(limit_down_count, 1), 2)

        # 最高连板数
        max_board_height = int(up_df['consecutive_days'].max()) if not up_df.empty else 0

        # 封板率（涨停池中标记了首次封板时间的比例 ≈ 已封板 / 全部涨停）
        sealed = up_df['first_seal_time'].notna() & (up_df['first_seal_time'] != '')
        sealing_rate = round(int(sealed.sum()) / max(limit_up_count, 1) * 100, 1) if limit_up_count > 0 else 0.0

        metrics = {
            'limit_up_count': limit_up_count,
            'limit_down_count': limit_down_count,
            'max_board_height': max_board_height,
            'sealing_rate': sealing_rate,
            'up_down_ratio': up_down_ratio,
        }

        # 四阶段映射
        if limit_up_count < 20 and max_board_height < 3 and sealing_rate < 40:
            phase = 'ice'
            phase_label = '情绪冰点'
        elif limit_up_count > 80 and sealing_rate > 75:
            phase = 'high'
            phase_label = '情绪高潮'
        elif max_board_height >= 3 and sealing_rate < 50:
            phase = 'ebb'
            phase_label = '情绪退潮'
        elif limit_up_count >= 20 and max_board_height >= 3:
            phase = 'recovery'
            phase_label = '情绪复苏'
        else:
            phase = 'neutral'
            phase_label = '情绪中性'

        return {
            'phase': phase,
            'phase_label': phase_label,
            'metrics': metrics,
            'data_available': True,
        }

    def get_sentiment_context(self, ts_code: str = '') -> Dict:
        """返回注入 snapshot verification 用的结构体"""
        phase_data = self.get_sentiment_phase()
        result = dict(phase_data)
        # 兼容九层框架：无数据时标记
        result.setdefault('data_available', False)
        return result
