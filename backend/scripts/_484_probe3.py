"""484号 探针③：fina_indicator 字段语义精确验证（单字段请求，防列序错位）"""
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

for flds in [
    'ts_code,end_date,gross_margin',
    'ts_code,end_date,roic',
    'ts_code,end_date,roa',
    'ts_code,end_date,ebit',
    'ts_code,end_date,roce',
    'ts_code,end_date,debt_to_assets',
    'ts_code,end_date,roe,roic,roa,ebit,gross_margin,debt_to_assets',
]:
    try:
        df = pro.fina_indicator(ts_code='600519.SH', fields=flds)
        print(f"--- fields={flds}")
        if df is None or df.empty:
            print("  [空]")
        else:
            print(df.head(2).to_string())
    except Exception as e:
        print(f"--- fields={flds} FAIL: {e}")
