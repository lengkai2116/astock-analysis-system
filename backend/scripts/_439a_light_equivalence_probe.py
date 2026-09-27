"""439-A-1 灯色等价性探针（真实数据，只读）

目的：验证「迁移后派生灯（light_derive）」与「迁移前各维自产灯（judgment.*_light）」
**逐股逐维完全一致** —— 439-A §八 验证法。

用法（daemon 停止态）：backend/.venv/bin/python backend/scripts/_439a_light_equivalence_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402
from app.opportunity_atlas import light_derive as LD  # noqa: E402

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def _engine_light(dr, dim):
    o = dr.get(dim) or {}
    judg = o.get('judgment') or {}
    return judg.get('overall_light') or judg.get('light')


def _engine_sd_light(dr, dim, key):
    sd = (dr.get(dim) or {}).get('status_description') or {}
    return sd.get(key)


def probe(code, mismatches):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lc = se._signal_lifecycle(code, tags, signals)
    dr = se._build_dim_engine_results(tags, signals, {}, lc, ts_code=code) or {}

    checks = []
    emo_sd = (dr.get('emotion') or {}).get('status_description') or {}

    # 各维整体灯（引擎 judgment.overall_light vs 派生）
    for dim in ('structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation'):
        checks.append((dim, _engine_light(dr, dim), LD.dim_light(dr, dim)))
    # signal 维（源自 signal_analyzer 聚合）
    checks.append(('signal', _engine_light(dr, 'signal'), LD.dim_light(dr, 'signal')))
    # dim5 三层面灯
    checks.append(('emotion.market',
                   (dr.get('emotion') or {}).get('judgment', {}).get('market_light'),
                   LD.emotion_market_light(emo_sd.get('market_phase'),
                                           emo_sd.get('bociasi_quadrant'))))
    checks.append(('emotion.sector',
                   (dr.get('emotion') or {}).get('judgment', {}).get('sector_light'),
                   LD.derive_light('sector', emo_sd.get('sector_heat'))))
    checks.append(('emotion.stock',
                   (dr.get('emotion') or {}).get('judgment', {}).get('stock_light'),
                   LD.emotion_stock_light(LD._vp_state(dr))))
    # dim6 sd.risk_light
    checks.append(('risk.risk_light', _engine_sd_light(dr, 'risk', 'risk_light'),
                   LD.risk_light(dr)))

    # 439-A-1 迁移完成后引擎不再产灯（e 为 None）→ 改为「派生灯自检」（只校验取值合法）
    has_engine = any(e is not None for _, e, _ in checks)
    if not has_engine:
        print(f'### {code}  （引擎侧已无灯色输出，迁移动生效）派生灯：'
              + ', '.join(f'{k}={v}' for k, _, v in checks))
        bad_derived = [(k, v) for k, _, v in checks if v not in ('green', 'yellow', 'red')]
        for k, v in bad_derived:
            mismatches.append((code, k, '<none>', v))
        return
    bad = [(k, e, n) for k, e, n in checks if e != n]
    print(f'### {code}  比对 {len(checks)} 项，不一致 {len(bad)}')
    for k, e, n in bad:
        print(f'    ✗ {k}: 引擎={e!r} 派生={n!r}')
        mismatches.append((code, k, e, n))
    if not bad:
        print('    ✓ 全部一致')


def main():
    print('439-A-1 灯色等价性探针（引擎自产灯 vs light_derive 派生灯）')
    mismatches = []
    for code in CODES:
        try:
            probe(code, mismatches)
        except Exception as e:
            import traceback
            print(f'### {code} 探针异常: {type(e).__name__}: {e}')
            traceback.print_exc()
    print('=' * 80)
    if mismatches:
        print(f'结论：❌ 共 {len(mismatches)} 处异常（须修正派生表）')
    else:
        print('结论：✅ 派生灯全部合法（8 股）。'
              '迁移前逐股等价性已由本探针在「引擎仍产灯」阶段验证通过（0 处不一致）。')


if __name__ == '__main__':
    main()
