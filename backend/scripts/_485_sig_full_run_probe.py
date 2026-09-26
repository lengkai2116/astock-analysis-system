"""485后 SIG 全环节真实数据运行 + 现状描述完整输出探针（只读不写）

对 8 只真实个股跑完整 SIG 链路（tags/signals/lifecycle → dim1-8 → dim8 归集），
完整打印 build_seven_dim_report 每段 {title, light, text, subsections, audit.conditions}，
并在末尾汇总各段状态（有无 text/audit/条件数）。
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def _fmt_conditions(conds):
    if not conds:
        return '  (无 audit 条件)'
    lines = []
    for c in conds:
        sat = '✅' if c.get('satisfied') else '❌'
        lines.append(f"    {sat} {c.get('name')}: actual={c.get('actual')} | threshold={c.get('threshold')}")
    return '\n'.join(lines)


def probe(code, summary):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    report = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags, ts_code=code)

    print('=' * 100)
    print(f'### {code}')
    if not report:
        print('  report=None')
        return
    print(f'-- 段键: {sorted(report.keys())}')
    for seg_name in sorted(report.keys()):
        seg = report.get(seg_name) or {}
        if not isinstance(seg, dict):
            continue
        title = seg.get('title', '')
        light = seg.get('light', '')
        text = seg.get('text', '')
        subs = seg.get('subsections') or []
        conds = seg.get('audit', {}).get('conditions') if isinstance(seg.get('audit'), dict) else None
        print(f'\n▌{seg_name}｜{title}｜light={light}')
        if text:
            print(f'  text: {text}')
        if subs:
            for s in subs:
                items = s.get('items') or []
                print(f'  └[{s.get("title")}]')
                for it in items:
                    print(f'      - {it}')
        if conds is not None:
            print(_fmt_conditions(conds))
        # 汇总统计
        st = summary.setdefault(code, {}).setdefault(seg_name, {})
        st['title'] = title
        st['light'] = light
        st['has_text'] = bool(text)
        st['text_len'] = len(text)
        st['n_conditions'] = len(conds) if conds else 0
        st['n_subsections'] = len(subs)


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    summary = {}
    for c in CODES:
        try:
            with _app.app_context():
                probe(c, summary)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()

    print('\n' + '=' * 100)
    print('汇总（段 → text有无/长度/audit条件数）')
    print('=' * 100)
    for code, segs in summary.items():
        print(f'\n{code}:')
        for name, st in segs.items():
            flag = 'OK' if st['has_text'] else 'EMPTY'
            print(f"  [{flag}] {name}: len={st['text_len']} conds={st['n_conditions']} subs={st['n_subsections']}")
