#!/usr/bin/env python3
"""手动触发日终数据同步 — 从 DB 最新交易日增量同步到当日"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.scheduler_manager import scheduler_manager

app = create_app()
with app.app_context():
    print("=== 开始日终同步 ===")
    t0 = time.time()
    result = scheduler_manager.run_daily_sync()
    elapsed = time.time() - t0
    print(f"状态: {result['status']}")
    print(f"新增记录: {result.get('records_added', 0)}")
    for dt in result.get('data_types', []):
        print(f"  {dt['type']}: {dt['count']} 条")
    print(f"耗时: {elapsed:.1f}s")
    if result.get('error_message'):
        print(f"错误: {result['error_message']}")
    print("=== 同步完成 ===")
