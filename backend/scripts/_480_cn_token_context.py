"""480 后续：精确 dump 指定 token 在展示文本的完整上下文（定位孤 token 来源，只读）"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine

CODES = ['000002.SZ', '601318.SH']
TARGETS = ['U', 'W', 'x', 'asr', 'right_emerging', 'MA10', 'MA5', 'composite',
           'dim2', 'dim4', 'neutral', 'risk_warning', 'BOCIASI', 'ERP',
           'chip', 'chan', 'fund', 'stage', 'trend', 'ssrp']


def _dump(code, text, label):
    for t in TARGETS:
        pat = re.compile(r'.{0,18}' + re.escape(t) + r'.{0,18}', re.I)
        for m in pat.finditer(text):
            print(f"  [{label}][{t}] ≣{m.group(0)}≣")
            break  # 每 token 每字段只报首个，防刷屏


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    report = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags, ts_code=code)
    if not report:
        print(f'{code}: report=None')
        return
    print(f'\n=== {code} ===')
    for key in ('emotion', 'summary'):
        seg = report.get(key)
        if not seg:
            continue
        t = seg.get('text', '')
        print(f'--- {key}.text ---')
        _dump(code, t, f'{code}.{key}.text')


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    for c in CODES:
        try:
            with _app.app_context():
                probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
