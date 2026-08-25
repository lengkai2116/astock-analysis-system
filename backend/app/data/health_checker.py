"""
数据源健康检查器（355号方案规则6.3）
===================================
提供数据源健康状态检查和监控功能。

检查内容：
1. 连接状态：数据源是否可达
2. 响应时间：数据源响应是否正常
3. 数据质量：返回数据是否有效
"""

import logging
import time
from typing import Dict, Optional
from datetime import datetime
import threading

logger = logging.getLogger(__name__)


class HealthChecker:
    """数据源健康检查器"""
    
    def __init__(self):
        self._health_scores: Dict[str, float] = {}
        self._check_interval = 60  # 秒
        self._running = False
        self._thread = None
        
    def check_source_health(self, source_name: str, check_func) -> float:
        """检查数据源健康状态
        
        Args:
            source_name: 数据源名称
            check_func: 检查函数，返回 (is_healthy, response_time, error_msg)
            
        Returns:
            健康评分（0-1）
        """
        try:
            start_time = time.time()
            is_healthy, response_time, error_msg = check_func()
            elapsed = (time.time() - start_time) * 1000  # 转换为毫秒
            
            # 计算健康评分
            score = self._calculate_health_score(is_healthy, elapsed, error_msg)
            self._health_scores[source_name] = score
            
            # 更新降级管理器状态
            from app.data.fallback_manager import fallback_manager
            fallback_manager.update_health_status(
                source_name, is_healthy, elapsed, error_msg
            )
            
            logger.debug(f"数据源 {source_name} 健康评分: {score:.2f}")
            return score
            
        except Exception as e:
            logger.warning(f"检查数据源 {source_name} 健康状态失败: {e}")
            self._health_scores[source_name] = 0.0
            return 0.0
            
    def _calculate_health_score(self, is_healthy: bool, response_time: float, 
                               error_msg: str) -> float:
        """计算健康评分
        
        评分标准：
        - 连接状态：0.4分
        - 响应时间：0.4分（<100ms得满分，>1000ms得0分）
        - 数据质量：0.2分
        """
        score = 0.0
        
        # 连接状态评分（0.4分）
        if is_healthy:
            score += 0.4
            
        # 响应时间评分（0.4分）
        if response_time < 100:
            score += 0.4
        elif response_time < 500:
            score += 0.3
        elif response_time < 1000:
            score += 0.2
        elif response_time < 2000:
            score += 0.1
            
        # 数据质量评分（0.2分）
        if error_msg is None:
            score += 0.2
        elif 'timeout' in str(error_msg).lower():
            score += 0.1
            
        return min(score, 1.0)
        
    def get_health_score(self, source_name: str) -> float:
        """获取数据源健康评分"""
        return self._health_scores.get(source_name, 0.0)
        
    def get_health_status(self, source_name: str) -> str:
        """获取数据源健康状态
        
        Returns:
            'healthy': 健康（评分>=0.9）
            'degraded': 降级（0.6<=评分<0.9）
            'unhealthy': 不健康（评分<0.6）
        """
        score = self.get_health_score(source_name)
        if score >= 0.9:
            return 'healthy'
        elif score >= 0.6:
            return 'degraded'
        else:
            return 'unhealthy'
            
    def start_periodic_check(self, sources: Dict[str, callable]):
        """启动定期健康检查
        
        Args:
            sources: 数据源检查函数字典 {source_name: check_func}
        """
        if self._running:
            logger.warning("健康检查已在运行")
            return
            
        self._running = True
        
        def _check_loop():
            while self._running:
                for source_name, check_func in sources.items():
                    try:
                        self.check_source_health(source_name, check_func)
                    except Exception as e:
                        logger.warning(f"定期检查 {source_name} 失败: {e}")
                time.sleep(self._check_interval)
                
        self._thread = threading.Thread(target=_check_loop, daemon=True)
        self._thread.start()
        logger.info(f"定期健康检查已启动，间隔 {self._check_interval} 秒")
        
    def stop_periodic_check(self):
        """停止定期健康检查"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("定期健康检查已停止")
        
    def get_all_health_scores(self) -> Dict[str, float]:
        """获取所有数据源健康评分"""
        return self._health_scores.copy()


# 全局单例
health_checker = HealthChecker()


def check_tushare_health():
    """检查 Tushare 健康状态"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        start = time.time()
        # 简单查询测试
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code')
        response_time = (time.time() - start) * 1000
        is_healthy = df is not None and not df.empty
        return is_healthy, response_time, None if is_healthy else "Empty response"
    except Exception as e:
        return False, 0, str(e)


def check_akshare_health():
    """检查 AKShare 健康状态"""
    try:
        import akshare as ak
        start = time.time()
        # 简单查询测试
        df = ak.stock_zh_a_spot_em()
        response_time = (time.time() - start) * 1000
        is_healthy = df is not None and not df.empty
        return is_healthy, response_time, None if is_healthy else "Empty response"
    except Exception as e:
        return False, 0, str(e)


def check_mootdx_health():
    """检查 mootdx 健康状态"""
    try:
        from mootdx import Quotes
        start = time.time()
        client = Quotes.factory(market='std')
        response_time = (time.time() - start) * 1000
        is_healthy = client is not None
        return is_healthy, response_time, None if is_healthy else "Client not available"
    except Exception as e:
        return False, 0, str(e)


def init_health_checks():
    """初始化健康检查"""
    # 注册健康检查函数
    health_checks = {
        'tushare': check_tushare_health,
        'akshare': check_akshare_health,
        'mootdx': check_mootdx_health,
    }
    
    # 执行初始健康检查
    for source_name, check_func in health_checks.items():
        try:
            health_checker.check_source_health(source_name, check_func)
        except Exception as e:
            logger.warning(f"初始健康检查 {source_name} 失败: {e}")
    
    logger.info("健康检查初始化完成")
