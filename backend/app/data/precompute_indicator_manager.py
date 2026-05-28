"""
预计算指标管理器
借鉴Vibe-Trading和Qlib的预计算策略
功能说明：
1. 批量预计算所有指标并缓存
2. 从缓存快速获取指标数据
3. 支持预计算触发
"""
import pandas as pd
from datetime import datetime
from typing import Optional
from app.indicators import TechnicalIndicatorEngine



import logging
logger = logging.getLogger(__name__)
class PrecomputeIndicatorManager:
    """
    预计算指标管理器核心类
    """
    
    def __init__(self, cache_manager):
        """
        初始化预计算管理器
        
        Args:
            cache_manager: EnhancedCacheManager实例
        """
        self.cache_manager = cache_manager
        self.engine = TechnicalIndicatorEngine()
    
    def precompute_all_indicators(self, ts_code: str, df: pd.DataFrame, force: bool = False) -> bool:
        """
        预计算所有指标并批量缓存
        
        Args:
            ts_code: 股票代码
            df: 日线数据DataFrame
            force: 是否强制重新计算（忽略已有缓存）
            
        Returns:
            bool: 是否成功完成预计算
        """
        if len(df) < 30:
            return False
        
        try:
            # 计算所有指标
            result = self.engine.calculate_all_indicators(df)
            
            # 批量缓存指标
            self._batch_cache_indicators(result, ts_code)
            
            return True
        except Exception as e:
            logger.warning(r"预计算指标失败 [{ts_code}]: {e}")
            return False
    
    def _batch_cache_indicators(self, df: pd.DataFrame, ts_code: str):
        """
        批量缓存计算好的指标
        
        Args:
            df: 包含指标的DataFrame
            ts_code: 股票代码
        """
        indicator_cols = [
            'ma5', 'ma10', 'ma20',
            'macd_dif', 'macd_dea', 'macd_hist',
            'rsi14',
            'kdj_k', 'kdj_d', 'kdj_j',
            'boll_upper', 'boll_mid', 'boll_lower',
            'vol_ma5', 'vol_ma10'
        ]
        
        records = []
        now = datetime.now()
        
        for _, row in df.iterrows():
            for col in indicator_cols:
                val = row.get(col)
                if pd.notna(val):
                    records.append({
                        'ts_code': ts_code,
                        'trade_date': row['trade_date'],
                        'indicator_name': col,
                        'value': float(val),
                        'cached_at': now
                    })
        
        if records:
            self.cache_manager.batch_cache_indicators(records)
    
    def get_precomputed_indicators(self, ts_code: str, indicators: Optional[list] = None) -> pd.DataFrame:
        """
        获取预计算好的指标（优先从缓存）
        
        Args:
            ts_code: 股票代码
            indicators: 需要的指标列表，None表示所有常用指标
            
        Returns:
            pd.DataFrame: 包含指标的DataFrame
        """
        if indicators is None:
            indicators = ['ma5', 'ma10', 'ma20', 'macd_dif', 'rsi14']
        
        result = pd.DataFrame()
        
        for indicator in indicators:
            df = self.cache_manager.get_indicator_data(ts_code, indicator)
            if not df.empty:
                if result.empty:
                    result = df[['trade_date', 'value']].rename(columns={'value': indicator})
                else:
                    # 按trade_date合并
                    temp = df[['trade_date', 'value']].rename(columns={'value': indicator})
                    result = result.merge(temp, on='trade_date', how='outer')
        
        # 按日期排序
        if not result.empty:
            result = result.sort_values('trade_date').reset_index(drop=True)
        
        return result
    
    def get_single_indicator(self, ts_code: str, indicator_name: str) -> pd.DataFrame:
        """
        获取单个预计算指标
        
        Args:
            ts_code: 股票代码
            indicator_name: 指标名称
            
        Returns:
            pd.DataFrame: 指标数据
        """
        return self.cache_manager.get_indicator_data(ts_code, indicator_name)
