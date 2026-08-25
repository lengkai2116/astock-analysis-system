"""
数据源降级管理器（355号方案规则6.2）
===================================
提供数据源故障时的自动降级机制。

降级策略：
1. 主数据源故障 → 自动切换到降级数据源
2. 降级数据源也故障 → 返回空数据，记录告警日志
3. 降级决策：基于数据源可用性、数据质量、响应时间综合判断
"""

import logging
import time
from typing import Optional, Any, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


class FallbackManager:
    """数据源降级管理器"""
    
    def __init__(self):
        # 数据源健康状态
        self._health_status: Dict[str, Dict] = {}
        # 降级链配置
        self._fallback_chains: Dict[str, List[str]] = {}
        # 降级历史
        self._fallback_history: List[Dict] = []
        
    def register_fallback_chain(self, source_name: str, fallback_chain: List[str]):
        """注册数据源降级链
        
        Args:
            source_name: 主数据源名称
            fallback_chain: 降级数据源列表（按优先级排序）
        """
        self._fallback_chains[source_name] = fallback_chain
        logger.info(f"注册降级链: {source_name} → {fallback_chain}")
        
    def update_health_status(self, source_name: str, is_healthy: bool, 
                            response_time: float = 0, error_msg: str = None):
        """更新数据源健康状态
        
        Args:
            source_name: 数据源名称
            is_healthy: 是否健康
            response_time: 响应时间（毫秒）
            error_msg: 错误信息
        """
        if source_name not in self._health_status:
            self._health_status[source_name] = {
                'healthy': True,
                'last_check': datetime.now(),
                'consecutive_failures': 0,
                'total_failures': 0,
                'avg_response_time': 0
            }
        
        status = self._health_status[source_name]
        status['last_check'] = datetime.now()
        
        if is_healthy:
            status['healthy'] = True
            status['consecutive_failures'] = 0
            # 更新平均响应时间
            if status['avg_response_time'] == 0:
                status['avg_response_time'] = response_time
            else:
                status['avg_response_time'] = (status['avg_response_time'] + response_time) / 2
        else:
            status['consecutive_failures'] += 1
            status['total_failures'] += 1
            if status['consecutive_failures'] >= 3:
                status['healthy'] = False
                logger.warning(f"数据源 {source_name} 连续失败 {status['consecutive_failures']} 次，标记为不健康")
                
    def get_healthy_source(self, source_name: str) -> Optional[str]:
        """获取可用的数据源（考虑健康状态）
        
        Args:
            source_name: 请求的数据源名称
            
        Returns:
            可用的数据源名称，如果没有可用的则返回None
        """
        # 首先检查主数据源
        if self._is_source_healthy(source_name):
            return source_name
            
        # 主数据源不健康，查找降级链
        fallback_chain = self._fallback_chains.get(source_name, [])
        for fallback_source in fallback_chain:
            if self._is_source_healthy(fallback_source):
                logger.info(f"数据源 {source_name} 不健康，降级到 {fallback_source}")
                self._record_fallback(source_name, fallback_source)
                return fallback_source
                
        logger.warning(f"数据源 {source_name} 及其降级链均不可用")
        return None
        
    def _is_source_healthy(self, source_name: str) -> bool:
        """检查数据源是否健康"""
        if source_name not in self._health_status:
            # 未注册的数据源，默认健康
            return True
        return self._health_status[source_name]['healthy']
        
    def _record_fallback(self, from_source: str, to_source: str):
        """记录降级事件"""
        self._fallback_history.append({
            'from': from_source,
            'to': to_source,
            'timestamp': datetime.now()
        })
        # 保留最近100条记录
        if len(self._fallback_history) > 100:
            self._fallback_history = self._fallback_history[-100:]
            
    def get_health_report(self) -> Dict:
        """获取数据源健康状态报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'sources': {},
            'fallback_count': len(self._fallback_history)
        }
        
        for source_name, status in self._health_status.items():
            report['sources'][source_name] = {
                'healthy': status['healthy'],
                'consecutive_failures': status['consecutive_failures'],
                'total_failures': status['total_failures'],
                'avg_response_time': round(status['avg_response_time'], 2),
                'last_check': status['last_check'].isoformat()
            }
            
        return report


# 全局单例
fallback_manager = FallbackManager()


def init_fallback_chains():
    """初始化降级链配置"""
    # 注册降级链
    fallback_manager.register_fallback_chain('eastmoney_http', ['mootdx', 'sina_http', 'tencent_http', 'cache'])
    fallback_manager.register_fallback_chain('mootdx', ['akshare', 'cache'])
    fallback_manager.register_fallback_chain('tushare', ['akshare', 'cache'])
    fallback_manager.register_fallback_chain('akshare', ['cache'])
    
    logger.info("降级链配置初始化完成")
