"""469号 8股全链路探针：验证 ①retail/phase 同源 ②divergence 兜底中性态（只读不写）"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600036.SH', '000002.SZ', '600519.SH', '300750.SZ',
         '002594.SZ', '688981.SH', '000001.SZ', '601318.SH']


def probe(ts_code):
    engine = StatusEngine()
    r = engine.evaluate(ts_code)
    dr = json.loads(r.get('dim_engine_results', '{}'))
    d4 = dr.get('chip_fund') or {}
    sd = d4.get('status_description', {}) or {}
    jg = d4.get('judgment', {}) or {}
    print(f'{ts_code}: phase=[{sd.get("phase","")[:30]}] retail=[{sd.get("retail_institution","")}] '
          f'div_status=[{sd.get("fund_price_divergence_status","")}] '
          f'div_label=[{sd.get("fund_price_divergence","")[:24]}]')


if __name__ == '__main__':
    for c in CODES:
        try:
            probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
