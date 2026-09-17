"""452号：dim6 流动性口径 + 波动率「机会而非风险」处置测试

445 §6.3 dim6 两条偏差：
  1. 波动率当风险源 —— KB《风险定义（纳兰达版）》「波动是机会而非风险」，
     高波动不应计入 risk_level/risk_factors（ATR 仅作参考信息，不再进判断）。
  2. 流动性口径不符 —— KB《量化财务门槛/风险剔除逻辑体系》门槛 =
     日均成交额>5000万 + 流通市值>30亿；原实现用「换手率<1%」当流动性风险源。

修复（用户拍板：波动率从风险源摘除 + 流动性改双门槛）：
  - _assess_liquidity 纯函数：成交额<5000万 或 流通市值<30亿 → 触发流动性风险
    （单位：daily_df.amount=千元→/10=万元；daily_basic.circ_mv=万元）。
  - _assess_risk_level / _list_risk_factors 移除 `volatility_level=='high'` 判据，
    流动性改用 liquidity_info 双门槛。
  - status_description 增 liquidity_risk/liquidity_detail/avg_amount_wan/circ_mv_wan；
    audit「波动率」条件替换为「流动性」。

注：本测试全部注入 data_context（daily_df + daily_basic_df），不触发真实 DB
回退查询（开发态基准库有写锁，避免与 daemon 的 SQLite 锁竞争）。
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions.dim6_risk_engine import (
    Dim6RiskEngine, _assess_liquidity, _assess_risk_level, _list_risk_factors,
)


def _mk_df(n=70, amount_wan=30000.0):
    """构造 daily_df：amount 列为 Tushare 口径（千元）。

    amount_wan 以「万元/日」传入 → 每行千元 = amount_wan * 10
    （1 万元 = 10 千元；与 332 号 P0 单位对齐）。
    默认 30000 万元/日 = 3 亿元/日，流动性充足。
    """
    rng = np.random.RandomState(0)
    closes = np.linspace(10, 20, n)
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    qianyuan_per_day = amount_wan * 10.0
    amt = [qianyuan_per_day] * n
    return pd.DataFrame({
        'ts_code': 'TEST.XSHG', 'open': closes,
        'high': closes * 1.01, 'low': closes * 0.99,
        'close': closes, 'vol': [1e5] * n, 'amount': amt,
    }, index=idx)


def _mk_basic(circ_mv_wan=500000.0):
    """构造 daily_basic_df：circ_mv 单位万元（500000 万元 = 50 亿，默认充足）"""
    return pd.DataFrame({
        'ts_code': ['TEST.XSHG'], 'trade_date': ['2026-09-15'],
        'circ_mv': [circ_mv_wan],
    })


_P_TAGS_BASE = {'risk_level': 'LOW', 'fina_health': 'good', 'catalyst_event': 'none',
                'main_force_phase': 'accumulating', 'volatility_level': 'low',
                'debt_to_assets': 40.0, 'roce': 20.0}  # debt_to_assets/roce 短路 PIERS-E DB 回退


class TestLiquidityAssessment:
    """_assess_liquidity 纯函数：KB 双门槛（成交额 + 流通市值）"""

    def test_liquidity_ok_when_amount_and_circ_above(self):
        """成交额充足 + 流通市值充足 → 不触发"""
        r = _assess_liquidity(_mk_df(amount_wan=60000), _mk_basic(500000))
        assert r['triggered'] is False

    def test_liquidity_triggers_when_amount_low(self):
        """日均成交额 <5000万（1000万）→ 触发"""
        r = _assess_liquidity(_mk_df(amount_wan=1000), _mk_basic(500000))
        assert r['triggered'] is True
        assert '成交额' in r['detail']

    def test_liquidity_triggers_when_circ_mv_low(self):
        """流通市值 <30亿（10亿）→ 触发"""
        r = _assess_liquidity(_mk_df(amount_wan=60000), _mk_basic(100000))
        assert r['triggered'] is True
        assert '流通市值' in r['detail']

    def test_liquidity_no_data_is_ok(self):
        """无 amount / 无 circ_mv 数据 → 不触发（保守，无数据不惩罚）"""
        r = _assess_liquidity(None, None)
        assert r['triggered'] is False

    def test_amount_unit_wan_conversion(self):
        """amount 千元 → 万元换算正确（332号单位教训）"""
        # 3e7 千元 = 3000 万元
        r = _assess_liquidity(_mk_df(amount_wan=3000), _mk_basic(500000))
        assert abs(r['avg_amount_wan'] - 3000.0) < 0.1


class TestVolatilityRemovedFromRisk:
    """波动率从风险源摘除（KB：波动是机会而非风险）"""

    def test_volatility_high_not_in_risk_sources(self):
        """volatility_level=high 不再计入 risk_sources 高风险"""
        tags = dict(_P_TAGS_BASE, volatility_level='high')
        ri = _assess_risk_level(tags, liquidity_info={'triggered': False})
        names = [s['name'] for s in ri['risk_sources']]
        assert '波动率风险' not in names

    def test_volatility_high_does_not_raise_level(self):
        """仅高波动（其它全低）→ risk_level 仍为低"""
        tags = dict(_P_TAGS_BASE, volatility_level='high')
        ri = _assess_risk_level(tags, liquidity_info={'triggered': False})
        assert ri['level'] == '低'

    def test_volatility_high_not_in_risk_factors(self):
        """volatility_level=high 不再生成风险因子"""
        factors = _list_risk_factors(dict(_P_TAGS_BASE, volatility_level='high'),
                                     liquidity_info={'triggered': False})
        cats = [f['category'] for f in factors]
        assert '波动率' not in cats


class TestLiquidityInRisk:
    """流动性（KB 双门槛）计入 risk_level/risk_factors"""

    def test_liquidity_high_in_risk_sources(self):
        """流动性触发 → risk_sources 含流动性风险"""
        ri = _assess_risk_level(_P_TAGS_BASE, liquidity_info={'triggered': True})
        names = [s['name'] for s in ri['risk_sources']]
        assert '流动性风险' in names

    def test_liquidity_triggers_low_high_raises_level(self):
        """流动性触发 + 另一风险源 → risk_level 升中/高"""
        tags = dict(_P_TAGS_BASE, risk_level='HIGH')
        ri = _assess_risk_level(tags, liquidity_info={'triggered': True})
        assert ri['level'] == '高'

    def test_liquidity_in_risk_factors(self):
        """流动性触发 → risk_factors 含「流动性不足」"""
        liq = _assess_liquidity(_mk_df(amount_wan=1000), _mk_basic(500000))
        factors = _list_risk_factors(_P_TAGS_BASE, liquidity_info=liq)
        cats = [f['category'] for f in factors]
        assert '流动性' in cats


class TestEvaluateWiring:
    """evaluate 接线（data_context 注入，避免 DB 回退）"""

    def test_evaluate_liquidity_output(self):
        """data_context 含充足流动性 → status_description 暴露流动性达标"""
        eng = Dim6RiskEngine()
        out = eng.evaluate({}, dict(_P_TAGS_BASE, ts_code='TEST'),
                           data_context={'daily_df': _mk_df(amount_wan=60000),
                                        'daily_basic_df': _mk_basic(500000)})
        s = out['status_description']
        assert 'liquidity_risk' in s
        assert s['liquidity_risk'] is False

    def test_evaluate_low_liquidity_flags_risk(self):
        """低成交额 + 小流通市值 → liquidity_risk=True，audit 流动性不满足"""
        eng = Dim6RiskEngine()
        out = eng.evaluate({}, dict(_P_TAGS_BASE, ts_code='TEST'),
                           data_context={'daily_df': _mk_df(amount_wan=1000),
                                        'daily_basic_df': _mk_basic(100000)})
        s = out['status_description']
        assert s['liquidity_risk'] is True
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '流动性')
        assert cond['satisfied'] is False

    def test_evaluate_audit_has_liquidity_no_volatility(self):
        """audit conditions 应含「流动性」、不再含「波动率」"""
        eng = Dim6RiskEngine()
        out = eng.evaluate({}, dict(_P_TAGS_BASE, ts_code='TEST'),
                           data_context={'daily_df': _mk_df(amount_wan=60000),
                                        'daily_basic_df': _mk_basic(500000),
                                        'daily_basic_df2': None})
        names = [c['name'] for c in out['audit']['conditions']]
        assert '流动性' in names
        assert '波动率' not in names


class TestSourceWiring:
    """源码接线（沿用 dim6/dim3 既有的源码-inspect 手法）"""

    def test_engine_has_liquidity_and_no_volatility_risk_source(self):
        import inspect
        src_assess = inspect.getsource(_assess_risk_level)
        # 波动率不再作为风险源
        assert "volatility_level" not in src_assess
        # 流动性走 liquidity_info
        assert 'liquidity_info' in src_assess

    def test_engine_has_liquidity_function(self):
        import inspect
        src = inspect.getsource(_assess_liquidity)
        # 门槛常量在模块级（_LIQUIDITY_MIN_*）；函数体内引用常量名
        assert '_LIQUIDITY_MIN_AVG_AMOUNT_WAN' in src
        assert '_LIQUIDITY_MIN_CIRC_MV_WAN' in src
        from app.opportunity_atlas.dimensions import dim6_risk_engine as m
        assert m._LIQUIDITY_MIN_AVG_AMOUNT_WAN == 5000.0
        assert m._LIQUIDITY_MIN_CIRC_MV_WAN == 300000.0

    def test_evaluate_precomputes_liquidity(self):
        import inspect
        src = inspect.getsource(Dim6RiskEngine.evaluate)
        assert '_assess_liquidity(' in src
        assert 'daily_basic_df' in src
