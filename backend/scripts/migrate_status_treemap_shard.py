"""
421号R4b 延伸：主库 status_snapshot / treemap_snapshot 残留副本清理（幂等可回滚）
============================================================
背景：375号T1 只切了读方（sharding_manager 读 snapshot_cache.db），JUD 写
     status_snapshot / treemap_snapshot 仍走 _ecm.conn（主库），造成读写分叉。
     421号R4a补充修复已把 JUD/OUT 写路径全部切到 snapshot_cache.db 分库。
     主库 stock_cache.db 仍有残留副本（09-09 旧批次），成为只写不读的死数据。

安全保证（对齐 migrate_signal_detail_shard.py）：
- 幂等：主库表已空/备份已存在则跳过
- 可回滚：先 CREATE TABLE AS 备份到 <表名>_bak（同库）
- 前置校验：snapshot_cache.db 分库权威副本行数 > 0（避免误删唯一副本）
- 保留表结构：仅 DELETE 数据，不 DROP 表
"""
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent

MAIN_DB = ROOT / 'data' / 'duckdb' / 'stock_cache.db'       # 主库（残留）
SNAP_DB = ROOT / 'data' / 'duckdb' / 'snapshot_cache.db'    # 分库（权威）

TABLES = ('status_snapshot', 'treemap_snapshot')


def _count(conn, table):
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return None


def main():
    snap = sqlite3.connect(str(SNAP_DB))
    snap.execute('PRAGMA busy_timeout=30000')
    main = sqlite3.connect(str(MAIN_DB))
    main.execute('PRAGMA busy_timeout=30000')
    try:
        for table in TABLES:
            logger.info(f"── {table} ──")
            # 1. 校验分库权威副本存在
            snap_cnt = _count(snap, table)
            if not snap_cnt:
                logger.error(f"分库 {table} 为空/不存在（{snap_cnt}）——拒绝清理主库，防止数据丢失")
                continue
            logger.info(f"分库权威副本: {snap_cnt} 行 ✅")

            # 2. 主库残留统计
            main_cnt = _count(main, table)
            if main_cnt is None:
                logger.info(f"主库无 {table} 表，跳过")
                continue
            if main_cnt == 0:
                logger.info("主库已为空，无需清理")
                continue
            logger.info(f"主库残留副本: {main_cnt} 行（分库 {snap_cnt} 行，校验通过）")

            # 3. 备份（幂等）
            bak = f"{table}_bak"
            bak_exists = main.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [bak]
            ).fetchone()
            if not bak_exists:
                main.execute(f"CREATE TABLE {bak} AS SELECT * FROM {table}")
                main.commit()
                logger.info(f"已备份主库残留 → {bak}（{main_cnt} 行）")
            else:
                logger.info(f"备份表 {bak} 已存在，跳过备份")

            # 4. 清空主库残留（保留表结构）
            main.execute(f"DELETE FROM {table}")
            main.commit()
            after = _count(main, table)
            logger.info(f"主库残留已清空: {main_cnt} → {after} 行")

            # 5. 校验备份可恢复
            bak_cnt = _count(main, bak)
            logger.info(f"校验备份: {bak} = {bak_cnt} 行（可回滚）")
    except Exception as e:
        main.rollback()
        logger.error(f"清理失败（已回滚）: {e}")
    finally:
        snap.close()
        main.close()


if __name__ == '__main__':
    main()
