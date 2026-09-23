"""479号-2 验证探针：dim2 补产出 8 股真实数据透传核查（只读不写）

覆盖（479-2 A1-A4 实施验证）：
  1. zhongshu_location_ratio 透传（有效中枢股有值）
  2. buy_sell_points_detail 窗口截取（万科历史多三卖 → 每 type ≤3）+ reason 中文化
  3. divergence_details / divergence_dual_confirmed 透传（背驰股有值）
  4. theorem_check_details 11 定理逐条（含"跳过/占位"标注）
  5. dim8 structure evidence 消费新字段
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


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dr = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    sd = (dr.get('structure') or {}).get('status_description', {}) or {}
    print('=' * 100)
    print(f'### {code}')
    print(f'-- 中枢区位比: {sd.get("zhongshu_location_ratio")}')
    bsp = sd.get('buy_sell_points_detail') or []
    print(f'-- 买卖点数: {len(bsp)}')
    for p in bsp[:3]:
        print(f'   {p.get("point_type")}({p.get("price")}) reason={p.get("reason")}')
    print(f'-- 背驰details: {sd.get("divergence_details")}')
    print(f'-- 背驰双确认: {sd.get("divergence_dual_confirmed")}')
    tcd = sd.get('theorem_check_details') or []
    print(f'-- 11定理[{len(tcd)}条]:')
    for t in tcd[:6]:
        print(f'   {t}')
    # 窗口截取：每 type 最多 3 个
    from collections import Counter
    cnt = Counter(p.get('point_type') for p in bsp)
    over = {k: v for k, v in cnt.items() if v > 3}
    assert not over, f'{code} 窗口截取失败: {over}'
    # dim8 消费
    report = Dim8SummaryEngine().build_seven_dim_report(dr, tags=tags, ts_code=code)
    if report and report.get('structure'):
        ev = report['structure'].get('evidence') or []
        print(f'-- dim8 structure.evidence: {ev[:8]}')
        joined = '；'.join(ev)
        if sd.get('zhongshu_location_ratio') is not None:
            assert '中枢区位比' in joined, 'dim8 未消费中枢区位比'
        if tcd:
            assert any('定理' in e or '通过' in e or '未通过' in e for e in ev), 'dim8 未消费定理明细'


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
