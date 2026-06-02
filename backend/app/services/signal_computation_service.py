"""
策略信号实时计算服务
从真实 K 线数据中实时计算 Chip / Chanlun / Factor 等多维度信号
当数据库缓存的策略输出为空时，通过此服务实时计算并返回
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, date
import pandas as pd
import numpy as np

from app import db
from app.data import DataManager
from app.engine.framework.chip_strategy import ChipScorer
from app.data.chip_indicators import ChipIndicators
from app.models import Signal as SignalModel
from app.models.strategy import StrategySignal
from app.services.strategy_output_service import StrategyOutputService

logger = logging.getLogger(__name__)


class SignalComputationService:
    """策略信号计算服务"""

    def __init__(self):
        self._data_manager = None
        self.chip_scorer = ChipScorer()

    @property
    def data_manager(self):
        if self._data_manager is None:
            self._data_manager = DataManager()
        return self._data_manager

    def compute_for_stock(self, ts_code: str, limit: int = 5) -> List[Dict]:
        """
        对单只股票计算多维策略信号

        Returns:
            信号列表，格式与 StrategyOutput.to_dict() 一致
        """
        df = self.data_manager.get_cached_daily_data(ts_code)
        if df.empty or len(df) < 60:
            return []

        # 确保列名统一
        for col in ['open', 'high', 'low', 'close', 'vol']:
            if col in df.columns:
                df[col] = df[col].astype(float)
        if 'vol' not in df.columns and 'amount' in df.columns:
            df['vol'] = df['amount']

        signals = []

        # ── L2: 筹码主力分析信号 ──
        try:
            chip_signal = self._compute_chip_signal(ts_code, df)
            if chip_signal:
                signals.append(chip_signal)
        except Exception as e:
            logger.debug(f"{ts_code} Chip 信号计算失败: {e}")

        # ── L3: 缠论信号 ──
        try:
            chanlun_signal = self._compute_chanlun_signal(ts_code, df)
            if chanlun_signal:
                signals.append(chanlun_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 缠论信号计算失败: {e}")

        # ── L3: 因子评分信号 ──
        try:
            factor_signal = self._compute_factor_signal(ts_code, df)
            if factor_signal:
                signals.append(factor_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 因子信号计算失败: {e}")


        # 持久化到数据库
        self._persist_signals(ts_code, signals)

        return signals[:limit]


    def _compute_chip_signal(self, ts_code: str, df: pd.DataFrame) -> Optional[Dict]:
        """计算筹码主力分析信号 (L2)"""
        score = self.chip_scorer.score(df)
        if score <= 0:
            return None

        closes = df['close'].values
        volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
        latest_close = float(closes[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())

        # 获取换手率数据
        turnover_rate = None
        turnover_status = None
        try:
            basic_df = self.data_manager.get_cached_daily_basic(
                ts_code,
                start_date=(datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
            )
            if not basic_df.empty and 'turnover_rate' in basic_df.columns:
                tr_series = basic_df['turnover_rate'].dropna()
                if not tr_series.empty:
                    turnover_rate = float(tr_series.iloc[-1])
                    # 从 chip_indicators 获取换手率状态描述
                    turnover_status = ChipIndicators().get_turnover_status(turnover_rate)
        except Exception:
            pass

        # 确定信号方向
        if score >= 6:
            signal = StrategySignal.BULLISH.value
            signal_label = '买入'
        elif score >= 4:
            signal = StrategySignal.WATCH.value
            signal_label = '关注'
        else:
            signal = StrategySignal.NEUTRAL.value
            signal_label = '观望'

        # 计算入场区间
        entry_low = round(latest_close * 0.97, 2)
        entry_high = round(latest_close * 1.02, 2)

        # 止损线
        risk_line = round(latest_close * 0.92, 2)

        # 目标区间
        target_high = round(latest_close * 1.12, 2)

        # 证据（含换手率信息）
        evidence = self._build_chip_evidence(df, score, turnover_rate, turnover_status)

        return {
            'strategy_name': '筹码主力分析',
            'signal': signal,
            'signal_label': signal_label,
            'confidence': round(score / 10, 2),
            'entry_zone': [entry_low, entry_high],
            'risk_line': risk_line,
            'target_zone': [entry_high, target_high],
            'position_suggestion': '20%' if signal == 'BULLISH' else ('10%' if signal == 'WATCH' else '5%'),
            'holding_period': '1-3个月',
            'evidence': evidence,
            'risk_notes': ['大盘系统性风险', '行业政策变化'],
            'signal_date': latest_date if isinstance(latest_date, str) else latest_date.strftime('%Y-%m-%d'),
            'backtest_win_rates': self._get_signal_win_rates(signal),

        }

    def _compute_chanlun_signal(self, ts_code: str, df: pd.DataFrame) -> Optional[Dict]:
        """计算缠论信号 (L3)"""
        closes = df['close'].values
        latest_close = float(closes[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())

        # 简单缠论信号判断
        # 1. 底分型 + MACD 底背离 → 一类买点
        # 2. 顶分型 + MACD 顶背离 → 一类卖点
        # 简化实现：基于价格形态和 MACD 判断

        if len(closes) < 34:
            return None

        # 判断分型
        last_3 = closes[-3:]
        is_top_fractal = last_3[1] >= last_3[0] and last_3[1] >= last_3[2]
        is_bottom_fractal = last_3[1] <= last_3[0] and last_3[1] <= last_3[2]

        # 计算简易 MACD
        ema12 = pd.Series(closes).ewm(span=12).mean().values
        ema26 = pd.Series(closes).ewm(span=26).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9).mean().values
        macd = 2 * (dif - dea)

        # 底背离检测：价格新低但 MACD 不新低
        recent_low_idx = np.argmin(closes[-20:])
        macd_recent = macd[-20:]
        divergence_up = (recent_low_idx == len(closes[-20:]) - 1 and
                         macd_recent[recent_low_idx] > macd_recent[recent_low_idx - 1])

        # 顶背离检测：价格新高但 MACD 不新高
        recent_high_idx = np.argmax(closes[-20:])
        divergence_down = (recent_high_idx == len(closes[-20:]) - 1 and
                           macd_recent[recent_high_idx] < macd_recent[recent_high_idx - 1])

        confidence = 0.5
        if is_bottom_fractal and divergence_up:
            signal = StrategySignal.BULLISH.value
            signal_label = '买入'
            confidence = 0.68
            evidence = ['形成底分型结构', 'MACD 底背离确认', '一类买点信号']
        elif is_top_fractal and divergence_down:
            signal = StrategySignal.BEARISH.value
            signal_label = '卖出'
            confidence = 0.62
            evidence = ['形成顶分型结构', 'MACD 顶背离确认', '一类卖点信号']
        elif is_bottom_fractal:
            signal = StrategySignal.WATCH.value
            signal_label = '关注'
            confidence = 0.50
            evidence = ['底分型形成', '等待 MACD 确认']
        else:
            return None

        return {
            'strategy_name': '缠论策略验证',
            'signal': signal,
            'signal_label': signal_label,
            'confidence': round(confidence, 2),
            'entry_zone': [round(latest_close * 0.98, 2), round(latest_close * 1.03, 2)],
            'risk_line': round(latest_close * 0.93, 2),
            'target_zone': [round(latest_close * 1.05, 2), round(latest_close * 1.15, 2)],
            'position_suggestion': '15%' if signal == 'BULLISH' else '10%',
            'holding_period': '1-2个月',
            'evidence': evidence,
            'risk_notes': ['缠论信号滞后性', '需成交量配合确认'],
            'signal_date': latest_date if isinstance(latest_date, str) else latest_date.strftime('%Y-%m-%d'),
            'backtest_win_rates': self._get_signal_win_rates(signal),

        }

    def _compute_factor_signal(self, ts_code: str, df: pd.DataFrame) -> Optional[Dict]:
        """计算因子评分信号 (L3)"""
        closes = df['close'].values
        volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
        latest_close = float(closes[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())

        if len(closes) < 20:
            return None

        # 多因子评分
        scores = {}

        # 动量因子
        mom_20 = (closes[-1] - closes[-20]) / closes[-20]
        scores['momentum'] = min(max(mom_20 * 5 + 0.5, 0), 1)

        # 成交量因子
        if len(volumes) >= 20:
            vol_ratio = volumes[-1] / (np.mean(volumes[-20:-1]) + 1e-9)
            scores['volume'] = min(vol_ratio * 0.4, 1)
        else:
            scores['volume'] = 0.5

        # 波动率因子
        vol_20 = np.std(closes[-20:]) / np.mean(closes[-20:])
        scores['volatility'] = min(vol_20 * 10, 1)

        # RSI 因子
        if len(closes) >= 15:
            deltas = np.diff(closes[-15:])
            gains = np.sum(deltas[deltas > 0])
            losses = abs(np.sum(deltas[deltas < 0]))
            rsi = 50 if losses == 0 else (100 - 100 / (1 + gains / losses))
            scores['rsi'] = 1 - abs(rsi - 50) / 50
        else:
            scores['rsi'] = 0.5

        # 加权综合
        weights = {'momentum': 0.3, 'volume': 0.25, 'volatility': 0.2, 'rsi': 0.25}
        composite = sum(scores[k] * weights[k] for k in weights)

        # 信号判定
        if composite >= 0.6:
            signal = StrategySignal.BULLISH.value
            signal_label = '买入'
        elif composite >= 0.4:
            signal = StrategySignal.WATCH.value
            signal_label = '关注'
        else:
            signal = StrategySignal.NEUTRAL.value
            signal_label = '观望'

        return {
            'strategy_name': '因子评分系统',
            'signal': signal,
            'signal_label': signal_label,
            'confidence': round(composite, 2),
            'entry_zone': [round(latest_close * 0.97, 2), round(latest_close * 1.02, 2)],
            'risk_line': round(latest_close * 0.90, 2),
            'target_zone': [round(latest_close * 1.05, 2), round(latest_close * 1.18, 2)],
            'position_suggestion': '10%',
            'holding_period': '2-4周',
            'evidence': [
                f"动量因子: {scores['momentum']:.2f}",
                f"量价因子: {scores['volume']:.2f}",
                f"波动因子: {scores['volatility']:.2f}",
                f"RSI因子: {scores['rsi']:.2f}",
            ],
            'risk_notes': ['因子模型假设偏差', '市场风格切换风险'],
            'signal_date': latest_date if isinstance(latest_date, str) else latest_date.strftime('%Y-%m-%d'),
            'backtest_win_rates': self._get_signal_win_rates(signal),

        }

    def _build_chip_evidence(self, df: pd.DataFrame, score: float,
                              turnover_rate: Optional[float] = None,
                              turnover_status: Optional[str] = None) -> List[str]:
        """构建筹码分析依据"""
        closes = df['close'].values
        volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
        evidence = []

        # 换手率证据
        if turnover_rate is not None and turnover_status is not None:
            evidence.append(f"换手率{turnover_rate:.2f}%，{turnover_status}")
        elif turnover_rate is not None:
            evidence.append(f"换手率{turnover_rate:.2f}%")

        # 价格位置
        if len(closes) >= 60:
            pos = (closes[-1] - np.min(closes[-60:])) / (np.max(closes[-60:]) - np.min(closes[-60:]) + 1e-9)
            if pos <= 0.3:
                evidence.append('股价处于60日低位区')
            elif pos >= 0.7:
                evidence.append('股价处于60日高位区')
            else:
                evidence.append('股价处于60日中位区')

        # 量比
        if len(volumes) >= 5:
            vr = volumes[-1] / (np.mean(volumes[-5:-1]) + 1e-9)
            if vr >= 1.5:
                evidence.append(f'成交量放大({vr:.1f}倍)')
            elif vr >= 1.2:
                evidence.append(f'成交量温和放量({vr:.1f}倍)')

        # 评分说明
        if score >= 7:
            evidence.append('筹码评分高，主力资金活跃')
        elif score >= 5:
            evidence.append('筹码评分中等，主力资金介入')

        if not evidence:
            evidence.append('基础技术分析信号')

        return evidence



    def _get_signal_win_rates(self, signal_type: str) -> dict:
        """从缓存获取信号类型的回测赢率数据"""
        try:
            wr = self.data_manager.cache.get_cached_win_rate(signal_type)
            if wr:
                return {
                    'signal_type': wr.get('signal_type', signal_type),
                    'samples': wr.get('samples', 0),
                    'win_rate_5d': float(wr.get('win_rate_5d', 0)),
                    'win_rate_10d': float(wr.get('win_rate_10d', 0)),
                    'win_rate_20d': float(wr.get('win_rate_20d', 0)),
                    'avg_return_5d': float(wr.get('avg_return_5d', 0)),
                    'avg_return_20d': float(wr.get('avg_return_20d', 0)),
                    'sharpe_5d': float(wr.get('sharpe_5d', 0)),
                    'sharpe_20d': float(wr.get('sharpe_20d', 0)),
                }
        except Exception:
            pass
        return {}
    def _persist_signals(self, ts_code: str, signals: List[Dict]):
        """将实时计算的信号持久化到数据库"""
        if not signals:
            return
        try:
            for sig in signals:
                entry = sig.get('entry_zone', [None, None])
                target = sig.get('target_zone', [None, None])
                reason_parts = []
                if sig.get('evidence'):
                    reason_parts.extend(sig['evidence'])
                if sig.get('risk_notes'):
                    reason_parts.append('风险: ' + '; '.join(sig['risk_notes']))
                record = SignalModel(
                    ts_code=ts_code,
                    signal_date=datetime.now(),
                    signal_type=sig.get('signal', 'NEUTRAL'),
                    confidence=sig.get('confidence', 0.5),
                    entry_price=entry[0],
                    stop_loss=sig.get('risk_line'),
                    take_profit=target[-1] if target else None,
                    indicators={
                        'strategy_name': sig.get('strategy_name'),
                        'signal_label': sig.get('signal_label'),
                        'position_suggestion': sig.get('position_suggestion'),
                        'holding_period': sig.get('holding_period'),
                    },
                    reason='; '.join(reason_parts) if reason_parts else None,
                    status='active' if sig.get('signal') in ('BULLISH', 'WATCH') else 'pending',
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.session.add(record)
            db.session.commit()
            # 同步写入 StrategyOutput 表
            self._sync_to_strategy_output(ts_code, signals)
            logger.info(f"{ts_code}: 已持久化 {len(signals)} 条信号")
        except Exception as e:
            db.session.rollback()
            logger.warning(f"{ts_code}: 信号持久化失败: {e}")



    def _sync_to_strategy_output(self, ts_code: str, signals: list):
        """同步信号到 StrategyOutput 表（账户管理系统读取用）"""
        if not signals:
            return
        try:
            # signal_date already imported at module level
            for sig in signals:
                entry_zone = sig.get('entry_zone', [None, None])
                target_zone = sig.get('target_zone', [None, None])
                sig_date = sig.get('signal_date', '')
                if isinstance(sig_date, str):
                    try:
                        sig_date = datetime.strptime(sig_date[:10], '%Y-%m-%d').date()
                    except ValueError:
                        sig_date = datetime.now().date()
                else:
                    sig_date = datetime.now().date()

                signal_val = sig.get('signal', 'NEUTRAL')

                StrategyOutputService.create_strategy_output(
                    ts_code=ts_code,
                    strategy_name=sig.get('strategy_name', '筹码策略'),
                    signal=signal_val,
                    signal_date=sig_date,
                    confidence=sig.get('confidence', 0.5),
                    entry_zone=entry_zone,
                    risk_line=sig.get('risk_line'),
                    target_zone=target_zone,
                    position_suggestion=sig.get('position_suggestion'),
                    holding_period=sig.get('holding_period'),
                    evidence=sig.get('evidence', []),
                    risk_notes=sig.get('risk_notes', []),
                )
        except Exception as e:
            logger.warning(f"{ts_code}: 同步到StrategyOutput失败: {e}")
