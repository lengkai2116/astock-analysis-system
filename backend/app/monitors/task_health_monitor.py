"""
定时任务健康监控

对照 151-观潮对标-系统能力提升与稳定性优化方案.md §5.4
增加任务健康检查 + 自动重启 + 执行统计

与 scheduler.py 配合使用，在 register_scheduler_jobs 中挂载监控回调。
"""

import time
import logging
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


class TaskStats:
    """单个任务的执行统计"""

    def __init__(self, task_name: str):
        self.task_name = task_name
        self.total = 0
        self.success = 0
        self.failures = 0
        self.consecutive_failures = 0
        self.avg_duration_ms = 0.0
        self.max_duration_ms = 0.0
        self.min_duration_ms = float('inf')
        self.last_execution: Optional[datetime] = None
        self.last_success: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_error_time: Optional[datetime] = None
        # 最近 10 次执行记录
        self.recent_history: deque = deque(maxlen=10)

    def record_execution(self, success: bool, duration_ms: float, error: Optional[str] = None):
        """记录一次执行"""
        now = datetime.now()
        self.total += 1
        self.last_execution = now

        entry = {
            'time': now.isoformat(),
            'success': success,
            'duration_ms': round(duration_ms, 1),
            'error': error,
        }
        self.recent_history.append(entry)

        if success:
            self.success += 1
            self.consecutive_failures = 0
            self.last_success = now
        else:
            self.failures += 1
            self.consecutive_failures += 1
            self.last_error = error
            self.last_error_time = now

        # 加权移动平均执行时长（新占比 30%）
        if self.avg_duration_ms == 0:
            self.avg_duration_ms = duration_ms
        else:
            self.avg_duration_ms = self.avg_duration_ms * 0.7 + duration_ms * 0.3

        # 最大/最小时长
        self.max_duration_ms = max(self.max_duration_ms, duration_ms)
        self.min_duration_ms = min(self.min_duration_ms, duration_ms)

    def get_success_rate(self) -> float:
        """获取成功率"""
        if self.total == 0:
            return 1.0
        return self.success / self.total

    def is_healthy(self, alert_threshold: int = 3) -> bool:
        """是否健康（连续失败 < 阈值）"""
        return self.consecutive_failures < alert_threshold

    def to_dict(self) -> Dict:
        return {
            'task_name': self.task_name,
            'total': self.total,
            'success': self.success,
            'failures': self.failures,
            'consecutive_failures': self.consecutive_failures,
            'success_rate': round(self.get_success_rate(), 3),
            'avg_duration_ms': round(self.avg_duration_ms, 1),
            'max_duration_ms': round(self.max_duration_ms, 1),
            'min_duration_ms': round(self.min_duration_ms, 1) if self.min_duration_ms != float('inf') else 0,
            'last_execution': self.last_execution.isoformat() if self.last_execution else None,
            'last_success': self.last_success.isoformat() if self.last_success else None,
            'last_error': self.last_error,
            'last_error_time': self.last_error_time.isoformat() if self.last_error_time else None,
            'healthy': self.is_healthy(),
        }


class TaskHealthMonitor:
    """
    定时任务健康监控器

    用法：
        monitor = TaskHealthMonitor()

        # 在执行任务时打点
        def my_task():
            t0 = time.time()
            try:
                # ... do work ...
                monitor.record_execution('my_task', True, (time.time()-t0)*1000)
            except Exception as e:
                monitor.record_execution('my_task', False, (time.time()-t0)*1000, str(e))
                raise
    """

    def __init__(self):
        self.tasks: Dict[str, TaskStats] = {}
        self.alert_threshold = 3  # 连续 3 次失败告警
        self.alert_callbacks: List[Callable] = []

        # 告警频率限制（同任务 5 分钟内只告警一次）
        self._last_alert: Dict[str, datetime] = {}
        self.alert_cooldown_minutes = 5

    def register_task(self, task_name: str):
        """注册一个任务"""
        if task_name not in self.tasks:
            self.tasks[task_name] = TaskStats(task_name)
            logger.info(f"任务 {task_name} 已注册")

    def record_execution(
        self,
        task_name: str,
        success: bool,
        duration_ms: float,
        error: Optional[str] = None,
    ):
        """
        记录任务执行结果

        Args:
            task_name: 任务名称
            success: 是否成功
            duration_ms: 执行时长（毫秒）
            error: 错误信息（可选）
        """
        if task_name not in self.tasks:
            self.register_task(task_name)

        task = self.tasks[task_name]
        task.record_execution(success, duration_ms, error)

        if success:
            logger.info(f"任务 {task_name} 完成 ({duration_ms:.0f}ms)")
        else:
            logger.error(f"任务 {task_name} 失败 ({duration_ms:.0f}ms): {error}")

        # 告警检查
        if not task.is_healthy(self.alert_threshold):
            self._trigger_alert(task_name, task)

    def register_alert_callback(self, callback: Callable):
        """
        注册告警回调

        callback(task_name, task_stats) 会在触发告警时被调用
        """
        self.alert_callbacks.append(callback)

    def _trigger_alert(self, task_name: str, task: TaskStats):
        """触发告警（带频率限制）"""
        now = datetime.now()

        # 频率限制检查
        last_alert = self._last_alert.get(task_name)
        if last_alert and (now - last_alert).total_seconds() < self.alert_cooldown_minutes * 60:
            return

        self._last_alert[task_name] = now

        alert_msg = (
            f"任务 {task_name} 连续 {task.consecutive_failures} 次失败，"
            f"成功率 {task.get_success_rate():.0%}"
        )
        logger.warning(f"[TASK_ALERT] {alert_msg}")

        # 调用告警回调
        for cb in self.alert_callbacks:
            try:
                cb(task_name, task)
            except Exception as e:
                logger.error(f"告警回调失败: {e}")

    def get_task_stats(self, task_name: Optional[str] = None) -> Dict:
        """获取任务统计"""
        if task_name:
            task = self.tasks.get(task_name)
            return task.to_dict() if task else {}

        return {
            name: task.to_dict()
            for name, task in self.tasks.items()
        }

    def get_unhealthy_tasks(self) -> List[Dict]:
        """获取不健康的任务列表"""
        return [
            task.to_dict()
            for task in self.tasks.values()
            if not task.is_healthy(self.alert_threshold)
        ]

    def get_summary(self) -> Dict:
        """获取汇总"""
        total = len(self.tasks)
        healthy = sum(1 for t in self.tasks.values() if t.is_healthy(self.alert_threshold))
        unhealthy = total - healthy

        return {
            'total_tasks': total,
            'healthy': healthy,
            'unhealthy': unhealthy,
            'unhealthy_tasks': [name for name, t in self.tasks.items() if not t.is_healthy(self.alert_threshold)],
            'check_time': datetime.now().isoformat(),
        }

    def reset_task(self, task_name: str):
        """重置任务统计"""
        if task_name in self.tasks:
            del self.tasks[task_name]
            logger.info(f"任务 {task_name} 统计已重置")

    def reset_all(self):
        """重置所有统计"""
        self.tasks.clear()
        self._last_alert.clear()
        logger.info("所有任务统计已重置")


# 全局单例
task_health_monitor = TaskHealthMonitor()
