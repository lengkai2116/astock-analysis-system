"""479号-10 验证探针：465-4~8 dim2 现状真实数据核查（只读不写）

逐项对照探针：
  465-4 trend_basis/chanlun_direction 是否入 structure.text（趋势结论句是否已产）
  465-5 vs_indicator 是否入 evidence/text（RSI 强弱是否透传）
  465-6 judgment.structure（单级别）vs multi_level_direction_text（多级别方向）是否矛盾
  465-7 audit 背驰检测 vs 有确认买点 是否并存、direction 是否语义冲突
  465-8 vs_indicator detail 的 RSI 分档（31-69 是否全中性）
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
    jg = (dr.get('structure') or {}).get('judgment', {}) or {}
    au = (dr.get('structure') or {}).get('audit', {}) or {}
    report = Dim8SummaryEngine().build_seven_dim_report(dr, tags=tags, ts_code=code)
    st = (report or {}).get('structure') or {}
    print('=' * 100)
    print(f'### {code}')
    print('[465-4/5] structure.text:', st.get('text'))
    print('[465-4] chanlun_direction=', sd.get('chanlun_direction'),
          '| trend_basis=', sd.get('trend_basis'),
          '| stage_name=', sd.get('stage_name'))
    print('[465-5] vs_indicator=', sd.get('vs_indicator'))
    print('[465-5] evidence 含RSI?',
          any('RSI' in e for e in (st.get('evidence') or [])),
          '| evidence 首5条:', (st.get('evidence') or [])[:5])
    print('[465-6] judgment.structure=', jg.get('structure'),
          '| overall_direction=', jg.get('overall_direction'),
          '| multi_level_direction_text=', sd.get('multi_level_direction_text'))
    print('[465-7] divergence=', sd.get('divergence'), sd.get('divergence_type'),
          '| 有确认买点?',
          any(p.get('type') == 'buy' and p.get('confirmed')
              for p in (sd.get('buy_sell_points_detail') or [])))
    for c in (au.get('conditions') or []):
        if c.get('name') in ('背驰检测', '有确认买点'):
            print(f'   audit[{c["name"]}] satisfied={c.get("satisfied")} actual={c.get("actual")}')
    print('[465-8] RSI值域:', sd.get('vs_indicator'))


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    for c in CODES:
        with _app.app_context():
            try:
                probe(c)
            except Exception as e:
                import traceback
                print(f'\n{c} [FATAL] {e}')
                traceback.print_exc()
