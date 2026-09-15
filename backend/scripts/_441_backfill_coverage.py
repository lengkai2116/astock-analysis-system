"""441号 D·通道②增强：一次性全量预补三张富字段素材表缺口（写入 history_cache.db）

用法（必须用 backend/.venv/bin/python）：
    .venv/bin/python scripts/_441_backfill_coverage.py --smoke N         # 冒烟补采 N 只/表
    .venv/bin/python scripts/_441_backfill_coverage.py --table stk         # 仅补某表（top10|stk|finance）
    .venv/bin/python scripts/_441_backfill_coverage.py                     # 三表全量一次性补足

前提：
  - 确认无 data_daemon 进程（避免与本脚本写库竞争）
  - 建议先备份 history_cache.db（本脚本默认 --backup 会自动备份）
缺口判定：全管道活跃股票池（_get_active_codes，441号A 已剔指数）∩ 各 cache 表 DISTINCT 缺失。
链路：复用 daemon 模块级单只补采辅助（_sync_single_finance/_sync_single_stk_holder/_sync_single_top10_holders）。
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
logger = logging.getLogger('441_coverage')


# 三张富字段素材表 → (cache表, daemon单只补采函数, 标签)
_TABLES = [
    ('top10_holders_cache',  '_sync_single_top10_holders', '前十大股东'),
    ('stk_holder_cache',     '_sync_single_stk_holder',    '股东人数'),
    ('finance_report_cache', '_sync_single_finance',       '扩展财务'),
]


def _import_daemon():
    """延迟导入 data_daemon（需在 DATA_DIR 就绪后）"""
    import data_daemon as dd
    return dd


def _backup(history_db_path: str) -> str:
    """备份 history_cache.db，返回备份路径"""
    if not os.path.exists(history_db_path):
        return ''
    stamp = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{history_db_path}.bak_441_d_{stamp}"
    shutil.copy2(history_db_path, bak)
    return bak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', type=int, default=0, help='冒烟补采 N 只/表（0=全量）')
    ap.add_argument('--table', choices=['top10', 'stk', 'finance', 'all'], default='all',
                    help='仅补某表（默认 all 三表）')
    ap.add_argument('--no-backup', action='store_true', help='跳过自动备份')
    args = ap.parse_args()

    dd = _import_daemon()
    dd._ensure_ecm()

    # ── 备份 ──
    data_dir = os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    history_db = os.path.join(data_dir, 'duckdb', 'history_cache.db')
    if not args.no_backup:
        bak = _backup(history_db)
        if bak:
            logger.info(f"[备份] history_cache.db → {os.path.basename(bak)}")
        else:
            logger.warning(f"[备份] 未找到 {history_db}，跳过备份")

    # ── 缺口清单 ──
    active = dd._get_active_codes()
    if not active:
        logger.error("active 股票池为空，中止")
        return 1
    active_set = set(active)
    logger.info(f"[目标] active 股票池 {len(active)} 只")

    # ── 组装待补（按 --table 过滤）──
    def _pick(db_table, tag):
        if args.table != 'all' and tag != args.table:
            return (None, [], None)
        try:
            rows = dd._shard_fetchall(
                db_table, f'SELECT DISTINCT ts_code FROM "{db_table}"')
            covered = {r[0] for r in rows}
            missing = [c for c in active if c not in covered]
            return (db_table, missing, tag)
        except Exception as e:
            logger.warning(f"  [{db_table}] 查询失败: {e}")
            return (None, [], None)

    jobs = []
    for db_table, sync_name, label in _TABLES:
        tag = label
        if '前十大' in label:
            tag = 'top10'
        elif '股东' in label:
            tag = 'stk'
        else:
            tag = 'finance'
        db_table, missing, _ = _pick(db_table, tag)
        if db_table and missing:
            jobs.append((db_table, getattr(dd, sync_name), label, missing))

    total_gap = sum(len(m) for _, _, _, m in jobs)
    if not jobs:
        logger.info("[缺口] 所选表无缺失，无需补采")
        return 0
    logger.info(f"[缺口] 待补 {len(jobs)} 表，共 {total_gap} 只："
                + ', '.join(f"{label}({len(m)})" for _, _, label, m in jobs))

    # ── 逐表补采 ──
    t0 = time.time()
    ok_total = fail_total = 0
    for db_table, sync_fn, label, missing in jobs:
        # 冒烟：每表只取前 args.smoke 只
        batch = (missing[:args.smoke] if args.smoke else missing)
        ok = fail = 0
        logger.info(f"\n===== [{label}] 补采 {len(batch)} 只（总缺 {len(missing)}）=====")
        for i, code in enumerate(batch, 1):
            try:
                n = sync_fn(code)
                if n:
                    ok += 1
                else:
                    fail += 1
                    logger.warning(f"  {code}: 单只补采空返回（数据源无该素材）")
            except Exception as e:
                fail += 1
                logger.warning(f"  {code}: 失败 {e}")
            if i % 50 == 0 or args.smoke:
                logger.info(f"  [{label}] {i}/{len(batch)} ok={ok} fail={fail}")
        ok_total += ok
        fail_total += fail
        logger.info(f"  → [{label}] 完成：成功 {ok}，失败/空 {fail}")

    logger.info(f"\n[完成] 成功 {ok_total}，失败/空 {fail_total}，总耗时 {time.time()-t0:.1f}s")
    return 0


if __name__ == '__main__':
    sys.exit(main())
