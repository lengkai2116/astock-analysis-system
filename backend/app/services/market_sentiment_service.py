"""
MarketSentimentService — 市场情绪聚合服务

273a 方案：基于涨停池数据计算全市场情绪指标，映射四阶段。

数据流:
  sentiment_pool_cache (ECM) → 聚合 → 四阶段映射 → snapshot.verification
"""
import logging
from datetime import datetime
from typing import Dict

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
                'phase': 'ice'|'recovery'|'climax'|'ebb',
                'phase_label': '情绪冰点'|'情绪复苏'|'情绪高潮'|'情绪退潮',
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
        sealing_rate = (
            round(int(sealed.sum()) / max(limit_up_count, 1) * 100, 1)
            if limit_up_count > 0 else 0.0
        )

        metrics = {
            'limit_up_count': limit_up_count,
            'limit_down_count': limit_down_count,
            'max_board_height': max_board_height,
            'sealing_rate': sealing_rate,
            'up_down_ratio': up_down_ratio,
        }

        # 四阶段映射（全覆盖，无 neutral）
        if limit_up_count < 20 and max_board_height < 3 and sealing_rate < 40:
            phase = 'ice'
            phase_label = '情绪冰点'
        elif limit_up_count > 80 and sealing_rate > 75:
            phase = 'climax'
            phase_label = '情绪高潮'
        elif (
            (max_board_height >= 3 and sealing_rate < 50)
            or (sealing_rate < 40 and limit_up_count < 40)
        ):
            phase = 'ebb'
            phase_label = '情绪退潮'
        else:
            phase = 'recovery'
            phase_label = '情绪复苏'

        return {
            'phase': phase,
            'phase_label': phase_label,
            'metrics': metrics,
            'data_available': True,
        }

    def _estimate_daily_sealing_rate(self, trade_date: str = None) -> float:
        """基于 daily_cache 的日频封板率近似值（备用，不阻塞主流程）"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')

        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            df = ecm._query_df(
                "SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg "
                "FROM daily_cache WHERE trade_date = ?",
                [trade_date],
            )
        except Exception:
            logger.warning("_estimate_daily_sealing_rate: 无法读取 daily_cache", exc_info=True)
            return 100.0

        if df is None or df.empty:
            return 100.0

        # 通过 pct_chg 推算 prev_close
        # pct_chg = (close - prev_close) / prev_close * 100
        # prev_close = close / (1 + pct_chg / 100)
        df['prev_close'] = df['close'] / (1 + df['pct_chg'] / 100)

        # 盘中触涨停: high >= prev_close * 1.099
        touched = (df['high'] >= df['prev_close'] * 1.099).sum()
        if touched == 0:
            return 100.0

        sealed = (df['close'] >= df['prev_close'] * 1.099).sum()
        return round(sealed / touched * 100, 1)

    def get_sentiment_context(self, ts_code: str = '') -> Dict:
        """返回注入 snapshot verification 用的结构体"""
        phase_data = self.get_sentiment_phase()
        result = dict(phase_data)
        # 兼容九层框架：无数据时标记
        result.setdefault('data_available', False)
        return result
