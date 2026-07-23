import os
import sys
import pandas as pd
from datetime import datetime
import tushare as ts

# ── 代理环境变量免疫 ──────────────────────────────────
# 与 akshare_provider.py 同步处理（240号方案 §1.4 方案C）
for _key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
             'http_proxy', 'https_proxy', 'all_proxy']:
    os.environ.pop(_key, None)


import logging
logger = logging.getLogger(__name__)

# ── Tushare 全局速率限制（与 data_daemon.py 同步） ──
import time as _time
_ts_last_call = 0.0
_TS_MIN_INTERVAL = 0.2  # 5次/秒

def _ts(pro_func, *args, **kwargs):
    """带速率限制的 Tushare API 调用"""
    global _ts_last_call
    elapsed = _time.time() - _ts_last_call
    if elapsed < _TS_MIN_INTERVAL:
        _time.sleep(_TS_MIN_INTERVAL - elapsed)
    _ts_last_call = _time.time()
    return pro_func(*args, **kwargs)
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

    def check_health(self) -> dict:
        """真实健康检查：调用 Tushare API 验证连通性"""
        if not self.pro:
            return {'status': 'error', 'message': 'API 未初始化'}
        try:
            df = _ts(self.pro.trade_cal, exchange='SSE', start_date='20260706', end_date='20260706')
            if df is not None and not df.empty:
                return {'status': 'ok'}
            return {'status': 'error', 'message': 'API 返回空'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)[:80]}

    def get_stock_list(self, market='all'):
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.stock_basic, exchange='', 
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
            
            data = _ts(self.pro.daily,ts_code=ts_code, start_date=start_date, end_date=end_date)
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
            
            data = _ts(self.pro.weekly, ts_code=ts_code, start_date=start_date, end_date=end_date)
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
            
            data = _ts(self.pro.monthly, ts_code=ts_code, start_date=start_date, end_date=end_date)
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
            logger.warning(f"获取分钟线数据失败 ({ts_code}, {freq}): {e}")
            return []
    

    def get_daily_by_date(self, trade_date):
        """按日期获取所有股票日线数据"""
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.daily, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_index_daily(self, ts_code='000001.SH'):
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.index_daily, ts_code=ts_code)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_stk_limit(self, trade_date):
        """获取涨跌停数据"""
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.stk_limit, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_moneyflow(self, trade_date):
        """获取资金流向数据"""
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.moneyflow, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_top_list(self, trade_date):
        """获取龙虎榜数据"""
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.top_list, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_top_inst(self, trade_date):
        """获取龙虎榜席位明细（278号方案：席位级数据用于假机构识别）"""
        if not self.pro:
            return []
        try:
            data = _ts(self.pro.top_inst, trade_date=trade_date)
            if data is None:
                return []
            records = data.to_dict('records')
            for r in records:
                if r.get('side') in ('0', 0, '1', 1):
                    r['side_label'] = 'buy' if str(r['side']) == '0' else 'sell'
            return records
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
                data = _ts(self.pro.daily_basic, trade_date=trade_date)
            else:
                if start_date is None:
                    start_date = (datetime.now() - pd.Timedelta(days=5*365)).strftime('%Y%m%d')
                if end_date is None:
                    end_date = datetime.now().strftime('%Y%m%d')
                
                data = _ts(self.pro.daily_basic,
ts_code=ts_code, 
                    start_date=start_date, 
                    end_date=end_date
                )
            
            return data.to_dict('records') if not data.empty else []
        except Exception as e:
            logger.warning(f"获取每日基础数据失败: {e}")
            return []
        
        try:
            data = _ts(self.pro.daily, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_index_daily(self, ts_code='000001.SH'):
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.index_daily, ts_code=ts_code)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_stk_limit(self, trade_date):
        """获取涨跌停数据"""
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.stk_limit, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_moneyflow(self, trade_date):
        """获取资金流向数据"""
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.moneyflow, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_top_list(self, trade_date):
        """获取龙虎榜数据"""
        if not self.pro:
            return []
        
        try:
            data = _ts(self.pro.top_list, trade_date=trade_date)
            return data.to_dict('records')
        except Exception:
            return []
    
    def get_top_inst(self, trade_date):
        """获取龙虎榜席位明细（278号方案：席位级数据用于假机构识别）"""
        if not self.pro:
            return []
        try:
            data = _ts(self.pro.top_inst, trade_date=trade_date)
            if data is None:
                return []
            records = data.to_dict('records')
            for r in records:
                if r.get('side') in ('0', 0, '1', 1):
                    r['side_label'] = 'buy' if str(r['side']) == '0' else 'sell'
            return records
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
                data = _ts(self.pro.daily_basic, trade_date=trade_date)
            else:
                # 获取指定股票的历史数据
                if start_date is None:
                    start_date = (datetime.now() - pd.Timedelta(days=5*365)).strftime('%Y%m%d')
                if end_date is None:
                    end_date = datetime.now().strftime('%Y%m%d')
                
                data = _ts(self.pro.daily_basic,
ts_code=ts_code, 
                    start_date=start_date, 
                    end_date=end_date
                )
            
            return data.to_dict('records') if not data.empty else []
        except Exception as e:
            logger.warning(r"获取每日基础数据失败: {e}")
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
            
            data = _ts(self.pro.adj_factor,
                ts_code=ts_code, 
                start_date=start_date, 
                end_date=end_date
            )
            
            return data.to_dict('records') if not data.empty else []
        except Exception as e:
            logger.warning(f"获取复权因子失败 ({ts_code}): {e}")
            return []
    
    def test_connection(self):
        """测试连接"""
        if not self.pro:
            return False, '未初始化API'
        
        try:
            df = _ts(self.pro.stock_basic, list_status='L', fields='ts_code,name', limit=5)
            if df is not None and not df.empty:
                return True, f'连接成功，获取到{len(df)}只股票'
            return False, '数据为空'
        except Exception as e:
            return False, str(e)

    # ══════════════════════════════════════════════
    # 以下为 5000积分 级别补齐 API（Provider层）
    # 前置条件：Tushare Pro Token 具备 5000分 权限（已确认就绪）
    # ══════════════════════════════════════════════

    # 273a: 扩展字段列表包含排雷所需指标
    FINA_FIELDS_ORIGINAL = (
        'ts_code,end_date,ann_date,eps,eps_diluted,eps_ttm,bvps,roe,revenue_ps,profit_ps,cf_ps'
    )
    FINA_FIELDS_EXTENDED = (
        'ts_code,end_date,ann_date,'
        'eps,eps_diluted,eps_ttm,bvps,roe,revenue_ps,profit_ps,cf_ps,'
        'roce,quick_ratio,ocfps,current_ratio,'
        'ebit,operating_profit,total_assets,total_liab,'
        'current_assets,current_liab'
    )

    def get_fina_indicator(self, ts_code, start_date=None, end_date=None):
        """获取财务指标数据（需5000积分）
        默认返回原始字段集（向后兼容 fina_indicator_cache）。
        """
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=2*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.fina_indicator, ts_code=ts_code,
                fields=self.FINA_FIELDS_ORIGINAL,
                start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取财务指标失败 ({ts_code}): {e}")
            return []

    def get_fina_indicator_extended(self, ts_code, start_date=None, end_date=None):
        """获取扩展财务指标（含 roce/quick_ratio/ocfps 等，供 273a 排雷使用）"""
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=2*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.fina_indicator, ts_code=ts_code,
                fields=self.FINA_FIELDS_EXTENDED,
                start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取扩展财务指标失败 ({ts_code}): {e}")
            return []

    def get_income(self, ts_code, start_date=None, end_date=None):
        """获取利润表数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=2*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.income, ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取利润表失败 ({ts_code}): {e}")
            return []

    def get_balancesheet(self, ts_code, start_date=None, end_date=None):
        """获取资产负债表数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=2*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.balancesheet, ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取资产负债表失败 ({ts_code}): {e}")
            return []

    def get_cashflow(self, ts_code, start_date=None, end_date=None):
        """获取现金流量表数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=2*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.cashflow, ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取现金流量表失败 ({ts_code}): {e}")
            return []

    def get_top10_holders(self, ts_code, end_date=None):
        """获取前十大股东数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            data = _ts(self.pro.top10_holders, ts_code=ts_code)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取前十大股东失败 ({ts_code}): {e}")
            return []

    def get_stk_holdernumber(self, ts_code, start_date=None, end_date=None):
        """获取股东人数数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=2*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.stk_holdernumber, ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取股东人数失败 ({ts_code}): {e}")
            return []

    def get_margin(self, ts_code, start_date=None, end_date=None):
        """获取融资融券数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=1*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.margin, ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取融资融券失败 ({ts_code}): {e}")
            return []

    def get_forecast(self, ts_code, start_date=None, end_date=None):
        """获取业绩预告数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if start_date is None:
                start_date = (datetime.now() - pd.Timedelta(days=2*365)).strftime('%Y%m%d')
            if end_date is None:
                end_date = datetime.now().strftime('%Y%m%d')
            data = _ts(self.pro.forecast, ts_code=ts_code, start_date=start_date, end_date=end_date)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取业绩预告失败 ({ts_code}): {e}")
            return []

    def get_industry(self, ts_code=None):
        """获取行业分类数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if ts_code:
                data = _ts(self.pro.industry, ts_code=ts_code)
            else:
                data = _ts(self.pro.industry)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取行业分类失败: {e}")
            return []

    def get_concept(self, ts_code=None):
        """获取概念分类数据（需5000积分）"""
        if not self.pro:
            return []
        try:
            if ts_code:
                data = _ts(self.pro.concept, ts_code=ts_code)
            else:
                data = _ts(self.pro.concept)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取概念分类失败: {e}")
            return []

    def get_index_member(self, index_code):
        """获取指数成分股（需5000积分）"""
        if not self.pro:
            return []
        try:
            data = _ts(self.pro.index_member, index_code=index_code)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取指数成分股失败 ({index_code}): {e}")
            return []

    def get_moneyflow_data(self, ts_code):
        """获取单只股票资金流向（按ts_code查询）

        与 get_moneyflow(trade_date) 不同，本方法按股票代码查询。
        """
        if not self.pro:
            return []
        try:
            data = _ts(self.pro.moneyflow, ts_code=ts_code)
            return data.to_dict('records') if data is not None and not data.empty else []
        except Exception as e:
            logger.warning(f"获取资金流向失败 ({ts_code}): {e}")
            return []

    def get_stock_info(self, ts_code):
        """获取单只股票基本信息（行业/上市日期/股本等）"""
        if not self.pro:
            return None
        try:
            data = _ts(self.pro.stock_basic, ts_code=ts_code)
            if data is not None and not data.empty:
                row = data.iloc[0].to_dict()
                return {
                    'name': row.get('name', ''),
                    'industry': row.get('industry', ''),
                    'industry_full': row.get('industry', ''),
                    'list_date': row.get('list_date', ''),
                    'total_share': row.get('total_share'),
                    'float_share': row.get('float_share', row.get('circ_share')),
                }
            return None
        except Exception as e:
            logger.warning(f"获取股票基本信息失败 ({ts_code}): {e}")
            return None

if __name__ == '__main__':
    provider = TushareProvider()
    success, msg = provider.test_connection()
