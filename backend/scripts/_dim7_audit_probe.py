"""dim7 定稿核查：600519/000002 数据获取 + 计算链路全面核dump（只读不写）

覆盖：
  1. 数据源四表最新期（daily_basic/income/balancesheet/cashflow/fina_indicator）
  2. 行业 → 类别 → 权重
  3. 各锚 a1-a5 分解（调用 RAW 侧同逻辑 ValuationEngine 方法，避开 dim7 SSOT 覆盖）
  4. composite 计算链路（含陷阱惩罚/质量修正）逐步，对比 tags.composite_rating
  5. SIG evaluate 实算 vs tags 全键对比
  6. potential 六维来源
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
from app.data import DataManager
from app.opportunity_atlas.valuation_estimator import ValuationEngine, CATEGORY_WEIGHTS, INDUSTRY_CATEGORY, QUALITY_ADJUST
from app.opportunity_atlas.dimensions.dim7_valuation_engine import _category
from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600519.SH', '000002.SZ']


def _first(df, col, default=None):
    if df is None or df.empty or col not in df.columns:
        return default
    s = df[col].dropna()
    return s.iloc[0] if not s.empty else default


def probe(code):
    dm = DataManager()
    cache = dm.cache
    print('=' * 100)
    print(f'### {code}')

    # ── 1. 数据源 ──
    print('--- 1. 数据源（最新期） ---')
    db = cache.get_cached_daily_basic(code)
    if db is not None and not db.empty:
        latest = db.iloc[-1]
        for k in ('trade_date', 'pe_ttm', 'pb', 'ps_ttm', 'dv_ttm', 'total_mv', 'circ_mv'):
            if k in db.columns:
                print(f'  daily_basic.{k} = {latest.get(k)}')
    inc = cache.get_cached_income(code)
    if inc is not None and not inc.empty:
        s = inc.sort_values('end_date', ascending=False)
        for i in range(min(2, len(s))):
            r = s.iloc[i]
            print(f'  income[{i}] end={r.get("end_date")} revenue={r.get("revenue")} net_profit={r.get("net_profit_atsopc", r.get("net_profit"))} rd={r.get("rd_expense")} op_profit={r.get("operating_profit")}')
    bs = cache.get_cached_balancesheet(code)
    if bs is not None and not bs.empty:
        s = bs.sort_values('end_date', ascending=False).iloc[0]
        print(f'  balancesheet end={s.get("end_date")} total_assets={s.get("total_assets")} total_liab={s.get("total_liab")} cash_eq={s.get("cash_equivalents", s.get("money_cap"))} cur_liab={s.get("current_liab")}')
    cf = cache.get_cached_cashflow(code)
    if cf is not None and not cf.empty:
        s = cf.sort_values('end_date', ascending=False)
        for i in range(min(2, len(s))):
            r = s.iloc[i]
            print(f'  cashflow[{i}] end={r.get("end_date")} free_cashflow={r.get("free_cashflow")} cashflow_oper={r.get("cashflow_oper")}')
    fi = cache.get_cached_fina_indicator(code)
    if fi is not None and not fi.empty:
        s = fi.sort_values('end_date', ascending=False)
        for i in range(min(4, len(s))):
            r = s.iloc[i]
            print(f'  fina_indicator[{i}] end={r.get("end_date")} roe={r.get("roe")}')

    # 行业 → 类别 → 权重
    ind = None
    try:
        ind = dm.get_stock_industry(code)
    except Exception as e:
        print(f'  行业查询异常: {e}')
    cat = _category(ind)
    weights = CATEGORY_WEIGHTS.get(cat, CATEGORY_WEIGHTS['微小/亏损'])
    print(f'  industry={ind}  →  cat={cat}  →  weights={weights}')

    # ── 2. 各锚分解（RAW 侧同逻辑） ──
    print('--- 2. 各锚 a1-a5 + composite 链路 ---')
    ve = ValuationEngine()
    ve.build_fcf_percentile(cache)
    df_basic = cache.get_cached_daily_basic(code)
    df_income = cache.get_cached_income(code)
    df_bs = cache.get_cached_balancesheet(code)
    df_cf = cache.get_cached_cashflow(code)
    a1 = ve._anchor_pb(df_basic)
    a2, peg_gt2 = ve._anchor_earnings(df_basic, df_income)
    a3 = ve._anchor_cashflow(df_basic, df_cf, df_bs, cat)
    a4 = ve._anchor_adjusted_pe(df_basic, df_income, cat)
    a5 = ve._anchor_bond_stock(df_basic)
    print(f'  a1(资产PB)={a1}  a2(收益PE)={a2}(peg_gt2={peg_gt2})  a3(现金流)={a3}  a4(调整PE)={a4}  a5(股债)={a5}')
    w1, w2, w3, w4, w5 = weights
    composite = w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4 + w5 * a5
    composite = max(-2.0, min(2.0, composite))
    print(f'  composite(原始加权) = {composite:.4f}')
    # 陷阱惩罚
    fina_health, roce_pass, roce_na, df_fina = ve._fina_health(code)
    value_trap = (not roce_pass and not roce_na)
    print(f'  fina_health={fina_health} roce_pass={roce_pass} roce_na={roce_na} value_trap={value_trap} growth_trap(peg_gt2)={peg_gt2}')
    if value_trap:
        composite -= 0.3
        print(f'  -0.3 价值陷阱 → {composite:.4f}')
    if peg_gt2:
        composite -= 0.5
        print(f'  -0.5 成长陷阱 → {composite:.4f}')
    composite = max(-2.0, min(2.0, composite))
    # 质量修正
    qa = QUALITY_ADJUST
    if fina_health == 'fail':
        composite -= qa['fail_penalty']
        print(f'  -{qa["fail_penalty"]} 财务fail惩罚 → {composite:.4f}')
    elif fina_health == 'pass' and not df_fina.empty and 'roe' in df_fina.columns:
        roe = df_fina['roe'].dropna()
        if not roe.empty:
            roe_v = float(roe.iloc[0] or 0)
            if roe_v > qa['roe_threshold']:
                premium = qa['premium'] * min(1.0, roe_v / qa['roe_norm'])
                composite += premium
                print(f'  +{premium:.4f} ROE质量溢价(roe={roe_v}) → {composite:.4f}')
    composite = max(-2.0, min(2.0, composite))
    # 成长修正
    if cat in ('科技', '成长') and df_income is not None and not df_income.empty and 'revenue' in df_income.columns:
        growth = ve._revenue_yoy(df_income)
        if growth is not None and growth > 0.20:
            composite += 0.2
            print(f'  +0.2 高成长容忍 → {composite:.4f}')
    composite = max(-2.0, min(2.0, composite))
    print(f'  ** 实算 composite（含全部修正）= {composite:.4f}')

    # ── 3. tags 对比 ──
    print('--- 3. tags（RAW 预计算） vs 实算 ---')
    tags = StatusEngine()._load_tags(code) or {}
    for k in ('composite_rating', 'valuation_level', 'valuation_deviation',
              'pe_percentile_5y', 'pb_percentile_5y', 'fcf_yield', 'dividend_yield',
              'revenue_growth', 'fina_health', 'roce_pass', 'value_trap',
              'asset_anchor_rating', 'earnings_anchor_rating',
              'cashflow_anchor_rating', 'adjusted_anchor_rating'):
        print(f'  tags.{k} = {tags.get(k)}')

    # ── 4. potential 六维来源 ──
    print('--- 4. potential 六维来源（tags 值） ---')
    for k in ('valuation_deviation', 'roe', 'fina_health', 'sector_heat',
              'catalyst_event', 'fund_flow', 'trend_alignment', 'sentiment_phase'):
        print(f'  tags.{k} = {tags.get(k)}')


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    for c in CODES:
        try:
            with _app.app_context():
                probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
