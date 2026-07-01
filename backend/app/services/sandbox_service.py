"""
策略沙箱服务（222号 Phase 1）
单策略轻量测试 → 参数变体对比 → 简化绩效输出
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import uuid

from app.engine.backtest_v2 import AShareBacktestEngine, BacktestConfig, create_default_engine
from app.data.tushare_provider import TushareProvider

logger = logging.getLogger(__name__)


class SandboxService:
    """
    策略沙箱服务

    单策略轻量测试引擎，支持：
    - 单次测试：固定参数运行并输出绩效
    - 参数变体对比：多组参数运行并排序对比
    - 快速运行：跳过完整回测，仅计算关键指标
    """

    def __init__(self):
        self._tp: Optional[TushareProvider] = None

    def _get_provider(self) -> Optional[TushareProvider]:
        if self._tp is None:
            try:
                self._tp = TushareProvider()
                if not self._tp.pro:
                    self._tp = None
            except Exception:
                self._tp = None
        return self._tp

    def run_single(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        params: Optional[Dict] = None,
        config: Optional[Dict] = None,
    ) -> Dict:
        """
        运行单策略沙箱测试

        Args:
            ts_code: 股票代码
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            params: 策略参数 {short_window, long_window, signal_method, ...}
            config: 回测配置

        Returns:
            简化绩效结果（5区域）
        """
        tp = self._get_provider()
        if not tp:
            return {'success': False, 'error': '数据源不可用'}

        params = params or {}
        config = config or {}

        # 1. 获取数据（含信号预热期）
        warmup = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=90)).strftime('%Y%m%d')
        raw = tp.get_daily_data(ts_code, warmup, end_date)
        if not raw:
            return {'success': False, 'error': f'获取{ts_code}日线数据为空'}

        df = pd.DataFrame(raw)
        date_col = 'trade_date' if 'trade_date' in df.columns else 'date'
        if date_col not in df.columns:
            return {'success': False, 'error': '数据缺少日期列'}
        df = df.set_index(date_col).sort_index()

        close = df['close'].astype(float)

        # 2. 根据参数生成信号
        signal_method = params.get('signal_method', 'sma_cross')
        short_window = params.get('short_window', 5)
        long_window = params.get('long_window', 20)

        signal = self._generate_signal(close, signal_method, short_window, long_window, params, df)

        # 3. 构建引擎输入
        signals_df = pd.DataFrame({
            'signal': signal,
            'ts_code': ts_code,
        }).reset_index(names='date')

        price_df = df.reset_index()

        # 4. 运行回测
        bc = BacktestConfig(
            initial_capital=config.get('initial_capital', 100000),
            commission_rate=config.get('commission_rate', 0.0003),
            stamp_duty_rate=config.get('stamp_duty_rate', 0.001),
            slippage_rate=config.get('slippage_rate', 0.0001),
            min_commission=config.get('min_commission', 5.0),
            max_position=config.get('max_position', 1),
        )

        engine = AShareBacktestEngine(bc)
        result = engine.run_backtest(
            price_data=price_df,
            signals=signals_df,
            benchmark_data=None,
            start_date=start_date,
            end_date=end_date,
        )

        # 5. 构建简化5区域输出
        return self._build_sandbox_output(ts_code, result, params, bc)

    def run_compare(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        param_sets: List[Dict],
        config: Optional[Dict] = None,
    ) -> Dict:
        """
        运行多组参数变体对比

        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            param_sets: 参数集列表，每项包含 {label, params, config?}
            config: 基础回测配置

        Returns:
            对比结果（各变体绩效 + 排序）
        """
        config = config or {}
        results = []

        for i, ps in enumerate(param_sets):
            label = ps.get('label', f'变体{i+1}')
            p = ps.get('params', {})
            try:
                r = self.run_single(ts_code, start_date, end_date, p, {**config, **(ps.get('config', {}))})
                results.append({
                    'label': label,
                    'params': p,
                    'success': r.get('success', False),
                    'metrics': r.get('metrics', {}),
                    'error': r.get('error'),
                })
            except Exception as e:
                results.append({
                    'label': label,
                    'params': p,
                    'success': False,
                    'error': str(e),
                })

        # 按 Sharpe 排序
        valid = [r for r in results if r.get('success')]
        valid.sort(key=lambda x: x.get('metrics', {}).get('sharpe_ratio', -999), reverse=True)

        return {
            'success': True,
            'ts_code': ts_code,
            'date_range': {'start': start_date, 'end': end_date},
            'variant_count': len(param_sets),
            'successful': len(valid),
            'ranked': valid,
            'best_label': valid[0]['label'] if valid else None,
            'best_sharpe': valid[0].get('metrics', {}).get('sharpe_ratio') if valid else None,
        }

    def _generate_signal(
        self,
        close: pd.Series,
        method: str,
        short_window: int,
        long_window: int,
        params: Dict,
        df: pd.DataFrame,
    ) -> pd.Series:
        """生成交易信号"""
        signal = pd.Series(0, index=close.index)

        if method in ('sma_cross', 'ma_cross'):
            sma_short = close.rolling(short_window).mean()
            sma_long = close.rolling(long_window).mean()
            signal[(sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))] = 1
            signal[(sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))] = -1

        elif method == 'rsi':
            rsi_period = params.get('rsi_period', 14)
            rsi_overbought = params.get('rsi_overbought', 70)
            rsi_oversold = params.get('rsi_oversold', 30)
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(rsi_period).mean()
            loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
            rsi = 100 - (100 / (1 + gain / (loss + 1e-10)))
            signal[rsi < rsi_oversold] = 1
            signal[rsi > rsi_overbought] = -1

        elif method == 'bb':
            # 布林带策略：触下轨买，触上轨卖
            bb_period = params.get('bb_period', 20)
            bb_std = params.get('bb_std', 2.0)
            sma = close.rolling(bb_period).mean()
            std = close.rolling(bb_period).std()
            upper = sma + bb_std * std
            lower = sma - bb_std * std
            signal[close <= lower] = 1
            signal[close >= upper] = -1

        elif method == 'trend_follow':
            # 趋势跟踪：EMA12/EMA26 金叉死叉
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9).mean()
            signal[(macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))] = 1
            signal[(macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))] = -1

        else:  # sma_cross default
            sma_short = close.rolling(short_window).mean()
            sma_long = close.rolling(long_window).mean()
            signal[(sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))] = 1
            signal[(sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))] = -1

        return signal

    def _build_sandbox_output(
        self,
        ts_code: str,
        result: Any,
        params: Dict,
        config: BacktestConfig,
    ) -> Dict:
        """构建简化5区域输出"""
        m = result.metrics

        # 区域1: 基本信息
        info = {
            'ts_code': ts_code,
            'method': params.get('signal_method', 'sma_cross'),
            'params': {k: v for k, v in params.items()},
            'config': {
                'initial_capital': config.initial_capital,
                'commission_rate': config.commission_rate,
            },
        }

        # 区域2: 绩效指标
        metrics = {
            'total_return': m.get('total_return'),
            'annual_return': m.get('annual_return'),
            'sharpe_ratio': m.get('sharpe_ratio'),
            'max_drawdown': m.get('max_drawdown'),
            'win_rate': m.get('win_rate'),
            'volatility': m.get('volatility'),
            'total_trades': m.get('total_trades'),
            'profit_loss_ratio': m.get('profit_loss_ratio'),
        }

        # 区域3: 交易记录（简化）
        trades = []
        for t in result.trades[:50]:
            trades.append({
                'date': t.date,
                'side': t.side.value,
                'price': t.price,
                'quantity': t.quantity,
                'pnl': round((t.price - t.amount / t.quantity) if t.quantity > 0 else 0, 2),
            })

        # 区域4: 净值曲线（简化，最多60点）
        equity = []
        step = max(1, len(result.daily_equity) // 60)
        for i, e in enumerate(result.daily_equity):
            if i % step == 0 or i == len(result.daily_equity) - 1:
                equity.append({
                    'date': e.date,
                    'total_value': round(e.total_value, 2),
                    'daily_return': round(e.daily_return, 4),
                })

        # 区域5: 评估建议
        suggestions = []
        if m.get('sharpe_ratio', 0) < 0.5:
            suggestions.append('夏普比率偏低，建议调整参数')
        if m.get('max_drawdown', 0) > 0.2:
            suggestions.append('最大回撤较大，建议收紧止损')
        if m.get('total_trades', 0) < 5:
            suggestions.append('交易次数偏少，信号可能过于稀疏')
        if m.get('win_rate', 0) < 0.35:
            suggestions.append('胜率偏低，建议结合趋势过滤')

        return {
            'success': True,
            'info': info,
            'metrics': metrics,
            'trades': trades,
            'truncated_trades': len(result.trades) > 50,
            'equity_curve': equity,
            'suggestions': suggestions,
            'generated_at': datetime.now().isoformat(),
        }


# ── 沙箱历史记录（内存存储） ────────────────────────────────────

_sandbox_history: List[Dict] = []


def save_test_record(ts_code: str, params: Dict, metrics: Dict, note: str = ''):
    """保存沙箱测试记录"""
    record = {
        'id': f"SB-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
        'ts_code': ts_code,
        'params': params,
        'metrics': metrics,
        'note': note,
        'created_at': datetime.now().isoformat(),
    }
    _sandbox_history.append(record)
    return record


def list_test_records(limit: int = 20) -> List[Dict]:
    return sorted(_sandbox_history, key=lambda x: x['created_at'], reverse=True)[:limit]
