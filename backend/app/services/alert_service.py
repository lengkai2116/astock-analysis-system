"""
AlertService — 告警通知服务
============================
实现: 数据监控/策略健康监控的告警推送渠道

支持:
- 邮件通知 (SMTP)
- Webhook (企业微信/DingTalk/Slack 兼容)
- 日志告警（本地记录）
"""

import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class AlertService:
    """
    告警通知服务

    使用方式:
        alert = AlertService()
        alert.send('策略胜率异常下降', 'chanlun策略5日胜率降至0.35',
                    level='warning', source='strategy_health')
    """

    # 告警等级
    LEVELS = {
        'info': '🔵',
        'warning': '🟡',
        'critical': '🔴',
    }

    def __init__(self):
        self._email_config = self._load_email_config()
        self._webhook_url = os.environ.get('ALERT_WEBHOOK_URL', '')
        self._alert_log: List[Dict] = []

    def _load_email_config(self) -> Optional[Dict]:
        """加载邮件配置"""
        smtp_host = os.environ.get('ALERT_SMTP_HOST', '')
        smtp_port = os.environ.get('ALERT_SMTP_PORT', '587')
        smtp_user = os.environ.get('ALERT_SMTP_USER', '')
        smtp_pass = os.environ.get('ALERT_SMTP_PASS', '')
        notify_to = os.environ.get('ALERT_NOTIFY_TO', '')

        if smtp_host and smtp_user and smtp_pass and notify_to:
            return {
                'host': smtp_host,
                'port': int(smtp_port),
                'user': smtp_user,
                'password': smtp_pass,
                'to': notify_to,
                'from': smtp_user,
            }
        return None

    def send(self, title: str, message: str,
             level: str = 'info',
             source: str = 'system',
             data: Dict = None) -> bool:
        """
        发送告警

        Args:
            title: 告警标题
            message: 告警内容
            level: 等级 info/warning/critical
            source: 来源标识
            data: 附加数据

        Returns:
            是否成功
        """
        timestamp = datetime.now().isoformat()
        icon = self.LEVELS.get(level, '🔵')

        record = {
            'title': title,
            'message': message,
            'level': level,
            'source': source,
            'timestamp': timestamp,
            'data': data or {},
        }

        # 1. 本地日志记录
        log_msg = f"{icon} [{source}] {title}: {message}"
        if level == 'critical':
            logger.error(log_msg)
        elif level == 'warning':
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        self._alert_log.append(record)
        if len(self._alert_log) > 1000:
            self._alert_log = self._alert_log[-500:]

        # 2. 邮件通知
        email_ok = True
        if self._email_config:
            email_ok = self._send_email(title, message, level, source)

        # 3. Webhook 通知
        webhook_ok = True
        if self._webhook_url:
            webhook_ok = self._send_webhook(record)

        return email_ok and webhook_ok

    def _send_email(self, title: str, message: str,
                    level: str, source: str) -> bool:
        """发送邮件通知"""
        try:
            cfg = self._email_config
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[{level.upper()}] {title}"
            msg['From'] = cfg['from']
            msg['To'] = cfg['to']

            html = f"""<html><body>
<h2>{self.LEVELS.get(level, '')} {title}</h2>
<p><b>来源:</b> {source}</p>
<p><b>时间:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<hr/><pre>{message}</pre>
</body></html>"""
            msg.attach(MIMEText(html, 'html', 'utf-8'))

            with smtplib.SMTP(cfg['host'], cfg['port']) as server:
                server.starttls()
                server.login(cfg['user'], cfg['password'])
                server.send_message(msg)
            return True
        except Exception as e:
            logger.warning(f"邮件告警发送失败: {e}")
            return False

    def _send_webhook(self, record: Dict) -> bool:
        """发送 Webhook 通知"""
        try:
            import requests
            payload = {
                'msgtype': 'markdown',
                'markdown': {
                    'title': f"[{record['level'].upper()}] {record['title']}",
                    'text': (f"### {self.LEVELS.get(record['level'], '')} {record['title']}\n"
                             f"- **来源:** {record['source']}\n"
                             f"- **时间:** {record['timestamp']}\n"
                             f"- **详情:** {record['message']}\n"),
                },
            }
            resp = requests.post(self._webhook_url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Webhook 告警发送失败: {e}")
            return False

    def get_recent_alerts(self, limit: int = 20,
                          min_level: str = 'info') -> List[Dict]:
        """获取最近告警"""
        levels = {'info': 0, 'warning': 1, 'critical': 2}
        min_score = levels.get(min_level, 0)
        result = []
        for r in reversed(self._alert_log):
            if levels.get(r['level'], 0) >= min_score:
                result.append(r)
            if len(result) >= limit:
                break
        return result


# 全局实例
_alert_service = AlertService()


def get_alert_service() -> AlertService:
    return _alert_service


def alert(title: str, message: str, level: str = 'info', source: str = 'system'):
    """快捷函数"""
    return _alert_service.send(title, message, level, source)
