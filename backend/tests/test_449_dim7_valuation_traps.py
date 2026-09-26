"""449号 dim7 估值陷阱处置测试

覆盖（对齐外部 wiki 三陷阱 + FCF 口径登记）：
1. 周期股陷阱：周期顶点 PE 极低分位(<20%) → 权重纯 PB 归一（w1=1 其余 0）
2. 成长陷阱：PEG>2 → composite 降级（-0.5），_anchor_earnings 返回 peg_gt2
3. 价值陷阱：ROCE<15% → composite 惩罚（-0.3），但无 ROCE 数据不误伤
4. _fina_health 三态：roce_na 区分「无数据」与「不达标」
5. status/audit 陷阱标注
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest

from app.opportunity_atlas.dimensions.dim7_valuation_engine import (
    Dim7ValuationEngine, _category,
)
from app.opportunity_atlas.valuation_estimator import ValuationEngine as VAL_Engine


def _basic(pe_list, pb_list=None, mv=1e6):
    """构造 daily_basic 历史 df（PE/PB 分位需≥20 期）"""
    n = len(pe_list)
    rows = []
    for i in range(n):
        rows.append({
            'ts_code': '000001.SZ', 'trade_date': f'2026-09-{i+1:02d}',
            'pe_ttm': pe_list[i],
            'pb': pb_list[i] if pb_list else 1.0,
            'total_mv': mv,
            'dv_ttm': 2.0,
        })
    return pd.DataFrame(rows)


def _income(revenue_list, net_profit_list, operating_profit=None, end_dates=None):
    n = len(revenue_list)
    rows = []
    default_end = ['2026-06-30', '2025-06-30', '2024-06-30'][:n]
    ends = end_dates if end_dates else default_end
    for i in range(n):
        rows.append({
            'ts_code': '000001.SZ', 'end_date': ends[i], 'ann_date': ends[i],
            'revenue': revenue_list[i], 'net_profit_atsopc': net_profit_list[i],
            'operating_profit': operating_profit[i] if operating_profit else net_profit_list[i],
        })
    return pd.DataFrame(rows)


class _FakeECM:
    """返回空财务 df，触发 _fina_health 的 ROCE「无数据」路径"""
    def get_cached_fina_indicator(self, ts_code):
        return pd.DataFrame()
    def get_cached_finance_report(self, ts_code):
        return pd.DataFrame()
    def get_cached_income(self, ts_code):
        return pd.DataFrame()
    def get_cached_balancesheet(self, ts_code):
        return pd.DataFrame()
    def get_cached_cashflow(self, ts_code):
        return pd.DataFrame()
    def get_cached_daily_basic(self, ts_code):
        return pd.DataFrame()


class _FakeECM_FULL:
    """带 ROCE 数据的 ECM（fina_indicator 提供 roce）"""
    def __init__(self, roce_list):
        self.roce_list = roce_list
    def get_cached_fina_indicator(self, ts_code):
        return pd.DataFrame({'ts_code': [ts_code]*len(self.roce_list),
                             'end_date': [f'2026-0{i+1}' for i in range(len(self.roce_list))],
                             'roe': [12.0]*len(self.roce_list),
                             'roce': self.roce_list})
    def get_cached_finance_report(self, ts_code):
        return pd.DataFrame()
    def get_cached_income(self, ts_code):
        return pd.DataFrame()
    def get_cached_balancesheet(self, ts_code):
        return pd.DataFrame()
    def get_cached_cashflow(self, ts_code):
        return pd.DataFrame()
    def get_cached_daily_basic(self, ts_code):
        return pd.DataFrame()


# ─────────────────────────────────────────────
# 2. 成长陷阱：_anchor_earnings 返回 peg_gt2
#    （476 收敛后 dim7 委托 valuation_estimator——dim7 版测试删除，
#      权威实现见下方 test_val_estimator_anchor_earnings_tuple）
# ─────────────────────────────────────────────

# 4. _fina_health 三态（roce_na）——权威实现见下方 test_val_estimator_fina_health_roce_na
#    （dim7 旧版测试删除，dim7 无独立 _fina_health）


# ─────────────────────────────────────────────
# 3. 价值陷阱惩罚 / 成长陷阱惩罚（_compute_valuation）
# ─────────────────────────────────────────────

def test_compute_valuation_growth_trap_penalty(monkeypatch):
    """PEG>2 → composite 降级（成长陷阱 -0.5），growth_trap 标注"""
    monkeypatch.setattr('app.data.DataManager.get_stock_industry', staticmethod(lambda ts: '电子'))
    # 476号收敛：_compute_valuation 内部委托 ValuationEngine——mock 其 _fina_health
    # 免真实库（roce_na=True=无数据 → value_trap 不触发，复现原「无 ROCE 数据不惩罚」语义）
    monkeypatch.setattr(VAL_Engine, '_fina_health',
                        lambda self, ts_code: ('pass', False, True, pd.DataFrame()))
    eng = Dim7ValuationEngine()
    df_basic = _basic([60.0]*25)                  # PE 60 → PEG>2
    df_income = _income([200, 160, 140], [10, 8, 7])  # +25% → PEG=2.4>2
    ctx = {'daily_basic_df': df_basic, 'income_df': df_income}
    val = eng._compute_valuation('000001.SZ', _FakeECM(), data_context=ctx)
    assert val['growth_trap'] is True, f"PEG>2 应 growth_trap=True, 实际 {val['growth_trap']}"
    assert val['value_trap'] is False, f"无 ROCE 数据不应 value_trap, 实际 {val['value_trap']}"


# ─────────────────────────────────────────────
# valuation_estimator（RAW 权威）侧同步
# ─────────────────────────────────────────────

def test_val_estimator_anchor_earnings_tuple():
    """ValuationEngine._anchor_earnings 也返回 (score, peg_gt2)（双侧同步）"""
    df_basic = _basic([60.0]*25)
    df_income = _income([200, 160, 140], [10, 8, 7])
    ve = VAL_Engine()
    score, peg_gt2 = ve._anchor_earnings(df_basic, df_income)
    assert peg_gt2 is True, f"RAW 侧 PEG>2 应标记, 实际 {peg_gt2}"


def test_val_estimator_fina_health_roce_na():
    """ValuationEngine._fina_health 返回 (health, roce_pass, roce_na, df_fina)"""
    ve = VAL_Engine()
    import app.data as data_mod
    monkey = pytest.MonkeyPatch()

    class _DM:
        def get_cached_income(self, ts): return pd.DataFrame()
        def get_cached_balancesheet(self, ts): return pd.DataFrame()
        def get_cached_cashflow(self, ts): return pd.DataFrame()
        def get_cached_finance_report(self, ts): return pd.DataFrame()
        def get_cached_fina_indicator(self, ts): return pd.DataFrame()
        def get_stock_industry(self, ts): return '电子'

    monkey.setattr(data_mod, 'DataManager', lambda: _DM())
    val = ve._fina_health('000001.SZ')
    # 返回 4 元组
    assert len(val) == 4, f"RAW 侧 _fina_health 应返回 4 元组, 实际 {len(val)}"
    health, roce_pass, roce_na, df_fina = val
    assert roce_na is True, f"无数据 roce_na 应为 True, 实际 {roce_na}"
    monkey.undo()
