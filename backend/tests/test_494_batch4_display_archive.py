"""494号 批次4 回归（R-5 history 归档 monthly_halt + R-6 前端 reduce + R-8 fixture 校准）

494号要点（详见方案 §四 批次4）：
- **R-5**：`status_snapshot_history` CREATE 增 `monthly_halt INTEGER` + 自愈补列
  （对齐 491 R4-① `signals` 先例）；归档 INSERT/SELECT 同步该列。
- **R-6**：前端 `opportunity-treemap.html` 状态行补 `reduce→建议减仓`；
  `indicator-ide.html` 标签词典 `opportunity_state` 补「建议减仓」。
- **R-8**：`tests/test_323_s6_fields.py` fixture 校准（hi 38→40 使 rr≥2）。
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


# ── R-5：history 归档 monthly_halt（源码级） ─────────────────────────

def test_daemon_history_create_has_monthly_halt():
    assert 'status_snapshot_history' in _DAEMON
    # CREATE 含 monthly_halt INTEGER
    assert 'signals TEXT, monthly_halt INTEGER,' in _DAEMON


def test_daemon_history_self_heal_adds_monthly_halt():
    assert "'monthly_halt' not in _hist_cols" in _DAEMON
    assert ("ALTER TABLE status_snapshot_history ADD COLUMN monthly_halt INTEGER"
            in _DAEMON)


def test_daemon_history_insert_select_include_monthly_halt():
    # INSERT 列表与 SELECT 列表均含 monthly_halt
    # （497号 批次1 在 monthly_halt 后追加 final_score 等 4 列：INSERT 缩进 17、SELECT 缩进 19）
    assert 'dim_engine_results, signals, monthly_halt,\n                 final_score' in _DAEMON
    assert 'dim_engine_results, signals, monthly_halt,\n                   final_score' in _DAEMON


def test_history_self_heal_behavior():
    """旧表（无 monthly_halt）经自愈补列 + 归档传播值（sqlite 模拟）"""
    db = os.path.join(tempfile.mkdtemp(), 'sim.db')
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE status_snapshot_history (
        ts_code TEXT, snapshot_date TEXT, dim_engine_results TEXT, signals TEXT,
        PRIMARY KEY (ts_code, snapshot_date))""")
    c.execute("""CREATE TABLE status_snapshot (
        ts_code TEXT PRIMARY KEY, snapshot_date TEXT, dim_engine_results TEXT,
        signals TEXT, monthly_halt INTEGER)""")
    c.execute("INSERT INTO status_snapshot VALUES ('A.SZ','2026-09-28','{}','[]',1)")
    c.execute("INSERT INTO status_snapshot VALUES ('B.SZ','2026-09-28','{}','[]',NULL)")
    c.commit()
    # 复刻 daemon 归档段
    c.execute("""CREATE TABLE IF NOT EXISTS status_snapshot_history (
        ts_code TEXT, snapshot_date TEXT, dim_engine_results TEXT, signals TEXT,
        monthly_halt INTEGER, PRIMARY KEY (ts_code, snapshot_date))""")
    _cols = {r[1] for r in c.execute("PRAGMA table_info(status_snapshot_history)").fetchall()}
    if 'signals' not in _cols:
        c.execute("ALTER TABLE status_snapshot_history ADD COLUMN signals TEXT DEFAULT NULL")
    if 'monthly_halt' not in _cols:
        c.execute("ALTER TABLE status_snapshot_history ADD COLUMN monthly_halt INTEGER DEFAULT NULL")
    c.execute("""INSERT OR REPLACE INTO status_snapshot_history
        (ts_code, snapshot_date, dim_engine_results, signals, monthly_halt)
        SELECT ts_code, snapshot_date, dim_engine_results, signals, monthly_halt
        FROM status_snapshot WHERE dim_engine_results IS NOT NULL""")
    c.commit()
    cols = {r[1] for r in c.execute("PRAGMA table_info(status_snapshot_history)")}
    assert 'monthly_halt' in cols
    rows = c.execute("SELECT ts_code, monthly_halt FROM status_snapshot_history ORDER BY ts_code").fetchall()
    assert rows == [('A.SZ', 1), ('B.SZ', None)]


# ── R-6：前端 reduce 文案（源码级） ──────────────────────────────────

def test_treemap_verdict_line_has_reduce():
    html = (_ROOT / '_ui-prototype' / 'opportunity-treemap.html').read_text(encoding='utf-8')
    assert "opportunity_state === 'reduce' ? '建议减仓'" in html


def test_indicator_ide_tag_dict_has_reduce():
    html = (_ROOT / '_ui-prototype' / 'indicator-ide.html').read_text(encoding='utf-8')
    assert "机会状态：可入场 / 轻仓 / 建议减仓 / 等待 / 回避" in html


# ── R-8：fixture 校准（hi=40 使 rr≥2） ─────────────────────────────

def test_r8_fixture_rr_within_gate():
    """_mk_df 默认 hi=40 → 几何 R:R≥RR_GATE(2.0)，enter 用例不再被降级"""
    import pandas as pd
    from app.opportunity_atlas.advice_builder import _geometric
    from app.opportunity_atlas.dim_adapter import RR_GATE
    dates = pd.date_range('2026-05-01', periods=70, freq='D')
    df = pd.DataFrame({'date': dates, 'open': 25.0, 'close': 30.0,
                       'high': 40.0, 'low': 20.0, 'volume': 1e6})
    rr = _geometric(df).get('risk_reward')
    assert rr is not None and rr >= RR_GATE, f"校准后 rr={rr} 应 ≥ {RR_GATE}"
