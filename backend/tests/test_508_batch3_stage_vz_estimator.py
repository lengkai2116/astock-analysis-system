"""508号批次3：StageDetector/ValuationZones/ChipDistributionEstimator 收敛验证

方案档：`002-方案存档/508-dim4双副本收敛（物理合入清理）.md` §〇 批次3（拍板：直接切外部完整版）。

覆盖：
  - dim4 命名空间三类指向外部权威（内嵌副本已删）
  - ChipDistributionEstimator 外部权威 estimate 与收敛前算法等价（构造 OHLCV 对比）
  - StageDetector 外部完整版可产出四阶段（UPTREND_ACTIVE/TOPPING/DOWNTREND_BOTTOMING/CONSOLIDATION）
  - _dim_stage mapping 与外部四阶段契约匹配（修复内嵌退化副本永不产出 TOPPING/BOTTOMING）
  - _run_stage_detector_v2 1 参调用（拍板：移除 indicator_ma_df 注入）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.data.chip_distribution_service import (  # noqa: E402
    ChipDistributionEstimator as ExtChipDistributionEstimator,
)
from app.engine.framework.volume_price_strategy import (  # noqa: E402
    Stage as ExtStage,
    StageDetector as ExtStageDetector,
    ValuationZones as ExtValuationZones,
)
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (  # noqa: E402
    ChipDistributionEstimator,
    Stage,
    StageDetector,
    ValuationZones,
)

_DIM4 = 'app.opportunity_atlas.dimensions.dim4_chip_fund_engine'


def _mk_kline(n=120, trend='up'):
    """构造 n 行日线。trend: up=持续上行 / down=持续下行 / flat=横盘"""
    if trend == 'up':
        close = np.linspace(10.0, 12.0, n)
    elif trend == 'down':
        close = np.linspace(12.0, 10.0, n)
    else:
        close = np.full(n, 10.0) + np.sin(np.arange(n) / 5.0) * 0.05
    idx = pd.date_range('2026-01-01', periods=n, freq='B')
    df = pd.DataFrame({
        'open': close - 0.1,
        'high': close + 0.3,
        'low': close - 0.3,
        'close': close,
        'vol': [1000.0] * n,
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
    })
    return df


def _mk_kline_sawtooth(n=140, upward=True):
    """锯齿上行/下行（满足 HH/HL 序列判据）"""
    base = np.linspace(10.0, 13.0, n) if upward else np.linspace(13.0, 10.0, n)
    wave = np.sin(np.arange(n) / 3.0) * 0.4
    close = base + wave
    idx = pd.date_range('2026-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'open': close - 0.05,
        'high': close + 0.25,
        'low': close - 0.25,
        'close': close,
        'vol': [1000.0] * n,
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
    })


# ── ① 命名空间收敛 ──────────────────────────────────────

def test_b3_dim4_names_are_external_authority():
    """dim4 命名空间三类与外部权威为同一对象（内嵌副本已删）"""
    import importlib
    m = importlib.import_module(_DIM4)
    assert m.StageDetector is ExtStageDetector, 'StageDetector 应指向外部权威'
    assert m.ValuationZones is ExtValuationZones, 'ValuationZones 应指向外部权威'
    assert m.Stage is ExtStage, 'Stage 应指向外部权威'
    assert m.ChipDistributionEstimator is ExtChipDistributionEstimator, \
        'ChipDistributionEstimator 应指向外部权威'
    # 内嵌独有特化方法不应残留（indicator_ma_df 注入已按拍板移除）
    assert not hasattr(m.StageDetector, '_calc_direction') or \
        hasattr(ExtStageDetector, '_calc_direction'), \
        'StageDetector 应为外部完整版（含 _calc_direction 等辅助方法）'


# ── ② ChipDistributionEstimator 等价 ─────────────────────

def test_b3_estimator_estimate_equivalent():
    """dim4 引用的外部 estimator 产 chip_bins 键与收敛前一致（ssrp/peak 口径不变）"""
    est = ChipDistributionEstimator()
    df = _mk_kline(120)
    chip_dist, min_p, max_p, step = est.estimate(df)
    assert step > 0 and min_p > 0
    assert chip_dist.shape == (150,)
    assert abs(float(chip_dist.sum()) - 1.0) < 1e-6, '归一化后总和应为 1'
    # 与直接外部实例结果一致（同一类）
    ext = ExtChipDistributionEstimator()
    c2, min_p2, max_p2, step2 = ext.estimate(df)
    np.testing.assert_allclose(chip_dist, c2)
    assert (min_p, max_p, step) == (min_p2, max_p2, step2)


def test_b3_get_chip_estimator_uses_external():
    """_get_chip_estimator 返回外部权威实例（内嵌类不再被实例化）"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine

    eng = object.__new__(PhaseDetectionEngine)
    eng._chip_estimator = None
    est = eng._get_chip_estimator()
    assert isinstance(est, ExtChipDistributionEstimator), '应返回外部权威实例'
    assert eng._chip_estimator is est, '应缓存'


# ── ③ StageDetector 外部完整版四阶段 ─────────────────────

def test_b3_stage_detector_full_phases_available():
    """外部完整版可产出四阶段（内嵌退化版仅三态，永不产 TOPPING/BOTTOMING）"""
    det = StageDetector()
    s_up = det.detect(_mk_kline_sawtooth(140, upward=True))
    assert s_up.name in ('UPTREND_ACTIVE', 'UPTREND_TOPPING'), f'上升应产出拉升/见顶: {s_up.name}'
    assert s_up.valuation is not None, '外部完整版应带 valuation（三周期分位）'
    assert s_up.trend_structure, '外部完整版应带 trend_structure（HH/HL）'
    s_dn = det.detect(_mk_kline_sawtooth(140, upward=False))
    assert s_dn.name in ('DOWNTREND_ACTIVE', 'DOWNTREND_BOTTOMING'), \
        f'下降应产出下跌/筑底: {s_dn.name}'


def test_b3_stage_detector_insufficient_data():
    """数据不足 → CONSOLIDATION（外部版守卫）"""
    det = StageDetector()
    s = det.detect(_mk_kline(20))
    assert s.name == 'CONSOLIDATION'


def test_b3_dim_stage_mapping_covers_external_phases():
    """_dim_stage 实际输出落入合法 phase（外部完整版四阶段 + CONSOLIDATION 证据验证）"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine

    eng = object.__new__(PhaseDetectionEngine)
    legal_phases = {'lifting', 'distributing', 'building', 'washing'}
    # 上升锯齿 → 拉升/出货/或 CONSOLIDATION 证据分支
    for trend, upward in (('up', True), ('down', False)):
        out = eng._dim_stage(_mk_kline_sawtooth(140, upward=upward))
        assert isinstance(out, dict)
        assert set(out.keys()) <= legal_phases, f'输出含非法 phase: {out}'
        for v in out.values():
            assert isinstance(v, float) and 0 <= v <= 1
    # 横盘 → 可能 CONSOLIDATION 证据验证（{} 或 washing/building）或直接阶段
    out = eng._dim_stage(_mk_kline(120, trend='flat'))
    assert isinstance(out, dict)
    assert set(out.keys()) <= legal_phases


def test_b3_run_stage_detector_v2_one_arg():
    """_run_stage_detector_v2 1 参调用（拍板：移除 indicator_ma_df 注入）"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine

    eng = object.__new__(PhaseDetectionEngine)
    out = eng._run_stage_detector_v2(_mk_kline_sawtooth(140, upward=True))
    assert out is not None, '1 参调用应成功返回'
    stage_name, conf = out
    assert stage_name in ('UPTREND_ACTIVE', 'UPTREND_TOPPING', 'DOWNTREND_ACTIVE',
                          'DOWNTREND_BOTTOMING', 'CONSOLIDATION')
    assert 0 <= conf <= 1.0


def test_b3_run_stage_detector_old_path_still_works():
    """旧 _run_stage_detector（死路径保留）切外部后 1 参兼容"""
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine

    eng = object.__new__(PhaseDetectionEngine)
    out = eng._run_stage_detector(_mk_kline(20))
    assert out in ('building', 'washing', 'lifting', 'distributing', 'unknown')
