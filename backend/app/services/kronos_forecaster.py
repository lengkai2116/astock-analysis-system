"""
Kronos K线预测适配器

将Kronos基础模型（Tsinghua/Microsoft, AAAI 2026）的输出
转换为策略系统可消费的信号格式。

设计原则：
- 懒加载：首次analyze()调用时加载模型（~10-15s）
- 开关控制：kronos_enabled=false时不加载、不推理
- 优雅降级：推理失败/超时 → 返回None → 下游融合点自动跳过
- 缓存友好：同一股票30分钟内不重复推理（由上层TieredMemoryCache控制）
"""

import logging
import time
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class KronosForecaster:
    """Kronos K线预测适配器 — 将Kronos模型输出转换为策略信号"""

    _instance = None  # 单例：模型在进程生命周期内只加载一次

    def __init__(self):
        self._predictor = None
        self._tokenizer = None
        self._model = None

    def _ensure_loaded(self) -> bool:
        """懒加载Kronos模型（首次调用时加载）"""
        if self._predictor is not None:
            return True

        try:
            import torch  # noqa: F401 — 验证torch已安装
            from model import Kronos, KronosTokenizer, KronosPredictor  # noqa

            logger.info("Kronos: 开始加载模型 (Kronos-mini)...")
            t0 = time.time()

            self._tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
            self._model = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
            self._predictor = KronosPredictor(
                self._model, self._tokenizer, max_context=2048
            )

            elapsed = time.time() - t0
            logger.info(f"Kronos: 模型加载完成 ({elapsed:.1f}s)")
            return True

        except ImportError as e:
            logger.warning(
                f"Kronos: 依赖未安装 — {e}. "
                "请安装 pipeline('kronos') 所需的依赖。"
            )
            return False
        except Exception as e:
            logger.warning(f"Kronos: 模型加载失败 — {e}")
            return False

    def analyze(self, kline_data: pd.DataFrame) -> Optional[Dict]:
        """
        主入口：输入K线数据 → Kronos推理 → 提取策略信号

        Args:
            kline_data: 包含OHLCV的DataFrame，至少需要200根K线

        Returns:
            {
                'direction': 'bullish'|'bearish'|'neutral',  # 方向预测
                'confidence': 0.72,                            # 预测置信度
                'volatility_regime': 'high'|'normal'|'low',   # 波动率状态
                'trend_strength': 0.65,                        # 趋势强度
                'volatility_warning': False,                   # 高波动预警
                'predicted_bars': [...],                        # 预测K线摘要（前20根）
                'model': 'kronos-mini',
                'inference_ms': 342,
            }
            推理失败时返回 None
        """
        if not self._ensure_loaded():
            return None

        if kline_data is None or len(kline_data) < 60:
            logger.debug("Kronos: K线数据不足(需>=60根)，跳过推理")
            return None

        try:
            t0 = time.time()

            # 准备输入数据
            input_df = self._prepare_input(kline_data)
            if input_df is None:
                return None

            # 执行推理
            pred_df = self._predictor.predict(
                df=input_df,
                x_timestamp=None,
                y_timestamp=None,
                pred_len=min(120, len(input_df)),
                T=1.0,
                top_p=0.9,
                sample_count=1,
            )

            elapsed_ms = round((time.time() - t0) * 1000)

            # 从预测K线中提取信号
            result = self._extract_signal(kline_data, pred_df)
            if result is None:
                return None

            result['model'] = 'kronos-mini'
            result['inference_ms'] = elapsed_ms
            logger.debug(
                f"Kronos: {len(kline_data)}根K线 → 推理完成 "
                f"({elapsed_ms}ms, dir={result['direction']})"
            )
            return result

        except Exception as e:
            logger.warning(f"Kronos: 推理异常 — {e}")
            return None

    def _prepare_input(self, kline_data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """将系统K线数据格式转为Kronos输入格式"""
        try:
            # 确保列名匹配Kronos期望格式
            required = ['open', 'high', 'low', 'close']
            for col in required:
                if col not in kline_data.columns:
                    logger.debug(f"Kronos: 缺少列 {col}")
                    return None

            df = kline_data[required].copy()
            # 可选：volume, amount
            if 'vol' in kline_data.columns:
                df['volume'] = kline_data['vol']
            if 'amount' in kline_data.columns:
                df['amount'] = kline_data['amount']

            # 取最后2048根（Kronos-mini上下文限制）
            if len(df) > 2048:
                df = df.iloc[-2048:]

            # 转为float
            for col in df.columns:
                df[col] = df[col].astype(float)

            return df

        except Exception as e:
            logger.warning(f"Kronos: 数据准备异常 — {e}")
            return None

    def _extract_signal(
        self, input_df: pd.DataFrame, pred_df: pd.DataFrame
    ) -> Optional[Dict]:
        """从预测K线中提取交易信号"""
        if pred_df is None or len(pred_df) == 0:
            return None

        try:
            # 1) 方向预测：对比预测K线平均close vs 输入最后20根平均close
            input_recent = input_df['close'].iloc[-20:].mean()
            pred_mean = pred_df['close'].mean() if 'close' in pred_df.columns else input_recent
            pct_change = (pred_mean / input_recent - 1)

            if pct_change > 0.005:  # >0.5%
                direction = 'bullish'
            elif pct_change < -0.005:
                direction = 'bearish'
            else:
                direction = 'neutral'
            confidence = min(1.0, abs(pct_change) * 20)  # 2%变化 → 0.4

            # 2) 趋势强度：预测序列的线性回归斜率
            if 'close' in pred_df.columns:
                x = np.arange(len(pred_df))
                y = pred_df['close'].values
                if len(y) > 1:
                    slope = np.polyfit(x, y, 1)[0]
                    trend_strength = float(np.tanh(slope / input_recent * 1000))
                else:
                    trend_strength = 0.0
            else:
                trend_strength = 0.0

            # 3) 波动率估计：预测K线OHLC标准差 vs 历史标准差
            hist_vol = float(input_df['close'].pct_change().std())
            if 'close' in pred_df.columns:
                pred_vol = float(pred_df['close'].pct_change().std())
                vol_ratio = pred_vol / max(hist_vol, 0.0001)
            else:
                vol_ratio = 1.0

            if vol_ratio > 1.5:
                volatility_regime = 'high'
            elif vol_ratio < 0.7:
                volatility_regime = 'low'
            else:
                volatility_regime = 'normal'

            # 4) 波动率预警
            volatility_warning = vol_ratio > 1.5

            # 5) 预测K线摘要（前20根，供AI语境使用）
            predicted_summary = []
            if 'close' in pred_df.columns:
                for i in range(min(20, len(pred_df))):
                    bar = {'index': i, 'close': round(float(pred_df['close'].iloc[i]), 2)}
                    if 'open' in pred_df.columns:
                        bar['open'] = round(float(pred_df['open'].iloc[i]), 2)
                    if 'high' in pred_df.columns:
                        bar['high'] = round(float(pred_df['high'].iloc[i]), 2)
                    if 'low' in pred_df.columns:
                        bar['low'] = round(float(pred_df['low'].iloc[i]), 2)
                    predicted_summary.append(bar)

            return {
                'direction': direction,
                'confidence': round(confidence, 2),
                'volatility_regime': volatility_regime,
                'trend_strength': round(trend_strength, 4),
                'volatility_warning': volatility_warning,
                'predicted_bars': predicted_summary,
            }

        except Exception as e:
            logger.warning(f"Kronos: 信号提取异常 — {e}")
            return None

    @staticmethod
    def check_available() -> bool:
        """检查Kronos依赖是否已安装（不加载模型）"""
        try:
            import torch  # noqa: F401
            return True
        except ImportError:
            return False
