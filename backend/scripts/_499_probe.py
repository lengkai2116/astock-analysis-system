"""499号 验证探针（只读）：12 处分库读 SQL 逐一跑通 + #5 信号回算分库取数"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data import DataManager
ecm = DataManager().cache
from app.data.sharding_manager import sharding_manager

ok = []
def chk(n, sql, params=None, table='daily_cache'):
    df = ecm._query_shard(table, sql, params)
    n_empty = len(df)
    ok.append(n_empty >= 0)
    print(f"  #{n}: rows={n_empty}  {'OK' if n_empty>0 else 'EMPTY(但查询未抛错)'}")

print("=== 12 处分库读 SQL 逐一跑通 ===")
LATEST = "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
chk(1, LATEST)
chk(2, """SELECT ts_code, COUNT(*) as cnt, MAX(trade_date) as last_date, MIN(trade_date) as first_date
          FROM daily_cache GROUP BY ts_code HAVING cnt < ? ORDER BY cnt ASC LIMIT ?""", [120, 100])
chk(3, "SELECT COUNT(DISTINCT trade_date) AS n FROM daily_basic_cache", table='daily_basic_cache')
chk(4, LATEST)
chk(6, "SELECT COUNT(*) AS cnt FROM daily_cache")
chk(7, LATEST)
chk(8, "SELECT * FROM daily_cache WHERE trade_date = ? ORDER BY pct_chg DESC", ["2026-09-29"])
chk(9, "SELECT ts_code, pct_chg FROM daily_cache WHERE trade_date = ?", ["2026-09-29"])
chk(10, "SELECT ts_code, close, pct_chg FROM daily_cache WHERE trade_date = ?", ["2026-09-29"])
chk(11, LATEST)
chk(12, "SELECT trade_date, COUNT(*) as cnt FROM daily_cache GROUP BY trade_date HAVING cnt >= ? ORDER BY trade_date DESC LIMIT 1", [1000])

print()
print("=== #5 信号回算分库取数（复现 _ec_fetch）===")
db = sharding_manager.get_db_for_table('daily_cache')
conn = sharding_manager.get_connection(db)
rows = conn.execute(
    "SELECT close FROM daily_cache WHERE ts_code=? AND trade_date >= ? ORDER BY trade_date LIMIT ?",
    ('600519.SH', '2026-09-01', 3)).fetchall()
print(f"  daily_cache 分库取 close 行数 = {len(rows)}（期望 ≥1，原总库=0/抛错）")
print(f"  样例: {rows[:2]}")

print()
print("=== 对照：原总库连接仍应失败（证根因）===")
try:
    ecm.read_conn.execute("SELECT 1 FROM daily_cache LIMIT 1").fetchone()
    print("  总库读 daily_cache: 意外成功")
except Exception as e:
    print(f"  总库读 daily_cache: {type(e).__name__}: {e}（符合预期）")

print()
print("ALL_CHECKS_DONE", "PASS" if all(ok) else "SOME_EMPTY")
