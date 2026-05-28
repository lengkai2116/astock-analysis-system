"""
筹码分布策略信号诊断
分析为什么没有生成买入信号
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np


def diagnose_signals():
    """诊断信号生成问题"""
    print("="*60)
    print("筹码分布策略信号诊断")
    print("="*60)

    # 获取数据
    from app.data.tushare_provider import TushareProvider
    from app.engine.pipeline import ChipDistributionStrategy

    provider = TushareProvider()
    strategy = ChipDistributionStrategy(lookback_period=120)

    print("\n[1] 获取历史数据...")
    data = provider.get_daily_data(
        ts_code='000001.SZ',
        start_date='2025-01-01',
        end_date='2026-01-01'
    )

    if not data or not isinstance(data, list):
        print("❌ 数据获取失败")
        return

    df = pd.DataFrame(data)
    df = df.sort_values('trade_date').reset_index(drop=True)
    print(f"✓ 获取数据: {len(df)} 条")

    # 分析每个时点
    print("\n[2] 分析信号条件...")
    signal_conditions = []

    for i in range(120, min(len(df), 200)):  # 分析前200天的信号
        window_data = df.iloc[:i+1].copy()

        try:
            analysis = strategy.analyze(window_data)
            indicators = analysis.get('indicators', {})
            phase_info = analysis.get('phase_info', {})

            # 记录每个条件的满足情况
            conditions = {
                'date': df.iloc[i]['trade_date'],
                'close': df.iloc[i]['close'],
                'phase': phase_info.get('phase', 'UNKNOWN'),
                'confidence': phase_info.get('confidence', 0),

                # S_BUY条件
                'ssrp': indicators.get('ssrp', 0),
                'ssrp_vs_close': (df.iloc[i]['close'] - indicators.get('ssrp', 0)) / indicators.get('ssrp', 1) if indicators.get('ssrp', 0) > 0 else 0,
                'asr': indicators.get('asr', 0),
                'profit_ratio': indicators.get('profit_ratio', 0),
                'rsi': indicators.get('rsi', 0),
                'vol_ratio': indicators.get('vol_ratio', 0),
                'cyqkl': indicators.get('cyqkl', 0),

                # 信号
                'signal': analysis.get('recommendation', {}).get('action', 'HOLD'),
                'reason': analysis.get('recommendation', {}).get('reason', '')
            }

            signal_conditions.append(conditions)

        except Exception as e:
            print(f"❌ 分析失败: {e}")

    # 分析结果
    print("\n[3] 信号分析结果...")
    df_conditions = pd.DataFrame(signal_conditions)

    if df_conditions.empty:
        print("❌ 没有有效的信号数据")
        return

    # 统计各阶段分布
    print(f"\n主力阶段分布:")
    phase_counts = df_conditions['phase'].value_counts()
    for phase, count in phase_counts.items():
        print(f"  - {phase}: {count}次 ({count/len(df_conditions)*100:.1f}%)")

    # 统计各信号分布
    print(f"\n信号分布:")
    signal_counts = df_conditions['signal'].value_counts()
    for signal, count in signal_counts.items():
        print(f"  - {signal}: {count}次 ({count/len(df_conditions)*100:.1f}%)")

    # 分析为什么没有买入信号
    print(f"\n[4] 分析买入条件...")
    buy_candidates = df_conditions[df_conditions['signal'] == 'BUY']
    if buy_candidates.empty:
        print("没有买入信号，分析原因:")

        # 检查各条件
        print(f"\n1. 拉升期出现次数: {(df_conditions['phase'] == 'RAISING').sum()}")
        print(f"   - 拉升期是主买入的必要条件")

        print(f"\n2. 价格高于SSRP的比例:")
        above_ssrp = (df_conditions['ssrp_vs_close'] > 0).sum()
        print(f"   - {above_ssrp}次 ({above_ssrp/len(df_conditions)*100:.1f}%)")

        print(f"\n3. ASR>=0.7的比例:")
        high_asr = (df_conditions['asr'] >= 0.7).sum()
        print(f"   - {high_asr}次 ({high_asr/len(df_conditions)*100:.1f}%)")

        print(f"\n4. RSI>=50的比例:")
        high_rsi = (df_conditions['rsi'] >= 50).sum()
        print(f"   - {high_rsi}次 ({high_rsi/len(df_conditions)*100:.1f}%)")

        print(f"\n5. 获利率>=0.6的比例:")
        high_profit = (df_conditions['profit_ratio'] >= 0.6).sum()
        print(f"   - {high_profit}次 ({high_profit/len(df_conditions)*100:.1f}%)")

        print(f"\n6. 成交量放大(>=1.5)的比例:")
        high_vol = (df_conditions['vol_ratio'] >= 1.5).sum()
        print(f"   - {high_vol}次 ({high_vol/len(df_conditions)*100:.1f}%)")

        print(f"\n结论:")
        print(f"  策略信号生成条件较严格，需要同时满足多个条件。")
        print(f"  建议:")
        print(f"  1. 放宽信号触发条件")
        print(f"  2. 添加更多试探性买入信号")
        print(f"  3. 使用更敏感的主力阶段判断")

    else:
        print(f"\n找到{len(buy_candidates)}次买入机会:")
        print(buy_candidates[['date', 'close', 'phase', 'ssrp', 'rsi', 'reason']].to_string())

    # 查看最近的信号
    print(f"\n[5] 最近10天的信号...")
    recent = df_conditions.tail(10)[['date', 'close', 'phase', 'confidence', 'asr', 'rsi', 'signal', 'reason']]
    print(recent.to_string())

    print("\n" + "="*60)


def main():
    """主函数"""
    print("\n" + "="*60)
    print("筹码分布策略信号诊断工具")
    print("="*60)

    diagnose_signals()

    print("\n✅ 诊断完成")


if __name__ == '__main__':
    main()
