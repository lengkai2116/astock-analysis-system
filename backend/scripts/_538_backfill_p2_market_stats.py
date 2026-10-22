"""538 P2：重采 10-21 daily_basic，并重算 market_stats_cache。

按 2026-10-22 拍板：先补采 pe_ttm；若仍全空，则由 data_daemon 的 538 守卫
允许 pe_percentile=None 落库，使 state/alerts/breadth 统一到 10-21。

用法：
  python backend/scripts/_538_backfill_p2_market_stats.py --date 2026-10-21
  python backend/scripts/_538_backfill_p2_market_stats.py --date 2026-10-21 --skip-fetch
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))


def _counts(ecm, date: str):
    df = ecm._query_shard(
        'daily_basic_cache',
        "SELECT COUNT(*) AS n, "
        "SUM(CASE WHEN pe_ttm IS NOT NULL THEN 1 ELSE 0 END) AS pe_ttm_n, "
        "SUM(CASE WHEN pe IS NOT NULL THEN 1 ELSE 0 END) AS pe_n "
        "FROM daily_basic_cache WHERE trade_date = ?", [date])
    try:
        r = df.iloc[0]
        return int(r['n']), int(r['pe_ttm_n']), int(r['pe_n'])
    except Exception:
        return -1, -1, -1


def main() -> int:
    ap = argparse.ArgumentParser(description='538 P2 PE/market_stats 补算')
    ap.add_argument('--date', default='2026-10-21')
    ap.add_argument('--skip-fetch', action='store_true',
                    help='跳过 daily_basic 重采，只重算 market_stats')
    args = ap.parse_args()

    os.environ.setdefault('DATA_DIR', str(ROOT / 'data'))
    os.environ.setdefault('DATA_DAEMON_RUNNING', '1')

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import init_sharding

    init_sharding(os.environ['DATA_DIR'])
    ecm = EnhancedCacheManager()

    print('补采前 daily_basic:', _counts(ecm, args.date))
    if not args.skip_fetch:
        from app.data.tushare_provider import TushareProvider
        provider = TushareProvider()
        raw = provider.get_daily_basic(trade_date=args.date.replace('-', ''))
        df = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw or [])
        if df.empty:
            print('  daily_basic 重采为空，保留原数据')
        else:
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            n = ecm.cache_daily_basic_data(df)
            print(f'  daily_basic 重采写入: {n if n is not None else len(df)} 行')
    print('补采后 daily_basic:', _counts(ecm, args.date))

    # 复用 daemon 的统计计算；538 守卫允许 pe_percentile 为空落库。
    import data_daemon as dd

    dd._ensure_ecm()
    if getattr(dd, '_ecm', None) is None:
        dd._ecm = ecm
    dd._precompute_market_stats(args.date, force=True)

    from app.data.sharding_manager import sharding_manager as sh_mgr
    db = sh_mgr.get_db_for_table('market_stats_cache')
    con = sh_mgr.get_connection(db)
    try:
        row = con.execute(
            "SELECT stat_date, pe_percentile, turnover_percentile, limit_ratio "
            "FROM market_stats_cache ORDER BY stat_date DESC LIMIT 2").fetchall()
        print('market_stats_cache 最新:', row)
    finally:
        con.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
