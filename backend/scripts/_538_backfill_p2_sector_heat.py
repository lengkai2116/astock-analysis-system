"""538 P2：补算板块资金热度 sector_fund_heat_cache（10-20/10-21）。

口径与 data_daemon._precompute_sector_fund_heat（530 RAW-2D）一致：
近5日主力净流入（大单+特大单−大单−特大单，万元）÷ 当日流通市值（万元）×100。

用法：
  python backend/scripts/_538_backfill_p2_sector_heat.py
  python backend/scripts/_538_backfill_p2_sector_heat.py --dates 2026-10-20 2026-10-21
  python backend/scripts/_538_backfill_p2_sector_heat.py --dry-run

轻量入口：只 init_sharding + EnhancedCacheManager，不 create_app()。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))


def backfill_one(ecm, target: str, dry_run: bool = False) -> int:
    from app.data.sharding_manager import sharding_manager as sh_mgr
    from app.data.sw_industry_map import get_sw_industry_map, normalize_code

    sw_map = get_sw_industry_map(ecm) or {}
    if not sw_map:
        print(f'  {target}: 申万映射为空，跳过')
        return 0

    dates_df = ecm._query_shard(
        'moneyflow_cache',
        "SELECT DISTINCT trade_date FROM moneyflow_cache "
        "WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 5", [target])
    dates = sorted(str(v) for v in dates_df['trade_date'].tolist()) \
        if dates_df is not None and not dates_df.empty else []
    if not dates:
        print(f'  {target}: moneyflow 无数据，跳过')
        return 0
    start = dates[0]

    mf_df = ecm._query_shard(
        'moneyflow_cache',
        "SELECT ts_code, buy_lg_amount, buy_elg_amount, sell_lg_amount, "
        "sell_elg_amount FROM moneyflow_cache "
        "WHERE trade_date >= ? AND trade_date <= ?", [start, target])
    net_5d = defaultdict(float)
    if mf_df is not None and not mf_df.empty:
        for r in mf_df.to_dict('records'):
            code = str(r.get('ts_code') or '')
            ind = sw_map.get(normalize_code(code))
            if not ind:
                continue
            net = (float(r.get('buy_lg_amount') or 0)
                   + float(r.get('buy_elg_amount') or 0)
                   - float(r.get('sell_lg_amount') or 0)
                   - float(r.get('sell_elg_amount') or 0))
            net_5d[ind] += net
    if not net_5d:
        print(f'  {target}: 净流入聚合为空，跳过')
        return 0

    cb_df = ecm._query_shard(
        'daily_basic_cache',
        "SELECT ts_code, circ_mv FROM daily_basic_cache WHERE trade_date = ?",
        [target])
    circ_mv = defaultdict(float)
    if cb_df is not None and not cb_df.empty:
        for r in cb_df.to_dict('records'):
            ind = sw_map.get(normalize_code(str(r.get('ts_code') or '')))
            if ind:
                circ_mv[ind] += float(r.get('circ_mv') or 0)

    rows = []
    for ind, net in net_5d.items():
        mv = circ_mv.get(ind, 0.0)
        if mv <= 0:
            continue
        rows.append({
            'industry': ind,
            'net_inflow_5d': round(net, 1),
            'circ_mv': round(mv, 1),
            'ratio': round(net / mv * 100, 4),
        })
    if not rows:
        print(f'  {target}: 占比计算为空，跳过')
        return 0

    rows.sort(key=lambda x: -x['ratio'])
    for i, r in enumerate(rows):
        r['rank'] = i + 1
        r['heat_level'] = ('top_10' if i < 10 else
                           'top_20' if i < 20 else
                           'normal' if i < 40 else 'none')

    print(f'  {target}: 窗口 {start}~{target}，{len(rows)} 个行业，'
          f'Top1={rows[0]["industry"]}({rows[0]["ratio"]}%)')
    if dry_run:
        return len(rows)

    db = sh_mgr.get_db_for_table('sector_fund_heat_cache')
    conn = sh_mgr.get_connection(db)
    lock = sh_mgr.get_write_lock(db)
    with lock:
        conn.execute("DELETE FROM sector_fund_heat_cache WHERE stat_date = ?",
                     [target])
        conn.executemany(
            "INSERT INTO sector_fund_heat_cache "
            "(stat_date, industry, net_inflow_5d, circ_mv, ratio, rank, heat_level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(target, r['industry'], r['net_inflow_5d'], r['circ_mv'],
              r['ratio'], r['rank'], r['heat_level']) for r in rows])
        conn.commit()
    print(f'  {target}: 已写入 {len(rows)} 行 -> {db}')
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description='538 P2 板块资金热度补算')
    ap.add_argument('--dates', nargs='*',
                    default=['2026-10-20', '2026-10-21'])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    os.environ.setdefault('DATA_DIR', str(ROOT / 'data'))
    os.environ.setdefault('DATA_DAEMON_RUNNING', '1')

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import init_sharding

    init_sharding(os.environ['DATA_DIR'])
    ecm = EnhancedCacheManager()
    total = 0
    for d in args.dates:
        total += backfill_one(ecm, d, dry_run=args.dry_run)
    print(f'完成：{total} 行' + ('（dry-run 未写库）' if args.dry_run else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
