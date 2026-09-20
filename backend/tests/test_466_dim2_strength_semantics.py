# -*- coding: utf-8 -*-
"""466号 ③④⑤：dim2 强度语义改造——chanlun_strength 重规划为"结构健康度"

③ 命名/键：chanlun_strength 保留别名（0-100，语义=结构健康度），新增 structure_health_score 键，
   continuous_value = 健康度/100（0-1，"健康度归一"而非"置信度"）。
④ 计分重构：以 11 定理 overall_score 为基底（健康权威源），中枢/趋势/背驰/买卖点降为轻信号项——
   消解"健康+上升+无背驰却 8%/0%"（旧 score() 纯买卖点加减分，茅台 15 三卖压到 6）。
⑤ 话术：dim8 structure 维文案改"结构健康xx/100"，不再冒充"置信xx%"。
"""
from unittest import mock

from app.engine.framework.chanlun_strategy import ChanlunScorer
from app.opportunity_atlas.dimensions.dim2_structure_engine import Dim2StructureEngine, ChanlunAnalyzer
from app.opportunity_atlas.dimensions.dim8_summary_engine import _brief_text


def _mk_result(theorem=0.7, trend='up', divergence=None, buys=(), sells=(), zs=()):
    from types import SimpleNamespace
    return {
        'trend': trend, 'zhongshu': list(zs), 'divergence': divergence,
        'buy_points': list(buys), 'sell_points': list(sells),
        'theorem_check': {'summary': {'overall_score': theorem}},
    }


def _zs(high, low, direction='up'):
    from types import SimpleNamespace
    return SimpleNamespace(high=high, low=low, direction=direction)


class TestStructureHealthScoreSemantics:
    """④：健康结构不塌底——11 定理基底，买卖点仅为轻信号项。"""

    def test_healthy_uptrend_no_divergence_neutral(self):
        """茅台场景核心：健康(0.7)+上升+无背驰+无买点 → 健康度不塌（旧 score 因无买点=50）。"""
        r = _mk_result(theorem=0.7, trend='up')
        sr = ChanlunScorer.structure_health_score(r)
        assert sr['score'] == 80  # 70 基底 + 上升10 = 80（无买卖点/中枢/背驰）

    def test_healthy_with_many_sells_not_crushed(self):
        """健康+上升+大量三卖 → 健康度仅轻扣，不被历史卖点压底（旧 score(): 15 三卖 → 6）。"""
        from test_465_dim2_strength_design import _bsp
        r = _mk_result(theorem=0.7, trend='up',
                       sells=[_bsp('third_sell', 300 + i) for i in range(15)])
        sr = ChanlunScorer.structure_health_score(r)
        assert sr['score'] > 60, f"健康结构不应因历史卖点塌底，实际 {sr['score']}"

    def test_unhealthy_trend_down_lower(self):
        """欲病(0.5)+下降+顶背驰 → 健康度低。"""
        from types import SimpleNamespace
        div = SimpleNamespace(direction='down', type='trend', confidence=0.8)
        r = _mk_result(theorem=0.5, trend='down', divergence=div)
        sr = ChanlunScorer.structure_health_score(r)
        assert sr['score'] < 60

    def test_theorem_base_drives(self):
        """11 定理为基底：健康 vs 欲病在同信号下拉开。"""
        healthy = _mk_result(theorem=0.8)
        sick = _mk_result(theorem=0.4)
        assert ChanlunScorer.structure_health_score(healthy)['score'] > \
            ChanlunScorer.structure_health_score(sick)['score']

    def test_zhongshu_quality_small_boost(self):
        r = _mk_result(theorem=0.7, zs=[_zs(12, 10)])
        no_zs = _mk_result(theorem=0.7)
        assert ChanlunScorer.structure_health_score(r)['score'] == \
            ChanlunScorer.structure_health_score(no_zs)['score'] + 6


class TestStructureHealthKeyWired:
    """③：dim2 evaluate 产出 structure_health_score + chanlun_strength 别名同值 + continuous=健康/100。"""

    def _evaluate(self, theorem=0.7):
        import numpy as np
        import pandas as pd
        closes = np.linspace(10, 20, 30)
        df = pd.DataFrame({
            'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
            'low': closes * 0.99, 'close': closes, 'vol': [1e5] * 30,
        }, index=pd.date_range('2025-01-01', periods=30, freq='B'))
        eng = Dim2StructureEngine()
        tags = {'ts_code': 'T.XSHG'}
        with mock.patch.object(ChanlunAnalyzer, 'analyze',
                               return_value=_mk_result(theorem=theorem)):
            return eng.evaluate({}, tags, data_context={'daily_df': df})

    def test_structure_health_key_present(self):
        out = self._evaluate()
        sd = out['status_description']
        assert 'structure_health_score' in sd
        assert sd['structure_health_score'] == sd['chanlun_strength']
        assert 0 <= sd['structure_health_score'] <= 100

    def test_continuous_value_is_health_norm(self):
        out = self._evaluate(theorem=0.7)
        sd = out['status_description']
        assert abs(out['judgment']['continuous_value']
                   - sd['structure_health_score'] / 100.0) < 1e-6


class TestDim8StructureWording:
    """⑤：dim8 structure 维文案 = 结构健康xx/100；其他维保持置信。"""

    def _jg(self):
        return {'structure': '上升'}

    def test_structure_wording_health(self):
        assert _brief_text('structure', self._jg(), {}) == '上升（结构健康50/100）'

    def test_other_dim_keeps_confidence(self):
        assert _brief_text('emotion', self._jg(), {}) == '上升（置信50%）'

    def test_structure_confidence_scaled(self):
        jg = {'structure': '上升', 'continuous_value': 0.72}
        assert _brief_text('structure', jg, {}) == '上升（结构健康72/100）'
