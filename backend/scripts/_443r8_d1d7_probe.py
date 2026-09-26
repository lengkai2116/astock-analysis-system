"""443 R8（437-A D1-D7 重审）验证探针：当前 seven_dim 结构（只读）

对 8 股真实数据构建 seven_dim，核查 D1-D7 落地证据：
  D1 fund_chip/risk 段内 subsections；D2 summary 尾置收益驱动；D3 summary 前置环境定位；
  D4 去重（emotion 无 stock 子句等）；D7 缺维不产段（段键集合）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH']


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    report = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags, ts_code=code)
    if not report:
        print(f'{code}: report=None'); return

    print('=' * 100)
    print(f'### {code}')
    print(f'-- 段键: {sorted(report.keys())}')
    assert 'signal' not in report and 'valuation' not in report, 'signal/valuation 不应有独立段（裁决+436 D5）'
    assert len(report) >= 6, 'D7: 缺维不产段，正常应 6 键+summary 恒在'

    # D1: fund_chip/risk subsections
    for seg_name in ['fund_chip', 'risk']:
        seg = report.get(seg_name) or {}
        subs = seg.get('subsections') or []
        titles = [s.get('title') for s in subs]
        print(f'-- {seg_name}.subsections: {titles}')
        if subs:
            print(f'   [第一小节] {subs[0].get("items", [])[:2]}')
            print(f'   [第二小节] {subs[1].get("items", [])[:2]}')

    # D4: emotion 无 stock 子句（主源 dim3）
    emo = report.get('emotion') or {}
    if emo:
        t = emo.get('text', '')
        print(f'-- emotion.text: {t[:100]}')

    # D2/D3: summary 前置环境定位 + 尾置收益驱动
    seg = report.get('summary') or {}
    t = seg.get('text', '')
    print(f'-- summary.text(前180): {t[:180]}')
    print(f'-- summary.text(后160): …{t[-160:]}')
    assert ('大盘状态' in t or '板块定位' in t or '相对强弱' in t or '指数' in t), 'D3 环境定位前置缺失'
    assert '；估值：' in t or t.startswith('估值：') or '估值水平' in t, 'D2 收益驱动尾置缺失'


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    ok = 0
    for c in CODES:
        try:
            with _app.app_context():
                probe(c)
            ok += 1
        except Exception as e:
            print(f'\n{c} [FAIL] {e}')
    print(f'\n通过 {ok}/{len(CODES)}')
