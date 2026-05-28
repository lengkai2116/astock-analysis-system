"""
框架模块测试
验证新增的量化框架功能正常工作
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_framework_import():
    """测试框架模块导入"""
    print("="*50)
    print("测试1: 框架模块导入")
    print("="*50)
    
    try:
        from app.engine.framework import (
            UniverseSelectionModel,
            AlphaModel,
            PortfolioConstructionModel,
            RiskManagementModel,
            ExecutionModel,
            Algorithm,
            Insight,
            EqualWeightPortfolioConstruction,
            StopLossRiskManagement
        )
        print("✓ 核心框架导入成功")
        
        from app.engine.framework.chip_strategy import (
            ChipUniverseSelectionModel,
            ChipAlphaModel,
            ChipScorer
        )
        print("✓ 筹码策略模块导入成功")
        
        from app.engine.framework.screener import (
            MultiLayerStockScreener,
            DarwinRiskFilter,
            SignalFusion
        )
        print("✓ 筛选器模块导入成功")
        
        from app.engine.framework.optimizer import (
            GridSearchOptimizer,
            RandomSearchOptimizer,
            ParameterSensitivityAnalysis
        )
        print("✓ 优化器模块导入成功")
        
        return True
    except Exception as e:
        print(f"✗ 导入失败: {e}")
        return False


def test_insight_creation():
    """测试Insight创建"""
    print("\n" + "="*50)
    print("测试2: Insight信号创建")
    print("="*50)
    
    try:
        from app.engine.framework import Insight
        
        insight = Insight(
            symbol='000001.SZ',
            direction=Insight.LONG,
            confidence=0.8,
            weight=0.7,
            reason='建仓期，筹码集中'
        )
        
        insight_dict = insight.to_dict()
        
        assert insight_dict['symbol'] == '000001.SZ'
        assert insight_dict['direction'] == 1
        assert insight_dict['confidence'] == 0.8
        
        print(f"✓ Insight创建成功")
        print(f"  - 股票: {insight_dict['symbol']}")
        print(f"  - 方向: {insight_dict['direction_name']}")
        print(f"  - 置信度: {insight_dict['confidence']}")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def generate_test_data(symbol='000001.SZ', days=100):
    """生成测试数据"""
    np.random.seed(42)
    
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    
    base_price = np.random.uniform(10, 20)
    prices = np.cumsum(np.random.normal(0, 0.02, days)) * base_price + base_price
    
    data = pd.DataFrame({
        'ts_code': [symbol] * days,
        'trade_date': dates.strftime('%Y%m%d'),
        'open': prices * np.random.normal(1, 0.01, days),
        'high': prices * np.random.normal(1.02, 0.01, days),
        'low': prices * np.random.normal(0.98, 0.01, days),
        'close': prices,
        'vol': np.random.randint(1000000, 10000000, days),
        'amount': np.random.randint(100000000, 1000000000, days)
    })
    
    return data


def test_chip_scorer():
    """测试筹码评分器"""
    print("\n" + "="*50)
    print("测试3: 筹码评分器")
    print("="*50)
    
    try:
        from app.engine.framework.chip_strategy import ChipScorer
        
        scorer = ChipScorer()
        data = generate_test_data()
        
        print(f"✓ 创建评分器成功")
        print(f"  - 测试数据: {len(data)} 条")
        
        score = scorer.score(data)
        
        print(f"✓ 评分计算成功")
        print(f"  - 综合评分: {score:.4f}")
        print(f"  - 评分有效: {score >= 0}")
        
        return score >= 0
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_signal_fusion():
    """测试信号融合"""
    print("\n" + "="*50)
    print("测试4: 多策略信号融合")
    print("="*50)
    
    try:
        from app.engine.framework.screener import SignalFusion
        
        fusion = SignalFusion({
            'chip': 0.4,
            'chanlun': 0.3,
            'factor': 0.3
        })
        
        # 测试买入信号
        signals_buy = {'chip': 1, 'chanlun': 0.8, 'factor': 0.5}
        result_buy = fusion.fuse(signals_buy)
        
        print(f"✓ 买入信号融合测试:")
        print(f"  - 输入: {signals_buy}")
        print(f"  - 结果: {result_buy['action']}, 评分: {result_buy['score']:.3f}")
        
        # 测试卖出信号
        signals_sell = {'chip': -1, 'chanlun': -0.8, 'factor': -0.5}
        result_sell = fusion.fuse(signals_sell)
        
        print(f"✓ 卖出信号融合测试:")
        print(f"  - 输入: {signals_sell}")
        print(f"  - 结果: {result_sell['action']}, 评分: {result_sell['score']:.3f}")
        
        # 测试观望信号
        signals_hold = {'chip': 0, 'chanlun': 0, 'factor': 0}
        result_hold = fusion.fuse(signals_hold)
        
        print(f"✓ 观望信号融合测试:")
        print(f"  - 输入: {signals_hold}")
        print(f"  - 结果: {result_hold['action']}")
        
        assert result_buy['action'] == 'BUY'
        assert result_sell['action'] == 'SELL'
        assert result_hold['action'] == 'HOLD'
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_optimizer():
    """测试优化器"""
    print("\n" + "="*50)
    print("测试5: 参数优化器")
    print("="*50)
    
    try:
        from app.engine.framework.optimizer import (
            GridSearchOptimizer,
            RandomSearchOptimizer,
            ParameterSensitivityAnalysis
        )
        
        # 定义参数空间
        param_space = {
            'lookback_period': [60, 90, 120],
            'rsi_lower': [20, 30],
            'rsi_upper': [70, 80]
        }
        
        # 测试网格搜索
        print("\n--- 测试网格搜索 ---")
        grid_optimizer = GridSearchOptimizer(param_space)
        
        # 简单的目标函数
        def objective(params):
            score = 0.5
            if params.get('lookback_period', 120) > 90:
                score += 0.1
            if params.get('rsi_upper', 70) < 80:
                score += 0.05
            return score + np.random.normal(0, 0.05)
        
        grid_result = grid_optimizer.optimize(objective, max_iterations=5)
        
        print(f"✓ 网格搜索完成")
        print(f"  - 最佳参数: {grid_result['best_params']}")
        print(f"  - 最佳评分: {grid_result['best_score']:.4f}")
        
        # 测试随机搜索
        print("\n--- 测试随机搜索 ---")
        random_optimizer = RandomSearchOptimizer(param_space, seed=42)
        random_result = random_optimizer.optimize(objective, max_iterations=10)
        
        print(f"✓ 随机搜索完成")
        print(f"  - 最佳参数: {random_result['best_params']}")
        print(f"  - 最佳评分: {random_result['best_score']:.4f}")
        
        # 测试敏感性分析
        print("\n--- 测试敏感性分析 ---")
        analysis = ParameterSensitivityAnalysis(random_optimizer)
        sensitivity = analysis.analyze()
        
        if sensitivity:
            print(f"✓ 敏感性分析完成")
            print(f"  - 参数敏感性排序: {sensitivity.get('sorted_params', [])}")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multi_layer_screener():
    """测试多层筛选器"""
    print("\n" + "="*50)
    print("测试6: 多层股票筛选器")
    print("="*50)
    
    try:
        from app.engine.framework.screener import (
            MultiLayerStockScreener,
            DarwinRiskFilter
        )
        
        # 创建测试数据
        test_stocks = ['000001.SZ', '000002.SZ', '600000.SH', '600036.SH']
        test_data = {}
        for stock in test_stocks:
            test_data[stock] = generate_test_data(stock)
        
        print(f"✓ 创建测试数据: {len(test_stocks)} 只股票")
        
        # 测试风险过滤
        risk_filter = DarwinRiskFilter()
        filtered = risk_filter.filter(test_stocks, test_data)
        
        print(f"✓ 风险过滤完成: {len(filtered)}/{len(test_stocks)} 只股票通过")
        
        # 测试完整筛选器
        screener = MultiLayerStockScreener()
        results = screener.screen(test_stocks, test_data)
        
        print(f"✓ 多层筛选完成")
        print(f"  - 筛选结果: {len(results)} 只股票")
        for i, res in enumerate(results[:3]):
            print(f"  #{i+1}: {res['symbol']}, 评分: {res.get('score', 0):.3f}")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_algorithm_framework():
    """测试完整算法框架"""
    print("\n" + "="*50)
    print("测试7: 完整算法框架")
    print("="*50)
    
    try:
        from app.engine.framework import (
            Algorithm,
            EqualWeightPortfolioConstruction,
            StopLossRiskManagement
        )
        from app.engine.framework.chip_strategy import (
            ChipUniverseSelectionModel,
            ChipAlphaModel
        )
        
        # 创建算法实例
        algorithm = Algorithm(name='ChipStrategy')
        
        # 设置各模块
        algorithm.set_universe_selection(ChipUniverseSelectionModel(top_n=20))
        algorithm.set_alpha(ChipAlphaModel())
        algorithm.set_portfolio_construction(EqualWeightPortfolioConstruction())
        algorithm.set_risk_management(StopLossRiskManagement())
        
        print("✓ 算法框架配置完成")
        print(f"  - 算法名称: {algorithm.name}")
        
        # 初始化
        algorithm.initialize()
        print("✓ 算法初始化成功")
        
        # 生成测试数据
        test_data = {}
        for symbol in ['000001.SZ', '600000.SH']:
            test_data[symbol] = generate_test_data(symbol)
        
        # 测试数据处理
        now = datetime.now()
        insights, orders = algorithm.on_data(now, test_data)
        
        print(f"✓ 数据处理成功")
        print(f"  - 生成洞察: {len(insights)} 个")
        print(f"  - 生成订单: {len(orders)} 个")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("\n" + "="*50)
    print("量化框架升级测试")
    print("="*50)
    
    tests = [
        ("框架导入", test_framework_import),
        ("Insight创建", test_insight_creation),
        ("筹码评分器", test_chip_scorer),
        ("信号融合", test_signal_fusion),
        ("参数优化器", test_optimizer),
        ("多层筛选器", test_multi_layer_screener),
        ("算法框架", test_algorithm_framework)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ 测试 {name} 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # 总结
    print("\n" + "="*50)
    print("测试总结")
    print("="*50)
    
    passed = sum(1 for _, res in results if res)
    total = len(results)
    
    for name, res in results:
        status = "✓ 通过" if res else "✗ 失败"
        print(f"  {name}: {status}")
    
    print(f"\n总测试: {total}/{passed} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)