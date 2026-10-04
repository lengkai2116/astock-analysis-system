"""508号批次5：PhaseDetectionEngine 演进版迁入 phase_detector.py 验证（dim4 内嵌 → 外部权威）

方案档：`002-方案存档/508-dim4双副本收敛（物理合入清理）.md` §〇 批次5（Q1 拍板：演进版为权威，
最小适配——daemon 3 参调用向后兼容）。

覆盖：
  - dim4/phase_detector 命名空间指向同一外部权威类（内嵌 868 行已删）
  - compute_tags 3 参兼容（daemon RAW 场景）+ 8 参 data_context 注入（SIG 场景）
  - 412 C3 v3.0 RSI 预计算覆写（迁入后内联于 _run_trading_phase_detector_v2）
  - 演进版差异方法（456 _cost_value/_apply_margin_signal / 443 _dim_ssrp cost_ext）
  - 451 语义 _dim_asr（asr>90→building，剔除 distributing 分支）
  - 464-12 _limit_up_cross_check 规则3 新窗口（T-1 涨停巨量 + T 低开）
  - 外部旧版死方法 _asr_to_phase 随迁移删除
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.opportunity_atlas.phase_detector import (  # noqa: E402
    PhaseDetectionEngine as ExtPhaseDetectionEngine,
)

_DIM4 = 'app.opportunity_atlas.dimensions.dim4_chip_fund_engine'


def _mk_kline(n=120, trend='up'):
    """构造 n 行日线（trend: up/down）"""
    if trend == 'up':
        close = np.linspace(10.0, 12.0, n)
    else:
        close = np.linspace(12.0, 10.0, n)
    idx = pd.date_range('2026-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'open': close - 0.1, 'high': close + 0.3, 'low': close - 0.3,
        'close': close, 'vol': [1000.0] * n,
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
    })


# ── ① 命名空间收敛 ──────────────────────────────────────

def test_b5_namespace_is_external_authority():
    """dim4 与 phase_detector 的 PhaseDetectionEngine 为同一外部权威类"""
    import importlib
    m = importlib.import_module(_DIM4)
    assert m.PhaseDetectionEngine is ExtPhaseDetectionEngine, 'dim4 应指向外部权威'
    assert m.PhaseDetectionEngine.__module__ == 'app.opportunity_atlas.phase_detector', \
        '类定义应在 phase_detector.py（演进版迁入）'


def test_b5_old_dead_method_asr_to_phase_removed():
    """外部旧版死方法 _asr_to_phase（507 Q1 只删了 dim4 侧）随迁移删除"""
    assert not hasattr(ExtPhaseDetectionEngine, '_asr_to_phase'), '_asr_to_phase 死方法应已删'


def test_b5_evolution_methods_present():
    """演进版差异方法齐全（456 _cost_value/_apply_margin_signal）"""
    for name in ('_cost_value', '_apply_margin_signal', 'compute_tags',
                 '_dim_ssrp', '_dim_asr', '_limit_up_cross_check',
                 '_run_trading_phase_detector_v2'):
        assert hasattr(ExtPhaseDetectionEngine, name), f'缺方法 {name}'


# ── ② 3 参 / 8 参调用 ───────────────────────────────────

def test_b5_compute_tags_3arg_compatible():
    """daemon RAW 场景 3 参调用（ts_code, df, extra_tags）兼容"""
    pde = ExtPhaseDetectionEngine()
    df = _mk_kline(120)
    res = pde.compute_tags('000001.SZ', df, extra_tags={'ssrp': 11.0})
    assert res['main_force_phase'] in ('building', 'washing', 'lifting',
                                       'distributing', 'unknown')
    assert res['price_position'] in ('low_zone', 'mid_zone', 'high_zone')
    assert res['trend_alignment'] in ('up_aligned', 'down_aligned', 'mixed', 'no_trend')
    assert res['fund_flow'] in ('5d_inflow', '5d_outflow', 'mixed', 'none')
    assert 0 <= res['phase_confidence'] <= 1


def test_b5_compute_tags_8arg_data_context():
    """SIG 场景 8 参 data_context 注入（chip_fund_ext/moneyflow_df/indicator_other_df）"""
    pde = ExtPhaseDetectionEngine()
    df = _mk_kline(120)
    res = pde.compute_tags(
        '000001.SZ', df, extra_tags={'ssrp': 11.0},
        chip_fund_ext={'asr': 85.0, 'concentration': 0.12, 'profit_ratio': 0.6, 'cyqkl': 30.0},
        moneyflow_df=pd.DataFrame({'net_lg_amount': [100.0] * 6}),
        indicator_ma_df=pd.DataFrame({'ma5': [11.9], 'ma10': [11.7], 'ma20': [11.3], 'ma60': [10.8]}),
        indicator_other_df=pd.DataFrame({'rsi14': [55.0]}),
        cost_ext={'main_force_cost': {'cost_price': 11.0}, 'margin_cost_price': {'cost_price': 11.0}})
    assert res['main_force_phase'] in ('building', 'washing', 'lifting',
                                       'distributing', 'unknown')
    assert res['fund_flow'] == '5d_inflow'  # moneyflow_df 注入生效（raw fallback 亦同向）


def test_b5_rsi_precompute_inlined():
    """412 C3 RSI 预计算覆写迁入 _run_trading_phase_detector_v2（indicator_other_df rsi14）"""
    pde = ExtPhaseDetectionEngine()
    df = _mk_kline(120)
    out = pde._run_trading_phase_detector_v2(
        '000001.SZ', df, indicator_other_df=pd.DataFrame({'rsi14': [33.3]}))
    assert out is not None, 'RSI 注入不应失败'
    phase, scores = out
    assert phase in ('BUILDING', 'WASHING', 'RAISING', 'SHIPPING', 'SUPPORT')


# ── ③ 演进版语义 ────────────────────────────────────────

def test_b5_dim_asr_451_semantics():
    """_dim_asr 451 语义：asr>90→building（蓄势），不再 distributing"""
    pde = ExtPhaseDetectionEngine()
    # monkeypatch _chip_distribution_analysis 返回高 ASR
    pde._chip_distribution_analysis = lambda ts, df: {'asr': 95.0, 'peak_position': 10.0}
    df = _mk_kline(120)
    out = pde._dim_asr('000001.SZ', df)
    assert out == {'building': 0.6}, f'asr>90 应 building（451 语义）: {out}'
    # 445 三处三义：asr>30 高于峰值 → 不再 distributing
    pde._chip_distribution_analysis = lambda ts, df: {'asr': 50.0, 'peak_position': 10.0}
    df2 = _mk_kline(120)
    df2.iloc[-1, df2.columns.get_loc('close')] = 11.0  # rel=1.1
    out2 = pde._dim_asr('000001.SZ', df2)
    assert out2 == {}, f'asr>30 高于峰值不应 distributing（445 剔除分支）: {out2}'


def test_b5_dim_ssrp_cost_ext_443():
    """443 R2 cost_ext 近距增强（现价距主力成本 5% 内 → 洗盘增强）"""
    pde = ExtPhaseDetectionEngine()
    df = _mk_kline(120)  # 现价 ≈ 12.0
    vec = pde._dim_ssrp(df, {'ssrp': 5.0},
                        cost_ext={'main_force_cost': {'cost_price': 11.9}})
    assert 'washing' in vec, f'cost_ext 近距应增强洗盘: {vec}'
    # 无 cost_ext → 走 ssrp 主规则
    vec2 = pde._dim_ssrp(df, {'ssrp': 5.0})
    assert vec2, 'ssrp 规则应产出'


def test_b5_limit_up_cross_check_46412():
    """464-12 规则3 新窗口：T-1 高位涨停巨量 + T 低开 → lifting 修正 distributing"""
    pde = ExtPhaseDetectionEngine()
    n = 80
    close = np.full(n, 10.0)
    close[-3] = 9.5
    close[-2] = 11.0   # T-1 涨停（+15.8%）
    close[-1] = 10.6   # T 低开回落（open 10.5 < prev*0.97）
    df = pd.DataFrame({
        'open': close, 'high': close + 0.3, 'low': close - 0.3,
        'close': close, 'vol': [1000.0] * (n - 2) + [3000.0, 2000.0],
        'pct_chg': [0.0] * n,
        'trade_date': [d.strftime('%Y-%m-%d') for d in
                       pd.date_range('2026-01-01', periods=n, freq='B')],
    })
    # 强制 T-1 巨量（vol[-2]=3000 > 60日均量*2）且 T 低开
    df.iloc[-2, df.columns.get_loc('vol')] = 3000.0
    out = pde._limit_up_cross_check(df, 'lifting', 'high_zone')
    assert out == 'distributing', f'464-12 规则3 应修正 distributing: {out}'


def test_b5_limit_up_cross_check_rules12_4():
    """规则1/2/4 保留（当日涨停）"""
    pde = ExtPhaseDetectionEngine()
    n = 80
    close = np.full(n, 10.0)
    close[-1] = 11.0  # 当日涨停（+10%）
    df = pd.DataFrame({
        'open': close, 'high': close + 0.3, 'low': close - 0.3,
        'close': close, 'vol': [1000.0] * n,
        'pct_chg': [0.0] * (n - 1) + [10.0],
        'trade_date': [d.strftime('%Y-%m-%d') for d in
                       pd.date_range('2026-01-01', periods=n, freq='B')],
    })
    # 规则2：building + 高位涨停 → distributing
    assert pde._limit_up_cross_check(df, 'building', 'high_zone') == 'distributing'
    # 规则1：building + 低位涨停 + 非巨量 → 保持 building
    assert pde._limit_up_cross_check(df, 'building', 'low_zone') == 'building'
    # 非涨停日 → 原样
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc('pct_chg')] = 1.0
    assert pde._limit_up_cross_check(df2, 'lifting', 'high_zone') == 'lifting'
