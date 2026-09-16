"""442号缺陷⑤A：补采 daily_cache 08-19~21 三天全市场空洞（写入 market_cache.db）

用法（必须用 backend/.venv/bin/python）：
    .venv/bin/python scripts/_442_backfill_daily_gap.py            # 补采三天全市场日线
    .venv/bin/python scripts/_442_backfill_daily_gap.py --no-backup # 跳过备份

背景：08-19/20/21 三天 daily_cache 仅 145-147 只（正常 ~5585），
  影响所有依赖日线连续性的计算（相对强弱60d、MA60/MACD 历史指标等）。
链路：复用 daemon _batch_daily（1 次 Tushare 调用/日，_ts 已做日期格式归一）。
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
logger = logging.getLogger('442_gap')

GAP_DATES = ['2026-08-19', '2026-08-20', '2026-08-21']


def _backup(db_path: str) -> str:
    if not os.path.exists(db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{db_path}.bak_442_daily_gap_{stamp}"
    shutil.copy2(db_path, bak)
    return bak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-backup', action='store_true')
    args = ap.parse_args()

    import data_daemon as dd
    dd._ensure_ecm()
    dd._ensure_pd()

    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    market_db = os.path.join(data_dir, 'duckdb', 'market_cache.db')
    if not args.no_backup:
        bak = _backup(market_db)
        if bak:
            logger.info(f"[备份] market_cache.db → {os.path.basename(bak)}")
        else:
            logger.warning(f"[备份] 未找到 {market_db}，跳过备份")

    from app.data.sharding_manager import sharding_manager
    conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_cache'))

    t0 = time.time()
    total = 0
    for d in GAP_DATES:
        before = conn.execute('SELECT COUNT(*) FROM daily_cache WHERE trade_date=?', [d]).fetchone()[0]
        n = dd._batch_daily(d)
        after = conn.execute('SELECT COUNT(*) FROM daily_cache WHERE trade_date=?', [d]).fetchone()[0]
        logger.info(f"[补采] {d}: {before} → {after} 行（新增 {after - before}）")
        total += n
    logger.info(f"[完成] 三天共采集 {total} 行，总耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == '__main__':
    sys.exit(main())
