"""
BOCIASI慢线 — 情绪层第二维度

在快线(OHLCV纯指标)基础上引入跨市场对比数据：
- ERP（股权风险溢价）= 1/PE_ttm - 10年国债收益率
- 股债位置差（Stock-Bond Position Difference）

依赖：需要指数数据和国债收益率数据（Tushare 5000分）
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger(__name__)


class BociasiSlowLine:
    """BOCIASI慢线 — 跨市场情绪对比"""

    # 中国10年国债收益率近似值（未接入实时数据时的默认值）
    DEFAULT_BOND_YIELD = 2.85  # %

    def evaluate(self, df: pd.DataFrame,
                 bond_yield: Optional[float] = None,
                 index_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        计算BOCIASI慢线信号

        Args:
            df: 个股日线OHLCV数据
            bond_yield: 10年国债收益率(%), None则用默认值
            index_df: 基准指数日线数据（用于计算股债位置差）

        Returns:
            {'signal': 'BULLISH'|'BEARISH'|'NEUTRAL', 'confidence': float, 'details': {...}}
        """
        if df.empty or len(df) < 60:
            return {'signal': 'NEUTRAL', 'confidence': 0.0, 'details': {'error': '数据不足'}}

        latest_close = float(df['close'].iloc[-1])

        # --- 获取PE数据 ---
        pe_ttm = self._get_pe(df)

        # --- ERP计算 ---
        if pe_ttm is not None and pe_ttm > 0:
            earnings_yield = 1.0 / pe_ttm * 100  # E/P百分比
            y = bond_yield if bond_yield is not None else self.DEFAULT_BOND_YIELD
            erp = earnings_yield - y
            erp_signal, erp_conf = self._judge_erp(erp)
        else:
            erp = None
            erp_signal = 'NEUTRAL'
            erp_conf = 0.0

        # --- 股债位置差 ---
        if index_df is not None and not index_df.empty:
            sb_signal, sb_conf, sb_details = self._calc_stock_bond_position(df, index_df)
        else:
            sb_signal = 'NEUTRAL'
            sb_conf = 0.0
            sb_details = {}

        # --- 综合信号 ---
        signals = []
        confs = []

        if erp_signal != 'NEUTRAL':
            signals.append(erp_signal)
            confs.append(erp_conf)
        if sb_signal != 'NEUTRAL':
            signals.append(sb_signal)
            confs.append(sb_conf)

        if not signals:
            final_signal = 'NEUTRAL'
            final_conf = 0.3
        else:
            bullish = signals.count('BULLISH')
            bearish = signals.count('BEARISH')
            avg_conf = np.mean(confs) if confs else 0.3

            if bullish > bearish:
                final_signal = 'BULLISH'
                final_conf = min(0.8, avg_conf * 1.1)
            elif bearish > bullish:
                final_signal = 'BEARISH'
                final_conf = min(0.8, avg_conf * 1.1)
            else:
                final_signal = 'NEUTRAL'
                final_conf = 0.3

        return {
            'signal': final_signal,
            'confidence': round(final_conf, 2),
            'details': {
                'erp': round(erp, 4) if erp is not None else None,
                'pe_ttm': round(pe_ttm, 2) if pe_ttm is not None else None,
                'erp_signal': erp_signal,
                'erp_confidence': round(erp_conf, 2),
                'sb_signal': sb_signal,
                'sb_details': sb_details,
            },
        }

    def _get_pe(self, df: pd.DataFrame) -> Optional[float]:
        """从df或其他数据源获取PE_TTM"""
        # 优先从 df 的列获取
        for col in ['pe_ttm', 'pe']:
            if col in df.columns and not df[col].empty:
                val = df[col].iloc[-1]
                if val is not None and val > 0:
                    return float(val)
        return None

    def _judge_erp(self, erp: float) -> Tuple[str, float]:
        """ERP判定

        ERP>5% = 股性价比高(看多)
        ERP<2% = 股性价比低(看空)
        其余=中性
        """
        if erp > 5.0:
            return 'BULLISH', 0.75
        elif erp > 3.0:
            return 'BULLISH', 0.60
        elif erp < 0.5:
            return 'BEARISH', 0.75
        elif erp < 1.5:
            return 'BEARISH', 0.60
        else:
            return 'NEUTRAL', 0.0

    def _calc_stock_bond_position(self, df: pd.DataFrame,
                                   index_df: pd.DataFrame) -> Tuple[str, float, Dict]:
        """股债位置差

        个股价格vs指数位置的相对强弱
        个股在指数中所处的相对位置(分位)

        Returns: (signal, confidence, details)
        """
        idx_close = index_df['close'].astype(float)
        stock_close = df['close'].astype(float)

        if len(idx_close) < 20 or len(stock_close) < 20:
            return 'NEUTRAL', 0.0, {}

        # 计算相对强度
        idx_ret = idx_close.iloc[-1] / idx_close.iloc[-20] - 1
        stock_ret = stock_close.iloc[-1] / stock_close.iloc[-21] - 1 if len(stock_close) >= 21 else 0

        rel_strength = stock_ret - idx_ret

        if rel_strength > 0.05:
            signal = 'BULLISH'
            conf = min(0.7, 0.5 + abs(rel_strength))
        elif rel_strength < -0.05:
            signal = 'BEARISH'
            conf = min(0.7, 0.5 + abs(rel_strength))
        else:
            signal = 'NEUTRAL'
            conf = 0.3

        return signal, round(conf, 2), {
            'stock_20d_ret': round(float(stock_ret * 100), 2),
            'index_20d_ret': round(float(idx_ret * 100), 2),
            'relative_strength': round(float(rel_strength * 100), 2),
        }
