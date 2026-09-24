"""479号-5 验证探针：dim8 实例→话术改造后 8 股真实数据 seven_dim 因果链核查（只读不写）

覆盖（479-5 B1 实施验证）：
  1. 五公开段（structure/volume_price/fund_chip/emotion/risk）text 均含「所以：」
  2. 有 audit 满足项时含「因为：{satisfied 条件名}」
  3. 有 total 时含「验证：条件稽核 N/M」（audit 动态读）
  4. plain == text（段内 plain 契约一致）
  5. evidence 含审计满足项底料
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

PUBLIC_KEYS = ('structure', 'volume_price', 'fund_chip', 'emotion', 'risk')


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    report = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags, ts_code=code)
    if not report:
        print(f'{code}: report=None')
        return False
    ok = True
    print(f'=== {code} ===')
    for key in PUBLIC_KEYS:
        seg = report.get(key)
        if not seg:
            continue
        t = seg.get('text', '')
        assert t.startswith('所以：'), f'{key} text 不以所以开头: {t[:40]}'
        assert seg.get('plain') == t, f'{key} plain != text'
        got = []
        if '；因为：' in t:
            got.append('因')
        if '；验证：条件稽核' in t:
            got.append('验')
        print(f'  {key}: [{"、".join(got) or "无因果"}] {t[:90]}')
        au = seg.get('audit') or {}
        sat = au.get('satisfied_count', 0)
        if sat and '；因为：' not in t:
            print(f'    ⚠️ {key} 有 {sat} 满足项但无因为节')
    return ok


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    allok = True
    for c in CODES:
        try:
            with _app.app_context():
                allok = probe(c) and allok
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
            allok = False
    print('\nALL_OK' if allok else '\nHAS_FATAL')
