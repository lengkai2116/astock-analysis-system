"""484号：448/449 数据补采落地回归测试

覆盖：
- cache_cashflow_data 列名映射（n_cashflow_act→cashflow_oper 等）+ 折旧列同名直写
- _anchor_cashflow 双侧（dim7/valuation_estimator）经营资产FCF 口径 + 回退 free_cashflow
- event_monitor 质押（>50%）/ 减持（近 90 日 DE）检测
- FinancialRiskFilter 行业黑名单（dim4 + chip_pre_filter 双份）
- FINA_FIELDS_EXTENDED 字段集订正（无非法字段、含 roic/roa）

纯逻辑验证：object.__new__ 绕过 __init__，monkeypatch _insert_from_df / 缓存读取，
不触碰任何真实数据库。
"""
import threading
from types import SimpleNamespace

import pandas as pd
import pytest

from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.data.tushare_provider import TushareProvider


@pytest.fixture()
def captured():
    """捕获传入 _insert_from_df 的 table 与映射后 df"""
    holder = {'table': None, 'df': None}
    yield holder


class TestCashflowColMap:
    """484-4：cache_cashflow_data 列名映射（根因修复）"""

    def _make_ecm(self, captured):
        ecm = object.__new__(EnhancedCacheManager)
        ecm._write_lock = threading.RLock()

        def _fake_insert(self_, table, df):
            captured['table'] = table
            captured['df'] = df.copy()
            return len(df)

        ecm._insert_from_df = lambda table, df: _fake_insert(ecm, table, df)
        return ecm

    def test_cashflow_native_cols_mapped(self, captured):
        """Tushare 原生 n_cashflow_act/n_cashflow_inv_act/n_cash_flows_fnc_act → 表列名"""
        ecm = self._make_ecm(captured)
        df = pd.DataFrame([{
            'ts_code': '600519.SH', 'end_date': '2026-06-30', 'ann_date': '2026-08-28',
            'net_profit': 3000000000.0, 'n_cashflow_act': 70690750119.06,
            'n_cashflow_inv_act': 25640543520.6, 'n_cash_flows_fnc_act': -37944297802.12,
            'free_cashflow': 36868735635.28, 'depr_fa_coga_dpba': 1019596188.09,
            'c_pay_acq_const_fiolta': 832142752.28,
        }])
        ecm.cache_cashflow_data(df)
        assert captured['table'] == 'cashflow_cache'
        d = captured['df']
        assert 'cashflow_oper' in d.columns and d.iloc[0]['cashflow_oper'] == 70690750119.06
        assert 'cashflow_inv' in d.columns and d.iloc[0]['cashflow_inv'] == 25640543520.6
        assert 'cashflow_fin' in d.columns and d.iloc[0]['cashflow_fin'] == -37944297802.12
        assert 'n_cashflow_act' not in d.columns, 'Tushare 原名不应透传'

    def test_cashflow_depr_columns_kept(self, captured):
        """484 加列 depr_fa_coga_dpba/c_pay_acq_const_fiolta 同名直写（非 rename 目标不受损）"""
        ecm = self._make_ecm(captured)
        df = pd.DataFrame([{
            'ts_code': '600519.SH', 'end_date': '2026-06-30',
            'depr_fa_coga_dpba': 1019596188.09, 'c_pay_acq_const_fiolta': 832142752.28,
            'free_cashflow': 36868735635.28,
        }])
        ecm.cache_cashflow_data(df)
        d = captured['df']
        assert d.iloc[0]['depr_fa_coga_dpba'] == 1019596188.09
        assert d.iloc[0]['c_pay_acq_const_fiolta'] == 832142752.28

    def test_cashflow_no_native_cols_untouched(self, captured):
        """无 Tushara 原生列时（已标准化输入）不破坏任何列"""
        ecm = self._make_ecm(captured)
        df = pd.DataFrame([{
            'ts_code': '000002.SZ', 'end_date': '2026-06-30',
            'cashflow_oper': 494766013.42, 'free_cashflow': -1140626040.52,
        }])
        ecm.cache_cashflow_data(df)
        d = captured['df']
        assert d.iloc[0]['cashflow_oper'] == 494766013.42


def _cf_df(oper=None, depr=None, fcf=36868735635.28):
    """构造 cashflow df（仅一行最新期）"""
    row = {'ts_code': '600519.SH', 'end_date': '2026-06-30'}
    if oper is not None:
        row['cashflow_oper'] = oper
    if depr is not None:
        row['depr_fa_coga_dpba'] = depr
    if fcf is not None:
        row['free_cashflow'] = fcf
    return pd.DataFrame([row])


def _bs_df(ta=2e12, cl=5e11):
    return pd.DataFrame([{'ts_code': '600519.SH', 'end_date': '2026-06-30',
                          'total_assets': ta, 'current_liab': cl, 'total_liab': 1.5e12,
                          'money_cap': 2e11}])


class TestAnchorCashflowFCF:
    """484-4：_anchor_cashflow 双侧经营资产FCF 口径（449 已拍板）"""

    def test_dim7_oper_minus_depr(self):
        """dim7：cashflow_oper - depr_fa_coga_dpba 为经营资产FCF"""
        from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine
        eng = object.__new__(Dim7ValuationEngine)
        eng._fcf_percentile = None
        basic = pd.DataFrame([{'ts_code': '600519.SH', 'total_mv': 2000000.0}])
        cf = _cf_df(oper=7e10, depr=1e9)
        score = eng._anchor_cashflow(basic, cf, _bs_df(), '蓝筹')
        # FCF=6.9e10, EV=total_mv*1e4+总负债-现金=2e10+1.5e12-2e11=1.32e12 → yield=5.23%
        assert score > 0, '经营资产FCF 收益为正应给正分'

    def test_dim7_fallback_free_cashflow(self):
        """dim7：缺折旧列/值 → 回退教科书 free_cashflow（不阻塞）"""
        from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine
        eng = object.__new__(Dim7ValuationEngine)
        eng._fcf_percentile = None
        basic = pd.DataFrame([{'ts_code': '600519.SH', 'total_mv': 2000000.0}])
        # fcf=1e11 → yield≈7.6% > 国债+3% → 正分（证明回退值被使用而非返回 0 兜底）
        cf = _cf_df(oper=7e10, depr=None, fcf=1.0e11)
        score = eng._anchor_cashflow(basic, cf, _bs_df(), '蓝筹')
        assert score > 0, '回退 free_cashflow 应参与计算并给正分'

    def test_valuation_estimator_oper_minus_depr(self):
        """valuation_estimator：双侧同步经营资产FCF 口径"""
        from app.opportunity_atlas.valuation_estimator import ValuationEngine
        eng = object.__new__(ValuationEngine)
        eng._fcf_percentile = None
        basic = pd.DataFrame([{'ts_code': '600519.SH', 'total_mv': 2000000.0}])
        cf = _cf_df(oper=7e10, depr=1e9)
        score = eng._anchor_cashflow(basic, cf, _bs_df(), '蓝筹')
        assert score > 0

    def test_financial_returns_zero(self):
        """金融行业跳过现金流锚（双侧既有语义保持）"""
        from app.opportunity_atlas.valuation_estimator import ValuationEngine
        eng = object.__new__(ValuationEngine)
        eng._fcf_percentile = None
        basic = pd.DataFrame([{'ts_code': '600519.SH', 'total_mv': 2000000.0}])
        assert eng._anchor_cashflow(basic, _cf_df(), _bs_df(), '金融') == 0.0


class _FakeCache:
    def __init__(self, pledge_df=None, ht_df=None):
        self._p = pledge_df
        self._h = ht_df

    def get_cached_pledge_stat(self, code):
        return self._p

    def get_cached_stk_holdertrade(self, code):
        return self._h


def _detector(monkeypatch, cache):
    from app.opportunity_atlas.event_monitor import EventMonitor
    mon = object.__new__(EventMonitor)
    mon._get_dm = lambda: SimpleNamespace(cache=cache)
    return mon


class TestPledgeDetector:
    """484-1：质押>50% 检出"""

    def test_high_pledge_detected(self, monkeypatch):
        cache = _FakeCache(pledge_df=pd.DataFrame([
            {'ts_code': '000002.SZ', 'end_date': '2026-09-18', 'pledge_ratio': 60.5},
        ]))
        r = _detector(monkeypatch, cache)._detect_pledge_risk('000002.SZ')
        assert r['detected'] is True
        assert r['direction'] == -1
        assert '60.5' in r['description']

    def test_low_pledge_not_detected(self, monkeypatch):
        cache = _FakeCache(pledge_df=pd.DataFrame([
            {'ts_code': '600519.SH', 'end_date': '2026-09-18', 'pledge_ratio': 0.06},
        ]))
        r = _detector(monkeypatch, cache)._detect_pledge_risk('600519.SH')
        assert r['detected'] is False

    def test_no_data_not_detected(self, monkeypatch):
        r = _detector(monkeypatch, _FakeCache(pledge_df=None))._detect_pledge_risk('000001.SZ')
        assert r['detected'] is False


class TestHolderReduceDetector:
    """484-2：近 90 日减持检出"""

    def test_recent_reduce_detected(self, monkeypatch):
        cache = _FakeCache(ht_df=pd.DataFrame([
            {'ts_code': '000007.SZ', 'ann_date': '2026-09-20', 'holder_name': '某股东',
             'in_de': 'DE', 'change_ratio': 4.98},
        ]))
        r = _detector(monkeypatch, cache)._detect_holder_reduce('000007.SZ')
        assert r['detected'] is True
        assert r['direction'] == -1
        assert '某股东' in r['description']

    def test_old_reduce_not_detected(self, monkeypatch):
        """2026-01 的减持超出 90 日窗口 → 不检出"""
        cache = _FakeCache(ht_df=pd.DataFrame([
            {'ts_code': '000007.SZ', 'ann_date': '2026-01-10', 'holder_name': '某股东',
             'in_de': 'DE', 'change_ratio': 4.98},
        ]))
        r = _detector(monkeypatch, cache)._detect_holder_reduce('000007.SZ')
        assert r['detected'] is False

    def test_increase_not_detected(self, monkeypatch):
        """in_de=IN（增持）不触发减持检测"""
        cache = _FakeCache(ht_df=pd.DataFrame([
            {'ts_code': '000007.SZ', 'ann_date': '2026-09-20', 'holder_name': '某股东',
             'in_de': 'IN', 'change_ratio': 4.98},
        ]))
        r = _detector(monkeypatch, cache)._detect_holder_reduce('000007.SZ')
        assert r['detected'] is False


class TestIndustryBlacklist:
    """484-3：东财行业黑名单（仅黑名单最小口径，用户拍板）"""

    def _risk_filter(self, industry):
        dm = SimpleNamespace(get_stock_info=lambda code: {'industry': industry})
        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import FinancialRiskFilter
        f = object.__new__(FinancialRiskFilter)
        f.data_manager = dm
        return f

    def test_real_estate_blacklisted(self):
        r = self._risk_filter('全国地产')._check_industry_risk('000002.SZ')
        assert r['passed'] is False
        assert '行业雷' in r['reason']

    def test_normal_industry_passes(self):
        r = self._risk_filter('白酒')._check_industry_risk('600519.SH')
        assert r['passed'] is True

    def test_no_industry_passes(self):
        r = self._risk_filter(None)._check_industry_risk('000001.SZ')
        assert r['passed'] is True

    def test_chip_pre_filter_synced(self):
        """chip_pre_filter 双份同黑名单"""
        from app.engine.framework.chip_pre_filter import FinancialRiskFilter as FRF
        from app.engine.framework.chip_pre_filter import INDUSTRY_RISK_BLACKLIST
        assert '全国地产' in INDUSTRY_RISK_BLACKLIST
        dm = SimpleNamespace(get_stock_info=lambda code: {'industry': '区域地产'})
        f = object.__new__(FRF)
        f.data_manager = dm
        assert f._check_industry_risk('000002.SZ')['passed'] is False

    def test_blacklist_contains_core_real_estate(self):
        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import INDUSTRY_RISK_BLACKLIST
        for ind in ['全国地产', '区域地产', '房产服务', '园区开发', '装修装饰']:
            assert ind in INDUSTRY_RISK_BLACKLIST, ind


class TestFinaFieldsExtended:
    """484-5：FINA_FIELDS_EXTENDED 字段集订正"""

    def test_no_invalid_fina_indicator_fields(self):
        fields = TushareProvider.FINA_FIELDS_EXTENDED
        for bad in ['roce', 'operating_profit', 'current_liab', 'total_assets',
                    'total_liab', 'current_assets']:
            assert bad not in fields, f'{bad} 非 fina_indicator 字段不应请求'

    def test_contains_roic_roa_ebit(self):
        fields = TushareProvider.FINA_FIELDS_EXTENDED
        for good in ['roic', 'roa', 'ebit', 'debt_to_assets', 'asset_liab_ratio']:
            assert good in fields, f'{good} 应保留'

    def test_gross_margin_semantics_documented(self):
        """gross_margin 为毛利额(元)非毛利率%——不加入扩展字段避免误导（探针实证）"""
        fields = TushareProvider.FINA_FIELDS_EXTENDED
        assert 'gross_margin' not in fields
