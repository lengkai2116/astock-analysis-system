#!/usr/bin/env python3
"""541 B5：归档 opportunity_tags_cache（默认 dry-run，不删除原表）。

用法：
  python backend/scripts/_541_archive_opportunity_tags.py            # 只统计
  python backend/scripts/_541_archive_opportunity_tags.py --apply    # 复制到归档表
  python backend/scripts/_541_archive_opportunity_tags.py --apply --overwrite
"""
import argparse
import os
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='执行复制（默认只统计）')
    parser.add_argument('--table', default=None,
                        help='归档表名（默认按当天日期生成）')
    parser.add_argument('--overwrite', action='store_true',
                        help='归档表已存在时先 DROP 再复制')
    args = parser.parse_args()

    table = args.table or (
        f'opportunity_tags_cache_archive_{time.strftime("%Y%m%d")}')
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', table):
        raise SystemExit('非法归档表名')

    data_dir = Path(os.getenv('DATA_DIR') or (ROOT / 'data'))
    db_path = data_dir / 'duckdb' / 'compute_cache.db'
    if not db_path.exists():
        raise SystemExit(f'数据库不存在: {db_path}')

    if not args.apply:
        conn = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)
        try:
            source_count = conn.execute(
                'SELECT COUNT(*) FROM opportunity_tags_cache').fetchone()[0]
            print(f'源表行数: {source_count:,}')
            print(f'归档表: {table}')
            print('dry-run：未写入。确认后加 --apply 复制（原表保留）')
        finally:
            conn.close()
        return

    conn = sqlite3.connect(db_path)
    try:
        source_count = conn.execute(
            'SELECT COUNT(*) FROM opportunity_tags_cache').fetchone()[0]
        print(f'源表行数: {source_count:,}')
        print(f'归档表: {table}')

        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            [table]).fetchone()
        if exists:
            if not args.overwrite:
                raise SystemExit(
                    f'归档表已存在: {table}（如需覆盖请加 --overwrite）')
            conn.execute(f'DROP TABLE {table}')

        conn.execute(
            f'CREATE TABLE {table} AS SELECT * FROM opportunity_tags_cache')
        archive_count = conn.execute(
            f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        conn.commit()
        print(f'归档行数: {archive_count:,}')
        if archive_count != source_count:
            raise SystemExit('归档行数与源表不一致')
        print('归档完成；原 opportunity_tags_cache 保留未删除')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
