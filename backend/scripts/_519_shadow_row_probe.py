"""519号探针：strategy_signal_detail 骨架行（影子行）报告 / 清理。

影子行＝**骨架日**当天、`dim_results_json` 与 `seven_dim_json` 均为 NULL 的骨架行
（单只预计算 `precompute_strategy` 先写 SIG 列、JUD 未跑时产生）；它会顶掉
`MAX(trade_date)`，使按「最新日 ∧ json 非空」取数的消费方（test_495_b2 / 门禁 /
health 等）误判无数据。

**骨架日判据（保守）：当日行数 < 100 且当天无任何 dim_results_json 非空行** ——
即「显然未跑过全市场 SIG/JUD」的极小日。以此避免误删全量日中个别计算失败的合法行。

用法：
  python scripts/_519_shadow_row_probe.py           # 只读报告（默认）
  python scripts/_519_shadow_row_probe.py --clean   # 删除骨架日影子行（写库）
"""
import argparse
import os
import sqlite3

DATA = os.environ.get('DATA_DIR') or '/Users/kalence/Desktop/01-A股股票分析系统/data'
DB = os.path.join(DATA, 'duckdb', 'snapshot_cache.db')

_SUM_SQL = (
    "SELECT trade_date, COUNT(*), "
    "SUM(CASE WHEN dim_results_json IS NOT NULL THEN 1 ELSE 0 END) "
    "FROM strategy_signal_detail GROUP BY trade_date "
    "ORDER BY trade_date DESC LIMIT 5"
)

_SKELETON_DAY_SUBQ = (
    "SELECT trade_date FROM strategy_signal_detail GROUP BY trade_date "
    "HAVING COUNT(*) < 100 "
    "AND SUM(CASE WHEN dim_results_json IS NOT NULL THEN 1 ELSE 0 END) = 0"
)

_SHADOW_SQL = (
    "SELECT ts_code, trade_date, cached_at FROM strategy_signal_detail "
    "WHERE dim_results_json IS NULL AND seven_dim_json IS NULL "
    "AND trade_date IN (" + _SKELETON_DAY_SUBQ + ")"
)

_DELETE_SQL = _SHADOW_SQL.replace(
    "SELECT ts_code, trade_date, cached_at FROM", "DELETE FROM")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clean', action='store_true',
                    help='删除骨架日影子行（当日行数<100 且全无 JUD 产物）')
    args = ap.parse_args()

    conn = sqlite3.connect(DB, timeout=30)
    print(f"DB: {DB}")
    print("--- 近 5 日按 trade_date 汇总（rows / json 非空） ---")
    for td, n, nn in conn.execute(_SUM_SQL):
        print(f"   {td}  rows={n}  json_nonnull={nn}")

    rows = conn.execute(_SHADOW_SQL).fetchall()
    print(f"--- 骨架日影子行（两 json 均 NULL）: {len(rows)} 条 ---")
    for ts, td, ca in rows[:20]:
        print(f"   {ts}  {td}  cached_at={ca}")

    if args.clean:
        if not rows:
            print("无骨架日影子行，无需清理")
        else:
            cur = conn.execute(_DELETE_SQL)
            conn.commit()
            print(f"已删除影子行: {cur.rowcount} 条")
    conn.close()


if __name__ == '__main__':
    main()
