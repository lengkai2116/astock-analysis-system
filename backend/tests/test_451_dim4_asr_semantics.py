"""451 号 dim4 ASR 语义统一 + 死代码清理 + 双份同步 回归测试

覆盖（B 类 dim4 ASR 处置，445 六维评估偏差项）：
  TestDimAsrSemantics   —— ① _dim_asr 统一高 ASR=筹码集中蓄势语义
  TestScoreBuildingLive —— ② _score_building 接真实集中度数值（消除 concentration_status 惰性分支）
  TestFrameworkAsr      —— ③ framework _score_chip_distribution 高 ASR 不再判抛压减分
  TestDeadCodeRemoved   —— ④ identify_phase / MainForceFilter / _phase_to_status 已从双份移除
"""
import numpy as np
import pandas as pd
import pytest

from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine, TradingPhaseDetector
from app.engine.framework.chip_strategy import MainForceScorer


def _mk_df(closes, vols=None):
    """构造最小 OHLCV DataFrame"""
    closes = np.asarray(closes, dtype=float)
    if vols is None:
        vols = np.full_like(closes, 10000.0)
    n = len(closes)
    return pd.DataFrame({
        'open': closes,
        'high': closes,
        'low': closes,
        'close': closes,
        'vol': np.asarray(vols, dtype=float),
    })


def _det(df=None):
    """用 object.__new__ 绕过构造，绑定 mock 的 _chip_distribution_analysis"""
    det = object.__new__(PhaseDetectionEngine)
    det._chip = {}
    if df is None:
        df = _mk_df([10.0] * 120)
    det._df = df
    calls = {'n': 0}

    def _mock_chip(ts_code, data):
        calls['n'] += 1
        return det._chip

    det._chip_distribution_analysis = _mock_chip
    return det


class TestDimAsrSemantics:
    """① _dim_asr：高 ASR=筹码集中蓄势（不再直接 lifting）；剔除孤立 'asr>30→distributing'"""

    def test_high_asr_low_rel_is_building(self):
        """asr>90（无论价格相对峰值位置）→ building：筹码集中/突破前蓄势"""
        det = _det()
        det._chip = {"asr": 95.0, "peak_position": 10.0}
        df = _mk_df([9.0] * 120)  # rel = 0.9 < 0.95
        assert det._dim_asr("000001.SZ", df) == {"building": 0.6}

    def test_high_asr_near_peak_is_building(self):
        """asr>90 且价格就在峰值附近 → 仍 building（旧逻辑 rel<0.95 才 lifting，现统一蓄势）"""
        det = _det()
        det._chip = {"asr": 92.0, "peak_position": 10.0}
        df = _mk_df([10.5] * 120)  # rel = 1.05
        assert det._dim_asr("000001.SZ", df) == {"building": 0.6}

    def test_low_asr_near_peak_is_building(self):
        """asr<15 + 价格锁定在密集峰值附近 → building（建仓锁仓）"""
        det = _det()
        det._chip = {"asr": 10.0, "peak_position": 10.0}
        df = _mk_df([10.0] * 120)
        assert det._dim_asr("000001.SZ", df) == {"building": 0.6}

    def test_low_asr_far_above_peak_is_lifting(self):
        """asr<15 + 大幅高于峰值（rel>1.2）→ lifting：筹码锁定充分、脱离密集区"""
        det = _det()
        det._chip = {"asr": 8.0, "peak_position": 10.0}
        df = _mk_df([13.0] * 120)  # rel = 1.3
        assert det._dim_asr("000001.SZ", df) == {"lifting": 0.5}

    def test_isolated_mid_asr_above_peak_no_distributing(self):
        """剔除孤立 'asr>30 且高于峰值→distributing'：asr=50 不再直接判出货（445 三处三义核心）"""
        det = _det()
        det._chip = {"asr": 50.0, "peak_position": 10.0}
        df = _mk_df([11.0] * 120)  # rel = 1.1 > 1.05（旧逻辑 distributing）
        assert det._dim_asr("000001.SZ", df) == {}

    def test_mid_asr_between_bands_is_empty(self):
        """asr 处于 15-90 中段（未锁定/未高集中）→ 无明确阶段判定"""
        det = _det()
        det._chip = {"asr": 40.0, "peak_position": 10.0}
        df = _mk_df([10.0] * 120)  # rel = 1.0
        assert det._dim_asr("000001.SZ", df) == {}

    def test_no_peak_price_defaults_rel_1(self):
        """peak_position=0 时 rel 默认 1.0；asr 中段 → 空"""
        det = _det()
        det._chip = {"asr": 60.0, "peak_position": 0.0}
        df = _mk_df([10.0] * 120)
        assert det._dim_asr("000001.SZ", df) == {}


class TestScoreBuildingLive:
    """② _score_building 集中度分支接入真实数值（concentration），不再依赖从未生产的 concentration_status"""

    def test_building_concentration_high_score(self):
        """concentration>0.3（前 20% 价位筹码占比高=集中）→ 建仓加 2 分（原惰性分支现生效）"""
        det = object.__new__(TradingPhaseDetector)
        df = _mk_df([10.0] * 120)
        indicators = {'concentration': 0.45}
        score_with = det._score_building(df, [], indicators, None, None)
        score_without = det._score_building(df, [], {'concentration': 0.0}, None, None)
        assert score_with - score_without == pytest.approx(2.0)

    def test_building_concentration_low_no_bonus(self):
        """concentration 低（筹码分散）→ 不额外加分（<2 仅可能由 asr/profit 触发，此处均不触发）"""
        det = object.__new__(TradingPhaseDetector)
        df = _mk_df([10.0] * 120)
        score = det._score_building(df, [], {'concentration': 0.1, 'asr': 50.0, 'profit_ratio': 0.5}, None, None)
        assert score <= 2.0  # 无集中度加分（asr<70、profit>=0.4 不触发）

    def test_building_concentration_missing_no_crash(self):
        """concentration 缺失（None）→ 不报错、不加分"""
        det = object.__new__(TradingPhaseDetector)
        df = _mk_df([10.0] * 120)
        score = det._score_building(df, [], {'asr': 50.0, 'profit_ratio': 0.5}, None, None)
        assert isinstance(score, float)


class TestFrameworkAsr:
    """③ framework _score_chip_distribution：高 ASR 不再判抛压减分，统一为筹码集中蓄势"""

    def _score(self, asr_val):
        scorer = MainForceScorer()
        df = _mk_df([10.0] * 60)
        # ssrp 取当前价 10.0，避免 None 触发出货/异常；cyqkl=0 无穿越加分
        return scorer._score_chip_distribution('000001.SZ', df,
                                               {'asr': asr_val, 'ssrp': 10.0, 'cyqkl': 0.0})

    def test_high_asr_adds_score_not_subtracts(self):
        """asr>90 → 加分（蓄势）；与旧逻辑 asr>80 减分 反转"""
        high = self._score(95.0)
        mid = self._score(50.0)
        assert high > mid

    def test_low_asr_locked_bonus(self):
        """asr<20 → 浮筹极低、筹码锁定良好，加分（≥ 基础 0.5）"""
        assert self._score(10.0) >= 0.5


class TestDeadCodeRemoved:
    """④ identify_phase / MainForceFilter / _phase_to_status 已从双份代码移除；MainForceScorer live 方法保留"""

    def test_dim4_dead_code_absent(self):
        import app.opportunity_atlas.dimensions.dim4_chip_fund_engine as m
        assert not hasattr(m, 'MainForceFilter')
        assert not hasattr(m, '_phase_to_status')
        assert not hasattr(m.MainForceScorer, 'identify_phase')
        # 模块级不残留 def identify_phase（已从 MainForceScorer 移除）
        src = open(m.__file__, encoding='utf-8').read()
        assert 'def identify_phase' not in src

    def test_framework_dead_code_absent(self):
        import app.engine.framework.chip_strategy as m
        assert not hasattr(m, 'MainForceFilter')
        assert not hasattr(m, '_phase_to_status')
        assert not hasattr(m.MainForceScorer, 'identify_phase')

    def test_main_force_scorer_live_methods_preserved(self):
        """MainForceScorer 类本身 live，get_sub_scores/成本计算须保留"""
        scorer = MainForceScorer()
        assert hasattr(scorer, 'get_sub_scores')
        assert hasattr(scorer, '_calc_main_force_cost')
        assert hasattr(scorer, '_calc_margin_cost_price')
