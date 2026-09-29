"""497号 批次1（P2）：status_snapshot/history 增列 final_score 等 4 键 + 自愈补列

497号要点（详见方案 §九 批次1）：
- `_build_status_snapshot` CREATE 19→23 列（追加 final_score REAL / semantic_type /
  reliability_summary / consensus_detail TEXT）；INSERT 18→22 列 + 参数
  （legacy 无键 → row.get 返回 None 落 NULL 兼容）。
- `status_snapshot_history` 归档 CREATE + 自愈补列（对齐 494 R-5 monthly_halt 先例）
  + INSERT...SELECT 双侧同步。
- consensus_detail 仅落库不透出（Q5）。
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

_ROOT = Path(__file__).resolve().parent.parent.parent
_DAEMON = (_ROOT / 'backend' / 'data_daemon.py').read_text(encoding='utf-8')

_SNAP_COLS = """CREATE TABLE status_snapshot (
    ts_code TEXT PRIMARY KEY, snapshot_date TEXT, trade_date TEXT,
    dim_states TEXT, status_bar TEXT, opportunity_state TEXT,
    state_evidence TEXT, conflict_evidence TEXT, consensus_rate REAL,
    direction TEXT, l0 TEXT, lifecycle TEXT, advice_params TEXT,
    summary_text TEXT, one_liner_detail TEXT, dim_engine_results TEXT,
    signals TEXT, monthly_halt INTEGER, created_at TEXT,
    final_score REAL, semantic_type TEXT,
    reliability_summary TEXT, consensus_detail TEXT)"""


# ── 源码级：CREATE / INSERT / history 同步 ──

def test_daemon_create_has_final_score_columns():
    assert 'final_score REAL, semantic_type TEXT,' in _DAEMON
    assert 'reliability_summary TEXT, consensus_detail TEXT' in _DAEMON


def test_daemon_insert_has_final_score_columns():
    assert 'final_score, semantic_type, reliability_summary, consensus_detail)' in _DAEMON
    assert "row.get('final_score'), row.get('semantic_type')," in _DAEMON
    assert "row.get('reliability_summary'), row.get('consensus_detail')" in _DAEMON


def test_daemon_history_create_self_heal_insert():
    # history CREATE 含 4 新列
    assert 'reliability_summary TEXT, consensus_detail TEXT,' in _DAEMON
    # 自愈补列（对齐 signals/monthly_halt 先例）
    assert "'final_score' not in _hist_cols" in _DAEMON
    assert 'ADD COLUMN final_score REAL DEFAULT NULL' in _DAEMON
    assert 'ADD COLUMN consensus_detail TEXT DEFAULT NULL' in _DAEMON
    # INSERT...SELECT 双侧含 4 新列
    assert ('final_score, semantic_type, reliability_summary, consensus_detail)'
            in _DAEMON)
    assert ('final_score, semantic_type, reliability_summary, consensus_detail\n'
            '            FROM status_snapshot' in _DAEMON)


# ── 行为级：sqlite 模拟增列往返 + legacy NULL + 旧表自愈 ──

def test_snapshot_columns_roundtrip():
    db = os.path.join(tempfile.mkdtemp(), 'snap.db')
    c = sqlite3.connect(db)
    c.execute(_SNAP_COLS)
    c.execute(
        "INSERT INTO status_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ['A.SZ', '2026-09-29', '2026-09-28', '{}', '不可交易', 'avoid',
         '[]', '[]', -0.3, 'bear', '{}', '{}', '{}', '整体偏空', None, '{}', '[]',
         None, None, 12.5, '矛盾型', '{"structure":0.8}', '{"warn_count":3}'])
    c.commit()
    cols = {r[1] for r in c.execute('PRAGMA table_info(status_snapshot)')}
    assert {'final_score', 'semantic_type', 'reliability_summary',
            'consensus_detail'} <= cols
    row = c.execute(
        "SELECT final_score, semantic_type, reliability_summary, consensus_detail "
        "FROM status_snapshot WHERE ts_code='A.SZ'").fetchone()
    assert row == (12.5, '矛盾型', '{"structure":0.8}', '{"warn_count":3}')


def test_snapshot_legacy_missing_keys_store_null():
    """legacy（无 final_score 键）→ row.get 返回 None → 落 NULL，不破坏插入"""
    db = os.path.join(tempfile.mkdtemp(), 'snap2.db')
    c = sqlite3.connect(db)
    c.execute(_SNAP_COLS)
    c.execute(
        "INSERT INTO status_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ['B.SZ', '2026-09-29', '2026-09-28', '{}', '不可交易', 'avoid',
         '[]', '[]', -0.1, 'bear', '{}', '{}', '{}', '整体偏空', None, '{}', '[]',
         None, None, None, None, None, None])
    c.commit()
    row = c.execute(
        "SELECT final_score, semantic_type, reliability_summary, consensus_detail "
        "FROM status_snapshot WHERE ts_code='B.SZ'").fetchone()
    assert row == (None, None, None, None)


def test_history_self_heal_adds_final_score_columns():
    """旧表（无 4 新列）经自愈补列 + 归档传播值（复刻 daemon 归档段）"""
    db = os.path.join(tempfile.mkdtemp(), 'hist.db')
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE status_snapshot_history (
        ts_code TEXT, snapshot_date TEXT, dim_engine_results TEXT, signals TEXT,
        monthly_halt INTEGER, PRIMARY KEY (ts_code, snapshot_date))""")
    c.execute("""CREATE TABLE status_snapshot (
        ts_code TEXT PRIMARY KEY, snapshot_date TEXT, dim_engine_results TEXT,
        signals TEXT, monthly_halt INTEGER,
        final_score REAL, semantic_type TEXT,
        reliability_summary TEXT, consensus_detail TEXT)""")
    c.execute("INSERT INTO status_snapshot VALUES "
              "('A.SZ','2026-09-29','{}','[]',1,78.5,'矛盾型','{\"r\":1}','{\"w\":2}')")
    c.commit()
    # 复刻 daemon 归档段（CREATE-IF-NOT-EXISTS + 自愈补列 + INSERT...SELECT）
    c.execute("""CREATE TABLE IF NOT EXISTS status_snapshot_history (
        ts_code TEXT, snapshot_date TEXT, dim_engine_results TEXT, signals TEXT,
        monthly_halt INTEGER,
        final_score REAL, semantic_type TEXT,
        reliability_summary TEXT, consensus_detail TEXT,
        PRIMARY KEY (ts_code, snapshot_date))""")
    _cols = {r[1] for r in c.execute(
        "PRAGMA table_info(status_snapshot_history)").fetchall()}
    for _col, _ddl in (('signals', 'TEXT DEFAULT NULL'),
                       ('monthly_halt', 'INTEGER DEFAULT NULL'),
                       ('final_score', 'REAL DEFAULT NULL'),
                       ('semantic_type', 'TEXT DEFAULT NULL'),
                       ('reliability_summary', 'TEXT DEFAULT NULL'),
                       ('consensus_detail', 'TEXT DEFAULT NULL')):
        if _col not in _cols:
            c.execute(f"ALTER TABLE status_snapshot_history ADD COLUMN {_col} {_ddl}")
    c.execute("""INSERT OR REPLACE INTO status_snapshot_history
        (ts_code, snapshot_date, dim_engine_results, signals, monthly_halt,
         final_score, semantic_type, reliability_summary, consensus_detail)
        SELECT ts_code, snapshot_date, dim_engine_results, signals, monthly_halt,
               final_score, semantic_type, reliability_summary, consensus_detail
        FROM status_snapshot WHERE dim_engine_results IS NOT NULL""")
    c.commit()
    cols = {r[1] for r in c.execute(
        "PRAGMA table_info(status_snapshot_history)")}
    assert {'final_score', 'semantic_type', 'reliability_summary',
            'consensus_detail'} <= cols
    row = c.execute("SELECT final_score, semantic_type FROM status_snapshot_history "
                    "WHERE ts_code='A.SZ'").fetchone()
    assert row == (78.5, '矛盾型')
