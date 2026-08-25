"""
时间节奏引擎 — 基于 BOLL 带宽 + 中枢横盘时长判定变盘窗口

输出标签（295号§3.4 标签26）：
  - approaching_turn: BOLL带宽收缩+横盘充分 → 临近变盘
  - mid_consolidation: 正在中枢横盘
  - early_consolidation: 横盘初期
  - unknown: 无明显节奏特征
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# BOLL 带宽收缩阈值
BANDWIDTH_TIGHT = 5       # 带宽 < 5% → 高度收缩
BANDWIDTH_NARROW = 10     # 带宽 < 10% → 轻度收缩
RANGE_TIGHT = 10          # 30日振幅 < 10% → 区间窄幅
CONSOLIDATION_MIN_DAYS = 15  # 至少横盘15个交易日才算充分


class TimeRhythmEngine:
    """时间节奏引擎 — 基于 BOLL 带宽 + 中枢横盘时长判定变盘窗口"""

    def compute_tags(self, df: pd.DataFrame) -> dict:
        """计算时间节奏标签

        Args:
            df: 日线 OHLCV DataFrame（必须含 close, high, low）

        Returns:
            {'time_rhythm': 'approaching_turn' | 'mid_consolidation' |
                            'early_consolidation' | 'unknown'}
        """
        result = {'time_rhythm': 'unknown'}
        try:
            if df is None or len(df) < 30:
                return result

            close = df['close'].values
            close_series = pd.Series(close)

            # BOLL 带宽
            ma20 = close_series.rolling(20).mean().values
            std20 = close_series.rolling(20).std().values
            bandwidth = np.where(
                ma20 > 1e-9, std20 / ma20 * 100, np.zeros_like(ma20)
            )

            # 30日振幅
            high_30 = np.max(df['high'].values[-30:])
            low_30 = np.min(df['low'].values[-30:])
            range_pct = (high_30 - low_30) / low_30 * 100 if low_30 > 0 else 0

            # 带宽趋势（最近10日斜率，正值=扩张，负值=收缩）
            bw_recent = bandwidth[-10:] if len(bandwidth) >= 10 else bandwidth
            if len(bw_recent) >= 5:
                bw_slope = (bw_recent[-1] - bw_recent[0]) / max(bw_recent[0], 1e-9) * 100
            else:
                bw_slope = 0

            current_bw = bandwidth[-1] if len(bandwidth) > 0 else 100

            # 中枢横盘时长：连续多少日价格在窄幅区间内
            consolidation_days = 0
            if len(close) >= 30:
                ref_low = np.min(df['low'].values[-30:])
                ref_high = np.max(df['high'].values[-30:])
                ref_mid = (ref_low + ref_high) / 2
                threshold = ref_mid * 0.05  # ±5% 作为横盘判定
                for i in range(min(60, len(close))):
                    price = close[-(i + 1)]
                    if abs(price - ref_mid) < threshold:
                        consolidation_days += 1
                    else:
                        break

            # 判定逻辑
            if current_bw < BANDWIDTH_TIGHT and range_pct < RANGE_TIGHT:
                # 带宽高度收缩 + 振幅收窄
                if consolidation_days >= CONSOLIDATION_MIN_DAYS:
                    # 横盘充分 → 临近变盘
                    result['time_rhythm'] = 'approaching_turn'
                elif consolidation_days >= 5:
                    # 正在横盘中
                    result['time_rhythm'] = 'mid_consolidation'
                else:
                    result['time_rhythm'] = 'early_consolidation'
            elif current_bw < BANDWIDTH_NARROW and range_pct < RANGE_TIGHT * 1.5:
                # 轻度收缩
                if consolidation_days >= CONSOLIDATION_MIN_DAYS:
                    result['time_rhythm'] = 'approaching_turn'
                elif consolidation_days >= 5:
                    result['time_rhythm'] = 'mid_consolidation'
                else:
                    result['time_rhythm'] = 'early_consolidation'
        except Exception as e:
            logger.debug('TimeRhythmEngine: %s', e)

        return result
