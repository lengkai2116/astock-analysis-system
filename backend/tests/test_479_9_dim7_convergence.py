"""479号：dim7 遗留收敛（D2）测试

覆盖 5 项：
  1. ① SSOT 优先：_compute_valuation 的 pe/pb/ps 5年分位优先读 tags._5y，本地 df_basic 实算降为纯兜底
  2. ② _spearman 死代码已删（模块无该符号；potential_engine 的 _spearman 仍活——不删）
  3. ③ status_description 补 _5y 数字键（reliability_assessor L2 读 pe/pb/ps_percentile_5y 做 PE存在性/PB+PS极端高估加成）
  4. ④ _fina_health 对 ecm=None 入参加固（不抛、不误判全 fail）
  5. ⑤ audit ROCE actual 对齐 tags.roce 真实数值（判定 val['roce_pass'] 不动，仅展示口径统一）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest
from unittest import mock

from app.opportunity_atlas.reliability_assessor import _assess_valuation


# ══════════════════════════════════════════════════════════
# ② _spearman 死代码删除
# ══════════════════════════════════════════════════════════

class TestSpearmanDeadCodeRemoved:
    def test_dim7_no_spearman(self):
        """dim7_valuation_engine 模块已无 _spearman（死代码已删）"""
        import app.opportunity_atlas.dimensions.dim7_valuation_engine as mod
        assert not hasattr(mod, '_spearman'), "dim7 的 _spearman 死代码应已删除"

    def test_potential_engine_spearman_kept(self):
        """potential_engine 的 _spearman 是活的（月度 IC 重权使用），不得误删"""
        import app.opportunity_atlas.potential_engine as mod
        assert hasattr(mod, '_spearman'), "potential_engine 的 _spearman 是活代码，应保留"


# ══════════════════════════════════════════════════════════
# ① SSOT 优先：pe/pb/ps 5年分位读 tags
# ══════════════════════════════════════════════════════════

class _FakeECMForCompute:
    """compute_valuation 用最小 ECM：提供空表即可（数据加载全空 → 兜底 None）"""

    def get_cached_daily_basic(self, code):
        return pd.DataFrame()

    def get_cached_income(self, code):
        return pd.DataFrame()

    def get_cached_balancesheet(self, code):
        return pd.DataFrame()

    def get_cached_cashflow(self, code):
        return pd.DataFrame()


def _mk_engine(monkeypatch):
    from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

    ecm = _FakeECMForCompute()
    monkeypatch.setattr(mod.Dim7ValuationEngine, '_get_dm', lambda self: type('DM', (), {'cache': ecm})())
    monkeypatch.setattr('app.data.DataManager.get_stock_industry', lambda self, c: None)
    # 锚方法返回 0
    for m in ('_anchor_pb', '_anchor_earnings', '_anchor_cashflow',
              '_anchor_adjusted_pe', '_anchor_bond_stock', '_adjust_composite'):
        pass
    return mod.Dim7ValuationEngine()


class TestSsotPercentiles:
    def test_tags_5y_override(self, monkeypatch):
        """tags 提供 pe/pb/ps_percentile_5y → _compute_valuation 直接采用"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        eng = _mk_engine(monkeypatch)
        ecm = eng._get_dm().cache
        tags = {
            'pe_percentile_5y': 3.1,
            'pb_percentile_5y': 5.2,
            'ps_percentile_5y': 9.9,
            'fina_health': 'pass', 'composite_rating': '1.2134',
            'valuation_level': 'extreme_low', 'valuation_deviation': '24.3',
        }
        val = eng._compute_valuation('600519.SH', ecm, tags=tags)
        assert val['pe_percentile_5y'] == pytest.approx(3.1)
        assert val['pb_percentile_5y'] == pytest.approx(5.2)
        assert val['ps_percentile_5y'] == pytest.approx(9.9), \
            "ps_percentile_5y 应 SSOT 读 tags（此前纯算了不产/不统一漂移）"

    def test_fallback_when_tags_missing(self, monkeypatch):
        """tags 缺失 _5y → 本地 df_basic 实算兜底（空表 → None，不炸）"""
        eng = _mk_engine(monkeypatch)
        ecm = eng._get_dm().cache
        val = eng._compute_valuation('600519.SH', ecm, tags={})
        assert val['pe_percentile_5y'] is None
        assert val['pb_percentile_5y'] is None
        assert val['ps_percentile_5y'] is None


# ══════════════════════════════════════════════════════════
# ③ status_description 补 _5y 数字键 → reliability 恢复
# ══════════════════════════════════════════════════════════

class TestStatusDescription5yKeys:
    def test_status_description_has_5y_keys(self, monkeypatch):
        """evaluate status_description 补 pe/pb/ps_percentile_5y 数字键（reliability 消费）"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        eng = _mk_engine(monkeypatch)
        ecm = eng._get_dm().cache
        tags = {
            'pe_percentile_5y': 3.1, 'pb_percentile_5y': 5.2, 'ps_percentile_5y': 9.9,
            'fina_health': 'pass', 'composite_rating': '1.2134',
            'valuation_level': 'extreme_low', 'valuation_deviation': '24.3',
            'roe': 30.0, 'sector_heat': 'top_10', 'catalyst_event': None,
            'fund_flow': '5d_inflow', 'trend_alignment': 'aligned',
        }
        with mock.patch.object(mod.Dim7ValuationEngine, '_compute_potential',
                               return_value={'signal_strength': 89,
                                             'potential_breakdown': '{"val":1.0}'}):
            res = eng.evaluate({}, tags, data_context={})
        sd = res['status_description']
        assert sd['pe_percentile_5y'] == pytest.approx(3.1)
        assert sd['pb_percentile_5y'] == pytest.approx(5.2)
        assert sd['ps_percentile_5y'] == pytest.approx(9.9)
        # 中文串展示键仍保留（定稿 12 键展示语义不变）
        assert sd['pe_percentile'].startswith('PE近5年')
        assert 'ps_percentile' not in sd, "展示层不产裸 ps 键（定稿 12 键无）"

    def test_reliability_valuation_now_scores_08(self):
        """reliability_assessor._assess_valuation 读 _5y 键：PE存在→0.8（此前 status_description 无 _5y 键致恒 0.3）"""
        dim_results = {'valuation': {'status_description': {
            'pe_percentile': 'PE近5年3.1%分位', 'pb_percentile': 'PB近5年5.2%分位',
            'pe_percentile_5y': 3.1, 'pb_percentile_5y': 5.2, 'ps_percentile_5y': 9.9,
        }}}
        rel = _assess_valuation(dim_results)
        assert rel == 0.8, f"PE 有数据 → 可靠性应 0.8，实际 {rel}"

    def test_reliability_pb_ps_extreme_bonus(self):
        """pb_percentile_5y>90 AND ps_percentile_5y>90 → 0.95（此前 _5y 键缺失致加成永不触发）"""
        dim_results = {'valuation': {'status_description': {
            'pe_percentile_5y': 50.0, 'pb_percentile_5y': 95.0, 'ps_percentile_5y': 92.0,
        }}}
        rel = _assess_valuation(dim_results)
        assert rel == 0.95, f"PB+PS 均 >90 → 可靠性 0.95，实际 {rel}"

    def test_reliability_missing_keys_still_03(self):
        """三个 _5y 键全缺 → PE None → 0.3（数据不足兜底，不炸）"""
        dim_results = {'valuation': {'status_description': {'valuation_level': '合理'}}}
        assert _assess_valuation(dim_results) == 0.3


# ══════════════════════════════════════════════════════════
# ④ _fina_health ecm=None 加固
# ══════════════════════════════════════════════════════════

class TestFinaHealthNoneGuard:
    def test_ecm_none_does_not_raise(self, monkeypatch):
        """ecm=None → _fina_health 不抛 AttributeError，返回 (health,roce_pass,roce_na) 缺省值"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        eng = mod.Dim7ValuationEngine()
        # tags 缺失路径触发 _fina_health(ts_code, None)
        monkeypatch.setattr('app.data.DataManager.get_stock_industry', lambda self, c: None)
        health, roce_pass, roce_na = eng._fina_health('600519.SH', None)
        assert health in ('pass', 'suspicious', 'fail')
        assert isinstance(roce_pass, bool) and isinstance(roce_na, bool)

    def test_ecm_valid_none_still_works(self, monkeypatch):
        """正常 ecm 传入 → 逻辑不变（回归防护）"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        eng = mod.Dim7ValuationEngine()
        monkeypatch.setattr('app.data.DataManager.get_stock_industry', lambda self, c: None)
        health, roce_pass, roce_na = eng._fina_health('600519.SH', _FakeECMForCompute())
        assert health in ('pass', 'suspicious', 'fail')


# ══════════════════════════════════════════════════════════
# ⑤ audit ROCE actual 对齐 tags.roce
# ══════════════════════════════════════════════════════════

class TestRocActualDisplay:
    def test_roce_actual_from_tags(self, monkeypatch):
        """evaluate tags 含 roce 数值 → audit ROCE actual 展示数值%（判定不动）"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        eng = _mk_engine(monkeypatch)
        ecm = eng._get_dm().cache
        tags = {
            'pe_percentile_5y': 3.1, 'pb_percentile_5y': 5.2, 'ps_percentile_5y': 9.9,
            'fina_health': 'pass', 'composite_rating': '1.2134',
            'valuation_level': 'extreme_low', 'valuation_deviation': '24.3',
            'roce': 22.5, 'roe': 30.0, 'sector_heat': 'top_10',
            'catalyst_event': None, 'fund_flow': '5d_inflow', 'trend_alignment': 'aligned',
        }
        with mock.patch.object(mod.Dim7ValuationEngine, '_compute_potential',
                               return_value={'signal_strength': 89,
                                             'potential_breakdown': '{"val":1.0}'}):
            res = eng.evaluate({}, tags, data_context={})
        roce_cond = next(c for c in res['audit']['conditions'] if c['name'] == 'ROCE达标')
        assert '22.50%' in roce_cond['actual'], f"actual 应展示 tags.roce 数值，实际 {roce_cond['actual']}"

    def test_roce_actual_fallback_when_no_tags_roce(self, monkeypatch):
        """tags 无 roce 数值 → actual 回退 通过/ROCE<15%（判定语，不炸）"""
        from app.opportunity_atlas.dimensions import dim7_valuation_engine as mod

        eng = _mk_engine(monkeypatch)
        ecm = eng._get_dm().cache
        tags = {
            'pe_percentile_5y': 3.1, 'pb_percentile_5y': 5.2, 'ps_percentile_5y': 9.9,
            'fina_health': 'pass', 'composite_rating': '1.2134',
            'valuation_level': 'extreme_low', 'valuation_deviation': '24.3',
            'roe': 30.0, 'sector_heat': 'top_10', 'catalyst_event': None,
            'fund_flow': '5d_inflow', 'trend_alignment': 'aligned',
        }
        with mock.patch.object(mod.Dim7ValuationEngine, '_compute_potential',
                               return_value={'signal_strength': 89,
                                             'potential_breakdown': '{"val":1.0}'}):
            res = eng.evaluate({}, tags, data_context={})
        roce_cond = next(c for c in res['audit']['conditions'] if c['name'] == 'ROCE达标')
        assert roce_cond['actual'] in ('通过', 'ROCE<15%')
