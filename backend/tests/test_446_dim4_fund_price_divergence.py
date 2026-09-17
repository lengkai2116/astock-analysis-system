"""446号：dim4 资金×价格背离缺失修复单元测试

445 §6.1 dim4「资金×价格背离缺失」→ PhaseDetectionEngine 已算 trend_alignment
与 fund_flow，但 Dim4ChipFundEngine.evaluate 从不交叉判定 → 拉抬出货/顶部背离
（危险回避信号）与底部吸筹信号静默缺失。

修复：新增 `_assess_fund_price_divergence(fund_flow, price_direction)` 模块函数
+ evaluate 接线产 `fund_price_divergence`/`_status`/`_risk` 三键 + audit 条件 + plain 文案。

wiki《筹码分布分析-主力视角》权威：
  - 连续卖超（流出）+ 股价上涨 → 拉抬出货/散户接盘（危险信号，回避）
  - 连续买超（流入）+ 股价下跌 → 底部吸筹/逆势建仓（看多）
  - 买超+价涨 / 卖超+价跌 → 同向一致
"""
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import _assess_fund_price_divergence


def _flow(direction):
    """资金流向 dict（_assess_fund_flow 形）"""
    return {'direction': direction, 'level_cn': '强流入' if direction == 'inflow' else '强流出',
            'detail': '大单5日净流入' if direction == 'inflow' else '大单5日净流出'}


class TestFundPriceDivergence:
    """_assess_fund_price_divergence 各分支"""

    def test_aligned_inflow_up(self):
        """资金流入+股价上涨 → 同向，无背离"""
        r = _assess_fund_price_divergence(_flow('inflow'), 'up')
        assert r['status'] == 'aligned' and r['risk'] == '无'

    def test_aligned_outflow_down(self):
        """资金流出+股价下跌 → 同向，无背离"""
        r = _assess_fund_price_divergence(_flow('outflow'), 'down')
        assert r['status'] == 'aligned' and r['risk'] == '无'

    def test_danger_outflow_up(self):
        """资金流出+股价上涨 → 拉抬出货/散户接盘（危险回避）"""
        r = _assess_fund_price_divergence(_flow('outflow'), 'up')
        assert r['status'] == 'divergence'
        assert r['direction'] == 'bearish'
        assert r['risk'] == '危险'
        assert '拉抬出货' in r['label']

    def test_accumulation_inflow_down(self):
        """资金流入+股价下跌 → 底部吸筹/逆势建仓（看多）"""
        r = _assess_fund_price_divergence(_flow('inflow'), 'down')
        assert r['status'] == 'divergence'
        assert r['direction'] == 'bullish'
        assert r['risk'] == '提示'
        assert '吸筹' in r['label']

    def test_neutral_fund_no_conclusion(self):
        """资金方向中性 → 数据不足，不产背离结论"""
        r = _assess_fund_price_divergence(_flow('neutral'), 'up')
        assert r['status'] == 'none' and r['risk'] == '无'

    def test_unknown_price_no_conclusion(self):
        """价格方向非 up/down（mixed/no_trend）→ 数据不足"""
        for pd_ in ('mixed', 'no_trend', ''):
            r = _assess_fund_price_divergence(_flow('inflow'), pd_)
            assert r['status'] == 'none' and r['risk'] == '无', pd_


class TestEvaluateWiring:
    """evaluate 接线（源码级，沿用 dim4 既有测试手法）"""

    def test_evaluate_has_divergence_wiring(self):
        import inspect
        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import Dim4ChipFundEngine
        src = inspect.getsource(Dim4ChipFundEngine.evaluate)
        assert "_assess_fund_price_divergence(" in src
        assert "'fund_price_divergence'" in src
        assert "'trend_alignment'" in src
