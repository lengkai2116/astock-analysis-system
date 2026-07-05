"""
规则调度服务 — RuleScheduler

APScheduler 定时任务管理器，负责安排规则的评估和休眠管理。

调度模式：
  1. 盘中定时扫描 — 按规则配置的间隔执行条件评估
  2. 日终批量评估 — daily_close_sync 完成后触发
  3. 每日休眠检查 — 检查 L1/L2/L3
  4. 每周健康报告 — 生成暂停/归档规则的汇总健康报告

集成方式：
  - 通过 scheduler_manager.py 注册定时任务
  - 日终评估监听 `daily_sync_completed` 信号（或回调列表）
"""
import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


# 回调列表（替代 blinker 信号）
_daily_eval_callbacks: List[Callable] = []


class RuleScheduler:
    """规则调度服务"""

    # 评估间隔选项（分钟）
    VALID_INTERVALS = [5, 15, 30, 60]

    @staticmethod
    def get_evaluator_interval(rule) -> int:
        """获取规则的评估间隔（分钟）

        读取规则配置中的 scan_interval_min，不在有效选项中的使用默认 15 分钟。
        """
        rule_dict = rule if isinstance(rule, dict) else getattr(rule, '__dict__', {})
        interval = rule_dict.get('scan_interval_min', 15)

        # 取最接近的有效值
        valid = RuleScheduler.VALID_INTERVALS
        if interval in valid:
            return interval

        closest = min(valid, key=lambda x: abs(x - interval))
        return closest

    @staticmethod
    def is_in_schedule_window(rule) -> bool:
        """检查当前时间是否在规则的调度时段内

        规则配置包含 schedule_start 和 schedule_end（格式: HH:MM）。
        为空表示全天可评估。
        """
        rule_dict = rule if isinstance(rule, dict) else getattr(rule, '__dict__', {})
        schedule_start = rule_dict.get('schedule_start', '')
        schedule_end = rule_dict.get('schedule_end', '')
        now = datetime.now()

        if not schedule_start and not schedule_end:
            return True  # 空时段 = 全天可用

        try:
            start_h, start_m = map(int, schedule_start.split(':')) if schedule_start else (9, 30)
            end_h, end_m = map(int, schedule_end.split(':')) if schedule_end else (15, 0)
            start_t = time(start_h, start_m)
            end_t = time(end_h, end_m)
            current_t = now.time()

            if start_t <= end_t:
                return start_t <= current_t <= end_t
            else:
                # 跨日时段（如 22:00 - 02:00）
                return current_t >= start_t or current_t <= end_t
        except (ValueError, AttributeError):
            return True  # 配置解析失败 → 默认全天

    @staticmethod
    def is_trading_time() -> bool:
        """判断当前是否在交易时间

        A股交易时间:
          - 上午: 09:30 - 11:30
          - 下午: 13:00 - 15:00
        """
        now = datetime.now().time()
        morning = time(9, 30) <= now <= time(11, 30)
        afternoon = time(13, 0) <= now <= time(15, 0)
        return morning or afternoon

    @staticmethod
    def get_next_evaluation_time(rule) -> str:
        """计算下次评估时间（ISO格式）"""
        from datetime import timedelta
        interval = RuleScheduler.get_evaluator_interval(rule)
        return (datetime.now() + timedelta(minutes=interval)).isoformat()

    # ── 调度任务注册 ──

    @staticmethod
    def register_intraday_eval(scheduler_manager, interval_minutes: int = 15):
        """注册盘中定时评估任务

        Args:
            scheduler_manager: APScheduler 管理器实例
            interval_minutes: 评估间隔（5/15/30/60）

        盘中模式仅在交易时段执行条件评估。
        """
        if interval_minutes not in RuleScheduler.VALID_INTERVALS:
            interval_minutes = 15

        try:
            job_id = f'notification_intraday_eval_{interval_minutes}m'

            def intraday_eval_job():
                """盘中评估执行体"""
                if not RuleScheduler.is_trading_time():
                    return  # 非交易时段跳过

                try:
                    from app.services.notification_service import run_evaluation
                    result = run_evaluation(mode='intraday')
                    if result:
                        logger.info(f"盘中评估完成: {result.get('evaluated', 0)} 规则, "
                                     f"{result.get('triggered', 0)} 条触发")
                except Exception as e:
                    logger.error(f"盘中评估异常: {e}")

            scheduler_manager.add_interval_job(
                job_id=job_id,
                func=intraday_eval_job,
                minutes=interval_minutes,
                max_instances=1,
                coalesce=True,
            )
            logger.info(f"盘中评估任务已注册: {job_id} (每 {interval_minutes} 分钟)")
        except Exception as e:
            logger.warning(f"盘中评估任务注册失败: {e}")

    @staticmethod
    def register_daily_eval(scheduler_manager):
        """注册日终批量评估任务

        在 daily_close_sync 完成后触发，对所有 running 规则执行完整评估。
        也注册一个定时任务作为兜底（15:35 执行）。
        """
        try:
            job_id = 'notification_daily_eval'

            def daily_eval_job():
                """日终评估执行体"""
                try:
                    with scheduler_manager._app.app_context():
                        from app.services.notification_service import run_evaluation
                        result = run_evaluation(mode='daily')
                        stats = result or {'evaluated': 0, 'triggered': 0, 'errors': 0}
                        logger.info(f"日终评估完成: {stats.get('evaluated', 0)} 规则, "
                                     f"{stats.get('triggered', 0)} 条触发")
                except Exception as e:
                    logger.error(f"日终评估异常: {e}")

            # 定时任务（15:35 执行，日终同步通常 15:30 完成）
            scheduler_manager.add_cron_job(
                job_id=job_id,
                func=daily_eval_job,
                hour=15,
                minute=35,
            )

            # 同时注册信号监听（daily_sync_completed 后立即触发）
            scheduler_manager.on_daily_sync_complete(daily_eval_job)
            logger.info(f"日终评估任务已注册: {job_id}")
        except Exception as e:
            logger.warning(f"日终评估任务注册失败: {e}")

    @staticmethod
    def register_dormancy_check(scheduler_manager):
        """注册每日休眠检查任务

        每天 06:00 执行，检查 L1/L2/L3。
        """
        try:
            job_id = 'notification_dormancy_check'

            def dormancy_check_job():
                """休眠检查执行体"""
                try:
                    with scheduler_manager._app.app_context():
                        from app import db
                        from app.models.notification import NotificationRule
                        from app.services.dormancy_manager import DormancyManager

                        rules = NotificationRule.query.filter(
                            NotificationRule.deleted_at.is_(None)
                        ).all()
                        result = DormancyManager.run_daily_check(rules)
                        logger.info(f"休眠检查完成: {result}")
                except Exception as e:
                    logger.error(f"休眠检查异常: {e}")

            scheduler_manager.add_cron_job(
                job_id=job_id,
                func=dormancy_check_job,
                hour=6,
                minute=0,
            )
            logger.info(f"每日休眠检查任务已注册: {job_id}")
        except Exception as e:
            logger.warning(f"休眠检查任务注册失败: {e}")

    @staticmethod
    def register_weekly_health_report(scheduler_manager):
        """注册每周健康报告任务

        每周一 06:30 执行。
        """
        try:
            job_id = 'notification_weekly_report'

            def weekly_report_job():
                """每周健康报告执行体"""
                try:
                    with scheduler_manager._app.app_context():
                        from app import db
                        from app.models.notification import NotificationRule
                        from app.services.dormancy_manager import DormancyManager

                        rules = NotificationRule.query.filter(
                            NotificationRule.deleted_at.is_(None)
                        ).all()
                        summary = DormancyManager.run_weekly_health_report(rules)

                        # 写入报告归档
                        from app.models.notification import ReportArchive
                        report = ReportArchive(
                            source='notification',
                            source_id='__weekly__',
                            report_type='weekly',
                            period_start=datetime.now().date(),
                            period_end=datetime.now().date(),
                            generated_at=datetime.now(),
                            file_path='',
                            total_triggers=summary.get('total_triggers', 0) if isinstance(summary, dict) else 0,
                            active_rules=len([r for r in rules if r.status == 'running']),
                        )
                        db.session.add(report)
                        db.session.commit()

                        logger.info(f"每周健康报告完成: {summary}")
                except Exception as e:
                    logger.error(f"每周健康报告异常: {e}")

            scheduler_manager.add_cron_job(
                job_id=job_id,
                func=weekly_report_job,
                day_of_week='mon',
                hour=6,
                minute=30,
            )
            logger.info(f"每周健康报告任务已注册: {job_id}")
        except Exception as e:
            logger.warning(f"每周健康报告任务注册失败: {e}")

    @staticmethod
    def register_retry_check(scheduler_manager):
        """注册倒计时重推检查任务（每15分钟）"""
        try:
            job_id = 'notification_retry_check'

            def retry_check_job():
                """重推检查执行体"""
                try:
                    with scheduler_manager._app.app_context():
                        from app.services.notification_pusher import NotificationPusher
                        result = NotificationPusher.run_retry_check()
                        if result['retried'] > 0 or result['errors'] > 0:
                            logger.info(f"重推检查: {result}")
                except Exception as e:
                    logger.error(f"重推检查异常: {e}")

            scheduler_manager.add_interval_job(
                job_id=job_id,
                func=retry_check_job,
                minutes=15,
                max_instances=1,
                coalesce=True,
            )
            logger.info(f"倒计时重推检查任务已注册: {job_id}")
        except Exception as e:
            logger.warning(f"倒计时重推检查任务注册失败: {e}")

    @staticmethod
    def register_all(scheduler_manager, intraval_interval: int = 15):
        """注册全部调度任务

        一站式注册，在应用启动时调用。
        """
        logger.info("注册通知模块全部调度任务...")
        RuleScheduler.register_intraday_eval(scheduler_manager, intraval_interval)
        RuleScheduler.register_daily_eval(scheduler_manager)
        RuleScheduler.register_dormancy_check(scheduler_manager)
        RuleScheduler.register_weekly_health_report(scheduler_manager)
        RuleScheduler.register_retry_check(scheduler_manager)
        logger.info("通知模块调度任务注册完成")
