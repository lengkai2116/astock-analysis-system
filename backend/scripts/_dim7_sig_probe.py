"""dim7 只读检查探针：SIG 侧引擎实例分位表状态 + 实算 vs tags 口径对比（只读不写）"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine

CODES = ['600519.SH', '000002.SZ', '601318.SH', '300750.SZ',
         '002594.SZ', '000001.SZ', '600036.SH', '688981.SH']

# _compute_potential 消费的 tags 键
POT_TAG_KEYS = [
    'roe', 'valuation_deviation', 'fina_health', 'sector_heat',
    'catalyst_event', 'fund_flow', 'trend_alignment', 'sentiment_phase',
    'ts_code', 'industry', 'industry_name',
]


def probe(ts_code):
    print('=' * 90)
    print(f'### {ts_code}')

    # 1. SIG 侧引擎实例状态（status_engine 同款：engine_cls() 直接 evaluate）
    eng = Dim7ValuationEngine()
    print('--- SIG 引擎实例分位表状态 ---')
    print(json.dumps({
        '_comp_percentile': 'None' if eng._comp_percentile is None else 'built',
        '_fcf_percentile': 'None' if eng._fcf_percentile is None else 'built',
        '_industry_mean': eng._industry_mean,
        '_potential_tables': {k: 'built' if v else 'empty' for k, v in eng._potential_tables.items()},
    }, ensure_ascii=False, indent=2, default=str))

    # 2. tags（因）
    engine = StatusEngine()
    tags = engine._load_tags(ts_code) or {}
    pot = {k: tags.get(k) for k in POT_TAG_KEYS}
    print('--- _compute_potential 消费 tags ---')
    print(json.dumps(pot, ensure_ascii=False, indent=2, default=str))

    # 3. 引擎侧 evaluate（注入 tags 实算）
    tags_in = dict(tags)
    tags_in['ts_code'] = ts_code
    r = eng.evaluate(dims={}, tags=tags_in, lifecycle=None, data_context=None)
    sd = r['status_description']
    jd = r['judgment']
    print('--- SIG 实算 valuation_level vs tags.valuation_level ---')
    print(json.dumps({
        'sig_level': jd['valuation_level']['value'],
        'sig_deviation': jd['valuation_deviation']['value'],
        'sig_composite': sd['valuation_level'],
        'tags_level': tags.get('valuation_level'),
        'tags_deviation': tags.get('valuation_deviation'),
        'tags_composite_rating': tags.get('composite_rating'),
        'sig_fina_health': jd['fina_health']['value'],
        'sig_potential_strength': jd['potential_strength']['value'],
        'sig_potential_breakdown': json.loads(sd['potential_breakdown'] or '{}'),
    }, ensure_ascii=False, indent=2, default=str))
    print('--- SIG audit ---')
    print(json.dumps(r['audit'], ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    for c in CODES:
        try:
            probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
