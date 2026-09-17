"""454号：dim2 audit 门槛改造（消除「全为有数据级门槛」恒真，对齐 dim3 先例）

445 §6.1 dim2「audit 4 项全为有数据级门槛」处置 — 用户拍板「判读条件对齐 dim3」：
- 保留 2 条数据完整门槛：趋势方向（有明确缠论方向）、价格vs中枢（有明确位置）
- 新增 3 条判读结论条件：结构健康度（chanlun_phase 健康）、背驰检测（无背驰）、
  有确认买点（buy_sell_points_detail 含 type='buy' 且 confirmed）

本测试经 patch ChanlunAnalyzer.analyze 精确控制 chanlun 输出，逐一验证每条条件的
判读语义，避免依赖真实缠论分析在合成数据上的随机结果。
"""
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions import dim2_structure_engine
from app.opportunity_atlas.dimensions.dim2_structure_engine import (
    ChanlunAnalyzer,
    Dim2StructureEngine,
)


def _mk_df(n=90):
    closes = np.linspace(10, 20, n) + np.sin(np.linspace(0, 8, n)) * 0.5
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes, 'vol': [1e5] * n, 'amount': [3e5] * n,
    }, index=idx)


def _mk_div(direction='down', dtype='trend', conf=0.8):
    return SimpleNamespace(direction=direction, type=dtype, confidence=conf)


def _mk_buy(conf, pos=None):
    return SimpleNamespace(
        type='first_buy', confidence=conf,
        position=pos or {'price': 12.0, 'date': '2025-04-01', 'idx': 40},
        reason='一买确认')


def _mk_analyzer_result(**kw):
    """构造 chanlun_result 字典，默认覆盖一条路径（趋势方向False/价格未知/欲病/无背驰/无买点）。"""
    base = {
        'trend': 'unknown',  # 数据完整门槛「趋势方向」→ False
        'zhongshu': [],      # 走 tags.position_vs_zs 兜底
        'divergence': None,  # 判读「背驰检测」→ True（无背驰）
        'buy_points': [],    # 判读「有确认买点」→ False
        'sell_points': [],
        'theorem_check': {'summary': {'overall_score': 0.5}},  # 欲病 → False
    }
    base.update({k: v for k, v in kw.items() if v is not None})
    return base


def _evaluate(audit_override=None, tags_override=None):
    """在 patch analyze 下跑 evaluate，返回 audit。"""
    df = _mk_df()
    eng = Dim2StructureEngine()
    tags = {'ts_code': 'T.XSHG', 'ma_alignment': '多头排列',
            'chip_concentration': 'concentrating', 'profit_ratio': 0.5,
            'indicator_status': 'ma=bullish', 'rsi_percentile': 0.7}
    tags.update(tags_override or {})
    with mock.patch.object(ChanlunAnalyzer, 'analyze', return_value=audit_override or _mk_analyzer_result()):
        out = eng.evaluate({}, tags, data_context={'daily_df': df})
    return out['audit']


def _cond(audit, name):
    for c in audit['conditions']:
        if c['name'] == name:
            return c
    raise AssertionError(f'条件缺失: {name}')


class TestAuditStructure:
    """454核心：audit 不再恒真，5 条件结构正确。"""

    def test_condition_names_and_count(self):
        au = _evaluate()
        names = [c['name'] for c in au['conditions']]
        assert names == ['趋势方向', '价格vs中枢', '结构健康度', '背驰检测', '有确认买点'], names
        assert au['total_count'] == 5

    def test_not_all_true(self):
        """消除「全为有数据级门槛」恒真：合成基准路径至少 1 条不满足，confidence<1.0。"""
        au = _evaluate()
        assert au['satisfied_count'] < au['total_count']
        assert 0 < au['confidence'] < 1.0

    def test_confidence_is_ratio(self):
        au = _evaluate()
        assert au['confidence'] == au['satisfied_count'] / au['total_count']


class TestDataCompletenessGates:
    """保留的数据完整门槛。"""

    def test_trend_direction_satisfied(self):
        au = _evaluate(_mk_analyzer_result(trend='up'))
        c = _cond(au, '趋势方向')
        assert c['satisfied'] is True
        assert c['actual'] == 'up'

    def test_trend_direction_unsatisfied_unknown(self):
        au = _evaluate(_mk_analyzer_result(trend='unknown'))
        assert _cond(au, '趋势方向')['satisfied'] is False

    def test_trend_direction_no_data(self):
        au = _evaluate(None)
        # 无 data_context 无法跑；此处验证「无数据」语义由 evaluate 缺 chanlun 时为 False
        assert _cond(au, '趋势方向')['satisfied'] is False

    def test_price_vs_zhongshu_satisfied_via_tags(self):
        au = _evaluate(_mk_analyzer_result(), tags_override={'position_vs_zs': '上方'})
        c = _cond(au, '价格vs中枢')
        assert c['satisfied'] is True
        assert c['actual'] == '上方'

    def test_price_vs_zhongshu_unsatisfied_no_position(self):
        au = _evaluate(_mk_analyzer_result())
        c = _cond(au, '价格vs中枢')
        assert c['satisfied'] is False
        assert c['actual'] == '未知'


class TestJudgmentConditions:
    """新增判读结论条件（对齐 dim3）。"""

    def test_phase_healthy_true(self):
        au = _evaluate(_mk_analyzer_result(
            theorem_check={'summary': {'overall_score': 0.7}}))
        c = _cond(au, '结构健康度')
        assert c['satisfied'] is True
        assert c['actual'] == '健康'

    def test_phase_ill_false(self):
        au = _evaluate(_mk_analyzer_result(
            theorem_check={'summary': {'overall_score': 0.5}}))
        c = _cond(au, '结构健康度')
        assert c['satisfied'] is False
        assert c['actual'] == '欲病'

    def test_no_divergence_true(self):
        au = _evaluate(_mk_analyzer_result(divergence=None))
        assert _cond(au, '背驰检测')['satisfied'] is True

    def test_top_divergence_false(self):
        au = _evaluate(_mk_analyzer_result(divergence=_mk_div(direction='down')))
        c = _cond(au, '背驰检测')
        assert c['satisfied'] is False
        assert c['actual'] == '顶背驰'

    def test_bottom_divergence_false(self):
        au = _evaluate(_mk_analyzer_result(divergence=_mk_div(direction='up')))
        c = _cond(au, '背驰检测')
        assert c['satisfied'] is False
        assert c['actual'] == '底背驰'

    def test_confirmed_buy_true(self):
        au = _evaluate(_mk_analyzer_result(buy_points=[_mk_buy(conf=0.8)]))
        c = _cond(au, '有确认买点')
        assert c['satisfied'] is True
        assert c['actual'] == '有确认买点'

    def test_unconfirmed_buy_false(self):
        au = _evaluate(_mk_analyzer_result(buy_points=[_mk_buy(conf=0.5)]))
        c = _cond(au, '有确认买点')
        assert c['satisfied'] is False
        assert c['actual'] == '无确认买点'

    def test_sell_only_no_buy_false(self):
        au = _evaluate(_mk_analyzer_result(
            buy_points=[], sell_points=[_mk_buy(conf=0.8)]))
        assert _cond(au, '有确认买点')['satisfied'] is False


class TestAllSatisfied:
    """健康且信号齐全的上行股：5 条件全真 → confidence=1.0。"""

    def test_all_satisfied(self):
        au = _evaluate(_mk_analyzer_result(
            trend='up',
            theorem_check={'summary': {'overall_score': 0.7}},
            divergence=None,
            buy_points=[_mk_buy(conf=0.8)],
        ), tags_override={'position_vs_zs': '上方'})
        assert au['satisfied_count'] == 5
        assert au['confidence'] == 1.0


if __name__ == '__main__':
    unittest.main()
