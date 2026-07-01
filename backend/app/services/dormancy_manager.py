"""
休眠管理 — DormancyManager

自动检测并处理长期未触发的规则。

三层休眠机制：
  L1 — 自动暂停 (30天): 连续 30 天无触发的规则，自动暂停
  L2 — 自动归档 (L1+14天): 暂停后 14 天用户未手动启用，归档
  L3 — 健康报告 (30天+): 归档后 30 天以上，生成健康报告

每个级别都通过数据库记录休眠历史，用户可随时恢复。
"""
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# 休眠配置常量
DORMANCY_L1_DAYS = 30      # 连续 N 天无触发 → L1 自动暂停
DORMANCY_L2_DAYS = 14      # 暂停后 N 天 → L2 归档
DORMANCY_L3_DAYS = 30      # 归档后 N 天 → L3 健康报告


class DormancyManager:
    """休眠管理器"""

    @staticmethod
    def check_l1_pause(rule, today_stats: Optional[dict] = None) -> bool:
        """L1 自动暂停检测

        判断规则是否应自动暂停:
          - 最近 N 天（DORMANCY_L1_DAYS）无触发记录
          - 规则状态为 running
          - 未处于手动暂停（status != paused）

        Returns:
            True = 已达到暂停条件
        """
        rule_dict = rule if isinstance(rule, dict) else getattr(rule, '__dict__', {})
        rule_id = rule_dict.get('rule_id', '')
        status = rule_dict.get('status', 'running')
        created_at = rule_dict.get('created_at', '')

        if status == 'paused':
            return False

        if not today_stats and created_at:
            # 尝试从数据库查询最近触发记录
            last_trigger = DormancyManager._get_last_trigger_date(rule_id)
            if last_trigger:
                days_since = (date.today() - last_trigger).days
                if days_since < DORMANCY_L1_DAYS:
                    return False

        # 检查 stats 中的 last_trigger
        stats = today_stats or {}
        days_since_trigger = stats.get('days_since_trigger', DORMANCY_L1_DAYS + 1)

        if isinstance(days_since_trigger, (int, float)):
            return days_since_trigger >= DORMANCY_L1_DAYS

        return False

    @staticmethod
    def check_l2_archive(rule) -> bool:
        """L2 归档检测

        判断已暂停的规则是否应归档:
          - 状态为 paused
          - 暂停时间超过 DORMANCY_L2_DAYS 天
          - 未被用户手动解除

        Returns:
            True = 已达到归档条件
        """
        rule_dict = rule if isinstance(rule, dict) else getattr(rule, '__dict__', {})
        rule_id = rule_dict.get('rule_id', '')
        status = rule_dict.get('status', '')
        paused_at = rule_dict.get('paused_at', rule_dict.get('updated_at', ''))

        if status != 'paused':
            return False

        # 从数据库获取暂停时间
        pause_date = DormancyManager._get_pause_date(rule_id)
        if not pause_date:
            return False

        days_since_pause = (date.today() - pause_date).days
        return days_since_pause >= DORMANCY_L2_DAYS

    @staticmethod
    def check_l3_health(rule) -> bool:
        """L3 健康报告检测

        判断已归档的规则是否应生成健康报告:
          - status 为归档状态或规则已软删除
          - 归档时间超过 DORMANCY_L3_DAYS 天

        Returns:
            True = 应生成健康报告
        """
        rule_dict = rule if isinstance(rule, dict) else getattr(rule, '__dict__', {})
        rule_id = rule_dict.get('rule_id', '')
        deleted_at = rule_dict.get('deleted_at', '')

        if not deleted_at:
            return False

        # 从数据库获取删除/归档时间
        archive_date = DormancyManager._get_archive_date(rule_id)
        if not archive_date:
            return False

        days_since_archive = (date.today() - archive_date).days
        return days_since_archive >= DORMANCY_L3_DAYS

    @staticmethod
    def execute_l1_pause(rule) -> bool:
        """执行 L1 暂停"""
        rule_id = rule if isinstance(rule, str) else (
            getattr(rule, 'rule_id', None) or (rule.get('rule_id', '') if isinstance(rule, dict) else '')
        )
        if not rule_id:
            return False

        try:
            from app.services.notification_service import update_rule
            update_rule(rule_id, {
                'status': 'paused',
                'paused_at': datetime.now().isoformat(),
                'pause_reason': f'L1自动暂停: 连续{DORMANCY_L1_DAYS}天无触发',
            })
            logger.info(f"L1 自动暂停: {rule_id}")
            return True
        except Exception as e:
            logger.error(f"L1 暂停失败 {rule_id}: {e}")
            return False

    @staticmethod
    def execute_l2_archive(rule) -> bool:
        """执行 L2 归档"""
        rule_id = rule if isinstance(rule, str) else (
            getattr(rule, 'rule_id', None) or (rule.get('rule_id', '') if isinstance(rule, dict) else '')
        )
        if not rule_id:
            return False

        try:
            from app.services.notification_service import update_rule
            update_rule(rule_id, {
                'status': 'archived',
                'archived_at': datetime.now().isoformat(),
                'archive_reason': f'L2自动归档: 暂停{DORMANCY_L2_DAYS}天未启用',
                'deleted_at': datetime.now().isoformat(),  # 软删除
            })
            logger.info(f"L2 自动归档: {rule_id}")
            return True
        except Exception as e:
            logger.error(f"L2 归档失败 {rule_id}: {e}")
            return False

    @staticmethod
    def execute_l3_health_report(rule) -> Optional[str]:
        """执行 L3 健康报告生成

        Returns:
            报告 ID（成功时）或 None（失败时）
        """
        rule_id = rule if isinstance(rule, str) else (
            getattr(rule, 'rule_id', None) or (rule.get('rule_id', '') if isinstance(rule, dict) else '')
        )
        rule_dict = rule if isinstance(rule, dict) else getattr(rule, '__dict__', {})

        if not rule_id:
            return None

        try:
            # 生成健康报告内容
            report_data = {
                'rule_id': rule_id,
                'rule_name': rule_dict.get('name', rule_dict.get('rule_name', '')),
                'rule_type': rule_dict.get('rule_type', rule_dict.get('type', '')),
                'status': rule_dict.get('status', ''),
                'created_at': rule_dict.get('created_at', ''),
                'paused_at': rule_dict.get('paused_at', ''),
                'archived_at': rule_dict.get('archived_at', ''),
                'days_inactive': DORMANCY_L1_DAYS + DORMANCY_L2_DAYS + DORMANCY_L3_DAYS,
                'health_status': 'inactive',
                'evaluated_at': datetime.now().isoformat(),
                'recommendation': '规则已长期未触发，建议检查条件配置是否合理或创建新的监控规则替代。',
            }

            # 推送到报告中心
            try:
                from app.routes.reports import create_report_entry
                report_id = create_report_entry({
                    'type': 'diagnosis',
                    'title': f'规则健康报告: {report_data["rule_name"]}',
                    'content': json.dumps(report_data, ensure_ascii=False),
                    'source': 'dormancy_manager',
                    'source_id': rule_id,
                })
                logger.info(f"L3 健康报告已生成: {report_id}")
                return report_id
            except Exception:
                # 报告中心不可用时，写入数据库
                from app import db
                from app.models.notification import ReportArchive
                report = ReportArchive(
                    rule_id=rule_id,
                    report_type='health_check',
                    content=json.dumps(report_data, ensure_ascii=False),
                    created_at=datetime.now(),
                )
                db.session.add(report)
                db.session.commit()
                logger.info(f"L3 健康报告已写入 DB: {rule_id}")
                return f"report-{rule_id}"

        except Exception as e:
            logger.error(f"L3 健康报告生成失败 {rule_id}: {e}")
            return None

    @staticmethod
    def _get_last_trigger_date(rule_id: str) -> Optional[date]:
        """从数据库查询规则最近触发日期"""
        try:
            from app import db
            from app.models.notification import NotificationRuleStats
            stats = NotificationRuleStats.query.filter_by(rule_id=rule_id).order_by(
                NotificationRuleStats.stat_date.desc()
            ).first()
            if stats and stats.last_trigger:
                return stats.last_trigger
        except Exception as e:
            logger.debug(f"查询触发日期失败 {rule_id}: {e}")
        return None

    @staticmethod
    def _get_pause_date(rule_id: str) -> Optional[date]:
        """查询暂停日期"""
        try:
            from app import db
            from app.models.notification import NotificationRule
            rule = NotificationRule.query.filter_by(rule_id=rule_id).first()
            if rule and rule.paused_at:
                if isinstance(rule.paused_at, str):
                    return datetime.fromisoformat(rule.paused_at).date()
                return rule.paused_at.date() if hasattr(rule.paused_at, 'date') else date.today()
        except Exception as e:
            logger.debug(f"查询暂停日期失败 {rule_id}: {e}")
        return None

    @staticmethod
    def _get_archive_date(rule_id: str) -> Optional[date]:
        """查询归档日期"""
        try:
            from app import db
            from app.models.notification import NotificationRule
            rule = NotificationRule.query.filter_by(rule_id=rule_id).first()
            if rule and rule.deleted_at:
                if isinstance(rule.deleted_at, str):
                    return datetime.fromisoformat(rule.deleted_at).date()
                return rule.deleted_at.date() if hasattr(rule.deleted_at, 'date') else date.today()
        except Exception as e:
            logger.debug(f"查询归档日期失败 {rule_id}: {e}")
        return None

    @staticmethod
    def run_daily_check(all_rules: List) -> dict:
        """每日休眠检查 — 检查所有规则并执行 L1/L2/L3

        Args:
            all_rules: 全部规则对象列表

        Returns:
            dict: {l1_paused: [...], l2_archived: [...], l3_reported: [...]}
        """
        result = {'l1_paused': [], 'l2_archived': [], 'l3_reported': []}

        for rule in all_rules:
            rule_id = rule if isinstance(rule, str) else (
                getattr(rule, 'rule_id', None) or (rule.get('rule_id', '') if isinstance(rule, dict) else '')
            )
            if not rule_id:
                continue

            # L1: 自动暂停
            if DormancyManager.check_l1_pause(rule):
                if DormancyManager.execute_l1_pause(rule):
                    result['l1_paused'].append(rule_id)
                continue

            # L2: 归档
            if DormancyManager.check_l2_archive(rule):
                if DormancyManager.execute_l2_archive(rule):
                    result['l2_archived'].append(rule_id)
                continue

            # L3: 健康报告
            if DormancyManager.check_l3_health(rule):
                report_id = DormancyManager.execute_l3_health_report(rule)
                if report_id:
                    result['l3_reported'].append({'rule_id': rule_id, 'report_id': report_id})

        logger.info(f"每日休眠检查完成: L1暂停{len(result['l1_paused'])} L2归档{len(result['l2_archived'])} L3报告{len(result['l3_reported'])}")
        return result

    @staticmethod
    def run_weekly_health_report(all_rules: List) -> dict:
        """每周健康报告 — 生成所有暂停/归档规则的汇总报告

        Returns:
            dict: {report_id, summary}
        """
        paused = [r for r in all_rules if getattr(r, 'status', None) == 'paused'
                  or (isinstance(r, dict) and r.get('status') == 'paused')]
        archived = [r for r in all_rules if getattr(r, 'status', None) == 'archived'
                    or (isinstance(r, dict) and r.get('status') == 'archived')]

        return {
            'total_rules': len(all_rules),
            'paused_count': len(paused),
            'archived_count': len(archived),
            'active_count': len(all_rules) - len(paused) - len(archived),
            'check_time': datetime.now().isoformat(),
        }


import json  # noqa: E402 (keep at bottom to avoid circular import issues)
