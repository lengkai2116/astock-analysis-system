import os
import json
import redis
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import pickle


import logging
logger = logging.getLogger(__name__)
class RedisCacheManager:
    """
    Redis二级缓存管理器
    用于缓存热点数据，提供快速访问
    """
    
    def __init__(self):
        self.redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
        self.ttl = int(os.getenv('REDIS_CACHE_TTL', 3600))  # 默认1小时
        self.prefix = 'stock:'
        self._init_redis()
        
        # 缓存命中率统计
        self.stats = {
            'hits': 0,
            'misses': 0,
            'total_requests': 0
        }
    
    def _init_redis(self):
        """初始化Redis连接"""
        try:
            self.client = redis.from_url(self.redis_url)
            self.client.ping()
            logger.info(r"Redis连接成功")
        except Exception as e:
            logger.warning(r"Redis连接失败: {e}，将使用内存缓存")
            self.client = None
            self._memory_cache = {}
    
    def _get_key(self, prefix: str, identifier: str) -> str:
        """生成缓存键"""
        return f"{self.prefix}{prefix}:{identifier}"
    
    def get_daily_data(self, ts_code: str, 
                     start_date: Optional[str] = None, 
                     end_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """
        从Redis获取日线数据
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame或None
        """
        key_parts = [ts_code]
        if start_date:
            key_parts.append(start_date)
        if end_date:
            key_parts.append(end_date)
        
        key = self._get_key('daily', '_'.join(key_parts))
        self.stats['total_requests'] += 1
        
        try:
            if self.client:
                data = self.client.get(key)
                if data:
                    df_data = json.loads(data)
                    df = pd.DataFrame(df_data)
                    # 转换日期格式
                    if 'trade_date' in df.columns:
                        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                    self.stats['hits'] += 1
                    return df
            else:
                # 使用内存缓存
                if key in self._memory_cache:
                    self.stats['hits'] += 1
                    return self._memory_cache[key]
        except Exception as e:
            logger.warning(r"Redis读取失败: {e}")
        
        self.stats['misses'] += 1
        return None
    
    def set_daily_data(self, ts_code: str, df: pd.DataFrame,
                     start_date: Optional[str] = None,
                     end_date: Optional[str] = None) -> bool:
        """
        将日线数据缓存到Redis
        
        Args:
            ts_code: 股票代码
            df: 数据DataFrame
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            是否成功
        """
        key_parts = [ts_code]
        if start_date:
            key_parts.append(start_date)
        if end_date:
            key_parts.append(end_date)
        
        key = self._get_key('daily', '_'.join(key_parts))
        
        try:
            # 准备数据用于序列化
            df_json = df.copy()
            if 'trade_date' in df_json.columns:
                df_json['trade_date'] = df_json['trade_date'].astype(str)
            
            data = df_json.to_dict('records')
            
            if self.client:
                self.client.setex(
                    key,
                    self.ttl,
                    json.dumps(data, ensure_ascii=False)
                )
            else:
                self._memory_cache[key] = df
            return True
        except Exception as e:
            logger.warning(r"Redis写入失败: {e}")
            return False
    
    def get_indicator_data(self, ts_code: str, indicator_name: str) -> Optional[pd.DataFrame]:
        """
        获取技术指标缓存
        """
        key = self._get_key('indicator', f"{ts_code}:{indicator_name}")
        self.stats['total_requests'] += 1
        
        try:
            if self.client:
                data = self.client.get(key)
                if data:
                    df_data = json.loads(data)
                    self.stats['hits'] += 1
                    return pd.DataFrame(df_data)
            else:
                if key in self._memory_cache:
                    self.stats['hits'] += 1
                    return self._memory_cache[key]
        except Exception as e:
            logger.warning(r"Redis读取失败: {e}")
        
        self.stats['misses'] += 1
        return None
    
    def set_indicator_data(self, ts_code: str, indicator_name: str, df: pd.DataFrame) -> bool:
        """
        缓存技术指标
        """
        key = self._get_key('indicator', f"{ts_code}:{indicator_name}")
        
        try:
            data = df.to_dict('records')
            if self.client:
                self.client.setex(key, self.ttl * 2, json.dumps(data))  # 指标缓存时间更长
            else:
                self._memory_cache[key] = df
            return True
        except Exception as e:
            logger.warning(r"Redis写入失败: {e}")
            return False
    
    def invalidate_daily(self, ts_code: Optional[str] = None):
        """
        使日线缓存失效
        
        Args:
            ts_code: 股票代码，如果为None则清除所有
        """
        try:
            if self.client:
                if ts_code:
                    pattern = self._get_key('daily', f"{ts_code}*")
                    for key in self.client.scan_iter(match=pattern):
                        self.client.delete(key)
                else:
                    pattern = self._get_key('daily', '*')
                    for key in self.client.scan_iter(match=pattern):
                        self.client.delete(key)
            else:
                keys_to_delete = [k for k in self._memory_cache.keys() 
                                 if k.startswith(f"{self.prefix}daily:")]
                if ts_code:
                    keys_to_delete = [k for k in keys_to_delete if ts_code in k]
                for k in keys_to_delete:
                    del self._memory_cache[k]
            return True
        except Exception as e:
            logger.warning(r"缓存失效失败: {e}")
            return False
    
    def clear_all(self):
        """清除所有缓存"""
        try:
            if self.client:
                pattern = self._get_key('*', '*')
                for key in self.client.scan_iter(match=pattern):
                    self.client.delete(key)
            else:
                self._memory_cache.clear()
            logger.info(r"Redis缓存已清空")
            return True
        except Exception as e:
            logger.warning(r"清空缓存失败: {e}")
            return False
    
    def get_hit_rate(self) -> Dict[str, float]:
        """
        获取缓存命中率
        
        Returns:
            包含命中率的字典
        """
        total = self.stats['total_requests']
        hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0
        
        return {
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'total_requests': total,
            'hit_rate_percent': hit_rate
        }
    
    def reset_stats(self):
        """重置统计"""
        self.stats = {'hits': 0, 'misses': 0, 'total_requests': 0}
