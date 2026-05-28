"""
检查系统历史数据情况
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timedelta


def check_tushare_data():
    """检查Tushare数据获取能力"""
    print("=" * 60)
    print("检查 Tushare 数据获取能力")
    print("=" * 60)

    try:
        from app.data.tushare_provider import TushareProvider

        provider = TushareProvider()

        # 测试连接
        success, msg = provider.test_connection()
        print(f"Tushare连接: {'✓' if success else '✗'} {msg}")

        if success:
            # 获取日线数据
            print("\n尝试获取000001.SZ最近数据...")
            data = provider.get_daily_data(
                ts_code='000001.SZ',
                start_date='2025-01-01',
                end_date='2026-01-01'
            )

            if data and isinstance(data, list):
                df = pd.DataFrame(data)
                print(f"✓ 获取成功: {len(df)} 条")
                print(f"  - 数据类型: {type(data)}")
                print(f"  - 列名: {list(df.columns)}")

                if 'trade_date' in df.columns:
                    print(f"  - 时间范围: {df['trade_date'].min()} 至 {df['trade_date'].max()}")
                    print(f"\n最近5条数据:")
                    print(df.tail())
                return df
            elif data is not None and hasattr(data, 'empty'):
                print(f"✓ 获取成功: {len(data)} 条")
                return data
            else:
                print(f"✗ Tushare返回异常: {type(data)}")

        return None

    except Exception as e:
        print(f"✗ Tushare检查失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def check_chip_data(df):
    """检查筹码分布数据计算"""
    print("\n" + "=" * 60)
    print("检查筹码分布数据计算能力")
    print("=" * 60)

    if df is None or (hasattr(df, 'empty') and df.empty):
        print("✗ 无法获取日线数据，跳过筹码分布计算")
        return None

    try:
        from app.engine.pipeline import ChipDistributionStrategy

        strategy = ChipDistributionStrategy(lookback_period=120)

        print(f"✓ 策略创建成功")
        print(f"  - 策略名称: {strategy.name}")
        print(f"  - 回顾周期: {strategy.lookback_period}")

        # 计算筹码分布
        analysis = strategy.analyze(df)

        if analysis:
            indicators = analysis.get('indicators', {})
            phase_info = analysis.get('phase_info', {})

            print(f"\n筹码指标:")
            print(f"  - SSRP: {indicators.get('ssrp', 0):.2f}")
            print(f"  - ASR: {indicators.get('asr', 0):.4f}")
            print(f"  - 集中度: {indicators.get('concentration', 0):.4f}")
            print(f"  - 获利率: {indicators.get('profit_ratio', 0):.4f}")

            if 'rsi' in indicators:
                print(f"  - RSI: {indicators.get('rsi', 0):.2f}")

            print(f"\n主力阶段: {phase_info.get('phase_name', 'UNKNOWN')}")
            print(f"置信度: {phase_info.get('confidence', 0):.2%}")

            recommendation = analysis.get('recommendation', {})
            print(f"\n操作建议: {recommendation.get('action', 'HOLD')}")
            print(f"原因: {recommendation.get('reason', 'N/A')}")

        return analysis

    except Exception as e:
        print(f"✗ 筹码分布计算失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_backtest_capability(df):
    """测试回测能力"""
    print("\n" + "=" * 60)
    print("测试回测系统能力")
    print("=" * 60)

    if df is None or (hasattr(df, 'empty') and df.empty):
        print("✗ 无法获取日线数据，跳过回测测试")
        return None

    try:
        from app.engine.backtest_v2 import create_default_engine

        print(f"✓ 回测引擎创建成功")

        # 生成模拟信号（简化版）
        signals = []
        for i in range(10, min(len(df), 100), 20):  # 简单的固定间隔信号
            if i < len(df):
                signals.append({
                    'trade_date': df.iloc[i]['trade_date'] if 'trade_date' in df.columns else str(i),
                    'ts_code': '000001.SZ',
                    'signal': 1
                })

        signals_df = pd.DataFrame(signals) if signals else None

        # 创建回测引擎
        engine = create_default_engine()

        print(f"  - 模拟信号数: {len(signals)}")

        # 运行回测
        result = engine.run_backtest(
            price_data=df,
            signals=signals_df,
            start_date=df.iloc[0]['trade_date'] if 'trade_date' in df.columns else None,
            end_date=df.iloc[-1]['trade_date'] if 'trade_date' in df.columns else None
        )

        print(f"\n✓ 回测运行成功!")
        print(f"\n回测结果:")
        print(f"  - 总交易次数: {len(result.trades)}")
        print(f"  - 初始资金: {result.config.initial_capital:,.0f}")

        if result.metrics:
            print(f"\n绩效指标:")
            print(f"  - 总收益率: {result.metrics.get('total_return', 0):.2%}")
            print(f"  - 年化收益率: {result.metrics.get('annual_return', 0):.2%}")
            print(f"  - 最大回撤: {result.metrics.get('max_drawdown', 0):.2%}")
            print(f"  - 夏普比率: {result.metrics.get('sharpe_ratio', 0):.2f}")

        return result

    except Exception as e:
        print(f"✗ 回测测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("系统历史数据与回测能力检查")
    print("=" * 60)

    # 1. 检查Tushare数据获取
    df = check_tushare_data()

    # 2. 检查筹码分布计算
    chip_data = check_chip_data(df)

    # 3. 测试回测能力
    backtest_result = test_backtest_capability(df)

    # 总结
    print("\n" + "=" * 60)
    print("能力评估总结")
    print("=" * 60)

    has_data = df is not None and (not hasattr(df, 'empty') or not df.empty)

    capabilities = {
        'Tushare数据获取': has_data,
        '筹码分布计算': chip_data is not None,
        '回测引擎': backtest_result is not None
    }

    for capability, available in capabilities.items():
        status = "✓ 具备" if available else "✗ 不足"
        print(f"{capability}: {status}")

    if all(capabilities.values()):
        print("\n🎉 系统具备完整的历史数据验证测试能力!")
        print("\n下一步建议:")
        print("1. 使用真实历史数据对筹码分布策略进行回测验证")
        print("2. 选取多只股票进行测试")
        print("3. 验证不同市场周期（牛市/熊市/震荡市）的表现")
        print("4. 根据回测结果优化策略参数")
    else:
        print("\n⚠️ 部分能力不足:")
        if not has_data:
            print("- 需要确保Tushare API正常工作")
            print("- 或者准备本地历史数据文件")


if __name__ == '__main__':
    main()
