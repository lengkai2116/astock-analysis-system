"""dim6 定稿第一步探针：dump Dim6RiskEngine 真实 evaluate 输出（只读不写）

用法：daemon 停止态运行（释放 SQLite 写锁）。
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600519.SH', '000002.SZ', '601318.SH', '300750.SZ',
         '002594.SZ', '000001.SZ', '600036.SH', '688981.SH']


def probe(ts_code):
    engine = StatusEngine()
    r = engine.evaluate(ts_code)
    dr = json.loads(r.get('dim_engine_results', '{}'))
    d6 = dr.get('risk') or {}
    print('=' * 90)
    print(f'### {ts_code}')
    print('--- status_description ---')
    print(json.dumps(d6.get('status_description', {}), ensure_ascii=False, indent=2, default=str))
    print('--- judgment ---')
    print(json.dumps(d6.get('judgment', {}), ensure_ascii=False, indent=2, default=str))
    print('--- audit ---')
    print(json.dumps(d6.get('audit', {}), ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    for c in CODES:
        try:
            probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
