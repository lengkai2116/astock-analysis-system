"""
数据同步脚本
- 同步股票列表
- 同步日线数据
- 计算技术指标
- 生成信号
"""
import sys
import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from app import create_app, db
from app.models import Stock, DailyData
from app.data import DataManager
from app.indicators import TechnicalIndicatorEngine
from app.signals import SignalGenerator


def sync_stocks():
    """同步股票列表"""
    print("=== 同步股票列表 ===")
    
    data_manager = DataManager()
    
    try:
        stocks = data_manager.get_stock_list()
        
        if not stocks:
            print("获取股票列表失败")
            return False
        
        saved_count = 0
        for stock_data in stocks:
            existing = Stock.query.filter_by(ts_code=stock_data['ts_code']).first()
            
            if not existing:
                stock = Stock(
                    ts_code=stock_data['ts_code'],
                    symbol=stock_data.get('symbol'),
                    name=stock_data.get('name'),
                    industry=stock_data.get('industry'),
                    market=stock_data.get('market')
                )
                db.session.add(stock)
                saved_count += 1
            else:
                existing.name = stock_data.get('name', existing.name)
                existing.industry = stock_data.get('industry', existing.industry)
        
        db.session.commit()
        print(f"成功保存 {saved_count} 只新股票")
        return True
        
    except Exception as e:
        print(f"同步股票列表失败: {str(e)}")
        db.session.rollback()
        return False


def sync_daily_data(ts_code: str, start_date: str = None, end_date: str = None):
    """同步单只股票的日线数据"""
    print(f"=== 同步 {ts_code} 日线数据 ===")
    
    if not end_date:
        end_date = date.today().strftime('%Y%m%d')
    
    if not start_date:
        start_date = (date.today() - timedelta(days=365)).strftime('%Y%m%d')
    
    data_manager = DataManager()
    
    try:
        daily_data = data_manager.get_daily_data(ts_code, start_date, end_date)
        
        if daily_data.empty:
            print(f"未获取到 {ts_code} 的数据")
            return False
        
        saved_count = 0
        for idx, row in daily_data.iterrows():
            existing = DailyData.query.filter_by(
                ts_code=ts_code,
                trade_date=row['trade_date']
            ).first()
            
            if not existing:
                dd = DailyData(
                    ts_code=ts_code,
                    trade_date=row['trade_date'],
                    open=row.get('open'),
                    high=row.get('high'),
                    low=row.get('low'),
                    close=row.get('close'),
                    vol=row.get('vol'),
                    amount=row.get('amount'),
                    pct_chg=row.get('pct_chg')
                )
                db.session.add(dd)
                saved_count += 1
        
        db.session.commit()
        print(f"成功保存 {saved_count} 条日线数据")
        return True
        
    except Exception as e:
        print(f"同步日线数据失败: {str(e)}")
        db.session.rollback()
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