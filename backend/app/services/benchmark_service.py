"""
基准数据获取服务
支持沪深300、中证500、中证1000、上证指数等主要A股指数
"""
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.data.tushare_provider import TushareProvider


class BenchmarkIndex:
    """基准指数定义"""
    
    HS300 = "000300.SH"
    ZZ500 = "000905.SH"
    ZZ1000 = "000852.SH"
    SH_COMP = "000001.SH"
    SZ_COMP = "399001.SZ"
    CYB = "399006.SZ"
    KCB = "000688.SH"
    
    NAMES = {
        HS300: "沪深300",
        ZZ500: "中证500",
        ZZ1000: "中证1000",
        SH_COMP: "上证指数",
        SZ_COMP: "深证成指",
        CYB: "创业板指",
        KCB: "科创50"
    }


class BenchmarkService:
    """
    基准数据获取服务
    
    提供A股主要指数的历史数据获取和缓存
    """
    
    def __init__(self, provider: Optional[TushareProvider] = None):
        self.provider = provider or TushareProvider()
        self.cache: Dict[str, pd.DataFrame] = {}
    
    def get_index_list(self) -> List[Dict]:
        """
        获取支持的指数列表
        
        Returns:
            指数列表，包含ts_code, name, count等信息
        """
        indices = []
        for ts_code, name in BenchmarkIndex.NAMES.items():
            indices.append({
                'ts_code': ts_code,
                'name': name
            })
        return indices
    
    def get_index_daily(self, 
                       ts_code: str = BenchmarkIndex.HS300,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None,
                       use_cache: bool = True) -> pd.DataFrame:
        """
        获取指数日线数据
        
        Args:
            ts_code: 指数代码
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            use_cache: 是否使用缓存
        
        Returns:
            指数日线数据DataFrame
        """
        cache_key = f"{ts_code}_{start_date}_{end_date}"
        
        if use_cache and cache_key in self.cache:
            return self.cache[cache_key].copy()
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365 * 5)).strftime('%Y%m%d')
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        data = self.provider.get_index_daily(ts_code)
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]
        df = df.sort_values('trade_date')
        
        self.cache[cache_key] = df.copy()
        
        return df
    
    def get_multiple_indices(self,
                            ts_codes: List[str],
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        获取多个指数数据
        
        Args:
            ts_codes: 指数代码列表
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            字典，key为指数代码，value为DataFrame
        """
        result = {}
        for ts_code in ts_codes:
            df = self.get_index_daily(ts_code, start_date, end_date)
            if not df.empty:
                result[ts_code] = df
        return result
    
    def get_benchmark_with_returns(self,
                                 ts_code: str = BenchmarkIndex.HS300,
                                 start_date: Optional[str] = None,
                                 end_date: Optional[str] = None) -> pd.DataFrame:
        """
        获取指数数据并计算收益率
        
        Args:
            ts_code: 指数代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            包含价格和收益率的DataFrame
        """
        df = self.get_index_daily(ts_code, start_date, end_date)
        
        if df.empty:
            return pd.DataFrame()
        
        df = df.sort_values('trade_date')
        df['daily_return'] = df['close'].pct_change()
        df['cumulative_return'] = (1 + df['daily_return']).cumprod() - 1
        
        return df
    
    def get_index_constituents(self, ts_code: str) -> List[str]:
        """
        获取指数成分股（模拟实现）
        
        注意：完整实现需要Tushare高级权限
        
        Args:
            ts_code: 指数代码
        
        Returns:
            成分股代码列表
        """
        constituents_map = {
            BenchmarkIndex.HS300: ['600519.SH', '600036.SH', '000858.SH', '601318.SH', '600276.SH'],
            BenchmarkIndex.ZZ500: ['600000.SH', '600016.SH', '600030.SH', '600050.SH', '600887.SH'],
            BenchmarkIndex.ZZ1000: ['600004.SH', '600009.SH', '600018.SH', '600028.SH', '600031.SH'],
            BenchmarkIndex.SH_COMP: [],
            BenchmarkIndex.SZ_COMP: [],
            BenchmarkIndex.CYB: [],
            BenchmarkIndex.KCB: []
        }
        
        return constituents_map.get(ts_code, [])
    
    def calculate_benchmark_metrics(self,
                                    ts_code: str = BenchmarkIndex.HS300,
                                    start_date: Optional[str] = None,
                                    end_date: Optional[str] = None) -> Dict:
        """
        计算指数绩效指标
        
        Args:
            ts_code: 指数代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            绩效指标字典
        """
        df = self.get_benchmark_with_returns(ts_code, start_date, end_date)
        
        if df.empty or len(df) < 2:
            return {}
        
        import numpy as np
        
        daily_returns = df['daily_return'].dropna()
        
        total_return = df['cumulative_return'].iloc[-1]
        trading_days = len(df)
        annual_return = (1 + total_return) ** (252 / trading_days) - 1
        
        volatility = daily_returns.std() * np.sqrt(252)
        
        cummax = df['close'].cummax()
        drawdown = (cummax - df['close']) / cummax
        max_drawdown = drawdown.max()
        
        risk_free_rate = 0.03
        excess_returns = daily_returns - risk_free_rate / 252
        sharke_ratio = np.sqrt(252) * excess_returns.mean() / (daily_returns.std() + 1e-10)
        
        downside_returns = daily_returns[daily_returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 1e-10
        sortino_ratio = np.sqrt(252) * excess_returns.mean() / downside_std
        
        return {
            'ts_code': ts_code,
            'name': BenchmarkIndex.NAMES.get(ts_code, ts_code),
            'total_return': float(total_return),
            'annual_return': float(annual_return),
            'volatility': float(volatility),
            'max_drawdown': float(max_drawdown),
            'sharpe_ratio': float(sharke_ratio),
            'sortino_ratio': float(sortino_ratio),
            'trading_days': trading_days
        }
    
    def compare_benchmarks(self,
                         ts_codes: List[str],
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> pd.DataFrame:
        """
        对比多个指数绩效
        
        Args:
            ts_codes: 指数代码列表
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            对比结果DataFrame
        """
        results = []
        for ts_code in ts_codes:
            metrics = self.calculate_benchmark_metrics(ts_code, start_date, end_date)
            if metrics:
                results.append(metrics)
        
        if not results:
            return pd.DataFrame()
        
        return pd.DataFrame(results)
    
    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()
    
    def get_index_industry_weight(self, ts_code: str) -> pd.DataFrame:
        """
        获取指数行业权重
        
        注意：需要Tushare高级权限
        
        Args:
            ts_code: 指数代码
        
        Returns:
            行业权重DataFrame
        """
        return pd.DataFrame()
    
    def get_index_basic_info(self, ts_code: str) -> Dict:
        """
        获取指数基本信息
        
        Args:
            ts_code: 指数代码
        
        Returns:
            指数基本信息
        """
        info = {
            'ts_code': ts_code,
            'name': BenchmarkIndex.NAMES.get(ts_code, ts_code),
            'full_name': self._get_full_name(ts_code),
            'publish_date': self._get_publish_date(ts_code),
            'base_date': self._get_base_date(ts_code),
            'base_point': 1000
        }
        return info
    
    def _get_full_name(self, ts_code: str) -> str:
        """获取指数全称"""
        full_names = {
            BenchmarkIndex.HS300: "中证沪市沪深300指数",
            BenchmarkIndex.ZZ500: "中证中证500指数",
            BenchmarkIndex.ZZ1000: "中证中证1000指数",
            BenchmarkIndex.SH_COMP: "上海证券交易所综合股价指数",
            BenchmarkIndex.SZ_COMP: "深圳证券交易所成分股价指数",
            BenchmarkIndex.CYB: "深圳证券交易所创业板指数",
            BenchmarkIndex.KCB: "上海证券交易所科创板指数"
        }
        return full_names.get(ts_code, ts_code)
    
    def _get_publish_date(self, ts_code: str) -> str:
        """获取指数发布日期"""
        dates = {
            BenchmarkIndex.HS300: "20050408000000",
            BenchmarkIndex.ZZ500: "20070131000000",
            BenchmarkIndex.ZZ1000: "20141017000000",
            BenchmarkIndex.SH_COMP: "19910715000000",
            BenchmarkIndex.SZ_COMP: "19950101",
            BenchmarkIndex.CYB: "20100601",
            BenchmarkIndex.KCB: "20190613"
        }
        return dates.get(ts_code, "")
    
    def _get_base_date(self, ts_code: str) -> str:
        """获取指数基期"""
        dates = {
            BenchmarkIndex.HS300: "20041231",
            BenchmarkIndex.ZZ500: "20041231",
            BenchmarkIndex.ZZ1000: "20141231",
            BenchmarkIndex.SH_COMP: "19901219",
            BenchmarkIndex.SZ_COMP: "19941208",
            BenchmarkIndex.CYB: "20100531",
            BenchmarkIndex.KCB: "20191231"
        }
        return dates.get(ts_code, "")


def create_benchmark_service(provider: Optional[TushareProvider] = None) -> BenchmarkService:
    """创建基准服务实例"""
    return BenchmarkService(provider)
