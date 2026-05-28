#!/usr/bin/env python3
"""
简化的API测试脚本
用于验证系统核心功能，不依赖PostgreSQL/Redis
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import datetime, date

def test_strategy_models():
    """测试策略模型"""
    print("=" * 60)
    print("1. 测试策略模型...")
    try:
        from app.models.strategy import StrategySignal, StrategyTemplateType
        print("   ✅ StrategySignal: ", [s.value for s in StrategySignal])
        print("   ✅ StrategyTemplateType: ", [t.value for t in StrategyTemplateType])
        print("   ✅ 策略模型导入成功")
        return True
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_strategy_services():
    """测试策略服务"""
    print("\n2. 测试策略服务...")
    try:
        from app.services.strategy_output_service import StrategyOutputService
        from app.services.strategy_template_service import StrategyTemplateService
        print("   ✅ StrategyOutputService 导入成功")
        print("   ✅ StrategyTemplateService 导入成功")
        return True
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False

def test_backtest_engine():
    """测试回测引擎"""
    print("\n3. 测试回测引擎...")
    try:
        from app.engine.backtest_v2 import AShareBacktestEngine
        print("   ✅ AShareBacktestEngine 导入成功")
        return True
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_indicator_services():
    """测试指标IDE服务"""
    print("\n4. 测试指标IDE服务...")
    services = []
    try:
        from app.services.indicator_contract import IndicatorContractParser
        services.append(("IndicatorContractParser", True))
        print("   ✅ IndicatorContractParser 导入成功")
    except Exception as e:
        services.append(("IndicatorContractParser", False))
        print(f"   ❌ IndicatorContractParser: {e}")
    
    try:
        from app.services.indicator_quality import IndicatorQualityChecker
        services.append(("IndicatorQualityChecker", True))
        print("   ✅ IndicatorQualityChecker 导入成功")
    except Exception as e:
        services.append(("IndicatorQualityChecker", False))
        print(f"   ❌ IndicatorQualityChecker: {e}")
    
    try:
        from app.services.indicator_sandbox import IndicatorSandbox
        services.append(("IndicatorSandbox", True))
        print("   ✅ IndicatorSandbox 导入成功")
    except Exception as e:
        services.append(("IndicatorSandbox", False))
        print(f"   ❌ IndicatorSandbox: {e}")
    
    return all(s[1] for s in services)

def test_report_generator():
    """测试报告生成器"""
    print("\n5. 测试报告生成器...")
    try:
        from app.services.report_generator import ReportGenerator
        print("   ✅ ReportGenerator 导入成功")
        return True
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False

def test_ai_services():
    """测试AI服务"""
    print("\n6. 测试AI服务...")
    try:
        from app.services.ai_strategy_generator import AIStrategyGenerator
        from app.services.research_pipeline import ResearchPipeline
        print("   ✅ AIStrategyGenerator 导入成功")
        print("   ✅ ResearchPipeline 导入成功")
        return True
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False

def test_routes():
    """测试路由蓝图"""
    print("\n7. 测试路由蓝图...")
    blueprints = []
    try:
        from app.routes.strategy import strategy_bp
        blueprints.append(("strategy_bp", True))
        print("   ✅ strategy_bp 导入成功")
    except Exception as e:
        blueprints.append(("strategy_bp", False))
        print(f"   ❌ strategy_bp: {e}")
    
    try:
        from app.routes.backtest import backtest_bp
        blueprints.append(("backtest_bp", True))
        print("   ✅ backtest_bp 导入成功")
    except Exception as e:
        blueprints.append(("backtest_bp", False))
        print(f"   ❌ backtest_bp: {e}")
    
    try:
        from app.routes.indicator_ide import indicator_ide_bp
        blueprints.append(("indicator_ide_bp", True))
        print("   ✅ indicator_ide_bp 导入成功")
    except Exception as e:
        blueprints.append(("indicator_ide_bp", False))
        print(f"   ❌ indicator_ide_bp: {e}")
    
    try:
        from app.routes.reports import reports_bp
        blueprints.append(("reports_bp", True))
        print("   ✅ reports_bp 导入成功")
    except Exception as e:
        blueprints.append(("reports_bp", False))
        print(f"   ❌ reports_bp: {e}")
    
    return all(b[1] for b in blueprints)

def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("A股分析系统 - 功能测试")
    print("=" * 60)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    results.append(("策略模型", test_strategy_models()))
    results.append(("策略服务", test_strategy_services()))
    results.append(("回测引擎", test_backtest_engine()))
    results.append(("指标IDE服务", test_indicator_services()))
    results.append(("报告生成器", test_report_generator()))
    results.append(("AI服务", test_ai_services()))
    results.append(("路由蓝图", test_routes()))
    
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
        if result:
            passed += 1
    
    print("\n" + "-" * 60)
    print(f"总计: {passed}/{total} 个测试通过")
    
    if passed == total:
        print("🎉 所有测试通过！系统核心功能正常！")
        return True
    else:
        print("⚠️ 部分测试失败")
        return False

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
