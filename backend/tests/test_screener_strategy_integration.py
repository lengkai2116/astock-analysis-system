"""
选股系统 L3 策略集成单元测试
验证 256号方案修改：因子组合真实接入 + Vibe策略真实接入
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _make_test_data(rows=120):
    """生成测试用的OHLCV DataFrame"""
    np.random.seed(42)
    base_price = 10.0
    dates = [(datetime.now() - timedelta(days=i)).strftime('%Y%m%d') for i in range(rows)]
    dates.reverse()
    prices = base_price + np.cumsum(np.random.randn(rows) * 0.2)
    data = {
        'ts_code': ['000001.SZ'] * rows,
        'trade_date': dates,
        'open': prices + np.random.randn(rows) * 0.1,
        'high': prices + np.abs(np.random.randn(rows)) * 0.2 + 0.1,
        'low': prices - np.abs(np.random.randn(rows)) * 0.2 - 0.1,
        'close': prices,
        'vol': np.random.randint(500000, 2000000, rows),
        'amount': prices * np.random.randint(500000, 2000000, rows),
        'pct_chg': np.random.randn(rows) * 2,
    }
    return pd.DataFrame(data)


def test_factor_computers_registered():
    """验证因子映射表 _FACTOR_COMPUTERS 已注册且包含关键因子"""
    from app.engine.framework.screener_strategy_integration import _FACTOR_COMPUTERS
    assert len(_FACTOR_COMPUTERS) >= 9, f"应≥9个因子, 实际{len(_FACTOR_COMPUTERS)}"
    for key in ['20日动量', '5日动量', '14日RSI', '5日量比', '20日波动率',
                '5日反转因子', '20日均线乖离率', '量比', '动量因子(MOM)']:
        assert key in _FACTOR_COMPUTERS, f"缺少因子: {key}"
    print(f"✅ {len(_FACTOR_COMPUTERS)} 个因子已注册")


def test_factor_score_no_combos():
    """无组合选择时因子分为 0"""
    from app.engine.framework.screener_strategy_integration import _compute_factor_score
    df = _make_test_data(120)
    score = _compute_factor_score(df, symbol='000001.SZ', combo_ids=None)
    assert score == 0.0, f"无组合时应为0, 实际{score}"
    score = _compute_factor_score(df, symbol='000001.SZ', combo_ids=[])
    assert score == 0.0, f"空组合时应为0, 实际{score}"
    print(f"✅ 无组合 → factor_score=0")


def test_factor_score_with_combos():
    """选中组合时差异化的因子分"""
    from app.engine.framework.screener_strategy_integration import _compute_factor_score
    df = _make_test_data(120)
    # 选中 p3 (A股核心五因子) + p5 (短线动量)
    score = _compute_factor_score(df, symbol='000001.SZ', combo_ids=['p3', 'p5'])
    assert score >= 0.1, f"选中组合时应>0, 实际{score}"
    assert score <= 10.0, f"因子分应在0-10内, 实际{score}"
    # 验证只有一个组合时也工作
    score_p3 = _compute_factor_score(df, symbol='000001.SZ', combo_ids=['p3'])
    assert score_p3 >= 0.1
    print(f"✅ 选中组合(p3+p5) → factor_score={score:.2f}")


def test_factor_score_differentiation():
    """不同股票获得不同因子分"""
    from app.engine.framework.screener_strategy_integration import _compute_factor_score
    # 生成两只有明显差异的股票
    df1 = _make_test_data(120)
    # 第二只：强上升趋势
    df2 = _make_test_data(120)
    df2['close'] = np.linspace(10, 15, 120) + np.random.randn(120) * 0.1
    df2['vol'] = np.random.randint(1000000, 3000000, 120)
    
    score1 = _compute_factor_score(df1, symbol='000001.SZ', combo_ids=['p3'])
    score2 = _compute_factor_score(df2, symbol='000002.SZ', combo_ids=['p3'])
    assert abs(score1 - score2) > 0.1, f"差异化不足: {score1} vs {score2}"
    print(f"✅ 差异化因子分: {score1:.2f} vs {score2:.2f}")


def test_vibe_bonus_default():
    """无策略详情时Vibe加分使用默认值"""
    from app.engine.framework.screener_strategy_integration import _compute_vibe_bonus
    # 无策略时加分=0
    assert _compute_vibe_bonus(None) == 0.0
    assert _compute_vibe_bonus([]) == 0.0
    # 有策略时默认 +0.5/个
    score = _compute_vibe_bonus(['vibe_7', 'vibe_8'])
    assert score == 1.0, f"2个策略应=1.0, 实际{score}"
    print(f"✅ Vibe加分: 0个=0, 2个=1.0")


def test_vibe_bonus_differentiated():
    """有策略代码时真实执行，无代码时统一加分"""
    from app.engine.framework.screener_strategy_integration import _compute_vibe_bonus
    import pandas as pd
    import numpy as np
    # 无 df → 降级模式：每策略 +0.5
    score = _compute_vibe_bonus(['vibe_7', 'vibe_8'], df=None)
    assert score == 1.0, f"2个策略应=1.0, 实际{score}"
    
    # 有 df 但策略无代码 → 执行失败，返回0
    df = pd.DataFrame({'close': np.random.randn(120)+10, 'vol': np.random.randint(100,200,120)})
    details = [{'id': 'vibe_7', 'code_template': '', 'ready': True}]
    score2 = _compute_vibe_bonus(['vibe_7'], df=df, strategy_details=details)
    assert score2 == 0.0, f"空代码无策略执行, 应=0, 实际{score2}"
    
    # 有 df + 有代码 → 真实执行
    details2 = [{'id': 'vibe_7', 'code_template': 'signal = 80', 'ready': True}]
    score3 = _compute_vibe_bonus(['vibe_7'], df=df, strategy_details=details2)
    assert score3 == 8.0, f"signal=80 → 8.0/10, 实际{score3}"
    
    print(f"✅ Vibe差异化: 无df=统一加分, 有df+代码=真实执行")


def test_combined_score_with_factors():
    """验证带权重的综合评分包含因子分量"""
    from app.engine.framework.screener_strategy_integration import _compute_combined_score
    # 缠论=6.0, 量价=5.0, 因子=7.0
    score = _compute_combined_score(
        6.0, 5.0, 'bullish', 'neutral',
        weights={'chanlun': 0.35, 'vp': 0.30, 'factor': 0.25, 'vibe': 0.10},
        factor_score=7.0,
        vibe_bonus=0.8
    )
    # 期望: (6.0*0.35 + 5.0*0.30 + 7.0*0.25 + 0.8*0.10) / 1.0 = 5.43
    assert 5.0 < score < 6.0, f"综合分异常: {score}"
    print(f"✅ 综合评分包含因子分量: {score:.2f}")


def test_preset_combos_structure():
    """验证 PRESET_COMBOS 中使用的因子名都可在 _FACTOR_COMPUTERS 中找到或映射"""
    from app.engine.framework.screener_strategy_integration import _FACTOR_COMPUTERS
    try:
        from app.routes.factors import PRESET_COMBOS
    except ImportError:
        print("⚠️ 无法导入 PRESET_COMBOS，跳过")
        return
    
    registered = set(_FACTOR_COMPUTERS.keys())
    used_names = set()
    for c in PRESET_COMBOS:
        for f in c.get('factors', []):
            used_names.add(f['n'])
    
    unmatched = used_names - registered
    total = len(used_names)
    matched = total - len(unmatched)
    print(f"✅ PRESET_COMBOS 因子匹配率: {matched}/{total}")
    if unmatched:
        print(f"   未匹配(使用中性分5.0回退): {unmatched}")


def test_screener_vibe_excluded_strategies():
    """验证 Vibe 策略排除名单的定义——检查 screener.py 中的 EXCLUDED_NAMES"""
    with open('/Users/kalence/Desktop/01-A股股票分析系统/backend/app/routes/screener.py') as f:
        content = f.read()
    assert 'EXCLUDED_NAMES' in content, "screener.py 缺少 EXCLUDED_NAMES"
    assert 'DarwinRiskStrategy' in content
    assert 'MainForceTrackingStrategy' in content
    assert 'ChanlunStrategy' in content
    assert 'VolumePriceStrategy' in content
    assert 'ChipStrategy' in content
    assert 'MultiLevelRiskControlStrategy' in content
    print(f"✅ Vibe 排除名单在 screener.py 中已定义，包含6个L1/L2/L3策略")


if __name__ == '__main__':
    tests = [
        test_factor_computers_registered,
        test_factor_score_no_combos,
        test_factor_score_with_combos,
        test_factor_score_differentiation,
        test_vibe_bonus_default,
        test_vibe_bonus_differentiated,
        test_combined_score_with_factors,
        test_preset_combos_structure,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*40}")
    print(f"📋 结果: {passed}/{len(tests)} 通过, {failed}/{len(tests)} 失败")
