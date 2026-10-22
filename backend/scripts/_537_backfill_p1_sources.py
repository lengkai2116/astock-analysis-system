"""537 P1 数据补采：limit_detail / margin / fund_share（单日，幂等）。

用法：
  python backend/scripts/_537_backfill_p1_sources.py --date 20261021
  python backend/scripts/_537_backfill_p1_sources.py --date 20261021 --only limit
  python backend/scripts/_537_backfill_p1_sources.py --date 20261021 --dry-run

说明：走轻量入口 init_sharding + EnhancedCacheManager，不 create_app()，
避免误启 mootdx/AKShare 采集线程与 APScheduler。写库按主键覆盖，可重复执行。
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


def backfill_limit(ecm, provider, date: str) -> int:
    frames = []
    for lt in ('U', 'Z'):
        raw = provider.get_limit_list_d(date, limit_type=lt)
        if raw is not None and not raw.empty:
            df = raw.copy()
            df['limit_type'] = lt
            frames.append(df)
    if not frames:
        print('  limit_detail: 0 行（接口无数据）')
        return 0
    n = ecm.cache_limit_detail_data(pd.concat(frames, ignore_index=True))
    print(f'  limit_detail: {n} 行')
    return n


def backfill_margin(ecm, provider, date: str) -> int:
    raw = provider.get_margin_detail(date)
    if raw is None or raw.empty:
        print('  margin: 0 行（接口无数据）')
        return 0
    df = raw.copy()
    for col in ['name', 'rqchl']:
        if col in df.columns:
            df = df.drop(columns=[col])
    if 'rzmre' in df.columns:
        df['rzmje'] = df['rzmre']
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    n = ecm.cache_margin_data(df)
    print(f'  margin: {n if n is not None else len(df)} 行')
    return n if n is not None else len(df)


def backfill_fund(ecm, provider, date: str) -> int:
    raw = provider.get_fund_share(trade_date=date)
    if raw is None or raw.empty:
        print('  fund_share: 0 行（接口无数据）')
        return 0
    n = ecm.cache_fund_share_data(raw)
    print(f'  fund_share: {n} 行')
    return n


def _count(ecm, table: str, date: str) -> int:
    # 缓存表 trade_date 统一为 YYYY-MM-DD；命令行参数允许 YYYYMMDD。
    date_norm = date if '-' in date else f'{date[:4]}-{date[4:6]}-{date[6:8]}'
    df = ecm._query_shard(
        table, f"SELECT COUNT(*) AS n FROM {table} WHERE trade_date = ?",
        [date_norm])
    try:
        return int(df.iloc[0]['n'])
    except Exception:
        return -1


def main() -> int:
    ap = argparse.ArgumentParser(description='537 P1 单日补采')
    ap.add_argument('--date', default='20261021', help='YYYYMMDD')
    ap.add_argument('--only', default='all',
                    choices=['all', 'limit', 'margin', 'fund'])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    date = args.date.replace('-', '')
    print(f'537 P1 补采: date={date} only={args.only}')
    if args.dry_run:
        print('  [dry-run] 不调用接口、不写库')
        return 0

    os.environ.setdefault('DATA_DIR', str(ROOT / 'data'))
    os.environ.setdefault('DATA_DAEMON_RUNNING', '1')

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import init_sharding
    from app.data.tushare_provider import TushareProvider

    init_sharding(os.environ['DATA_DIR'])
    ecm = EnhancedCacheManager()
    provider = TushareProvider()

    if args.only in ('all', 'limit'):
        backfill_limit(ecm, provider, date)
    if args.only in ('all', 'margin'):
        backfill_margin(ecm, provider, date)
    if args.only in ('all', 'fund'):
        backfill_fund(ecm, provider, date)

    print('  补采后行数：')
    for table in ('limit_detail_cache', 'margin_cache', 'fund_share_cache'):
        print(f'    {table}: {_count(ecm, table, date)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
