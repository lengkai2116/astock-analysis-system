"""484号 数据补采可行性探针（只读，不落库）

验证 Tushare 四个接口的字段可用性：
1. fina_indicator 是否返回 roic/roa/ebit/gross_margin（扩采 roic/roa/gross_margin 用）
2. cashflow 是否返回 depr_fa_coca/c_fr_capital（449 FCF 折旧列用）
3. pledge_stat 股权质押（448 R 用）
4. stk_holdertrade 股东增减持（448 R 用）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 从 .env 读取 token
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line.startswith('TUSHARE_TOKEN='):
            os.environ['TUSHARE_TOKEN'] = line.split('=', 1)[1]
            break

import tushare as ts
pro = ts.pro_api()

CODE = '600519.SH'


def head(df, name):
    print(f"\n=== {name} ===")
    if df is None or df.empty:
        print("  [空返回]")
        return
    print(f"  行数={len(df)}")
    print(f"  列={list(df.columns)}")
    print(df.head(2).to_string())


try:
    df = pro.fina_indicator(ts_code=CODE, fields='ts_code,end_date,roe,roic,roa,ebit,gross_margin,roce,debt_to_assets')
    head(df, 'fina_indicator 指定字段(roic/roa/ebit/gm/roce)')
except Exception as e:
    print(f"\n=== fina_indicator 指定字段 FAIL: {e} ===")

try:
    df = pro.fina_indicator(ts_code=CODE)
    cols = set(df.columns)
    for f in ['roic', 'roa', 'ebit', 'gross_margin', 'roce', 'debt_to_assets']:
        print(f"  fina_indicator 全字段含 {f}: {f in cols}")
    if 'roic' in cols:
        print(df[['end_date', 'roic', 'roa', 'ebit', 'gross_margin', 'roce']].head(3).to_string())
except Exception as e:
    print(f"\n=== fina_indicator 全字段 FAIL: {e} ===")

try:
    df = pro.cashflow(ts_code=CODE)
    cols = set(df.columns)
    for f in ['depr_fa_coca', 'c_fr_capital', 'free_cashflow', 'cashflow_oper', 'c_pay_acq_const_fiolta']:
        print(f"  cashflow 含 {f}: {f in cols}")
    if 'depr_fa_coca' in cols and 'c_fr_capital' in cols:
        print(df[['end_date', 'depr_fa_coca', 'c_fr_capital', 'free_cashflow']].head(3).to_string())
except Exception as e:
    print(f"\n=== cashflow FAIL: {e} ===")

try:
    df = pro.pledge_stat(ts_code=CODE)
    head(df, 'pledge_stat 股权质押')
except Exception as e:
    print(f"\n=== pledge_stat FAIL: {e} ===")

try:
    df = pro.stk_holdertrade(ts_code=CODE)
    head(df, 'stk_holdertrade 股东增减持')
except Exception as e:
    print(f"\n=== stk_holdertrade FAIL: {e} ===")
