from .tushare_provider import TushareProvider
from .enhanced_cache_manager import get_ecm_instance, EnhancedCacheManager
from app.models import Stock
from app import db
from datetime import datetime
import pandas as pd
from sqlalchemy import or_


import logging
logger = logging.getLogger(__name__)
class DataManager:
    def __init__(self):
        self.tushare = TushareProvider()
        self.cache = get_ecm_instance()
    
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
                logger.info(f"使用缓存数据: {ts_code}")
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
            return len(df)

        return 0

    def sync_all_daily_data(self):
        stocks = Stock.query.all()
        count = 0
        
        for stock in stocks:
            count += self.sync_daily_data(stock.ts_code)
        
        return count
    
    def get_cached_daily_data(self, ts_code, start_date=None, end_date=None):
        """从缓存获取日线数据（244号方案：移除PG DailyData降级，只走内存→DuckDB）"""
        return self.cache.get_cached_daily(ts_code, start_date, end_date)

    def preload_cache(self):
        """缓存预热 — 从 Stock 表获取股票列表，逐只预热"""
        stocks = Stock.query.all()
        count = 0
        for s in stocks:
            self.get_cached_daily_data(s.ts_code)
            count += 1
            if count % 50 == 0:
                logger.info(f"已预热 {count} 只股票")
        logger.info(f"缓存预热完成: {count} 只股票")

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
    
    def sync_daily_basic_data(self, ts_code=None, start_date=None, end_date=None, trade_date=None):
        """
        同步每日基础数据（换手率、市盈率、市值等）

        Args:
            ts_code: 股票代码（如果None则获取当日全部）
            start_date: 开始日期
            end_date: 结束日期
            trade_date: 指定交易日（传此参数则获取当日全部股票）

        Returns:
            同步的数据条数
        """
        data = self.tushare.get_daily_basic(ts_code, start_date, end_date, trade_date)

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


    def sync_moneyflow_data(self, trade_date=None):
        """同步资金流向数据"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        data = self.tushare.get_moneyflow(trade_date=trade_date)
        if not data:
            return 0
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            buy_lg = item.get('buy_lg_amount', 0) or 0
            sell_lg = item.get('sell_lg_amount', 0) or 0
            buy_elg = item.get('buy_elg_amount', 0) or 0
            sell_elg = item.get('sell_elg_amount', 0) or 0
            buy_sm = item.get('buy_sm_amount', 0) or 0
            sell_sm = item.get('sell_sm_amount', 0) or 0
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'buy_lg_vol': item.get('buy_lg_vol'),
                'buy_lg_amount': buy_lg,
                'sell_lg_vol': item.get('sell_lg_vol'),
                'sell_lg_amount': sell_lg,
                'buy_elg_amount': buy_elg,
                'sell_elg_amount': sell_elg,
                'buy_sm_amount': buy_sm,
                'sell_sm_amount': sell_sm,
                'net_lg_amount': round(float(buy_lg) - float(sell_lg), 2),
                'net_elg_amount': round(float(buy_elg) - float(sell_elg), 2),
                'net_sm_amount': round(float(buy_sm) - float(sell_sm), 2),
            })
        if df_data:
            df = pd.DataFrame(df_data)
            self.cache.cache_moneyflow_data(df)
            return len(df)
        return 0

    def get_cached_moneyflow(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        """从缓存获取资金流向数据"""
        return self.cache.get_cached_moneyflow(
            ts_code=ts_code, trade_date=trade_date,
            start_date=start_date, end_date=end_date
        )

    # ==========================================
    # 批量数据同步方法（供 scheduler 调用）
    # ==========================================

    def sync_daily_data_range(self, start_date: str, end_date: str = None, mode: str = 'incremental') -> int:
        """同步指定日期范围内所有股票的日线数据

        Args:
            start_date: 起始日期 YYYYMMDD 或 datetime.date
            end_date: 结束日期 YYYYMMDD 或 datetime.date（默认今天）
            mode: 'incremental'（增量）或 'full'（全量强制覆盖）

        Returns:
            同步的记录总数
        """
        from app.models import Stock
        stocks = Stock.query.all()
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        if hasattr(start_date, 'strftime'):
            start_date = start_date.strftime('%Y%m%d')
        if hasattr(end_date, 'strftime'):
            end_date = end_date.strftime('%Y%m%d')

        total = 0
        for stock in stocks:
            cnt = self.sync_daily_data(
                stock.ts_code, use_cache=False,
                start_date=start_date, end_date=end_date
            )
            total += cnt
            if total % 100 == 0:
                logger.info(f"日线同步进度: {total} 条")
        return total

    def sync_index_daily_data(self, trade_date: str = None) -> int:
        """同步指数日线数据到缓存

        Args:
            trade_date: 日期 YYYYMMDD（默认空，表示获取最新）

        Returns:
            缓存的指数记录数
        """
        if not self.tushare or not self.tushare.pro:
            return 0
        total = 0
        index_codes = ['000001.SH', '399001.SZ', '899050.BJ', '399006.SZ']
        import pandas as pd
        for code in index_codes:
            try:
                raw = self.tushare.get_index_daily(code)
                if raw:
                    df = pd.DataFrame(raw)
                    # trade_date 来自 Tushare 为 YYYYMMDD, DuckDB DATE 列需要 YYYY-MM-DD
                    if not df.empty and 'trade_date' in df.columns:
                        df['trade_date'] = pd.to_datetime(
                            df['trade_date'], format='%Y%m%d'
                        ).dt.date
                    self.cache.cache_daily_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步指数 {code} 失败: {e}")
        logger.info(f"指数日线缓存同步完成: {total} 条")
        return total

    def sync_adj_factor_data(self, ts_code: str = None, start_date: str = None, end_date: str = None) -> int:
        """同步复权因子数据到缓存

        Args:
            ts_code: 股票代码（None 则同步全部）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            同步的记录数
        """
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        if ts_code:
            raw = self.tushare.get_adj_factor(ts_code, start_date, end_date)
            if raw:
                df = pd.DataFrame(raw)
                # adj_factor 仅含 ts_code/trade_date/adj_factor, 写入独立表
                if not df.empty and 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(
                        df['trade_date'], format='%Y%m%d'
                    ).dt.date
                self.cache.cache_adj_factor_data(df)
                return len(df)
            return 0
        # 同步全部股票
        from app.models import Stock
        stocks = Stock.query.all()
        total = 0
        for stk in stocks:
            raw = self.tushare.get_adj_factor(stk.ts_code, start_date, end_date)
            if raw:
                df = pd.DataFrame(raw)
                if not df.empty and 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(
                        df['trade_date'], format='%Y%m%d'
                    ).dt.date
                self.cache.cache_adj_factor_data(df)
                total += len(df)
        return total

    # ══════════════════════════════════════════════

    def get_fina_indicator(self, ts_code, start_date=None, end_date=None):
        """获取财务指标数据（需5000积分）"""
        return self.tushare.get_fina_indicator(ts_code, start_date, end_date)

    def get_income(self, ts_code, start_date=None, end_date=None):
        """获取利润表数据（需5000积分）"""
        return self.tushare.get_income(ts_code, start_date, end_date)

    def get_balancesheet(self, ts_code, start_date=None, end_date=None):
        """获取资产负债表数据（需5000积分）"""
        return self.tushare.get_balancesheet(ts_code, start_date, end_date)

    def get_cashflow(self, ts_code, start_date=None, end_date=None):
        """获取现金流量表数据（需5000积分）"""
        return self.tushare.get_cashflow(ts_code, start_date, end_date)

    def get_top10_holders(self, ts_code, end_date=None):
        """获取前十大股东数据（需5000积分）"""
        return self.tushare.get_top10_holders(ts_code, end_date)

    def get_stk_holdernumber(self, ts_code, start_date=None, end_date=None):
        """获取股东人数数据（需5000积分）"""
        return self.tushare.get_stk_holdernumber(ts_code, start_date, end_date)

    def get_margin(self, ts_code, start_date=None, end_date=None):
        """获取融资融券数据（需5000积分）"""
        return self.tushare.get_margin(ts_code, start_date, end_date)

    def get_forecast(self, ts_code, start_date=None, end_date=None):
        """获取业绩预告数据（需5000积分）"""
        return self.tushare.get_forecast(ts_code, start_date, end_date)

    def get_industry(self, ts_code=None):
        """获取行业分类数据（需5000积分）"""
        return self.tushare.get_industry(ts_code)

    def get_concept(self, ts_code=None):
        """获取概念分类数据（需5000积分）"""
        return self.tushare.get_concept(ts_code)

    def get_index_member(self, index_code):
        """获取指数成分股（需5000积分）"""
        return self.tushare.get_index_member(index_code)
