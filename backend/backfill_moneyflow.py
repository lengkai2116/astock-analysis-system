#!/usr/bin/env python3
"""
独立资金流向回填脚本 — 逐日调用 Tushare API，规避 6000 条/次上限。

用法:
  cd backend && .venv/bin/python backfill_moneyflow.py          # 回填最近25天
  cd backend && .venv/bin/python backfill_moneyflow.py --days 30 # 回填最近30天
  cd backend && .venv/bin/python backfill_moneyflow.py --dry-run # 仅查看缺失日期，不写入

后台静默运行:
  nohup .venv/bin/python backfill_moneyflow.py --days 25 > logs/backfill_moneyflow.log 2>&1 &
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta

# 确保 backend 在 sys.path 中
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

# 清除代理环境变量（与 data_daemon.py 保持一致）
for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
           'http_proxy', 'https_proxy', 'all_proxy']:
    os.environ.pop(_k, None)


def get_existing_dates():
    """查询 moneyflow_cache 已有日期"""
    from app.data.sharding_manager import sharding_manager
    conn = sharding_manager.get_connection(
        sharding_manager.get_db_for_table('daily_cache')
    )
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM moneyflow_cache"
    ).fetchall()
    return {str(r[0]).replace('-', '') for r in rows}


def get_trading_days(cutoff_date: str):
    """从 daily_cache 获取交易日列表"""
    from app.data.sharding_manager import sharding_manager
    conn = sharding_manager.get_connection(
        sharding_manager.get_db_for_table('daily_cache')
    )
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM daily_cache "
        "WHERE trade_date >= ? ORDER BY trade_date",
        [cutoff_date]
    ).fetchall()
    return [str(r[0]).replace('-', '') for r in rows]


def backfill_one_day(pro, ecm, trade_date: str) -> int:
    """回填单日资金流向数据"""
    import pandas as pd
    raw = pro.moneyflow(trade_date=trade_date)
    if raw is None or raw.empty:
        return 0
    df = raw.copy()
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    # 补齐 net_* 列
    for net_col, buy_col in [('net_lg_amount', 'buy_lg_amount'),
                              ('net_elg_amount', 'buy_elg_amount'),
                              ('net_sm_amount', 'buy_sm_amount')]:
        if net_col not in df.columns and buy_col in df.columns:
            sell_col = 'sell_' + buy_col[4:]
            df[net_col] = (df[buy_col].fillna(0)
                           - df.get(sell_col, pd.Series([0] * len(df))).fillna(0))
    ecm.cache_moneyflow_data(df)
    return len(df)


def main():
    parser = argparse.ArgumentParser(description='资金流向逐日回填')
    parser.add_argument('--days', type=int, default=25,
                        help='回填最近N个交易日（默认25）')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅查看缺失日期，不实际写入')
    args = parser.parse_args()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 资金流向回填启动")
    print(f"  目标: 最近 {args.days} 个交易日")

    # 查已有数据
    existing = get_existing_dates()
    print(f"  已有: {len(existing)} 天")

    # 查交易日（cutoff 用 YYYY-MM-DD 格式匹配 DB 存储格式）
    cutoff = (datetime.now() - timedelta(days=args.days + 10)).strftime('%Y-%m-%d')
    trading_days = get_trading_days(cutoff)
    missing = [d for d in trading_days if d not in existing]
    print(f"  需回填: {len(missing)} 天")

    if not missing:
        print("  无缺失数据，退出")
        return

    for i, d in enumerate(missing):
        print(f"    [{i+1}/{len(missing)}] {d}")

    if args.dry_run:
        print("\n[dry-run] 以上日期需要回填，未执行写入")
        return

    # 初始化
    import tushare as ts
    pro = ts.pro_api()
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    total = 0
    errors = 0
    for i, dt in enumerate(missing):
        try:
            count = backfill_one_day(pro, ecm, dt)
            total += count
            status = f"{count} 条" if count > 0 else "无数据"
            print(f"  [{i+1}/{len(missing)}] {dt}: {status}")
        except Exception as e:
            errors += 1
            print(f"  [{i+1}/{len(missing)}] {dt}: 失败 - {e}")

        # Tushare 限频保护：每次调用间隔约 0.35s（_ts 内部已有保护，此处额外保险）
        if i < len(missing) - 1:
            time.sleep(0.2)

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 回填完成: {total} 条, {errors} 个错误")


if __name__ == '__main__':
    main()
