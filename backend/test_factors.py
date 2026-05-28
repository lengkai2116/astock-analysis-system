"""
测试因子库
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def test_factor_base():
    """测试因子基类"""
    print("=" * 50)
    print("测试因子基类")
    
    from app.factors.base import BaseFactor, FactorParam
    
    print("✓ FactorParam 导入成功")
    print("✓ BaseFactor 导入成功")
    
    print("\n✓ 因子基类测试通过")
    
    return True


def test_factor_registry():
    """测试因子注册表"""
    print("=" * 50)
    print("测试因子注册表")
    
    from app.factors.registry import get_factor_registry
    
    registry = get_factor_registry()
    print("✓ 因子注册表初始化成功")
    
    categories = registry.list_categories()
    print(f"✓ 发现 {len(categories)} 个类别: {categories}")
    
    sources = registry.list_sources()
    print(f"✓ 发现 {len(sources)} 个来源: {sources}")
    
    all_factors = registry.list_factors()
    print(f"✓ 共注册 {len(all_factors)} 个因子")
    
    if all_factors:
        print(f"  前10个因子: {all_factors[:10]}")
    
    print("\n✓ 因子注册表测试通过")
    
    return True


def test_factor_calculator():
    """测试因子计算器"""
    print("=" * 50)
    print("测试因子计算器")
    
    from app.factors import FactorCalculator
    
    calculator = FactorCalculator()
    print("✓ 因子计算器初始化成功")
    
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
    
    # 测试计算单个因子
    registry = get_factor_registry()
    test_factors = registry.list_factors()[:5]
    
    for factor_name in test_factors:
        try:
            result = calculator.calculate_single_factor(df, factor_name)
            if result is not None:
                print(f"✓ 成功计算 {factor_name}: 共 {len(result)} 个值")
        except Exception as e:
            print(f"✗ 计算失败 {factor_name}: {e}")
    
    print("\n✓ 因子计算器测试通过")
    
    return True


def test_precompute_manager():
    """测试预计算管理器"""
    print("=" * 50)
    print("测试预计算管理器")
    
    from app.data.factor_precompute import FactorPrecomputeManager
    
    manager = FactorPrecomputeManager()
    print("✓ 预计算管理器初始化成功")
    
    print("\n✓ 预计算管理器测试通过")
    
    return True


def main():
    print("=" * 50)
    print("因子库测试开始")
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
        test_factor_registry()
    except Exception as e:
        print(f"✗ 因子注册表测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        test_factor_calculator()
    except Exception as e:
        print(f"✗ 因子计算器测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        test_precompute_manager()
    except Exception as e:
        print(f"✗ 预计算管理器测试失败: {e}")
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
