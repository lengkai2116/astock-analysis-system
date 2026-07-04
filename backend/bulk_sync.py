#!/usr/bin/env python
"""
批量数据同步脚本（244号方案：写入 DuckDB，不走 PG DailyData）
支持进度显示和性能统计
"""
import sys
import os
from pathlib import Path
import time
import random
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

from app import create_app
from app.data import DataManager, get_ecm_instance
from app.models import Stock

def bulk_sync_with_progress(limit=None, shuffle=True, skip_existing=True):
    """
    批量同步股票数据（244号方案：写入 DuckDB daily_cache）

    Args:
        limit: 最多同步多少只股票，None表示全部
        shuffle: 是否随机打乱顺序
        skip_existing: 是否跳过已有数据的股票（从 DuckDB 检测）
    """
    print("="*80)
    print("🚀 开始批量数据同步")
    print("="*80)

    app = create_app()

    with app.app_context():
        data_manager = DataManager()
        ecm = get_ecm_instance()

        # 获取所有股票
        stocks = Stock.query.all()

        if not stocks:
            print("❌ 没有找到股票数据")
            return

        print(f"📊 总共有 {len(stocks)} 只股票")

        if shuffle:
            random.shuffle(stocks)
            print("🔀 已随机打乱股票顺序")

        if limit:
            stocks = stocks[:limit]
            print(f"📋 限制同步前 {limit} 只股票")

        success_count = 0
        fail_count = 0
        skip_count = 0
        total_daily_count = 0
        start_time = time.time()

        print("="*80)
        print(f"{'序号':<6} {'股票代码':<12} {'股票名称':<10} {'数据量':<8} {'状态':<8}")
        print("-"*80)

        for idx, stock in enumerate(stocks, 1):
            try:
                # 检查 DuckDB 是否已有数据（244号方案：取代 PG DailyData 检查）
                if skip_existing:
                    count_df = ecm.conn.execute(
                        "SELECT COUNT(*) AS cnt FROM daily_cache WHERE ts_code = ?",
                        [stock.ts_code]
                    ).fetchdf()
                    existing_count = int(count_df['cnt'].iloc[0]) if not count_df.empty else 0
                    if existing_count > 100:  # 已有超过100天数据就跳过
                        print(f"{idx:<6} {stock.ts_code:<12} {stock.name:<10} {'已存在':<8} ⏭️ 跳过")
                        skip_count += 1
                        continue

                # 同步数据（写入 DuckDB）
                stock_start = time.time()
                daily_count = data_manager.sync_daily_data(stock.ts_code, use_cache=False)
                stock_elapsed = time.time() - stock_start

                if daily_count > 0:
                    status = "✅ 成功"
                    success_count += 1
                    total_daily_count += daily_count
                else:
                    status = "⚠️ 无数据"
                    fail_count += 1

                print(f"{idx:<6} {stock.ts_code:<12} {stock.name:<10} {daily_count:<8} {status} ({stock_elapsed:.2f}s)")

                # 每10只股票显示一次统计
                if idx % 10 == 0:
                    elapsed = time.time() - start_time
                    avg_speed = total_daily_count / elapsed if elapsed > 0 else 0
                    print(f"\n📈 当前进度: {idx}/{len(stocks)}, 平均速度: {avg_speed:.1f}条/秒\n")

                # 稍微延迟，避免API限流
                if idx % 5 == 0:
                    time.sleep(0.5)

            except Exception as e:
                print(f"{idx:<6} {stock.ts_code:<12} {stock.name:<10} {'N/A':<8} ❌ 失败: {str(e)[:30]}")
                fail_count += 1
                import traceback
                traceback.print_exc()

        elapsed = time.time() - start_time

        print("="*80)
        print("📊 同步完成统计")
        print("="*80)
        print(f"✅ 成功: {success_count} 只")
        print(f"⚠️ 无数据: {fail_count} 只")
        print(f"⏭️ 跳过: {skip_count} 只")
        print(f"📈 总日线数据: {total_daily_count} 条")
        print(f"⏱️ 总耗时: {elapsed:.2f} 秒")
        print(f"🚀 平均速度: {total_daily_count / elapsed:.1f} 条/秒")
        print("="*80)

        # 获取缓存统计（244号方案：DuckDB 缓存统计）
        print("\n📦 DuckDB 缓存统计:")
        stats = data_manager.get_cache_stats()
        if stats is not None:
            print(stats.to_string(index=False) if hasattr(stats, 'to_string') else stats)


def warmup_cache():
    """
    缓存预热：遍历股票列表，触发 DataManager 从 DuckDB 加载到内存缓存
    （244号方案：从 DuckDB daily_cache 读取，不走 PG DailyData）
    """
    print("="*80)
    print("🔥 开始缓存预热")
    print("="*80)

    app = create_app()

    with app.app_context():
        data_manager = DataManager()
        stocks = Stock.query.all()

        print(f"📊 找到 {len(stocks)} 只股票")

        cached_count = 0
        start_time = time.time()

        for idx, stock in enumerate(stocks, 1):
            try:
                cached_df = data_manager.get_cached_daily_data(stock.ts_code)
                if not cached_df.empty:
                    cached_count += 1
                    print(f"\r🔥 预热 {idx}/{len(stocks)}: {stock.ts_code} ({len(cached_df)}条)", end="")

                    if idx % 50 == 0:
                        print()
            except Exception as e:
                print(f"\n❌ 预热失败 {stock.ts_code}: {e}")

        elapsed = time.time() - start_time
        print("\n" + "="*80)
        print(f"✅ 缓存预热完成")
        print(f"🔥 预热股票: {cached_count} 只")
        print(f"⏱️ 耗时: {elapsed:.2f} 秒")
        print("="*80)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='批量数据同步工具')
    parser.add_argument('--limit', type=int, default=None,
                       help='最多同步多少只股票')
    parser.add_argument('--skip-existing', action='store_true',
                       help='跳过已有数据的股票')
    parser.add_argument('--warmup', action='store_true',
                       help='只进行缓存预热，不同步新数据')
    parser.add_argument('--shuffle', action='store_true',
                       help='随机打乱股票顺序')

    args = parser.parse_args()

    if args.warmup:
        warmup_cache()
    else:
        bulk_sync_with_progress(
            limit=args.limit,
            shuffle=args.shuffle,
            skip_existing=args.skip_existing
        )
