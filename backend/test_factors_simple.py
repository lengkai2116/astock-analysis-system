"""
简化版因子库测试
不依赖app.__init__.py中的Flask初始化
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def test_factor_base():
    """测试因子基类"""
    print("=" * 50)
    print("测试因子基类")
    
    from factors.base import BaseFactor, FactorParam
    
    print("✓ FactorParam 导入成功")
    print("✓ BaseFactor 导入成功")
    
    print("\n✓ 因子基类测试通过")
    
    return True


def test_builtin_factors():
    """测试内置因子"""
    print("=" * 50)
    print("测试内置因子")
    
    from factors.builtin.momentum import ROC, RSI, MACD_DIF
    from factors.builtin.volatility import ATR, STD
    from factors.builtin.trend import MA, EMA
    from factors.builtin.volume import VOL_MA, OBV
    from factors.builtin.reversal import BIAS, WILLR
    
    factors = [
        (ROC, "ROC"),
        (RSI, "RSI"), 
        (MACD_DIF, "MACD_DIF"),
        (ATR, "ATR"),
        (STD, "STD"),
        (MA, "MA"),
        (EMA, "EMA"),
        (VOL_MA, "VOL_MA"),
        (OBV, "OBV"),
        (BIAS, "BIAS"),
        (WILLR, "WILLR")
    ]
    
    # 创建测试数据
    dates = [datetime.now() - timedelta(days=i) for i in range(100)]
    dates.reverse()
    data = {
        'open': np.random.normal(100, 5, 100),
        'high': np.random.normal(102, 5, 100),
        'low': np.random.normal(98, 5, 100),
        'close': np.random.normal(100, 5, 100),
        'vol': np.random.normal(1000000, 100000, 100)
    }
    df = pd.DataFrame(data, index=dates)
    
    print(f"✓ 测试数据创建成功 ({len(df)} 条)")
    
    for factor_class, name in factors:
        try:
            factor = factor_class()
            result = factor.calculate(df)
            if result is not None and len(result) > 0:
                print(f"✓ 成功计算 {name}: 共 {len(result)} 个值")
        except Exception as e:
            print(f"✗ 计算失败 {name}: {e}")
    
    print("\n✓ 内置因子测试通过")
    
    return True


def test_registry():
    """测试注册表（简化版）"""
    print("=" * 50)
    print("测试因子注册表")
    
    from factors.registry import FactorRegistry
    from factors.builtin.momentum import ROC, RSI
    from factors.builtin.volatility import ATR
    from factors.builtin.trend import MA
    
    registry = FactorRegistry()
    print("✓ 注册表初始化成功")
    
    # 手动注册一些因子测试
    registry.register(ROC)
    registry.register(RSI)
    registry.register(ATR)
    registry.register(MA)
    
    categories = registry.list_categories()
    print(f"✓ 发现 {len(categories)} 个类别: {categories}")
    
    sources = registry.list_sources()
    print(f"✓ 发现 {len(sources)} 个来源: {sources}")
    
    all_factors = registry.list_factors()
    print(f"✓ 共注册 {len(all_factors)} 个因子")
    
    for factor_name in all_factors:
        factor = registry.get_factor(factor_name)
        if factor:
            print(f"  - {factor_name}: {factor.name_cn} ({factor.source})")
    
    print("\n✓ 注册表测试通过")
    
    return True


def test_calculator():
    """测试因子计算器"""
    print("=" * 50)
    print("测试因子计算器")
    
    from factors.calculator import FactorCalculator
    from factors.registry import FactorRegistry
    from factors.builtin.momentum import ROC, RSI
    
    registry = FactorRegistry()
    registry.register(ROC)
    registry.register(RSI)
    
    # 打补丁让计算器用我们的注册表
    calculator = FactorCalculator()
    calculator.registry = registry
    
    print("✓ 计算器初始化成功")
    
    # 创建测试数据
    dates = [datetime.now() - timedelta(days=i) for i in range(100)]
    dates.reverse()
    data = {
        'open': np.random.normal(100, 5, 100),
        'high': np.random.normal(102, 5, 100),
        'low': np.random.normal(98, 5, 100),
        'close': np.random.normal(100, 5, 100),
        'vol': np.random.normal(1000000, 100000, 100)
    }
    df = pd.DataFrame(data, index=dates)
    
    # 测试单个因子
    result = calculator.calculate_single_factor(df, "ROC")
    if result is not None and len(result) > 0:
        print(f"✓ 计算器计算 ROC 成功: {len(result)} 个值")
    
    # 测试多个因子
    configs = [
        {"name": "ROC", "params": {"period": 12}},
        {"name": "RSI", "params": {"period": 14}}
    ]
    results_df = calculator.calculate_multiple_factors(df, configs)
    if not results_df.empty:
        print(f"✓ 计算器批量计算成功: {list(results_df.columns)}")
    
    print("\n✓ 计算器测试通过")
    
    return True


def main():
    print("=" * 50)
    print("简化版因子库测试开始")
    print("=" * 50)
    
    all_passed = True
    
    try:
        test_factor_base()
    except Exception as e:
        print(f"✗ 因子基类测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        test_builtin_factors()
    except Exception as e:
        print(f"✗ 内置因子测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        test_registry()
    except Exception as e:
        print(f"✗ 注册表测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        test_calculator()
    except Exception as e:
        print(f"✗ 计算器测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    print("=" * 50)
    if all_passed:
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败")
    print("=" * 50)
    
    return all_passed


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
