"""484号 探针⑤：per-stock 查询 roic/roa/ebit 非空率（随机 10 只）"""
import os
import sys
import random

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

codes = ['000001.SZ', '000002.SZ', '300750.SZ', '601318.SH', '002594.SZ',
         '600036.SH', '600276.SH', '000078.SZ', '600519.SH', '000011.SZ']
random.shuffle(codes)

for code in codes[:6]:
    df = pro.fina_indicator(ts_code=code)
    latest = df.sort_values('end_date', ascending=False).iloc[0]
    vals = {c: latest.get(c) for c in ['roe', 'roic', 'roa', 'ebit', 'gross_margin', 'debt_to_assets']}
    print(f"{code} end={latest['end_date']}: " + ' '.join(f"{k}={v}" for k, v in vals.items()))
