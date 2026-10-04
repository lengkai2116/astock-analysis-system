"""508号批次4：TradingPhaseDetector 收敛验证（dim4 内嵌 → 外部 chip_strategy_impl.py 权威）

方案档：`002-方案存档/508-dim4双副本收敛（物理合入清理）.md` §〇 批次4（拍板：收敛+修复）。

覆盖：
  - dim4 命名空间 TradingPhaseDetector 指向外部权威（内嵌副本已删）
  - 7/8 方法逐行一致（detect_phase/_calc_moneyflow_score/_score_washing/raising/shipping/support）
  - _score_building 集中度分支收敛外部 concentration_status（修复 508批次2 切 P95-P5 后
    dim4 内嵌 concentration>0.3 语义反转——高=分散却加建仓分）
  - detect_phase 输出契约（phase/confidence/scores/moneyflow_score）
  - dim4 旧死代码 _run_trading_phase_detector 已删
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from app.engine.chip_strategy_impl import (  # noqa: E402
    TradingPhaseDetector as ExtTradingPhaseDetector,
)
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (  # noqa: E402
    TradingPhaseDetector,
)

_DIM4 = 'app.opportunity_atlas.dimensions.dim4_chip_fund_engine'


def _mk_kline(n=120):
    idx = pd.date_range('2026-01-01', periods=n, freq='B')
    close = np.linspace(10.0, 12.0, n)
    return pd.DataFrame({
        'open': close - 0.1, 'high': close + 0.3, 'low': close - 0.3,
        'close': close, 'vol': [1000.0] * n,
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
    })


def _mk_chip_bins():
    return [
        {'price_bin': 10.0, 'chip_ratio': 0.4},
        {'price_bin': 11.0, 'chip_ratio': 0.4},
        {'price_bin': 12.0, 'chip_ratio': 0.2},
    ]


# ── ① 命名空间收敛 ──────────────────────────────────────

def test_b4_dim4_names_is_external_authority():
    """dim4 命名空间 TradingPhaseDetector 指向外部权威（内嵌副本已删）"""
    import importlib
    m = importlib.import_module(_DIM4)
    assert m.TradingPhaseDetector is ExtTradingPhaseDetector, '应指向外部权威'


def test_b4_internal_old_dead_method_removed():
    """dim4 旧死代码 _run_trading_phase_detector（506 F4 残留）已删"""
    import importlib
    m = importlib.import_module(_DIM4)
    assert not hasattr(m.PhaseDetectionEngine, '_run_trading_phase_detector'), \
        '死代码 _run_trading_phase_detector 应已删'
    assert hasattr(m.PhaseDetectionEngine, '_run_trading_phase_detector_v2'), \
        'live 路径 _run_trading_phase_detector_v2 应保留'


# ── ② 方法一致性 ────────────────────────────────────────

def test_b4_method_signatures_identical():
    """收敛后方法签名与外部一致（dim4 消费方调用兼容）"""
    import inspect
    for name in ('detect_phase', '_calc_moneyflow_score', '_score_building',
                 '_score_washing', '_score_raising', '_score_shipping', '_score_support'):
        assert hasattr(TradingPhaseDetector, name), f'缺方法 {name}'
        sig = inspect.signature(getattr(ExtTradingPhaseDetector, name))
        assert inspect.signature(getattr(TradingPhaseDetector, name)) == sig, \
            f'{name} 签名与外部不一致'


def test_b4_score_building_concentration_status_semantics():
    """_score_building 收敛外部 concentration_status（P95-P5：集中加分/分散不加）"""
    det = object.__new__(TradingPhaseDetector)
    df = _mk_kline(120)
    s_concentrated = det._score_building(
        df, [], {'concentration_status': '高度集中'}, None, None)
    s_dispersed = det._score_building(
        df, [], {'concentration_status': '高度发散'}, None, None)
    assert s_concentrated - s_dispersed == 2.0, \
        f'集中应加 2 分（修复批次2 语义反转）: concentrated={s_concentrated} dispersed={s_dispersed}'


def test_b4_detect_phase_contract():
    """detect_phase 输出契约（phase/confidence/scores/moneyflow_score）"""
    det = object.__new__(TradingPhaseDetector)
    det.chip_indicators = None  # 不触发 transfer（chip_bins_history=None）
    df = _mk_kline(120)
    out = det.detect_phase(df, _mk_chip_bins(),
                           {'rsi': 50, 'asr': 50, 'ssrp': 10.0, 'profit_ratio': 0.5})
    assert out['phase'] in ('BUILDING', 'WASHING', 'RAISING', 'SHIPPING', 'SUPPORT')
    assert 0 <= out['confidence'] <= 1
    assert set(out['scores'].keys()) == {'BUILDING', 'WASHING', 'RAISING',
                                          'SHIPPING', 'SUPPORT'}
    assert 'moneyflow_score' in out


def test_b4_detect_phase_insufficient_data():
    """数据不足 → UNKNOWN（外部版守卫）"""
    det = object.__new__(TradingPhaseDetector)
    det.chip_indicators = None
    out = det.detect_phase(_mk_kline(40), _mk_chip_bins(), {})
    assert out['phase'] == 'UNKNOWN'
