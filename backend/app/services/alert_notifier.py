"""
告警通知服务

提供轻量级告警分发机制，当前支持日志输出和文件记录。
设计上支持扩展 webhook / email 等渠道。

用法:
    from app.services.alert_notifier import AlertNotifier
    notifier = AlertNotifier()
    notifier.send("LOW_WIN_RATE", "量价策略", "5日胜率跌破40%", severity="WARN")
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class AlertNotifier:
    """告警通知器 — 记录告警到日志和文件，预留 webhook/email 扩展点"""

    def __init__(self, alert_log_dir: Optional[str] = None):
        log_dir = alert_log_dir or os.environ.get(
            'ALERT_LOG_DIR',
            os.path.join(os.environ.get('DATA_DIR', '/data'), 'alerts')
        )
        os.makedirs(log_dir, exist_ok=True)
        self.alert_log = os.path.join(log_dir, 'alerts.jsonl')

    def send(
        self,
        alert_type: str,
        source: str,
        message: str,
        severity: str = 'WARN',
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        发送告警。

        Args:
            alert_type: 告警类型标识 (如 LOW_WIN_RATE, DATA_STALL)
            source:     告警来源 (如 策略名称 / 模块名)
            message:    告警正文
            severity:   严重级别 (INFO / WARN / ALERT / CRITICAL)
            metadata:   附加结构数据

        Returns:
            告警记录字典
        """
        record = {
            'timestamp': datetime.now().isoformat(),
            'type': alert_type,
            'source': source,
            'severity': severity,
            'message': message,
            'metadata': metadata or {},
        }

        # 1. 写 JSONL 日志文件（可作为 Prometheus / 日志采集的输入源）
        try:
            with open(self.alert_log, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except OSError as e:
            logger.error(f"写告警日志失败: {e}")

        # 2. Python logging（进入应用日志轮转体系）
        log_msg = f"[{severity}] {source}: {message}"
        if severity == 'CRITICAL':
            logger.critical(log_msg)
        elif severity == 'ALERT':
            logger.error(log_msg)
        elif severity == 'WARN':
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # 3. 预留扩展: webhook / email / 企业微信 / Slack
        # self._dispatch_webhook(record)
        # self._dispatch_email(record)

        return record

    # --- 扩展预留 ---
    # def _dispatch_webhook(self, record: dict): ...
    # def _dispatch_email(self, record: dict): ...
