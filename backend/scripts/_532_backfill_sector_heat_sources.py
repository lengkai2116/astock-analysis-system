#!/usr/bin/env python3
"""532号 批次1 回填：板块热度五维原料（新增表，不动旧核算/旧消费）。

覆盖：
  - 申万一级行业指数历史（写入既有 daily_cache，复用 _batch_index_daily 同口径）
  - HS300 历史（写入既有 daily_cache）
  - ETF 份额（fund_share_cache）
  - 涨停/炸板明细（limit_detail_cache）
  - 北向市场级（northbound_flow_cache）
  - ETF→申万一级/主题映射（etf_industry_map）

用法（回填前必须先停 data_daemon 与看守）：
  python backend/scripts/_532_backfill_sector_heat_sources.py --days 250
  python backend/scripts/_532_backfill_sector_heat_sources.py --days 120 --only limit
  python backend/scripts/_532_backfill_sector_heat_sources.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

_SW_COL_MAP = {'pct_change': 'pct_chg'}
_DAILY_COLS = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close',
               'vol', 'amount', 'pct_chg']


def _trade_dates(ecm, days: int) -> list[str]:
    df = ecm._query_shard(
        'daily_cache',
        "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT ?",
        [int(days)])
    if df is None or df.empty:
        return []
    return sorted(str(x) for x in df['trade_date'].tolist())


def _normalize_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(columns=_SW_COL_MAP).copy()
    if 'trade_date' in out.columns:
        out['trade_date'] = pd.to_datetime(out['trade_date']).dt.strftime('%Y-%m-%d')
    keep = [c for c in _DAILY_COLS if c in out.columns]
    return out[keep]


def backfill_sw(ecm, provider, start: str, end: str) -> int:
    from app.data.market_universe import SW_INDEX_CODES

    total = 0
    ok = 0
    for code in SW_INDEX_CODES:
        raw = provider.get_sw_index_daily(code, start_date=start, end_date=end)
        df = _normalize_daily(raw)
        if df.empty:
            continue
        ecm.cache_daily_data(df)
        total += len(df)
        ok += 1
    print(f"  申万行业指数: {ok}/{len(SW_INDEX_CODES)} 个, {total} 行")
    return total


def backfill_hs300(ecm, provider, start: str, end: str) -> int:
    raw = provider.get_index_daily_range('000300.SH', start_date=start, end_date=end)
    df = _normalize_daily(raw)
    if df.empty:
        print("  HS300: 0 行")
        return 0
    ecm.cache_daily_data(df)
    print(f"  HS300: {len(df)} 行")
    return len(df)


def backfill_fund_share(ecm, provider, dates: list[str]) -> int:
    total = 0
    for d in dates:
        raw = provider.get_fund_share(trade_date=d.replace('-', ''))
        if raw is None or raw.empty:
            continue
        total += ecm.cache_fund_share_data(raw)
    print(f"  ETF份额: {total} 行 / {len(dates)} 个交易日")
    return total


def _fetch_limit_list(provider, trade_date: str, limit_type: str):
    """limit_list_d 200 次/分钟限频：失败重试 3 次（每次退避 2s）。"""
    for _ in range(3):
        raw = provider.get_limit_list_d(trade_date, limit_type=limit_type)
        if raw is not None:
            return raw
        time.sleep(2.0)
    return None


def backfill_limit_detail(ecm, provider, dates: list[str]) -> int:
    """补齐涨停/炸板明细：跳过已有日期 + 0.35s 节流（≤200次/分钟）。"""
    existing = set()
    try:
        df = ecm._query_shard(
            'limit_detail_cache',
            "SELECT DISTINCT trade_date FROM limit_detail_cache")
        if df is not None and not df.empty:
            existing = {str(x) for x in df['trade_date'].tolist()}
    except Exception:
        pass
    todo = [d for d in dates if d not in existing]
    print(f"  涨停/炸板明细: 待补 {len(todo)}/{len(dates)} 日（已有 {len(existing)} 日）")
    total = 0
    for d in todo:
        frames = []
        for lt in ('U', 'Z'):
            raw = _fetch_limit_list(provider, d.replace('-', ''), lt)
            time.sleep(0.35)  # limit_list_d 限频 200次/分钟
            if raw is not None and not raw.empty:
                df = raw.copy()
                df['limit_type'] = lt
                frames.append(df)
        if frames:
            total += ecm.cache_limit_detail_data(pd.concat(frames, ignore_index=True))
    print(f"  涨停/炸板明细: 新增 {total} 行 / 补齐 {len(todo)} 日")
    return total


def backfill_northbound(ecm, provider, start: str, end: str) -> int:
    raw = provider.get_moneyflow_hsgt(start_date=start, end_date=end)
    if raw is None or raw.empty:
        print("  北向市场级: 0 行")
        return 0
    n = ecm.cache_northbound_flow_data(raw)
    print(f"  北向市场级: {n} 行")
    return n


def refresh_etf_map(ecm) -> int:
    from app.data.etf_industry_map import refresh_etf_industry_map

    n = refresh_etf_industry_map(ecm, force=True)
    print(f"  ETF行业映射: {n} 条")
    return n


def main():
    ap = argparse.ArgumentParser(description='532号 批次1 回填（板块热度五维原料）')
    ap.add_argument('--days', type=int, default=250, help='回填交易日数（默认 250）')
    ap.add_argument('--only', default='all',
                    choices=['all', 'sw', 'hs300', 'etf', 'limit', 'north', 'etfmap'],
                    help='只回填某一类')
    ap.add_argument('--dry-run', action='store_true', help='只打印计划，不调用接口/不写库')
    args = ap.parse_args()

    print('⚠️  回填会写库；请确认 data_daemon 与看守已停止。')
    os.environ.setdefault('DATA_DIR', str(ROOT / 'data'))
    os.environ.setdefault('DATA_DAEMON_RUNNING', '1')

    # 轻量入口：只初始化分库 + ECM，不 create_app（避免误启采集/调度器）
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import init_sharding
    from app.data.tushare_provider import TushareProvider

    init_sharding(os.environ['DATA_DIR'])
    ecm = EnhancedCacheManager()
    dates = _trade_dates(ecm, args.days)
    if not dates:
        print('❌ daily_cache 无可用交易日，终止。')
        return 1
    start, end = dates[0], dates[-1]
    print(f'窗口: {start} ~ {end}（{len(dates)} 个交易日, days={args.days}）')

    plan = {
        'sw': '申万行业指数历史 → daily_cache',
        'hs300': 'HS300 历史 → daily_cache',
        'etf': f'ETF 份额 → fund_share_cache（{len(dates)} 日）',
        'limit': f'涨停/炸板明细 → limit_detail_cache（{min(len(dates), 120)} 日）',
        'north': '北向市场级 → northbound_flow_cache',
        'etfmap': 'ETF→行业映射 → etf_industry_map',
    }
    todo = list(plan) if args.only == 'all' else [args.only]
    if args.dry_run:
        for k in todo:
            print(f'  [dry-run] {plan[k]}')
        return 0

    provider = TushareProvider()
    if args.only in ('all', 'sw'):
        backfill_sw(ecm, provider, start.replace('-', ''), end.replace('-', ''))
    if args.only in ('all', 'hs300'):
        backfill_hs300(ecm, provider, start.replace('-', ''), end.replace('-', ''))
    if args.only in ('all', 'etf'):
        backfill_fund_share(ecm, provider, dates)
    if args.only in ('all', 'limit'):
        backfill_limit_detail(ecm, provider, dates[-min(len(dates), 120):])
    if args.only in ('all', 'north'):
        backfill_northbound(ecm, provider, start.replace('-', ''), end.replace('-', ''))
    if args.only in ('all', 'etfmap'):
        refresh_etf_map(ecm)
    print('✅ 回填完成（幂等：重复执行按主键覆盖）。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
