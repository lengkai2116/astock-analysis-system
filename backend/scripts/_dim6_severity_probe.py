"""dim6 audit severity 口径拍板实证：risk_level vs audit「无极高风险事件」并存规模

对 8 股 + 全市场抽样跑 dim6 evaluate，统计：
  1. risk_level='高/极高' 但 audit 条件4（无极高风险事件）satisfied=True 的并存比例
  2. 条件4 不满足（存在极高事件）的股票及其事件
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    dims = se._build_dim_engine_results(
        tags, se._load_signals(code) or {}, {}, se._signal_lifecycle(code, tags, se._load_signals(code) or {}),
        ts_code=code)
    r = dims.get('risk') or {}
    aud = r.get('audit') or {}
    conds = aud.get('conditions') or []
    c4 = next((c for c in conds if c['name'] == '无极高风险事件'), None)
    level = (r.get('judgment') or {}).get('risk_level') or (r.get('status_description') or {}).get('risk_level')
    return {
        'code': code, 'level': level,
        'c4_name': c4.get('name') if c4 else None,
        'c4_satisfied': c4.get('satisfied') if c4 else None,
        'c4_actual': c4.get('actual') if c4 else None,
        'satisfied_count': aud.get('satisfied_count'), 'total': aud.get('total_count'),
    }


def main():
    from app import create_app
    _app = create_app()
    rows = []
    with _app.app_context():
        for c in CODES:
            try:
                rows.append(probe(c))
            except Exception as e:
                print(f'{c} [FAIL] {e}')

    print(f"{'code':<10} {'level':<6} {'c4(无极高事件)':<14} {'c4.actual'}")
    for r in rows:
        print(f"{r['code']:<10} {r['level']:<6} {str(r['c4_satisfied']):<14} {r['c4_actual']}")

    # 并存统计：level 高/极高 但 c4 satisfied=True
    coexist = [r for r in rows if r['level'] in ('高', '极高') and r['c4_satisfied'] is True]
    print(f"\n并存（level=高/极高 且 条件4通过）: {len(coexist)}/{len(rows)}")
    for r in coexist:
        print(f"  {r['code']} level={r['level']} c4=通过（无极高事件）——R2 层级并存")


if __name__ == '__main__':
    main()
