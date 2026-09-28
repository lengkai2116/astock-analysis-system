"""494号 批次3 探针（只读）：R-3 止损/止盈产出面 + R-4 白名单落库

对 09-24 样本逐只（真实 dim_results + 日线）：
  1. 两 builder（图谱 advice_engine / 个股页 advice_builder）在传入 dim_results 后
     `stop_loss_price` / `stop_loss_basis` / `profit_tiers` 产出率（494 前两路径均为 0）；
  2. 两 builder `executable.exit_rules` 止损一致率（同源 SSOT）；
  3. R-4：模拟 _assemble 白名单过滤 → `profit_tiers`/`stop_loss_basis` 保留率。

用法（建议停 daemon 避免分库锁）：backend/.venv/bin/python backend/scripts/_494_batch3_advice_probe.py
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data import DataManager  # noqa: E402
from app.data.sharding_manager import sharding_manager as sm  # noqa: E402
from app.opportunity_atlas.advice_builder import build_operation_advice as bld  # noqa: E402
from app.opportunity_atlas.advice_engine import build_operation_advice as eng  # noqa: E402

TRADE_DATE = '2026-09-24'
_WL = ('max_position_ratio', 'stop_loss_price', 'target_price', 'risk_reward_ratio',
       'invalidation_conditions', 'entry_zone', 'target_zone', 'risk_budget_position',
       'profit_tiers', 'stop_loss_basis')


def _dims(dr):
    ch = (dr.get('structure') or {}).get('status_description') or {}
    em = (dr.get('emotion') or {}).get('status_description') or {}
    return {'chanlun': {'direction': '上升', 'buy_point': ch.get('chanlun_phase', '')},
            'volume_price': {'direction': 'up'}, 'chip': {'direction': 'bullish'},
            'emotion': {'rotation_state': em.get('market_phase', '')},
            'factor': {'trend': 'bullish'}}


def main():
    dm = DataManager()
    rows = sm.execute_query('strategy_signal_detail',
                            "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
                            "WHERE trade_date=? AND dim_results_json IS NOT NULL ORDER BY ts_code",
                            [TRADE_DATE])
    step = max(1, len(rows) // 300)
    sample = rows[::step][:300]
    print(f'### 494 批次3 探针  n_in={len(rows)} n_sample={len(sample)}')

    n = 0
    eng_stop = bld_stop = eng_tiers = bld_tiers = consistent = both_rules = 0
    bases = Counter()
    r4_ok = 0
    for code, dj in sample:
        try:
            dr = json.loads(dj)
        except Exception:
            continue
        df = dm.get_cached_daily_data(code)
        if df is None or getattr(df, 'empty', True):
            continue
        n += 1
        tags = {'opportunity_state': 'enter', 'right_side_confirm': '强确认'}
        try:
            e = eng(code, _dims(dr), [], df, tags=tags, dim_results=dr)
        except Exception:
            e = {}
        try:
            b = bld(code, _dims(dr), [], df, tags=tags, dim_results=dr)
        except Exception:
            b = {}
        if e.get('stop_loss_price') is not None:
            eng_stop += 1
        if e.get('profit_tiers'):
            eng_tiers += 1
        if b.get('stop_loss_price') is not None:
            bld_stop += 1
        if b.get('profit_tiers'):
            bld_tiers += 1
        if e.get('stop_loss_basis'):
            bases[e['stop_loss_basis']] += 1
        _ee = (e.get('executable') or {}).get('exit_rules') or []
        _be = (b.get('executable') or {}).get('exit_rules') or []
        if _ee and _be:
            both_rules += 1
            if _ee == _be:
                consistent += 1
        # R-4：白名单过滤（L6 advice → advice_params）
        _kept = {k: v for k, v in {'profit_tiers': e.get('profit_tiers'),
                                   'stop_loss_basis': e.get('stop_loss_basis')}.items()
                 if k in _WL and v is not None}
        if e.get('stop_loss_basis') is None or 'stop_loss_basis' in _kept:
            r4_ok += 1

    print(f'\n--- R-3 产出面（n={n}）---')
    print(f'  图谱路径 advice_engine: stop_loss_price 非空={eng_stop}   profit_tiers={eng_tiers}')
    print(f'  个股页 advice_builder: stop_loss_price 非空={bld_stop}   profit_tiers={bld_tiers}')
    print('  （494 前实测：图谱 stop/profit=0/0；个股页 stop=0、profit=43/120）')
    print(f'  stop_loss_basis 分布: {dict(bases)}')
    print('\n--- 两 builder exit_rules 止损一致（同源 SSOT）---')
    print(f'  两者均非空={both_rules}  完全一致={consistent}')
    print('\n--- R-4 白名单 ---')
    print(f'  profit_tiers/stop_loss_basis 未被白名单丢弃（或本就为 None）: {r4_ok}/{n}')


if __name__ == '__main__':
    main()
