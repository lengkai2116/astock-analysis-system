from app.models import Stock
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MarketService:
    def __init__(self):
        self._data_manager = None
        self._akshare = None

    @property
    def akshare(self):
        """懒加载 AkshareProvider"""
        if self._akshare is None:
            try:
                from app.data.akshare_provider import AkshareProvider
                self._akshare = AkshareProvider()
            except ImportError:
                self._akshare = None
        return self._akshare
    
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
        # 通过 DataManager 走 DuckDB
        try:
            df = self.data_manager.get_cached_daily_data(ts_code, start_date, end_date)
            if df is not None and not df.empty:
                df = df.sort_values('trade_date')
                # 将 DataFrame 的 trade_date 转为 date 对象（兼容原接口返回格式）
                records = []
                for _, r in df.iterrows():
                    d = dict(r)
                    records.append(d)
                return records
        except Exception:
            pass
        return []
    
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

        # 盘中 → AKShare 实时指数
        try:
            from app.utils.trading_hours import is_trading_time
            if is_trading_time() and self.akshare:
                results = []
                for idx in indices:
                    try:
                        data = self.akshare.get_index_daily(idx['ts_code'])
                        if data:
                            data['name'] = idx['name']
                            data['source'] = 'akshare'
                            results.append(data)
                        else:
                            results.append({**idx, 'value': 0, 'timestamp': datetime.now().isoformat(), 'source': 'akshare'})
                    except Exception as e:
                        logger.warning(f"AKShare 指数失败 ({idx['ts_code']}): {e}")
                        results.append({**idx, 'value': 0, 'timestamp': datetime.now().isoformat(), 'source': 'akshare'})
                return results
        except ImportError:
            pass

        # 盘后 / AKShare 不可用 → 返回元数据
        return indices
    
    def get_industries(self):
        industries = Stock.query.with_entities(Stock.industry).distinct().all()
        return [i[0] for i in industries if i[0]]
    
    def get_markets(self):
        markets = Stock.query.with_entities(Stock.market).distinct().all()
        return [m[0] for m in markets if m[0]]
