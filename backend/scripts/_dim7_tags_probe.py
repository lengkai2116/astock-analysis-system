"""dim7 定稿原料探针：dump dim7 相关 tags（因）真实值（只读不写）"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600519.SH', '000002.SZ', '601318.SH', '300750.SZ',
         '002594.SZ', '000001.SZ', '600036.SH', '688981.SH']

TAG_KEYS = [
    # 估值组（data_daemon RAW 白名单）
    'pe_percentile_5y', 'pb_percentile_5y', 'ps_percentile_5y',
    'valuation_level', 'valuation_deviation',
    'fcf_yield', 'dividend_yield', 'composite_rating',
    'revenue_growth', 'fina_health',
    'asset_anchor_rating', 'earnings_anchor_rating',
    'cashflow_anchor_rating', 'adjusted_anchor_rating',
    'roce_pass', 'value_trap',
    # 相关因（dim6 同源 / 行业）
    'debt_to_assets', 'roce', 'industry', 'market_cap',
]


def probe(ts_code):
    engine = StatusEngine()
    tags = engine._load_tags(ts_code) or {}
    print('=' * 90)
    print(f'### {ts_code}')
    out = {k: tags.get(k) for k in TAG_KEYS}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    for c in CODES:
        try:
            probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
