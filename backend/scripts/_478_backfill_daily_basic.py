"""478号：daily_basic 历史回补（2021-07-07 → 2026-01-04，对齐 daily_cache 起点）

背景：daily_basic_cache 仅 2026-01-05 起（9 个月），daily_cache 有 5 年+ →
  dim7 pe/pb「5年分位」实为「9个月分位」→ a1/a2 锚失真（万科 pb 判"极度高估"方向存疑）。
回补：交易日 = daily_cache 已有、daily_basic 缺失的日期（2021-07-07 起）。
复用 daemon `_batch_daily_basic`（Tushare 按日全市场 1 次调用，_ts 已做日期归一）。

用法（必须用 backend/.venv/bin/python，daemon 停止态）：
    .venv/bin/python scripts/_478_backfill_daily_basic.py --smoke N   # 冒烟回补 N 个交易日
    .venv/bin/python scripts/_478_backfill_daily_basic.py             # 全量回补（~1100 交易日）
"""
import os
import sys
import time
import shutil
import argparse
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('478_backfill')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', type=int, default=0, help='冒烟回补 N 个交易日（0=全量）')
    ap.add_argument('--no-backup', action='store_true')
    args = ap.parse_args()

    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()

    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    db_path = os.path.join(data_dir, 'duckdb', 'market_cache.db')
    if not args.no_backup:
        stamp = time.strftime('%Y%m%d_%H%M%S')
        bak = f"{db_path}.bak_478_daily_basic_{stamp}"
        shutil.copy2(db_path, bak)
        logger.info(f"[备份] market_cache.db → {os.path.basename(bak)}")

    from app.data.sharding_manager import sharding_manager
    conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_basic_cache'))

    # 交易日 = daily_cache 全部日期；已有 = daily_basic 已有日期
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date").fetchall()]
    have = {r[0] for r in conn.execute(
        "SELECT DISTINCT trade_date FROM daily_basic_cache").fetchall()}
    todo = [d for d in dates if d not in have]
    logger.info(f"[478] daily_cache 交易日 {len(dates)} 个（{dates[0]} → {dates[-1]}）；"
                f"daily_basic 已有 {len(have)} 个；待回补 {len(todo)} 个")
    if not todo:
        logger.info("无需回补")
        return 0
    if args.smoke:
        todo = todo[:args.smoke]
    logger.info(f"[478] 开始回补 {len(todo)} 个交易日（{'冒烟 ' + str(args.smoke) if args.smoke else '全量'}）")

    t0 = time.time()
    ok = 0
    fail = []
    for i, d in enumerate(todo, 1):
        try:
            n = dd._batch_daily_basic(d)
            if n and n > 0:
                ok += 1
            else:
                fail.append((d, '0 行'))
        except Exception as e:
            fail.append((d, str(e)[:80]))
        if i % 50 == 0 or i == len(todo):
            logger.info(f"  进度 {i}/{len(todo)}（成功 {ok}，失败 {len(fail)}），"
                        f"耗时 {time.time()-t0:.0f}s")
    logger.info(f"[478] 完成：成功 {ok}/{len(todo)}，失败 {len(fail)}，耗时 {time.time()-t0:.0f}s")
    if fail:
        logger.warning(f"[478] 失败日期（前 10）: {fail[:10]}")

    # 验证：600519 深度
    r = conn.execute(
        "SELECT COUNT(*) FROM daily_basic_cache WHERE ts_code='600519.SH'").fetchone()
    logger.info(f"[478] 验证 600519 daily_basic 行数 = {r[0]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
