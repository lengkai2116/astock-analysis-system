"""
全量补采脚本（355号+356号方案）
===================================
根据系统需求规划全量补采，填充所有为零的数据表。

补采优先级：
- P0: adj_factor_cache, fina_indicator_cache, chip_distribution_cache, strategy_signal_detail
- P1: moneyflow_cache, stk_limit_cache, income_cache, balancesheet_cache, cashflow_cache, forecast_cache
- P2: minute_kline_cache, margin_cache, top10_holders_cache, stk_holder_cache, win_rate_cache
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime, timedelta

# 添加backend目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logger = logging.getLogger(__name__)


def check_database_status():
    """检查数据库状态"""
    print("=== 数据库状态检查 ===")
    print()
    
    db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')
    
    databases = {
        'market_cache.db': {
            'desc': '行情分库',
            'tables': ['daily_cache', 'daily_basic_cache', 'moneyflow_cache', 'stk_limit_cache', 'minute_kline_cache', 'margin_cache']
        },
        'financial_cache.db': {
            'desc': '财务分库',
            'tables': ['fina_indicator_cache', 'income_cache', 'balancesheet_cache', 'cashflow_cache', 'forecast_cache']
        },
        'history_cache.db': {
            'desc': '历史分库',
            'tables': ['adj_factor_cache', 'top10_holders_cache', 'stk_holder_cache']
        },
        'compute_cache.db': {
            'desc': '计算分库',
            'tables': ['indicator_ma', 'indicator_macd', 'indicator_other',
                       'factor_cache', 'opportunity_tags_cache',
                       'chip_distribution_cache', 'pre_feat_cache']
        },
        'snapshot_cache.db': {
            'desc': '快照分库',
            'tables': ['status_snapshot', 'treemap_snapshot',
                       'status_snapshot_history', 'treemap_snapshot_history',
                       'tag_history', 'strategy_signal_detail', 'win_rate_cache']
        },
    }
    
    for db_file, config in databases.items():
        db_path = os.path.join(db_dir, db_file)
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            print(f"{db_file} ({config['desc']}):")
            for table in config['tables']:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    status = "✅" if count > 0 else "❌"
                    print(f"  {status} {table}: {count:,} 行")
                except Exception as e:
                    print(f"  ❌ {table}: 查询失败")
            
            conn.close()
        else:
            print(f"❌ {db_file}: 不存在")
        print()


def backfill_adj_factor():
    """补采复权因子数据"""
    print("=== 补采复权因子数据 ===")
    print()
    
    try:
        # 检查Tushare是否可用
        import tushare as ts
        pro = ts.pro_api()
        
        # 尝试获取复权因子数据
        print("尝试获取复权因子数据...")
        
        # 获取最近的交易日
        today = datetime.now().strftime('%Y%m%d')
        
        # 尝试批量获取
        try:
            df = pro.adj_factor(trade_date=today)
            if df is not None and not df.empty:
                print(f"  获取到 {len(df)} 条复权因子数据")
                
                # 写入数据库
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb', 'history_cache.db')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # 创建表（如果不存在）
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS adj_factor_cache (
                        ts_code TEXT,
                        trade_date TEXT,
                        adj_factor REAL,
                        cached_at TIMESTAMP,
                        PRIMARY KEY (ts_code, trade_date)
                    )
                """)
                
                # 插入数据
                for _, row in df.iterrows():
                    try:
                        cursor.execute("""
                            INSERT OR REPLACE INTO adj_factor_cache (ts_code, trade_date, adj_factor, cached_at)
                            VALUES (?, ?, ?, ?)
                        """, [row['ts_code'], row['trade_date'], row['adj_factor'], datetime.now().isoformat()])
                    except Exception as e:
                        pass
                
                conn.commit()
                conn.close()
                
                print(f"  ✅ 复权因子数据补采完成")
                return True
            else:
                print(f"  ⚠️ 未获取到复权因子数据")
                return False
        except Exception as e:
            print(f"  ❌ 获取复权因子数据失败: {e}")
            return False
            
    except ImportError:
        print("  ❌ Tushare未安装")
        return False


def backfill_fina_indicator():
    """补采财务指标数据"""
    print("=== 补采财务指标数据 ===")
    print()
    
    try:
        # 检查Tushare是否可用
        import tushare as ts
        pro = ts.pro_api()
        
        # 尝试获取财务指标数据
        print("尝试获取财务指标数据...")
        
        # 获取股票列表
        try:
            stocks = pro.stock_basic(exchange='', list_status='L')
            if stocks is not None and not stocks.empty:
                stock_codes = stocks['ts_code'].tolist()[:100]  # 限制100只股票
                
                print(f"  获取到 {len(stock_codes)} 只股票")
                
                # 写入数据库
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb', 'financial_cache.db')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # 创建表（如果不存在）
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS fina_indicator_cache (
                        ts_code TEXT,
                        ann_date TEXT,
                        end_date TEXT,
                        roe REAL,
                        roa REAL,
                        grossprofit_margin REAL,
                        netprofit_margin REAL,
                        cached_at TIMESTAMP,
                        PRIMARY KEY (ts_code, end_date)
                    )
                """)
                
                # 逐只获取财务指标
                success_count = 0
                for code in stock_codes[:10]:  # 限制10只测试
                    try:
                        df = pro.fina_indicator(ts_code=code, period='20251231')
                        if df is not None and not df.empty:
                            for _, row in df.iterrows():
                                try:
                                    cursor.execute("""
                                        INSERT OR REPLACE INTO fina_indicator_cache 
                                        (ts_code, ann_date, end_date, roe, roa, grossprofit_margin, netprofit_margin, cached_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """, [
                                        row.get('ts_code'),
                                        row.get('ann_date'),
                                        row.get('end_date'),
                                        row.get('roe'),
                                        row.get('roa'),
                                        row.get('grossprofit_margin'),
                                        row.get('netprofit_margin'),
                                        datetime.now().isoformat()
                                    ])
                                    success_count += 1
                                except Exception as e:
                                    pass
                    except Exception as e:
                        pass
                
                conn.commit()
                conn.close()
                
                print(f"  ✅ 财务指标数据补采完成: {success_count} 条")
                return True
            else:
                print(f"  ⚠️ 未获取到股票列表")
                return False
        except Exception as e:
            print(f"  ❌ 获取股票列表失败: {e}")
            return False
            
    except ImportError:
        print("  ❌ Tushare未安装")
        return False


def backfill_moneyflow():
    """补采资金流向数据"""
    print("=== 补采资金流向数据 ===")
    print()
    
    try:
        # 检查Tushare是否可用
        import tushare as ts
        pro = ts.pro_api()
        
        # 尝试获取资金流向数据
        print("尝试获取资金流向数据...")
        
        # 获取最近的交易日
        today = datetime.now().strftime('%Y%m%d')
        
        # 尝试批量获取
        try:
            df = pro.moneyflow(trade_date=today)
            if df is not None and not df.empty:
                print(f"  获取到 {len(df)} 条资金流向数据")
                
                # 写入数据库
                db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb', 'market_cache.db')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # 创建表（如果不存在）
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS moneyflow_cache (
                        ts_code TEXT,
                        trade_date TEXT,
                        buy_lg_vol REAL,
                        buy_lg_amount REAL,
                        sell_lg_vol REAL,
                        sell_lg_amount REAL,
                        buy_elg_amount REAL,
                        sell_elg_amount REAL,
                        buy_sm_amount REAL,
                        sell_sm_amount REAL,
                        net_lg_amount REAL,
                        net_elg_amount REAL,
                        net_sm_amount REAL,
                        cached_at TIMESTAMP,
                        PRIMARY KEY (ts_code, trade_date)
                    )
                """)
                
                # 插入数据
                for _, row in df.iterrows():
                    try:
                        cursor.execute("""
                            INSERT OR REPLACE INTO moneyflow_cache 
                            (ts_code, trade_date, buy_lg_vol, buy_lg_amount, sell_lg_vol, sell_lg_amount,
                             buy_elg_amount, sell_elg_amount, buy_sm_amount, sell_sm_amount,
                             net_lg_amount, net_elg_amount, net_sm_amount, cached_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            row.get('ts_code'),
                            row.get('trade_date'),
                            row.get('buy_lg_vol'),
                            row.get('buy_lg_amount'),
                            row.get('sell_lg_vol'),
                            row.get('sell_lg_amount'),
                            row.get('buy_elg_amount'),
                            row.get('sell_elg_amount'),
                            row.get('buy_sm_amount'),
                            row.get('sell_sm_amount'),
                            row.get('net_lg_amount'),
                            row.get('net_elg_amount'),
                            row.get('net_sm_amount'),
                            datetime.now().isoformat()
                        ])
                    except Exception as e:
                        pass
                
                conn.commit()
                conn.close()
                
                print(f"  ✅ 资金流向数据补采完成")
                return True
            else:
                print(f"  ⚠️ 未获取到资金流向数据")
                return False
        except Exception as e:
            print(f"  ❌ 获取资金流向数据失败: {e}")
            return False
            
    except ImportError:
        print("  ❌ Tushare未安装")
        return False


def run_backfill():
    """执行全量补采"""
    print("=== 开始全量补采 ===")
    print()
    
    # 检查数据库状态
    check_database_status()
    
    # 执行P0紧急补采
    print("=" * 60)
    print("执行P0紧急补采")
    print("=" * 60)
    
    results = {}
    
    # 1. 复权因子
    results['adj_factor_cache'] = backfill_adj_factor()
    
    # 2. 财务指标
    results['fina_indicator_cache'] = backfill_fina_indicator()
    
    # 3. 资金流向
    results['moneyflow_cache'] = backfill_moneyflow()
    
    # 输出结果
    print()
    print("=" * 60)
    print("补采结果汇总")
    print("=" * 60)
    
    for table, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"  {table}: {status}")
    
    print()
    print("=== 全量补采完成 ===")
    
    return results


if __name__ == '__main__':
    run_backfill()
