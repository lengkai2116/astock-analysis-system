"""
筹码分布策略多股票回测测试
选取10只代表性股票进行历史数据验证
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List


class MultiStockBacktester:
    """多股票回测器"""

    # 选取10只代表性股票
    STOCK_POOL = [
        {
            'code': '000001.SZ',
            'name': '平安银行',
            'industry': '银行',
            'market_cap': '大盘'
        },
        {
            'code': '000002.SZ',
            'name': '万科A',
            'industry': '房地产',
            'market_cap': '大盘'
        },
        {
            'code': '000858.SZ',
            'name': '五粮液',
            'industry': '白酒',
            'market_cap': '大盘'
        },
        {
            'code': '002594.SZ',
            'name': '比亚迪',
            'industry': '新能源汽车',
            'market_cap': '大盘'
        },
        {
            'code': '300059.SZ',
            'name': '东方财富',
            'industry': '互联网金融',
            'market_cap': '大盘'
        },
        {
            'code': '600519.SH',
            'name': '贵州茅台',
            'industry': '白酒',
            'market_cap': '超大盘'
        },
        {
            'code': '600036.SH',
            'name': '招商银行',
            'industry': '银行',
            'market_cap': '大盘'
        },
        {
            'code': '601318.SH',
            'name': '中国平安',
            'industry': '保险',
            'market_cap': '超大盘'
        },
        {
            'code': '002415.SZ',
            'name': '海康威视',
            'industry': '电子',
            'market_cap': '大盘'
        },
        {
            'code': '300750.SZ',
            'name': '宁德时代',
            'industry': '新能源',
            'market_cap': '大盘'
        }
    ]

    def __init__(self, start_date: str, end_date: str):
        self.start_date = start_date
        self.end_date = end_date

        from app.engine.pipeline import ChipDistributionStrategy
        from app.engine.backtest_v2 import create_default_engine

        self.strategy = ChipDistributionStrategy(lookback_period=120)
        self.backtest_engine = create_default_engine()

    def fetch_and_analyze(self, stock_info: Dict) -> Dict:
        """获取并分析单只股票"""
        code = stock_info['code']
        name = stock_info['name']
        industry = stock_info['industry']
        market_cap = stock_info['market_cap']

        result = {
            'code': code,
            'name': name,
            'industry': industry,
            'market_cap': market_cap,
            'success': False,
            'data_count': 0,
            'signals': {},
            'metrics': {}
        }

        try:
            # 获取数据
            from app.data.tushare_provider import TushareProvider
            provider = TushareProvider()

            data = provider.get_daily_data(
                ts_code=code,
                start_date=self.start_date,
                end_date=self.end_date
            )

            if not data or not isinstance(data, list):
                result['error'] = '数据获取失败'
                return result

            df = pd.DataFrame(data)
            df = df.sort_values('trade_date').reset_index(drop=True)

            result['data_count'] = len(df)
            result['date_range'] = f"{df['trade_date'].min()} ~ {df['trade_date'].max()}"

            # 生成信号
            signals = self._generate_signals(df)
            result['signals'] = signals

            # 信号统计
            result['buy_count'] = signals.get('buy', 0)
            result['sell_count'] = signals.get('sell', 0)
            result['hold_count'] = signals.get('hold', 0)

            # 阶段分布
            phase_dist = signals.get('phase_distribution', {})
            result['phase_distribution'] = phase_dist

            # 主要阶段
            if phase_dist:
                main_phase = max(phase_dist.items(), key=lambda x: x[1])
                result['main_phase'] = main_phase[0]
                result['main_phase_ratio'] = f"{main_phase[1]/sum(phase_dist.values())*100:.1f}%"

            # 平均指标
            indicators = signals.get('indicators_summary', {})
            result['indicators'] = indicators

            result['success'] = True

        except Exception as e:
            result['error'] = str(e)

        return result

    def _generate_signals(self, df: pd.DataFrame) -> Dict:
        """生成信号统计"""
        signals = {
            'buy': 0,
            'sell': 0,
            'hold': 0,
            'phase_distribution': {},
            'indicators_summary': {}
        }

        phase_counts = {}
        ssrp_list = []
        asr_list = []
        rsi_list = []
        profit_ratio_list = []

        for i in range(120, len(df)):
            window_data = df.iloc[:i+1].copy()

            try:
                analysis = self.strategy.analyze(window_data)

                # 统计信号
                recommendation = analysis.get('recommendation', {})
                action = recommendation.get('action', 'HOLD')

                if action == 'BUY':
                    signals['buy'] += 1
                elif action == 'SELL':
                    signals['sell'] += 1
                else:
                    signals['hold'] += 1

                # 统计阶段
                phase_info = analysis.get('phase_info', {})
                phase = phase_info.get('phase', 'UNKNOWN')
                phase_counts[phase] = phase_counts.get(phase, 0) + 1

                # 收集指标
                indicators = analysis.get('indicators', {})
                if indicators:
                    ssrp_list.append(indicators.get('ssrp', 0))
                    asr_list.append(indicators.get('asr', 0))
                    rsi_list.append(indicators.get('rsi', 0))
                    profit_ratio_list.append(indicators.get('profit_ratio', 0))

            except:
                pass

        signals['phase_distribution'] = phase_counts

        # 计算平均指标
        if ssrp_list:
            signals['indicators_summary'] = {
                'avg_ssrp': np.mean(ssrp_list),
                'avg_asr': np.mean(asr_list),
                'avg_rsi': np.mean(rsi_list),
                'avg_profit_ratio': np.mean(profit_ratio_list)
            }

        return signals

    def run_backtest(self) -> Dict:
        """运行多股票回测"""
        print("="*80)
        print("筹码分布策略多股票回测测试")
        print("="*80)
        print(f"时间范围: {self.start_date} ~ {self.end_date}")
        print(f"股票数量: {len(self.STOCK_POOL)}")
        print("="*80)

        results = []
        success_count = 0
        fail_count = 0

        for i, stock in enumerate(self.STOCK_POOL, 1):
            print(f"\n[{i}/{len(self.STOCK_POOL)}] 正在分析 {stock['name']}({stock['code']})...")

            result = self.fetch_and_analyze(stock)

            if result['success']:
                success_count += 1
                print(f"  ✓ 数据: {result['data_count']}条 | 买入: {result['buy_count']}次 | 卖出: {result['sell_count']}次")
                print(f"    主要阶段: {result.get('main_phase', 'N/A')} ({result.get('main_phase_ratio', 'N/A')})")
            else:
                fail_count += 1
                print(f"  ✗ 失败: {result.get('error', '未知错误')}")

            results.append(result)

        return {
            'results': results,
            'success_count': success_count,
            'fail_count': fail_count,
            'total_count': len(self.STOCK_POOL)
        }

    def print_summary(self, backtest_result: Dict):
        """打印汇总报告"""
        results = backtest_result['results']

        print("\n" + "="*80)
        print("汇总报告")
        print("="*80)

        # 按行业统计
        print("\n【一、按行业统计】")
        industry_stats = {}
        for r in results:
            if r['success']:
                industry = r['industry']
                if industry not in industry_stats:
                    industry_stats[industry] = {
                        'count': 0,
                        'total_buy': 0,
                        'total_sell': 0,
                        'total_data': 0
                    }

                industry_stats[industry]['count'] += 1
                industry_stats[industry]['total_buy'] += r.get('buy_count', 0)
                industry_stats[industry]['total_sell'] += r.get('sell_count', 0)
                industry_stats[industry]['total_data'] += r.get('data_count', 0)

        print(f"\n{'行业':<10} {'股票数':<8} {'买入信号':<10} {'卖出信号':<10} {'数据量':<10}")
        print("-" * 60)
        for industry, stats in sorted(industry_stats.items()):
            print(f"{industry:<10} {stats['count']:<8} {stats['total_buy']:<10} {stats['total_sell']:<10} {stats['total_data']:<10}")

        # 统计信号总数
        total_buy = sum(r.get('buy_count', 0) for r in results if r['success'])
        total_sell = sum(r.get('sell_count', 0) for r in results if r['success'])
        total_data = sum(r.get('data_count', 0) for r in results if r['success'])

        print(f"\n总计: 买入信号{total_buy}次, 卖出信号{total_sell}次, 数据量{total_data}条")

        # 阶段分布
        print("\n【二、主力阶段分布】")
        phase_total = {}
        for r in results:
            if r['success']:
                phases = r.get('phase_distribution', {})
                for phase, count in phases.items():
                    phase_total[phase] = phase_total.get(phase, 0) + count

        if phase_total:
            total = sum(phase_total.values())
            print(f"\n{'阶段':<15} {'次数':<10} {'占比':<10}")
            print("-" * 40)
            for phase, count in sorted(phase_total.items(), key=lambda x: x[1], reverse=True):
                ratio = count / total * 100 if total > 0 else 0
                print(f"{phase:<15} {count:<10} {ratio:>6.1f}%")

        # 平均指标
        print("\n【三、平均筹码指标】")
        all_ssrp = []
        all_asr = []
        all_rsi = []
        all_profit = []

        for r in results:
            if r['success']:
                indicators = r.get('indicators', {})
                if indicators:
                    all_ssrp.append(indicators.get('avg_ssrp', 0))
                    all_asr.append(indicators.get('avg_asr', 0))
                    all_rsi.append(indicators.get('avg_rsi', 0))
                    all_profit.append(indicators.get('avg_profit_ratio', 0))

        if all_ssrp:
            print(f"\n平均SSRP: {np.mean(all_ssrp):.2f}")
            print(f"平均ASR: {np.mean(all_asr):.4f}")
            print(f"平均RSI: {np.mean(all_rsi):.2f}")
            print(f"平均获利率: {np.mean(all_profit):.4f}")

        # 成功率统计
        print("\n【四、测试成功率】")
        print(f"成功: {backtest_result['success_count']}/{backtest_result['total_count']}")
        print(f"失败: {backtest_result['fail_count']}/{backtest_result['total_count']}")

        # 详细结果表
        print("\n【五、详细结果】")
        print(f"\n{'股票代码':<12} {'名称':<10} {'行业':<10} {'数据量':<8} {'买入':<6} {'卖出':<6} {'主要阶段':<15}")
        print("-" * 80)
        for r in results:
            if r['success']:
                code = r['code']
                name = r['name'][:8]
                industry = r['industry'][:8]
                data_count = r['data_count']
                buy = r.get('buy_count', 0)
                sell = r.get('sell_count', 0)
                main_phase = r.get('main_phase', 'N/A')
                print(f"{code:<12} {name:<10} {industry:<10} {data_count:<8} {buy:<6} {sell:<6} {main_phase:<15}")
            else:
                code = r['code']
                name = r['name'][:8]
                error = r.get('error', '未知')[:30]
                print(f"{code:<12} {name:<10} {'--':<10} {'--':<8} {'--':<6} {'--':<6} 失败: {error}")

        print("\n" + "="*80)


def main():
    """主函数"""
    # 使用2024年全年数据进行测试
    tester = MultiStockBacktester('2024-01-01', '2025-01-01')
    result = tester.run_backtest()
    tester.print_summary(result)


if __name__ == '__main__':
    main()
