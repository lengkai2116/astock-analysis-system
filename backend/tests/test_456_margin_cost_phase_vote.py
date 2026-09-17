"""456号测试：dim4 融资成本价进阶段投票（wiki《融资成本价》解套压力位语义）+ framework 双份同步

覆盖：
  TestApplyMarginSignal   —— ① _apply_margin_signal 三分支（站上→lifting / 深套→building / 中间→washing）
  TestDimSsrpMarginVote   —— ② _dim_ssrp 集成：cost_ext.margin_cost_price 作弱补充叠加，不覆盖主规则
  TestFrameworkMarginCost —— ③ framework _score_chip_distribution 现价站上融资成本价→做多加 0.2
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine
from app.engine.framework.chip_strategy import MainForceScorer


def _mk_close(close: float) -> pd.DataFrame:
    return pd.DataFrame({'close': [close * 0.9, close * 0.95, close]})


class TestApplyMarginSignal:
    """_apply_margin_signal 弱补充分支"""

    def _run(self, current, mcp, base):
        pde = PhaseDetectionEngine()
        return pde._apply_margin_signal(dict(base), current, {'margin_cost_price': mcp})

    def test_above_cost_boosts_lifting(self):
        """现价 ≥ 融资成本价×1.05（站上/突破解套压力位）→ lifting +0.2"""
        out = self._run(current=11.0, mcp=10.0, base={'washing': 0.3})
        assert out['lifting'] == 0.2, out
        assert out['washing'] == 0.3  # 原票保留

    def test_below_cost_deep_boosts_building(self):
        """现价 ≤ 融资成本价×0.85（融资盘深套，安全边际）→ building +0.1"""
        out = self._run(current=8.0, mcp=10.0, base={'washing': 0.3})
        assert out['building'] == 0.1, out

    def test_mid_zone_boosts_washing(self):
        """中间区（成本位下方/附近承压，反弹遇解套抛压）→ washing +0.2"""
        out = self._run(current=9.0, mcp=10.0, base={'building': 0.3})
        assert out['washing'] == 0.2, out
        assert out['building'] == 0.3

    def test_no_own_washing_creates_key(self):
        """中间区且原向量无 washing → 补建该键"""
        out = self._run(current=9.5, mcp=10.0, base={'lifting': 0.4})
        assert out['washing'] == 0.2, out

    def test_missing_mcp_unchanged(self):
        """margin_cost_price 缺失/非正 → 原向量原样返回"""
        pde = PhaseDetectionEngine()
        base = {'washing': 0.3}
        assert pde._apply_margin_signal(dict(base), 9.0, {'margin_cost_price': None}) == base
        assert pde._apply_margin_signal(dict(base), 9.0, {'margin_cost_price': 0}) == base
        assert pde._apply_margin_signal(dict(base), 9.0, None) == base


class TestDimSsrpMarginVote:
    """_dim_ssrp 集成 margin_cost_price 弱叠加"""

    def test_far_cost_with_above_margin_votes_lifting(self):
        """主力成本远离（不触发近距），但现价站上融资成本价 → lifting 弱加分"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 14.0}  # rel=0.71 → 主规则 building
        cost_ext = {'main_force_cost': 20.0, 'margin_cost_price': 9.0}  # 现价 10 > 9*1.05 → lifting+0.2
        out = pde._dim_ssrp(df, tags, cost_ext=cost_ext)
        assert out['building'] == 0.3
        assert out['lifting'] == 0.2, out

    def test_near_cost_and_above_margin_keeps_washing_adds_lifting(self):
        """近主线（443 R2 洗盘增强）叠加上方融资信号 → washing 主 + lifting 弱补充"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 9.0}
        cost_ext = {'main_force_cost': 10.2, 'margin_cost_price': 9.2}
        out = pde._dim_ssrp(df, tags, cost_ext=cost_ext)
        assert out['washing'] >= 0.5, out          # 近距增强主票
        assert out['lifting'] == 0.2, out           # 站上融资成本价弱补充

    def test_above_ssrp_float_adds_margin(self):
        """主规则 lifting 分支叠加上方融资信号 → lifting 增强"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 7.0}  # rel=1.43 → lifting 主
        cost_ext = {'main_force_cost': 20.0, 'margin_cost_price': 8.0}
        out = pde._dim_ssrp(df, tags, cost_ext=cost_ext)
        assert out.get('lifting', 0) >= 0.5 + 0.2 - 0.001, out

    def test_no_margin_in_cost_ext_unchanged(self):
        """cost_ext 只有 main_force_cost → 行为与 443 R2 一致（无 margin 叠加）"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 9.0}
        out = pde._dim_ssrp(df, tags, cost_ext={'main_force_cost': 20.0})
        assert out == {}, out


class TestCostValueDictCompat:
    """_cost_value：归一化 precompute_raw 完整返回 dict 与标量双形态"""

    def test_dict_price_value(self):
        """真实库 main_force_cost={'cost_price':..,'distance_pct':..,'near_cost':..} 取 cost_price"""
        pde = PhaseDetectionEngine()
        assert pde._cost_value({'cost_price': 10.2, 'distance_pct': 0.0, 'near_cost': True}) == 10.2

    def test_dict_null_price_returns_zero(self):
        """margin_cost_price={'cost_price':None,..} → 0（不可用）"""
        pde = PhaseDetectionEngine()
        assert pde._cost_value({'cost_price': None, 'distance_pct': None}) == 0.0

    def test_scalar_value(self):
        """单测惯用标量仍支持"""
        pde = PhaseDetectionEngine()
        assert pde._cost_value(9.0) == 9.0
        assert pde._cost_value('10.5') == 10.5

    def test_none_or_invalid(self):
        """None / 空 dict / 非法 → 0"""
        pde = PhaseDetectionEngine()
        assert pde._cost_value(None) == 0.0
        assert pde._cost_value({}) == 0.0

    def test_dim_ssrp_with_real_dict_structure(self):
        """真实 precompute_raw dict 结构下 _dim_ssrp 近距增强正常命中（不再因 dict 崩溃）"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 9.0}
        cost_ext = {
            'main_force_cost': {'cost_price': 10.2, 'distance_pct': -1.5, 'near_cost': True},
            'margin_cost_price': {'cost_price': 9.3, 'distance_pct': 7.5},
        }
        out = pde._dim_ssrp(df, tags, cost_ext=cost_ext)
        assert 'washing' in out, out          # 近距增强命中（若崩则空/异常）
        assert 'lifting' in out, out           # 现价站上 margin cost_price → 弱补


class TestFrameworkMarginCost:
    """framework _score_chip_distribution：现价站上融资成本价→做多加 0.2（双份同步）"""

    def test_score_chip_distribution_consumes_storage(self):
        src = __import__('inspect').getsource(MainForceScorer._score_chip_distribution)
        assert '_calc_margin_cost_price' in src
        assert 'current_price > mcp * 1.05' in src

    def test_standing_above_margin_cost_adds(self):
        """站上融资成本价 → 加分（mock _calc_margin_cost_price）"""
        scorer = object.__new__(MainForceScorer)
        scorer._chip_indicators = None
        scorer._chip_bins = None
        scorer._calc_margin_cost_price = (lambda symbol, latest_close:
                                          {'cost_price': 9.0, 'distance_pct': 11.1})
        data = pd.DataFrame({
            'close': np.full(60, 10.0),  # 现价 10 > 9*1.05
            'vol': np.full(60, 10000.0),
        })
        base = {
            'asr': 50, 'ssrp': 12.0,  # 现价 10 vs ssrp 12 → 偏离 16.7% → 无 ssrp 加分
            'cyqkl': 0.05, 'concentration': 20,
        }
        out_plus = scorer._score_chip_distribution('TEST', data, chip_fund_ext=base)
        # 对比：融资成本价低于现价（9）才加分；若成本高于现价则不加
        scorer2 = object.__new__(MainForceScorer)
        scorer2._chip_indicators = None
        scorer2._chip_bins = None
        scorer2._calc_margin_cost_price = (lambda symbol, latest_close:
                                          {'cost_price': 12.0, 'distance_pct': -16.7})
        out_no = scorer2._score_chip_distribution('TEST', data, chip_fund_ext=base)
        assert out_plus > out_no, (out_plus, out_no)
        assert abs(out_plus - out_no - 0.2) < 1e-9, (out_plus, out_no)
