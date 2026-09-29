"""497号 批次3（P1）：分布偏移归因探针（只读，不写库）

Q4 拍板：先轻量归因确认「09-28 bear 占比 73.1%」是行情真实反映还是 risk 维度异常放大，
再重定基线。本探针输出：
  1. 两交易日（09-28 最新 / 09-24 旧基线期）L1 各维 direction 分布对照；
  2. direction=bear 分桶下，各维 direction=-1 的占比（看主导维）；
  3. L2 reliability 各维均值对照（看是否单维异常放大权重）；
  4. L3 group_details 各族 direction 对照。

用法（停 data_daemon 后）：
  backend/.venv/bin/python backend/scripts/_497_b3_attribution_probe.py
"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.consensus_engine import compute as consensus_compute  # noqa: E402
from app.opportunity_atlas.dim_adapter import convert_to_factors  # noqa: E402
from app.opportunity_atlas.reliability_assessor import assess  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

_DATES = ['2026-09-28', '2026-09-24']


def _load(trade_date):
    return sharding_manager.execute_query(
        'strategy_signal_detail',
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
        "WHERE trade_date = ? AND dim_results_json IS NOT NULL", [trade_date])


def _analyze(trade_date):
    rows = _load(trade_date)
    se = StatusEngine()
    dim_dir = defaultdict(Counter)      # dim -> Counter(direction)
    rel_sum = defaultdict(float)        # dim -> 累计 reliability
    rel_n = defaultdict(int)
    grp_dir = defaultdict(Counter)      # group -> Counter(direction)
    n = 0
    bear_dims = defaultdict(int)        # bear 分桶中，各维 -1 计数
    bear_n = 0
    for code, dj in rows:
        try:
            dr = json.loads(dj)
            row = se.evaluate(code, dim_results=dr)
        except Exception:
            continue
        if not row:
            continue
        n += 1
        tags = se._load_tags(code)
        try:
            dims_factor = convert_to_factors(dr, tags)
        except Exception:
            dims_factor = {}
        for dim, val in dims_factor.items():
            if isinstance(val, dict):
                dim_dir[dim][int(val.get('direction', 0))] += 1
        try:
            reliability = assess(dims_factor, dr)
        except Exception:
            reliability = {}
        for dim, rv in reliability.items():
            try:
                rel_sum[dim] += float(rv)
                rel_n[dim] += 1
            except (TypeError, ValueError):
                pass
        # L3 族方向
        try:
            regime = se._detect_market_regime(tags, {})
            weights = se.MARKET_REGIME_WEIGHTS.get(regime, se.MARKET_REGIME_WEIGHTS['ranging'])
            cons = consensus_compute(dims_factor, reliability, weights, 'neutral')
            for grp, gd in (cons.get('group_details') or {}).items():
                grp_dir[grp][gd.get('direction')] += 1
        except Exception:
            pass
        if row.get('direction') == 'bear':
            bear_n += 1
            for dim, val in dims_factor.items():
                if isinstance(val, dict) and int(val.get('direction', 0)) < 0:
                    bear_dims[dim] += 1
    return dict(n=n, dim_dir=dim_dir, rel_sum=rel_sum, rel_n=rel_n,
                grp_dir=grp_dir, bear_dims=bear_dims, bear_n=bear_n)


def _report(trade_date, a):
    n = a['n']
    print(f'\n===== {trade_date}  n={n} =====')
    print('-- L1 各维 direction 分布（-1/0/+1）--')
    for dim in sorted(a['dim_dir']):
        c = a['dim_dir'][dim]
        tot = sum(c.values()) or 1
        print(f'  {dim:14s}: -1 {c[-1]/tot*100:5.1f}%  0 {c[0]/tot*100:5.1f}%  '
              f'+1 {c[1]/tot*100:5.1f}%')
    print('-- L2 各维 reliability 均值 --')
    for dim in sorted(a['rel_n']):
        print(f'  {dim:14s}: {a["rel_sum"][dim]/a["rel_n"][dim]:.3f}  (n={a["rel_n"][dim]})')
    print('-- L3 各族 direction 分布 --')
    for grp in sorted(a['grp_dir']):
        c = a['grp_dir'][grp]
        tot = sum(c.values()) or 1
        print(f'  {grp:14s}: bull {c.get("bull",0)/tot*100:5.1f}%  bear {c.get("bear",0)/tot*100:5.1f}%')
    bn = a['bear_n']
    print(f'-- direction=bear 分桶（n={bn}）中各维 -1 占比（主导维度）--')
    for dim, c in sorted(a['bear_dims'].items(), key=lambda x: -x[1]):
        print(f'  {dim:14s}: {c}/{bn} = {c/max(bn,1)*100:.1f}%')


if __name__ == '__main__':
    for d in _DATES:
        _report(d, _analyze(d))
