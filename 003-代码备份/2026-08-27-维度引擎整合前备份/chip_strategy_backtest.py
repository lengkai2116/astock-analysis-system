"""
筹码分布策略历史回测验证
使用真实历史数据验证策略效果
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List


class ChipStrategyBacktester:
    """
    筹码分布策略回测器
    """

    def __init__(self, stock_code: str = '000001.SZ'):
        self.stock_code = stock_code
        from app.engine.pipeline import ChipDistributionStrategy
        self.strategy = ChipDistributionStrategy(lookback_period=120)
        from app.engine.backtest_v2 import create_default_engine
        self.backtest_engine = create_default_engine()

    def fetch_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """获取历史数据"""
        from app.data.tushare_provider import TushareProvider

        provider = TushareProvider()
        data = provider.get_daily_data(
            ts_code=self.stock_code,
            start_date=start_date,
            end_date=end_date
        )

        if data and isinstance(data, list):
            df = pd.DataFrame(data)
            # 按日期排序
            df = df.sort_values('trade_date').reset_index(drop=True)
            return df

        return pd.DataFrame()

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成交易信号"""
        signals = []

        for i in range(120, len(df)):  # 需要至少120天数据
            # 获取历史窗口数据
            window_data = df.iloc[:i+1].copy()

            # 计算筹码分布和分析
            try:
                analysis = self.strategy.analyze(window_data)
                recommendation = analysis.get('recommendation', {})

                action = recommendation.get('action', 'HOLD')
                reason = recommendation.get('reason', '')

                # 生成信号
                if action == 'BUY':
                    signal = 1
                elif action == 'SELL':
                    signal = -1
                else:
                    signal = 0

                signals.append({
                    'trade_date': df.iloc[i]['trade_date'],
                    'ts_code': self.stock_code,
                    'signal': signal,
                    'action': action,
                    'reason': reason,
                    'close': df.iloc[i]['close']
                })

            except Exception as e:
                print(f"信号生成失败: {e}")
                signals.append({
                    'trade_date': df.iloc[i]['trade_date'],
                    'ts_code': self.stock_code,
                    'signal': 0,
                    'action': 'ERROR',
                    'reason': str(e),
                    'close': df.iloc[i]['close']
                })

        return pd.DataFrame(signals)

    def run_backtest(self, price_df: pd.DataFrame, signals_df: pd.DataFrame) -> Dict:
        """运行回测"""
        if signals_df.empty:
            return {'error': '没有信号'}

        # 合并价格和信号
        merged = price_df.merge(
            signals_df[['trade_date', 'signal']],
            on='trade_date',
            how='left'
        )
        merged['signal'] = merged['signal'].fillna(0)

        # 运行回测引擎
        result = self.backtest_engine.run_backtest(
            price_data=merged,
            signals=signals_df,
            start_date=price_df['trade_date'].iloc[0],
            end_date=price_df['trade_date'].iloc[-1]
        )

        return {
            'result': result,
            'metrics': result.metrics,
            'trade_count': len(result.trades)
        }

    def analyze_results(self, result) -> Dict:
        """分析回测结果"""
        if not result.metrics:
            return {}

        metrics = result.metrics

        return {
            'total_return': metrics.get('total_return', 0),
            'annual_return': metrics.get('annual_return', 0),
            'max_drawdown': metrics.get('max_drawdown', 0),
            'sharpe_ratio': metrics.get('sharpe_ratio', 0),
            'win_rate': metrics.get('win_rate', 0),
            'trade_count': metrics.get('trade_count', 0),
            'avg_trades_per_year': metrics.get('trade_count', 0) / max(metrics.get('trading_days', 1) / 252, 1)
        }

    def run_full_backtest(self, start_date: str, end_date: str) -> Dict:
        """完整回测流程"""
        print(f"\n{'='*60}")
        print(f"筹码分布策略回测验证")
        print(f"{'='*60}")
        print(f"股票: {self.stock_code}")
        print(f"时间范围: {start_date} 至 {end_date}")

        # 1. 获取数据
        print(f"\n[1/4] 获取历史数据...")
        df = self.fetch_data(start_date, end_date)
        if df.empty:
            return {'error': '数据获取失败'}

        print(f"✓ 获取数据: {len(df)} 条")

        # 2. 生成信号
        print(f"\n[2/4] 生成交易信号...")
        signals_df = self.generate_signals(df)

        buy_signals = (signals_df['signal'] == 1).sum()
        sell_signals = (signals_df['signal'] == -1).sum()
        hold_signals = (signals_df['signal'] == 0).sum()

        print(f"✓ 买入信号: {buy_signals} 次")
        print(f"✓ 卖出信号: {sell_signals} 次")
        print(f"✓ 观望信号: {hold_signals} 次")

        # 3. 运行回测
        print(f"\n[3/4] 运行回测...")
        backtest_result = self.run_backtest(df, signals_df)

        if 'error' in backtest_result:
            return backtest_result

        # 4. 分析结果
        print(f"\n[4/4] 分析结果...")
        analysis = self.analyze_results(backtest_result['result'])

        print(f"\n{'='*60}")
        print(f"回测结果")
        print(f"{'='*60}")
        print(f"总交易次数: {analysis.get('trade_count', 0)}")
        print(f"年化交易次数: {analysis.get('avg_trades_per_year', 0):.1f}")
        print(f"胜率: {analysis.get('win_rate', 0):.2%}")
        print(f"总收益率: {analysis.get('total_return', 0):.2%}")
        print(f"年化收益率: {analysis.get('annual_return', 0):.2%}")
        print(f"最大回撤: {analysis.get('max_drawdown', 0):.2%}")
        print(f"夏普比率: {analysis.get('sharpe_ratio', 0):.2f}")

        return {
            'data_info': {
                'stock_code': self.stock_code,
                'start_date': start_date,
                'end_date': end_date,
                'data_count': len(df)
            },
            'signal_summary': {
                'buy': buy_signals,
                'sell': sell_signals,
                'hold': hold_signals
            },
            'performance': analysis
        }


def main():
    """主函数"""
    print("\n" + "="*60)
    print("筹码分布策略历史数据验证测试")
    print("="*60)

    # 创建回测器
    tester = ChipStrategyBacktester('000001.SZ')

    # 运行回测（2025年全年）
    result = tester.run_full_backtest('2025-01-01', '2026-01-01')

    # 结果评估
    print("\n" + "="*60)
    print("评估结论")
    print("="*60)

    if 'error' in result:
        print(f"❌ 回测失败: {result['error']}")
        return

    perf = result.get('performance', {})

    # 技术说明书建议的目标
    print("\n对比技术说明书建议的目标:")
    print(f"  - 目标年化收益率: >15%")
    print(f"  - 实际年化收益率: {perf.get('annual_return', 0):.2%}")
    print(f"  - 达标情况: {'✓' if perf.get('annual_return', 0) > 0.15 else '✗'}")

    print(f"\n  - 目标最大回撤: <25%")
    print(f"  - 实际最大回撤: {perf.get('max_drawdown', 0):.2%}")
    print(f"  - 达标情况: {'✓' if perf.get('max_drawdown', 0) < 0.25 else '✗'}")

    print(f"\n  - 目标夏普比率: >1.2")
    print(f"  - 实际夏普比率: {perf.get('sharpe_ratio', 0):.2f}")
    print(f"  - 达标情况: {'✓' if perf.get('sharpe_ratio', 0) > 1.2 else '✗'}")

    print(f"\n  - 目标胜率: >45%")
    print(f"  - 实际胜率: {perf.get('win_rate', 0):.2%}")
    print(f"  - 达标情况: {'✓' if perf.get('win_rate', 0) > 0.45 else '✗'}")

    print(f"\n  - 目标交易频率: 月均2-5次")
    print(f"  - 实际年化交易: {perf.get('avg_trades_per_year', 0):.1f}次")
    print(f"  - 达标情况: {'✓' if 24 <= perf.get('avg_trades_per_year', 0) <= 60 else '✗'}")

    print("\n" + "="*60)
    print("✓ 历史数据验证测试完成!")
    print("="*60)


if __name__ == '__main__':
    main()
