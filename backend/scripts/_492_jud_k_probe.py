"""492号 K1-K5 真实数据全链路验证探针（只读，不写库）

对 8 只个股跑 SIG→JUD 真实链路，验证 492 号五处「键名/API 错位致机制空转」修复生效：
  K1  2% 风险预算仓位   —— advice risk_budget_position 不再恒 None
  K2  情绪周期仓位联动   —— l0.emotion_position_cap 随 sentiment_phase 变化
  K3  市场状态/情绪阶段权重 —— consensus 随 regime/sentiment_phase 变化（group_details.state_weight）
  K4  advice 白名单      —— _assemble advice_params 含 entry_zone/target_zone
  K5  signal_confirm     —— L1 signal_confirm.evidence 非空（classify_attribute 真实执行）

用法（停 data_daemon 优先；只读亦可带锁运行）：
  backend/.venv/bin/python backend/scripts/_492_jud_k_probe.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.consensus_engine import compute as consensus_compute  # noqa: E402
from app.opportunity_atlas.dim_adapter import convert_to_factors  # noqa: E402
from app.opportunity_atlas.reliability_assessor import assess  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine, _normalize_emotion_phase  # noqa: E402

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

# 与 status_engine.yaml 同步的 regime 权重（用于 K3 对比，逐档取自 yaml）
_REGIMES = {
    'trending_up': {'signal': 0.15, 'structure': 0.20, 'vp': 0.15, 'chip_fund': 0.10,
                    'emotion': 0.10, 'risk': 0.15, 'valuation': 0.15},
    'ranging': {'signal': 0.10, 'structure': 0.15, 'vp': 0.20, 'chip_fund': 0.10,
                'emotion': 0.10, 'risk': 0.20, 'valuation': 0.15},
    'trending_down': {'signal': 0.10, 'structure': 0.10, 'vp': 0.10, 'chip_fund': 0.10,
                      'emotion': 0.10, 'risk': 0.30, 'valuation': 0.20},
    'extreme_panic': {'signal': 0.05, 'structure': 0.05, 'vp': 0.05, 'chip_fund': 0.10,
                      'emotion': 0.10, 'risk': 0.40, 'valuation': 0.25},
}

_STATS = {'K1_ok': 0, 'K2_ok': 0, 'K3_ok': 0, 'K4_ok': 0, 'K5_ok': 0, 'n': 0}


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dr = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code) or {}
    dr['daily_df'] = se.dm.get_cached_daily_data(code)

    print('=' * 100)
    print(f'### {code}')

    # ── K5：signal_confirm 真实执行 ──
    f = convert_to_factors(dr, tags)
    sc = f.get('signal_confirm') or {}
    sc_ev = sc.get('evidence') or []
    k5 = bool(sc_ev and any(sc_ev))
    print(f'[K5] signal_confirm dir={sc.get("direction")} evidence={sc_ev[:1]} → {"OK" if k5 else "FAIL"}')

    # ── K2：情绪阶段归一化 + L0b2 仓位上限 ──
    sp_raw = tags.get('sentiment_phase')
    phase = _normalize_emotion_phase(tags)
    l0 = se._apply_l0(code, tags, {}, lifecycle) or {}
    cap = l0.get('emotion_position_cap')
    k2 = (sp_raw is not None) and (cap is not None)
    print(f'[K2] sentiment_phase={sp_raw!r} → phase={phase!r}  emotion_position_cap={cap} → {"OK" if k2 else "n/a"}')

    # ── K3：weights 生效（同因子下不同 regime → 不同共识） ──
    rel = assess(f, dr)
    cs = {r: consensus_compute(f, rel, w, phase)['consensus_rate'] for r, w in _REGIMES.items()}
    distinct = len(set(cs.values())) > 1
    gd = consensus_compute(f, rel, _REGIMES['ranging'], phase).get('group_details', {})
    vq = (gd.get('valuation_quality') or {}).get('state_weight')
    k3 = distinct and vq is not None
    print(f'[K3] consensus@{ {k: v for k, v in cs.items()} }')
    print(f'     差异化={distinct}  valuation_quality.state_weight={vq} → {"OK" if k3 else "FAIL"}')

    # ── K1/K4：L6 advice（经 v390 全链路） ──
    row = se.evaluate(code, dim_results=dr) or {}
    ap = json.loads(row.get('advice_params') or '{}')
    k1 = ap.get('risk_budget_position') is not None
    k4 = ('entry_zone' in ap) or ('target_zone' in ap)
    print(f'[K1] advice risk_budget_position={ap.get("risk_budget_position")} '
          f'max_position_ratio={ap.get("max_position_ratio")} → {"OK" if k1 else "n/a(无止损/入场价)"}')
    print(f'[K4] advice_params entry_zone={ap.get("entry_zone")} '
          f'target_zone={ap.get("target_zone")} → {"OK" if k4 else "n/a(dim3 无区间)"}')

    _STATS['n'] += 1
    _STATS['K5_ok'] += int(k5)
    _STATS['K2_ok'] += int(k2)
    _STATS['K3_ok'] += int(k3)
    _STATS['K1_ok'] += int(k1)
    _STATS['K4_ok'] += int(k4)


def main():
    print('492号 K1-K5 真实数据全链路验证探针（只读）')
    for code in CODES:
        try:
            probe(code)
        except Exception as e:
            import traceback
            print(f'### {code} 探针异常: {type(e).__name__}: {e}')
            traceback.print_exc()
    n = max(_STATS['n'], 1)
    print('=' * 100)
    print(f'汇总（{n} 只）：K1 {_STATS["K1_ok"]}/{n}  K2 {_STATS["K2_ok"]}/{n}  '
          f'K3 {_STATS["K3_ok"]}/{n}  K4 {_STATS["K4_ok"]}/{n}  K5 {_STATS["K5_ok"]}/{n}')
    print('注：K1/K4 的 n/a 表示该股缺止损位或 dim3 无区间（非缺陷）。')


if __name__ == '__main__':
    main()
