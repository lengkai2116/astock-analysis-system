from .tushare_provider import TushareProvider
from .enhanced_cache_manager import EnhancedCacheManager
from app.models import Stock, DailyData
from app import db
from datetime import datetime
import pandas as pd
from sqlalchemy import or_


import logging
logger = logging.getLogger(__name__)
class DataManager:
    def __init__(self):
        self.tushare = TushareProvider()
        self.cache = EnhancedCacheManager()
    
    def sync_stock_list(self):
        stocks = self.tushare.get_stock_list()
        
        if not stocks:
            return 0
        
        for stock in stocks:
            existing = Stock.query.get(stock['ts_code'])
            list_date = stock.get('list_date')
            
            if existing:
                existing.symbol = stock['symbol']
                existing.name = stock['name']
                existing.industry = stock.get('industry')
                existing.market = stock.get('market')
                if list_date:
                    existing.list_date = datetime.strptime(list_date, '%Y%m%d').date()
            else:
                new_stock = Stock(
                    ts_code=stock['ts_code'],
                    symbol=stock['symbol'],
                    name=stock['name'],
                    industry=stock.get('industry'),
                    market=stock.get('market'),
                    list_date=datetime.strptime(list_date, '%Y%m%d').date() if list_date else None
                )
                db.session.add(new_stock)
        
        db.session.commit()
        return len(stocks)
    
    def sync_daily_data(self, ts_code, use_cache=True, start_date=None, end_date=None):
        """同步日线数据，优先使用缓存"""
        # 先尝试从缓存获取
        if use_cache:
            cached_df = self.cache.get_cached_daily(ts_code, start_date, end_date)
            if not cached_df.empty:
                logger.info(r"使用缓存数据: {ts_code}")
                self._sync_cached_to_postgres(ts_code, cached_df)
                return len(cached_df)
        
        # 缓存未命中，从Tushare获取
        data = self.tushare.get_daily_data(ts_code, start_date, end_date)
        
        if not data:
            return 0
        
        # 转换为DataFrame
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'vol': item.get('vol'),
                'amount': item.get('amount'),
                'pct_chg': item.get('pct_chg')
            })
        
        if df_data:
            df = pd.DataFrame(df_data)
            # 缓存到增强缓存系统
            self.cache.cache_daily_data(df)
            # 同步到PostgreSQL
            self._sync_cached_to_postgres(ts_code, df)
            return len(df)
        
        return 0
    
    def _sync_cached_to_postgres(self, ts_code, df):
        """将缓存数据同步到PostgreSQL"""
        for _, row in df.iterrows():
            existing = DailyData.query.filter_by(
                ts_code=row['ts_code'],
                trade_date=row['trade_date']
            ).first()
            
            if not existing:
                daily = DailyData(
                    ts_code=row['ts_code'],
                    trade_date=row['trade_date'],
                    open=row.get('open'),
                    high=row.get('high'),
                    low=row.get('low'),
                    close=row.get('close'),
                    vol=row.get('vol'),
                    amount=row.get('amount'),
                    pct_chg=row.get('pct_chg')
                )
                db.session.add(daily)
        
        db.session.commit()
    
    def sync_all_daily_data(self):
        stocks = Stock.query.all()
        count = 0
        
        for stock in stocks:
            count += self.sync_daily_data(stock.ts_code)
        
        return count
    
    def get_cached_daily_data(self, ts_code, start_date=None, end_date=None):
        """从缓存获取日线数据"""
        cached_df = self.cache.get_cached_daily(ts_code, start_date, end_date)
        
        # 如果缓存为空，尝试从PostgreSQL获取并缓存
        if cached_df.empty:
            from app.models import DailyData
            query = DailyData.query.filter_by(ts_code=ts_code)
            
            if start_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d').date()
                    query = query.filter(DailyData.trade_date >= start)
                except:
                    pass
            if end_date:
                try:
                    end = datetime.strptime(end_date, '%Y-%m-%d').date()
                    query = query.filter(DailyData.trade_date <= end)
                except:
                    pass
            
            daily_data = query.order_by(DailyData.trade_date).all()
            
            if daily_data:
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
                cached_df = pd.DataFrame(df_data)
                self.cache.cache_daily_data(cached_df)
        
        return cached_df
    
    def preload_cache(self):
        """预加载缓存"""
        logger.info(r"开始缓存预热")
        from app.models import DailyData
        
        # 获取有数据的股票列表
        from sqlalchemy import func
        stock_counts = db.session.query(
            DailyData.ts_code,
            func.count(DailyData.ts_code).label('count')
        ).group_by(DailyData.ts_code).all()
        
        count = 0
        for ts_code, _ in stock_counts:
            self.get_cached_daily_data(ts_code)
            count += 1
            if count % 50 == 0:
                logger.info(r"已预热 {count} 只股票")
        
        logger.info(r"缓存预热完成: {count} 只股票")
    
    def get_cache_stats(self):
        """获取缓存统计信息"""
        return self.cache.get_cache_stats()
    
    def get_stock_info(self, ts_code):
        """获取单只股票信息"""
        stock = Stock.query.get(ts_code)
        return stock.to_dict() if stock else None
    
    def get_stock_list(self, keyword=None, limit=50):
        """获取股票列表，支持按代码/名称搜索"""
        query = Stock.query.order_by(Stock.ts_code)
        if keyword:
            query = query.filter(
                or_(
                    Stock.ts_code.ilike(f'%{keyword}%'),
                    Stock.name.ilike(f'%{keyword}%')
                )
            )
        stocks = query.limit(limit).all()
        return [s.to_dict() for s in stocks]
    
    def get_kline_data(self, ts_code, period='D', start_date=None, end_date=None):
        """
        获取K线数据
        period: D(日线)/W(周线)/M(月线)/1m/5m/15m/30m/60m
        """
        if period == 'D':
            return self.get_cached_daily_data(ts_code, start_date, end_date)
        elif period == 'W':
            return self._get_weekly_data(ts_code, start_date, end_date)
        elif period == 'M':
            return self._get_monthly_data(ts_code, start_date, end_date)
        elif period in ['1m', '5m', '15m', '30m', '60m']:
            return self._get_minute_data(ts_code, period, start_date, end_date)
        else:
            return self.get_cached_daily_data(ts_code, start_date, end_date)
    
    def _get_weekly_data(self, ts_code, start_date=None, end_date=None):
        """获取周线数据，优先从本地日线聚合"""
        # 优先使用本地日线聚合，确保数据新鲜
        daily_data = self.get_cached_daily_data(ts_code, start_date, end_date)
        if not daily_data.empty:
            return self._aggregate_daily_to_weekly(daily_data)
        
        # 日线数据不存在时才从Tushare获取
        data = self.tushare.get_weekly_data(ts_code, start_date, end_date)
        if not data:
            return pd.DataFrame()
        
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'vol': item.get('vol'),
                'amount': item.get('amount'),
                'pct_chg': item.get('pct_chg')
            })
        df = pd.DataFrame(df_data) if df_data else pd.DataFrame()
        if not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
        return df
    
    def _get_monthly_data(self, ts_code, start_date=None, end_date=None):
        """获取月线数据，优先从本地日线聚合"""
        # 优先使用本地日线聚合，确保数据新鲜
        daily_data = self.get_cached_daily_data(ts_code, start_date, end_date)
        if not daily_data.empty:
            return self._aggregate_daily_to_monthly(daily_data)
        
        # 日线数据不存在时才从Tushare获取
        data = self.tushare.get_monthly_data(ts_code, start_date, end_date)
        if not data:
            return pd.DataFrame()
        
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'vol': item.get('vol'),
                'amount': item.get('amount'),
                'pct_chg': item.get('pct_chg')
            })
        df = pd.DataFrame(df_data) if df_data else pd.DataFrame()
        if not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
        return df
    
    def _get_minute_data(self, ts_code, freq, start_date=None, end_date=None):
        """获取分钟线数据"""
        data = self.tushare.get_minute_data(ts_code, freq, start_date, end_date)
        if not data:
            return pd.DataFrame()
        
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d%H%M%S') if len(trade_date_str) > 8 else datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'vol': item.get('vol'),
                'amount': item.get('amount')
            })
        return pd.DataFrame(df_data) if df_data else pd.DataFrame()
    
    def _aggregate_daily_to_weekly(self, daily_df):
        """将日线数据聚合为周线数据"""
        if daily_df.empty:
            return pd.DataFrame()
        
        df = daily_df.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        
        # 按周聚合
        weekly = df.resample('W-FRI').agg({
            'ts_code': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'vol': 'sum',
            'amount': 'sum'
        }).dropna()
        
        weekly.reset_index(inplace=True)
        weekly['pct_chg'] = weekly['close'].pct_change() * 100
        return weekly
    
    def _aggregate_daily_to_monthly(self, daily_df):
        """将日线数据聚合为月线数据"""
        if daily_df.empty:
            return pd.DataFrame()
        
        df = daily_df.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        
        # 按月聚合
        monthly = df.resample('M').agg({
            'ts_code': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'vol': 'sum',
            'amount': 'sum'
        }).dropna()
        
        monthly.reset_index(inplace=True)
        monthly['pct_chg'] = monthly['close'].pct_change() * 100
        return monthly
    
    def sync_daily_basic_data(self, ts_code=None, start_date=None, end_date=None):
        """
        同步每日基础数据（换手率、市盈率、市值等）
        
        Args:
            ts_code: 股票代码（如果None则获取当日全部）
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            同步的数据条数
        """
        data = self.tushare.get_daily_basic(ts_code, start_date, end_date)
        
        if not data:
            return 0
        
        # 转换为DataFrame并缓存
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'close': item.get('close'),
                'turnover_rate': item.get('turnover_rate'),
                'turnover_rate_f': item.get('turnover_rate_f'),
                'volume_ratio': item.get('volume_ratio'),
                'pe': item.get('pe'),
                'pe_ttm': item.get('pe_ttm'),
                'pb': item.get('pb'),
                'ps': item.get('ps'),
                'ps_ttm': item.get('ps_ttm'),
                'dv_ratio': item.get('dv_ratio'),
                'dv_ttm': item.get('dv_ttm'),
                'total_share': item.get('total_share'),
                'float_share': item.get('float_share'),
                'free_share': item.get('free_share'),
                'total_mv': item.get('total_mv'),
                'circ_mv': item.get('circ_mv')
            })
        
        if df_data:
            df = pd.DataFrame(df_data)
            self.cache.cache_daily_basic_data(df)
            return len(df)
        
        return 0
    
    def get_cached_daily_basic(self, ts_code, start_date=None, end_date=None):
        """
        从缓存获取每日基础数据
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame
        """
        return self.cache.get_cached_daily_basic(ts_code, start_date, end_date)
    
    def sync_all_daily_basic_data(self, trade_date=None):
        """同步全部股票每日基础数据"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        
        return self.sync_daily_basic_data(trade_date=trade_date)
