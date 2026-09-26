"""484号 探针②：cashflow 全列名盘点（找折旧摊销/资本支出/经营现金流字段）"""
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

df = pro.cashflow(ts_code='600519.SH')
print(f"行数={len(df)}")
print("全列名：")
print(sorted(df.columns))
print()
# 找疑似字段
kw = ['depr', 'coca', 'capital', 'acq', 'const', 'oper', 'act', 'free']
for c in sorted(df.columns):
    if any(k in c for k in kw):
        print(f"  候选: {c} = {df[c].iloc[0] if not df[c].isna().iloc[0] else 'NULL'}")
