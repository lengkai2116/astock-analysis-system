"""
数据源三态管理器

对照 151-观潮对标-系统能力提升与稳定性优化方案.md §4.1
管理数据源状态（normal/degraded/fallback/unavailable），
自动切换与降级策略。

前端联动：配合 150 号方案 DataSourceStatus 状态指示组件使用。
"""

import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class DataSourceStatus(Enum):
    """数据源三态"""
    NORMAL = 'normal'          # 数据正常
    DEGRADED = 'degraded'      # 降级（延迟/部分字段缺失）
    FALLBACK = 'fallback'      # 回退（主数据源不可用，切后备）
    UNAVAILABLE = 'unavailable'  # 不可用


class DataSourceHealth:
    """单个数据源的健康状态"""

    def __init__(self, name: str, priority: int = 0):
        self.name = name
        self.priority = priority          # 优先级：数字越小越优先
        self.status = DataSourceStatus.NORMAL
        self.last_check = time.time()
        self.failures = 0
        self.consecutive_failures = 0
        self.successes = 0
        self.avg_latency_ms = 0.0
        self.last_error: Optional[str] = None
        self.last_error_time: Optional[float] = None
        self.total_requests = 0
        self._latency_samples: List[float] = []

    def record_success(self, latency_ms: float):
        """记录一次成功请求"""
        self.successes += 1
        self.total_requests += 1
        self.consecutive_failures = 0
        self.last_check = time.time()

        # 加权移动平均延迟
        if self.avg_latency_ms == 0:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = self.avg_latency_ms * 0.7 + latency_ms * 0.3

        # 自动恢复
        if self.status in (DataSourceStatus.DEGRADED, DataSourceStatus.FALLBACK):
            if self.successes >= 3:  # 连续 3 次成功自动恢复
                old = self.status
                self.status = DataSourceStatus.NORMAL
                logger.info(f"数据源 {self.name} 状态恢复: {old.value} → normal")

    def record_failure(self, error: str):
        """记录一次失败请求"""
        self.failures += 1
        self.total_requests += 1
        self.consecutive_failures += 1
        self.last_error = error
        self.last_error_time = time.time()
        self.last_check = time.time()

    def get_availability(self) -> float:
        """计算可用率"""
        total = self.successes + self.failures
        if total == 0:
            return 1.0
        return self.successes / total

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'priority': self.priority,
            'status': self.status.value,
            'avg_latency_ms': round(self.avg_latency_ms, 1),
            'availability': round(self.get_availability(), 3),
            'consecutive_failures': self.consecutive_failures,
            'total_requests': self.total_requests,
            'last_error': self.last_error,
            'last_check': self.last_check,
        }


class DataSourceManager:
    """
    数据源管理器

    职责：
    1. 注册数据源及其优先级
    2. 自动健康检测
    3. 故障时自动降级/切换备用数据源
    4. 恢复时自动切回主数据源
    5. 提供状态快照供前端轮询
    """

    def __init__(self):
        self.sources: Dict[str, DataSourceHealth] = {}
        self.providers: Dict[str, Callable] = {}
        self.active_source: Optional[str] = None

        # 阈值配置
        self.degraded_latency_ms = 5000     # 延迟超过 5s 触发降级
        self.fallback_failures = 3           # 连续 3 次失败触发回退
        self.auto_recovery_successes = 3      # 连续 3 次成功自动恢复
        self.health_check_interval = 60       # 健康检查间隔（秒）

        self._last_health_check = 0.0

    # ==================== 注册 ====================

    def register_source(self, name: str, provider: Callable, priority: int = 0):
        """
        注册数据源

        Args:
            name: 数据源唯一标识（如 'tushare', 'akshare'）
            provider: 数据获取函数，签名: provider(endpoint, params) → Any
            priority: 优先级（数字越小越优先）
        """
        if name not in self.sources:
            self.sources[name] = DataSourceHealth(name, priority)
            self.providers[name] = provider
            logger.info(f"数据源 {name} 已注册 (priority={priority})")

        # 首个注册的作为活跃源
        if self.active_source is None:
            self.active_source = name

        # 按优先级重新排序活跃源
        self._update_active_source()

    def _update_active_source(self):
        """按优先级 + 健康状态选择活跃数据源"""
        available = [
            (name, health)
            for name, health in self.sources.items()
            if health.status != DataSourceStatus.UNAVAILABLE
        ]

        if not available:
            self.active_source = None
            logger.warning("无可用数据源")
            return

        # 按优先级排序，同优先级按可用率排序
        available.sort(key=lambda x: (x[1].priority, -x[1].get_availability()))

        new_active = available[0][0]
        if new_active != self.active_source:
            old = self.active_source
            self.active_source = new_active
            logger.info(f"活跃数据源切换: {old} → {new_active}")

    # ==================== 健康检查 ====================

    def check_health(self, force: bool = False):
        """
        执行健康检查（频率控制）

        Args:
            force: 是否强制检查（忽略间隔）
        """
        now = time.time()
        if not force and (now - self._last_health_check) < self.health_check_interval:
            return

        self._last_health_check = now

        for name, health in self.sources.items():
            provider = self.providers.get(name)
            if provider is None:
                continue

            try:
                t0 = time.time()
                # 发送轻量 ping 检测
                result = provider('health_check', {})
                latency = (time.time() - t0) * 1000

                if result is not None:
                    health.record_success(latency)

                    if latency > self.degraded_latency_ms:
                        health.status = DataSourceStatus.DEGRADED
                        logger.warning(f"数据源 {name} 延迟过高: {latency:.0f}ms")
                else:
                    health.record_failure("健康检查返回空")
            except Exception as e:
                health.record_failure(str(e))
                logger.warning(f"数据源 {name} 健康检查失败: {e}")

            # 检查是否触发降级
            self._evaluate_status(name, health)

        self._update_active_source()

    def _evaluate_status(self, name: str, health: DataSourceHealth):
        """评估数据源状态"""
        # 不可用：连续失败超阈值且无法恢复
        if health.consecutive_failures >= self.fallback_failures * 2:
            if health.status != DataSourceStatus.UNAVAILABLE:
                health.status = DataSourceStatus.UNAVAILABLE
                logger.error(f"数据源 {name} 不可用")
            return

        # 回退：连续失败超阈值
        if health.consecutive_failures >= self.fallback_failures:
            if health.status != DataSourceStatus.FALLBACK:
                health.status = DataSourceStatus.FALLBACK
                logger.warning(f"数据源 {name} 触发回退")
            return

        # 降级：延迟过高
        if health.avg_latency_ms > self.degraded_latency_ms:
            if health.status == DataSourceStatus.NORMAL:
                health.status = DataSourceStatus.DEGRADED
                logger.warning(f"数据源 {name} 降级")
            return

    # ==================== 数据获取 ====================

    def get_data(self, endpoint: str, params: Dict = None) -> Any:
        """
        获取数据 — 自动降级与回退

        Args:
            endpoint: API 端点标识
            params: 请求参数

        Returns:
            数据结果

        Raises:
            RuntimeError: 无可用数据源
        """
        self.check_health()

        if self.active_source is None:
            # 尝试任何可用源
            for name in self.sources:
                if self.sources[name].status != DataSourceStatus.UNAVAILABLE:
                    self.active_source = name
                    break

        if self.active_source is None:
            raise RuntimeError("无可用数据源")

        provider = self.providers.get(self.active_source)
        if provider is None:
            raise RuntimeError(f"数据源 {self.active_source} 无 provider")

        health = self.sources[self.active_source]

        try:
            t0 = time.time()
            result = provider(endpoint, params or {})
            latency = (time.time() - t0) * 1000
            health.record_success(latency)
            self._evaluate_status(self.active_source, health)
            return result

        except Exception as e:
            health.record_failure(str(e))
            self._evaluate_status(self.active_source, health)

            # 触发回退
            if health.status in (DataSourceStatus.FALLBACK, DataSourceStatus.UNAVAILABLE):
                self._update_active_source()
                if self.active_source:
                    logger.info(f"自动切换至备用数据源: {self.active_source}")
                    return self.get_data(endpoint, params)

            raise

    # ==================== 状态查询 ====================

    def get_status_snapshot(self) -> Dict:
        """
        返回状态快照（供前端状态组件轮询）

        Returns:
            {
                'active': 'tushare',
                'timestamp': 1234567890,
                'sources': {
                    'tushare': { status, latency, failures, ... },
                    'akshare': { status, latency, failures, ... },
                }
            }
        """
        self.check_health()

        return {
            'active': self.active_source,
            'timestamp': time.time(),
            'sources': {
                name: health.to_dict()
                for name, health in self.sources.items()
            },
        }

    def get_source_status(self, name: str) -> Optional[str]:
        """获取指定数据源的状态"""
        health = self.sources.get(name)
        return health.status.value if health else None

    def get_active_source_name(self) -> Optional[str]:
        """获取当前活跃数据源名称"""
        return self.active_source

    def reset_source(self, name: str):
        """重置数据源状态"""
        health = self.sources.get(name)
        if health:
            health.status = DataSourceStatus.NORMAL
            health.consecutive_failures = 0
            health.failures = 0
            health.last_error = None
            logger.info(f"数据源 {name} 已重置")
            self._update_active_source()

    def reset_all(self):
        """重置所有数据源"""
        for name in self.sources:
            self.reset_source(name)
        self._update_active_source()

    def get_stats(self) -> Dict:
        """获取全局统计"""
        total_requests = sum(h.total_requests for h in self.sources.values())
        total_failures = sum(h.failures for h in self.sources.values())
        return {
            'total_requests': total_requests,
            'total_failures': total_failures,
            'overall_availability': round(
                (total_requests - total_failures) / max(total_requests, 1), 3
            ),
            'source_count': len(self.sources),
            'active_source': self.active_source,
        }


# 全局单例
data_source_manager = DataSourceManager()
