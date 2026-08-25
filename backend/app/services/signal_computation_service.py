"""策略信号计算服务 — 调度层（369号方案重构）

369号方案 Step10：从3285行的内联计算中心重构为调度层，
调用8个维度引擎（dim1-dim8）替代内联计算。

保留：compute_for_stock() 接口签名不变，输出格式不变。
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional
import pandas as pd

from app.data import DataManager
from app.services.benchmark_service import BenchmarkService

logger = logging.getLogger(__name__)


class SignalComputationService:
    """策略信号计算服务 — 调度层"""

    STRATEGY_WINDOWS = {
        'chanlun': 130, 'volume_price': 130, 'chip': 70,
        'factor': 30, 'bociasi': 30, 'long_term': 260,
    }

    def __init__(self):
        self._data_manager = None
        self._benchmark_service = None
        self.last_data_availability = {}

    @property
    def data_manager(self):
        if self._data_manager is None:
            self._data_manager = DataManager()
        return self._data_manager

    @property
    def benchmark_service(self):
        if self._benchmark_service is None:
            self._benchmark_service = BenchmarkService()
        return self._benchmark_service

    def compute_for_stock(self, ts_code: str, limit: int = 5, period: str = 'long') -> List[Dict]:
        """对单只股票计算多维策略信号（调度层入口）

        369号方案：调用维度引擎替代内联计算。
        返回信号列表，格式与旧接口兼容。
        """
        df = self.data_manager.get_cached_daily_data(ts_code, adj='hfq')
        if df.empty or len(df) < 60:
            mf_available = False
            try:
                mf_check = self.data_manager.get_cached_moneyflow(ts_code)
                mf_available = mf_check is not None and not mf_check.empty
            except:
                self.data_manager.request_data('full_moneyflow', ts_code)
            self.last_data_availability = {
                'ts_code': ts_code, 'kline': len(df) >= 60,
                'daily_basic': False, 'moneyflow': mf_available,
                'index': False, 'market_state': False,
            }
            return []

        if 'vol' not in df.columns and 'amount' in df.columns:
            df['vol'] = df['amount']

        market_context, da = self._load_market_context(ts_code, df)
        self.last_data_availability = {**da, 'ts_code': ts_code, 'kline': True}

        tags = dict(market_context)
        tags['ts_code'] = ts_code
        dims = {}

        signals = self.compute_via_engines(ts_code, tags, dims)
        return self._apply_post_processing(signals, market_context, ts_code, df, limit)

    def compute_via_engines(self, ts_code: str, tags: dict, dims: dict,
                            lifecycle: dict = None) -> List[Dict]:
        """通过维度引擎计算策略信号

        368号P2修复：每个信号新增 continuous_value（连续强度值）
        事项3修复：完整引擎结果附加到 _dim_results 供JUD消费
        """
        signals = []
        dim_results = {}  # 事项3：存储引擎完整结果

        # dim1: 信号确认
        try:
            from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
            r1 = Dim1SignalEngine().evaluate(dims, tags, lifecycle=lifecycle or {})
            jg1 = r1.get('judgment', {})
            dim_results['signal'] = r1  # 事项3
            cv1 = jg1.get('continuous_value', 0.5)
            if jg1.get('attribute', {}).get('code') not in ('neutral', 'consolidating'):
                signals.append({
                    'strategy_name': '信号确认',
                    'signal': 'bullish' if jg1.get('overall_direction', 0) > 0 else ('bearish' if jg1.get('overall_direction', 0) < 0 else 'neutral'),
                    'confidence': cv1,  # 事项1：改用连续值
                    'continuous_value': cv1,  # 事项1：显式输出
                    'direction': jg1.get('overall_direction', 0),
                    'evidence': [r1.get('status_description', {}).get('attribute', '')],
                    'source': 'Dim1SignalEngine',
                })
        except Exception as e:
            logger.debug(f"dim1引擎调用失败: {e}")

        # dim2: 缠论结构
        try:
            from app.opportunity_atlas.dimensions.dim2_structure_engine import Dim2StructureEngine
            r2 = Dim2StructureEngine().evaluate(dims, tags, lifecycle=lifecycle or {})
            sd2, jg2 = r2.get('status_description', {}), r2.get('judgment', {})
            dim_results['structure'] = r2  # 事项3
            cv2 = jg2.get('continuous_value', 0.5)
            if sd2.get('chanlun_direction') and sd2['chanlun_direction'] != '未知':
                signals.append({
                    'strategy_name': '缠论走势分析',
                    'signal': 'bullish' if jg2.get('overall_direction', 0) > 0 else ('bearish' if jg2.get('overall_direction', 0) < 0 else 'neutral'),
                    'confidence': cv2,  # 事项1
                    'continuous_value': cv2,  # 事项1
                    'direction': jg2.get('overall_direction', 0),
                    'evidence': [sd2.get('vs_zhongshu', ''), sd2.get('vs_ma', '')],
                    'source': 'Dim2StructureEngine',
                })
        except Exception as e:
            logger.debug(f"dim2引擎调用失败: {e}")

        # dim3: 量价健康
        try:
            from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine
            r3 = Dim3VPEngine().evaluate(dims, tags, lifecycle=lifecycle or {})
            sd3, jg3 = r3.get('status_description', {}), r3.get('judgment', {})
            dim_results['volume_price'] = r3  # 事项3
            cv3 = jg3.get('continuous_value', 0.5)
            if sd3.get('vp_state'):
                signals.append({
                    'strategy_name': '量价分析策略',
                    'signal': 'bullish' if jg3.get('overall_direction', 0) > 0 else ('bearish' if jg3.get('overall_direction', 0) < 0 else 'neutral'),
                    'confidence': cv3,  # 事项1
                    'continuous_value': cv3,  # 事项1
                    'direction': jg3.get('overall_direction', 0),
                    'evidence': [sd3.get('vp_state', ''), sd3.get('divergence', '')],
                    'source': 'Dim3VPEngine',
                })
        except Exception as e:
            logger.debug(f"dim3引擎调用失败: {e}")

        # dim4: 资金筹码
        try:
            from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import Dim4ChipFundEngine
            r4 = Dim4ChipFundEngine().evaluate(dims, tags, lifecycle=lifecycle or {})
            sd4, jg4 = r4.get('status_description', {}), r4.get('judgment', {})
            dim_results['chip_fund'] = r4  # 事项3
            cv4 = jg4.get('continuous_value', 0.5)
            if sd4.get('phase'):
                signals.append({
                    'strategy_name': '筹码主力分析',
                    'signal': 'bullish' if jg4.get('direction') == 'inflow' else ('bearish' if jg4.get('direction') == 'outflow' else 'neutral'),
                    'confidence': cv4,  # 事项1
                    'continuous_value': cv4,  # 事项1
                    'direction': jg4.get('overall_direction', 0),
                    'evidence': [sd4.get('phase', ''), sd4.get('fund_flow', '')],
                    'source': 'Dim4ChipFundEngine',
                })
        except Exception as e:
            logger.debug(f"dim4引擎调用失败: {e}")

        # dim5: 情绪环境
        try:
            from app.opportunity_atlas.dimensions.dim5_emotion_engine import Dim5EmotionEngine
            r5 = Dim5EmotionEngine().evaluate(dims, tags, lifecycle=lifecycle or {})
            sd5, jg5 = r5.get('status_description', {}), r5.get('judgment', {})
            dim_results['emotion'] = r5  # 事项3
            cv5 = jg5.get('continuous_value', 0.5)
            if sd5.get('market'):
                signals.append({
                    'strategy_name': 'BOCIASI快线',
                    'signal': 'bullish' if jg5.get('overall_direction', 0) > 0 else ('bearish' if jg5.get('overall_direction', 0) < 0 else 'neutral'),
                    'confidence': cv5,  # 事项1
                    'continuous_value': cv5,  # 事项1
                    'direction': jg5.get('overall_direction', 0),
                    'evidence': [sd5.get('market', ''), sd5.get('quadrant', '')],
                    'source': 'Dim5EmotionEngine',
                })
        except Exception as e:
            logger.debug(f"dim5引擎调用失败: {e}")

        # dim6: 风险边界
        try:
            from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine
            r6 = Dim6RiskEngine().evaluate(dims, tags, lifecycle=lifecycle or {})
            jg6 = r6.get('judgment', {})
            dim_results['risk'] = r6  # 事项3
            cv6 = jg6.get('continuous_value', 0.5)
            if jg6.get('level') in ('高', '极高'):
                signals.append({
                    'strategy_name': '风险警示',
                    'signal': 'bearish',
                    'confidence': 1.0 - cv6,  # 事项1：风险越高confidence越高
                    'continuous_value': cv6,  # 事项1
                    'direction': -1,
                    'evidence': [r6.get('status_description', {}).get('risk_level', '')],
                    'source': 'Dim6RiskEngine',
                })
        except Exception as e:
            logger.debug(f"dim6引擎调用失败: {e}")

        # 事项3：将完整引擎结果附加到signals列表（通过特殊key传递）
        if dim_results:
            signals.append({'_dim_results': dim_results, '_source': 'engine_results'})

        return signals

    def _load_market_context(self, ts_code: str, df: pd.DataFrame):
        """加载扩展数据（daily_basic/moneyflow/index/market_state）+ 构建市场上下文

        从 compute_for_stock 提取的数据加载模块（P3重构）。
        返回 (market_context, da) 二元组供策略计算使用。
        """
        market_context: Dict = {}
        da: Dict = {'daily_basic': False, 'moneyflow': False, 'index': False, 'market_state': False}

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
                da['daily_basic'] = True
                logger.debug(f"{ts_code} 已加载 daily_basic: 换手率={market_context.get('turnover_rate')}, "
                             f"市值={market_context.get('circ_mv')}")
        except Exception as e:
            logger.debug(f"{ts_code} daily_basic 加载跳过: {e}")
            self.data_manager.request_data('full_basic', ts_code)

        # 1.5) 价格位置计算：乖离率、历史分位、BOLL带宽、均线粘合
        try:
            closes = df['close'].values
            n = len(closes)
            if n >= 60:
                latest_c = float(closes[-1])
                ma5 = float(np.mean(closes[-5:])) if n >= 5 else latest_c
                ma20 = float(np.mean(closes[-20:])) if n >= 20 else latest_c
                ma60 = float(np.mean(closes[-60:])) if n >= 60 else latest_c
                market_context['bias_ma5'] = round((latest_c - ma5) / ma5 * 100, 2) if ma5 else None
                market_context['bias_ma20'] = round((latest_c - ma20) / ma20 * 100, 2) if ma20 else None
                market_context['bias_ma60'] = round((latest_c - ma60) / ma60 * 100, 2) if ma60 else None
                lookback = min(n, 250)
                recent = closes[-lookback:]
                rank = sum(1 for v in recent if v <= latest_c)
                market_context['percentile_250d'] = round(rank / lookback * 100, 1) if lookback else None
                if n >= 20:
                    ma20_arr = float(np.mean(closes[-20:]))
                    std20 = float(np.std(closes[-20:]))
                    if ma20_arr:
                        boll_upper = ma20_arr + 2 * std20
                        boll_lower = ma20_arr - 2 * std20
                        market_context['boll_bandwidth'] = round((boll_upper - boll_lower) / ma20_arr * 100, 2)
                if n >= 60:
                    ma10 = float(np.mean(closes[-10:]))
                    mas = [ma5, ma10, ma20, ma60]
                    ma_min = min(mas)
                    ma_max = max(mas)
                    market_context['ma_convergence'] = round((ma_max - ma_min) / ma_min * 100, 2) if ma_min else None
        except Exception as e:
            logger.debug(f"{ts_code} 价格位置计算跳过: {e}")

        # 2) 资金流向
        try:
            df_mf = self.data_manager.get_cached_moneyflow(ts_code)
            if df_mf is not None and not df_mf.empty:
                recent_mf = df_mf.tail(5)
                market_context['net_lg_amount'] = float(recent_mf['net_lg_amount'].sum())
                market_context['net_mf_amount'] = float(recent_mf['net_mf_amount'].sum()) if 'net_mf_amount' in recent_mf.columns else 0
                market_context['buy_lg_amount'] = float(recent_mf['buy_lg_amount'].sum())
                market_context['sell_lg_amount'] = float(recent_mf['sell_lg_amount'].sum())
                market_context['net_elg_amount'] = float(recent_mf['net_elg_amount'].sum())
                market_context['net_sm_amount'] = float(recent_mf['net_sm_amount'].sum())
                da['moneyflow'] = True
                logger.debug(f"{ts_code} 已加载资金流向: 近5日大单净额={market_context.get('net_lg_amount')}")
        except Exception as e:
            logger.debug(f"{ts_code} 资金流向加载跳过: {e}")
            self.data_manager.request_data('full_moneyflow', ts_code)

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
                try:
                    if df is not None and not df.empty and len(df) >= 20:
                        stock_close = df['close'].astype(float)
                        stock_20d_ret = (stock_close.iloc[-1] / stock_close.iloc[-20] - 1) * 100
                        market_context['stock_vs_index_20d'] = round(float(stock_20d_ret - idx_20d_ret * 100), 2)
                except Exception:
                    pass
                da['index'] = True
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
            da['market_state'] = True
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
        if market_context.get('index_condition'):
            market_context.setdefault('market_env', {})['condition'] = market_context['index_condition']
        if market_context.get('idx_5d_ret') is not None:
            market_context.setdefault('market_env', {})['index_return_5d'] = market_context['idx_5d_ret']

        # ── Phase 1: 新增市场上下文计算字段 ──
        # P1-4: 散户反向指标 — 大小单对比
        try:
            net_lg = market_context.get('net_lg_amount', 0) or 0
            net_sm = market_context.get('net_sm_amount', 0) or 0
            net_elg = market_context.get('net_elg_amount', 0) or 0
            main_net = net_lg + net_elg
            if da.get('moneyflow') and abs(main_net) > 0 and abs(net_sm) > 0:
                if net_sm < 0 and main_net > 0:
                    market_context['retail_vs_institutional'] = 'healthy'
                elif net_sm > 0 and main_net < 0:
                    market_context['retail_vs_institutional'] = 'danger'
                elif net_sm > 0 and main_net > 0:
                    market_context['retail_vs_institutional'] = 'overheat'
                else:
                    market_context['retail_vs_institutional'] = 'panic'
            else:
                market_context['retail_vs_institutional'] = None
        except Exception:
            market_context['retail_vs_institutional'] = None

        # P1-5: 情绪拥挤度因子 — 融资余额增长率 vs 股价涨幅
        try:
            from app.data import DataManager
            _dm = DataManager()
            margin_df = _dm.get_cached_margin(ts_code)
            if margin_df is not None and not margin_df.empty and len(margin_df) >= 5:
                recent_margin = margin_df.tail(5)
                if 'mrz' in recent_margin.columns:
                    margin_vals = recent_margin['mrz'].dropna().values
                    if len(margin_vals) >= 5:
                        margin_growth = (margin_vals[-1] / margin_vals[0] - 1) * 100
                    elif len(margin_vals) >= 2:
                        margin_growth = (margin_vals[-1] / margin_vals[0] - 1) * 100
                    else:
                        margin_growth = 0.0
                    if df is not None and not df.empty and len(df) >= 5:
                        stock_5d = (df['close'].iloc[-1] / df['close'].iloc[-5] - 1) * 100
                    else:
                        stock_5d = 0.0
                    crowding = round(float(margin_growth - stock_5d), 2)
                    market_context['sentiment_crowding'] = crowding
                    if crowding > 15:
                        market_context['sentiment_crowding_label'] = 'overheat'
                    elif crowding < -5:
                        market_context['sentiment_crowding_label'] = 'cooling'
                    else:
                        market_context['sentiment_crowding_label'] = 'normal'
        except Exception:
            self.data_manager.request_data('margin', ts_code)
            market_context['sentiment_crowding'] = None
            market_context['sentiment_crowding_label'] = None

        # P1-6: 乖离率 + 历史分位
        try:
            if df is not None and not df.empty:
                closes = df['close'].astype(float).values
                latest_close = closes[-1]
                if len(closes) >= 5:
                    market_context['bias_ma5'] = round(float((latest_close / np.mean(closes[-5:]) - 1) * 100), 2)
                if len(closes) >= 20:
                    market_context['bias_ma20'] = round(float((latest_close / np.mean(closes[-20:]) - 1) * 100), 2)
                if len(closes) >= 60:
                    market_context['bias_ma60'] = round(float((latest_close / np.mean(closes[-60:]) - 1) * 100), 2)
                lookback = min(len(closes), 250)
                if lookback >= 20:
                    low_250 = np.min(closes[-lookback:])
                    high_250 = np.max(closes[-lookback:])
                    if high_250 > low_250:
                        market_context['percentile_250d'] = round(float((latest_close - low_250) / (high_250 - low_250) * 100), 1)
        except Exception:
            pass

        # P1-7: BOLL带宽 + 均线粘合
        try:
            if df is not None and not df.empty and len(df) >= 26:
                closes = df['close'].astype(float).values
                ma_20 = np.mean(closes[-20:])
                std_20 = np.std(closes[-20:])
                upper = ma_20 + 2 * std_20
                lower = ma_20 - 2 * std_20
                bb_width = (upper - lower) / ma_20 if ma_20 > 0 else 0
                market_context['boll_bandwidth'] = 'contracted' if bb_width < 0.08 else ('expanding' if bb_width > 0.15 else 'normal')
                if len(closes) >= 60:
                    ma5 = np.mean(closes[-5:])
                    ma20 = np.mean(closes[-20:])
                    ma60 = np.mean(closes[-60:])
                    ma_spread = max(ma5, ma20, ma60) - min(ma5, ma20, ma60)
                    ma_avg = (ma5 + ma20 + ma60) / 3
                    if ma_avg > 0 and ma_spread / ma_avg < 0.03:
                        market_context['ma_convergence'] = True
                    else:
                        market_context['ma_convergence'] = False
        except Exception:
            pass

        return market_context, da


    def _apply_post_processing(self, signals: List[Dict], market_context: Dict,
                                 ts_code: str, df: pd.DataFrame, limit: int) -> List[Dict]:
        """信号后处理：新闻修正、VAP支撑阻力、中枢强度、持久化、数据可用性

        从 compute_for_stock 提取的后处理模块（P3重构）。
        包含策略信号计算完成后的所有修正、补充和持久化逻辑。
        """
        # ── 新闻情绪修正因子（C2） ──
        try:
            from app.data.news_provider import NewsProvider as NP
            np_provider = NP()
            news_items = np_provider.get_news(ts_code, days_back=3, max_count=5)
            if news_items:
                sentiments = [n.sentiment for n in news_items if n.sentiment is not None]
                if sentiments:
                    avg_sentiment = sum(sentiments) / len(sentiments)
                    clipped = max(-0.15, min(0.15, avg_sentiment))
                    modifier = 1.0 + (clipped * 0.33)
                    for sig in signals:
                        sig['confidence'] = min(1.0, sig.get('confidence', 0.5) * modifier)
                        label = '正面' if clipped > 0 else ('负面' if clipped < 0 else '中性')
                        sig['evidence'] = sig.get('evidence', []) + [
                            f"新闻情绪: {label} (修正{modifier:.2f}x, {len(sentiments)}条)"
                        ]
                    logger.debug(f"{ts_code} 新闻情绪修正: avg={avg_sentiment:.3f} -> modifier={modifier:.3f}")
        except Exception as e:
            logger.debug(f"{ts_code} 新闻情绪修正跳过: {e}")

        # ═══ Phase 2 P2-9: VAP 支撑/阻力 ═══
        try:
            if df is not None and not df.empty and len(df) >= 30:
                closes = df['close'].astype(float).values
                highs = df['high'].astype(float).values if 'high' in df.columns else closes
                lows = df['low'].astype(float).values if 'low' in df.columns else closes
                volumes = df['vol'].astype(float).values if 'vol' in df.columns else df['amount'].astype(float).values
                latest_close = float(closes[-1])
                vap = _calc_vap_support_resistance(closes, highs, lows, volumes, latest_close)
                market_context['vap_support'] = vap.get('vap_support')
                market_context['vap_resistance'] = vap.get('vap_resistance')
        except Exception:
            pass

        # ═══ Phase 2 P2-6: 中枢强度 — 注入 chanlun signal ═══
        try:
            chip_signal = next((s for s in signals if s.get('strategy_name', '').startswith('筹码')), None)
            chip_sr = chip_signal.get('status_recognition', {}) if chip_signal else None
            for sig in signals:
                if sig.get('strategy_name') == '缠论走势分析':
                    cl_sr = sig.get('status_recognition', {})
                    cl_detail = sig.get('chanlun_analysis_detail', {})
                    zs_list_raw = cl_detail.get('zhongshu_list', [])
                    if zs_list_raw:
                        ZS = type('ZS', (), {})
                        zhongshu_objs = []
                        for z in zs_list_raw:
                            obj = ZS()
                            obj.low = z.get('low', 0)
                            obj.high = z.get('high', 0)
                            obj.center = z.get('center', 0)
                            zhongshu_objs.append(obj)
                        strength = _calc_zhongshu_strength(df, zhongshu_objs, chip_sr)
                        if strength:
                            cl_sr['zhongshu_strength'] = strength
                    break
        except Exception:
            pass

        # 持久化到数据库
        try:
            self._persist_signals(ts_code, signals)
        except Exception as e:
            logger.debug(f"{ts_code}: 信号持久化到数据库跳过 (非关键): {e}")

        # 记录数据可用性
        da = next((s for s in signals if isinstance(s, dict) and s.get('data_availability')), None)
        kline_ok = df is not None and len(df) >= 60
        self.last_data_availability = {
            'ts_code': ts_code,
            'kline': kline_ok,
            'daily_basic': bool(market_context.get('turnover_rate')),
            'moneyflow': bool(market_context.get('net_lg_amount')),
            'index': bool(market_context.get('index_condition')),
            'market_state': bool(market_context.get('market_state')),
        }

        return signals[:limit]


