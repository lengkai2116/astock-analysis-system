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
from app.services.backtest_evidence_service import BacktestEvidenceService
from app.services.benchmark_service import BenchmarkService, BenchmarkIndex
from app.factors.calculator import FactorCalculator

logger = logging.getLogger(__name__)


class SignalComputationService:
    """策略信号计算服务"""

    def __init__(self):
        self._data_manager = None
        self._chip_strategy = None
        self._benchmark_service = None

    @property
    def data_manager(self):
        if self._data_manager is None:
            self._data_manager = DataManager()
        return self._data_manager

    @property
    def chip_strategy(self):
        if self._chip_strategy is None:
            from app.engine.pipeline import ChipDistributionStrategy
            self._chip_strategy = ChipDistributionStrategy(data_manager=self.data_manager)
        return self._chip_strategy

    @property
    def benchmark_service(self):
        if self._benchmark_service is None:
            self._benchmark_service = BenchmarkService()
        return self._benchmark_service

    # [P1-#27] 各策略独立取数窗口配置
    STRATEGY_WINDOWS = {
        'chanlun': 130,      # 缠论需要足量数据构建笔段中枢
        'volume_price': 130, # 量价策略需要120根完整MA计算
        'chip': 70,          # 筹码分析70根已足够
        'factor': 30,        # 因子大多14-20周期
        'bociasi': 30,       # BOCIASI快线30根
        'long_term': 260,    # 长线锚点需250日线
    }

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

        # ── 加载扩展数据：基本面 + 资金流向 + 大盘环境 ──
        market_context = {}  # 传递到各策略的通用上下文

        # 1) daily_basic: 换手率、市值、PE/PB
        try:
            df_basic = self.data_manager.get_cached_daily_basic(ts_code)
            if df_basic is not None and not df_basic.empty:
                latest_basic = df_basic.iloc[-1].to_dict()
                market_context['turnover_rate'] = latest_basic.get('turnover_rate', None)
                market_context['turnover_rate_f'] = latest_basic.get('turnover_rate_f', None)
                market_context['total_mv'] = latest_basic.get('total_mv', None)
                market_context['circ_mv'] = latest_basic.get('circ_mv', None)
                market_context['pe'] = latest_basic.get('pe', None)
                market_context['pe_ttm'] = latest_basic.get('pe_ttm', None)
                market_context['pb'] = latest_basic.get('pb', None)
                market_context['volume_ratio'] = latest_basic.get('volume_ratio', None)
                logger.debug(f"{ts_code} 已加载 daily_basic: 换手率={market_context.get('turnover_rate')}, "
                             f"市值={market_context.get('circ_mv')}")
        except Exception as e:
            logger.debug(f"{ts_code} daily_basic 加载跳过: {e}")

        # 2) 资金流向
        try:
            df_mf = self.data_manager.get_cached_moneyflow(ts_code)
            if df_mf is not None and not df_mf.empty:
                # 取最近5日汇总
                recent_mf = df_mf.tail(5)
                market_context['net_lg_amount'] = float(recent_mf['net_lg_amount'].sum())
                market_context['net_mf_amount'] = float(recent_mf['net_mf_amount'].sum()) if 'net_mf_amount' in recent_mf.columns else 0
                market_context['buy_lg_amount'] = float(recent_mf['buy_lg_amount'].sum())
                market_context['sell_lg_amount'] = float(recent_mf['sell_lg_amount'].sum())
                logger.debug(f"{ts_code} 已加载资金流向: 近5日大单净额={market_context.get('net_lg_amount')}")
        except Exception as e:
            logger.debug(f"{ts_code} 资金流向加载跳过: {e}")

        # 3) 大盘环境: 通过沪深300最近N日收益率判断
        try:
            idx_df = self.benchmark_service.get_index_daily(BenchmarkIndex.HS300)
            if idx_df is not None and not idx_df.empty:
                idx_close_series = idx_df['close'].astype(float)
                idx_5d_ret = (idx_close_series.iloc[-1] / idx_close_series.iloc[-5] - 1) if len(idx_close_series) >= 5 else 0
                idx_20d_ret = (idx_close_series.iloc[-1] / idx_close_series.iloc[-20] - 1) if len(idx_close_series) >= 20 else 0
                if idx_5d_ret > 0.03 or idx_20d_ret > 0.05:
                    market_context['index_condition'] = 'GOOD'
                elif idx_5d_ret < -0.03 or idx_20d_ret < -0.05:
                    market_context['index_condition'] = 'POOR'
                else:
                    market_context['index_condition'] = 'NEUTRAL'
                market_context['idx_5d_ret'] = round(float(idx_5d_ret * 100), 2)
                market_context['idx_20d_ret'] = round(float(idx_20d_ret * 100), 2)
                logger.debug(f"{ts_code} 大盘环境: {market_context.get('index_condition')}, "
                             f"5日={market_context.get('idx_5d_ret')}%, 20日={market_context.get('idx_20d_ret')}%")
        except Exception as e:
            logger.debug(f"{ts_code} 大盘环境加载跳过: {e}")

        # 4) 基础市场状态识别 [P1-#25]
        try:
            from app.engine.framework.volume_price_strategy import StageDetector
            sd = StageDetector()
            market_state = sd.recognize_market_condition(df)
            market_context['market_state'] = market_state.get('market_state', 'UNKNOWN')
            market_context['ma_trend'] = market_state.get('ma_trend', 'neutral')
            market_context['market_volatility'] = market_state.get('bb_width', 0)
            logger.debug(f"{ts_code} 市场状态: {market_context.get('market_state')}")
        except Exception as e:
            logger.debug(f"{ts_code} 市场状态识别跳过: {e}")
            market_context['market_state'] = 'UNKNOWN'

        # [P2-#57] 状态依赖动态周期权重
        _state = market_context.get('market_state', 'UNKNOWN')
        if _state == 'TRENDING_BULL':
            cycle_weights = {'primary': 0.8, 'secondary': 0.2, 'execution': 0.0}
        elif _state == 'TRENDING_BEAR':
            cycle_weights = {'primary': 0.4, 'secondary': 0.6, 'execution': 0.0}
        elif _state == 'HIGH_VOL':
            cycle_weights = {'primary': 0.3, 'secondary': 0.3, 'execution': 0.4}
        elif _state == 'RANGING':
            cycle_weights = {'primary': 0.6, 'secondary': 0.4, 'execution': 0.0}
        else:
            cycle_weights = {'primary': 0.6, 'secondary': 0.3, 'execution': 0.1}
        market_context['cycle_weights'] = cycle_weights

        # 构建 market_env 字典（供量价/缠论策略使用）
        market_env = {}
        if market_context.get('index_condition'):
            market_env['condition'] = market_context['index_condition']
        if market_context.get('idx_5d_ret') is not None:
            market_env['index_return_5d'] = market_context['idx_5d_ret']

        signals = []

        # ── L2: 筹码主力分析信号 ──
        try:
            chip_signal = self._compute_chip_signal(ts_code, df, market_context)
            if chip_signal:
                signals.append(chip_signal)
        except Exception as e:
            logger.debug(f"{ts_code} Chip 信号计算失败: {e}")

        # ── L3: 缠论信号 ──
        try:
            chanlun_signal = self._compute_chanlun_signal(ts_code, df, market_context)
            if chanlun_signal:
                signals.append(chanlun_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 缠论信号计算失败: {e}")

        # ── L3: 因子评分信号 ──
        try:
            factor_signal = self._compute_factor_signal(ts_code, df, market_context)
            if factor_signal:
                signals.append(factor_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 因子信号计算失败: {e}")

        # ── L3: 量价分析信号 ──
        try:
            volume_price_signal = self._compute_volume_price_signal(ts_code, df, market_context, market_env)
            if volume_price_signal:
                signals.append(volume_price_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 量价信号计算失败: {e}")

        # ── BOCIASI 快线（情绪层）──
        try:
            bociasi_signal = self._compute_bociasi_signal(ts_code, df)
            if bociasi_signal:
                signals.append(bociasi_signal)
        except Exception as e:
            logger.debug(f"{ts_code} BOCIASI 信号计算失败: {e}")

        # ── BOCIASI 慢线（情绪层跨市场）[P1-#22] ──
        try:
            from app.engine.framework.bociasi_slowline import BociasiSlowLine
            bsl = BociasiSlowLine()
            # 获取指数数据
            try:
                index_data = self.benchmark_service.get_index_daily() if self.benchmark_service else None
            except Exception:
                index_data = None
            bociasi_slow = bsl.evaluate(df, index_df=index_data)
            if bociasi_slow:
                signals.append({
                    'strategy_name': 'BOCIASI慢线(情绪-跨市场)',
                    'signal': bociasi_slow.get('signal', 'NEUTRAL').lower(),
                    'signal_label': '做多' if bociasi_slow.get('signal') == 'BULLISH' else ('做空' if bociasi_slow.get('signal') == 'BEARISH' else '中性'),
                    'confidence': bociasi_slow.get('confidence', 0.3),
                    'evidence': [f"ERP={bociasi_slow['details'].get('erp','N/A')}", f"相对强度={bociasi_slow['details'].get('sb_details',{}).get('relative_strength','N/A')}%"],
                    'risk_notes': ['模型依赖PE数据和国债收益率近似值'],
                    'status_recognition': {
                        'state': 'ACCUMULATING' if bociasi_slow.get('signal') == 'BULLISH' else ('DISTRIBUTING' if bociasi_slow.get('signal') == 'BEARISH' else 'RANGING'),
                        'state_label': bociasi_slow.get('signal', 'NEUTRAL'),
                        'trend': {'direction': bociasi_slow.get('signal', ''), 'strength': '', 'stage': ''},
                        'momentum': {'level': bociasi_slow.get('signal', ''), 'score': bociasi_slow.get('confidence', 0.0)},
                        'volume': {'state': '', 'structure': ''},
                        'support_resistance': {'support': 0.0, 'resistance': 0.0},
                        'risk_level': 'MEDIUM',
                    },
                })
        except Exception as e:
            logger.debug(f"{ts_code} BOCIASI慢线跳过: {e}")

        # [P1-#26] 主决策周期方向约束: 周线(120日)看空时日线买入信号降权
        if market_context.get('market_state') == 'TRENDING_BEAR' or market_context.get('ma_trend') == 'bearish':
            for sig in signals:
                if sig.get('signal') == 'bullish':
                    sig['signal'] = 'watch'
                    sig['signal_label'] = '暂缓买入(周线偏空)'
                    sig['confidence'] = sig.get('confidence', 0.5) * 0.7
                    if 'evidence' in sig:
                        sig['evidence'].append('⚠️ 周线偏空，买入信号降权')
                elif sig.get('signal') == 'neutral':
                    sig['signal'] = 'watch'

        # 持久化到数据库
        self._persist_signals(ts_code, signals)

        return signals[:limit]


    def _compute_chip_signal(self, ts_code: str, df: pd.DataFrame, market_context: Optional[Dict] = None) -> Optional[Dict]:
        """计算筹码主力分析信号 (L2) — 使用完整 ChipDistributionStrategy"""
        # 确保 K 线数据包含 ts_code
        if 'ts_code' not in df.columns:
            df = df.copy()
            df['ts_code'] = ts_code

        # 运行完整筹码分析
        analysis = self.chip_strategy.analyze(df)
        
        # 检查 PreFilter 结果
        if not analysis.get('pre_filter_passed', True):
            logger.info(f"{ts_code} PreFilter未通过: {analysis.get('pre_filter_reason', '')}")
            return None
        
        recommendation = analysis.get('recommendation', {})
        phase_info = analysis.get('phase_info', {})
        signals = analysis.get('signals', {})
        market_env = analysis.get('market_environment', {})
        stock_filter = analysis.get('stock_filter', {})
        
        action = recommendation.get('action', 'HOLD')
        latest_close = float(df['close'].iloc[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())
        
        # 映射为统一信号格式
        if action == 'BUY':
            signal = StrategySignal.BULLISH.value
            signal_label = '买入'
        elif action == 'SELL':
            signal = StrategySignal.BEARISH.value
            signal_label = '卖出'
        else:
            signal = StrategySignal.NEUTRAL.value
            signal_label = '观望'
        
        # 从 recommendation 或信号细节中提取入场/止损/目标
        target_position = recommendation.get('target_position')
        if target_position is None:
            # 根据信号类型设置默认仓位
            if action == 'BUY':
                target_position = 0.5
            elif action == 'SELL':
                target_position = 0.0
            else:
                target_position = 0.1
        
        # 入场区间: 从信号细节获取或默认
        entry_low = round(latest_close * 0.97, 2)
        entry_high = round(latest_close * 1.02, 2)
        risk_line = round(latest_close * 0.92, 2)
        target_high = round(latest_close * 1.12, 2)
        
        # 构建分析证据
        evidence = []
        
        # 阶段信息
        phase = phase_info.get('phase_name', '未知')
        phase_confidence = phase_info.get('confidence', 0)
        evidence.append(f"阶段判定: {phase}({phase_confidence:.0%})")
        
        # 触发信号详情
        triggered_signals = []
        for sig_name in ['S_BUY', 'S_WASH_END', 'S_BOUNCE', 'S_SELL', 'S_WASH_STOP', 'S_DIVERG_SELL']:
            sig_detail = signals.get(sig_name, {})
            if sig_detail.get('triggered'):
                triggered_signals.append(sig_name)
        if triggered_signals:
            evidence.append(f"触发信号: {', '.join(triggered_signals)}")
        
        # K线形态
        patterns = signals.get('patterns', [])
        if patterns:
            evidence.append(f"K线形态: {', '.join(p.get('name', '') for p in patterns[:3])}")
        
        # 指标摘要
        indicators = analysis.get('indicators', {})
        if indicators:
            ind_parts = []
            if indicators.get('asr') is not None:
                ind_parts.append(f"ASR={indicators['asr']:.0%}")
            if indicators.get('profit_ratio') is not None:
                ind_parts.append(f"获利={indicators['profit_ratio']:.0%}")
            if indicators.get('vol_ratio') is not None:
                ind_parts.append(f"量比={indicators['vol_ratio']:.1f}")
            if ind_parts:
                evidence.append(f"指标: {' | '.join(ind_parts)}")
        
        # 大盘环境
        env = market_env.get('environment', {})
        if env.get('condition'):
            evidence.append(f"大盘: {env['condition']}({env.get('reason', '')[:30]})")

        # 市场扩展数据（换手率/资金流向）
        if market_context:
            tr = market_context.get('turnover_rate')
            if tr is not None:
                evidence.append(f"换手率: {tr:.2f}%")
            net_lg = market_context.get('net_lg_amount')
            if net_lg is not None and abs(net_lg) > 0:
                evidence.append(f"近5日大单净额: {net_lg:+.0f}")
            idx_cond = market_context.get('index_condition')
            if idx_cond:
                evidence.append(f"大盘环境: {idx_cond}")
            mv = market_context.get('circ_mv')
            if mv is not None:
                evidence.append(f"流通市值: {mv/1e8:.1f}亿")
        
        # 市值适配
        cap = stock_filter.get('cap_level', '')
        if cap:
            evidence.append(f"市值适配: {cap}")
        
        # 构建风险提示
        risk_notes = ['大盘系统性风险']
        if stock_filter.get('turnover_rate', 0) > 10:
            risk_notes.append('换手率极高，注意出货风险')
        if cap == 'MEGA':
            risk_notes.append('超大盘股流动性有限')
        
        # 信号置信度
        confidence = recommendation.get('confidence', 0.5)
        if confidence is None:
            confidence = 0.5

        # 筹码策略现状识别
        chip_status = {
            'state': 'ACCUMULATING' if action == 'BUY' else ('DISTRIBUTING' if action == 'SELL' else 'RANGING'),
            'state_label': signal_label,
            'trend': {'direction': '', 'strength': '', 'stage': phase},
            'momentum': {'level': action, 'score': round(float(confidence), 2)},
            'volume': {'state': '', 'structure': ''},
            'support_resistance': {'support': 0.0, 'resistance': 0.0},
            'risk_level': 'HIGH' if cap else 'MEDIUM',
        }

        return {
            'strategy_name': '筹码主力分析',
            'signal': signal,
            'signal_label': signal_label,
            'confidence': round(float(confidence), 2),
            'entry_zone': [entry_low, entry_high],
            'risk_line': risk_line,
            'target_zone': [entry_high, target_high],
            'position_suggestion': f'{int(target_position * 100)}%',
            'holding_period': '1-3个月',
            'evidence': evidence,
            'risk_notes': risk_notes,
            'signal_date': latest_date if isinstance(latest_date, str) else latest_date.strftime('%Y-%m-%d'),
            'backtest_win_rates': self._get_signal_win_rates(signal),
            # L3 缠论评分
            'chanlun_score': chanlun_score,
            'chanlun_recommendation': score_recommendation,
            'score_details': score_details,

            'signal_source_detail': {
                'phase': phase,
                'triggered_signals': triggered_signals,
                'patterns': [p.get('name', '') for p in patterns],
                'market_condition': env.get('condition', ''),
                'cap_level': cap,
                'pre_filter_pass': True,
            },
            'status_recognition': chip_status,
        }

    def _compute_chanlun_signal(self, ts_code: str, df: pd.DataFrame, market_context: Optional[Dict] = None) -> Optional[Dict]:
        """计算缠论策略建议 — 基于缠论决策树的全中文分析报告"""
        from app.engine.framework.chanlun_strategy import ChanlunAnalyzer, ChanlunScorer, BuySellPoint

        if df.empty or len(df) < 60:
            return None

        latest_close = float(df['close'].iloc[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())
        if not isinstance(latest_date, str):
            latest_date = str(latest_date)[:10]

        # 准备数据
        df_analysis = df.copy()
        if 'vol' in df_analysis.columns and 'volume' not in df_analysis.columns:
            df_analysis['volume'] = df_analysis['vol']
        if 'trade_date' not in df_analysis.columns:
            if isinstance(df_analysis.index, pd.DatetimeIndex):
                df_analysis['trade_date'] = df_analysis.index.strftime('%Y-%m-%d')
            else:
                df_analysis['trade_date'] = ''

        try:
            analyzer = ChanlunAnalyzer()
            result = analyzer.analyze(df_analysis)
        except Exception as e:
            logger.warning(f"{ts_code} ChanlunAnalyzer 异常: {e}")
            return None


        # L3 评分：缠论评分系统量化置信度
        try:
            score_result = ChanlunScorer.score(result, latest_close=latest_close, market_context=market_context)
            chanlun_score = score_result.get("score", 50)
            score_details = score_result.get("details", [])
            score_recommendation = score_result.get("recommendation", "HOLD")
        except Exception as e:
            logger.warning(f"{ts_code} ChanlunScorer 异常: {e}")
            chanlun_score = 50
            score_details = []
            score_recommendation = "HOLD"

        if not result.get('success') or 'error' in result:
            return None

        summary = result.get('summary', {})
        strokes = result.get('strokes', [])
        segments = result.get('segments', [])
        zhongshu_list = result.get('zhongshu', [])
        divergence = result.get('divergence')
        buy_points: List[BuySellPoint] = result.get('buy_points', [])
        sell_points: List[BuySellPoint] = result.get('sell_points', [])
        trend = result.get('trend', 'unknown')

        if not strokes:
            return None

        # ─── 1. 走势结构 ───
        last_stroke = strokes[-1]
        prev_stroke = strokes[-2] if len(strokes) >= 2 else None

        ls_end_price = float(last_stroke.end_price)
        price_offset = (latest_close / ls_end_price - 1) * 100

        seg_count = summary.get('total_segments', 0)
        zs_count = summary.get('total_zhongshu', 0)

        if last_stroke.direction == 'up':
            if price_offset >= -2:
                phase_detail = f"最后一笔为上升笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前{price_offset:+.2f}%, 仍在笔终点附近"
                last_bi_status = 'up_延续'
            else:
                phase_detail = f"最后一笔为上升笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前回落{abs(price_offset):.1f}%, 新下跌笔未确认"
                last_bi_status = 'up_结束_回调'
                if prev_stroke and prev_stroke.direction == 'down':
                    phase_detail += f"，前序下跌笔低点@{prev_stroke.end_price:.2f}"
        else:
            if price_offset <= 2:
                phase_detail = f"最后一笔为下降笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前{price_offset:+.2f}%, 仍在笔终点附近"
                last_bi_status = 'down_延续'
            else:
                phase_detail = f"最后一笔为下降笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前反弹{price_offset:.1f}%, 新上涨笔未确认"
                last_bi_status = 'down_结束_反弹'
                if prev_stroke and prev_stroke.direction == 'up':
                    phase_detail += f"，前序上涨笔高点@{prev_stroke.end_price:.2f}"

        # ─── 2. 中枢分析 ───
        latest_zhongshu = zhongshu_list[-1] if zhongshu_list else None
        zs_high = float(latest_zhongshu.high) if latest_zhongshu else None
        zs_low = float(latest_zhongshu.low) if latest_zhongshu else None
        zs_center = float(latest_zhongshu.center) if latest_zhongshu else None

        if latest_zhongshu and latest_close > zs_high:
            position_vs_zs = '上方'
            pct_from_zs = (latest_close / zs_high - 1) * 100
            position_detail = f"价格{latest_close:.2f}高于中枢上沿{zs_high:.2f}(+{pct_from_zs:.1f}%)"
        elif latest_zhongshu and latest_close < zs_low:
            position_vs_zs = '下方'
            pct_from_zs = (zs_low / latest_close - 1) * 100
            position_detail = f"价格{latest_close:.2f}低于中枢下沿{zs_low:.2f}(-{pct_from_zs:.1f}%)"
        elif latest_zhongshu:
            position_vs_zs = '内部'
            pct_from_zs = 0
            position_detail = f"价格{latest_close:.2f}在中枢区间[{zs_low:.2f}, {zs_high:.2f}]内"
        else:
            position_vs_zs = '无中枢'
            pct_from_zs = 0
            position_detail = '尚未形成中枢结构'

        # ─── 3. 买卖点过滤（当前中枢之后） ───
        recent_buy = []
        recent_sell = []
        zs_formed_date = str(latest_zhongshu.start_date)[:10] if latest_zhongshu and hasattr(latest_zhongshu, 'start_date') else None

        for p in buy_points:
            p_date = str(p.position.get('date', ''))[:10] if p.position else ''
            if zs_formed_date and p_date >= zs_formed_date:
                recent_buy.append(p)
            elif not zs_formed_date:
                recent_buy.append(p)

        for p in sell_points:
            p_date = str(p.position.get('date', ''))[:10] if p.position else ''
            if zs_formed_date and p_date >= zs_formed_date:
                recent_sell.append(p)
            elif not zs_formed_date:
                recent_sell.append(p)

        # 买卖点类型映射
        BP_TYPE_CN = {
            'first_buy': '第一类买点', 'second_buy': '第二类买点', 'third_buy': '第三类买点',
            'first_sell': '第一类卖点', 'second_sell': '第二类卖点', 'third_sell': '第三类卖点',
        }
        BP_ORDER = {'first_buy': 1, 'second_buy': 2, 'third_buy': 3,
                    'first_sell': 1, 'second_sell': 2, 'third_sell': 3}

        # ─── 4. 缠论决策树 ───
        trend_cn = {'up': '上升', 'down': '下降', 'unknown': '待定'}
        trend_str = trend_cn.get(trend, '待定')
        
        # 初始化决策变量
        action = '静待观察'
        action_reason_parts = []
        confidence = 0.5
        
        # 建仓策略
        position_plan = []  # 分档建仓描述列表
        stop_loss_settings = []  # 止损设置
        target_reference = []  # 止盈参考
        
        # 等待信号
        watch_signals = []
        
        # 统计买卖点类型
        buy_types = set(p.type for p in recent_buy)
        sell_types = set(p.type for p in recent_sell)
        has_first_buy = 'first_buy' in buy_types
        has_second_buy = 'second_buy' in buy_types
        has_third_buy = 'third_buy' in buy_types
        has_first_sell = 'first_sell' in sell_types
        has_second_sell = 'second_sell' in sell_types
        has_third_sell = 'third_sell' in sell_types
        
        # 最近买点和卖点
        best_buy = max(recent_buy, key=lambda p: BP_ORDER.get(p.type, 0)) if recent_buy else None
        best_sell = max(recent_sell, key=lambda p: BP_ORDER.get(p.type, 0)) if recent_sell else None
        
        # 最近买点距当前价的涨幅
        buy_price_pct = None
        if best_buy:
            bp = best_buy.position.get('price', latest_close)
            buy_price_pct = (latest_close / bp - 1) * 100
        
        # 最近卖点距当前价的跌幅
        sell_price_pct = None
        if best_sell:
            sp = best_sell.position.get('price', latest_close)
            sell_price_pct = (sp / latest_close - 1) * 100

        # ========== 决策树 ==========
        if trend == 'up':
            # 趋势向上
            if position_vs_zs == '上方':
                if has_first_buy:
                    action = '买入建仓'
                    confidence = 0.75
                    action_reason_parts.append(f"上升趋势中出现第一类买点(背驰点)，趋势转折早期信号")
                    position_plan = [
                        "第一档(试探): 当前价附近建仓 5%，确认背驰有效",
                        "第二档(确认): 回调不破买点价时加仓至 10%",
                        "第三档(加仓): 突破前高且5日线上穿10日线时加仓至 15%",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 跌破买点价下方 5%",
                        "移动止损: 第二类买点确认后，止损上移至二买价下方",
                        "缠论结构止损: 若出现第三类卖点则清仓",
                    ]
                    target_reference = [
                        f"第一目标: 前笔终点 {last_stroke.end_price:.2f}",
                        "第二目标: 突破前高后看线段延伸",
                    ]
                elif has_third_buy and buy_price_pct is not None and 0 <= buy_price_pct < 20:
                    action = '买入建仓'
                    confidence = 0.70
                    action_reason_parts.append(f"上升趋势+三类买点@最近买点价, 当前涨幅{buy_price_pct:.0f}%仍具性价比")
                    position_plan = [
                        f"第一档(追击): 当前价 {latest_close:.2f} 建仓 10%",
                        f"第二档(确认): 若回调不进入中枢(>={zs_high:.2f})则加仓至 15%",
                        "第三档(加仓): 等待新一笔上涨确认后再评估",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 跌破中枢上沿 {zs_high:.2f} (-{(1 - zs_high/latest_close)*100:.0f}%)",
                        "移动止损: 沿5日线持有，拐头向下减半仓",
                        "缠论结构止损: 本级别出现第二类卖点",
                    ]
                    target_reference = [
                        f"第一目标: 前笔终点 {last_stroke.end_price:.2f}",
                        "第二目标: 突破前高后看线段延伸情况",
                    ]
                elif buy_price_pct is not None and buy_price_pct >= 30:
                    action = '静待观察'
                    confidence = 0.65
                    action_reason_parts.append(f"最近买点已上涨 {buy_price_pct:.0f}%，已远离买点区域，当前性价比较低")
                    watch_signals = [
                        "信号A: 若回调出现盘整背驰 → 可考虑第一类买点试探建仓",
                        f"信号B: 若回调至中枢上沿 {zs_high:.2f} 附近企稳 → 可考虑中枢内操作",
                        "信号C: 若直接跌破中枢 → 趋势转弱，继续等待",
                    ]
                elif buy_price_pct is not None and buy_price_pct < 0:
                    action = '静待观察'
                    confidence = 0.55
                    action_reason_parts.append(f"最近买点价 {best_buy.position.get('price',0):.2f}，当前价 {latest_close:.2f} 已跌破买点价 {abs(buy_price_pct):.1f}%，回调深度超预期，等待企稳")
                    watch_signals = [
                        f"信号A: 回调在中枢上沿 {zs_high:.2f} 上方企稳 → 可等待第二类买点",
                        f"信号B: 若继续跌破中枢上沿 {zs_high:.2f} → 观察中枢内部是否盘整背驰",
                        "信号C: 出现新低后观察下跌背驰 → 第一类买点试探建仓",
                    ]
                elif last_bi_status == 'up_延续':
                    action = '持仓观察'
                    confidence = 0.55
                    action_reason_parts.append("上升趋势中，最后一笔向上延续，持仓等待卖点信号")
                    watch_signals = [
                        "注意: 关注是否出现背驰信号，一旦出现第一类卖点考虑减仓",
                        "若持续上涨无背驰，可继续持有",
                    ]
                elif last_bi_status == 'up_结束_回调':
                    action = '静待观察'
                    confidence = 0.55
                    action_reason_parts.append(f"上升趋势中，上涨笔结束, 回调{abs(price_offset):.1f}%，等待企稳信号")
                    watch_signals = [
                        f"信号A: 回调在中枢上沿 {zs_high:.2f} 上方企稳 → 可关注第二类买点",
                        f"信号B: 回调进入中枢内部 → 需观察中枢下沿 {zs_low:.2f} 支撑",
                        "信号C: 出现下跌背驰 → 第一类买点试探建仓",
                    ]
                else:
                    action = '静待观察'
                    confidence = 0.50
                    action_reason_parts.append(f"上升趋势中, 当前状态待确认 ({last_bi_status})")
                    watch_signals = ["等待新一笔方向确认后再评估"]
            
            elif position_vs_zs == '内部':
                if has_first_buy:
                    action = '买入建仓'
                    confidence = 0.65
                    action_reason_parts.append("中枢内出现第一类买点(背驰)，可试探建仓")
                    position_plan = [
                        f"第一档(试探): 当前价 {latest_close:.2f} 建仓 5%",
                        "第二档(确认): 突破中枢上沿后加仓至 10%",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 跌破中枢下沿 {zs_low:.2f}",
                        "缠论结构止损: 若出现第三类卖点则清仓",
                    ]
                    target_reference = [
                        f"第一目标: 中枢上沿 {zs_high:.2f}",
                        "第二目标: 突破中枢后看上沿上方",
                    ]
                elif has_third_buy:
                    action = '买入建仓'
                    confidence = 0.70
                    action_reason_parts.append("中枢内出现第三类买点，趋势即将突破")
                    position_plan = [
                        f"第一档(追击): 当前价 {latest_close:.2f} 建仓 10%",
                        "第二档(确认): 确认突破中枢后加仓至 15%",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 重回中枢内部(跌破 {zs_high:.2f})",
                        "缠论结构止损: 本级别出现第二类卖点",
                    ]
                    target_reference = [
                        f"第一目标: 突破中枢上沿 {zs_high:.2f}",
                    ]
                else:
                    action = '静待观察'
                    confidence = 0.45
                    action_reason_parts.append("中枢内震荡，等待方向突破")
                    watch_signals = [
                        f"信号A: 向上突破中枢上沿 {zs_high:.2f} → 第三类买点追击",
                        f"信号B: 向下突破中枢下沿 {zs_low:.2f} → 防第三类卖点",
                    ]
            else:
                action = '静待观察'
                confidence = 0.50
                action_reason_parts.append("上升趋势但价格低于中枢，走势结构有矛盾，需等待确认")
                watch_signals = ["等待价格回到中枢内再评估"]

        elif trend == 'down':
            if has_third_sell:
                action = '清仓'
                confidence = 0.75
                action_reason_parts.append("下降趋势+第三类卖点，趋势确认向下，建议清仓规避")
                stop_loss_settings = ["已持仓: 立即止损清仓", "未持仓: 不参与下降趋势"]
                watch_signals = [
                    "等待信号: 出现下跌背驰+第一类买点后才考虑介入",
                ]
            elif has_first_buy:
                action = '买入建仓'
                confidence = 0.60
                action_reason_parts.append("下降趋势中出现第一类买点(背驰)，可试探建仓，严格止损")
                position_plan = [
                    f"第一档(试探): 当前价 {latest_close:.2f} 轻仓 5%",
                    "第二档(确认): 回调不创新低(第二类买点)时加仓至 10%",
                ]
                stop_loss_settings = [
                    f"硬止损: 跌破第一类买点价下方 5%",
                    f"止损参考: 买点价格 (可参考最近买点)",
                    "缠论结构止损: 若继续下跌出现第三类卖点则清仓",
                ]
                target_reference = [
                    f"第一目标: 中枢下沿 {zs_low:.2f}",
                    "第二目标: 中枢中心区域",
                ]
            elif has_second_buy:
                action = '买入建仓'
                confidence = 0.65
                action_reason_parts.append("下降趋势中出现第二类买点(回调确认)，底部区域")
                position_plan = [
                    f"第一档(试探): 当前价 {latest_close:.2f} 建仓 5%",
                    "第二档(确认): 确认反弹后加仓至 10%",
                ]
                stop_loss_settings = [
                    f"硬止损: 跌破最近低点",
                    "缠论结构止损: 若出现第三类卖点则清仓",
                ]
                target_reference = [
                    f"第一目标: 中枢下沿 {zs_low:.2f}",
                ]
            elif last_bi_status in ('down_延续',):
                action = '静待观察'
                confidence = 0.55
                action_reason_parts.append("下降趋势中，下跌笔延续，等待底部确认")
                watch_signals = [
                    "信号A: 出现下跌背驰+第一类买点 → 可试探建仓",
                    "信号B: 在下方形成新的中枢后再评估",
                ]
            else:
                action = '静待观察'
                confidence = 0.50
                action_reason_parts.append("下降趋势中，等待趋势转折信号")
                watch_signals = [
                    "信号A: 出现下跌背驰 → 第一类买点可试探",
                    f"信号B: 回到中枢内部 → 需重新评估",
                ]
        else:
            action = '静待观察'
            confidence = 0.35
            action_reason_parts.append("趋势不明朗，无可靠信号，建议观望")
            watch_signals = [
                "等待至少形成新的线段后判断方向",
            ]

        # ─── 5. 构建英文兼容字段（供系统消费） ───
        signal_map = {
            '买入建仓': StrategySignal.BULLISH.value,
            '持仓观察': StrategySignal.WATCH.value,
            '静待观察': StrategySignal.WATCH.value,
            '清仓': StrategySignal.BEARISH.value,
        }
        signal_label_map = {
            '买入建仓': '买入',
            '持仓观察': '观望',
            '静待观察': '观望',
            '清仓': '卖出',
        }
        internal_signal = signal_map.get(action, StrategySignal.NEUTRAL.value)
        internal_label = signal_label_map.get(action, '中性')

        entry_low = round(latest_close * 0.97, 2)
        entry_high = round(latest_close * 1.03, 2)
        risk_line = round(latest_close * 0.92, 2)
        target_val = round(latest_close * 1.12, 2)

        # 构建证据列表（英文兼容）
        evidence_list = []
        evidence_list.append(f"当前趋势: {trend_str} ({seg_count}段, {zs_count}中枢)")
        evidence_list.append(f"当前笔阶段: {phase_detail}")
        evidence_list.append(f"价格位置: {position_detail}")
        if latest_zhongshu:
            evidence_list.append(f"中枢区间: [{zs_low:.2f}, {zs_high:.2f}] 中心={zs_center:.2f}")
        if recent_buy:
            bt = [BP_TYPE_CN.get(p.type, p.type) for p in recent_buy]
            evidence_list.append(f"中枢形成后买点: {len(recent_buy)}个 ({', '.join(sorted(set(bt)))})")
        if recent_sell:
            st = [BP_TYPE_CN.get(p.type, p.type) for p in recent_sell]
            evidence_list.append(f"中枢形成后卖点: {len(recent_sell)}个 ({', '.join(sorted(set(st)))})")
        if divergence:
            div_dir = {'up': '上涨', 'down': '下跌'}.get(divergence.direction, '')
            div_type_map = {'trend': '趋势', 'consolidation': '盘整', 'zhongshu': '中枢破坏'}
            div_type = div_type_map.get(divergence.type, divergence.type)
            evidence_list.append(f"背驰: {div_dir}{div_type}背驰 (置信度={divergence.confidence:.2f})")
        evidence_list.append(f"分析建议: {action}")

        risk_notes = ['缠论信号具有滞后性']
        if buy_price_pct is not None and buy_price_pct > 20:
            risk_notes.append(f"最近买点已上涨 {buy_price_pct:.0f}%，追高风险较大")
        if pct_from_zs and abs(pct_from_zs) > 40:
            risk_notes.append(f"价格距中枢较远({abs(pct_from_zs):.0f}%)，回归中枢的可能性存在")
        if trend == 'unknown':
            risk_notes.append('趋势不明朗，建议控制仓位')

        # ─── 6. 构建全中文分析报告 ───
        report_lines = []
        report_lines.append(f"{ts_code} — {latest_date} 缠论分析报告")
        report_lines.append("")
        report_lines.append("【走势结构】")
        report_lines.append(f"  趋势方向：{trend_str}（{seg_count}段, {zs_count}中枢）")
        report_lines.append(f"  当前笔阶段：{phase_detail}")
        report_lines.append("")
        report_lines.append("【中枢分析】")
        if latest_zhongshu:
            report_lines.append(f"  最新中枢区间：[{zs_low:.2f}, {zs_high:.2f}]，中心 {zs_center:.2f}")
            report_lines.append(f"  价格相对中枢：{position_vs_zs}（{position_detail}）")
        else:
            report_lines.append("  尚未形成中枢结构")
        report_lines.append("")
        report_lines.append("【买卖点信号】")
        if recent_buy or recent_sell:
            if recent_buy:
                for p in recent_buy:
                    p_price = p.position.get('price', 0)
                    p_date = str(p.position.get('date', ''))[:10]
                    p_type_cn = BP_TYPE_CN.get(p.type, p.type)
                    p_pct = (latest_close / p_price - 1) * 100 if p_price else 0
                    report_lines.append(f"  买入: {p_type_cn} @{p_price:.2f} ({p_date}), 距当前+{p_pct:.0f}%")
            if recent_sell:
                for p in recent_sell:
                    p_price = p.position.get('price', 0)
                    p_date = str(p.position.get('date', ''))[:10]
                    p_type_cn = BP_TYPE_CN.get(p.type, p.type)
                    p_pct = (p_price / latest_close - 1) * 100 if p_price else 0
                    report_lines.append(f"  卖出: {p_type_cn} @{p_price:.2f} ({p_date}), 距当前-{p_pct:.0f}%")
            report_lines.append("")
        else:
            report_lines.append("  中枢形成后无买卖点信号")
            report_lines.append("")
        if divergence:
            div_dir = {'up': '上涨', 'down': '下跌'}.get(divergence.direction, '')
            div_type_map = {'trend': '趋势', 'consolidation': '盘整', 'zhongshu': '中枢破坏'}
            div_type = div_type_map.get(divergence.type, divergence.type)
            report_lines.append(f"  背驰: {div_dir}{div_type}背驰 (置信度={divergence.confidence:.2f})")
            report_lines.append("")
        
        report_lines.append("【操作建议】")
        report_lines.append(f"建议动作：{action}")
        report_lines.append(f"建议置信度：{confidence:.0%}")
        report_lines.append("")
        if action == '买入建仓':
            report_lines.append(f"买入依据：{'；'.join(action_reason_parts)}")
            report_lines.append("")
            report_lines.append("建仓策略：")
            for plan_line in position_plan:
                report_lines.append(f"  {plan_line}")
            report_lines.append("")
            report_lines.append("止损设置：")
            for sl_line in stop_loss_settings:
                report_lines.append(f"  {sl_line}")
            report_lines.append("")
            if target_reference:
                report_lines.append("止盈参考：")
                for tr_line in target_reference:
                    report_lines.append(f"  {tr_line}")
        elif action == '清仓':
            report_lines.append(f"清仓理由：{'；'.join(action_reason_parts)}")
            if stop_loss_settings:
                report_lines.append("")
                report_lines.append("操作策略：")
                for sl_line in stop_loss_settings:
                    report_lines.append(f"  {sl_line}")
        elif action == '持仓观察':
            report_lines.append(f"当前状态：{'；'.join(action_reason_parts)}")
        else:
            report_lines.append(f"等待理由：{'；'.join(action_reason_parts)}")
            report_lines.append("")
            report_lines.append("等待信号：")
            for ws in watch_signals:
                report_lines.append(f"  {ws}")
        
        report_lines.append("")
        # L3 评分汇总
        report_lines.append(f"缠论评分: {chanlun_score:.0f}/100 ({score_recommendation})")
        if score_details:
            report_lines.append("评分明细:")
            for sd in score_details[:5]:
                report_lines.append(f"  {sd}")
        report_lines.append("")

        report_lines.append("风险提示：")
        for rn in risk_notes:
            report_lines.append(f"  注意: {rn}")
        if pct_from_zs and abs(pct_from_zs) > 20:
            report_lines.append(f"  注意: 当前价格距中枢{abs(pct_from_zs):.0f}%，趋势一旦反转回调空间大")

        analysis_report = '\n'.join(report_lines)

        # 仓位和建议周期（兼容字段）
        if action == '买入建仓':
            pos_sug = '15%'
            hold_period = '1~3个月(等待上升段走完)'
        elif action == '清仓':
            pos_sug = '0%'
            hold_period = '立即'
        else:
            pos_sug = '0%'
            hold_period = '观望'

        return {
            'strategy_name': '缠论走势分析',
            'signal': internal_signal,
            'signal_label': internal_label,
            'confidence': round(confidence, 2),
            'entry_zone': [entry_low, entry_high],
            'risk_line': risk_line,
            'target_zone': [entry_high, target_val],
            'position_suggestion': pos_sug,
            'holding_period': hold_period,
            'evidence': evidence_list,
            'risk_notes': risk_notes,
            'signal_date': latest_date,
            'backtest_win_rates': self._get_signal_win_rates(internal_signal),
            # L3 缠论评分
            'chanlun_score': chanlun_score,
            'chanlun_recommendation': score_recommendation,
            'score_details': score_details,


            # 缠论结构化分析详情（供前端结构化展示）
            'chanlun_analysis_detail': {
                '走势结构': {
                    '趋势方向': trend_str,
                    '线段数量': seg_count,
                    '中枢数量': zs_count,
                    '当前笔阶段': last_bi_status,
                    '笔阶段详情': phase_detail,
                },
                '中枢分析': {
                    '最新中枢区间': [zs_low, zs_high],
                    '中枢中心': zs_center,
                    '价格相对位置': position_vs_zs,
                    '价格详情': position_detail,
                } if latest_zhongshu else {},
                '买卖点信号': {
                    '中枢形成后买点数': len(recent_buy),
                    '中枢形成后卖点数': len(recent_sell),
                    '最近买点': {
                        '类型': BP_TYPE_CN.get(best_buy.type, best_buy.type),
                        '日期': str(best_buy.position.get('date', ''))[:10],
                        '价格': round(best_buy.position.get('price', 0), 2),
                        '当前涨幅': round(buy_price_pct, 1),
                    } if best_buy else None,
                    '最近卖点': {
                        '类型': BP_TYPE_CN.get(best_sell.type, best_sell.type),
                        '日期': str(best_sell.position.get('date', ''))[:10],
                        '价格': round(best_sell.position.get('price', 0), 2),
                        '当前跌幅': round(sell_price_pct, 1),
                    } if best_sell else None,
                    '背驰信号': {
                        '方向': divergence.direction,
                        '类型': divergence.type,
                        '置信度': round(divergence.confidence, 2),
                    } if divergence else None,
                },
                '操作建议': {
                    '建议动作': action,
                    '建议置信度': round(confidence, 2),
                    '依据': '; '.join(action_reason_parts) if action_reason_parts else None,
                    '建仓策略': position_plan if position_plan else None,
                    '止损设置': stop_loss_settings if stop_loss_settings else None,
                    '止盈参考': target_reference if target_reference else None,
                    '等待信号': watch_signals if watch_signals else None,
                },
            },
            
            # 全中文分析报告（主要用户输出）
            '分析报告': analysis_report,

            # 缠论现状识别
            'status_recognition': {
                'state': 'ACCUMULATING' if trend_str == '上升' else ('BEARISH' if trend_str == '下降' else 'RANGING'),
                'state_label': trend_str or '方向待定',
                'trend': {
                    'direction': 'up' if trend_str == '上升' else ('down' if trend_str == '下降' else ''),
                    'strength': 'strong' if '延续' in (last_bi_status or '') else 'weakening',
                    'stage': last_bi_status or '',
                },
                'momentum': {
                    'level': str(divergence.direction) if divergence else '',
                    'score': round(divergence.confidence, 4) if divergence else 0.0,
                },
                'volume': {'state': '', 'structure': ''},
                'support_resistance': {
                    'support': round(float(zs_low), 2) if zs_low else 0.0,
                    'resistance': round(float(zs_high), 2) if zs_high else 0.0,
                },
                'risk_level': 'HIGH' if trend_str == '下降' and confidence < 0.5 else 'MEDIUM',
            },
        }
    def _compute_factor_signal(self, ts_code: str, df: pd.DataFrame, market_context: Optional[Dict] = None) -> Optional[Dict]:
        """计算因子评分信号 (L3) — 优先使用 FactorRegistry"""
        closes = df['close'].values
        volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
        latest_close = float(closes[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())

        if len(closes) < 20:
            return None

        # 尝试 FactorRegistry 计算
        registry_scores, registry_ok = self._compute_via_registry(df)
        if registry_ok:
            scores = registry_scores
            weights = {'ROC': 0.25, 'VOL_RATIO': 0.20, 'ATR': 0.15, 'RSI': 0.25, 'LINEARREG_SLOPE': 0.15}
            composite = sum(scores.get(k, 0.5) * weights[k] for k in weights)
            evidence_keys = list(scores.keys())

            # [P2-#55] 状态依赖动态权重矩阵
            try:
                from app.engine.framework.state_dependent_factor_weight import StateDependentFactorWeight
                market_state = (market_context or {}).get('market_state', 'UNKNOWN') if market_context else 'UNKNOWN'
                # 映射因子分数到4个语义类别
                mapped_scores = {
                    'momentum': (scores.get('ROC', 0.5) + scores.get('LINEARREG_SLOPE', 0.5)) / 2,
                    'reversal': 1 - abs(scores.get('RSI', 0.5) - 0.5) * 2,  # RSI偏离0.5越远=反转信号越强
                    'sentiment': scores.get('VOL_RATIO', 0.5),
                    'chip': scores.get('ATR', 0.5),
                }
                dyn = StateDependentFactorWeight().compute_weighted_score(mapped_scores, market_state)
                if abs(dyn['score'] - composite) > 0.2:
                    scores['dynamic_weight_adjusted'] = True
                scores['dynamic_weight_detail'] = dyn['weight_detail']
                scores['dynamic_weighted_score'] = dyn['score']
                scores['dynamic_market_state'] = market_state
            except Exception:
                pass
        else:
            # 降级到内联计算
            scores, composite = self._compute_factor_signal_inline(closes, volumes)
            evidence_keys = list(scores.keys())

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
            'evidence': [f"{k}: {scores[k]:.2f}" for k in evidence_keys],
            'risk_notes': ['因子模型假设偏差', '市场风格切换风险'],
            'signal_date': latest_date if isinstance(latest_date, str) else latest_date.strftime('%Y-%m-%d'),
            'backtest_win_rates': self._get_signal_win_rates(signal),

            # 因子现状识别
            'status_recognition': {
                'state': 'ACCUMULATING' if composite >= 0.6 else ('BEARISH' if composite < 0.4 else 'RANGING'),
                'state_label': signal_label,
                'trend': {'direction': '', 'strength': '', 'stage': ''},
                'momentum': {
                    'level': signal,
                    'score': round(max(scores.values()), 4) if scores else round(composite, 4),
                },
                'volume': {'state': '', 'structure': ''},
                'support_resistance': {'support': 0.0, 'resistance': 0.0},
                'risk_level': 'HIGH' if composite < 0.4 else 'LOW',
            },
        }

    def _compute_via_registry(self, df: pd.DataFrame) -> tuple:
        """通过 FactorRegistry 计算因子评分"""
        try:
            calculator = FactorCalculator()
            factor_configs = [
                {'name': 'ROC', 'params': {'period': 20}},
                {'name': 'VOL_RATIO', 'params': {'period': 5}},
                {'name': 'ATR', 'params': {'period': 14}},
                {'name': 'RSI', 'params': {'period': 14}},
                {'name': 'LINEARREG_SLOPE', 'params': {'period': 20}},
            ]
            scores = {}
            for cfg in factor_configs:
                series = calculator.calculate_single_factor(df, cfg['name'], **cfg['params'])
                if series is not None and not series.empty:
                    val = float(series.iloc[-1])
                    # 归一化到 [0,1]
                    name = cfg['name']
                    if name == 'ROC':
                        scores[name] = min(max(val * 5 + 0.5, 0), 1)
                    elif name == 'VOL_RATIO':
                        scores[name] = min(val * 0.4, 1)
                    elif name == 'ATR':
                        # ATR 归一化：相对价格位置
                        scores[name] = min(val / (float(df['close'].iloc[-1]) * 0.1 + 1e-9), 1)
                    elif name == 'RSI':
                        scores[name] = 1 - abs(val - 50) / 50
                    elif name == 'LINEARREG_SLOPE':
                        scores[name] = min(max(val * 10 + 0.5, 0), 1)
            if len(scores) >= 3:
                return scores, True
        except Exception as e:
            logger.debug(f"FactorRegistry 计算降级: {e}")
        return {}, False

    def _compute_factor_signal_inline(self, closes: np.ndarray, volumes: np.ndarray) -> tuple:
        """内联因子计算（降级后备）"""
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

        weights = {'momentum': 0.3, 'volume': 0.25, 'volatility': 0.2, 'rsi': 0.25}
        composite = sum(scores[k] * weights[k] for k in weights)
        return scores, composite

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

    def _build_chip_status(self, chip_signal: Dict) -> Dict:
        """构建筹码策略的现状识别"""
        phase = chip_signal.get('signal_source_detail', {}).get('phase', '')
        signal = chip_signal.get('signal', 'NEUTRAL')

        # 状态判定
        if '吸筹' in phase or '吸筹' in str(chip_signal.get('evidence', [])):
            state, label = 'ACCUMULATING', '主力吸筹'
        elif '出货' in phase or '派发' in phase:
            state, label = 'DISTRIBUTING', '主力出货'
        elif signal in ('BULLISH',):
            state, label = 'ACCUMULATING', '偏向看多'
        elif signal in ('BEARISH',):
            state, label = 'DISTRIBUTING', '偏向看空'
        else:
            state, label = 'RANGING', '方向不明'

        cap_level = chip_signal.get('signal_source_detail', {}).get('cap_level', '')
        risk_level = 'HIGH' if cap_level in ('MEGA',) else 'MEDIUM'

        return {
            'state': state,
            'state_label': label,
            'trend': {'direction': '', 'strength': '', 'stage': phase},
            'momentum': {'level': signal, 'score': chip_signal.get('confidence', 0.5)},
            'volume': {'state': '', 'structure': ''},
            'support_resistance': {'support': 0.0, 'resistance': 0.0},
            'risk_level': risk_level,
        }

    def _build_chanlun_status(self, chanlun_signal: Dict) -> Dict:
        """构建缠论策略的现状识别"""
        detail = chanlun_signal.get('chanlun_analysis_detail', {})
        structure = detail.get('走势结构', {})
        zhongshu = detail.get('中枢分析', {})
        ops = detail.get('操作建议', {})

        trend_str = structure.get('趋势方向', '')
        if trend_str == '上升':
            state, label = 'ACCUMULATING', '上升趋势'
        elif trend_str == '下降':
            state, label = 'BEARISH', '下降趋势'
        else:
            state, label = 'RANGING', '方向待定'

        bi_status = structure.get('当前笔阶段', '')
        trend = {
            'direction': 'up' if trend_str == '上升' else ('down' if trend_str == '下降' else ''),
            'strength': 'strong' if '延续' in bi_status else 'weakening',
            'stage': bi_status,
        }

        zs_interval = zhongshu.get('最新中枢区间', [])
        support_resistance = {
            'support': round(float(zs_interval[0]), 2) if len(zs_interval) > 0 else 0.0,
            'resistance': round(float(zs_interval[1]), 2) if len(zs_interval) > 1 else 0.0,
        }

        div = detail.get('买卖点信号', {}).get('背驰信号')
        momentum = {
            'level': str(div.get('方向', '')) if div else '',
            'score': float(div.get('置信度', 0)) if div else 0.0,
        }

        score = chanlun_signal.get('chanlun_score', 50)
        risk_level = 'HIGH' if (score < 30 or state == 'BEARISH') else 'MEDIUM'

        return {
            'state': state,
            'state_label': label,
            'trend': trend,
            'momentum': momentum,
            'volume': {'state': '', 'structure': ''},
            'support_resistance': support_resistance,
            'risk_level': risk_level,
        }

    def _build_factor_status(self, factor_signal: Dict) -> Dict:
        """构建因子策略的现状识别"""
        signal = factor_signal.get('signal', 'NEUTRAL')
        confidence = factor_signal.get('confidence', 0.5)

        if confidence >= 0.6 and signal in ('BULLISH',):
            state, label = 'ACCUMULATING', '因子看多'
        elif confidence < 0.4 or signal in ('BEARISH',):
            state, label = 'BEARISH', '因子看空'
        else:
            state, label = 'RANGING', '因子中性'

        # 从 evidence 提取因子得分
        ev = factor_signal.get('evidence', [])
        scores = {}
        for e in ev:
            parts = e.split(':')
            if len(parts) == 2:
                try:
                    scores[parts[0].strip()] = float(parts[1].strip())
                except ValueError:
                    pass

        max_score = max(scores.values()) if scores else 0.0
        momentum = {'level': signal, 'score': round(max_score, 4)}

        risk_level = 'HIGH' if state == 'BEARISH' else 'LOW'

        return {
            'state': state,
            'state_label': label,
            'trend': {'direction': '', 'strength': '', 'stage': ''},
            'momentum': momentum,
            'volume': {'state': '', 'structure': ''},
            'support_resistance': {'support': 0.0, 'resistance': 0.0},
            'risk_level': risk_level,
        }

    def _compute_bociasi_signal(self, ts_code: str, df: pd.DataFrame) -> Optional[Dict]:
        """计算 BOCIASI 快线情绪信号"""
        from app.engine.framework.bociasi_quickline import BociasiQuickLine
        try:
            bql = BociasiQuickLine()
            result = bql.evaluate(df)
            if result['pass_count'] == 0:
                return None

            signal_map = {'BUY': 'BULLISH', 'WATCH': 'WATCH', 'NEUTRAL': 'NEUTRAL'}
            label_map = {'BUY': '情绪积极', 'WATCH': '情绪中性', 'NEUTRAL': '情绪低迷'}
            ind = result['indicators']

            evidence = []
            if ind.get('fast_vol'):
                evidence.append(f"放量确认: 量比{result['details']['vol_ratio']:.1f}x")
            if ind.get('fast_price'):
                evidence.append(f"价格强势: 收于5日均价之上(+{result['details']['price_offset_pct']:.1f}%)")
            if ind.get('fast_mom'):
                evidence.append(f"短期动量: 5日涨幅{result['details']['mom_5d_pct']:.1f}%")
            if ind.get('fast_breadth'):
                evidence.append(f"波动活跃: 日内振幅{result['details']['amplitude_pct']:.1f}%")

            return {
                'strategy_name': 'BOCIASI快线',
                'signal': signal_map.get(result['signal'], 'NEUTRAL'),
                'signal_label': label_map.get(result['signal'], '情绪中性'),
                'confidence': result['confidence'],
                'entry_zone': [0, 0],
                'risk_line': 0,
                'target_zone': [0, 0],
                'position_suggestion': '0%',
                'holding_period': '短期（3-5日）',
                'evidence': evidence,
                'risk_notes': ['情绪指标偏短期，需结合其他策略使用'],
                'signal_date': '',
                'status_recognition': {
                    'state': 'ACCUMULATING' if result['signal'] == 'BUY' else ('DISTRIBUTING' if result['signal'] == 'NEUTRAL' else 'RANGING'),
                    'state_label': label_map.get(result['signal'], ''),
                    'trend': {'direction': '', 'strength': '', 'stage': ''},
                    'momentum': {'level': result['signal'], 'score': result['confidence']},
                    'volume': {'state': '放量' if ind.get('fast_vol') else '平量', 'structure': ''},
                    'support_resistance': {'support': 0.0, 'resistance': 0.0},
                    'risk_level': 'LOW' if result['signal'] == 'BUY' else 'MEDIUM',
                },
            }
        except Exception as e:
            logger.debug(f"{ts_code} BOCIASI 信号异常: {e}")
            return None

    def _compute_volume_price_signal(self, ts_code: str, df: pd.DataFrame,
                                      market_context: Optional[Dict] = None,
                                      market_env: Optional[Dict] = None) -> Optional[Dict]:
        """计算量价分析信号 (L3) — 完整四阶段分析链"""
        from app.engine.framework.volume_price_strategy import compute_volume_price_signal
        try:
            # [P2-#57] 注入动态周期权重
            env = dict(market_env or {})
            if market_context and 'cycle_weights' in market_context:
                env['cycle_weights'] = market_context['cycle_weights']

            result = compute_volume_price_signal(ts_code, df, market_env=env)
            if result and market_context and 'cycle_weights' in market_context:
                cw = market_context['cycle_weights']
                result['cycle_weights'] = cw
                # 根据周期权重微调信号置信度
                if cw.get('execution', 0) >= 0.3:
                    result['confidence'] = round(result.get('confidence', 0.5) * 0.85, 2)
                    result.setdefault('evidence', []).append(
                        f"[周期权重] 执行层{cw['execution']:.0%}，保守处理"
                    )
            return result
        except Exception as e:
            logger.debug(f"{ts_code} 量价信号异常: {e}")
            return None

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
                
                # 合并 evidence 和 signal_source_detail（方案二完整版用）
                full_evidence = list(sig.get('evidence', []))
                sig_detail = sig.get('signal_source_detail', {})
                if sig_detail:
                    for k, v in sig_detail.items():
                        if v and (isinstance(v, str) or (isinstance(v, list) and v)):
                            full_evidence.append(f"[{k}] {v if isinstance(v, str) else ', '.join(v)}")

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
                    evidence=full_evidence,
                    risk_notes=sig.get('risk_notes', []),
                    status_recognition=sig.get('status_recognition'),
                )

                # 同步记录到 SignalRecord（轨A·后台自动）
                try:
                    entry_zone_list = sig.get("entry_zone", [None, None])
                    target_zone_list = sig.get("target_zone", [None, None])
                    BacktestEvidenceService().record_signal(
                        ts_code=ts_code,
                        strategy_name=sig.get("strategy_name", "筹码策略"),
                        signal_type=signal_val,
                        confidence=sig.get("confidence", 0.5),
                        entry_price=entry_zone_list[0],
                        risk_line=sig.get("risk_line"),
                        target_price=target_zone_list[-1] if target_zone_list else None,
                        entry_zone_low=entry_zone_list[0],
                        entry_zone_high=entry_zone_list[1],
                        signal_snapshot={
                            "direction": sig.get("signal_label"),
                            "evidence": full_evidence,
                            "risk_notes": sig.get("risk_notes", []),
                        },
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"{ts_code}: 同步到StrategyOutput失败: {e}")
