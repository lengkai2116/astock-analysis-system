"""494号 批次1 探针（只读）：R-2 主链大级别否决的全市场影响面

对最新 trade_date 的 strategy_signal_detail.dim_results_json 逐只跑真实主链 L5 仲裁
（含 R-10 接线：周线方向取自 dim_results），对比「含否决 / 不含否决」的 opportunity_state，
统计受影响股数与档位迁移矩阵。

不依赖 DataManager（stub dm），仅只读分库 → 可与 daemon 并存。
用法：backend/.venv/bin/python backend/scripts/_494_batch1_weekly_veto_impact.py
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager as sm  # noqa: E402
from app.opportunity_atlas.dim_adapter import (  # noqa: E402
    convert_to_factors,
    multi_level_consistency,
    weekly_direction_from_dim_results,
)
from app.opportunity_atlas.factor_arbiter import arbitrate  # noqa: E402

TRADE_DATE = '2026-09-24'


def _tags_for(code: str, cache: dict) -> dict:
    return cache.get(code, {})


def main():
    rows = sm.execute_query(
        'strategy_signal_detail',
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
        "WHERE trade_date=? AND dim_results_json IS NOT NULL ORDER BY ts_code",
        [TRADE_DATE])
    print(f'### 494 批次1 探针（R-2 主链大级别否决） trade_date={TRADE_DATE}  n={len(rows)}')

    # 最小 tags：right_side_confirm（RSC 门控）+ multi_level 不提供（主链实证无）
    rsc = dict(sm.execute_query(
        'opportunity_tags_cache',
        "SELECT ts_code, tag_value FROM opportunity_tags_cache "
        "WHERE tag_name='right_side_confirm'"))

    mig = Counter()          # (pre -> post)
    pre_cnt = Counter()
    post_cnt = Counter()
    n_veto = 0               # 触发否决（weekly=down & daily多 & enter/light）
    n_weekly_down = n_daily_up = 0
    n_err = 0
    ml_cnt = Counter()

    for code, dj in rows:
        try:
            dr = json.loads(dj)
        except Exception:
            n_err += 1
            continue
        try:
            dims_factor = convert_to_factors(dr, {})
            _ml, _ = multi_level_consistency(dr)
            ml_cnt[_ml or '(缺)'] += 1
            weekly = weekly_direction_from_dim_results(dr)
            if weekly == 'down':
                n_weekly_down += 1
            if int((dims_factor.get('structure') or {}).get('direction', 0) or 0) > 0 \
                    or int((dims_factor.get('vp') or {}).get('direction', 0) or 0) > 0:
                n_daily_up += 1

            tags = {'right_side_confirm': rsc.get(code, '未确认')}
            consensus = {'consensus_rate': 1.0, 'direction': 'neutral'}
            # 真实评分：用 consensus_engine 复算太贵 → 以 dims_factor 方向票近似共识率
            _dirs = [int((dims_factor.get(k) or {}).get('direction', 0) or 0)
                     for k in ('signal', 'structure', 'vp', 'chip_fund', 'emotion', 'valuation')]
            _bull = sum(1 for d in _dirs if d > 0)
            _bear = sum(1 for d in _dirs if d < 0)
            consensus['consensus_rate'] = (_bull / max(1, _bull + _bear)) if (_bull or _bear) else 0.5
            pre = arbitrate(consensus, {}, tags, dims_factor, {})
            post = arbitrate(consensus, {}, tags, dims_factor, {}, weekly_direction=weekly)
            pre_cnt[pre['opportunity_state']] += 1
            post_cnt[post['opportunity_state']] += 1
            if pre['opportunity_state'] != post['opportunity_state']:
                mig[f"{pre['opportunity_state']}->{post['opportunity_state']}"] += 1
                n_veto += 1
        except Exception:
            n_err += 1
            continue

    n = len(rows) - n_err
    print('\n--- 方向与多级别可得性 ---')
    print(f'  weekly=down           : {n_weekly_down}/{n}')
    print(f'  daily 结构/量价看多    : {n_daily_up}/{n}')
    print(f'  multi_level_consistency: {dict(ml_cnt)}')
    print(f'\n--- 档位迁移（pre → post，触发否决 {n_veto} 只 = {n_veto/max(1,n)*100:.1f}%）---')
    for k, v in mig.most_common():
        print(f'  {k}: {v}')
    print('\n--- 分布对照 ---')
    print(f'  pre : {dict(pre_cnt.most_common())}')
    print(f'  post: {dict(post_cnt.most_common())}')
    print(f'\n完成：n={n} err={n_err}')


if __name__ == '__main__':
    main()
