#!/usr/bin/env python
"""
定时任务脚本
用于自动化数据同步和缓存管理
"""
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
import schedule

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

from app import create_app, db
from app.data import DataManager
from app.models import Stock, DailyData

class ScheduledTasks:
    """定时任务管理器"""
    
    def __init__(self):
        self.app = create_app()
        self.data_manager = None
    
    def _init_data_manager(self):
        """初始化数据管理器"""
        if not self.data_manager:
            self.data_manager = DataManager()
    
    def sync_latest_data(self):
        """同步最新数据（每日收盘后）"""
        print(f"\n{'='*60}")
        print(f"📅 同步最新数据 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        with self.app.app_context():
            self._init_data_manager()
            
            try:
                # 同步股票列表
                stock_count = self.data_manager.sync_stock_list()
                print(f"✅ 股票列表: {stock_count} 只")
                
                # 同步最近的数据
                end_date = datetime.now().strftime('%Y%m%d')
                start_date = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')
                
                stocks = Stock.query.limit(100).all()  # 只同步100只活跃股票
                total_count = 0
                
                for stock in stocks:
                    try:
                        count = self.data_manager.sync_daily_data(
                            stock.ts_code, 
                            start_date=start_date,
                            end_date=end_date
                        )
                        total_count += count
                    except Exception as e:
                        print(f"⚠️ 同步失败 {stock.ts_code}: {e}")
                
                print(f"✅ 同步完成: {total_count} 条新数据")
                
                # 清除旧缓存
                self.data_manager.cache.invalidate_old_data(days=30)
                print(f"✅ 清理旧缓存完成")
                
            except Exception as e:
                print(f"❌ 同步失败: {e}")
                import traceback
                traceback.print_exc()
    
    def warmup_cache(self):
        """缓存预热"""
        print(f"\n{'='*60}")
        print(f"🔥 缓存预热 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        with self.app.app_context():
            self._init_data_manager()
            self.data_manager.preload_cache()
    
    def full_sync(self):
        """全量同步（每周）"""
        print(f"\n{'='*60}")
        print(f"🚀 全量数据同步 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        with self.app.app_context():
            self._init_data_manager()
            
            try:
                stocks = Stock.query.all()
                success_count = 0
                total_daily = 0
                
                for idx, stock in enumerate(stocks, 1):
                    try:
                        daily_count = self.data_manager.sync_daily_data(stock.ts_code, use_cache=False)
                        total_daily += daily_count
                        if daily_count > 0:
                            success_count += 1
                        
                        if idx % 50 == 0:
                            print(f"📊 进度: {idx}/{len(stocks)}, 已同步: {total_daily} 条")
                        
                        # 限制频率
                        if idx % 10 == 0:
                            time.sleep(0.5)
                        
                    except Exception as e:
                        print(f"⚠️ 同步失败 {stock.ts_code}: {e}")
                
                print(f"✅ 全量同步完成: {success_count} 只, {total_daily} 条数据")
                
            except Exception as e:
                print(f"❌ 全量同步失败: {e}")
    
    def clear_old_cache(self):
        """清理老缓存"""
        print(f"\n{'='*60}")
        print(f"🧹 清理旧缓存 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        with self.app.app_context():
            self._init_data_manager()
            self.data_manager.cache.invalidate_old_data(days=30)
            print("✅ 旧缓存清理完成")

def run_scheduler():
    """运行调度器"""
    tasks = ScheduledTasks()
    
    # 设置定时任务
    # 每日17:00同步最新数据
    schedule.every().day.at("17:00").do(tasks.sync_latest_data)
    
    # 每日02:00缓存预热
    schedule.every().day.at("02:00").do(tasks.warmup_cache)
    
    # 每周日03:00全量同步
    schedule.every().sunday.at("03:00").do(tasks.full_sync)
    
    # 每周清理旧缓存
    schedule.every().monday.at("04:00").do(tasks.clear_old_cache)
    
    print("⏰ 定时任务已启动")
    print("📋 任务列表:")
    print("   • 每日17:00: 同步最新数据")
    print("   • 每日02:00: 缓存预热")
    print("   • 每周日03:00: 全量同步")
    print("   • 每周一04:00: 清理旧缓存")
    print("\n⏳ 等待定时任务...")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n🛑 定时任务已停止")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='定时任务管理')
    parser.add_argument('--run-now', action='store_true',
                       help='立即运行一次同步任务')
    parser.add_argument('--warmup', action='store_true',
                       help='立即运行缓存预热')
    parser.add_argument('--full', action='store_true',
                       help='立即运行全量同步')
    parser.add_argument('--scheduler', action='store_true',
                       help='启动定时任务调度器')
    
    args = parser.parse_args()
    
    if args.scheduler:
        run_scheduler()
    elif args.warmup:
        tasks = ScheduledTasks()
        tasks.warmup_cache()
    elif args.full:
        tasks = ScheduledTasks()
        tasks.full_sync()
    elif args.run_now:
        tasks = ScheduledTasks()
        tasks.sync_latest_data()
    else:
        print("请指定操作:")
        print("  --scheduler    启动定时任务")
        print("  --run-now      立即同步最新数据")
        print("  --warmup       立即缓存预热")
        print("  --full         立即全量同步")
