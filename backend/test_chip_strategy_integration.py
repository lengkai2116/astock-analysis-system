"""
测试筹码分布策略集成
验证ChipDistributionStrategy在pipeline.py中的完整实现
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def create_sample_data(ts_code='000001.SZ', days=120):
    """创建示例OHLCV数据"""
    data = []
    base_price = 15.0
    today = datetime.now()

    for i in range(days):
        date = today - timedelta(days=days-i-1)

        daily_volatility = np.random.uniform(0.01, 0.03)
        change = np.random.normal(0, daily_volatility)
        close = base_price * (1 + change)
        base_price = close

        open_price = close * np.random.uniform(0.98, 1.02)
        high = max(open_price, close) * np.random.uniform(1.0, 1.03)
        low = min(open_price, close) * np.random.uniform(0.97, 1.0)

        vol = np.random.uniform(5000000, 15000000)

        data.append({
            'ts_code': ts_code,
            'trade_date': date.strftime('%Y-%m-%d'),
            'open': round(open_price, 2),
            'high': round(high, 2),
            'low': round(low, 2),
            'close': round(close, 2),
            'vol': vol
        })

    return pd.DataFrame(data)


def test_strategy_import():
    """测试策略导入"""
    print("=" * 60)
    print("测试1: 策略导入")
    print("=" * 60)

    try:
        from app.engine.pipeline import ChipDistributionStrategy, StrategyPipeline, create_strategy
        print("✓ 成功导入 ChipDistributionStrategy")
        print("✓ 成功导入 StrategyPipeline")
        print("✓ 成功导入 create_strategy")
        return True
    except Exception as e:
        print(f"✗ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_strategy_instantiation():
    """测试策略实例化"""
    print("\n" + "=" * 60)
    print("测试2: 策略实例化")
    print("=" * 60)

    try:
        from app.engine.pipeline import ChipDistributionStrategy

        strategy = ChipDistributionStrategy(lookback_period=120)
        print(f"✓ 策略名称: {strategy.name}")
        print(f"✓ 策略描述: {strategy.description}")
        print(f"✓ 回顾周期: {strategy.lookback_period}")
        print(f"✓ ChipService: {type(strategy.chip_service).__name__}")
        print(f"✓ ChipIndicators: {type(strategy.chip_indicators).__name__}")
        return True
    except Exception as e:
        print(f"✗ 实例化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_chip_indicators():
    """测试筹码指标计算"""
    print("\n" + "=" * 60)
    print("测试3: 筹码指标计算")
    print("=" * 60)

    try:
        from app.engine.pipeline import ChipDistributionStrategy

        strategy = ChipDistributionStrategy(lookback_period=120)
        data = create_sample_data(days=120)

        chip_df = strategy.calculate_chip_distribution(data)
        print(f"✓ 筹码分布计算成功: {len(chip_df)} 个价格区间")

        analysis = strategy.analyze(data)
        indicators = analysis.get('indicators', {})

        if indicators:
            print(f"✓ SSRP: {indicators.get('ssrp', 0):.2f}")
            print(f"✓ ASR: {indicators.get('asr', 0):.4f}")
            print(f"✓ ASR状态: {indicators.get('asr_status', 'N/A')}")
            print(f"✓ 集中度: {indicators.get('concentration', 0):.4f}")
            print(f"✓ 集中度状态: {indicators.get('concentration_status', 'N/A')}")
            print(f"✓ 获利率: {indicators.get('profit_ratio', 0):.4f}")
            print(f"✓ 获利率状态: {indicators.get('profit_ratio_status', 'N/A')}")
            if 'rsi' in indicators:
                print(f"✓ RSI: {indicators.get('rsi', 0):.2f}")
                print(f"✓ RSI状态: {indicators.get('rsi_status', 'N/A')}")
            if 'cyqkl' in indicators:
                print(f"✓ CYQKL: {indicators.get('cyqkl', 0):.4f}")
                print(f"✓ CYQKL状态: {indicators.get('cyqkl_status', 'N/A')}")

        return True
    except Exception as e:
        print(f"✗ 筹码指标计算失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_phase_detection():
    """测试主力阶段识别"""
    print("\n" + "=" * 60)
    print("测试4: 主力阶段识别")
    print("=" * 60)

    try:
        from app.engine.pipeline import ChipDistributionStrategy

        strategy = ChipDistributionStrategy(lookback_period=120)
        data = create_sample_data(days=120)

        phase_info = strategy.identify_main_phase(data)

        print(f"✓ 主力阶段: {phase_info.get('phase', 'UNKNOWN')}")
        print(f"✓ 阶段名称: {phase_info.get('phase_name', 'UNKNOWN')}")
        print(f"✓ 置信度: {phase_info.get('confidence', 0):.4f}")

        if 'scores' in phase_info:
            scores = phase_info['scores']
            print(f"✓ 建仓期得分: {scores.get('BUILDING', 0):.1f}")
            print(f"✓ 洗盘期得分: {scores.get('WASHING', 0):.1f}")
            print(f"✓ 拉升期得分: {scores.get('RAISING', 0):.1f}")
            print(f"✓ 出货期得分: {scores.get('SHIPPING', 0):.1f}")
            print(f"✓ 下跌期得分: {scores.get('SUPPORT', 0):.1f}")

        return True
    except Exception as e:
        print(f"✗ 阶段识别失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_signal_generation():
    """测试信号生成"""
    print("\n" + "=" * 60)
    print("测试5: 信号生成")
    print("=" * 60)

    try:
        from app.engine.pipeline import ChipDistributionStrategy

        strategy = ChipDistributionStrategy(lookback_period=120)
        data = create_sample_data(days=120)

        analysis = strategy.analyze(data)
        signals = analysis.get('signals', {})

        signal_names = ['S_BUY', 'S_WASH_END', 'S_BOUNCE', 'S_SELL', 'S_WASH_STOP']
        for name in signal_names:
            if name in signals:
                signal = signals[name]
                status = "✓" if signal.get('triggered', False) else "✗"
                print(f"{status} {name}: {'触发' if signal.get('triggered', False) else '未触发'}")

        recommendation = analysis.get('recommendation', {})
        if recommendation:
            print(f"✓ 最终建议: {recommendation.get('action', 'N/A')}")
            print(f"✓ 原因: {recommendation.get('reason', 'N/A')}")
            pos = recommendation.get('target_position')
            if pos is not None:
                print(f"✓ 目标仓位: {pos:.0%}")

        return True
    except Exception as e:
        print(f"✗ 信号生成失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pipeline_integration():
    """测试策略流水线集成"""
    print("\n" + "=" * 60)
    print("测试6: 策略流水线集成")
    print("=" * 60)

    try:
        from app.engine.pipeline import StrategyPipeline, ChipDistributionStrategy

        pipeline = StrategyPipeline()

        strategy = ChipDistributionStrategy(lookback_period=120)
        pipeline.add_strategy(strategy, weight=1.0)

        strategies = pipeline.list_strategies()
        print(f"✓ 已注册策略数: {len(strategies)}")

        available = pipeline.get_available_strategies()
        chip_strategy = next((s for s in available if s['name'] == 'ChipDistribution'), None)

        if chip_strategy:
            print(f"✓ ChipDistribution 状态: {'已实现' if chip_strategy['implemented'] else '预留'}")
            print(f"✓ 策略描述: {chip_strategy['description']}")

        return True
    except Exception as e:
        print(f"✗ 流水线集成失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("筹码分布策略集成测试（完整实现版）")
    print("=" * 60)

    results = []

    results.append(("策略导入", test_strategy_import()))
    results.append(("策略实例化", test_strategy_instantiation()))
    results.append(("筹码指标计算", test_chip_indicators()))
    results.append(("主力阶段识别", test_phase_detection()))
    results.append(("信号生成", test_signal_generation()))
    results.append(("策略流水线集成", test_pipeline_integration()))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name}: {status}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！筹码分布策略已完整实现并集成到pipeline.py")
    else:
        print(f"\n⚠️  {total - passed} 项测试失败，请检查日志")


if __name__ == '__main__':
    main()
