"""545号 A4：按指定交易日回补 RAW-2C / SIG / JUD 产物（默认 dry-run）。

用法（从项目根目录）：
  backend/.venv/bin/python backend/scripts/_545_backfill_sig_jud_out.py --date 20261021
  backend/.venv/bin/python backend/scripts/_545_backfill_sig_jud_out.py --date 20261021 --limit 5 --apply
  backend/.venv/bin/python backend/scripts/_545_backfill_sig_jud_out.py --date 20261021 --apply --skip-raw2c

前置：必须先停 data_daemon（避免写库竞争与管道重入）。脚本自检并拒绝运行，
      --force 可跳过该保护（不建议）。
说明：
  - 设置 DATA_DAEMON_RUNNING=1，create_app() 不再注册采集线程；
  - JUD 产物写 status_snapshot_history / treemap_snapshot_history，绝不替换 live 表；
  - SIG 按 (ts_code, trade_date) 覆盖写，写前清掉该日影子行。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))


def _norm_date(date: str) -> str:
    d = date.replace('-', '')[:8]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _daemon_running() -> bool:
    try:
        out = subprocess.run(['pgrep', '-f', 'data_daemon.py'],
                             capture_output=True, text=True).stdout.strip()
        return bool(out)
    except Exception:
        return False


def _count(ecm, table: str, date_col: str, date: str) -> int:
    try:
        df = ecm._query_shard(table, f"SELECT COUNT(*) AS n FROM {table} WHERE {date_col} = ?", [date])
        return int(df.iloc[0]['n']) if df is not None and not df.empty else 0
    except Exception:
        return -1


def main() -> int:
    ap = argparse.ArgumentParser(description='545号：指定交易日回补 SIG/JUD')
    ap.add_argument('--date', required=True, help='目标交易日 YYYYMMDD')
    ap.add_argument('--apply', action='store_true', help='实际写库（默认 dry-run）')
    ap.add_argument('--limit', type=int, default=0, help='仅处理前 N 只（冒烟测试）')
    ap.add_argument('--skip-raw2c', action='store_true', help='跳过 RAW-2C 行业位置')
    ap.add_argument('--force', action='store_true', help='daemon 运行时仍执行（不建议）')
    args = ap.parse_args()

    date = _norm_date(args.date)
    print(f"545 A4 回补: date={date} apply={args.apply} limit={args.limit or 'all'}")

    if args.apply and _daemon_running() and not args.force:
        print("❌ data_daemon 正在运行：回补会与管道争写。请先停 daemon（含看守），或加 --force。")
        return 2
    if _daemon_running() and not args.apply:
        print("  （daemon 运行中：dry-run 只读，不做写库）")

    os.environ.setdefault('DATA_DIR', str(ROOT / 'data'))
    os.environ['DATA_DAEMON_RUNNING'] = '1'

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import init_sharding

    init_sharding(os.environ['DATA_DIR'])
    ecm = EnhancedCacheManager()

    # 1) 目标日股票池：以 pre_feat_cache 为准（RAW-2 产物）
    df = ecm._query_shard('pre_feat_cache',
                          "SELECT ts_code FROM pre_feat_cache WHERE trade_date = ? ORDER BY ts_code",
                          [date])
    codes = list(df['ts_code']) if df is not None and not df.empty else []
    if args.limit:
        codes = codes[:args.limit]
    print(f"  股票池(pre_feat): {len(codes)}")
    if not codes:
        print("❌ 目标日无 pre_feat 数据，先确认 RAW-2 已跑完该日。")
        return 3

    # 2) 前置覆盖
    print(f"  RAW-2C industry_position: {_count(ecm, 'industry_position_cache', 'asof_date', date)}")
    print(f"  SIG strategy_signal_detail: {_count(ecm, 'strategy_signal_detail', 'trade_date', date)}")
    print(f"  JUD status_snapshot_history: {_count(ecm, 'status_snapshot_history', 'trade_date', date)}")
    print(f"  JUD treemap_snapshot_history: {_count(ecm, 'treemap_snapshot_history', 'trade_date', date)}")

    if not args.apply:
        print("  [dry-run] 不计算、不写库；加 --apply 执行。")
        return 0

    import data_daemon as dd
    dd._ecm = ecm

    # 3) RAW-2C（历史日缺该原料时补算）
    if not args.skip_raw2c:
        have = _count(ecm, 'industry_position_cache', 'asof_date', date)
        if have < len(codes):
            print("  RAW-2C: 补算行业位置 ...")
            dd._precompute_industry_position(codes, as_of=date)
            print(f"  RAW-2C 完成: {_count(ecm, 'industry_position_cache', 'asof_date', date)}")

    # 4) 清掉目标日影子行（519号：骨架行会顶掉 MAX(trade_date)）
    try:
        from app.data.sharding_manager import sharding_manager
        sharding_manager.execute_write('strategy_signal_detail',
                                       "DELETE FROM strategy_signal_detail WHERE trade_date = ?", [date])
    except Exception as e:
        print(f"  ⚠️ 影子行清理失败（继续）: {e}")

    # 5) SIG → JUD（写 history）
    print("  SIG: 按日重算 ...")
    dd._precompute_strategy_signals(codes, as_of=date)
    print(f"  SIG 完成: {_count(ecm, 'strategy_signal_detail', 'trade_date', date)}")

    print("  JUD: status_snapshot → history ...")
    dd._build_status_snapshot(codes, as_of=date)
    dd._jud_enrich_with_meta(codes, as_of=date)
    print("  JUD: treemap_snapshot → history ...")
    dd._build_treemap_snapshot(codes, as_of=date)

    print("  回补后覆盖：")
    for table, col in (('strategy_signal_detail', 'trade_date'),
                       ('status_snapshot_history', 'trade_date'),
                       ('treemap_snapshot_history', 'trade_date'),
                       ('industry_position_cache', 'asof_date')):
        print(f"    {table}: {_count(ecm, table, col, date)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
