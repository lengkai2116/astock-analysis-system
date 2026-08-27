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
import os
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
                        "data_types": ["daily", "basic", "moneyflow", "index", "adj_factor",
                                       "fina_indicator", "income", "balancesheet", "cashflow",
                                       "forecast", "stk_limit", "lhb",
                                       "top10_holders", "stk_holder"],
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

        # ── 日终数据同步（仅在无 data_daemon 时注册）──
        ds = config.get('daily_sync', {})
        if ds.get('enabled', True) and not os.environ.get('DATA_DAEMON_RUNNING'):
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

        # ── 信号验证回算 T+5/T+10/T+20（345号第③层核查激活） ──
        # 2026-08-16 修复：scheduler.py register_scheduler_jobs 定义了
        # t5/t10/t20_checkpoint（18:00/18:05/18:10）但 scheduler_manager 从未
        # 调用 register_scheduler_jobs → 1083 条 signal_records 全部 pending
        # 未回算（345号 G3.1 样本不足根因）。此处显式注册每日回算任务。
        # 仅 API 进程注册（daemon 模式由 data_daemon 独立管理，避免双调度）。
        if not os.environ.get('DATA_DAEMON_RUNNING'):
            for off, job_id, name, hh, mm in [
                (5, 't5_checkpoint', '信号验证回算 T+5', 18, 0),
                (10, 't10_checkpoint', '信号验证回算 T+10', 18, 5),
                (20, 't20_checkpoint', '信号验证回算 T+20', 18, 10),
            ]:
                try:
                    self._scheduler.add_job(
                        lambda o=off: self._run_signal_checkpoint(o),
                        CronTrigger(hour=hh, minute=mm),
                        id=job_id,
                        name=name,
                        replace_existing=True,
                        coalesce=True,
                        max_instances=1,
                        misfire_grace_time=3600,
                    )
                except Exception as e:
                    logger.warning(f"注册 {name} 失败: {e}")
        else:
            logger.info("daemon 模式：信号验证回算由 data_daemon 独立管理，跳过 APScheduler 注册")

        # ── 盘中快照推送（迭代2：API 进程 APScheduler 推送） ──
        # 320号 L4：仅 API 进程注册（daemon 模式跳过——daemon 独立管理推送，
        # 否则 daemon 进程收盘后 APScheduler 每 5s 空转触发刷日志）
        if not os.environ.get('DATA_DAEMON_RUNNING'):
            try:
                from datetime import timedelta
                now = datetime.now()
                self._scheduler.add_job(
                    self._market_snapshot_push_wrapper_5s,
                    IntervalTrigger(seconds=5),
                    id='market_snapshot_push_5s',
                    name='盘中快照推送（涨跌/涨幅榜/自选）',
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                    misfire_grace_time=15,
                    next_run_time=now + timedelta(seconds=10),  # 冷启动保护：首次延迟10s
                )
                logger.debug("注册盘中快照推送: 每 5s 推送涨跌分布+涨幅榜+自选行情")
            except Exception as e:
                logger.warning("注册盘中快照推送(5s)失败: %s", e)

            try:
                self._scheduler.add_job(
                    self._market_snapshot_push_wrapper_30s,
                    IntervalTrigger(seconds=30),
                    id='market_snapshot_push_30s',
                    name='盘中板块排行推送',
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                    misfire_grace_time=60,
                )
                logger.debug("注册盘中板块排行推送: 每 30s 推送板块排行")
            except Exception as e:
                logger.warning("注册盘中板块排行推送(30s)失败: %s", e)

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
        # DATA_DAEMON_RUNNING 模式下，数据守护进程独立管理日终同步
        if os.environ.get('DATA_DAEMON_RUNNING') == '1':
            return {'status': 'skipped', 'reason': 'managed_by_data_daemon',
                    'records_added': 0, 'data_types': []}

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

            # 预热缓存（已废弃：InMemoryStateStore 无需预热，SQLite WAL 直接访问）
            # 旧 CacheManager 已被 EnhancedCacheManager 替代
            if warmup and records_added > 0:
                pass

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

                # 5. [已废弃] PostgreSQL 盘中实时表清理 — realtime_pg.py 已于 248号方案 Phase C 移除
                # PG realtime_* 表不再写入，盘中数据使用 InMemoryStateStore + mootdx TCP

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
          - 数据已最新 → 检查单只股票数据完整性（新上市/数据不全股票）
          - 数据不足 120 日的股票 → 按需触发增量同步
        """
        if not self._app:
            logger.warning("启动补采: 无 app 引用，跳过")
            return
        with self._app.app_context():
            from app.data.enhanced_cache_manager import get_ecm_instance
            from app.utils.trading_hours import is_holiday
            from datetime import date, datetime

            # ── 检查 daily_basic_cache 历史数据完整性（247号方案 §4） ──
            # 后台线程执行，不阻塞服务器启动
            import threading as _th
            _th.Thread(target=self._catch_up_daily_basic, daemon=True).start()

            today = date.today()
            if is_holiday(datetime.combine(today, datetime.min.time())):
                logger.info("启动补采: 今日非交易日，跳过")
                return

            ecm = get_ecm_instance()
            import pandas as pd
            date_df = pd.read_sql(
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1",
                ecm.conn
            )
            max_date = date_df['trade_date'].iloc[0] if not date_df.empty else None
            if max_date is None:
                logger.info("=== 启动补采: 无数据, 后台线程开始全量同步（不影响服务器启动）===")
                import threading
                t = threading.Thread(target=self.run_daily_sync, daemon=True)
                t.start()
                # Stock 同步也后台执行
                threading.Thread(target=self._run_stock_sync_if_needed, daemon=True).start()
                return
            elif date.fromisoformat(str(max_date)) < today:
                logger.info(f"=== 启动补采: 数据最新 {max_date}, 早于今日 {today}, 后台增量同步 ===")
                import threading
                threading.Thread(target=self.run_daily_sync, daemon=True).start()
                return

            logger.info(f"启动补采: 数据已最新 ({max_date}), 跳过")

            # ── 即使数据全局最新，仍检查数据不足 120 日的股票 ──
            try:
                self._replenish_sparse_stocks(ecm, min_days=120)
            except Exception as e:
                logger.warning(f"启动补采: 数据补齐失败（可忽略）: {e}")

            # 执行 Stock 月度同步启动检查（244号方案 D5）
            self._run_stock_sync_if_needed()

    _last_replenish_date: 'date' = None  # 上次补采日期，同一自然日不重复

    def _replenish_sparse_stocks(self, ecm, min_days: int = 120, max_stocks: int = 100):
        """补齐数据不足 min_days 天的股票

        查询 daily_cache 中每条数据的行数，对数据量不足的股票
        触发按需增量同步。

        过滤逻辑：
          - 新股/次新股（最早交易日期距今不足 min_days 天）→ 跳过
          - 同一自然日内已补采过 → 跳过（避免每次重启重复补）

        Args:
            ecm: EnhancedCacheManager 实例
            min_days: 最低所需天数
            max_stocks: 每轮最多补齐的股票数
        """
        from datetime import date, timedelta
        import pandas as pd

        today = date.today()

        # 同一自然日不重复补采（避免多次重启重复触发）
        if self._last_replenish_date == today:
            logger.info(f"启动补采: 今日({today})已补采过，跳过")
            return

        # 查询数据不足的股票，同时取最早和最晚交易日
        sparse_df = pd.read_sql("""
            SELECT ts_code, COUNT(*) as cnt,
                   MAX(trade_date) as last_date,
                   MIN(trade_date) as first_date
            FROM daily_cache
            GROUP BY ts_code
            HAVING cnt < ?
            ORDER BY cnt ASC
            LIMIT ?
        """, ecm.conn, params=[min_days, max_stocks])

        if sparse_df.empty:
            logger.info(f"启动补采: 所有股票数据均 >= {min_days} 天，无需补齐")
            self._last_replenish_date = today
            return

        # 过滤新股/次新股（上市不足 min_days 天，不可能有足够数据）
        cutoff_date = pd.Timestamp(today) - pd.Timedelta(days=min_days)
        pre_filter = len(sparse_df)
        sparse_df = sparse_df[sparse_df['first_date'] <= cutoff_date].copy()
        new_listing_skipped = pre_filter - len(sparse_df)

        if sparse_df.empty:
            logger.info(f"启动补采: {pre_filter} 只数据不足的股票均为新股/次新股（上市不满 {min_days} 天），跳过")
            self._last_replenish_date = today
            return

        logger.info(f"启动补采: {pre_filter} 只数据不足，其中新股/次新股 {new_listing_skipped} 只已跳过，实际需补 {len(sparse_df)} 只")

        from app.data import DataManager
        dm = DataManager()

        replenished = 0
        for _, row in sparse_df.iterrows():
            ts_code = row['ts_code']
            last_date = row['last_date']
            try:
                if pd.isna(last_date):
                    cnt = dm.sync_daily_data(ts_code, use_cache=False)
                else:
                    # SQLite 可能返回 date 对象或字符串，统一处理
                    if hasattr(last_date, 'strftime'):
                        start_str = last_date.strftime('%Y%m%d')
                    else:
                        start_str = str(last_date).replace('-', '').replace(' ', '')[:8]
                    cnt = dm.sync_daily_data(ts_code, use_cache=False, start_date=start_str)
                if cnt > 0:
                    replenished += 1
                    logger.info(f"启动补采: {ts_code} 补齐 {cnt} 条（现有 {row['cnt']} 天）")
            except Exception as e:
                logger.debug(f"启动补采: {ts_code} 补齐失败: {e}")

        logger.info(f"启动补采完成: 补齐 {replenished}/{len(sparse_df)} 只股票（跳过 {new_listing_skipped} 只新股）")
        self._last_replenish_date = today

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

    def _catch_up_daily_basic(self):
        """检查 daily_basic_cache 历史数据完整性，不足时触发回填（247号方案 §4）"""
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        try:
            df = ecm._query_df("SELECT COUNT(DISTINCT trade_date) as cnt FROM daily_basic_cache")
            date_count = df.iloc[0]['cnt'] if not df.empty else 0
        except Exception:
            date_count = 0

        if date_count >= 60:
            logger.info(f"daily_basic 历史检查: {date_count} 天，满足要求")
            return

        logger.info(f"daily_basic 历史检查: 仅 {date_count} 天，不足 60 天，触发历史回填...")
        from app.data import DataManager
        dm = DataManager()
        count = dm.sync_daily_basic_history(max_days=120)
        logger.info(f"daily_basic 历史回填完成: {count} 条")

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
                import pandas as pd
                date_df = pd.read_sql(
                    "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1",
                    ecm.conn
                )
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
        elif data_type == 'fina_indicator':
            return dm.sync_fina_indicator_data()
        elif data_type == 'income':
            return dm.sync_income_data()
        elif data_type == 'balancesheet':
            return dm.sync_balancesheet_data()
        elif data_type == 'cashflow':
            return dm.sync_cashflow_data()
        elif data_type == 'forecast':
            return dm.sync_forecast_data()
        elif data_type == 'margin':
            return dm.sync_margin_data()
        elif data_type == 'stk_limit':
            return dm.sync_stk_limit_data()
        elif data_type == 'finance_report':
            return dm.sync_finance_report_data()
        elif data_type == 'lhb':
            return dm.sync_lhb_data()
        elif data_type == 'lhb_detail':
            return dm.sync_lhb_detail_data()
        elif data_type == 'top10_holders':
            return dm.sync_top10_holders_data()
        elif data_type == 'stk_holder':
            return dm.sync_stk_holder_data()
        elif data_type == 'concept':
            return dm.sync_concept_data()
        elif data_type == 'index_member':
            return dm.sync_index_member_data()
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

    def _run_signal_checkpoint(self, days_offset: int):
        """信号验证回算 T+5/T+10/T+20（345号第③层核查激活，2026-08-16）

        signal_records 生命周期：pending → t5_checked → t10_checked → completed。
        scheduler.py register_scheduler_jobs 定义了任务但从未接入调度，
        此处由 scheduler_manager 显式注册每日 18:00/18:05/18:10 执行。
        """
        try:
            from flask import current_app
            with current_app.app_context():
                from app.services.backtest_evidence_service import BacktestEvidenceService
                service = BacktestEvidenceService()
                service.run_checkpoint_update(days_offset)
                logger.info(f"信号验证回算 T+{days_offset} 完成")
        except Exception as e:
            logger.error(f"信号验证回算 T+{days_offset} 失败: {e}")

    # ── 盘中快照推送包装器（迭代2） ─────────────────────────

    def _market_snapshot_push_wrapper_5s(self):
        """盘中快照推送包装器（每 5s）：检查交易时段，推送涨跌/涨幅榜/自选

        冷启动保护：首次执行由 next_run_time=now+10s 延迟。
        """
        # DATA_DAEMON_RUNNING 模式下，采集进程独立管理推送，API 进程不执行盘中推送
        if os.environ.get('DATA_DAEMON_RUNNING') == '1':
            return
        # 非交易时段跳过
        try:
            from app.utils.trading_hours import is_trading_time
            if not is_trading_time():
                return
        except Exception:
            pass  # 导入失败则默认执行

        try:
            from flask import current_app
            with current_app.app_context():
                from app.services.push_service import (
                    push_market_summary,
                    push_top_stocks,
                    push_watchlist_quotes,
                )
                push_market_summary()
                push_top_stocks()
                push_watchlist_quotes()
        except Exception as e:
            logger.error("盘中快照推送(5s)异常: %s", e)

    def _market_snapshot_push_wrapper_30s(self):
        """盘中板块排行推送包装器（每 30s）"""
        # DATA_DAEMON_RUNNING 模式下跳过
        if os.environ.get('DATA_DAEMON_RUNNING') == '1':
            return
        # 非交易时段跳过
        try:
            from app.utils.trading_hours import is_trading_time
            if not is_trading_time():
                return
        except Exception:
            pass

        try:
            from flask import current_app
            with current_app.app_context():
                from app.services.push_service import push_sector_rankings
                push_sector_rankings()
        except Exception as e:
            logger.error("盘中板块排行推送(30s)异常: %s", e)

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
