"""
MarketSentimentService — 市场情绪聚合服务

273a 方案：基于涨停池数据计算全市场情绪指标，映射六段论。

数据流:
  sentiment_pool_cache (ECM) → 聚合 → 六段论映射 → snapshot.verification

六段论（365号批次B升级）:
  ice(冰点) → sprout(萌芽) → ferment(发酵) → climax(高潮) → ebb(退潮) → regression(回归)
"""
import logging
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)


class MarketSentimentService:
    """市场情绪聚合服务 — 涨跌停数据 → 六段论映射"""

    PHASE_LABELS = {
        'ice': '情绪冰点',
        'sprout': '情绪萌芽',
        'ferment': '情绪发酵',
        'climax': '情绪高潮',
        'ebb': '情绪退潮',
        'regression': '情绪回归',
        'neutral': '情绪中性',
    }

    def __init__(self, data_manager=None):
        if data_manager is None:
            from app.data import DataManager
            data_manager = DataManager()
        self.data_manager = data_manager

    def get_sentiment_phase(self, trade_date: str = None, metrics_override: Dict = None) -> Dict:
        """获取当前市场情绪阶段（六段论）

        Args:
            trade_date: 交易日期 YYYYMMDD，默认今天
            metrics_override: 535 P1：可选，使用外部权威涨停生态指标
                （limit_detail_cache U/Z）覆盖 sentiment_pool 聚合结果。

        Returns:
            {
                'phase': 'ice'|'sprout'|'ferment'|'climax'|'ebb'|'regression',
                'phase_label': str,
                'metrics': {...},
                'data_available': bool,
            }
        """
        if not trade_date:
            trade_date = datetime.now().strftime('%Y%m%d')

        if metrics_override is not None:
            metrics = {
                'limit_up_count': int(metrics_override.get('limit_up_count') or 0),
                'limit_down_count': int(metrics_override.get('limit_down_count') or 0),
                'max_board_height': int(metrics_override.get('max_board_height') or 0),
                'sealing_rate': float(metrics_override.get('sealing_rate') or 0.0),
                'up_down_ratio': round(float(metrics_override.get('up_down_ratio') or 0.0), 2),
            }
            phase = self._classify_phase(metrics)
            return {
                'phase': phase,
                'phase_label': self.PHASE_LABELS.get(phase, '情绪中性'),
                'metrics': metrics,
                'data_available': True,
            }

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

        # 封板率（488-2：优先「涨停 / (涨停+炸板)」——AKShare 涨停池本身即已封板股，
        #   仅按池内「首次封板时间」算恒 100%、无区分度；炸板池缺数据时回退原口径）
        zha_df = df[df['limit_type'] == 'zha']
        if limit_up_count > 0 and len(zha_df) > 0:
            sealing_rate = round(limit_up_count / (limit_up_count + len(zha_df)) * 100, 1)
        else:
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

        phase = self._classify_phase(metrics)
        phase_label = self.PHASE_LABELS.get(phase, '情绪中性')

        return {
            'phase': phase,
            'phase_label': phase_label,
            'metrics': metrics,
            'data_available': True,
        }

    @staticmethod
    def _classify_phase(metrics: Dict) -> str:
        """六段论映射（365号批次B阈值，535 提取为可复用）。"""
        limit_up_count = int(metrics.get('limit_up_count') or 0)
        max_board_height = int(metrics.get('max_board_height') or 0)
        sealing_rate = float(metrics.get('sealing_rate') or 0.0)
        if limit_up_count < 20 and max_board_height < 3 and sealing_rate < 40:
            return 'ice'
        if limit_up_count < 40 and max_board_height <= 2 and sealing_rate < 50:
            return 'sprout'
        if 40 <= limit_up_count <= 80 and max_board_height >= 3 and sealing_rate >= 40:
            return 'ferment'
        if limit_up_count > 80 and sealing_rate > 75:
            return 'climax'
        if ((max_board_height >= 3 and sealing_rate < 50)
                or (sealing_rate < 40 and limit_up_count < 40)):
            return 'ebb'
        if 20 <= limit_up_count <= 60 and max_board_height <= 2:
            return 'regression'
        return 'ferment'

    def _estimate_daily_sealing_rate(self, trade_date: str = None) -> float:
        """基于 daily_cache 的日频封板率近似值（备用，不阻塞主流程）"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')

        try:
            ecm = self.data_manager.cache
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
