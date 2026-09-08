"""396号方案 — dim2引擎修复验证测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import inspect

from app.opportunity_atlas.dimensions.dim2_structure_engine import (
    BuySellPointDetector,
    ChanlunAnalyzer,
    ChanlunLevelValidator,
    Divergence,
    Stroke,
    TrendStructureDetector,
    Zhongshu,
    calc_support_resistance,
)

# ═══════════════════════════════════════════════════════════
# F-01: BuySellPointDetector.find() 买卖点检测
# ═══════════════════════════════════════════════════════════

def test_bsp_detector_has_find_no_detect():
    """find()方法存在，detect()方法不存在"""
    det = BuySellPointDetector()
    assert hasattr(det, 'find'), "find() should exist"
    assert not hasattr(det, 'detect'), "detect() should not exist"


def test_bsp_detector_find_returns_tuple():
    """find()返回(buy_points, sell_points)元组"""
    det = BuySellPointDetector()
    strokes = [
        Stroke(0, 10, 10.0, 12.0, '2026-01-01', '2026-01-15', 'up'),
        Stroke(10, 20, 12.0, 11.0, '2026-01-15', '2026-02-01', 'down'),
        Stroke(20, 30, 11.0, 13.0, '2026-02-01', '2026-02-15', 'up'),
    ]
    zs = Zhongshu(10, 25, '2026-01-15', '2026-02-10', 12.5, 11.0)
    div = Divergence('trend', 'down', 0.85, {'idx': 30, 'price': 13.0})

    buy_pts, sell_pts = det.find(strokes, [zs], div)
    assert isinstance(buy_pts, list)
    assert isinstance(sell_pts, list)
    assert len(buy_pts) > 0 or len(sell_pts) > 0, "Should detect at least one point"


def test_bsp_detector_buy_point_has_attributes():
    """买卖点对象有type/confidence/position属性"""
    det = BuySellPointDetector()
    strokes = [
        Stroke(0, 10, 10.0, 12.0, 'd', 'd', 'up'),
        Stroke(10, 20, 12.0, 11.0, 'd', 'd', 'down'),
        Stroke(20, 30, 11.0, 13.0, 'd', 'd', 'up'),
    ]
    div = Divergence('trend', 'down', 0.85, {'idx': 30, 'price': 13.0})
    buy_pts, _ = det.find(strokes, [], div)
    if buy_pts:
        bp = buy_pts[0]
        assert hasattr(bp, 'type'), "BuySellPoint should have type"
        assert hasattr(bp, 'confidence'), "BuySellPoint should have confidence"
        assert hasattr(bp, 'position'), "BuySellPoint should have position"


# ═══════════════════════════════════════════════════════════
# F-14: TrendStructureDetector 返回 assumption 字段
# ═══════════════════════════════════════════════════════════

def test_trend_structure_returns_assumptions():
    """detect()返回值包含assumption1/2/3"""
    import numpy as np
    import pandas as pd

    ts = TrendStructureDetector()
    # 构造有明确趋势的数据
    np.random.seed(42)
    n = 60
    df = pd.DataFrame({
        'close': np.linspace(10, 15, n) + np.random.normal(0, 0.2, n),
        'high': np.linspace(10, 15, n) + 0.5,
        'low': np.linspace(10, 15, n) - 0.5,
        'open': np.linspace(10, 15, n),
        'vol': np.random.uniform(1000, 5000, n),
    })
    result = ts.detect(df)
    if result is not None:
        assert 'assumption1' in result, "Missing assumption1"
        assert 'assumption2' in result, "Missing assumption2"
        assert 'assumption3' in result, "Missing assumption3"
        assert isinstance(result['assumption1'], (bool, np.bool_)), "assumption1 should be bool"
        assert isinstance(result['assumption2'], (bool, np.bool_)), "assumption2 should be bool"
        assert isinstance(result['assumption3'], (bool, np.bool_)), "assumption3 should be bool"


# ═══════════════════════════════════════════════════════════
# F-15: fractal_threshold_pct 默认值为0.5
# ═══════════════════════════════════════════════════════════

def test_fractal_threshold_default():
    """ChanlunAnalyzer默认fractal_threshold_pct=0.5"""
    analyzer = ChanlunAnalyzer()
    assert analyzer.fractal_detector.threshold_pct == 0.5, \
        f"Expected 0.5, got {analyzer.fractal_detector.threshold_pct}"


def test_fractal_threshold_custom():
    """ChanlunAnalyzer支持自定义fractal_threshold_pct"""
    analyzer = ChanlunAnalyzer(config={'fractal_threshold_pct': 1.0})
    assert analyzer.fractal_detector.threshold_pct == 1.0


# ═══════════════════════════════════════════════════════════
# F-16: only_last 参数已移除
# ═══════════════════════════════════════════════════════════

def test_bsp_find_no_only_last_param():
    """find()签名中不含only_last参数"""
    sig = inspect.signature(BuySellPointDetector.find)
    assert 'only_last' not in sig.parameters, "only_last should be removed"


def test_chanlun_analyzer_no_only_judge_last():
    """ChanlunAnalyzer不含only_judge_last属性"""
    analyzer = ChanlunAnalyzer()
    assert not hasattr(analyzer, 'only_judge_last'), \
        "only_judge_last should be removed"


# ═══════════════════════════════════════════════════════════
# F-07: _determine_trend 综合判定
# ═══════════════════════════════════════════════════════════

def test_determine_trend_returns_string():
    """_determine_trend返回有效趋势字符串"""
    analyzer = ChanlunAnalyzer()
    trend = analyzer._determine_trend()
    assert isinstance(trend, str)
    assert trend in ('up', 'down', 'unknown', 'neutral')


# ═══════════════════════════════════════════════════════════
# F-02: _check_fractal_pair 无死代码
# ═══════════════════════════════════════════════════════════

def test_check_fractal_pair_no_dead_code():
    """_check_fractal_pair末尾无不可达return False"""
    from app.opportunity_atlas.dimensions.dim2_structure_engine import StrokeBuilder
    src = inspect.getsource(StrokeBuilder._check_fractal_pair)
    lines = [l.strip() for l in src.strip().split('\n') if l.strip()]
    # 最后一行应该是 return True（不是 return False）
    assert lines[-1] == 'return True', f"Last line should be 'return True', got '{lines[-1]}'"


# ═══════════════════════════════════════════════════════════
# F-06: resample 不假设 amount 列
# ═══════════════════════════════════════════════════════════

def test_resample_without_amount_column():
    """_resample_to_weekly/monthly 不依赖amount列"""
    import numpy as np
    import pandas as pd

    validator = ChanlunLevelValidator()
    df = pd.DataFrame({
        'trade_date': pd.date_range('2025-01-01', periods=60),
        'open': np.random.uniform(10, 12, 60),
        'high': np.random.uniform(12, 14, 60),
        'low': np.random.uniform(8, 10, 60),
        'close': np.random.uniform(10, 12, 60),
        'vol': np.random.uniform(1000, 5000, 60),
        # 故意不提供 amount 列
    })
    # 不应抛异常
    weekly = validator._resample_to_weekly(df)
    monthly = validator._resample_to_monthly(df)
    assert len(weekly) > 0, "Weekly should have data"
    assert len(monthly) > 0, "Monthly should have data"


# ═══════════════════════════════════════════════════════════
# calc_support_resistance 基础验证
# ═══════════════════════════════════════════════════════════

def test_calc_support_resistance_with_data():
    """有数据时返回有效支撑阻力"""
    import numpy as np
    import pandas as pd

    df = pd.DataFrame({
        'close': np.random.uniform(10, 15, 60),
        'high': np.random.uniform(12, 17, 60),
        'low': np.random.uniform(8, 13, 60),
    })
    result = calc_support_resistance(df)
    assert 'support_price' in result
    assert 'resistance_price' in result
    assert 'dist_to_support_pct' in result


def test_calc_support_resistance_empty():
    """空数据返回None值"""
    result = calc_support_resistance(None)
    assert result['support_price'] is None
    assert result['resistance_price'] is None
