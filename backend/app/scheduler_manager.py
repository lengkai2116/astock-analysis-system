"""
APScheduler 定时任务管理器

职责：
  1. 应用启动时初始化 BackgroundScheduler
  2. 提供 daily_close_sync() 统一编排器（复用现有 sync 脚本逻辑）
  3. 从 RuntimeConfigManager 读取用户配置，动态管理 Job
  4. 同步完成后触发 blinker 信号（供下游模块监听）

生产环境约束：
  - 使用 APScheduler BackgroundScheduler（非阻塞）
  - 所有定时参数由 RuntimeConfigManager 管理，无硬编码 cron
  - 信号机制用 blinker（或降级为直接回调）

依赖：
  - apscheduler>=3.10.4
  - blinker（Flask 依赖自带）
"""
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# blinker 信号（可选依赖）
# ──────────────────────────────────────────

try:
    from blinker import signal as _signal_factory
    daily_sync_completed = _signal_factory('daily_sync_completed')
    HAS_BLINKER = True
except ImportError:
    HAS_BLINKER = False
    # 降级：简单的回调列表
    _sync_listeners = []
    daily_sync_completed = type('FakeSignal', (), {
        'connect': lambda self, fn: _sync_listeners.append(fn),
        'send': lambda self, **kw: [fn(**kw) for fn in _sync_listeners]
    })()


# ──────────────────────────────────────────
# APScheduler 导入
# ──────────────────────────────────────────

_APSCHEDULER_AVAILABLE = False
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    logger.warning("APScheduler 未安装，定时任务不可用。请执行: pip install apscheduler>=3.10.4")


class SchedulerManager:
    """定时任务管理器"""

    def __init__(self):
        self._scheduler = None
        self._initialized = False
        self._app = None

    def init_app(self, app):
        """初始化 APScheduler"""
        if not _APSCHEDULER_AVAILABLE:
            logger.warning("APScheduler 未安装，跳过调度器初始化")
            return

        self._app = app
        if self._scheduler is None:
            self._scheduler = BackgroundScheduler(
                daemon=True,
                job_defaults={
                    'coalesce': True,       # 积压的多次触发合并为一次
                    'max_instances': 1,      # 同一任务不并行
                    'misfire_grace_time': 300  # 5分钟内错过可补
                }
            )

        # 从配置读取调度参数并注册 Job
        with app.app_context():
            config = self._load_config()
            self._register_jobs(config)

        self._scheduler.start()
        self._initialized = True
        logger.info("APScheduler 已启动")

    def _load_config(self) -> Dict[str, Any]:
        """从 RuntimeConfigManager 加载调度配置"""
        try:
            from app.services.runtime_config import runtime_config_manager
            config = runtime_config_manager.get('scheduling', {})

            # 默认值兜底
            if not config:
                config = {
                    "daily_sync": {
                        "enabled": True,
                        "trigger_time": "15:30",
                        "mode": "incremental",
                        "data_types": ["daily", "basic", "moneyflow", "index", "adj_factor"],
                        "warmup_cache": True,
                        "timeout_minutes": 30
                    },
                    "intraday": {"enabled": True, "moneyflow_interval_min": 30},
                    "analysis": {
                        "weekly_eval": {"enabled": True, "day_of_week": "mon", "time": "06:00"},
                        "health_check": {"enabled": True, "day_of_week": "mon", "time": "06:30"},
                        "weekly_report": {"enabled": True, "day_of_week": "sun", "time": "20:00"},
                        "param_plateau": {"enabled": True, "day_of_month": 1, "time": "05:00"}
                    }
                }
            return config
        except Exception as e:
            logger.warning(f"加载调度配置失败: {e}")
            return {}

    def _register_jobs(self, config: Dict[str, Any]):
        """根据配置注册 APScheduler Job"""
        if not self._scheduler:
            return

        # 移除所有现有 Job（避免重复注册）
        self._scheduler.remove_all_jobs()

        # ── 日终数据同步 ──
        ds = config.get('daily_sync', {})
        if ds.get('enabled', True):
            trigger_time = ds.get('trigger_time', '15:30')
            try:
                hour, minute = trigger_time.split(':')
                self._scheduler.add_job(
                    self.run_daily_sync,
                    CronTrigger(hour=int(hour), minute=int(minute)),
                    id='daily_close_sync',
                    name='日终数据同步',
                    replace_existing=True
                )
                logger.info(f"注册日终同步任务: 每日 {trigger_time}")
            except Exception as e:
                logger.warning(f"注册日终同步失败: {e}")

        # ── 周度赢率评估 ──
        we = config.get('analysis', {}).get('weekly_eval', {})
        if we.get('enabled', True):
            try:
                day_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6, '周一': 0,
                           '周二': 1, '周三': 2, '周四': 3, '周五': 4, '周六': 5, '周日': 6}
                day = day_map.get(we.get('day_of_week', 'mon'), 0)
                t = we.get('time', '06:00')
                h, m = t.split(':')
                self._scheduler.add_job(
                    self._run_weekly_eval,
                    CronTrigger(day_of_week=day, hour=int(h), minute=int(m)),
                    id='weekly_eval',
                    name='周度赢率评估'
                )
            except Exception:
                pass

        # ── 策略健康检查 ──
        hc = config.get('analysis', {}).get('health_check', {})
        if hc.get('enabled', True):
            try:
                day_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6,
                           '周一': 0, '周二': 1, '周三': 2, '周四': 3, '周五': 4, '周六': 5, '周日': 6}
                day = day_map.get(hc.get('day_of_week', 'mon'), 0)
                t = hc.get('time', '06:30')
                h, m = t.split(':')
                self._scheduler.add_job(
                    self._run_health_check,
                    CronTrigger(day_of_week=day, hour=int(h), minute=int(m)),
                    id='strategy_health_check',
                    name='策略健康检查'
                )
            except Exception:
                pass

        # ── 周度报告 ──
        wr = config.get('analysis', {}).get('weekly_report', {})
        if wr.get('enabled', True):
            try:
                day_map = {'sun': 6, '周日': 6}
                day = day_map.get(wr.get('day_of_week', 'sun'), 6)
                t = wr.get('time', '20:00')
                h, m = t.split(':')
                self._scheduler.add_job(
                    self._run_weekly_report,
                    CronTrigger(day_of_week=day, hour=int(h), minute=int(m)),
                    id='weekly_report',
                    name='周度报告生成'
                )
            except Exception:
                pass

        # ── 月度参数平原校验 ──
        pp = config.get('analysis', {}).get('param_plateau', {})
        if pp.get('enabled', True):
            try:
                dom = pp.get('day_of_month', 1)
                t = pp.get('time', '05:00')
                h, m = t.split(':')
                self._scheduler.add_job(
                    self._run_param_plateau_check,
                    CronTrigger(day=dom, hour=int(h), minute=int(m)),
                    id='param_plateau_check',
                    name='月度参数平原校验'
                )
            except Exception:
                pass

        # ── 月度 Stock 同步（244号方案 D5） ──
        ss = config.get('stock_sync', {})
        if ss.get('enabled', True):
            try:
                dom = ss.get('day_of_month', 1)
                t = ss.get('time', '04:00')
                h, m = t.split(':')
                self._scheduler.add_job(
                    self._run_stock_sync,
                    CronTrigger(day=dom, hour=int(h), minute=int(m)),
                    id='monthly_stock_sync',
                    name='月度 Stock 列表同步'
                )
                logger.info(f"注册月度 Stock 同步: 每月 {dom} 日 {t}")
            except Exception:
                pass

    def reschedule_from_config(self, config: Dict[str, Any]):
        """根据新配置动态更新 Job（无需重启）"""
        if self._scheduler:
            self._register_jobs(config)

    def get_jobs(self) -> List[Dict[str, Any]]:
        """获取所有 Job 信息（含下次执行时间）"""
        if not self._scheduler:
            return []

        jobs = []
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run.isoformat() if next_run else None,
                'trigger': str(job.trigger)
            })
        return jobs

    # ──────────────────────────────────────────
    # 日终同步编排器
    # ──────────────────────────────────────────

    def run_daily_sync(self) -> Dict[str, Any]:
        """日终数据同步编排器

        从 RuntimeConfigManager 读取用户配置，执行增量/全量同步，
        完成后触发 daily_sync_completed 信号通知下游模块。
        """
        start_ts = time.time()
        sync_type = 'daily'
        result = {'status': 'running', 'records_added': 0, 'data_types': []}

        try:
            from app import db

            # 记录同步开始
            sync_log_id = self._record_sync_start(sync_type)

            # 从配置读取参数
            config = self._load_config()
            ds_config = config.get('daily_sync', {})
            mode = ds_config.get('mode', 'incremental')
            data_types = ds_config.get('data_types', ['daily', 'basic', 'moneyflow', 'index', 'adj_factor'])
            warmup = ds_config.get('warmup_cache', True)

            logger.info(f"=== 开始日终同步 (mode={mode}, types={data_types}) ===")

            # 执行同步（按数据类型）
            records_added = 0
            for data_type in data_types:
                try:
                    count = self._sync_by_type(data_type, mode)
                    records_added += count
                    result['data_types'].append({'type': data_type, 'count': count})
                except Exception as e:
                    logger.error(f"同步 {data_type} 失败: {e}")

            # 预热缓存
            if warmup and records_added > 0:
                try:
                    from app.data.cache_manager import CacheManager
                    cm = CacheManager()
                    cm.warmup_cache()
                    logger.info("DuckDB 缓存预热完成")
                except Exception as e:
                    logger.warning(f"缓存预热失败: {e}")

            duration_ms = int((time.time() - start_ts) * 1000)
            result['status'] = 'success'
            result['records_added'] = records_added
            result['duration_ms'] = duration_ms

            logger.info(f"=== 日终同步完成: {records_added} 条, 耗时 {duration_ms}ms ===")

            # 更新同步日志
            self._record_sync_end(sync_log_id, result)

            # 发送完成信号
            daily_sync_completed.send(
                date=datetime.now().strftime('%Y-%m-%d'),
                stats=result,
                data_types=data_types
            )

            # ── 盘后清理链（239/244号方案 §2.2/§5 Phase 2） ───────────
            if result['status'] == 'success' and records_added > 0:
                today = datetime.now().strftime('%Y-%m-%d')
                # 1. 清理 DuckDB as_minute_kline（当日分钟K线）
                try:
                    from app.data.enhanced_cache_manager import get_ecm_instance
                    ecm = get_ecm_instance()
                    ecm.clean_as_minute_kline(today)
                except Exception as e:
                    logger.warning(f"盘后清理 as_minute_kline 失败: {e}")

                # 2. 清理 InMemoryStateStore（盘中内存缓存）
                try:
                    from app.data.in_memory_store import store as mem_store
                    mem_store.clear_all()
                    logger.info("InMemoryStateStore 盘中缓存已清理")
                except Exception as e:
                    logger.warning(f"清理 InMemoryStateStore 失败: {e}")

                # 3. 清理 TieredMemoryCache（盘中三级缓存）
                try:
                    from app.data.memory_cache import TieredMemoryCache
                    tmc = TieredMemoryCache()
                    tmc.clear()
                    logger.info("TieredMemoryCache 盘中缓存已清理")
                except Exception as e:
                    logger.warning(f"清理 TieredMemoryCache 失败: {e}")

                # 4. 清理 AkshareCollector 关注列表（为次日做准备）
                try:
                    from app.data.akshare_collector import akshare_collector
                    akshare_collector.clear_watchlist()
                except Exception as e:
                    logger.debug(f"清理采集器关注列表失败: {e}")

                # 5. 清理 PostgreSQL 盘中实时表（realtime_* 当日数据）
                try:
                    from app.data.realtime_pg import cleanup_old_data
                    cleanup_old_data(retention_days=0)  # 0 = 仅清理当日之前
                except Exception as e:
                    logger.debug(f"清理 PG realtime_* 表失败: {e}")

                logger.info(f"=== 盘后清理链完成 (date={today}) ===")

        except Exception as e:
            duration_ms = int((time.time() - start_ts) * 1000)
            result['status'] = 'failed'
            result['error_message'] = str(e)
            result['duration_ms'] = duration_ms
            logger.error(f"日终同步失败: {e}")

        return result

    def catch_up_if_needed(self):
        """应用启动时检测：若缺少交易日数据则自动触发同步

        取代固定 cron 时间（15:30）的依赖。每次应用启动时检查：
          - 非交易日 → 跳过
          - 完全无数据 → 全量同步
          - 数据最新日期 < 今日 → 增量同步
          - 数据已最新 → 跳过
        """
        if not self._app:
            logger.warning("启动补采: 无 app 引用，跳过")
            return
        with self._app.app_context():
            from app.data.enhanced_cache_manager import get_ecm_instance
            from app.utils.trading_hours import is_holiday
            from datetime import date, datetime

            today = date.today()
            if is_holiday(datetime.combine(today, datetime.min.time())):
                logger.info("启动补采: 今日非交易日，跳过")
                return

            ecm = get_ecm_instance()
            date_df = ecm.conn.execute(
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
            ).fetchdf()
            max_date = date_df['trade_date'].iloc[0] if not date_df.empty else None
            if max_date is None:
                logger.info("=== 启动补采: DuckDB 无数据, 开始全量同步 ===")
            elif max_date < today:
                logger.info(f"=== 启动补采: 数据最新 {max_date}, 早于今日 {today}, 开始增量同步 ===")
            else:
                logger.info(f"启动补采: 数据已最新 ({max_date}), 跳过")
                # 即使数据最新，仍执行 Stock 月度同步启动检查（244号方案 D5）
                self._run_stock_sync_if_needed()
                return

            self.run_daily_sync()
            # 日终同步后执行 Stock 月度同步启动检查
            self._run_stock_sync_if_needed()

    def _run_stock_sync_if_needed(self):
        """启动时检查 Stock 表是否需要月度更新（244号方案 A7）"""
        try:
            from app.models import Stock
            from datetime import date
            today = date.today()
            # 检查是否有本月同步的股票数据——用 max(updated_at) 判断
            latest = Stock.query.order_by(Stock.updated_at.desc()).first()
            if latest and latest.updated_at:
                from datetime import timedelta
                if latest.updated_at.month == today.month and latest.updated_at.year == today.year:
                    logger.info("Stock 月度同步检查: 本月已同步，跳过")
                    return
            logger.info("=== Stock 月度同步检查: 执行同步 ===")
            from app.data import DataManager
            from app import db
            count = DataManager().sync_stock_list()
            logger.info(f"Stock 月度同步完成: {count} 只")
        except Exception as e:
            from app import db
            db.session.rollback()
            logger.warning(f"Stock 月度同步启动检查失败: {e}")

    def _sync_by_type(self, data_type: str, mode: str) -> int:
        """按数据类型执行同步"""
        from app import db
        from app.data import DataManager
        dm = DataManager()

        if data_type == 'daily':
            if mode == 'full':
                return dm.sync_all_daily_data()
            else:
                # 增量：从 DuckDB 获取最后交易日
                from app.data.enhanced_cache_manager import get_ecm_instance
                ecm = get_ecm_instance()
                date_df = ecm.conn.execute(
                    "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
                ).fetchdf()
                last_date = date_df['trade_date'].iloc[0] if not date_df.empty else None
                if last_date:
                    try:
                        from datetime import datetime
                        last_date_str = last_date.strftime('%Y%m%d') if hasattr(last_date, 'strftime') else str(last_date).replace('-', '')
                    except Exception:
                        last_date_str = str(last_date)
                    return dm.sync_daily_data_range(last_date_str, mode='incremental')
                return dm.sync_all_daily_data()

        elif data_type == 'basic':
            return dm.sync_all_daily_basic_data()
        elif data_type == 'moneyflow':
            return dm.sync_moneyflow_data()
        elif data_type == 'index':
            return dm.sync_index_daily_data()
        elif data_type == 'adj_factor':
            return dm.sync_adj_factor_data()
        return 0

    def _record_sync_start(self, sync_type: str) -> Optional[int]:
        """记录同步开始日志"""
        try:
            from app import db
            from app.models.system_config import SyncLog
            log_entry = SyncLog(
                sync_type=sync_type,
                status='running',
                started_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()
            return log_entry.id
        except Exception:
            from app import db
            db.session.rollback()
            return None

    def _record_sync_end(self, log_id: Optional[int], result: Dict[str, Any]):
        """更新同步结束日志"""
        if not log_id:
            return
        try:
            from app import db
            from app.models.system_config import SyncLog
            log_entry = SyncLog.query.get(log_id)
            if log_entry:
                log_entry.status = result.get('status', 'failed')
                log_entry.finished_at = datetime.utcnow()
                log_entry.duration_ms = result.get('duration_ms')
                log_entry.records_added = result.get('records_added', 0)
                log_entry.error_message = result.get('error_message')
                log_entry.details = {'data_types': result.get('data_types', [])}
                db.session.commit()
        except Exception:
            pass

    # ──────────────────────────────────────────
    # 维护任务（封装 scheduler.py 原有功能）
    # ──────────────────────────────────────────

    def _run_weekly_eval(self):
        """周度批量赢率评估"""
        try:
            from app.scheduler import run_weekly_batch_eval
            run_weekly_batch_eval()
        except Exception as e:
            logger.error(f"周度赢率评估失败: {e}")

    def _run_health_check(self):
        """策略健康度巡检"""
        try:
            from app.scheduler import run_strategy_health_check
            run_strategy_health_check()
        except Exception as e:
            logger.error(f"策略健康检查失败: {e}")

    def _run_weekly_report(self):
        """周度验证报告"""
        try:
            from app.scheduler import run_weekly_report
            run_weekly_report()
        except Exception as e:
            logger.error(f"周度报告生成失败: {e}")

    def _run_param_plateau_check(self):
        """月度参数平原校验"""
        try:
            from app.scheduler import run_monthly_parameter_plateau_check
            run_monthly_parameter_plateau_check()
        except Exception as e:
            logger.error(f"月度参数校验失败: {e}")

    def _run_stock_sync(self):
        """月度 Stock 列表同步（244号方案 D5）"""
        try:
            from flask import current_app
            with current_app.app_context():
                from app.data import DataManager
                count = DataManager().sync_stock_list()
                logger.info(f"月度 Stock 同步完成: {count} 只")
        except Exception as e:
            logger.error(f"月度 Stock 同步失败: {e}")

    def shutdown(self):
        """关闭调度器"""
        if self._scheduler and self._initialized:
            self._scheduler.shutdown(wait=False)
            self._initialized = False
            logger.info("APScheduler 已关闭")

    # ──────────────────────────────────────────
    # 辅助方法（供下游模块注册任务）
    # ──────────────────────────────────────────

    def add_interval_job(self, job_id: str, func, minutes: int,
                         max_instances: int = 1, coalesce: bool = True) -> bool:
        """注册间隔任务"""
        if not self._scheduler:
            return False
        try:
            from apscheduler.triggers.interval import IntervalTrigger
            self._scheduler.add_job(
                func,
                IntervalTrigger(minutes=minutes),
                id=job_id,
                name=job_id,
                replace_existing=True,
                max_instances=max_instances,
                coalesce=coalesce,
                misfire_grace_time=300,
            )
            logger.debug(f"间隔任务已注册: {job_id} ({minutes}min)")
            return True
        except Exception as e:
            logger.warning(f"注册间隔任务失败 {job_id}: {e}")
            return False

    def add_cron_job(self, job_id: str, func, **cron_kwargs) -> bool:
        """注册 cron 任务

        cron_kwargs 支持: hour, minute, day_of_week, day, month 等标准 APScheduler 参数
        """
        if not self._scheduler:
            return False
        try:
            self._scheduler.add_job(
                func,
                CronTrigger(**cron_kwargs),
                id=job_id,
                name=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
            )
            logger.debug(f"Cron任务已注册: {job_id} ({cron_kwargs})")
            return True
        except Exception as e:
            logger.warning(f"注册 cron 任务失败 {job_id}: {e}")
            return False

    def on_daily_sync_complete(self, callback) -> None:
        """注册日终同步完成回调

        在 run_daily_sync() 完成后被调用。
        因 blinker 可能不可用，使用回调列表存储。
        """
        global _sync_listeners
        if HAS_BLINKER:
            daily_sync_completed.connect(callback)
        else:
            _sync_listeners.append(callback)
        logger.debug(f"日终同步回调已注册")
        # 更新 send 方法以包含所有注册的回调
        if not HAS_BLINKER:

            def _send_with_listeners(**kw):
                for fn in _sync_listeners:
                    try:
                        fn(**kw)
                    except Exception as e:
                        logger.error(f"日终同步回调执行失败: {e}")
            daily_sync_completed.send = _send_with_listeners

    def remove_job(self, job_id: str) -> bool:
        """移除指定任务"""
        if not self._scheduler:
            return False
        try:
            self._scheduler.remove_job(job_id)
            logger.debug(f"任务已移除: {job_id}")
            return True
        except Exception:
            return False


# ──────────────────────────────────────────
# 模块单例
# ──────────────────────────────────────────

scheduler_manager = SchedulerManager()
