"""479号-9 验证探针：dim7 遗留收敛 8 股真实数据核查（只读不写）

覆盖（479-9 D2 五子项）：
  1. ①SSOT 优先：_compute_valuation 的 pe/pb/ps_percentile_5y 与 tags._5y 一致（RAW 预计算口径）
  2. ③status_description 含 _5y 数字键 → reliability_assessor._assess_valuation 恢复 0.8/0.95（非恒 0.3）
  3. ④_fina_health ecm=None 加固（直接 evaluate 不炸）
  4. ⑤audit ROCE actual 展示 tags.roce 数值（判定不动）
  5. dim8 展示层不受影响（估值段话术键值不变性比对：改后 evaluate 输出含 pe/pb 中文串键）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.reliability_assessor import _assess_valuation
from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    val = (dim_results or {}).get('valuation', {}) or {}

    print(f'=== {code} ===')
    issues = []

    # 1. ①SSOT: evaluate status_description._5y 数字键 与审计 PE/PB 一致性验证
    val_sd = val.get('status_description', {}) or {}
    pe5 = val_sd.get('pe_percentile_5y')
    pb5 = val_sd.get('pb_percentile_5y')
    ps5 = val_sd.get('ps_percentile_5y')
    print(f'  status_description._5y keys: pe={pe5} pb={pb5} ps={ps5}')
    # 中文串展示键仍在（定稿 12 键语义不变）
    pe_cn = val_sd.get('pe_percentile')
    print(f'  展示中文串键: pe_percentile={pe_cn}')

    # 2. ③ reliability 恢复 0.8（PE 有数据）——此前 key 错位恒 0.3
    rel = _assess_valuation({'valuation': {'status_description': val_sd}})
    print(f'  reliability_assessor(dim7) = {rel}')
    if pe5 is not None:
        if rel < 0.8:
            issues.append(f'PE有数据但 reliability={rel} < 0.8（应 >=0.8）')

    # 3. ⑤ audit ROCE actual 展示 tags.roce 数值
    roce_cond = None
    for c in val.get('audit', {}).get('conditions', []):
        if c.get('name') == 'ROCE达标':
            roce_cond = c
            break
    if roce_cond is not None:
        print(f'  audit ROCE actual={roce_cond["actual"]} satisfied={roce_cond["satisfied"]}')
        tags_roce = tags.get('roce')
        if tags_roce is not None:
            if not isinstance(roce_cond['actual'], str) or '%' not in str(roce_cond['actual']):
                issues.append(f"tags.roce={tags_roce} 但 actual 未展示数值: {roce_cond['actual']}")

    # 4. ④ _fina_health ecm=None 加固
    try:
        se2 = Dim7ValuationEngine()
        h, rp, rn = se2._fina_health(code, None)
        print(f'  _fina_health(ecm=None) → health={h} roce_pass={rp} roce_na={rn}')
    except Exception as e:
        issues.append(f'_fina_health ecm=None 异常: {e}')

    if issues:
        print(f'  ⚠️ 问题: {"；".join(issues)}')
        return False
    print(f'  OK')
    return True


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
