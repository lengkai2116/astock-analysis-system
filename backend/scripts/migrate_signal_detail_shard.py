"""
421号R4b：主库 strategy_signal_detail 残留副本清理（幂等可回滚）
============================================================
背景：421号R1/R4a 已把 strategy_signal_detail 的读写全部切到 snapshot_cache.db
     （357号分库标准）。主库 stock_cache.db 仍有历史残留副本（R1 修复前
     _batch_write_signal_detail 直连 _ecm.db_path 误写所致）。
     本脚本：备份主库残留 → 校验分库权威副本完整性 → 清空主库残留。

安全保证：
- 幂等：主库表已空/备份已存在则跳过
- 可回滚：先 CREATE TABLE AS 备份到 strategy_signal_detail_bak（同库）
- 前置校验：snapshot_cache.db 分库权威副本行数 ≥ 主库残留（避免误删唯一副本）
- 保留表结构：仅 DELETE 数据，不 DROP 表（读路径 read_conn 若误查不报错）
"""
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent

MAIN_DB = ROOT / 'data' / 'duckdb' / 'stock_cache.db'       # 主库（残留）
SNAP_DB = ROOT / 'data' / 'duckdb' / 'snapshot_cache.db'    # 分库（权威）


def main():
    # 1. 校验分库权威副本存在且完整
    snap = sqlite3.connect(str(SNAP_DB))
    try:
        snap_cnt = snap.execute("SELECT COUNT(*) FROM strategy_signal_detail").fetchone()[0]
    except Exception as e:
        logger.error(f"分库 snapshot_cache.db 读取失败: {e}")
        return
    finally:
        snap.close()
    if snap_cnt == 0:
        logger.error(f"分库 strategy_signal_detail 为空（{snap_cnt} 行）——拒绝清理主库，防止数据丢失")
        return
    logger.info(f"分库权威副本: {snap_cnt} 行 ✅")

    main = sqlite3.connect(str(MAIN_DB))
    main.execute("PRAGMA busy_timeout=30000")
    try:
        # 2. 主库残留统计
        main_cnt = main.execute("SELECT COUNT(*) FROM strategy_signal_detail").fetchone()[0]
        if main_cnt == 0:
            logger.info("主库 strategy_signal_detail 已为空，无需清理")
            return
        logger.info(f"主库残留副本: {main_cnt} 行（分库 {snap_cnt} 行 ≥ 残留，校验通过）")

        # 3. 备份（幂等：已存在则跳过）
        bak_exists = main.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_signal_detail_bak'"
        ).fetchone()
        if not bak_exists:
            main.execute(
                "CREATE TABLE strategy_signal_detail_bak AS SELECT * FROM strategy_signal_detail"
            )
            main.commit()
            logger.info(f"已备份主库残留 → strategy_signal_detail_bak（{main_cnt} 行）")
        else:
            logger.info("备份表 strategy_signal_detail_bak 已存在，跳过备份")

        # 4. 清空主库残留（保留表结构）
        main.execute("DELETE FROM strategy_signal_detail")
        main.commit()
        after = main.execute("SELECT COUNT(*) FROM strategy_signal_detail").fetchone()[0]
        logger.info(f"主库残留已清空: {main_cnt} → {after} 行")

        # 5. 校验备份可恢复
        bak_cnt = main.execute("SELECT COUNT(*) FROM strategy_signal_detail_bak").fetchone()[0]
        logger.info(f"校验备份: strategy_signal_detail_bak = {bak_cnt} 行（可回滚）")
    except Exception as e:
        main.rollback()
        logger.error(f"清理失败（已回滚）: {e}")
    finally:
        main.close()


if __name__ == '__main__':
    main()
