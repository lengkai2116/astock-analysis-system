"""480 后续：dim5/dim7 中文网关扩展——8 股真实 seven_dim 展示中残留 ASCII token 扫描（只读）

目的（464 网关扩展纪律 + 464-dim8-dim5/7 定稿）：
  dim8 `_to_display_text` 网关已统一接入 emotion(段)/valuation(summary 尾置)，
  但可能仍有未覆盖的英文缩写/枚举进入展示。本探针 dump 各段 text/evidence/
  subsections 中的 ASCII token（≥2 字母），列出「可能仍需中文化」与「合理保留」两类，
  供判定。
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

# 明确可保留的 ASCII（数字单位/百分比后缀/代码/相对强弱基准等），不计入残留
KEEP = re.compile(r'^\d|%$|^SH$|^SZ$|^0|^60|^000|^30')

# 已由网关中文化的子串（防误报，仍按子串剔除）
ALREADY_CN = ('ASR（活跃筹码比率）', 'CYQKL（筹码穿透力）', 'RPS（相对强弱因子）',
              '阶段引擎', '适中', '背离', '同向')


def _tokens(s: str) -> list[str]:
    """提取展示文本里的 ASCII token（英文缩写/枚举/数字单位），剔除已中文段"""
    if not s:
        return []
    raw = re.findall(r'[A-Za-z][A-Za-z0-9_.\-]*', s)
    toks = []
    for t in raw:
        if KEEP.search(t):
            continue
        if any(t in a for a in ALREADY_CN):
            continue
        toks.append(t)
    return toks


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    report = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags, ts_code=code)
    if not report:
        print(f'{code}: report=None')
        return {}
    seen = {}
    # emotion 段（dim5）
    for key in ('emotion',):
        seg = report.get(key)
        if not seg:
            continue
        fields = {'text': seg.get('text', '')}
        for i, e in enumerate(seg.get('evidence', []) or []):
            fields[f'evidence[{i}]'] = e
        for gi, grp in enumerate(seg.get('subsections', []) or []):
            for ii, it in enumerate(grp.get('items', []) or []):
                fields[f'sub[{gi}][{ii}]'] = it
        for fname, val in fields.items():
            toks = _tokens(val)
            if toks:
                seen[f'{key}.{fname}'] = (val, toks)
    # summary 段（dim8 综合含 dim7 valuation 尾置）
    seg = report.get('summary')
    if seg:
        fields = {'text': seg.get('text', '')}
        for i, e in enumerate(seg.get('evidence', []) or []):
            fields[f'evidence[{i}]'] = e
        for fname, val in fields.items():
            toks = _tokens(val)
            if toks:
                seen[f'summary.{fname}'] = (val, toks)
    return seen


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    agg = {}
    for c in CODES:
        try:
            with _app.app_context():
                r = probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
            continue
        if not r:
            continue
        print(f'=== {c}：残留 ASCII ===')
        for fname, (val, toks) in r.items():
            print(f'  [{fname}] {val}')
            print(f'       toks={sorted(set(toks))}')
            for t in set(toks):
                agg.setdefault(t, []).append(c)
    print('\n========= 全市场去重残留 token 汇总 =========')
    for t, codes in sorted(agg.items()):
        print(f'  {t!r}  出现于 {len(codes)} 股: {codes}')
