"""484号 探针④：period 路径 vs ts_code 路径的字段覆盖差异验证"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line.startswith('TUSHARE_TOKEN='):
            os.environ['TUSHARE_TOKEN'] = line.split('=', 1)[1]
            break

import tushare as ts
pro = ts.pro_api()

# 1) period 路径（全市场 20260630）——不带 fields
df = pro.fina_indicator(period='20260630')
print(f"period=20260630 不带fields: {len(df)} 行")
for c in ['roe', 'roic', 'roa', 'ebit', 'gross_margin', 'debt_to_assets', 'roce']:
    if c in df.columns:
        nn = df[c].notna().sum()
        print(f"  列 {c}: 非空 {nn}/{len(df)}  样例={df[c].dropna().iloc[0] if nn else 'NULL'}")
    else:
        print(f"  列 {c}: 不存在")

# 2) period 路径 + 显式扩展字段
try:
    df2 = pro.fina_indicator(period='20260630',
        fields='ts_code,end_date,roe,roic,roa,ebit,gross_margin,debt_to_assets')
    print(f"\nperiod=20260630 + 显式扩展字段: {len(df2)} 行")
    for c in ['roe', 'roic', 'roa', 'ebit', 'gross_margin', 'debt_to_assets']:
        if c in df2.columns:
            nn = df2[c].notna().sum()
            print(f"  列 {c}: 非空 {nn}/{len(df2)}")
        else:
            print(f"  列 {c}: 不存在")
except Exception as e:
    print(f"\nperiod+显式字段 FAIL: {e}")
