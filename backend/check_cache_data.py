#!/usr/bin/env python3
"""
查看DuckDB缓存中的数据
"""
import duckdb
import os

db_path = '/Users/kalence/Desktop/测试/01-A股股票分析系统/data/duckdb/stock_cache.db'

print("="*70)
print("查看DuckDB缓存数据")
print("="*70)
print(f"数据库路径:", db_path)

try:
    conn = duckdb.connect(db_path)
    
    # 1. 查看有哪些股票
    print("\n1. 查询股票数量及数据量:")
    stocks = conn.execute("""
        SELECT ts_code, COUNT(*) as cnt, MIN(trade_date), MAX(trade_date) 
        FROM daily_cache 
        GROUP BY ts_code 
        ORDER BY cnt DESC
    """).fetchdf()
    print(stocks.head(20))
    
    print(f"\n总股票总数: {len(stocks)}")
    
    # 2. 查看一只股票的数据示例
    if len(stocks) > 0:
        sample_ts_code = stocks.iloc[0]['ts_code']
        print(f"\n2. 示例股票: {sample_ts_code} 的数据:")
        sample_data = conn.execute(f"""
            SELECT * FROM daily_cache WHERE ts_code = '{sample_ts_code}' ORDER BY trade_date
        """).fetchdf()
        print(f"数据量: {len(sample_data)}")
        print("\n前10条:")
        print(sample_data.head(10))
    
    conn.close()
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
