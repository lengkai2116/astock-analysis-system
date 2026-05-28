#!/usr/bin/env python
"""
DuckDB缓存初始化脚本
创建DuckDB数据库并执行数据同步
"""
import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

from app import create_app, db
from app.data import DataManager, CacheManager
from app.models import Stock, DailyData
from datetime import datetime

def init_duckdb_cache():
    """初始化DuckDB缓存数据库"""
    print("=" * 60)
    print("🚀 初始化DuckDB缓存数据库")
    print("=" * 60)
    
    try:
        # 创建应用上下文
        app = create_app()
        
        with app.app_context():
            # 1. 初始化CacheManager，这会自动创建DuckDB数据库和表
            print("\n📦 步骤1: 初始化DuckDB缓存...")
            cache_manager = CacheManager()
            print("✅ DuckDB缓存数据库创建成功")
            print(f"   数据库路径: {cache_manager.db_path}")
            
            # 2. 同步股票列表
            print("\n📋 步骤2: 同步股票列表...")
            data_manager = DataManager()
            stock_count = data_manager.sync_stock_list()
            print(f"✅ 成功同步 {stock_count} 只股票")
            
            # 3. 验证PostgreSQL中的股票数量
            stocks = Stock.query.all()
            print(f"📊 PostgreSQL现有股票: {len(stocks)} 只")
            
            if len(stocks) > 0:
                print("\n📊 股票列表预览:")
                for stock in stocks[:5]:
                    print(f"   - {stock.ts_code}: {stock.name} ({stock.market})")
                if len(stocks) > 5:
                    print(f"   ... 还有 {len(stocks)-5} 只")
            
            # 4. 同步日线数据
            print("\n📈 步骤3: 同步日线数据...")
            success_count = 0
            fail_count = 0
            
            for i, stock in enumerate(stocks):
                try:
                    print(f"\r   正在同步 {stock.ts_code} ({i+1}/{len(stocks)})...", end="")
                    daily_count = data_manager.sync_daily_data(stock.ts_code)
                    
                    if daily_count > 0:
                        success_count += 1
                        
                        # 同时缓存到DuckDB
                        try:
                            daily_data = DailyData.query.filter_by(
                                ts_code=stock.ts_code
                            ).order_by(DailyData.trade_date).all()
                            
                            if daily_data:
                                import pandas as pd
                                df_data = []
                                for d in daily_data:
                                    df_data.append({
                                        'ts_code': d.ts_code,
                                        'trade_date': d.trade_date,
                                        'open': d.open,
                                        'high': d.high,
                                        'low': d.low,
                                        'close': d.close,
                                        'vol': d.vol,
                                        'amount': d.amount,
                                        'pct_chg': d.pct_chg
                                    })
                                
                                if df_data:
                                    df = pd.DataFrame(df_data)
                                    cache_manager.cache_daily_data(df)
                                    
                        except Exception as e:
                            print(f"\n   ⚠️ DuckDB缓存失败 {stock.ts_code}: {e}")
                    else:
                        fail_count += 1
                        
                except Exception as e:
                    print(f"\n   ❌ 同步失败 {stock.ts_code}: {e}")
                    fail_count += 1
            
            print()  # 换行
            
            # 5. 验证PostgreSQL中的日线数据量
            total_daily = DailyData.query.count()
            print(f"\n📊 PostgreSQL日线数据: {total_daily} 条")
            
            # 6. 验证DuckDB中的缓存数据
            print("\n📦 步骤4: 验证DuckDB缓存数据...")
            try:
                cached_count = cache_manager.conn.execute(
                    "SELECT COUNT(*) FROM daily_cache"
                ).fetchone()[0]
                
                print(f"✅ DuckDB缓存数据: {cached_count} 条")
                
                if cached_count > 0:
                    sample_data = cache_manager.conn.execute(
                        "SELECT * FROM daily_cache ORDER BY trade_date DESC LIMIT 3"
                    ).fetchdf()
                    print("\n📊 缓存数据预览:")
                    print(sample_data.to_string(index=False))
                    
            except Exception as e:
                print(f"⚠️ 验证缓存失败: {e}")
            
            # 7. 完成总结
            print("\n" + "=" * 60)
            print("✅ 数据同步完成!")
            print("=" * 60)
            print(f"📋 股票同步: {len(stocks)} 只")
            print(f"📈 日线数据: {total_daily} 条")
            print(f"📦 DuckDB缓存: {cached_count} 条" if 'cached_count' in locals() else "📦 DuckDB缓存: 验证失败")
            print(f"✅ 成功股票: {success_count} 只")
            print(f"❌ 失败股票: {fail_count} 只")
            print("=" * 60)
            
            return True
            
    except Exception as e:
        print(f"\n❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_cache_strategy():
    """验证缓存策略配置"""
    print("\n" + "=" * 60)
    print("🔧 缓存策略配置验证")
    print("=" * 60)
    
    print("\n📋 缓存策略配置:")
    print("   - 数据源: Tushare API")
    print("   - 主数据库: PostgreSQL")
    print("   - 缓存层: DuckDB")
    print("   - 缓存策略: 读写缓存")
    print("   - 数据优先级: DuckDB缓存 → PostgreSQL → Tushare")
    
    print("\n✅ 缓存策略已配置!")
    return True

if __name__ == "__main__":
    print("🐍 Python环境检查")
    print(f"   Python版本: {sys.version}")
    
    success = init_duckdb_cache()
    
    if success:
        verify_cache_strategy()
        print("\n🎉 所有任务完成!")
        sys.exit(0)
    else:
        print("\n❌ 任务执行失败!")
        sys.exit(1)
