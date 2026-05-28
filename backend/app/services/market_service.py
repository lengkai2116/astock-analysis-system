from app.models import Stock, DailyData
from datetime import datetime

class MarketService:
    def __init__(self):
        self._data_manager = None
    
    @property
    def data_manager(self):
        """懒加载DataManager"""
        if self._data_manager is None:
            from app.data import DataManager
            self._data_manager = DataManager()
        return self._data_manager
    
    def get_stock_list(self, page, page_size, industry=None, market=None):
        query = Stock.query
        
        if industry:
            query = query.filter(Stock.industry == industry)
        if market:
            query = query.filter(Stock.market == market)
        
        total = query.count()
        stocks = query.offset((page - 1) * page_size).limit(page_size).all()
        
        return {
            'success': True,
            'data': [s.to_dict() for s in stocks],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'pages': (total + page_size - 1) // page_size
            }
        }
    
    def get_stock_detail(self, ts_code):
        stock = Stock.query.get(ts_code)
        return stock.to_dict() if stock else None
    
    def get_daily_data(self, ts_code, start_date=None, end_date=None):
        # 避免不必要的DuckDB连接
        # 先从PostgreSQL获取
        query = DailyData.query.filter_by(ts_code=ts_code)
        
        if start_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                query = query.filter(DailyData.trade_date >= start)
            except ValueError:
                pass
        
        if end_date:
            try:
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                query = query.filter(DailyData.trade_date <= end)
            except ValueError:
                pass
        
        return [d.to_dict() for d in query.order_by(DailyData.trade_date).all()]
    
    def sync_stock_data(self):
        try:
            count = self.data_manager.sync_stock_list()
            return {
                'success': True,
                'message': f'成功同步 {count} 只股票'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'同步失败: {str(e)}'
            }
    
    def sync_daily_data(self, ts_code):
        try:
            count = self.data_manager.sync_daily_data(ts_code)
            return {
                'success': True,
                'message': f'成功同步 {count} 条日线数据'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'同步失败: {str(e)}'
            }
    
    def get_index_data(self):
        indices = [
            {'ts_code': '000001.SH', 'name': '上证指数'},
            {'ts_code': '399001.SZ', 'name': '深圳成指'},
            {'ts_code': '399006.SZ', 'name': '创业板指'}
        ]
        return indices
    
    def get_industries(self):
        industries = Stock.query.with_entities(Stock.industry).distinct().all()
        return [i[0] for i in industries if i[0]]
    
    def get_markets(self):
        markets = Stock.query.with_entities(Stock.market).distinct().all()
        return [m[0] for m in markets if m[0]]
