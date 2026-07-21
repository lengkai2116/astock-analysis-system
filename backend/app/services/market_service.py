from app.models import Stock
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


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
    
    def get_index_data(self):
        indices = [
            {'ts_code': '000001.SH', 'name': '上证指数'},
            {'ts_code': '399001.SZ', 'name': '深圳成指'},
            {'ts_code': '399006.SZ', 'name': '创业板指'}
        ]

        # 从 ECM 读取最近交易日日线数据
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            results = []
            for idx in indices:
                try:
                    df = ecm.get_cached_daily(idx['ts_code'], limit=2)
                    if df is not None and not df.empty:
                        latest = df.iloc[-1].to_dict()
                        prev = df.iloc[-2].to_dict() if len(df) >= 2 else latest
                        prev_close = prev.get('close', latest.get('pre_close', 0))
                        close_val = latest.get('close', 0)
                        change = close_val - prev_close if prev_close else 0
                        change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                        results.append({
                            'ts_code': idx['ts_code'],
                            'name': idx['name'],
                            'value': close_val,
                            'change': round(change, 2),
                            'changePercent': round(change_pct, 2),
                            'close': close_val,
                            'pre_close': prev_close,
                            'volume': latest.get('vol', 0),
                            'amount': latest.get('amount', 0),
                            'source': 'ecm',
                        })
                    else:
                        results.append({**idx, 'value': 0, 'timestamp': datetime.now().isoformat(), 'source': 'ecm'})
                except Exception as e:
                    logger.warning(f"指数数据获取失败 ({idx['ts_code']}): {e}")
                    results.append({**idx, 'value': 0, 'timestamp': datetime.now().isoformat(), 'source': 'ecm'})
            return results
        except Exception:
            return indices
    
    def get_industries(self):
        industries = Stock.query.with_entities(Stock.industry).distinct().all()
        return [i[0] for i in industries if i[0]]
    
    def get_markets(self):
        markets = Stock.query.with_entities(Stock.market).distinct().all()
        return [m[0] for m in markets if m[0]]
