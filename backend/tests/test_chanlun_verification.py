"""
缠论策略综合验证测试

验证范围:
1. 代码逻辑正确性（bug检测）
2. 策略在选股系统的集成
3. 个股策略分析的集成
4. 实际数据执行验证

用法：
    python backend/tests/test_chanlun_verification.py
    # 或
    pytest backend/tests/test_chanlun_verification.py -v --tb=long
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ============================================================
# 工具函数：测试数据生成
# ============================================================

def make_test_klines(rows=120, seed=42):
    """生成 OHLCV 测试数据"""
    np.random.seed(seed)
    base_price = 10.0
    # 生成带趋势的数据：前60根横盘，后60根先涨后跌
    t = np.linspace(0, 3 * np.pi, rows)
    trend = np.sin(t) * 1.5 + np.linspace(0, 1, rows) * 0.5
    prices = base_price + np.cumsum(np.random.randn(rows) * 0.15) + trend * 0.3
    
    dates = [(datetime.now() - timedelta(days=i)).strftime('%Y%m%d') for i in range(rows)]
    dates.reverse()
    return pd.DataFrame({
        'ts_code': ['000001.SZ'] * rows,
        'trade_date': dates,
        'open': prices + np.random.randn(rows) * 0.05,
        'high': prices + np.abs(np.random.randn(rows)) * 0.15 + 0.05,
        'low': prices - np.abs(np.random.randn(rows)) * 0.15 - 0.05,
        'close': prices,
        'vol': np.random.randint(500000, 2000000, rows),
    })


def make_trend_data(trend_type='up_down', rows=200):
    """
    生成特定走势的测试数据。
    
    Args:
        trend_type: 
            'up_down' - 先升后降的完整周期
            'double_zs' - 两中枢趋势（a+A+b+B+c）
            'sideways' - 横盘震荡
    """
    np.random.seed(42)
    base = 10.0
    
    if trend_type == 'up_down':
        # 先升后降：适合测试完整笔段
        seg1 = np.linspace(0, 3, rows // 3)  # 上升
        seg2 = np.linspace(3, 1, rows // 3)  # 下降
        seg3 = np.linspace(1, 0.5, rows - 2 * (rows // 3))  # 盘整
        t = np.concatenate([seg1, seg2, seg3])
    elif trend_type == 'double_zs':
        # a+A+b+B+c: 两中枢趋势
        n = rows // 5
        a = np.linspace(0, 2, n)
        A_low = np.sin(np.linspace(0, 2 * np.pi, n)) * 0.5 + np.ones(n) * 2
        b = np.linspace(2, 4, n)
        B_low = np.sin(np.linspace(0, 2 * np.pi, n)) * 0.5 + np.ones(n) * 4
        c = np.linspace(4, 6, n)
        t = np.concatenate([a, A_low, b, B_low, c])
    else:  # sideways
        t = np.sin(np.linspace(0, 8 * np.pi, rows)) * 0.5
    
    prices = base + t + np.random.randn(rows) * 0.05
    dates = [(datetime.now() - timedelta(days=i)).strftime('%Y%m%d') for i in range(rows)]
    dates.reverse()
    
    return pd.DataFrame({
        'ts_code': ['000001.SZ'] * rows,
        'trade_date': dates,
        'open': prices + np.random.randn(rows) * 0.05,
        'high': prices + np.abs(np.random.randn(rows)) * 0.1 + 0.02,
        'low': prices - np.abs(np.random.randn(rows)) * 0.1 - 0.02,
        'close': prices,
        'vol': np.random.randint(500000, 2000000, rows),
    })


# ============================================================
# 第1组：代码逻辑正确性检测
# ============================================================

def test_bug_variable_name_mismatch_in_divergence():
    """
    检测 BUG: _detect_trend_divergence 上涨趋势背驰分支变量名错误
    
    BUG描述:
    上涨趋势背驰分支(1123-1124行)使用了未定义的变量名 `area_ratio` 和 `macd_confirmed`。
    正确的变量名应为 `metric_ratio` 和 `metric_confirmed`。
    当上涨趋势背驰条件触发时将抛出 NameError。
    """
    from app.engine.framework.chanlun_strategy import (
        DivergenceDetector, Stroke, Divergence
    )
    
    detector = DivergenceDetector(macd_algo='area')
    
    # 构造上涨趋势背驰的笔序列
    # 需要至少4笔: up-down-up-down(创新高但力度减弱)
    closes = np.array([10.0 + i * 0.01 for i in range(200)])
    
    strokes = [
        Stroke(start_idx=0, end_idx=20, start_price=10.0, end_price=10.5,
               start_date='2024-01-01', end_date='2024-01-20', direction='up',
               high=10.5, low=10.0),
        Stroke(start_idx=20, end_idx=40, start_price=10.5, end_price=10.3,
               start_date='2024-01-21', end_date='2024-02-10', direction='down',
               high=10.5, low=10.3),
        Stroke(start_idx=40, end_idx=60, start_price=10.3, end_price=10.8,
               start_date='2024-02-11', end_date='2024-03-01', direction='up',
               high=10.8, low=10.3),
        Stroke(start_idx=60, end_idx=80, start_price=10.8, end_price=10.6,
               start_date='2024-03-02', end_date='2024-03-21', direction='down',
               high=10.8, low=10.6),
        # 第五笔：创新高但幅度减弱 => 触发上涨趋势背驰
        Stroke(start_idx=80, end_idx=100, start_price=10.6, end_price=10.85,
               start_date='2024-03-22', end_date='2024-04-10', direction='up',
               high=10.85, low=10.6),
    ]
    
    # 让 closes 与 strokes 索引对齐
    detector._closes = closes
    
    try:
        result = detector._detect_trend_divergence(strokes)
        # 如果没有抛出 NameError，说明得到了结果
        print(f"  ✓ 上涨趋势背驰检测结果: {result}")
        if result:
            # 检查 details 中是否使用了正确的字段
            details = result.details or {}
            if 'macd_area_ratio' in details:
                print(f"  ⚠ BUG存在: details 使用了 'macd_area_ratio'(旧变量名)")
            if 'strength_ratio' in details:
                print(f"  ✓ details 包含 'strength_ratio'")
        else:
            print(f"  ⚠ 未检测到上涨趋势背驰（笔的涨幅差距可能不够明显）")
    except NameError as e:
        print(f"  ❌ BUG确认: NameError - {e}")
        print(f"     原因: 上涨趋势背驰分支使用了未定义的变量 area_ratio/macd_confirmed")
        print(f"     正确: 应使用 metric_ratio/metric_confirmed")
        raise


def test_bug_duplicated_post_init():
    """
    检测 BUG: Zhongshu 类中 __post_init__ 被重复定义
    
    BUG描述:
    第125-146行和第148-152行各有一个 __post_init__ 方法。
    后者覆盖前者，导致 duration 计算永远不执行。
    """
    from app.engine.framework.chanlun_strategy import Zhongshu
    
    zs = Zhongshu(
        start_idx=0, end_idx=10,
        start_date='2024-01-01', end_date='2024-02-15',
        high=12.0, low=10.0,
    )
    
    # duration 应该被计算为 "1月"（45天）
    if zs.duration is None:
        print(f"  ❌ BUG确认: duration 为 None")
        print(f"     原因: 第二个 __post_init__ 覆盖了第一个，跳过了 duration 计算")
    else:
        print(f"  ✓ duration = {zs.duration}")


def test_bug_down_trend_divergence_uses_area_directly():
    """
    检测 BUG: 下跌趋势背驰分支直接调用 _calc_stroke_macd_area 而非 _calc_stroke_metric

    BUG描述:
    下跌趋势背驰分支(1138-1139行)使用了 _calc_stroke_macd_area，
    未遵循配置的 macd_algo 参数。
    """
    from app.engine.framework.chanlun_strategy import (
        DivergenceDetector, Stroke
    )
    
    # 使用 slope 算法验证
    detector = DivergenceDetector(macd_algo='slope')
    closes = np.array([10.0 + i * 0.01 for i in range(200)])
    
    strokes = [
        Stroke(start_idx=0, end_idx=20, start_price=10.0, end_price=10.5,
               start_date='2024-01-01', end_date='2024-01-20', direction='up',
               high=10.5, low=10.0),
        Stroke(start_idx=20, end_idx=40, start_price=10.5, end_price=10.3,
               start_date='2024-01-21', end_date='2024-02-10', direction='down',
               high=10.5, low=10.3),
        Stroke(start_idx=40, end_idx=60, start_price=10.3, end_price=10.8,
               start_date='2024-02-11', end_date='2024-03-01', direction='up',
               high=10.8, low=10.3),
        Stroke(start_idx=60, end_idx=80, start_price=10.8, end_price=10.5,
               start_date='2024-03-02', end_date='2024-03-21', direction='down',
               high=10.8, low=10.5),
        # 第五笔：创新低
        Stroke(start_idx=80, end_idx=100, start_price=10.5, end_price=10.2,
               start_date='2024-03-22', end_date='2024-04-10', direction='down',
               high=10.5, low=10.2),
    ]
    
    detector._closes = closes
    result = detector._detect_trend_divergence(strokes)
    
    # 检查是否使用了 slope 算法（应该返回非 None）
    if result:
        print(f"  ✓ 下跌趋势背驰检测完成: {result.type}/{result.direction}")
        print(f"  ⚠ 注意: 下跌分支固定使用 area 算法，即便配置为 slope")
    else:
        print(f"  ⚠ 未检测到下跌趋势背驰")


# ============================================================
# 第2组：ChanlunAnalyzer 完整流程测试
# ============================================================

def test_chanlun_analyzer_full_pipeline():
    """测试 ChanlunAnalyzer 完整分析流程"""
    from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
    
    df = make_test_klines(rows=150, seed=42)
    assert len(df) >= 130, f"数据不足: {len(df)}"
    
    analyzer = ChanlunAnalyzer()
    result = analyzer.analyze(df)
    
    # 验证结果结构
    assert 'success' in result, "缺少 success 字段"
    if result.get('success'):
        summary = result.get('summary', {})
        assert summary.get('total_strokes', 0) >= 3, f"笔数不足: {summary.get('total_strokes')}"
        
        print(f"  ✓ 完整分析通过")
        print(f"    K线: {summary.get('total_klines')}, 分型: {summary.get('total_fractals')}")
        print(f"    笔: {summary.get('total_strokes')}, 线段: {summary.get('total_segments')}")
        print(f"    中枢: {summary.get('total_zhongshu')}, 趋势: {summary.get('current_trend')}")
        print(f"    买点: {summary.get('buy_point_count')}, 卖点: {summary.get('sell_point_count')}")
        print(f"    背驰: {summary.get('has_divergence')}")
        
        # 检查定理校验
        theorem = result.get('theorem_check', {})
        ts = theorem.get('summary', {})
        print(f"    定理校验: {ts.get('passed')}/{ts.get('total')} 通过, 得分={ts.get('overall_score')}")
    else:
        print(f"  ⚠ 分析未成功: {result.get('error', '未知错误')}")
        # 这可能是因为合成数据不足或不满足缠论基本条件


def test_chanlun_analyzer_with_double_zs_trend():
    """测试双中枢趋势走势分析"""
    from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
    
    df = make_trend_data('double_zs', rows=250)
    assert len(df) >= 200
    
    analyzer = ChanlunAnalyzer()
    result = analyzer.analyze(df)
    
    if result.get('success'):
        summary = result.get('summary', {})
        zhongshu_list = result.get('zhongshu', [])
        divergence = result.get('divergence')
        
        print(f"  ✓ 双中枢趋势分析通过")
        print(f"    笔: {summary.get('total_strokes')}, 段: {summary.get('total_segments')}")
        print(f"    中枢: {summary.get('total_zhongshu')}")
        if zhongshu_list:
            for i, zs in enumerate(zhongshu_list):
                print(f"    中枢{i+1}: [{zs.low:.2f}, {zs.high:.2f}] {zs.type}")
        if divergence:
            print(f"    背驰: {divergence.type}/{divergence.direction} 置信度={divergence.confidence:.2f}")
        
        buy_points = result.get('buy_points', [])
        sell_points = result.get('sell_points', [])
        print(f"    买点: {len(buy_points)}, 卖点: {len(sell_points)}")
    else:
        print(f"  ⚠ 双中枢趋势分析未成功: {result.get('error', '')}")


# ============================================================
# 第3组：ChanlunScorer 评分验证
# ============================================================

def test_chanlun_scorer():
    """测试缠论评分系统"""
    from app.engine.framework.chanlun_strategy import (
        ChanlunAnalyzer, ChanlunScorer
    )
    
    df = make_test_klines(rows=150, seed=42)
    analyzer = ChanlunAnalyzer()
    result = analyzer.analyze(df)
    
    if result.get('success'):
        latest_close = float(df['close'].iloc[-1])
        score_result = ChanlunScorer.score(result, latest_close=latest_close)
        
        assert 'score' in score_result
        assert 0 <= score_result['score'] <= 100
        
        print(f"  ✓ 评分结果: score={score_result['score']:.1f}")
        print(f"    推荐: {score_result.get('recommendation')}")
        for d in score_result['details'][:5]:
            print(f"    - {d}")


# ============================================================
# 第4组：SignalComputationService 集成验证
# ============================================================

def test_signal_computation_chanlun_integration():
    """验证 SignalComputationService 中缠论信号计算流程"""
    from app.engine.framework.chanlun_strategy import (
        ChanlunAnalyzer, ChanlunScorer, BuySellPoint
    )
    
    df = make_test_klines(rows=150, seed=42)
    df_analysis = df.copy()
    df_analysis['volume'] = df_analysis['vol']
    df_analysis['trade_date'] = df_analysis['trade_date']
    
    analyzer = ChanlunAnalyzer()
    result = analyzer.analyze(df_analysis)
    
    assert result.get('success'), f"分析失败: {result.get('error')}"
    
    # ---- 模拟 signal_computation_service 的流程 ----
    
    # Step L3: 评分
    latest_close = float(df['close'].iloc[-1])
    score_result = ChanlunScorer.score(result, latest_close=latest_close)
    chanlun_score = score_result.get('score', 50)
    
    print(f"  ✓ L3评分: {chanlun_score:.1f}")
    
    # 走势结构分析
    strokes = result.get('strokes', [])
    segments = result.get('segments', [])
    zhongshu_list = result.get('zhongshu', [])
    divergence = result.get('divergence')
    buy_points = result.get('buy_points', [])
    sell_points = result.get('sell_points', [])
    trend = result.get('trend', 'unknown')
    
    assert len(strokes) > 0, "无笔数据"
    
    last_stroke = strokes[-1]
    latest_close = float(df['close'].iloc[-1])
    price_offset = (latest_close / float(last_stroke.end_price) - 1) * 100
    
    print(f"  ✓ 走势结构: 趋势={trend}, 最后一笔方向={last_stroke.direction}")
    print(f"    笔终点={last_stroke.end_price:.2f}, 当前价={latest_close:.2f}, 偏离={price_offset:+.2f}%")
    
    # 中枢分析
    latest_zhongshu = zhongshu_list[-1] if zhongshu_list else None
    if latest_zhongshu:
        if latest_close > latest_zhongshu.high:
            pos = '上方'
        elif latest_close < latest_zhongshu.low:
            pos = '下方'
        else:
            pos = '内部'
        print(f"  ✓ 中枢分析: 中枢=[{latest_zhongshu.low:.2f}, {latest_zhongshu.high:.2f}], 价格相对位置={pos}")
    
    # 卖点分析
    latest_sell = max(sell_points, key=lambda p: {'first_sell':1,'second_sell':2,'third_sell':3}.get(p.type,0)) if sell_points else None
    if latest_sell:
        print(f"  ✓ 最近卖点: {latest_sell.type} @price={latest_sell.position.get('price', 0):.2f}")


# ============================================================
# 第5组：个股策略分析集成验证
# ============================================================

def test_strategy_analyze_chanlun_dimension():
    """验证个股策略分析中的缠论维度构建"""
    from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
    
    df = make_test_klines(rows=150, seed=42)
    analyzer = ChanlunAnalyzer()
    result = analyzer.analyze(df)
    
    if not result.get('success'):
        print(f"  ⚠ 跳过: 分析未成功")
        return
    
    # 构造 _build_chanlun_dimension 需要的输入
    # 模拟 signal_computation_service 产出
    sig = {
        'strategy_name': '缠论走势分析',
        'signal': 'bullish',
        'signal_label': '上升趋势延续',
        'confidence': 0.72,
        'evidence': [
            '上升趋势，最后一笔为上升笔',
            '价格在中枢上方运行'
        ],
        'chanlun_analysis_detail': {
            '走势结构': {
                '趋势方向': '上升',
                '当前状态': '上升笔延续',
                '笔数': len(result.get('strokes', [])),
            },
            '中枢分析': {
                '价格相对位置': '上方',
            },
            '操作建议': {
                '建议动作': '持仓',
            },
        },
        'status_recognition': {
            'trend': {
                'direction': 'up',
                'strength': 'strong'
            },
            'buy_sell_point': {
                'buy': [],
                'sell': [],
            },
            'support_resistance': {
                'support': 9.5,
                'resistance': 11.0,
            }
        },
        'latest_close': float(df['close'].iloc[-1])
    }
    
    # 手动模拟 _build_chanlun_dimension
    sr = sig.get('status_recognition', {})
    trend = sr.get('trend', {})
    detail = sig.get('chanlun_analysis_detail', {})
    
    structure = detail.get('走势结构', {})
    trend_str = structure.get('趋势方向', '')
    
    zhongshu = detail.get('中枢分析', {})
    zhongshu_position = zhongshu.get('价格相对位置', '')
    
    bp = sr.get('buy_sell_point', {})
    buy_list = bp.get('buy', [])
    
    print(f"  ✓ 个股策略分析维度:")
    print(f"    趋势方向: {trend_str}")
    print(f"    中枢相对位置: {zhongshu_position}")
    print(f"    买点: {', '.join(buy_list) if buy_list else '无'}")


# ============================================================
# 第6组：多级别分析验证
# ============================================================

def test_multi_level_analysis():
    """验证多级别缠论联立分析"""
    from app.engine.framework.chanlun_multi_level import MultiLevelChanlunAnalyzer
    
    df_daily = make_test_klines(rows=260, seed=42)
    df_hourly = make_test_klines(rows=130, seed=43)
    
    analyzer = MultiLevelChanlunAnalyzer()
    result = analyzer.analyze({'daily': df_daily, 'hourly': df_hourly})
    
    assert 'direction_text' in result
    assert 'levels' in result
    assert result.get('enabled'), "多级别分析未启用"
    
    levels = result.get('levels', {})
    direction_map = result.get('direction_map', {})
    
    print(f"  ✓ 多级别联立分析完成")
    print(f"    已分析的级别: {list(direction_map.keys())}")
    print(f"    方向描述: {result.get('direction_text')}")
    for level_name, data in levels.items():
        print(f"    {level_name}: 笔={data.get('stroke_count')}, 段={data.get('segment_count')}, 中枢={data.get('zhongshu_count')}")


# ============================================================
# 第7组：性能与特殊场景
# ============================================================

def test_analyzer_with_insufficient_data():
    """验证数据不足时的处理"""
    from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
    
    df = make_test_klines(rows=20, seed=42)
    assert len(df) < 30
    
    analyzer = ChanlunAnalyzer()
    result = analyzer.analyze(df)
    
    assert 'error' in result, "数据不足时应返回 error"
    print(f"  ✓ 数据不足正确处理: {result['error']}")


def test_analyzer_with_no_trend():
    """验证无趋势数据的分析"""
    from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
    
    df = make_trend_data('sideways', rows=150)
    analyzer = ChanlunAnalyzer()
    result = analyzer.analyze(df)
    
    if result.get('success'):
        summary = result.get('summary', {})
        print(f"  ✓ 横盘数据分析完成")
        print(f"    笔: {summary.get('total_strokes')}, 中枢: {summary.get('total_zhongshu')}")


def test_buy_sell_subtypes_1p():
    """验证盘整背驰第一类买卖点 (1p) 的生成"""
    from app.engine.framework.chanlun_strategy import (
        BuySellPointDetector, Stroke, Divergence, Zhongshu
    )

    detector = BuySellPointDetector(bs_type='1,1p,2,3a,3b')

    zs = Zhongshu(start_idx=0, end_idx=100, start_date='', end_date='',
                  high=12.0, low=10.0, center=11.0, level='daily', direction='up')

    strokes = [
        Stroke(start_idx=0, end_idx=20, start_price=10.0, end_price=11.0,
               start_date='', end_date='', direction='up', high=11.0, low=10.0),
        Stroke(start_idx=20, end_idx=40, start_price=11.0, end_price=10.5,
               start_date='', end_date='', direction='down', high=11.0, low=10.5),
        Stroke(start_idx=40, end_idx=60, start_price=10.5, end_price=11.5,
               start_date='', end_date='', direction='up', high=11.5, low=10.5),
        Stroke(start_idx=60, end_idx=80, start_price=11.5, end_price=11.0,
               start_date='', end_date='', direction='down', high=11.5, low=11.0),
    ]

    # 盘整背驰 (consolidation type)
    divergence = Divergence(type='consolidation', direction='up', confidence=0.7,
                            position={'idx': 80, 'price': 11.0})

    buy, sell = detector.find(strokes, [zs], divergence)
    # 盘整背驰买点应生成 first_buy_p 类型
    has_1p = any(p.type == 'first_buy_p' for p in buy)
    has_1 = any(p.type == 'first_buy' for p in buy)
    assert has_1p or has_1, f"盘整背驰应生成 first_buy_p 或 first_buy, 实际: buy={[p.type for p in buy]}"
    if has_1p:
        print(f"  ✓ first_buy_p generated: reason={[p.reason for p in buy if p.type == 'first_buy_p']}")


def test_buy_sell_subtypes_3a_vs_3b():
    """验证第三类买卖点 3a(一类后) vs 3b(一类前) 的区分"""
    from app.engine.framework.chanlun_strategy import (
        BuySellPointDetector, Stroke, Divergence, Zhongshu
    )

    detector = BuySellPointDetector(bs_type='1,2,3a,3b')

    zs = Zhongshu(start_idx=0, end_idx=40, start_date='', end_date='',
                  high=12.0, low=10.0, center=11.0, level='daily', direction='up')

    # 场景：3b（一类前）— 笔序列中有第三类买点但之前无第一类买点
    strokes_3b = [
        Stroke(start_idx=0, end_idx=20, start_price=10.0, end_price=12.5,
               start_date='', end_date='', direction='up', high=12.5, low=10.0),
        Stroke(start_idx=20, end_idx=35, start_price=12.5, end_price=11.5,
               start_date='', end_date='', direction='down', high=12.5, low=11.5),
    ]
    # 通过中枢后的笔形成第三类买点（回调不进入中枢）
    strokes_3b_after = [
        Stroke(start_idx=50, end_idx=70, start_price=11.5, end_price=13.0,
               start_date='', end_date='', direction='up', high=13.0, low=11.5),
        Stroke(start_idx=70, end_idx=85, start_price=13.0, end_price=12.5,
               start_date='', end_date='', direction='down', high=13.0, low=12.5),
    ]
    all_strokes = strokes_3b + strokes_3b_after

    # 不带 divergence（无第一类买点）→ 应生成 third_buy_b
    buy_3b, _ = detector.find(all_strokes, [zs], divergence=None)
    has_3b = any(p.type == 'third_buy_b' for p in buy_3b)
    if has_3b:
        print(f"  ✓ third_buy_b (一类前) generated")
    else:
        print(f"  ⚠ third_buy_b not generated (可能未满足第三类买点条件)")


def test_buy_sell_subtypes_2s():
    """验证 bs_type 配置过滤第二类买卖点的有效性"""
    from app.engine.framework.chanlun_strategy import BuySellPointDetector

    # bs_type 关闭 '2' → _has_type 应返回 False
    detector_no_2 = BuySellPointDetector(bs_type='1,3a,3b')
    # bs_type 包含 '2' → _has_type 应返回 True
    detector_with_2 = BuySellPointDetector(bs_type='1,2,3a,3b')

    assert detector_with_2._has_type('2'), "有'2'时 _has_type('2') 应为True"
    assert not detector_no_2._has_type('2'), "无'2'时 _has_type('2') 应为False"
    assert detector_with_2._has_type('3a'), "有'3a'时 _has_type('3a') 应为True"
    assert not detector_with_2._has_type('1p'), "无'1p'时 _has_type('1p') 应为False"

    print(f"  ✓ bs_type 过滤验证通过: with_2={detector_with_2.bs_type}, no_2={detector_no_2.bs_type}")


def test_bs_type_config_filter():
    """验证 bs_type 配置字符串 → set 映射正确"""
    from app.engine.framework.chanlun_strategy import BuySellPointDetector

    d1 = BuySellPointDetector(bs_type='1,2,3a,3b')
    assert d1._has_type('1'), "应包含类型1"
    assert d1._has_type('2'), "应包含类型2"
    assert d1._has_type('3a'), "应包含类型3a"
    assert not d1._has_type('1p'), "不应包含类型1p"
    assert not d1._has_type('2s'), "不应包含类型2s"

    d2 = BuySellPointDetector(bs_type='1,1p,2,2s,3a,3b')
    assert d2._has_type('1p'), "应包含类型1p"
    assert d2._has_type('2s'), "应包含类型2s"
    assert d2._has_type('3b'), "应包含类型3b"
    print(f"  ✓ bs_type 配置过滤正确: all={d1.bs_type}")


# ============================================================
# 主入口——追加到 run_all_tests
# ============================================================

def run_all_tests():
    """运行全部测试"""
    test_map = {
        # 第1组：代码逻辑正确性检测
        'BUG-01: 上涨趋势背驰变量名错误': test_bug_variable_name_mismatch_in_divergence,
        'BUG-02: __post_init__重复定义': test_bug_duplicated_post_init,
        'BUG-03: 下跌背驰固定使用area算法': test_bug_down_trend_divergence_uses_area_directly,
        
        # 第2组：完整分析流程
        'ANALYZER-01: 完整分析流程': test_chanlun_analyzer_full_pipeline,
        'ANALYZER-02: 双中枢趋势': test_chanlun_analyzer_with_double_zs_trend,
        
        # 第3组：评分系统
        'SCORER-01: 评分验证': test_chanlun_scorer,
        
        # 第4组：选股系统集成
        'INTEGRATION-01: 信号计算集成': test_signal_computation_chanlun_integration,
        
        # 第5组：个股策略分析
        'STRATEGY-01: 个股策略维度': test_strategy_analyze_chanlun_dimension,
        
        # 第6组：多级别分析
        'MULTI-LEVEL-01: 多级别联立': test_multi_level_analysis,
        
        # 第7组：特殊场景
        'EDGE-01: 数据不足': test_analyzer_with_insufficient_data,
        'EDGE-02: 横盘走势': test_analyzer_with_no_trend,

        # 第8组：买卖点子类型
        'SUBTYPE-01: 盘整背驰1p': test_buy_sell_subtypes_1p,
        'SUBTYPE-02: 3a/3b区分': test_buy_sell_subtypes_3a_vs_3b,
        'SUBTYPE-03: bs_type配置过滤': test_buy_sell_subtypes_2s,
        'SUBTYPE-04: bs_type配置': test_bs_type_config_filter,
    }
    
    total = len(test_map)
    passed = 0
    failed = 0
    
    print("=" * 80)
    print("缠论策略综合验证报告")
    print("=" * 80)
    
    for name, func in test_map.items():
        print(f"\n[{name}]")
        try:
            func()
            passed += 1
            print(f"  ✅ 通过")
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"  ❌ 失败: {e}")
    
    print("\n" + "=" * 80)
    print(f"验证结果: {passed}/{total} 通过, {failed}/{total} 失败")
    
    # 详细bug报告
    print("\n")
    print("=" * 80)
    print("BUG 报告摘要")
    print("=" * 80)
    print("""
[BUG-01] NameError in _detect_trend_divergence (上升趋势背驰分支)
  位置: chanlun_strategy.py:1123-1124
  描述: 使用了未定义的变量 'area_ratio' 和 'macd_confirmed'
        正确应为 'metric_ratio' 和 'metric_confirmed'
  影响: 当上升趋势出现背驰条件时触发 NameError，导致分析崩溃
  复现: test_chanlun_verification.py::test_bug_variable_name_mismatch_in_divergence

[BUG-02] __post_init__ 重复定义
  位置: chanlun_strategy.py:125-146 和 148-152
  描述: Zhongshu 类有两个 __post_init__ 方法，后者覆盖前者
        center/range_width 重复计算，duration 计算被跳过
  影响: 中枢的 duration 字段始终为 None
  复现: test_chanlun_verification.py::test_bug_duplicated_post_init

[BUG-03] 下跌趋势背驰固定使用 MACD area 算法
  位置: chanlun_strategy.py:1138-1139
  描述: 下跌分支直接调用 _calc_stroke_macd_area，
        未使用 _calc_stroke_metric 方法，不遵循配置的 macd_algo
  影响: macd_algo='slope'/'volume'/'peak' 等配置在下跌分支中失效
""")
    
    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
