import os
import sys
import pandas as pd
from datetime import datetime
import tushare as ts

class TushareProvider:
    def __init__(self):
        self.token = self._load_token()
        self.pro = self._init_api()
    
    def _load_token(self):
        """加载Tushare Token，支持多种来源"""
        token = os.getenv('TUSHARE_TOKEN', '')
        
        if not token:
            env_paths = [
                '/Users/kalence/Desktop/测试/01-A股股票分析系统/.env',
                '/Users/kalence/Desktop/测试/stock_analyzer_desktop/.env',
                '/Users/kalence/Desktop/测试/.env'
            ]
            for env_path in env_paths:
                if os.path.exists(env_path):
                    with open(env_path, 'r') as f:
                        for line in f:
                            if line.startswith('TUSHARE_TOKEN='):
                                token = line.split('=', 1)[1].strip()
                                break
                    if token:
                        break
        
        return token
    
    def _init_api(self):
        """初始化Tushare API"""
        if not self.token:
            return None
        
        try:
            ts.set_token(self.token)
            pro = ts.pro_api()
            return pro
        except Exception:
            return None
    
    def get_stock_list(self, market='all'):
        if not self.pro:
            return []
        
        try:
            data = self.pro.stock_basic(
                exchange='', 
                list_status='L', 
                fields='ts_code,symbol,name,industry,list_date,market'
            )
            if market != 'all':
                data = data[data['market'] == market]
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_daily_data(self, ts_code, start_date=None, end_date=None):
        if not self.pro:
            return []
        
        try:
            if start_date is None:
                # 默认获取5年数据，而不是1年
                start_date = (datetime.now() - pd.Timedelta(days=5*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            
            data = self.pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_weekly_data(self, ts_code, start_date=None, end_date=None):
        """获取周线数据"""
        if not self.pro:
            return []
        
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=5*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            
            data = self.pro.weekly(ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_monthly_data(self, ts_code, start_date=None, end_date=None):
        """获取月线数据"""
        if not self.pro:
            return []
        
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=10*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            
            data = self.pro.monthly(ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_minute_data(self, ts_code, freq='15min', start_date=None, end_date=None):
        """
        获取分钟线数据
        freq: 1min/5min/15min/30min/60min
        
        Tushare 5000积分档权限说明：
        - 1min: 仅可获取当日数据，历史数据需更高权限
        - 5min/15min/30min/60min: 可获取最近30天数据
        
        使用 ts.bar() 接口获取分钟线数据（新版Tushare推荐方式）
        """
        if not self.pro:
            return []
        
        try:
            if start_date is None:
                # 分钟线只获取最近30天
                start_date = (datetime.now() - pd.Timedelta(days=30)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            
            # 使用 ts.pro_bar() 接口获取分钟线数据
            # 新版 Tushare Pro 参数说明：
            # - ts_code: 证券代码（格式：600519.SH）
            # - freq: 频率，支持1min/5min/15min/30min/60min/D/W/M/Q/Y
            # - adj: 复权类型，qfq前复权
            # - start_date/end_date: 格式为YYYYMMDD
            ts.set_token(self.token)
            data = ts.pro_bar(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                freq=freq,
                adj='qfq'
            )
            
            if data is not None and not data.empty:
                return data.to_dict('records')
            return []
        except Exception as e:
            print(f"⚠️ 获取分钟线数据失败 ({ts_code}, {freq}): {e}")
            return []
    
    def get_daily_by_date(self, trade_date):
        """按日期获取所有股票日线数据"""
        if not self.pro:
            return []
        
        try:
            data = self.pro.daily(trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_index_daily(self, ts_code='000001.SH'):
        if not self.pro:
            return []
        
        try:
            data = self.pro.index_daily(ts_code=ts_code)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_stk_limit(self, trade_date):
        """获取涨跌停数据"""
        if not self.pro:
            return []
        
        try:
            data = self.pro.stk_limit(trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_moneyflow(self, trade_date):
        """获取资金流向数据"""
        if not self.pro:
            return []
        
        try:
            data = self.pro.moneyflow(trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_top_list(self, trade_date):
        """获取龙虎榜数据"""
        if not self.pro:
            return []
        
        try:
            data = self.pro.top_list(trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_daily_basic(self, ts_code=None, start_date=None, end_date=None, trade_date=None):
        """
        获取每日基础数据（换手率、市盈率、市值等）
        
        Args:
            ts_code: 股票代码（可选，如果None则获取当日全部股票）
            start_date: 开始日期（格式YYYYMMDD）
            end_date: 结束日期（格式YYYYMMDD）
            trade_date: 指定交易日期（格式YYYYMMDD，与ts_code二选一）
            
        Returns:
            数据列表
        """
        if not self.pro:
            return []
        
        try:
            if trade_date:
                # 获取指定日期全部股票
                data = self.pro.daily_basic(trade_date=trade_date)
            else:
                # 获取指定股票的历史数据
                if start_date is None:
                    start_date = (datetime.now() - pd.Timedelta(days=5*365)).strftime('%Y%m%d')
                if end_date is None:
                    end_date = datetime.now().strftime('%Y%m%d')
                
                data = self.pro.daily_basic(
                    ts_code=ts_code, 
                    start_date=start_date, 
                    end_date=end_date
                )
            
            return data.to_dict('records') if not data.empty else []
        except Exception as e:
            print(f"⚠️ 获取每日基础数据失败: {e}")
            return []
    
    def get_adj_factor(self, ts_code, start_date=None, end_date=None):
        """
        获取复权因子
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期（格式YYYYMMDD）
            end_date: 结束日期（格式YYYYMMDD）
            
        Returns:
            复权因子数据列表
        """
        if not self.pro:
            return []
        
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=5*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            
            data = self.pro.adj_factor(
                ts_code=ts_code, 
                start_date=start_date, 
                end_date=end_date
            )
            
            return data.to_dict('records') if not data.empty else []
        except Exception as e:
            print(f"⚠️ 获取复权因子失败 ({ts_code}): {e}")
            return []
    
    def test_connection(self):
        """测试连接"""
        if not self.pro:
            return False, '未初始化API'
        
        try:
            df = self.pro.stock_basic(list_status='L', fields='ts_code,name', limit=5)
            if df is not None and not df.empty:
                return True, f'连接成功，获取到{len(df)}只股票'
            return False, '数据为空'
        except Exception as e:
            return False, str(e)

if __name__ == '__main__':
    provider = TushareProvider()
    success, msg = provider.test_connection()
