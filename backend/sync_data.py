"""
数据同步脚本（244号方案：改写入 DuckDB）
- 同步股票列表
- 同步日线数据到 DuckDB
- 计算技术指标
- 生成信号
"""
import sys
import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from app import create_app
from app.data import DataManager
from app.indicators import TechnicalIndicatorEngine
from app.signals import SignalGenerator


def sync_stocks():
    """同步股票列表（委托 DataManager）"""
    print("=== 同步股票列表 ===")
    data_manager = DataManager()
    try:
        count = data_manager.sync_stock_list()
        print(f"成功同步 {count} 只股票")
        return True
    except Exception as e:
        print(f"同步股票列表失败: {str(e)}")
        return False


def sync_daily_data(ts_code: str, start_date: str = None, end_date: str = None):
    """同步单只股票的日线数据到 DuckDB（244号方案：写入 DuckDB daily_cache）"""
    print(f"=== 同步 {ts_code} 日线数据 ===")
    if not end_date:
        end_date = date.today().strftime('%Y%m%d')
    if not start_date:
        start_date = (date.today() - timedelta(days=365)).strftime('%Y%m%d')

    data_manager = DataManager()
    try:
        count = data_manager.sync_daily_data(ts_code, use_cache=False,
                                             start_date=start_date, end_date=end_date)
        if count > 0:
            print(f"成功同步 {count} 条日线数据到 DuckDB")
            return True
        else:
            print(f"未获取到 {ts_code} 的新数据")
            return False
    except Exception as e:
        print(f"同步日线数据失败: {str(e)}")
        return False


def sync_multiple_stocks(ts_codes: list, start_date: str = None):
    """同步多只股票数据"""
    print(f"=== 同步 {len(ts_codes)} 只股票 ===")
    success_count = 0
    for ts_code in ts_codes:
        if sync_daily_data(ts_code, start_date):
            success_count += 1
    print(f"成功同步 {success_count}/{len(ts_codes)} 只股票")


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        print("=" * 50)
        print("A股股票分析系统 - 数据同步工具")
        print("=" * 50)
        sync_stocks()
        print("\n获取热门股票进行同步...")
        hot_stocks = [
            '000001.SZ', '600519.SH', '000858.SZ', '002594.SZ', '002475.SZ',
            '601318.SH', '601888.SH', '002415.SZ', '000568.SZ', '600809.SH',
            '002812.SZ', '000333.SZ', '600036.SH', '002475.SZ', '000338.SZ'
        ]
        sync_multiple_stocks(hot_stocks, '20240101')
        print("\n数据同步完成！")
