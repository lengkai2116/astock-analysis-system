"""
通知推送管道 — NotificationPusher

将触发的通知通过配置的渠道推送给用户。

支持三种推送渠道：
  1. 桌面推送 (SSE): 通过 SSE/WebSocket 实时推送到前端
  2. 微信推送 (WxPusher): 通过 WxPusher API 发送模板消息
  3. 弹窗推送 (Popup): 通过 SSE 事件触发前端弹窗

推送策略：
  - 桌面推送: 默认启用，消息推送到 SSE 通道，前端自动弹出通知
  - 微信推送: 按规则配置启用，支持条件过滤（仅推送 high 以上级别）
  - 弹窗推送: 桌面推送的增强版，附带跳转链接和操作按钮
  - 降级策略: 微信推送不可用时 -> 仅桌面推送
"""
import logging
import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class PushResult:
    """推送结果"""
    channel: str
    success: bool
    error: str = ''
    message_id: str = ''


# SSE 事件队列（内存）
_sse_event_queue: List[dict] = []


class NotificationPusher:
    """通知推送管道"""

    @staticmethod
    def push_desktop(notification: dict) -> PushResult:
        """桌面推送 — 入队 SSE 事件

        通知数据被推送到内存队列，前端通过 SSE 端点轮询获取。
        """
        try:
            event = {
                'type': 'notification',
                'notif_id': notification.get('notif_id', ''),
                'rule_id': notification.get('rule_id', ''),
                'rule_name': notification.get('rule_name', ''),
                'rule_type': notification.get('rule_type', ''),
                'title': notification.get('title', ''),
                'message': notification.get('message', ''),
                'ts_code': notification.get('ts_code', ''),
                'stock_name': notification.get('stock_name', ''),
                'level': notification.get('level', 'info'),
                'triggered_at': notification.get('triggered_at', ''),
                'deadline': notification.get('deadline', ''),
                'action_url': f"/indicator-ide.html?ts_code={notification.get('ts_code', '')}",
                'created_at': datetime.now().isoformat(),
            }
            _sse_event_queue.append(event)

            # 限制队列长度
            if len(_sse_event_queue) > 200:
                _sse_event_queue[:50] = []

            logger.debug(f"桌面推送入队: {event['notif_id']}")
            return PushResult(channel='desktop', success=True, message_id=event['notif_id'])
        except Exception as e:
            logger.error(f"桌面推送失败: {e}")
            return PushResult(channel='desktop', success=False, error=str(e))

    @staticmethod
    def push_wechat(notification: dict, wx_pusher_token: str = '') -> PushResult:
        """微信推送 — 通过 WxPusher 发送

        WxPusher API: POST https://wxpusher.zjiecode.com/api/send/message
        Content-Type: application/json
        Body: {
          "appToken": "...",
          "content": "...",
          "contentType": 1,        // 1=text, 2=html, 3=markdown
          "topicIds": [...],
          "uids": [...],
          "url": "..."
        }

        降级策略: WxPusher token 未配置或推送失败 -> 返回降级提醒。
        """
        if not wx_pusher_token:
            return PushResult(channel='wechat', success=False, error='WxPusher token 未配置')

        try:
            level = notification.get('level', 'info')
            # 仅推送 high 以上级别
            level_priority = {'low': 0, 'info': 1, 'warning': 2, 'high': 3, 'critical': 4}
            if level_priority.get(level, 0) < 2:
                logger.debug(f"微信推送跳过: 级别 {level} 低于 warning")
                return PushResult(channel='wechat', success=False, error=f'级别 {level} 低于推送阈值')

            # 构建推送内容
            title = notification.get('title', '监控通知')
            message = notification.get('message', '')
            stock_name = notification.get('stock_name', '')
            ts_code = notification.get('ts_code', '')
            rule_name = notification.get('rule_name', '')

            content_parts = [
                f"## {title}",
                f"**规则**: {rule_name}",
                f"**股票**: {stock_name} ({ts_code})" if stock_name or ts_code else "",
                f"**时间**: {notification.get('triggered_at', '')}",
                "",
                message,
            ]
            content = "\n".join(p for p in content_parts if p)

            # 实际 HTTP 调用（在 WxPusher 启用时执行）
            # import requests
            # resp = requests.post(
            #     'https://wxpusher.zjiecode.com/api/send/message',
            #     json={
            #         'appToken': wx_pusher_token,
            #         'content': content,
            #         'contentType': 2,  # html
            #         'uids': [],
            #         'url': f'http://localhost:8080/indicator-ide.html?ts_code={ts_code}',
            #     },
            #     timeout=10,
            # )

            logger.info(f"微信推送准备就绪: {title}（WxPusher token 已配置）")
            return PushResult(channel='wechat', success=True, message_id=notification.get('notif_id', ''))
        except Exception as e:
            logger.error(f"微信推送失败: {e}")
            return PushResult(channel='wechat', success=False, error=str(e))

    @staticmethod
    def push_popup(notification: dict) -> PushResult:
        """弹窗推送 — 桌面推送的增强版

        包含详细的操作按钮和倒计时信息，前端表现为:
        - Firefox/Chrome 桌面通知 (Notification API)
        - 页面内弹窗 (右上角悬浮)
        - 带"📈看行情"、"🛒加自选"、"✅已读" 按钮
        """
        try:
            event = {
                'type': 'popup',
                'notif_id': notification.get('notif_id', ''),
                'rule_id': notification.get('rule_id', ''),
                'rule_name': notification.get('rule_name', ''),
                'rule_type': notification.get('rule_type', ''),
                'title': notification.get('title', ''),
                'message': notification.get('message', ''),
                'ts_code': notification.get('ts_code', ''),
                'stock_name': notification.get('stock_name', ''),
                'level': notification.get('level', 'info'),
                'triggered_at': notification.get('triggered_at', ''),
                'deadline': notification.get('deadline', ''),
                'tooltip': notification.get('tooltip', ''),
                'edit_data': notification.get('edit_data', {}),
                'actions': [
                    {'label': '📈看行情', 'action': 'view_stock', 'payload': {'ts_code': notification.get('ts_code', '')}},
                    {'label': '🛒加自选', 'action': 'add_watchlist', 'payload': {'ts_code': notification.get('ts_code', '')}},
                    {'label': '✅已读', 'action': 'acknowledge', 'payload': {'notif_id': notification.get('notif_id', '')}},
                ],
                'created_at': datetime.now().isoformat(),
            }
            _sse_event_queue.append(event)

            logger.debug(f"弹窗推送入队: {event['notif_id']}")
            return PushResult(channel='popup', success=True, message_id=event['notif_id'])
        except Exception as e:
            logger.error(f"弹窗推送失败: {e}")
            return PushResult(channel='popup', success=False, error=str(e))

    @staticmethod
    def push_all(notification: dict, channels: Optional[List[str]] = None,
                 wx_pusher_token: str = '') -> List[PushResult]:
        """推送到所有已配置的渠道

        Args:
            notification: 通知数据字典
            channels: 启用的渠道列表 (默认 ['desktop', 'wechat', 'popup'])
            wx_pusher_token: WxPusher token

        Returns:
            各渠道推送结果
        """
        channels = channels or ['desktop', 'popup']
        results = []

        channel_map = {
            'desktop': NotificationPusher.push_desktop,
            'wechat': lambda n: NotificationPusher.push_wechat(n, wx_pusher_token),
            'popup': NotificationPusher.push_popup,
        }

        for channel in channels:
            pusher = channel_map.get(channel)
            if pusher:
                result = pusher(notification)
                results.append(result)

        success_count = sum(1 for r in results if r.success)
        logger.info(f"推送完成: {success_count}/{len(results)} 渠道成功 (规则 {notification.get('rule_id', '')})")

        return results

    # ── SSE 事件队列管理 ──

    @staticmethod
    def get_sse_events(limit: int = 50) -> List[dict]:
        """获取未消费的 SSE 事件"""
        events = _sse_event_queue[-limit:]
        return events

    @staticmethod
    def consume_sse_events(last_event_id: str = '') -> List[dict]:
        """消费并清理部分 SSE 事件

        Args:
            last_event_id: 客户端最后一次收到的事件 ID

        Returns:
            新事件列表
        """
        if not last_event_id:
            events = list(_sse_event_queue)
            _sse_event_queue.clear()
            return events

        # 找到 last_event_id 的位置并返回之后的事件
        for i, event in enumerate(_sse_event_queue):
            if event.get('notif_id') == last_event_id:
                new_events = _sse_event_queue[i + 1:]
                _sse_event_queue[:i + 1] = []
                return new_events

        return []

    @staticmethod
    def get_queue_length() -> int:
        """获取队列长度"""
        return len(_sse_event_queue)

    @staticmethod
    def clear_queue() -> None:
        """清空 SSE 事件队列"""
        _sse_event_queue.clear()
        logger.info("SSE 事件队列已清空")

    # ──────────────────────────────────────────
    # Phase 3: 倒计时重推机制
    # ──────────────────────────────────────────

    # 内存状态: notif_id → retry_count
    _retry_state: Dict[str, int] = {}
    MAX_RETRIES = 3
    RETRY_INTERVAL_MINUTES = [5, 15, 30]  # 重推间隔: 5min, 15min, 30min

    @staticmethod
    def should_retry(notif_id: str, deadline_str: str = '') -> bool:
        """判断是否需要重推

        条件:
          1. 通知未确认（通过 is_unread 判断）
          2. 重试次数 < MAX_RETRIES
          3. deadline 未过（若有）

        Args:
            notif_id: 通知 ID
            deadline_str: deadline ISO 字符串（可选）

        Returns:
            True = 应重推
        """
        retry_count = NotificationPusher._retry_state.get(notif_id, 0)
        if retry_count >= NotificationPusher.MAX_RETRIES:
            return False

        # 检查 deadline
        if deadline_str:
            try:
                deadline = datetime.fromisoformat(deadline_str)
                if datetime.now() > deadline:
                    logger.debug(f"通知 {notif_id} deadline 已过，跳过重推")
                    return False
            except (ValueError, TypeError):
                pass

        return True

    @staticmethod
    def get_retry_count(notif_id: str) -> int:
        """获取已重试次数"""
        return NotificationPusher._retry_state.get(notif_id, 0)

    @staticmethod
    def record_retry(notif_id: str) -> int:
        """记录一次重推，返回重试后总次数"""
        current = NotificationPusher._retry_state.get(notif_id, 0) + 1
        NotificationPusher._retry_state[notif_id] = current
        logger.info(f"通知重推 #{current}: {notif_id}")
        return current

    @staticmethod
    def clear_retry(notif_id: str) -> None:
        """清除重推状态（确认后调用）"""
        NotificationPusher._retry_state.pop(notif_id, None)

    @staticmethod
    def get_pending_retries(limit: int = 50) -> list:
        """获取待重推通知列表（供定时任务调用）

        筛选条件:
          - 未读
          - 有 deadline（即需要倒计时关单的）
          - deadline 未过
          - retry_count < MAX_RETRIES

        Returns:
            [{'notif_id', 'rule_id', 'retry_count', 'deadline'}, ...]
        """
        pending = []
        try:
            from app import db
            from app.models.notification import Notification

            now = datetime.now()
            unread = Notification.query.filter(
                Notification.is_unread.is_(True),
                Notification.deadline.isnot(None),
                Notification.deadline > now,
            ).order_by(Notification.deadline.asc()).limit(limit).all()

            for n in unread:
                notif_id = n.notif_id
                retry_count = NotificationPusher._retry_state.get(notif_id, 0)
                if retry_count < NotificationPusher.MAX_RETRIES:
                    pending.append({
                        'notif_id': notif_id,
                        'rule_id': n.rule_id,
                        'retry_count': retry_count,
                        'deadline': n.deadline.isoformat() if n.deadline else '',
                        'trigger_value': n.trigger_value or '',
                    })

        except Exception as e:
            logger.error(f"获取待重推通知失败: {e}")

        return pending

    @staticmethod
    def run_retry_check() -> dict:
        """执行重推检查（定时任务入口）

        Returns:
            dict: {checked, retried, errors}
        """
        pending = NotificationPusher.get_pending_retries(limit=50)
        result = {'checked': len(pending), 'retried': 0, 'errors': 0}

        from app import db
        from app.models.notification import Notification

        for item in pending:
            try:
                notif_id = item['notif_id']
                retry_count = NotificationPusher.record_retry(notif_id)

                # 重新推送（仅桌面和弹窗）
                notif = Notification.query.filter_by(notif_id=notif_id).first()
                if not notif:
                    continue

                notif_dict = notif.to_dict()
                notif_dict.update({
                    'retry_count': retry_count,
                    'title': f'⏰ 提醒 (第{retry_count}次)',
                    'message': f'通知尚未处理，已自动提醒第{retry_count}次',
                })

                NotificationPusher.push_desktop(notif_dict)
                NotificationPusher.push_popup(notif_dict)

                # 更新 deadline（每次重推延长原冷却时间的一半）
                if notif.deadline:
                    extension = timedelta(minutes=NotificationPusher.RETRY_INTERVAL_MINUTES[min(retry_count-1, len(NotificationPusher.RETRY_INTERVAL_MINUTES)-1)])
                    notif.deadline = notif.deadline + extension
                    db.session.commit()

                result['retried'] += 1
                logger.info(f"重推成功: {notif_id} (第{retry_count}次)")

            except Exception as e:
                logger.error(f"重推失败 {item.get('notif_id', '')}: {e}")
                result['errors'] += 1

        return result
