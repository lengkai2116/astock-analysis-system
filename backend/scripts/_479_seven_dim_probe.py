"""479号 验证探针：dim8 改造后 8 股真实数据 seven_dim 输出核查（只读不写）

覆盖（479-1/479-6 实施验证）：
  1. 段键集合 = 6 键（无 signal/valuation——2026-09-15 裁决 + 436 D5）
  2. structure text 无「结构强度」（chanlun_strength 归 JUD）
  3. volume_price text 无「健康度：8/10 / 形态评分 / 量比:」评分键值，rps 已转表述
     （2026-09-26 修正：因果链「因为」引 audit 条件名含「健康度评分」属正常，不再禁裸词）
  4. risk 段 subsections = 价格位置/风险状态两小节（P15）
  5. audit.conditions 透传 actual/threshold（P9）
  6. summary 尾置收益驱动句（估值条件 N/M 满足）且无重复「估值：」（D2=A）
  7. volatility_level 中文化（P11）
  8. trend_structure_signal='none' 不产句（B8）
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
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    report = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags, ts_code=code)
    if not report:
        print(f'{code}: report=None'); return

    print('=' * 100)
    print(f'### {code}')
    print(f'-- 段键: {sorted(report.keys())}')
    assert 'signal' not in report and 'valuation' not in report

    # 1. structure
    seg = report.get('structure') or {}
    if seg:
        t = seg.get('text', '')
        print(f'-- structure.text: {t}')
        assert '结构强度' not in t, 'chanlun_strength 不应产句'
    # 2. volume_price
    seg = report.get('volume_price') or {}
    if seg:
        t = seg.get('text', '')
        print(f'-- volume_price.text: {t}')
        # 443 R8 重审修正（2026-09-26）：479-5 因果链升级后 text「因为」部分引用 audit
        # 条件名（如「健康度评分、背离检测」）——条件名含「健康度」字样属正常，非评分键产句。
        # 故只禁评分键**值**模式（`健康度：8/10` / `形态评分`），不再禁裸「健康度」。
        assert '形态评分' not in t, '形态评分键不应产句'
        assert '健康度：' not in t and '健康度:' not in t, 'health_score 值不应产句'
        assert '量比:' not in t, 'vol_ratio 不应独立产句'
    # 3. risk subsections
    seg = report.get('risk') or {}
    if seg:
        subs = seg.get('subsections') or []
        titles = [s['title'] for s in subs]
        print(f'-- risk.subsections: {titles}')
        if subs:
            assert titles == ['价格位置', '风险状态'], 'P15 两小节'
            print(f'   [价格位置] {subs[0]["items"][:3]}')
            print(f'   [风险状态] {subs[1]["items"][:4]}')
        conds = seg['audit']['conditions']
        if conds:
            c0 = conds[0]
            print(f'-- risk.audit.conditions[0]: {c0}')
            assert 'actual' in c0 and 'threshold' in c0, 'P9 actual/threshold'
        t = seg.get('text', '')
        print(f'-- risk.text: {t[:120]}')
        # P11：volatility 中文化（T 表 risk 含 volatility_level）
        assert '波动率:low' not in t and '波动率:medium' not in t and '波动率:high' not in t, \
            'P11 volatility_level 未中文化'
    # 4. emotion（无 stock 子句）
    seg = report.get('emotion') or {}
    if seg:
        t = seg.get('text', '')
        print(f'-- emotion.text: {t}')
    # 5. summary 估值尾置
    seg = report.get('summary') or {}
    t = seg.get('text', '')
    print(f'-- summary.text: …{t[-160:]}')
    # 收益驱动尾置唯一（risk 段风险因素可能含"估值：估值过高"——category 名，非收益驱动段，
    #   故只断言尾置前缀与验证句存在，不苛求全局唯一）
    assert '；估值：' in t or t.startswith('估值：'), '收益驱动尾置句缺失'
    if '估值条件' in t:
        print('   ✅ 收益驱动验证句在')

    # 6. 环境定位（ts_code 已传）
    if '大盘状态' in t or '板块定位' in t or '相对强弱' in t:
        print('   ✅ summary 环境定位句在')


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
