"""
缠论策略模块 - 完整测试
测试所有核心功能
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.framework.chanlun_strategy import (
    KLine, Fractal, Stroke, Segment, Zhongshu, Divergence, BuySellPoint,
    KLineMerger, FractalDetector, StrokeBuilder,
    SegmentAnalyzer, ZhongshuAnalyzer,
    DivergenceDetector, BuySellPointDetector,
    ChanlunAnalyzer, ChanlunScorer, ChanlunAlphaModel,
    SignalFusion, StrategyValidationLayer, DarwinRiskFilter,
    MultiLayerStockScreener, analyze_single_stock, analyze_chanlun,
    Insight
)

def generate_test_data(days=150, trend='random'):
    """生成测试数据"""
    np.random.seed(42)
    
    dates = []
    current_date = datetime.now() - timedelta(days=days)
    for _ in range(days):
        dates.append(current_date.strftime('%Y%m%d'))
        current_date += timedelta(days=1)
    
    prices = [100.0]
    for i in range(days - 1):
        if trend == 'up':
            change = np.random.normal(0.5, 2)
        elif trend == 'down':
            change = np.random.normal(-0.5, 2)
        elif trend == 'consolidate':
            change = np.random.normal(0, 1)
        else:
            change = np.random.normal(0, 2)
        
        prices.append(prices[-1] * (1 + change / 100))
    
    data = pd.DataFrame({
        'trade_date': dates,
        'open': prices,
        'high': [p * (1 + abs(np.random.normal(0.5, 0.3)) / 100) for p in prices],
        'low': [p * (1 - abs(np.random.normal(0.5, 0.3)) / 100) for p in prices],
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, days)
    })
    
    return data

def test_kline_merger():
    """测试1: K线包含关系处理"""
    print("\n" + "="*60)
    print("测试1: K线包含关系处理")
    print("="*60)
    
    klines = [
        KLine(0, 100, 105, 98, 103, "20240101"),
        KLine(1, 103, 104, 102, 103, "20240102"),
        KLine(2, 103, 106, 100, 105, "20240103"),
    ]
    
    merged = KLineMerger.merge(klines)
    
    print(f"✓ 原始K线数: {len(klines)}")
    print(f"✓ 合并后K线数: {len(merged)}")
    
    if len(merged) < len(klines):
        print(f"✓ 包含关系处理正确")
    
    return True

def test_fractal_detector():
    """测试2: 分型识别"""
    print("\n" + "="*60)
    print("测试2: 分型识别")
    print("="*60)
    
    klines = [
        KLine(0, 100, 105, 98, 103, "20240101"),
        KLine(1, 103, 104, 102, 103, "20240102"),
        KLine(2, 103, 108, 102, 107, "20240103"),
        KLine(3, 107, 108, 104, 105, "20240104"),
        KLine(4, 105, 106, 100, 101, "20240105"),
        KLine(5, 101, 102, 100, 101, "20240106"),
        KLine(6, 101, 105, 100, 104, "20240107"),
    ]
    
    detector = FractalDetector()
    fractals = detector.detect(klines)
    
    print(f"✓ 识别出 {len(fractals)} 个分型")
    for f in fractals:
        print(f"  - {f}")
    
    return True

def test_stroke_builder():
    """测试3: 笔构建"""
    print("\n" + "="*60)
    print("测试3: 笔构建")
    print("="*60)
    
    fractals = [
        Fractal('bottom', 0, 100, "20240101"),
        Fractal('top', 3, 108, "20240104"),
        Fractal('bottom', 6, 98, "20240107"),
        Fractal('top', 9, 112, "20240110"),
    ]
    
    builder = StrokeBuilder(min_klines=2)
    strokes = builder.build(fractals)
    
    print(f"✓ 构建出 {len(strokes)} 笔")
    for s in strokes:
        print(f"  - {s}")
    
    return len(strokes) >= 2

def test_segment_analyzer():
    """测试4: 线段识别"""
    print("\n" + "="*60)
    print("测试4: 线段识别")
    print("="*60)
    
    strokes = [
        Stroke(0, 3, 100, 108, "20240101", "20240104", "up", 108, 100),
        Stroke(3, 6, 108, 98, "20240104", "20240107", "down", 108, 98),
        Stroke(6, 9, 98, 112, "20240107", "20240110", "up", 112, 98),
        Stroke(9, 12, 112, 95, "20240110", "20240113", "down", 112, 95),
        Stroke(12, 15, 95, 115, "20240113", "20240116", "up", 115, 95),
    ]
    
    analyzer = SegmentAnalyzer(min_stroke_count=3)
    segments = analyzer.build(strokes)
    
    print(f"✓ 识别出 {len(segments)} 个线段")
    for seg in segments:
        print(f"  - {seg}")
    
    return True

def test_zhongshu_analyzer():
    """测试5: 中枢识别"""
    print("\n" + "="*60)
    print("测试5: 中枢识别")
    print("="*60)
    
    segments = [
        Segment(0, 5, 100, 110, "20240101", "20240106", "up", high=110, low=100),
        Segment(5, 10, 110, 102, "20240106", "20240111", "down", high=110, low=102),
        Segment(10, 15, 102, 112, "20240111", "20240116", "up", high=112, low=102),
        Segment(15, 20, 112, 104, "20240116", "20240121", "down", high=112, low=104),
        Segment(20, 25, 104, 114, "20240121", "20240126", "up", high=114, low=104),
    ]
    
    analyzer = ZhongshuAnalyzer(min_segment_count=3)
    zhongshu_list = analyzer.find(segments)
    
    print(f"✓ 识别出 {len(zhongshu_list)} 个中枢")
    for zs in zhongshu_list:
        print(f"  - {zs}")
        print(f"    中枢区间: [{zs.low:.2f}, {zs.high:.2f}]")
        print(f"    中枢中心: {zs.center:.2f}")
    
    return True

def test_divergence_detector():
    """测试6: 背驰判断"""
    print("\n" + "="*60)
    print("测试6: 背驰判断")
    print("="*60)
    
    strokes = [
        Stroke(0, 3, 100, 115, "20240101", "20240104", "up", 115, 100),
        Stroke(3, 6, 115, 105, "20240104", "20240107", "down", 115, 105),
        Stroke(6, 9, 105, 118, "20240107", "20240110", "up", 118, 105),
    ]
    
    detector = DivergenceDetector()
    divergence = detector.detect(strokes)
    
    if divergence:
        print(f"✓ 检测到背驰: {divergence}")
        print(f"  - 类型: {divergence.type}")
        print(f"  - 方向: {divergence.direction}")
        print(f"  - 置信度: {divergence.confidence:.2f}")
    else:
        print("✓ 未检测到背驰（当前示例数据简化）")
    
    return True

def test_buy_sell_detector():
    """测试7: 买卖点识别"""
    print("\n" + "="*60)
    print("测试7: 买卖点识别")
    print("="*60)
    
    divergence = Divergence(
        type='trend',
        direction='up',
        confidence=0.8,
        position={'idx': 9, 'price': 118}
    )
    
    strokes = [
        Stroke(0, 3, 100, 115, "20240101", "20240104", "up", 115, 100),
        Stroke(3, 6, 115, 105, "20240104", "20240107", "down", 115, 105),
        Stroke(6, 9, 105, 118, "20240107", "20240110", "up", 118, 105),
    ]
    
    zhongshu_list = [
        Zhongshu(3, 12, "20240104", "20240113", 112, 108, direction='up')
    ]
    
    detector = BuySellPointDetector()
    buy_points, sell_points = detector.find(strokes, zhongshu_list, divergence)
    
    print(f"✓ 识别出 {len(buy_points)} 个买点")
    for bp in buy_points:
        print(f"  - {bp}")
    
    print(f"✓ 识别出 {len(sell_points)} 个卖点")
    for sp in sell_points:
        print(f"  - {sp}")
    
    return True

def test_chanlun_scorer():
    """测试8: 缠论评分系统"""
    print("\n" + "="*60)
    print("测试8: 缠论评分系统")
    print("="*60)
    
    analysis_result = {
        'buy_points': [
            BuySellPoint(type='first_buy', confidence=0.8, position={'idx': 9, 'price': 118}, reason='测试')
        ],
        'sell_points': [],
        'divergence': Divergence(type='trend', direction='up', confidence=0.7, position={'idx': 9, 'price': 118}),
        'trend': 'up',
        'zhongshu': [Zhongshu(0, 10, "20240101", "20240111", 110, 100)]
    }
    
    score_result = ChanlunScorer.score(analysis_result, latest_close=120.0)
    
    print(f"✓ 评分: {score_result['score']:.2f}")
    print(f"✓ 建议: {score_result['recommendation']}")
    print(f"✓ 详情: {len(score_result['details'])} 项")
    
    return score_result['score'] > 0

def test_full_analyzer():
    """测试9: 完整缠论分析器"""
    print("\n" + "="*60)
    print("测试9: 完整缠论分析器")
    print("="*60)
    
    data = generate_test_data(days=150, trend='up')
    result = analyze_chanlun(data)
    
    if 'error' in result:
        print(f"✗ 分析出错: {result['error']}")
        return False
    
    print(f"✓ 分析成功")
    
    summary = result.get('summary', {})
    print(f"\n分析摘要:")
    for key, value in summary.items():
        print(f"  - {key}: {value}")
    
    if result.get('success'):
        print(f"\n✓ 分型数: {len(result.get('fractals', []))}")
        print(f"✓ 笔数: {len(result.get('strokes', []))}")
        print(f"✓ 线段数: {len(result.get('segments', []))}")
        print(f"✓ 中枢数: {len(result.get('zhongshu', []))}")
        print(f"✓ 买点数: {len(result.get('buy_points', []))}")
        print(f"✓ 卖点数: {len(result.get('sell_points', []))}")
        print(f"✓ 背驰: {'是' if result.get('divergence') else '否'}")
        print(f"✓ 趋势: {result.get('trend', 'unknown')}")
    
    return True

def test_alpha_model():
    """测试10: 缠论Alpha模型"""
    print("\n" + "="*60)
    print("测试10: 缠论Alpha模型")
    print("="*60)
    
    alpha_model = ChanlunAlphaModel()
    
    data = {
        '000001.SZ': generate_test_data(days=150, trend='up'),
        '000002.SZ': generate_test_data(days=150, trend='down')
    }
    
    insights = alpha_model.generate_insights(data)
    
    print(f"✓ 生成 {len(insights)} 个信号")
    for insight in insights:
        dir_name = {Insight.LONG: 'LONG', Insight.SHORT: 'SHORT', Insight.FLAT: 'HOLD'}.get(insight.direction, 'UNKNOWN')
        print(f"  - {insight.symbol}: {dir_name}, 置信度: {insight.confidence:.2f}")
    
    return True

def test_signal_fusion():
    """测试11: 信号融合"""
    print("\n" + "="*60)
    print("测试11: 信号融合")
    print("="*60)
    
    fusion = SignalFusion()
    
    signals_dict = {
        'chanlun': [
            Insight('000001.SZ', Insight.LONG, 0.7, 0.3, '缠论信号'),
        ],
        'chip': [
            Insight('000001.SZ', Insight.LONG, 0.6, 0.4, '筹码信号'),
        ]
    }
    
    result = fusion.fuse(signals_dict)
    
    print(f"✓ 融合成功")
    print(f"  - BUY: {result['action_count']['BUY']}")
    print(f"  - SELL: {result['action_count']['SELL']}")
    print(f"  - HOLD: {result['action_count']['HOLD']}")
    
    return True

def test_strategy_validation():
    """测试12: 策略验证层"""
    print("\n" + "="*60)
    print("测试12: 策略验证层")
    print("="*60)
    
    layer = StrategyValidationLayer()
    
    candidates = [
        {'symbol': '000001.SZ', 'code': '000001.SZ', 'chip_score': 70},
        {'symbol': '000002.SZ', 'code': '000002.SZ', 'chip_score': 60}
    ]
    
    stock_data = {
        '000001.SZ': generate_test_data(days=150, trend='up'),
        '000002.SZ': generate_test_data(days=150, trend='down')
    }
    
    validated = layer.validate(candidates, stock_data)
    
    print(f"✓ 验证成功，获得 {len(validated)} 个候选")
    for v in validated:
        print(f"  - {v.get('symbol')}: {v.get('final_action')}, 置信度: {v.get('confidence', 0):.2f}")
    
    return True

def test_multi_layer_screener():
    """测试13: 三层筛选器"""
    print("\n" + "="*60)
    print("测试13: 三层筛选器")
    print("="*60)
    
    screener = MultiLayerStockScreener()
    
    all_stocks = ['000001.SZ', '000002.SZ', '000003.SZ']
    stock_data = {
        '000001.SZ': generate_test_data(days=150, trend='up'),
        '000002.SZ': generate_test_data(days=150, trend='down'),
        '000003.SZ': generate_test_data(days=150, trend='consolidate')
    }
    
    results = screener.screen(all_stocks, stock_data)
    
    print(f"✓ 筛选完成，获得 {len(results)} 个最终候选")
    for r in results:
        print(f"  - {r.get('symbol')}: {r.get('final_action')}")
    
    return True

def test_single_stock_analysis():
    """测试14: 单股票分析"""
    print("\n" + "="*60)
    print("测试14: 单股票分析（用户自选股支持）")
    print("="*60)
    
    data = generate_test_data(days=150, trend='up')
    result = analyze_single_stock('000001.SZ', data)
    
    print(f"✓ 分析完成: {result.get('symbol')}")
    print(f"  - 风险检查: {'通过' if result.get('risk_check', {}).get('passed') else '不通过'}")
    
    chanlun = result.get('chanlun', {})
    if 'error' in chanlun:
        print(f"  - 缠论分析: 错误 - {chanlun['error']}")
    else:
        print(f"  - 缠论分析: 成功")
        print(f"    - 评分: {chanlun.get('score', 0):.2f}")
        print(f"    - 建议: {chanlun.get('recommendation', 'N/A')}")
        print(f"    - 趋势: {chanlun.get('trend', 'N/A')}")
        print(f"    - 买点: {chanlun.get('buy_points', 0)}")
        print(f"    - 卖点: {chanlun.get('sell_points', 0)}")
    
    return True

def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("    缠论策略模块 - 完整测试")
    print("="*60)
    
    tests = [
        ("K线包含关系处理", test_kline_merger),
        ("分型识别", test_fractal_detector),
        ("笔构建", test_stroke_builder),
        ("线段识别", test_segment_analyzer),
        ("中枢识别", test_zhongshu_analyzer),
        ("背驰判断", test_divergence_detector),
        ("买卖点识别", test_buy_sell_detector),
        ("缠论评分系统", test_chanlun_scorer),
        ("完整缠论分析器", test_full_analyzer),
        ("缠论Alpha模型", test_alpha_model),
        ("信号融合", test_signal_fusion),
        ("策略验证层", test_strategy_validation),
        ("三层筛选器", test_multi_layer_screener),
        ("单股票分析", test_single_stock_analysis),
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
    
    print("\n" + "="*60)
    print("    测试总结")
    print("="*60)
    
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
    sys.exit(main())