"""dim6 定稿第二步原料探针：dump dim6 相关 tags（因）真实值（只读不写）"""
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
    'risk_level', 'fina_health', 'catalyst_event', 'main_force_phase',
    'valuation_level', 'profit_ratio',
    'event_details', 'event_risk_factors',
    'support_price', 'resistance_price', 'dist_to_support_pct',
    'dist_to_resistance_pct', 'risk_reward', 'signal_days', 'dist_to_prev_high_pct',
    'atr_14d', 'atr_pct', 'volatility_level', 'volatility_percentile',
    'debt_to_assets', 'roce', 'sentiment_phase', 'right_side_confirm',
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
