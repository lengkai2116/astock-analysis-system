"""
监控告警管理器（355号方案规则16-18）
===================================
提供数据采集、存储、读写的监控和告警功能。

监控指标：
1. 数据采集成功率
2. 数据格式一致率
3. 数据时效性达标率
4. 数据源可用率
5. WAL文件大小
6. 锁冲突次数
"""

import logging
import os
import threading
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)


class AlertLevel:
    """告警级别"""
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'


class Monitor:
    """监控告警管理器"""

    def __init__(self):
        self._metrics: Dict[str, Dict] = {}
        self._alerts: List[Dict] = []
        self._alert_callbacks: List[callable] = []
        self._lock = threading.Lock()
        # 500号#28：告警 ID 单调计数器（原 len(_alerts)+1，裁剪至 100 条后新 ID 与存活
        # 告警碰撞 → acknowledge_alert(id) 可能确认无关告警）
        self._alert_seq = 0

    def record_metric(self, metric_name: str, value: float, tags: Dict = None):
        """记录监控指标

        Args:
            metric_name: 指标名称
            value: 指标值
            tags: 标签（可选）
        """
        with self._lock:
            if metric_name not in self._metrics:
                self._metrics[metric_name] = {
                    'values': [],
                    'last_update': datetime.now()
                }

            self._metrics[metric_name]['values'].append({
                'value': value,
                'timestamp': datetime.now(),
                'tags': tags or {}
            })

            # 保留最近1000条记录
            if len(self._metrics[metric_name]['values']) > 1000:
                self._metrics[metric_name]['values'] = \
                    self._metrics[metric_name]['values'][-1000:]

            self._metrics[metric_name]['last_update'] = datetime.now()

    def create_alert(self, level: str, title: str, message: str,
                    source: str = None, metrics: Dict = None):
        """创建告警

        Args:
            level: 告警级别（INFO/WARNING/ERROR/CRITICAL）
            title: 告警标题
            message: 告警信息
            source: 告警来源
            metrics: 相关指标
        """
        with self._lock:
            self._alert_seq += 1
            alert = {
                'id': self._alert_seq,
                'level': level,
                'title': title,
                'message': message,
                'source': source,
                'metrics': metrics or {},
                'timestamp': datetime.now(),
                'acknowledged': False
            }
            self._alerts.append(alert)
            # 保留最近100条告警
            if len(self._alerts) > 100:
                self._alerts = self._alerts[-100:]

        # 记录日志（500号#30：未知/None 级别不再静默降为 INFO，回退 warning）
        _lvl = (level or '').lower()
        log_func = getattr(logger, _lvl, None)
        if not callable(log_func):
            logger.warning(f"未知告警级别 {level!r}，按 warning 记录")
            log_func = logger.warning
        log_func(f"[{level}] {title}: {message}")

        # 触发回调（500号#29：持锁快照回调列表，避免并发 register 改动列表时迭代异常）
        with self._lock:
            _callbacks = list(self._alert_callbacks)
        for callback in _callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.warning(f"告警回调执行失败: {e}")

    def register_alert_callback(self, callback: callable):
        """注册告警回调函数（500号#29：持锁）"""
        with self._lock:
            self._alert_callbacks.append(callback)

    def get_metric_stats(self, metric_name: str) -> Dict:
        """获取指标统计信息（500号#29：持锁读取快照）"""
        with self._lock:
            _metric = self._metrics.get(metric_name)
            if _metric is None:
                return {}
            values = [v['value'] for v in _metric['values']]
            last_update = _metric['last_update']
        if not values:
            return {}

        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'avg': sum(values) / len(values),
            'last': values[-1],
            'last_update': last_update.isoformat()
        }

    def get_alerts(self, level: str = None, limit: int = 50) -> List[Dict]:
        """获取告警列表（500号#29：持锁快照，避免读到整体替换中的列表）"""
        with self._lock:
            alerts = list(self._alerts)
        if level:
            alerts = [a for a in alerts if a['level'] == level]
        return alerts[-limit:]

    def acknowledge_alert(self, alert_id: int):
        """确认告警（500号#29：持锁）"""
        with self._lock:
            for alert in self._alerts:
                if alert['id'] == alert_id:
                    alert['acknowledged'] = True
                    break

    def check_wal_size(self, db_path: str, threshold_mb: int = 2048):
        """检查WAL文件大小（355号方案规则16）"""
        wal_path = db_path + '-wal'
        try:
            if os.path.exists(wal_path):
                wal_size_mb = os.path.getsize(wal_path) / 1024 / 1024
                self.record_metric('wal_size_mb', wal_size_mb)

                if wal_size_mb > threshold_mb:
                    self.create_alert(
                        AlertLevel.WARNING,
                        'WAL文件过大',
                        f'WAL文件大小 {wal_size_mb:.0f}MB 超过阈值 {threshold_mb}MB',
                        source='wal_monitor',
                        metrics={'wal_size_mb': wal_size_mb}
                    )
        except Exception as e:
            logger.warning(f"检查WAL文件大小失败: {e}")

    def check_lock_conflicts(self, conflict_count: int, threshold: int = 10):
        """检查锁冲突次数（355号方案规则17）"""
        self.record_metric('lock_conflict_count', conflict_count)

        if conflict_count > threshold:
            self.create_alert(
                AlertLevel.WARNING,
                '锁冲突频繁',
                f'锁冲突次数 {conflict_count} 超过阈值 {threshold}',
                source='lock_monitor',
                metrics={'conflict_count': conflict_count}
            )

    def check_data_quality(self, table_name: str, anomaly_count: int, threshold: int = 0):
        """检查数据质量（355号方案规则18）"""
        self.record_metric(f'{table_name}_anomaly_count', anomaly_count)

        if anomaly_count > threshold:
            self.create_alert(
                AlertLevel.WARNING,
                '数据质量异常',
                f'表 {table_name} 异常记录数 {anomaly_count}',
                source='data_quality_monitor',
                metrics={'table': table_name, 'anomaly_count': anomaly_count}
            )


# 全局单例
monitor = Monitor()


def init_monitoring():
    """初始化监控系统"""
    # 注册告警回调（可以扩展为发送邮件、Slack通知等）
    def log_alert_callback(alert):
        logger.info(f"告警触发: [{alert['level']}] {alert['title']}")

    monitor.register_alert_callback(log_alert_callback)

    logger.info("监控系统初始化完成")
