"""541号 OCR 修复：opportunity_tags_cache 归档脚本定向测试。

覆盖：
- dry-run 以只读方式打开，不创建归档表；
- --apply 建表并复制；
- 归档表已存在时中止，--overwrite 才覆盖。
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1]
          / 'scripts' / '_541_archive_opportunity_tags.py')


def _load_script():
    spec = importlib.util.spec_from_file_location('archive541', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_db(tmp_path) -> Path:
    db = tmp_path / 'duckdb' / 'compute_cache.db'
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE opportunity_tags_cache (ts_code TEXT, tag_name TEXT)')
    conn.execute(
        "INSERT INTO opportunity_tags_cache VALUES ('000001.SZ', 'x')")
    conn.execute(
        "INSERT INTO opportunity_tags_cache VALUES ('600000.SH', 'y')")
    conn.commit()
    conn.close()
    return db


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
    try:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_dry_run_is_read_only_and_creates_nothing(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['script'])
    before = _tables(db)

    _load_script().main()

    assert _tables(db) == before


def test_apply_creates_archive_and_refuses_existing(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    module = _load_script()

    monkeypatch.setattr(
        sys, 'argv', ['script', '--apply', '--table', 'archive_t1'])
    module.main()
    assert 'archive_t1' in _tables(db)

    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            'SELECT COUNT(*) FROM archive_t1').fetchone()[0] == 2
    finally:
        conn.close()

    with pytest.raises(SystemExit):
        module.main()

    monkeypatch.setattr(
        sys, 'argv',
        ['script', '--apply', '--table', 'archive_t1', '--overwrite'])
    module.main()
