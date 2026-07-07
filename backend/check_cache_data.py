#!/usr/bin/env python3
"""
查看 SQLite 缓存中的数据（250号方案）
用法: python check_cache_data.py
"""
import sqlite3
import os
import pandas as pd

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'duckdb', 'stock_cache.db')

print("=" * 70)
print("查看 SQLite 缓存数据")
print("=" * 70)
print(f"数据库路径: {db_path}")

if not os.path.exists(db_path):
    print(f"文件不存在，请先运行系统以创建缓存")
    exit(1)

try:
    conn = sqlite3.connect(db_path)

    print("\n1. 查询股票数量及数据量:")
    stocks = pd.read_sql("""
        SELECT ts_code, COUNT(*) as cnt, MIN(trade_date) as first, MAX(trade_date) as latest
        FROM daily_cache GROUP BY ts_code ORDER BY cnt DESC
    """, conn)
    print(stocks.head(20))
    print(f"\n总股票总数: {len(stocks)}")

    if len(stocks) > 0:
        sample = stocks.iloc[0]['ts_code']
        print(f"\n2. 示例股票: {sample} 的数据:")
        data = pd.read_sql(
            "SELECT * FROM daily_cache WHERE ts_code = ? ORDER BY trade_date",
            conn, params=[sample]
        )
        print(f"数据量: {len(data)}")
        print(data.head(10))

    for table in ['daily_cache', 'daily_basic_cache', 'moneyflow_cache']:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"\n  {table}: {cnt:,} 行")

    conn.close()

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
