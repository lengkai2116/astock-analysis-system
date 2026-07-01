"""
横截面回测聚合服务（218号 Phase 1）
多只股票并行执行统一策略回测 → 中位数/IQR聚合 → 多维度验证
"""
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import logging
import uuid

from app.engine.backtest_v2 import (
    AShareBacktestEngine, BacktestConfig,
    create_default_engine
)
from app.data.tushare_provider import TushareProvider
from app.data.memory_cache import TieredMemoryCache

logger = logging.getLogger(__name__)

MAX_WORKERS = 8  # 并行回测线程数


# ── 任务状态数据结构 ──────────────────────────────────────────────

@dataclass
class TaskProgress:
    """任务进度状态"""
    task_id: str
    ts_codes: List[str]
    start_date: str
    end_date: str
    status: str = 'pending'          # pending → data_fetch → signal_gen → backtest → metrics → aggregation → done
    progress_pct: float = 0.0
    current_stock: str = ''
    stocks_completed: int = 0
    stocks_total: int = 0
    message: str = ''
    error: Optional[str] = None
    created_at: str = ''
    completed_at: Optional[str] = None


# ── 在内存中存储任务状态（跨请求共享） ────────────────────────────

_task_store: Dict[str, TaskProgress] = {}
_result_store: Dict[str, Dict] = {}


def _init_task(ts_codes: List[str], start_date: str, end_date: str) -> str:
    """创建任务并返回 task_id"""
    task_id = f"BT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    _task_store[task_id] = TaskProgress(
        task_id=task_id,
        ts_codes=list(dict.fromkeys(ts_codes)),  # 去重保序
        start_date=start_date,
        end_date=end_date,
        status='pending',
        created_at=datetime.now().isoformat(),
        stocks_total=len(ts_codes),
    )
    return task_id


def get_progress(task_id: str) -> Optional[TaskProgress]:
    return _task_store.get(task_id)


def get_result(task_id: str) -> Optional[Dict]:
    return _result_store.get(task_id)


# ── 主服务 ────────────────────────────────────────────────────────

class CrossSectionalBacktestService:
    """横截面回测聚合服务"""

    def __init__(self):
        self._tp: Optional[TushareProvider] = None
        self._cache = TieredMemoryCache()

    def _get_provider(self) -> Optional[TushareProvider]:
        if self._tp is None:
            try:
                self._tp = TushareProvider()
                if not self._tp.pro:
                    self._tp = None
            except Exception:
                self._tp = None
        return self._tp

    def run_strategy_backtest(
        self,
        ts_codes: List[str],
        start_date: str,
        end_date: str,
        config: Optional[Dict] = None,
        task_id: Optional[str] = None,
    ) -> Dict:
        """
        对多只股票运行统一策略回测（同步执行，适用于中等规模股票池）

        Args:
            ts_codes: 股票代码列表
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            config: 回测配置参数
            task_id: 任务ID（用于进度追踪）

        Returns:
            包含9大区域的完整回测结果
        """
        if not task_id:
            task_id = _init_task(ts_codes, start_date, end_date)

        ts_codes = list(dict.fromkeys([c.strip() for c in ts_codes if c.strip()]))
        tp = self._get_provider()
        if not tp:
            return {'success': False, 'error': 'Tushare数据源不可用', 'task_id': task_id}

        backtest_config = BacktestConfig(
            initial_capital=config.get('initial_capital', 100000) if config else 100000,
            commission_rate=config.get('commission_rate', 0.0003) if config else 0.0003,
            stamp_duty_rate=config.get('stamp_duty_rate', 0.001) if config else 0.001,
            slippage_rate=config.get('slippage_rate', 0.0001) if config else 0.0001,
            min_commission=config.get('min_commission', 5.0) if config else 5.0,
            max_position=config.get('max_position', 10) if config else 10,
            price_limit_check=config.get('price_limit_check', True) if config else True,
        )
        # 横截面特有参数
        signal_method = config.get('signal_method', 'sma_cross') if config else 'sma_cross'
        allocation_per_stock = config.get('allocation_per_stock', 0.2) if config else 0.2

        # ── 阶段1：数据获取 ──
        _update_progress(task_id, 'data_fetch', 0.05, message='正在获取行情数据...')
        stock_data_map, failed_codes = self._fetch_all_prices(tp, ts_codes, start_date, end_date)
        ts_codes = [c for c in ts_codes if c in stock_data_map]
        _update_progress(task_id, 'data_fetch', 0.15, stocks_total=len(ts_codes))

        # ── 阶段2：信号生成 ──
        _update_progress(task_id, 'signal_gen', 0.15, message='正在生成交易信号...')
        signal_map = {}
        for ts_code, df in stock_data_map.items():
            signals = self._generate_technical_signals(df, method=signal_method)
            if not signals.empty:
                signal_map[ts_code] = signals

        _update_progress(task_id, 'signal_gen', 0.25)

        # ── 阶段3：并行回测执行 ──
        _update_progress(task_id, 'backtest', 0.25, message='正在并行执行回测...')
        per_stock_results: Dict[str, Optional[Dict]] = {}

        all_dates = sorted(set(d for df in stock_data_map.values() for d in df.index.unique()))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {}
            for i, ts_code in enumerate(ts_codes):
                future = executor.submit(
                    self._run_single_stock_backtest,
                    ts_code, stock_data_map, signal_map, backtest_config,
                    all_dates, start_date, end_date
                )
                future_map[future] = ts_code

            completed = 0
            for future in as_completed(future_map):
                ts_code = future_map[future]
                try:
                    per_stock_results[ts_code] = future.result()
                except Exception as e:
                    logger.error(f"回测失败({ts_code}): {e}")
                    per_stock_results[ts_code] = None
                completed += 1
                pct = 0.25 + 0.40 * (completed / len(ts_codes))
                _update_progress(task_id, 'backtest', pct,
                                 current_stock=ts_code, stocks_completed=completed)

        # ── 阶段4：指标计算 ──
        _update_progress(task_id, 'metrics', 0.65, message='正在计算绩效指标...')
        valid_results = {k: v for k, v in per_stock_results.items() if v is not None}
        for ts_code, r in valid_results.items():
            self._compute_stock_metrics(r)

        _update_progress(task_id, 'metrics', 0.75)

        # ── 阶段5：横截面聚合 ──
        _update_progress(task_id, 'aggregation', 0.75, message='正在执行横截面聚合...')
        aggregation = self._cross_sectional_aggregation(valid_results)

        # ── 阶段6：检查点计算 ──
        checkpoints = self._compute_checkpoints(valid_results, stock_data_map, start_date, end_date)

        # ── 合并结果（9大区域） ──
        final_result = self._build_result(
            task_id, ts_codes, start_date, end_date,
            valid_results, failed_codes, aggregation, checkpoints, backtest_config
        )
        _update_progress(task_id, 'done', 1.0, message='回测完成')
        _result_store[task_id] = final_result
        return final_result

    # ── 私有方法 ──────────────────────────────────────────────

    def _fetch_all_prices(
        self, tp: TushareProvider, ts_codes: List[str],
        start_date: str, end_date: str
    ) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
        """并行获取所有股票的历史日线数据"""
        stock_data_map = {}
        failed = []

        # 需要更多历史数据用于信号计算（信号需要前N日数据）
        signal_warmup = 60  # 交易日
        try:
            warmup_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=signal_warmup * 1.5)).strftime('%Y%m%d')
        except ValueError:
            warmup_start = start_date

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {
                executor.submit(tp.get_daily_data, c, warmup_start, end_date): c
                for c in ts_codes
            }
            for future in as_completed(future_map):
                ts_code = future_map[future]
                try:
                    raw = future.result()
                    if not raw:
                        failed.append(ts_code)
                        continue
                    df = pd.DataFrame(raw)
                    if df.empty:
                        failed.append(ts_code)
                        continue
                    # 确保列名统一
                    date_col = 'trade_date' if 'trade_date' in df.columns else 'date'
                    if date_col not in df.columns:
                        failed.append(ts_code)
                        continue
                    df = df.set_index(date_col).sort_index()
                    # 舍去 warmup 部分，只保留回测区间
                    df = df.loc[df.index >= start_date] if start_date in df.index or any(d >= start_date for d in df.index) else df
                    # 补齐必须字段
                    for col in ['open', 'high', 'low', 'close', 'vol', 'amount']:
                        if col not in df.columns and col.replace('vol', 'volume') in df.columns:
                            df[col] = df[col.replace('vol', 'volume')]
                    if 'pct_chg' not in df.columns and 'close' in df.columns:
                        df['pct_chg'] = df['close'].pct_change() * 100
                    stock_data_map[ts_code] = df
                except Exception as e:
                    logger.warning(f"获取{ts_code}数据失败: {e}")
                    failed.append(ts_code)
        return stock_data_map, failed

    def _generate_technical_signals(
        self, df: pd.DataFrame, method: str = 'sma_cross'
    ) -> pd.DataFrame:
        """
        生成技术交易信号

        Args:
            df: 日线DataFrame (index=date, columns包含 close)
            method: 信号生成方法
                - sma_cross: SMA5/SMA20 金叉死叉
                - rsi: RSI超买超卖
                - combined: 组合信号

        Returns:
            DataFrame: index=date, columns=[signal, strength]
                signal: 1=买入, -1=卖出, 0=持仓
                strength: 信号强度 (0~1)
        """
        if df.empty or 'close' not in df.columns:
            return pd.DataFrame()

        close = df['close'].astype(float)

        if method == 'rsi':
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + gain / (loss + 1e-10)))
            signal = pd.Series(0, index=df.index)
            signal[rsi < 30] = 1
            signal[rsi > 70] = -1
            strength = pd.Series(0.5, index=df.index)
            strength[rsi < 25] = 0.8
            strength[rsi > 75] = 0.8
        elif method == 'combined':
            # SMA交叉 + RSI + 成交量确认
            sma5 = close.rolling(5).mean()
            sma20 = close.rolling(20).mean()
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + gain / (loss + 1e-10)))
            volume = df.get('vol', df.get('volume', pd.Series(0, index=df.index))).astype(float)
            vol_ma5 = volume.rolling(5).mean()

            signal = pd.Series(0, index=df.index)
            strength = pd.Series(0.0, index=df.index)

            # 金叉 + RSI不超买 + 量确认 → 买入
            buy_cond = (sma5 > sma20) & (sma5.shift(1) <= sma20.shift(1)) & (rsi < 70)
            buy_cond = buy_cond & ((volume > vol_ma5 * 1.2) | vol_ma5.isna())
            signal[buy_cond] = 1
            strength[buy_cond] = 0.7

            # 死叉 + RSI不超卖 + 量确认 → 卖出
            sell_cond = (sma5 < sma20) & (sma5.shift(1) >= sma20.shift(1)) & (rsi > 30)
            sell_cond = sell_cond & ((volume > vol_ma5 * 1.2) | vol_ma5.isna())
            signal[sell_cond] = -1
            strength[sell_cond] = 0.7
        else:
            # sma_cross (默认)
            sma5 = close.rolling(5).mean()
            sma20 = close.rolling(20).mean()
            signal = pd.Series(0, index=df.index)
            signal[(sma5 > sma20) & (sma5.shift(1) <= sma20.shift(1))] = 1
            signal[(sma5 < sma20) & (sma5.shift(1) >= sma20.shift(1))] = -1
            strength = pd.Series(0.6, index=df.index)

        # 填充NaN（前20天无有效信号）
        result = pd.DataFrame({'signal': signal, 'strength': strength}, index=df.index)
        return result

    def _run_single_stock_backtest(
        self, ts_code: str, stock_data_map: Dict[str, pd.DataFrame],
        signal_map: Dict[str, pd.DataFrame], config: BacktestConfig,
        all_dates: List[str], start_date: str, end_date: str
    ) -> Optional[Dict]:
        """对单只股票执行回测并返回结果"""
        df = stock_data_map.get(ts_code)
        if df is None or df.empty:
            return None

        signals = signal_map.get(ts_code)
        if signals is None or signals.empty:
            return None

        # 构建引擎输入格式
        engine = AShareBacktestEngine(config)

        # 准备价格DataFrame（engine要求index=ts_code或单只）
        price_df = df.copy()
        price_df['ts_code'] = ts_code
        price_df = price_df.reset_index()

        # 重命名列以匹配引擎预期
        rename_map = {'vol': 'volume', 'trade_date': 'date'}
        for old_k, new_k in rename_map.items():
            if old_k in price_df.columns and new_k not in price_df.columns:
                price_df[new_k] = price_df[old_k]

        if 'volume' not in price_df.columns:
            price_df['volume'] = 0

        # 准备信号DataFrame
        signals_df = signals.reset_index()
        signals_df['ts_code'] = ts_code
        signals_df = signals_df.rename(columns={'index': 'date'})  # will use 'date' as column name at reset
        signals_df = signals_df.rename(columns={signals_df.columns[0]: 'date'})

        # engine需要 signals 列名为: ts_code, date, signal
        signal_cols = {'date': 'date', 'signal': 'signal', 'strength': 'strength'}
        signals_for_engine = signals_df[['date', 'signal', 'strength']].copy()
        signals_for_engine['ts_code'] = ts_code

        # 运行回测
        try:
            result = engine.run_backtest(
                price_data=price_df,
                signals=signals_for_engine,
                benchmark_data=None,
                start_date=start_date,
                end_date=end_date
            )
            return {'ts_code': ts_code, 'result': result}
        except Exception as e:
            logger.error(f"{ts_code} 回测引擎执行失败: {e}")
            return None

    def _compute_stock_metrics(self, stock_result: Dict):
        """补充计算单只股票的扩展指标"""
        result = stock_result.get('result')
        if not result or not hasattr(result, 'daily_equity'):
            stock_result['extended_metrics'] = {}
            return

        metrics = result.metrics
        total_return = metrics.get('total_return', 0)
        max_dd = metrics.get('max_drawdown', 0)
        sharpe = metrics.get('sharpe_ratio', 0)

        # 收益风险比
        if abs(max_dd) > 1e-10:
            calmar = total_return / abs(max_dd)
        else:
            calmar = total_return if abs(total_return) > 0 else 0

        # 日胜率检查点
        daily_eq = result.daily_equity
        t5_return = _checkpoint_return(daily_eq, 5)
        t10_return = _checkpoint_return(daily_eq, 10)
        t20_return = _checkpoint_return(daily_eq, 20)

        stock_result['extended_metrics'] = {
            'calmar_ratio': round(calmar, 4),
            't5_return': round(t5_return, 4),
            't10_return': round(t10_return, 4),
            't20_return': round(t20_return, 4),
            'avg_holding_days': _avg_holding_days(result.trades),
            'total_trades': metrics.get('total_trades', 0),
        }

    def _cross_sectional_aggregation(self, valid_results: Dict[str, Dict]) -> Dict:
        """横截面聚合：中位数/IQR/通过率"""
        if not valid_results:
            return {
                'stock_count': 0, 'median': {}, 'mean': {},
                'q25': {}, 'q75': {}, 'pass_rate': {}, 'positive_ratio': {},
            }

        metrics_list = []
        for ts_code, sr in valid_results.items():
            r = sr.get('result')
            if not r:
                continue
            m = {**r.metrics, **sr.get('extended_metrics', {})}
            m['ts_code'] = ts_code
            metrics_list.append(m)

        if not metrics_list:
            return {
                'stock_count': 0, 'median': {}, 'mean': {},
                'q25': {}, 'q75': {}, 'pass_rate': {}, 'positive_ratio': {},
            }

        df = pd.DataFrame(metrics_list)
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        def _agg(col):
            vals = df[col].dropna()
            if vals.empty:
                return {'median': None, 'mean': None, 'q25': None, 'q75': None, 'std': None}
            return {
                'median': round(float(vals.median()), 4),
                'mean': round(float(vals.mean()), 4),
                'q25': round(float(vals.quantile(0.25)), 4),
                'q75': round(float(vals.quantile(0.75)), 4),
                'std': round(float(vals.std()), 4),
            }

        aggregation = {
            'stock_count': len(valid_results),
            'stock_ts_codes': list(valid_results.keys()),
        }

        for col in numeric_cols:
            aggregation[col] = _agg(col)

        # 通过率指标
        aggregation['pass_rate'] = {
            'sharpe_gt_1': _pass_rate(df, 'sharpe_ratio', lambda x: x > 1),
            'total_return_gt_0': _pass_rate(df, 'total_return', lambda x: x > 0),
            'max_drawdown_lt_20': _pass_rate(df, 'max_drawdown', lambda x: x < 0.2),
        }
        aggregation['positive_ratio'] = {
            't5_return': _pass_rate(df, 't5_return', lambda x: x > 0),
            't10_return': _pass_rate(df, 't10_return', lambda x: x > 0),
            't20_return': _pass_rate(df, 't20_return', lambda x: x > 0),
        }

        return aggregation

    def _compute_checkpoints(
        self, valid_results: Dict[str, Dict],
        stock_data_map: Dict[str, pd.DataFrame],
        start_date: str, end_date: str
    ) -> Dict:
        """计算回测区间内的检查点表现"""
        if not valid_results:
            return {}

        checkpoints = {'t5': {}, 't10': {}, 't20': {}}
        for ts_code, sr in valid_results.items():
            ext = sr.get('extended_metrics', {})
            checkpoints['t5'][ts_code] = ext.get('t5_return')
            checkpoints['t10'][ts_code] = ext.get('t10_return')
            checkpoints['t20'][ts_code] = ext.get('t20_return')

        # 聚合检查点
        for key, cp_data in checkpoints.items():
            vals = [v for v in cp_data.values() if v is not None]
            if vals:
                cp_data['_median'] = round(float(np.median(vals)), 4)
                cp_data['_mean'] = round(float(np.mean(vals)), 4)
                cp_data['_positive_ratio'] = round(sum(1 for v in vals if v > 0) / len(vals), 4)
                cp_data['_count'] = len(vals)

        return checkpoints

    def _build_result(
        self, task_id: str, ts_codes: List[str],
        start_date: str, end_date: str,
        valid_results: Dict[str, Optional[Dict]],
        failed_codes: List[str],
        aggregation: Dict,
        checkpoints: Dict,
        config: BacktestConfig,
    ) -> Dict:
        """构建完整的9大区域结果"""
        # 区域1: 概要
        successful = {k: v for k, v in valid_results.items() if v is not None}
        total_stocks = len(ts_codes) + len(failed_codes)

        summary = {
            'task_id': task_id,
            'created_at': datetime.now().isoformat(),
            'date_range': {'start': start_date, 'end': end_date},
            'total_stocks': total_stocks,
            'successful_stocks': len(successful),
            'failed_stocks': len(failed_codes),
            'failed_codes': failed_codes,
            'trading_days': 0,
        }

        # 区域2: 净值曲线（取中位数组合）
        equity_curve = _build_median_equity_curve(successful)

        # 区域3: 交易记录（全量合并）
        all_trades = []
        for ts_code, sr in successful.items():
            result = sr.get('result')
            if result and hasattr(result, 'daily_equity'):
                for t in result.trades:
                    all_trades.append({
                        'ts_code': ts_code,
                        'trade_id': t.trade_id,
                        'date': t.date,
                        'side': t.side.value,
                        'price': t.price,
                        'quantity': t.quantity,
                        'amount': t.amount,
                        'commission': t.commission,
                        'total_cost': t.total_cost,
                    })

        # 区域4: 绩效指标（聚合版）
        portfolio_metrics = aggregation.get('total_return', {})
        summary['trading_days'] = len(equity_curve)

        # 区域5: 横截面聚合
        # (已在上文计算)

        # 区域6: 基准对比（暂缺基准数据，留空）
        benchmark = {
            'benchmark_return': None,
            'excess_return': None,
            'benchmark_name': '待配置',
        }

        # 区域7: 检查点
        # (已在上文计算)

        # 区域8: 配置
        config_info = {
            'initial_capital': config.initial_capital,
            'commission_rate': config.commission_rate,
            'stamp_duty_rate': config.stamp_duty_rate,
            'slippage_rate': config.slippage_rate,
            'max_position': config.max_position,
            'price_limit_check': config.price_limit_check,
        }

        # 区域9: 策略信息
        strategy_info = {
            'strategy_id': 'sma_cross_v1',
            'strategy_name': 'SMA5/20金叉死叉（含成交量确认）',
            'signal_method': 'combined',
            'backtest_engine': 'AShareBacktestEngine V2',
        }

        return {
            'success': True,
            'task_id': task_id,
            'summary': summary,
            'equity_curve': equity_curve,
            'trades': {
                'total_trades': len(all_trades),
                'buy_trades': sum(1 for t in all_trades if t['side'] == 'buy'),
                'sell_trades': sum(1 for t in all_trades if t['side'] == 'sell'),
                'all_trades': all_trades[:500],  # 前端限制500条
                'truncated': len(all_trades) > 500,
            },
            'metrics': portfolio_metrics,
            'cross_sectional': aggregation,
            'benchmark': benchmark,
            'checkpoints': checkpoints,
            'config': config_info,
            'strategy_info': strategy_info,
            'per_stock': {
                ts_code: {
                    'metrics': sr.get('result').metrics if sr and sr.get('result') else {},
                    'extended': sr.get('extended_metrics', {}),
                    'trade_count': len(sr.get('result').trades) if sr and sr.get('result') else 0,
                }
                for ts_code, sr in successful.items()
            },
        }


# ── 辅助函数 ──────────────────────────────────────────────────────

def _update_progress(task_id: str, status: str, pct: float,
                     message: str = '', current_stock: str = '',
                     stocks_completed: int = 0, stocks_total: int = 0):
    """更新任务进度"""
    task = _task_store.get(task_id)
    if task:
        task.status = status
        task.progress_pct = round(min(pct, 1.0), 4)
        if message:
            task.message = message
        if current_stock:
            task.current_stock = current_stock
        if stocks_completed:
            task.stocks_completed = stocks_completed
        if stocks_total:
            task.stocks_total = stocks_total
        if pct >= 1.0:
            task.completed_at = datetime.now().isoformat()


def _checkpoint_return(daily_equity: List, periods: int) -> float:
    """计算第N个交易日的累计收益"""
    if not daily_equity or len(daily_equity) < periods + 1:
        return 0.0
    start_val = daily_equity[0].total_value
    if start_val <= 0:
        return 0.0
    end_val = daily_equity[min(periods, len(daily_equity) - 1)].total_value
    return (end_val - start_val) / start_val


def _avg_holding_days(trades: List) -> float:
    """计算平均持仓天数"""
    buys = [t for t in trades if t.side.value == 'buy']
    sells = [t for t in trades if t.side.value == 'sell']
    if not buys or not sells:
        return 0.0
    # 按ts_code配对
    holdings = []
    for t in buys:
        holding_sells = [s for s in sells if s.ts_code == t.ts_code and s.date >= t.date]
        if holding_sells:
            days = (datetime.strptime(holding_sells[0].date, '%Y-%m-%d') -
                    datetime.strptime(t.date, '%Y-%m-%d')).days
            holdings.append(days)
    return round(np.mean(holdings), 1) if holdings else 0.0


def _pass_rate(df: pd.DataFrame, col: str, condition_fn) -> float:
    """计算通过率"""
    if col not in df.columns:
        return 0.0
    vals = df[col].dropna()
    if vals.empty:
        return 0.0
    return round(float(condition_fn(vals).sum() / len(vals)), 4)


def _build_median_equity_curve(valid_results: Dict[str, Dict]) -> List[Dict]:
    """基于中位数构建横截面净值曲线"""
    all_curves = {}
    for ts_code, sr in valid_results.items():
        r = sr.get('result')
        if not r or not hasattr(r, 'daily_equity'):
            continue
        for eq in r.daily_equity:
            if eq.date not in all_curves:
                all_curves[eq.date] = []
            all_curves[eq.date].append(eq.total_value)

    sorted_dates = sorted(all_curves.keys())
    curve = []
    for d in sorted_dates:
        vals = all_curves[d]
        if vals:
            curve.append({
                'date': d,
                'median_value': round(float(np.median(vals)), 2),
                'mean_value': round(float(np.mean(vals)), 2),
                'q25_value': round(float(np.percentile(vals, 25)), 2),
                'q75_value': round(float(np.percentile(vals, 75)), 2),
                'stock_count': len(vals),
            })
    return curve


# ── 优化引擎 ──────────────────────────────────────────────────────

class ParameterOptimizer:
    """回测参数优化引擎（网格搜索）"""

    @staticmethod
    def grid_search(
        ts_code: str,
        param_grid: Dict[str, List],
        start_date: str,
        end_date: str,
        base_config: Optional[Dict] = None,
    ) -> Dict:
        """
        网格搜索参数优化

        Args:
            ts_code: 股票代码
            param_grid: 参数网格 {param_name: [values]}
            start_date: 开始日期
            end_date: 结束日期
            base_config: 基础回测配置

        Returns:
            优化结果（包含所有组合的评分排序）
        """
        from app.data.tushare_provider import TushareProvider
        tp = TushareProvider()
        if not tp.pro:
            return {'success': False, 'error': '数据源不可用'}

        # 获取数据
        warmup = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=90)).strftime('%Y%m%d')
        raw = tp.get_daily_data(ts_code, warmup, end_date)
        if not raw:
            return {'success': False, 'error': f'获取{ts_code}数据失败'}
        df = pd.DataFrame(raw)
        date_col = 'trade_date' if 'trade_date' in df.columns else 'date'
        df = df.set_index(date_col).sort_index()

        # 生成参数组合
        import itertools
        param_names = list(param_grid.keys())
        combos = [dict(zip(param_names, vals)) for vals in itertools.product(*param_grid.values())]

        results = []
        config_base = base_config or {}
        for combo in combos:
            try:
                # 根据当前参数生成信号
                short_window = combo.get('short_window', 5)
                long_window = combo.get('long_window', 20)
                rsi_period = combo.get('rsi_period', 14)

                close = df['close'].astype(float)
                sma_short = close.rolling(short_window).mean()
                sma_long = close.rolling(long_window).mean()

                signal = pd.Series(0, index=df.index)
                signal[(sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))] = 1
                signal[(sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))] = -1

                signals_df = pd.DataFrame({
                    'signal': signal,
                    'ts_code': ts_code,
                }).reset_index(names='date')

                price_df = df.reset_index()

                engine = create_default_engine()
                bc = BacktestConfig(
                    initial_capital=config_base.get('initial_capital', 100000),
                    commission_rate=config_base.get('commission_rate', 0.0003),
                    stamp_duty_rate=config_base.get('stamp_duty_rate', 0.001),
                    slippage_rate=config_base.get('slippage_rate', 0.0001),
                    max_position=config_base.get('max_position', 10),
                )

                engine = AShareBacktestEngine(bc)
                result = engine.run_backtest(price_df, signals_df, None, start_date, end_date)
                m = result.metrics

                combo_score = (
                    m.get('sharpe_ratio', 0) * 0.4 +
                    m.get('total_return', 0) * 100 * 0.3 +
                    (1 - m.get('max_drawdown', 1)) * 0.3
                )

                results.append({
                    'params': combo,
                    'metrics': {
                        'sharpe_ratio': m.get('sharpe_ratio'),
                        'total_return': m.get('total_return'),
                        'max_drawdown': m.get('max_drawdown'),
                        'win_rate': m.get('win_rate'),
                        'total_trades': m.get('total_trades'),
                    },
                    'score': round(combo_score, 4),
                })
            except Exception as e:
                logger.warning(f"参数组合优化失败 {combo}: {e}")
                continue

        results.sort(key=lambda x: x['score'], reverse=True)

        return {
            'success': True,
            'ts_code': ts_code,
            'total_combinations': len(combos),
            'evaluated': len(results),
            'param_names': param_names,
            'best_params': results[0]['params'] if results else None,
            'best_score': results[0]['score'] if results else None,
            'results': results[:50],  # 返回Top50
        }


# ── 快照管理 ──────────────────────────────────────────────────────

_snapshot_store: List[Dict] = []


def save_snapshot(params: Dict, metrics: Dict, note: str = '') -> Dict:
    """保存参数快照"""
    snapshot = {
        'id': f"SN-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
        'params': params,
        'metrics': metrics,
        'note': note,
        'created_at': datetime.now().isoformat(),
    }
    _snapshot_store.append(snapshot)
    return snapshot


def list_snapshots(limit: int = 20) -> List[Dict]:
    return sorted(_snapshot_store, key=lambda x: x['created_at'], reverse=True)[:limit]
