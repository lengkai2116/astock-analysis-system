"""
data_daemon — 数据采集守护进程（254号方案）
==========================================
独立于 Flask API 进程运行，负责：
  - mootdx TCP 实时采集（5s）
  - AKShare 低频补充（30min）
  - 启动完整性检查（自动补采缺失数据）
  - 日终批量同步（15:30，全市场 1 次 API 调用）
  - 定时巡检（非交易时段每小时）

启动：DATA_DAEMON_RUNNING=1 python data_daemon.py
停止：Ctrl+C 或 kill
"""
import os, sys, time, threading, signal, logging, json
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta

# ── 环境准备 ──
for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]
os.environ['DATA_DAEMON_RUNNING'] = '1'
os.environ.setdefault('DATA_DIR', '/Users/kalence/Desktop/01-A股股票分析系统/data')

# 加载 .env 文件（确保 DATABASE_URL 等配置就绪）
try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    load_dotenv(dotenv_path)
except Exception:
    pass

log_handler = TimedRotatingFileHandler(
    os.path.join(os.path.dirname(__file__), 'logs', 'data_daemon.log'),
    when='midnight',
    backupCount=7,
    encoding='utf-8'
)
log_handler.suffix = '%Y-%m-%d'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] data_daemon: %(message)s',
    handlers=[
        log_handler,
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('data_daemon')

# ── 重复日志去重过滤器（Task 3：预计算异常刷爆日志时，同内容只警告一次） ──
class _DedupLogFilter(logging.Filter):
    """按消息前缀去重，同内容只放行第一条 WARNING，后续降为 DEBUG"""
    def __init__(self):
        super().__init__()
        self._seen = set()
    def filter(self, record):
        if record.levelno < logging.WARNING:
            return True
        key = record.getMessage()[:80]
        if key in self._seen:
            record.levelno = logging.DEBUG
            record.levelname = 'DEBUG'
            return True
        self._seen.add(key)
        return True

logger.addFilter(_DedupLogFilter())

# ── Tushare 全局速率限制（防止误伤，确保 ≤5次/秒） ──
_ts_last_call = 0.0
_TS_MIN_INTERVAL = 0.2  # 5次/秒
# COL/RAW 卡死根治：Tushare SDK 底层无 socket 超时，若其 TCP 请求挂起不返回，
# 主循环 30s tick 会被拖死，导致后续采集/预计算停摆。故在统一入口对网络调用
# 做子线程超时：超时返回 None（上层判空跳过该次），主循环立即继续，不再阻塞。
_TS_CALL_TIMEOUT = 15.0

def _to_tushare_date(v):
    """Tushare 日期归一：YYYY-MM-DD → YYYYMMDD（Tushare 要求紧凑，横杠会静默空返回）
    428 日期整改 §阶段A：对 str/int 均尝试剥离 '-'; datetime/date 对象保持原样由上层处理。
    """
    if isinstance(v, str) and '-' in v:
        return v.replace('-', '')
    return v


def _ts(pro_func, *args, **kwargs):
    """带速率限制 + 网络超时保护的 Tushare API 调用

    速率限制在主线程做（保持 ≤5次/秒 节奏稳定）；实际网络调用放入子线程，
    超过 _TS_CALL_TIMEOUT 未返回视为卡死，返回 None 由上层判空跳过。
    428 日期整改 §阶段A：调用前对 trade_date/start_date/end_date 参数做紧凑归一
    （YYYY-MM-DD → YYYYMMDD，根治 Tushare 对横杠日期的静默空返回）。
    """
    global _ts_last_call
    # 日期参数紧凑归一（仅影响 Tushare 调用入口，不改存储/展示侧横杠格式）
    for _dkey in ('trade_date', 'start_date', 'end_date'):
        if _dkey in kwargs:
            kwargs[_dkey] = _to_tushare_date(kwargs[_dkey])
    elapsed = time.time() - _ts_last_call
    if elapsed < _TS_MIN_INTERVAL:
        time.sleep(_TS_MIN_INTERVAL - elapsed)
    _ts_last_call = time.time()
    import concurrent.futures as _cf
    _exe = _cf.ThreadPoolExecutor(max_workers=1)
    try:
        _fut = _exe.submit(pro_func, *args, **kwargs)
        result = _fut.result(timeout=_TS_CALL_TIMEOUT)
        # 428 日期整改 §阶段A：给定显式日期却返回空 → 记录告警，避免再被误判"外部不可用"
        if result is None:
            return None
        _has_explicit_date = any(k in kwargs for k in ('trade_date', 'start_date', 'end_date'))
        try:
            if _has_explicit_date and hasattr(result, 'empty') and result.empty:
                logger.warning(f"  [Tushare空返回] {getattr(pro_func, '__name__', str(pro_func))} "
                               f"参数显式却返回空（{ {k: kwargs.get(k) for k in ('trade_date', 'start_date', 'end_date') if k in kwargs} }）")
        except Exception:
            pass  # 告警为次要，不影响主流程
        return result
    except _cf.TimeoutError:
        logger.warning(f"  [Tushare超时] {getattr(pro_func, '__name__', str(pro_func))} "
                       f"超过 {_TS_CALL_TIMEOUT}s 未返回，跳过本次（不阻塞主循环）")
        return None
    finally:
        # 不等待超时线程：后台线程继续跑但结果丢弃，主流程立即继续（与 _run_with_timeout 一致）
        try:
            _exe.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

# 补充：stk_mins 极严限流（1次/分钟）
_ts_minute_last_call = 0.0
_TS_MINUTE_INTERVAL = 60.0
_TS_MINUTE_CALL_TIMEOUT = 60.0

def _ts_minute(pro_func, *args, **kwargs):
    """极严限流的分钟数据接口（1次/分钟），含网络超时保护"""
    global _ts_minute_last_call
    elapsed = time.time() - _ts_minute_last_call
    if elapsed < _TS_MINUTE_INTERVAL:
        time.sleep(_TS_MINUTE_INTERVAL - elapsed)
    _ts_minute_last_call = time.time()
    import concurrent.futures as _cf
    _exe = _cf.ThreadPoolExecutor(max_workers=1)
    try:
        _fut = _exe.submit(pro_func, *args, **kwargs)
        return _fut.result(timeout=_TS_MINUTE_CALL_TIMEOUT)
    except _cf.TimeoutError:
        logger.warning(f"  [分钟接口超时] {getattr(pro_func, '__name__', str(pro_func))} "
                       f"超过 {_TS_MINUTE_CALL_TIMEOUT}s 未返回，跳过本次")
        return None
    finally:
        try:
            _exe.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

# ── 全局引用 ──
_running = True
_retention_checked = False  # 保留期检查一次性标记（日终完成后执行一次；426号 S3/D1 原 _cleanup_done 语义扩展；修复 2026-08-04：原挂在 bool _running 上必然失败）
_ecm = None

def _ensure_ecm():
    """确保 _ecm 已初始化（支持从外部脚本调用管道函数）"""
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    return _ecm

_tushare_provider = None

def _get_tushare_provider():
    """惰性获取 TushareProvider 单例（424号§10决策④：_batch_* 收敛到适配层）"""
    global _tushare_provider
    if _tushare_provider is None:
        from app.data.tushare_provider import TushareProvider
        _tushare_provider = TushareProvider()
    return _tushare_provider
_last_step_counts = {}  # 371号P0#3：管道步骤成功计数
_jud_meta_cache = {}  # 371号JUD接入：{ts_code: enriched_meta_dict} 供 treemap_snapshot 读取
_market_stats_cache = {}  # 411号Phase 10：全市场级统计预计算，供BociasiQuadrantAnalyzer消费

# 425号 C-1：写入优先级状态机（HIGH > NORMAL > LOW）
# - HIGH：补采/补预计算（SIG/JUD 核心分析依赖），mootdx 盘中降频让路
# - NORMAL：日终同步/巡检（默认）
# - LOW：盘中采集（前端展示，容忍延迟）
_collect_priority = 'NORMAL'
_collect_priority_lock = threading.Lock()
# 425号 C-3：sync_requests 核心依赖类（SIG/JUD 分析依赖，HIGH 模式下优先消费；
# 前端展示类 full_* 等在 HIGH 窗口让路）。财务类目标 financial/history 库天然分库隔离，不触发降频。
_SYNC_CORE_TYPES = frozenset({'finance_report', 'stk_holder', 'margin',
                              'adj_factor', 'top10_holders'})


# ══════════════════════════════════════════════════════════
# 采集器管理
# ══════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════
# 425号：写入优先级调度（优先级状态机 / 核心滞后判定 / mootdx 降频 / HIGH 补采包装）
# ══════════════════════════════════════════════════════════

_PRIORITY_LEVELS = {'HIGH': 3, 'NORMAL': 2, 'LOW': 1}


def _set_collect_priority(level: str):
    """425号 C-1：设置写入优先级（HIGH/NORMAL/LOW），线程安全 + monitor 上报

    HIGH 窗口 = 核心补采进行中（run_integrity_check 回溯补采），mootdx 盘中让路、
    sync_requests 前端展示类延后；完成后恢复 NORMAL。
    """
    global _collect_priority
    if level not in _PRIORITY_LEVELS:
        logger.warning(f"未知优先级 {level}，忽略（保持 {_collect_priority}）")
        return
    with _collect_priority_lock:
        _collect_priority = level
    logger.info(f"[优先级] 采集/补采优先级 → {level}")
    try:
        from app.data.monitor import monitor
        monitor.record_metric('collect_priority_mode', _PRIORITY_LEVELS[level])
    except Exception as e:
        logger.debug(f"优先级指标上报失败: {e}")


def _get_collect_priority() -> str:
    """425号 C-1：读取当前写入优先级（线程安全）"""
    with _collect_priority_lock:
        return _collect_priority


def _core_data_stale() -> bool:
    """425号 C-1：核心数据（daily/basic/moneyflow/stk_limit）是否滞后 >1 天

    复用 _check_data_timeliness 的核心口径（355号规则4.2），返回判定供启动闭环使用。
    """
    today = datetime.now()
    core_tables = [
        ('daily_cache', '日线'),
        ('daily_basic_cache', '基本面'),
        ('moneyflow_cache', '资金流向'),
        ('stk_limit_cache', '涨跌停'),
    ]
    for table, label in core_tables:
        try:
            latest = _query_table(table, f"SELECT MAX(trade_date) FROM {table}")
            if latest:
                latest_date = (datetime.strptime(str(latest), '%Y-%m-%d')
                               if isinstance(latest, str) else latest)
                # 432号 R3：滞后按交易日口径（周末/节假日不计，周五数据周一开机不再误判 HIGH）
                lag_days = _lag_trading_days(latest_date, today)
                if lag_days > 1:
                    logger.warning(f"  [启动补采] {label}({table}) 滞后 {lag_days} 个交易日，需要 HIGH 补采")
                    return True
                logger.debug(f"  [启动补采] {label}({table}) 滞后 {lag_days} 个交易日 ✅")
        except Exception as e:
            logger.debug(f"  [启动补采] {label}时效性检查失败: {e}")
    return False


def _set_mootdx_backoff(active: bool):
    """425号 C-2：mootdx 盘中采集降频/恢复（interval 可变属性，不 stop 线程、保留连接）

    active=True：market_snapshot 5s→60s、minute_full 300s→600s（HIGH 补采窗口让路）；
    active=False：恢复原频率。仅当补采目标含 market_cache.db 时由调用方触发。
    """
    try:
        from app.data.mootdx_collector import mootdx_collector
        if active:
            mootdx_collector.set_interval('market_snapshot', 60)
            mootdx_collector.set_interval('minute_full', 600)
            logger.info("[优先级] mootdx 高频线程降频（market_snapshot 5s→60s, minute_full 300s→600s）")
        else:
            mootdx_collector.set_interval('market_snapshot', 5)
            mootdx_collector.set_interval('minute_full', 300)
            logger.info("[优先级] mootdx 高频线程恢复频率")
    except Exception as e:
        logger.warning(f"mootdx 降频/恢复失败: {e}")


def _run_priority_integrity_check(backfill_days: int = 1):
    """425号 C-1：数据完整性检查（HIGH 优先级包装，启动/整点巡检复用）

    核心数据滞后 >1 天 → 进入 HIGH 补采模式（mootdx 降频让路，目标含 market_cache.db）
    → run_integrity_check 补采 → 恢复 NORMAL。补采后的完整 QA 校验由 423 QA-CHECK
    在管道推进后自然衔接（不重复执行 run_quality_round）。
    无滞后时按普通模式执行（保持现状行为，无缺口快速返回）。
    """
    if _core_data_stale():
        _set_collect_priority('HIGH')
        _set_mootdx_backoff(True)
        try:
            run_integrity_check(backfill_days=backfill_days)
        finally:
            _set_mootdx_backoff(False)
            _set_collect_priority('NORMAL')
    else:
        run_integrity_check(backfill_days=backfill_days)

def _start_collectors():
    """启动 mootdx + AKShare 采集器

    355号方案规则10：非交易日停止不必要的采集器
    - 交易日：启动所有采集器
    - 非交易日：仅启动必要的数据维护采集器，停止实时采集器
    """
    ok = []

    # 检查是否为交易日
    is_trading_day = _is_market_day()
    if not is_trading_day:
        logger.info("非交易日，跳过实时采集器启动")

    # mootdx 采集器：仅交易日启动
    if is_trading_day:
        try:
            from app.data.mootdx_collector import mootdx_collector
            if mootdx_collector.start():
                ok.append('mootdx')
                logger.info("MootdxCollector 已启动（快照:东财HTTP, 分钟:mootdx）")
            else:
                logger.warning("MootdxCollector 启动失败（降级模式不可用）")
        except Exception as e:
            logger.warning(f"MootdxCollector 启动失败: {e}")
    else:
        logger.info("非交易日：MootdxCollector 跳过启动")

    # AKShare 采集器：仅交易日启动实时采集，非交易日可启动低频采集
    if is_trading_day:
        try:
            from app.data.akshare_collector import akshare_collector
            akshare_collector.start()
            ok.append('akshare')
            logger.info("AkshareCollector 已启动")
        except Exception as e:
            logger.warning(f"AkshareCollector 启动失败: {e}")
    else:
        logger.info("非交易日：AkshareCollector 跳过启动")

    return ok


def _stop_collectors():
    """停止所有采集器"""
    try:
        from app.data.mootdx_collector import mootdx_collector
        mootdx_collector.stop()
    except Exception:
        pass
    try:
        from app.data.akshare_collector import akshare_collector
        akshare_collector.stop()
    except Exception:
        pass
    logger.info("采集器已停止")


# ══════════════════════════════════════════════════════════
# 批量 Tushare API（替代逐只调用的低效方式）
# ══════════════════════════════════════════════════════════

def _batch_daily(trade_date: str) -> int:
    """全市场日线 — 1 次 API 调用"""
    import tushare as ts
    pro = ts.pro_api()
    df = _ts(pro.daily, trade_date=trade_date)
    if df is None or df.empty:
        return 0
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    _ecm.cache_daily_data(df)
    return len(df)


def _batch_daily_basic(trade_date: str) -> int:
    """全市场基本面 — 1 次 API 调用"""
    import tushare as ts
    pro = ts.pro_api()
    df = _ts(pro.daily_basic, trade_date=trade_date)
    if df is None or df.empty:
        return 0
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    _ecm.cache_daily_basic_data(df)
    return len(df)


def _compute_volume_ratio(trade_date: str) -> int:
    """计算量比并回写 daily_basic_cache

    量比 = 今日成交量 / 过去5日平均成交量
    计算层：数据到达后自动触发，符合红线规则3。
    """
    _ensure_pd()
    import pandas as pd
    from app.data.sharding_manager import sharding_manager
    try:
        _daily_conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_cache'))
        _basic_conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_basic_cache'))
        # 获取最近5个交易日
        dates = _daily_conn.execute(
            "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 5"
        ).fetchall()
        if not dates or len(dates) < 5:
            return 0
        date_list = [r[0] for r in dates]
        today = str(trade_date).replace('-', '')
        today = f'{today[:4]}-{today[4:6]}-{today[6:]}' if len(today) == 8 else str(trade_date)

        if today not in date_list:
            date_list.insert(0, today)

        # 获取这5天的 vol 数据
        placeholders = ','.join(['?'] * len(date_list))
        rows = _daily_conn.execute(
            f"SELECT ts_code, trade_date, vol FROM daily_cache WHERE trade_date IN ({placeholders})",
            date_list
        ).fetchall()
        if not rows:
            return 0

        df = pd.DataFrame(rows, columns=['ts_code', 'trade_date', 'vol'])
        df['vol'] = pd.to_numeric(df['vol'], errors='coerce').fillna(0)

        today_df = df[df['trade_date'] == today].copy()
        hist_df = df[df['trade_date'] != today].copy()

        if today_df.empty:
            return 0

        # 计算每只股票的5日均量
        hist_avg = hist_df.groupby('ts_code')['vol'].mean().reset_index()
        hist_avg.columns = ['ts_code', 'avg_vol']

        merged = today_df.merge(hist_avg, on='ts_code', how='left')
        merged['volume_ratio'] = merged.apply(
            lambda r: round(r['vol'] / r['avg_vol'], 2) if r['avg_vol'] > 0 else None, axis=1
        )

        # 回写到 daily_basic_cache
        updated = 0
        for _, r in merged.iterrows():
            if r['volume_ratio'] is not None:
                _basic_conn.execute(
                    "UPDATE daily_basic_cache SET volume_ratio = ? WHERE ts_code = ? AND trade_date = ?",
                    [r['volume_ratio'], r['ts_code'], today]
                )
                updated += 1
        _basic_conn.commit()
        if updated > 0:
            logger.info(f"  [量比] 自算回写 {updated} 条")
        return updated
    except Exception as e:
        logger.warning(f"  [量比] 计算失败: {e}")
        return 0


def _compute_relative_strength(trade_date: str = None) -> int:
    """438号缺口③：全市场个股相对强弱（双基准超额收益）批量计算

    对全市场活跃股票，按最新可用交易日计算 20d/60d 个股收益率，
    分别相对上证指数(000001.SH)/沪深300(000300.SH)求出超额收益，
    写入 relative_strength_cache（compute_cache.db），供 dim8/前端查询。

    收益率口径：N日收益率 = 最新收盘 / N交易日前收盘 - 1。
    """
    _ensure_pd()
    import pandas as pd
    from app.data.sharding_manager import sharding_manager
    try:
        conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_cache'))

        # 1) 定位最新交易日
        latest = conn.execute(
            "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return 0
        asof_date = latest[0]

        # 2) 取最近至多90个交易日作为20d/60d收益率窗口（442号缺陷⑤：原LIMIT 61 无容错，
        #    窗口内任何缺失日（如 08-19~21 全市场空洞）→ _n_day_ret 观测不足 → 60d 恒 None；
        #    扩至 90 日，dropna 后仍有 ≥61 观测，容忍零星缺失）
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 90"
        ).fetchall()][::-1]
        if len(dates) < 61:
            logger.info(f"  [相对强弱] 交易日不足({len(dates)}<61)，跳过")
            return 0
        placeholders = ','.join('?' * len(dates))

        # 3) 股票池：全市场日线代码，剔除指数代码（宽基 BROAD_INDEX_CODES + 申万 .SI）
        pool_rows = conn.execute(
            f"SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date IN ({placeholders})",
            dates
        ).fetchall()
        exclude = set(BROAD_INDEX_CODES)
        exclude |= set(SW_INDEX_CODES)
        stock_codes = [r[0] for r in pool_rows
                       if r[0] not in exclude and not r[0].endswith('.SI')]

        # 4) 加载窗口内全部收盘价（股票池 + 双基准）
        load_codes = stock_codes + ['000001.SH', '000300.SH']
        code_ph = ','.join('?' * len(load_codes))
        rows = conn.execute(
            f"SELECT ts_code, trade_date, close FROM daily_cache "
            f"WHERE trade_date IN ({placeholders}) AND ts_code IN ({code_ph}) "
            f"ORDER BY ts_code, trade_date",
            dates + load_codes
        ).fetchall()
        if not rows:
            return 0
        df = pd.DataFrame(rows, columns=['ts_code', 'trade_date', 'close'])

        def _n_day_ret(series: pd.Series, n: int) -> float:
            """series 为按时间升序的收盘价序列，返回 n 交易日收益（需 n+1 个观测）"""
            s = series.dropna()
            if len(s) < n + 1:
                return None
            return float(s.iloc[-1] / s.iloc[-1 - n] - 1)

        # 5) 双基准窗口内收益（000001.SH 上证 / 000300.SH 沪深300）
        bench_rows = df[df['ts_code'].isin(['000001.SH', '000300.SH'])]
        bench_closes = {}
        for code in ['000001.SH', '000300.SH']:
            sub = bench_rows.loc[bench_rows['ts_code'] == code, 'close']
            bench_closes[code] = {
                'ret_20d': _n_day_ret(sub, 20),
                'ret_60d': _n_day_ret(sub, 60),
            }

        # 6) 每股 20d/60d 收益率 → 每股映射
        ret_map = {}
        for code in stock_codes:
            sub = df.loc[df['ts_code'] == code, 'close'].dropna()
            if len(sub) < 21:
                continue
            ret_map[code] = (_n_day_ret(sub, 20), _n_day_ret(sub, 60))

        # 6.5) 跨截面 RPS 百分位（445 §6.1 dim3：RPS 被 RSI 顶替 → 补产出）
        #   知识库权威：RPS = 个股涨幅在全部股票涨幅排名中的位次值 (1-rank/n)*100，
        #   欧奈尔强势股狂飙前平均 RPS=87，A股 80 以上；RPS>85 → +1 分。
        #   pandas rank(pct=True) 取上涨排名百分位（涨幅越高 RPS 越高）：最高=100，最低趋近 0。
        ret20_series = pd.Series({c: r[0] for c, r in ret_map.items() if r[0] is not None})
        ret60_series = pd.Series({c: r[1] for c, r in ret_map.items() if r[1] is not None})
        # 无对比基准（无其它股票/全部缺数据）时 RPS 恒 None，由消费侧兜底不产结论
        rps20_by_code = None
        rps60_by_code = None
        if len(ret20_series) >= 2:
            rps20_by_code = (ret20_series.rank(pct=True) * 100).to_dict()
        if len(ret60_series) >= 2:
            rps60_by_code = (ret60_series.rank(pct=True) * 100).to_dict()

        # 7) 每股 × 每基准 → 写出多行（20d/60d 各独立计算：深度不足时该档为 None，
        #    不因缺 60d 历史而整行丢弃——新上市/长期停牌股仍产出 20d 超额；RPS 为市场截面，双基准行同值）
        out = []
        for code, (ret_20d, ret_60d) in ret_map.items():
            for bench, br in bench_closes.items():
                b20 = br.get('ret_20d'); b60 = br.get('ret_60d')
                ex20 = ret_20d - b20 if (ret_20d is not None and b20 is not None) else None
                ex60 = ret_60d - b60 if (ret_60d is not None and b60 is not None) else None
                rps20 = round(rps20_by_code[code], 2) if (rps20_by_code and code in rps20_by_code) else None
                rps60 = round(rps60_by_code[code], 2) if (rps60_by_code and code in rps60_by_code) else None
                out.append((asof_date, code, bench,
                            ret_20d, ret_60d, b20, b60, ex20, ex60, rps20, rps60))
        if out:
            written_stocks = len(set(r[1] for r in out))
            _ecm.cache_relative_strength(out)
            logger.info(f"  [相对强弱] asof={asof_date} 写入 {len(out)} 条 ({written_stocks} 股 × 2 基准)")
        return len(out)
    except Exception as e:
        logger.warning(f"  [相对强弱] 计算失败: {e}")
        return 0


def _batch_moneyflow(trade_date: str) -> int:
    """全市场资金流向 — 1 次 API 调用"""
    import tushare as ts
    pro = ts.pro_api()
    raw = _ts(pro.moneyflow, trade_date=trade_date)
    if raw is None or raw.empty:
        return 0
    df = raw.copy()
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    # 补齐 net_* 列
    for net_col, buy_col in [('net_lg_amount','buy_lg_amount'),
                              ('net_elg_amount','buy_elg_amount'),
                              ('net_sm_amount','buy_sm_amount')]:
        if net_col not in df.columns and buy_col in df.columns:
            sell_col = 'sell_' + buy_col[4:]
            df[net_col] = df[buy_col].fillna(0) - df.get(sell_col, pd.Series([0]*len(df))).fillna(0)
    _ecm.cache_moneyflow_data(df)
    return len(df)


def _backfill_moneyflow(days: int = 25) -> int:
    """启动时回填资金流历史数据（25天）"""
    _ensure_pd()
    import tushare as ts
    from datetime import timedelta
    pro = ts.pro_api()
    total = 0
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')

    # 检查已有数据量
    try:
        from app.data.sharding_manager import sharding_manager
        conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_cache'))
        existing = conn.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM moneyflow_cache"
        ).fetchone()[0]
    except Exception:
        existing = 0

    if existing >= days:
        logger.info(f"资金流回填: 已有{existing}天数据，跳过")
        return 0

    logger.info(f"资金流回填: 从{start_date}到{end_date}")
    try:
        raw = _ts(pro.moneyflow, start_date=start_date, end_date=end_date)
        if raw is None or raw.empty:
            logger.warning("资金流回填: API返回空")
            return 0
        df = raw.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
        for net_col, buy_col in [('net_lg_amount','buy_lg_amount'),
                                  ('net_elg_amount','buy_elg_amount'),
                                  ('net_sm_amount','buy_sm_amount')]:
            if net_col not in df.columns and buy_col in df.columns:
                sell_col = 'sell_' + buy_col[4:]
                df[net_col] = df[buy_col].fillna(0) - df.get(sell_col, pd.Series([0]*len(df))).fillna(0)
        _ecm.cache_moneyflow_data(df)
        total = len(df)
    except Exception as e:
        logger.warning(f"资金流回填失败: {e}")
    if total > 0:
        logger.info(f"资金流回填完成: {total} 条记录")
    return total


# 四大宽基指数代码（438号缺口①修复：HS300/000300.SH 为全系统相对强弱基准，读方 BenchmarkService 在用、此前写方遗漏未落日线）
BROAD_INDEX_CODES = [
    '000001.SH', '000300.SH', '399001.SZ', '399006.SZ', '899050.BJ',
]

# 申万一级行业指数代码（31 个，SW2021 全量）
# 438号缺口②修复：①接口改用 sw_daily（index_daily 不含 801*，致从源头取空）
# ②补齐 SW2021 一级行业：移除废弃 801020（子行业，数据源无），新增 801950/801960/801970/801980
SW_INDEX_CODES = [
    '801010.SI', '801030.SI', '801040.SI', '801050.SI', '801080.SI',
    '801110.SI', '801120.SI', '801130.SI', '801140.SI', '801150.SI',
    '801160.SI', '801170.SI', '801180.SI', '801200.SI', '801210.SI',
    '801230.SI', '801710.SI', '801720.SI', '801730.SI', '801740.SI',
    '801750.SI', '801760.SI', '801770.SI', '801780.SI', '801790.SI',
    '801880.SI', '801890.SI', '801950.SI', '801960.SI', '801970.SI',
    '801980.SI',
]

# 申万行业指数 Tushare 接口：sw_daily（index_daily 不含 801*）
# sw_daily 返回列 -> daily_cache 需要的 daily_cols 映射：
#   pct_change -> pct_chg；change/name/pe/pb/float_mv/total_mv 丢弃；vol->vol(万手? 由源定)、amount->amount
_SW_DAILY_COL_MAP = {
    'pct_change': 'pct_chg',
}
_SW_DAILY_KEEP = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg'}


def _batch_index_daily(trade_date: str) -> int:
    """四大指数日线 + 申万行业指数日线 — 批量 API 调用"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0

    # 四大宽基指数（含 HS300/000300.SH，438号缺口①）
    for code in BROAD_INDEX_CODES:
        try:
            raw = _ts(pro.index_daily, ts_code=code, trade_date=trade_date)
            if raw is None or raw.empty:
                continue
            df = raw.copy()
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            daily_cols = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg'}
            extra = [c for c in df.columns if c not in daily_cols]
            if extra:
                df = df.drop(columns=extra)
            _ecm.cache_daily_data(df)
            total += len(df)
        except Exception as e:
            logger.warning(f"指数 {code} 同步失败: {e}")

    # 申万一级行业指数（31 个，模块级常量 SW_INDEX_CODES）
    # 438号缺口②：接口改用 sw_daily（index_daily 不含 801*，从源头取空）
    sw_codes = SW_INDEX_CODES
    sw_count = 0
    for code in sw_codes:
        try:
            raw = _ts(pro.sw_daily, ts_code=code, trade_date=trade_date)
            if raw is None or raw.empty:
                continue
            df = raw.rename(columns=_SW_DAILY_COL_MAP)
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            extra = [c for c in df.columns if c not in _SW_DAILY_KEEP]
            if extra:
                df = df.drop(columns=extra)
            _ecm.cache_daily_data(df)
            sw_count += 1
        except Exception as e:
            logger.debug(f"行业指数 {code} 同步失败: {e}")
    if sw_count > 0:
        logger.info(f"  申万行业指数: {sw_count}/{len(sw_codes)} 个")
    total += sw_count
    return total


def _backfill_index_daily(days: int = 25) -> int:
    """启动时回填指数日线历史数据（25天）"""
    _ensure_pd()
    import tushare as ts
    from datetime import timedelta
    pro = ts.pro_api()
    total = 0
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')  # 多取10天覆盖周末

    # 检查已有数据量（按各宽基最少天数判定：任一指数（如 000300）缺失即触发回填，438号缺口①）
    try:
        from app.data.sharding_manager import sharding_manager
        conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_cache'))
        placeholders = ','.join('?' * len(BROAD_INDEX_CODES))
        existing = conn.execute(
            "SELECT MIN(cnt) FROM (SELECT COUNT(DISTINCT trade_date) AS cnt FROM daily_cache "
            f"WHERE ts_code IN ({placeholders}) GROUP BY ts_code)",
            BROAD_INDEX_CODES,
        ).fetchone()[0] or 0
    except Exception:
        existing = 0

    if existing >= days:
        logger.info(f"指数日线回填: 已有至少{existing}天数据（各宽基覆盖），跳过")
        return 0

    logger.info(f"指数日线回填: 从{start_date}到{end_date}")
    for code in BROAD_INDEX_CODES:
        try:
            raw = _ts(pro.index_daily, ts_code=code, start_date=start_date, end_date=end_date)
            if raw is None or raw.empty:
                continue
            df = raw.copy()
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            daily_cols = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg'}
            extra = [c for c in df.columns if c not in daily_cols]
            if extra:
                df = df.drop(columns=extra)
            _ecm.cache_daily_data(df)
            total += len(df)
        except Exception as e:
            logger.warning(f"指数回填 {code} 失败: {e}")
    if total > 0:
        logger.info(f"指数日线回填完成: {total} 条记录")
    return total


def _batch_stk_limit(trade_date: str) -> int:
    """全市场涨跌停 — 1 次 API 调用"""
    import tushare as ts
    pro = ts.pro_api()
    raw = _ts(pro.stk_limit, trade_date=trade_date)
    if raw is None or raw.empty:
        return 0
    df = raw.rename(columns={'up_limit': 'high_limit', 'down_limit': 'low_limit'})
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    _ecm.cache_stk_limit_data(df)
    return len(df)


def _batch_lhb(trade_date: str) -> int:
    """全市场龙虎榜 — 1 次 API 调用"""
    import tushare as ts
    pro = ts.pro_api()
    raw = _ts(pro.top_list, trade_date=trade_date)
    if raw is None or raw.empty:
        return 0
    df = raw.rename(columns={
        'pct_change': 'change_pct', 'l_buy': 'buy_amount',
        'l_sell': 'sell_amount', 'net_rate': 'buy_rate',
        'amount_rate': 'sell_rate'
    })
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    # 只保留 lhb_cache 表有定义的列，避免列冲突（Tushare 可能返回 close/amount 等额外列）
    lhb_cols = {'ts_code', 'trade_date', 'name', 'change_pct', 'buy_amount', 'sell_amount',
                'net_amount', 'buy_rate', 'sell_rate'}
    extra_cols = [c for c in df.columns if c not in lhb_cols]
    if extra_cols:
        df = df.drop(columns=extra_cols)
    _ecm.cache_lhb_data(df)
    return len(df)


def _batch_lhb_detail(trade_date: str) -> int:
    """全市场龙虎榜席位明细（278号方案）— 1 次 API 调用

    从 Tushare top_inst 获取各股票的买卖席位详情，
    写入 ECM lhb_detail_cache 表。
    """
    import tushare as ts
    pro = ts.pro_api()
    raw = _ts(pro.top_inst, trade_date=trade_date)
    if raw is None or raw.empty:
        return 0
    records = []
    for _, r in raw.iterrows():
        ts_code = r.get('ts_code', '')
        seat_name = r.get('exalter', '')
        if not ts_code or not seat_name:
            continue
        side_val = r.get('side', '0')
        side_label = 'buy' if str(side_val) == '0' else 'sell'
        records.append({
            'ts_code': ts_code,
            'trade_date': trade_date,
            'seat_name': seat_name,
            'seat_type': _classify_seat_name(seat_name),
            'buy_amount': float(r.get('buy', 0)),
            'sell_amount': float(r.get('sell', 0)),
            'net_amount': float(r.get('net_buy', 0) if r.get('net_buy') is not None else 0),
            'buy_rank': 0,
            'sell_rank': 0,
            'reason_category': str(r.get('reason', '')),
            'side': side_label,
            'data_source': 'tushare',
        })
    if records:
        _ecm.cache_lhb_detail_data(records)
    return len(records)


def _classify_seat_name(seat_name: str) -> str:
    """根据席位名称推断类型"""
    seat_lower = seat_name.lower()
    if any(kw in seat_lower for kw in [
        '机构专用', '机构', '基金', '自营', '社保', 'qfii',
        '资产管理', '资管', '保险', '信托', '年金',
    ]):
        return 'institution'
    return 'brokerage'


def _batch_margin(trade_date: str) -> int:
    """全市场融资融券个股明细 — 支持非交易日降级到最近交易日"""
    _ensure_pd()
    provider = _get_tushare_provider()
    raw = provider.get_margin_detail(trade_date)
    if raw is None or raw.empty:
        # 非交易日降级：使用 daily_cache 中的最新交易日（424号P0-1：改走分库权威副本）
        try:
            latest = _shard_query_df('daily_cache',
                "SELECT MAX(trade_date) FROM daily_cache").iloc[0, 0]
            if latest:
                # 统一格式为 YYYYMMDD（Tushare API 要求）
                fallback = str(latest).replace('-', '')
                if fallback != trade_date:
                    raw = provider.get_margin_detail(fallback)
        except Exception:
            pass
    if raw is None or raw.empty:
        return 0
    df = raw.copy()
    # margin_detail 返回 name/rqchl 列，表结构无这些字段
    for col in ['name', 'rqchl']:
        if col in df.columns:
            df = df.drop(columns=[col])
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    _ecm.cache_margin_data(df)
    return len(df)


def _batch_margin_range(start_date: str, end_date: str) -> int:
    """363号F55-3修复：支持日期范围的融资融券增量回补

    424号P0-1修复：兼容 YYYYMMDD 与 YYYY-MM-DD 两种日期格式。
    调用处 run_integrity_check 传 today（YYYYMMDD），原实现 strptime('%Y-%m-%d')
    抛 ValueError 被外层 except 吞掉 → 范围补采每次触发但永不执行。
    """
    from datetime import datetime as _dt, timedelta
    start = _dt.strptime(str(start_date).replace('-', ''), '%Y%m%d')
    end = _dt.strptime(str(end_date).replace('-', ''), '%Y%m%d')
    total = 0
    current = start
    while current <= end:
        date_str = current.strftime('%Y%m%d')
        try:
            added = _batch_margin(date_str)
            total += added
        except Exception as e:
            logger.debug(f"  融资融券 {date_str} 补采失败: {e}")
        current += timedelta(days=1)
    return total


def _batch_concept(trade_date: str = None) -> int:
    """全市场概念板块及成分股 — 2 次 API 调用（Tushare + AKShare 降级）"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    # 1. 获取概念列表
    try:
        concept_list = _ts(pro.concept)
    except Exception as e:
        logger.info(f"Tushare concept() 异常({e})，切换 AKShare 降级...")
        concept_list = None
    if concept_list is not None and not concept_list.empty:
        # Tushare 成功路径
        detail_records = []
        for _, row in concept_list.iterrows():
            concept_code = row.get('code') or row.get('concept_code')
            concept_name = row.get('name') or row.get('concept_name')
            if not concept_code:
                continue
            try:
                detail = _ts(pro.concept_detail, id=concept_code)
                if detail is not None and not detail.empty:
                    for _, d in detail.iterrows():
                        detail_records.append({
                            'ts_code': d.get('ts_code'),
                            'concept_name': concept_name or concept_code,
                            'concept_code': concept_code,
                        })
            except Exception as e:
                logger.debug(f"概念 {concept_code} 详情获取失败: {e}")
        try:
            _ecm.cache_concept_data(concept_list)
        except Exception as e:
            logger.warning(f"概念列表缓存失败: {e}")
        if detail_records:
            _ecm.cache_concept_data(pd.DataFrame(detail_records))
        total = len(concept_list) + len(detail_records)
        logger.info(f"概念板块同步完成(Tushare): {len(concept_list)} 个概念, {len(detail_records)} 条成分股映射")
        return total

    # 降级：AKShare 概念板块
    logger.info("Tushare concept() 返回空，切换 AKShare 降级...")
    try:
        import akshare as ak
        board_df = ak.stock_board_concept_name_em()
        if board_df is None or board_df.empty:
            raise ValueError("AKShare 返回空")
        # AKShare 列名: '板块名称', '成分股数量', ...
        concept_records = []
        detail_records = []
        concept_count = 0
        code_idx = 0
        for _, row in board_df.iterrows():
            name = row.get('板块名称', '')
            if not name:
                continue
            code = f"AK_CONCEPT_{code_idx}"
            code_idx += 1
            concept_count += 1
            concept_records.append({
                'ts_code': code,
                'concept_name': name,
                'concept_code': code,
            })
            # 只取前 50 个概念获取成分股（避免 AKShare 限流）
            if concept_count <= 50:
                try:
                    hist = ak.stock_board_concept_hist_em(symbol=name)
                    if hist is not None and not hist.empty and '代码' in hist.columns:
                        for _, h in hist.iterrows():
                            detail_records.append({
                                'ts_code': str(h['代码']) + '.SH' if str(h['代码']).startswith('6') else str(h['代码']) + '.SZ',
                                'concept_name': name,
                                'concept_code': code,
                            })
                except Exception as e:
                    logger.debug(f"AKShare 概念 {name} 成分股获取失败: {e}")
                    continue
        if concept_records:
            _ecm.cache_concept_data(pd.DataFrame(concept_records))
        if detail_records:
            _ecm.cache_concept_data(pd.DataFrame(detail_records))
        total = concept_count + len(detail_records)
        logger.info(f"概念板块同步完成(AKShare): {concept_count} 个概念, {len(detail_records)} 条成分股映射")
        return total
    except Exception as e:
        logger.warning(f"AKShare 概念板块降级失败: {e}")
        # 最后降级：使用 stock_basic 行业分类替代概念数据
        logger.info("最后降级：使用 stock_basic 行业分类...")
        try:
            stock_df = _ts(pro.stock_basic, fields='ts_code,name,industry,area')
            if stock_df is not None and not stock_df.empty and 'industry' in stock_df.columns:
                industry_records = []
                for _, row in stock_df.iterrows():
                    ind = row.get('industry', '')
                    ts_code = row.get('ts_code', '')
                    if ind and ts_code:
                        industry_records.append({
                            'ts_code': ts_code,
                            'concept_name': ind,
                            'concept_code': f"INDUSTRY_{ind}",
                        })
                if industry_records:
                    _ecm.cache_concept_data(pd.DataFrame(industry_records))
                    logger.info(f"行业分类替代概念数据: {len(industry_records)} 条, {stock_df['industry'].nunique()} 个行业")
                    return len(industry_records)
        except Exception as e2:
            logger.warning(f"stock_basic 行业降级也失败: {e2}")
        return 0


def _batch_index_member() -> int:
    """指数成分股 — 对主要指数逐一查询（Tushare + AKShare 降级）"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    main_indices = ['000300.SH', '000016.SH', '000905.SH', '399006.SZ']
    tushare_failed = []
    for code in main_indices:
        try:
            raw = _ts(pro.index_member, ts_code=code)
            if raw is not None and not raw.empty:
                df = raw.copy()
                if 'in_date' in df.columns:
                    df['in_date'] = pd.to_datetime(df['in_date']).dt.date
                _ecm.cache_index_member_data(df)
                total += len(df)
            else:
                tushare_failed.append(code)
        except Exception as e:
            logger.warning(f"Tushare 指数 {code} 成分股同步失败: {e}")
            tushare_failed.append(code)

    # 对 Tushare 失败的指数，用 AKShare 降级
    if tushare_failed:
        logger.info(f"Tushare index_member 返回空，切换 AKShare 降级: {tushare_failed}")
        try:
            import akshare as ak
            akshare_index_map = {
                '000300.SH': '000300', '000016.SH': '000016',
                '000905.SH': '000905', '399006.SZ': '399006',
            }
            for code in tushare_failed:
                try:
                    ak_code = akshare_index_map.get(code, code.replace('.SH', '').replace('.SZ', ''))
                    raw_df = ak.index_stock_cons(symbol=ak_code)
                    if raw_df is not None and not raw_df.empty:
                        # 映射AKShare中文列名到标准列名
                        ak_df = pd.DataFrame()
                        ak_df['index_code'] = code
                        # 品种代码 → ts_code（补全后缀）
                        if '品种代码' in raw_df.columns:
                            ak_df['ts_code'] = raw_df['品种代码'].apply(
                                lambda x: str(x) + '.SH' if str(x).startswith('6') else str(x) + '.SZ'
                            )
                        elif 'stock_code' in raw_df.columns:
                            ak_df['ts_code'] = raw_df['stock_code']
                        # 品种名称 → coname
                        if '品种名称' in raw_df.columns:
                            ak_df['coname'] = raw_df['品种名称']
                        elif 'name' in raw_df.columns:
                            ak_df['coname'] = raw_df['name']
                        elif 'stock_name' in raw_df.columns:
                            ak_df['coname'] = raw_df['stock_name']
                        # 纳入日期 → in_date
                        if '纳入日期' in raw_df.columns:
                            ak_df['in_date'] = raw_df['纳入日期']
                        if 'in_date' in ak_df.columns:
                            ak_df['in_date'] = pd.to_datetime(ak_df['in_date']).dt.date
                        _ecm.cache_index_member_data(ak_df)
                        ak_total = len(ak_df)
                        total += ak_total
                        logger.info(f"AKShare 指数 {code} 成分股: {ak_total} 条")
                except Exception as e:
                    logger.warning(f"AKShare 指数 {code} 成分股获取失败: {e}")
        except Exception as e:
            logger.warning(f"AKShare index_stock_cons 降级失败: {e}")

    return total


def _batch_win_rate() -> int:
    """策略胜率计算 — 从历史信号计算，不调外部 API"""
    _ensure_pd()
    try:
        from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
        manager = PrecomputeIndicatorManager(_ecm)
        win_df = manager.compute_win_rates()
        if win_df is not None and not win_df.empty:
            _ecm.cache_win_rates(win_df)
            return len(win_df)
        else:
            logger.info("胜率计算: 无足够历史信号")
    except Exception as e:
        logger.warning(f"胜率计算失败: {e}")
    return 0


def _batch_fina_indicator(trade_date: str = None) -> int:
    """全市场财务指标 — 后台低优任务

    355号方案修复：Tushare fina_indicator接口需要ts_code参数，
    改为逐只获取或使用period参数获取最新一期。
    """
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    n_skip = 0
    target = _target_fin_period()  # 428 P1-1：本地已有目标报告期则跳过
    try:
        # 方案1：使用period参数获取最近一期（如果支持）
        if trade_date:
            # 尝试使用period参数
            try:
                df = _ts(pro.fina_indicator, period=trade_date)
                if df is not None and not df.empty:
                    for col in ['end_date', 'ann_date']:
                        if col in df.columns:
                            df[col] = pd.to_datetime(df[col]).dt.date
                    if _ecm.cache_fina_indicator_data(df):
                        total = len(df)
                        logger.info(f"  [财务指标] 同步 {total} 条")
                    else:
                        logger.warning("  [财务指标] period 写入失败（不计入完成数）")
                    return total
            except Exception as e:
                logger.debug(f"  [财务指标] period参数失败，尝试逐只获取: {e}")

        # 方案2：逐只获取（降级方案）
        # 获取股票列表
        try:
            stocks = pro.stock_basic(exchange='', list_status='L')
            if stocks is not None and not stocks.empty:
                stock_codes = stocks['ts_code'].tolist()[:100]  # 限制100只股票
                logger.info(f"  [财务指标] 逐只获取 {len(stock_codes)} 只股票")

                fail = 0
                for code in stock_codes:
                    # 428 P1-1：本地已有目标报告期则跳过（次新股/新披露补采走 API）
                    if _finance_covers_period('fina_indicator_cache', code, target):
                        n_skip += 1
                        continue
                    try:
                        df = _ts(pro.fina_indicator, ts_code=code)
                        if df is not None and not df.empty:
                            # 获取最新的财务指标
                            df_sorted = df.sort_values('end_date', ascending=False)
                            latest = df_sorted.iloc[0:1]  # 只取最新一期

                            for col in ['end_date', 'ann_date']:
                                if col in latest.columns:
                                    latest[col] = pd.to_datetime(latest[col]).dt.date

                            # 426号 P2-2：按写入结果计数，写失败不再虚报"完成 N 条"
                            if _ecm.cache_fina_indicator_data(latest):
                                total += 1
                            else:
                                fail += 1
                    except Exception:
                        pass  # 跳过失败的股票

                logger.info(f"  [财务指标] 逐只同步完成，共 {total} 条" +
                            (f"，写入失败 {fail} 条" if fail else "") +
                            (f"，跳过 {n_skip} 只已有最新期" if n_skip else ""))
        except Exception as e:
            logger.warning(f"  [财务指标] 获取股票列表失败: {e}")

    except Exception as e:
        logger.warning(f"  [财务指标] 批量同步失败: {e}")
    return total


def _find_kline_insufficient(threshold: int = 130, limit: int = 5000) -> list:
    """320号 F1：找出 daily_cache K 线不足 threshold 根的股票

    策略引擎需要 ≥130 根 K 线（缠论/量价门槛），不足则机会图谱标签与
    九层解读的 K 线依赖维度同时失效。
    432号 R5：排除非个股代码（申万指数 .SI / 测试码 .TEST / 深市指数段 399*.SZ /
    上证指数 000*.SH / 北证指数 899*.BJ）——pro.daily 对它们必然空返回，白耗配额。
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    try:
        rows = _shard_fetchall(
            'daily_cache',
            "SELECT ts_code, COUNT(*) cnt FROM daily_cache "
            "WHERE ts_code NOT LIKE '%.SI' AND ts_code NOT LIKE '%.TEST' "
            "AND ts_code NOT LIKE '399%.SZ' AND ts_code NOT LIKE '000%.SH' "
            "AND ts_code NOT LIKE '899%.BJ' "
            "GROUP BY ts_code HAVING cnt < ? LIMIT ?",
            [threshold, limit]
        )
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning(f"_find_kline_insufficient failed: {e}")
        return []


def _backfill_kline_history(ts_code: str, years: int = 5) -> int:
    """320号 F1：补采单股历史日线（pro.daily 指定 ts_code + 近 years 年）

    用于 K 线深度不足的股票（如 600519 仅 1 行），补采后满足策略引擎 ≥130 根门槛。
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    start = (datetime.now() - timedelta(days=years * 365)).strftime('%Y%m%d')
    try:
        raw = _ts(pro.daily, ts_code=ts_code, start_date=start, end_date=datetime.now().strftime('%Y%m%d'))
        if raw is None or raw.empty:
            logger.info(f"  [K线补采] {ts_code} 无返回（可能停牌/次新）")
            return 0
        df = raw.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
        # 按表列过滤（cache_daily_data 内部已处理，但避免多余警告）
        _ecm.cache_daily_data(df)
        logger.info(f"  [K线补采] {ts_code} 写入 {len(df)} 条")
        return len(df)
    except Exception as e:
        logger.warning(f"  [K线补采] {ts_code} 失败: {e}")
        return 0


def _backfill_all_insufficient_kline(threshold: int = 130, max_codes: int = 200):
    """320号 F1：批量补采 K 线不足股票（完整性检查内调用，后台低优）"""
    codes = _find_kline_insufficient(threshold=threshold, limit=max_codes)
    if not codes:
        logger.info("  [K线深度] 全部股票 K 线充足 ✅")
        return 0
    logger.info(f"  [K线深度] {len(codes)} 只 K 线<{threshold} 根，开始补采...")
    total = 0
    for i, code in enumerate(codes):
        total += _backfill_kline_history(code)
        if (i + 1) % 50 == 0:
            logger.info(f"    [K线补采] 进度 {i+1}/{len(codes)}")
    logger.info(f"  [K线深度] 补采完成，共写入 {total} 条")
    return total


def _batch_adj_factor() -> int:
    """全市场复权因子 — 批量按 trade_date（432号 R2：最近交易日多日回退）

    原实现批量查询用"昨天"（周末/节假日必空）→ 恒降级逐只重采前 500 只全历史
    （约 250 万条/次）。现按最近 N 个交易日逐日试批量，首个有数据的日期即写；
    不再保留降级逐只路径（批量按日无数据时逐只也必然无数据，降级纯浪费配额）。
    """
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    for i in range(10):  # 最近 10 个交易日逐日试（覆盖长假期后多日缺口）
        trade_d = _recent_trade_date(i)
        if trade_d is None:
            break
        try:
            raw = _ts(pro.adj_factor, trade_date=trade_d)
            if raw is not None and not raw.empty:
                df = raw.copy()
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                _ecm.cache_adj_factor_data(df)
                return len(df)
        except Exception:
            continue
    logger.info("  [复权因子] 最近交易日无数据，跳过本次补采")
    return 0


def _batch_top10_holders() -> int:
    """全市场前十大股东 — 批量按 end_date（替代逐只500次）

    实测 pro.top10_holders(end_date=date) 可返回全市场数据。
    不再逐只 Tushare 查询，1 次 API 请求完成。
    """
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    end_dt = (datetime.now().replace(day=1) - timedelta(days=30)).strftime('%Y%m%d')
    try:
        raw = _ts(pro.top10_holders, end_date=end_dt)
        if raw is not None and not raw.empty:
            df = raw.copy()
            for col in ['end_date', 'ann_date']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col]).dt.date
            _ecm.cache_top10_holders(df)
            return len(df)
    except Exception:
        pass
    # 降级：逐只
    codes = _shard_fetchall('daily_cache', "SELECT DISTINCT ts_code FROM daily_cache")
    codes = [r[0] for r in codes[:500]]
    total = 0
    for code in codes:
        try:
            raw = _ts(pro.top10_holders, ts_code=code)
            if raw is not None and not raw.empty:
                df = raw.copy()
                for col in ['end_date', 'ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                _ecm.cache_top10_holders(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [前十大股东] 降级逐只同步 {total} 条")
    return total


def _batch_stk_holder() -> int:
    """全市场股东人数 — 批量按 end_date（替代逐只500次）

    实测 pro.stk_holdernumber(end_date=date) 可返回全市场数据。
    """
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    end_dt = (datetime.now().replace(day=1) - timedelta(days=30)).strftime('%Y%m%d')
    try:
        raw = _ts(pro.stk_holdernumber, end_date=end_dt)
        if raw is not None and not raw.empty:
            df = raw.copy()
            for col in ['end_date', 'ann_date']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col]).dt.date
            _ecm.cache_stk_holder_data(df)
            return len(df)
    except Exception:
        pass
    # 降级：逐只
    codes = _shard_fetchall('daily_cache', "SELECT DISTINCT ts_code FROM daily_cache")
    codes = [r[0] for r in codes[:500]]
    total = 0
    for code in codes:
        try:
            raw = _ts(pro.stk_holdernumber, ts_code=code)
            if raw is not None and not raw.empty:
                df = raw.copy()
                for col in ['end_date', 'ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                _ecm.cache_stk_holder_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [股东人数] 降级逐只同步 {total} 条")
    return total


def _batch_finance_report(codes: list = None) -> int:
    """全市场扩展财务指标（273a 排雷指标）

    后台低优，每次最多处理 500 只。
    使用 pro.fina_indicator 带 FINA_FIELDS_EXTENDED 字段集。

    Args:
        codes: 指定股票列表（None 则取全市场前 500 只）。
    """
    _ensure_pd()
    provider = _get_tushare_provider()
    if codes is None:
        codes = _shard_fetchall('daily_cache', "SELECT DISTINCT ts_code FROM daily_cache")
        codes = [r[0] for r in codes[:500]]
    total = 0
    for code in codes:
        try:
            raw = provider.get_fina_indicator_extended(code)
            # provider 返回 list（to_dict('records')），非 DataFrame
            if raw:
                df = pd.DataFrame(raw)
                for col in ['end_date', 'ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                _ecm.cache_finance_report_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [扩展财务] 同步 {total} 条 (共 {len(codes)} 只)")
    return total


# ── 441号D·通道②增强：个股级素材覆盖巡检 ─────────────────────
# run_integrity_check 的 batch_background 原实现仅空表触发批量补采，
# 抓不到「非空表 + 个股缺失」（如 stk_holder 曾缺 456 只深市个股）。
# 现将单只补采辅助提取为模块级，供「按 active_code 覆盖核对」复用。

def _sync_single_finance(code: int = 0) -> int:
    """单只扩展财务指标补采（复用 429号 单只路径）"""
    _ensure_ecm()
    provider = _get_tushare_provider()
    raw = provider.get_fina_indicator_extended(code)
    if raw:
        import pandas as _pd
        df = _pd.DataFrame(raw)
        for col in ['end_date', 'ann_date']:
            if col in df.columns:
                df[col] = _pd.to_datetime(df[col]).dt.date
        _ecm.cache_finance_report_data(df)
        return len(df)
    return 0


def _sync_single_stk_holder(code: int = 0) -> int:
    """单只股东人数补采（复用 429号 单只路径）"""
    _ensure_ecm()
    provider = _get_tushare_provider()
    raw = provider.get_stk_holdernumber(code)
    if raw:
        import pandas as _pd
        df = _pd.DataFrame(raw)
        for col in ['end_date', 'ann_date']:
            if col in df.columns:
                df[col] = _pd.to_datetime(df[col]).dt.date
        _ecm.cache_stk_holder_data(df)
        return len(df)
    return 0


def _sync_single_top10_holders(code: int = 0) -> int:
    """单只前十大股东补采（复用 429号 单只路径）"""
    _ensure_ecm()
    provider = _get_tushare_provider()
    raw = provider.get_top10_holders(code)
    if raw:
        import pandas as _pd
        df = _pd.DataFrame(raw)
        for col in ['end_date', 'ann_date']:
            if col in df.columns:
                df[col] = _pd.to_datetime(df[col]).dt.date
        _ecm.cache_top10_holders(df)
        return len(df)
    return 0


# 覆盖巡检表 → (cache表, 单只补采函数)
# 与 batch_background 保持一致的三张表：非空表时逐 active_code 核对缺失并单只补采。
_COVERAGE_RECONCILE = [
    ('top10_holders_cache',  _sync_single_top10_holders,  '前十大股东'),
    ('stk_holder_cache',     _sync_single_stk_holder,     '股东人数'),
    ('finance_report_cache', _sync_single_finance,        '扩展财务'),
]


def _reconcile_cache_coverage(max_codes: int = 40) -> dict:
    """按 active_code 覆盖核对三张富字段素材表，缺失的个股单只补采。

    441号D·通道②增强：原 batch_background 仅空表触发批量补采（抓不到「非空表+个股缺失」）。
    本函数取全管道股票池（_get_active_codes，441号A 已剔指数），对照各 cache 表的
    DISTINCT ts_code 集合求差集，对缺失个股按 MAX 上限逐只单只补采，避免单 tick 打爆
    Tushare 积分（上限受 max_codes 限流，剩余缺口留待下轮巡检）。

    Returns:
        {表标签: 补采只数}
    """
    _ensure_ecm()
    results = {}
    try:
        active = _get_active_codes()
    except Exception as e:
        logger.warning(f"覆盖巡检：获取 active 股票池失败: {e}")
        return results
    if not active:
        logger.info("覆盖巡检：active 池为空，跳过")
        return results
    for table, sync_fn, label in _COVERAGE_RECONCILE:
        try:
            # 读分库该 cache 表已覆盖股票集合（非空表才做个股覆盖核对）
            covered_rows = _shard_fetchall(
                table, f"SELECT DISTINCT ts_code FROM \"{table}\"")
            covered = {r[0] for r in covered_rows}
            missing = [c for c in active if c not in covered]
            if not missing:
                logger.info(f"  [{label}] 覆盖完整（{len(covered)} 只）")
                results[label] = 0
                continue
            # 单只补采缺失个股，受 max_codes 限流
            _done = 0
            for code in missing[:max_codes]:
                try:
                    sync_fn(code)
                    _done += 1
                except Exception as e:
                    logger.warning(f"  [{label}] 单只覆盖补采失败 {code}: {e}")
            logger.info(f"  [{label}] 缺失 {len(missing)} 只，本轮单只补采 {_done} 只（上限 {max_codes}）")
            results[label] = _done
        except Exception as e:
            logger.warning(f"  [{label}] 覆盖巡检失败: {e}")
    return results


def _batch_pattern_score(trade_date: str):
    """日终批量计算形态评分（353/358号方案）

    对全市场活跃股票运行 PatternEngine.evaluate()，
    结果写入 pattern_score_cache 供前端直接读取。

    Args:
        trade_date: 交易日期（YYYYMMDD 或 YYYY-MM-DD）
    """
    from app.engine.patterns.engine import PatternEngine

    engine = PatternEngine()
    _ensure_pd()

    # 格式化日期为 YYYY-MM-DD（cache_pattern_score 要求）
    td_str = str(trade_date).replace('-', '')
    if len(td_str) == 8:
        td_fmt = f'{td_str[:4]}-{td_str[4:6]}-{td_str[6:]}'
    else:
        td_fmt = str(trade_date)

    # 获取当日有数据的所有股票
    try:
        rows = _shard_fetchall(
            'daily_cache', "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?", [td_fmt])
        if not rows:
            # 非交易日回退：用最新交易日
            row = _shard_fetchall(
                'daily_cache', "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
            if row:
                td_fmt = row[0][0]
                rows = _shard_fetchall(
                    'daily_cache', "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?", [td_fmt])
                logger.info(f"  [形态评分] 今日无数据，回退到最近交易日: {td_fmt}")
    except Exception as e:
        logger.warning(f"  [形态评分] 查询股票列表失败: {e}")
        return

    codes = [r[0] for r in rows]
    if not codes:
        logger.info("  [形态评分] 无活跃股票，跳过")
        return

    logger.info(f"  [形态评分] 开始计算 {len(codes)} 只股票...")

    computed = 0
    skipped = 0
    errors = 0

    for ts_code in codes:
        try:
            df = _ecm.get_cached_daily(ts_code)
            if df.empty or len(df) < 20:
                skipped += 1
                continue

            score, details = engine.evaluate(df)
            _ecm.cache_pattern_score(ts_code, td_fmt, score, details)
            computed += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.debug(f"  [形态评分] {ts_code} 计算失败: {e}")
            continue

    logger.info(f"  [形态评分] 完成: 计算 {computed} 只, 跳过 {skipped} 只, 错误 {errors} 只")


def _batch_stock_list() -> int:
    """全市场股票列表同步（通过 DataManager）"""
    try:
        from app.data import DataManager
        dm = DataManager()
        from app.models import Stock
        stocks = dm.tushare.get_stock_list()
        if not stocks:
            return 0
        for stock in stocks:
            existing = Stock.query.get(stock['ts_code'])
            list_date = stock.get('list_date')
            if existing:
                existing.symbol = stock['symbol']
                existing.name = stock['name']
                existing.industry = stock.get('industry')
                existing.market = stock.get('market')
                if list_date:
                    existing.list_date = datetime.strptime(list_date, '%Y%m%d').date()
            else:
                new_stock = Stock(
                    ts_code=stock['ts_code'],
                    symbol=stock['symbol'],
                    name=stock['name'],
                    industry=stock.get('industry'),
                    market=stock.get('market'),
                    list_date=datetime.strptime(list_date, '%Y%m%d').date() if list_date else None
                )
                from app import db
                db.session.add(new_stock)
        from app import db
        db.session.commit()
        logger.info(f"股票列表同步: {len(stocks)} 只")
        return len(stocks)
    except Exception as e:
        logger.warning(f"股票列表同步失败: {e}")
        return 0


def _target_fin_period() -> str:
    """推导 COL-7 财务增量目标报告期（428 阶段 P1-1）

    按"披露截止日已过的最新报告期"推导，而非简单的当前季度末：
    - 1~4月    → 上年 12-31（年报，4-30 截止已过）
    - 5~8月    → 当年 06-30（半年报，8-31 截止窗口）
    - 9~12月   → 当年 09-30（三季报，10-31 截止已过 / 或已披露完毕）

    依据：daily_cache 最新交易日所在月份决定当前已披露完成的最新报告期。
    例：09-11 → 当年 09-30（三季报已披露）；04-15 → 上年 12-31（年报刚过截止）。
    返回 YYYY-MM-DD 横杠格式（与存储侧 end_date 一致）。

    注：若某股未按时披露，其 MAX(end_date) 停在更早期 → 会被判定需补采，逻辑自洽。
    """
    try:
        latest = _shard_fetchall(
            'daily_cache',
            "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
        if not latest or not latest[0] or not latest[0][0]:
            return None
        s = str(latest[0][0]).replace('-', '')
        year = int(s[:4])
        month = int(s[4:6])
        if month <= 4:
            # 1~4月：当年年报截止(4-30)过后，取上年 12-31 年报
            return f'{year - 1}-12-31'
        if month <= 7:
            # 5~7月：半年报披露窗口（8-31截止），取当年 06-30
            return f'{year}-06-30'
        if month <= 10:
            # 8~10月：三季报披露窗口（10-31截止），取当年 09-30
            # 注：8月半年报刚截止期，实际最新仍可能是 06-30（三季报未到）——
            # 但 8月 daily 数据多在半年报披露期内，用 09-30 会过早；改为 06-30。
            if month == 8:
                return f'{year}-06-30'
            return f'{year}-09-30'
        # 11~12月：三季报已披露完毕，取当年 09-30
        return f'{year}-09-30'
    except Exception as e:
        logger.warning(f"[财务增量] 目标报告期推导失败: {e}")
        return None


def _finance_covers_period(table: str, code: str, target_period: str) -> bool:
    """本地该股是否已有目标报告期数据（428 阶段 P1-1 增量跳过判定）

    对 income/balancesheet/cashflow 用 MAX(end_date) == 目标报告期 判定已是最新，
    相等则跳过该股 API 拉取（二次运行 CALL 量减 90%+）。
    target_period 传 _target_fin_period() 返回值（YYYY-MM-DD 或 YYYYMMDD）。
    """
    if not target_period:
        return False
    try:
        rows = _shard_fetchall(
            table, f"SELECT MAX(end_date) FROM {table} WHERE ts_code=?", [code])
        if not rows or rows[0][0] is None:
            return False
        local = str(rows[0][0]).replace('-', '')
        target = str(target_period).replace('-', '')
        return local == target
    except Exception:
        return False

def _batch_income_recent(codes: list = None) -> int:
    """增量同步最近一期利润表 — 后台低优

    Args:
        codes: 指定股票列表（None 则取全市场前 500 只）。
    """
    _ensure_pd()
    provider = _get_tushare_provider()
    total = 0
    n_skip = 0
    target = _target_fin_period()  # 428 P1-1：本地已有目标报告期则跳过
    if codes is None:
        codes = _shard_fetchall('daily_cache', "SELECT DISTINCT ts_code FROM daily_cache")
        codes = [r[0] for r in codes[:500]]  # 限500只，避免过长
    for code in codes:
        if _finance_covers_period('income_cache', code, target):
            n_skip += 1
            continue
        try:
            raw = provider.get_income(code)
            # provider 返回 list（to_dict('records')），非 DataFrame
            if raw:
                df = pd.DataFrame(raw)
                if 'end_date' in df.columns:
                    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                if 'ann_date' in df.columns:
                    df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                _ecm.cache_income_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [利润表] 增量同步 {total} 条 (共 {len(codes)} 只"
                + (f"，跳过 {n_skip} 只已有最新期" if n_skip else ")")
                + ")")
    return total


def _batch_balancesheet(codes: list = None) -> int:
    """增量同步最近一期资产负债表 — 后台低优

    Args:
        codes: 指定股票列表（None 则取全市场前 500 只）。
    """
    _ensure_pd()
    provider = _get_tushare_provider()
    total = 0
    n_skip = 0
    target = _target_fin_period()  # 428 P1-1
    if codes is None:
        codes = _shard_fetchall('daily_cache', "SELECT DISTINCT ts_code FROM daily_cache")
        codes = [r[0] for r in codes[:500]]
    for code in codes:
        if _finance_covers_period('balancesheet_cache', code, target):
            n_skip += 1
            continue
        try:
            raw = provider.get_balancesheet(code)
            # provider 返回 list（to_dict('records')），非 DataFrame
            if raw:
                df = pd.DataFrame(raw)
                for col in ['end_date', 'ann_date', 'f_ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                _ecm.cache_balancesheet_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [资产负债表] 同步 {total} 条 (共 {len(codes)} 只"
                + (f"，跳过 {n_skip} 只已有最新期" if n_skip else ")")
                + ")")
    return total


def _batch_cashflow(codes: list = None) -> int:
    """增量同步最近一期现金流量表 — 后台低优

    Args:
        codes: 指定股票列表（None 则取全市场前 500 只）。
    """
    _ensure_pd()
    provider = _get_tushare_provider()
    total = 0
    n_skip = 0
    target = _target_fin_period()  # 428 P1-1
    if codes is None:
        codes = _shard_fetchall('daily_cache', "SELECT DISTINCT ts_code FROM daily_cache")
        codes = [r[0] for r in codes[:500]]
    for code in codes:
        if _finance_covers_period('cashflow_cache', code, target):
            n_skip += 1
            continue
        try:
            raw = provider.get_cashflow(code)
            # provider 返回 list（to_dict('records')），非 DataFrame
            if raw:
                df = pd.DataFrame(raw)
                for col in ['end_date', 'ann_date', 'f_ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                _ecm.cache_cashflow_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [现金流量表] 同步 {total} 条 (共 {len(codes)} 只"
                + (f"，跳过 {n_skip} 只已有最新期" if n_skip else ")")
                + ")")
    return total


def _batch_forecast(codes: list = None) -> int:
    """增量同步最近一期业绩预告 — 后台低优

    Args:
        codes: 指定股票列表（None 则取全市场前 500 只）。
    """
    _ensure_pd()
    provider = _get_tushare_provider()
    total = 0
    if codes is None:
        codes = _shard_fetchall('daily_cache', "SELECT DISTINCT ts_code FROM daily_cache")
        codes = [r[0] for r in codes[:500]]
    for code in codes:
        try:
            raw = provider.get_forecast(code)
            # provider 返回 list（to_dict('records')），非 DataFrame
            if raw:
                df = pd.DataFrame(raw)
                for col in ['end_date', 'ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                _ecm.cache_forecast_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [业绩预告] 同步 {total} 条 (共 {len(codes)} 只)")
    return total


# ══════════════════════════════════════════════════════════
# 完整性检查与补采
# ══════════════════════════════════════════════════════════

DAILY_THRESHOLD = 5000
BASIC_THRESHOLD = 5000
MF_THRESHOLD = 1000
LIMIT_THRESHOLD = 1000
LHB_THRESHOLD = 20

IMPORT_PD = False


def _ensure_pd():
    global IMPORT_PD
    if not IMPORT_PD:
        import pandas as pd
        import numpy as np
        globals()['pd'] = pd
        globals()['np'] = np
        IMPORT_PD = True


def _check_count(table: str, trade_date: str) -> int:
    """356号方案：从正确的数据库（分库或总库）查询行数"""
    try:
        return _query_table(table, f"SELECT COUNT(*) FROM \"{table}\" WHERE trade_date=?", [trade_date])
    except Exception:
        return 0


def _query_table(table: str, sql: str, params=None):
    """356号方案：从分库或总库执行查询（通用路由）"""
    try:
        from app.data.sharding_manager import sharding_manager
        db_name = sharding_manager.get_db_for_table(table)
        if db_name:
            conn = sharding_manager.get_connection(db_name)
            if params:
                return conn.execute(sql, params).fetchone()[0]
            else:
                return conn.execute(sql).fetchone()[0]
        else:
            if params:
                return _ecm.conn.execute(sql, params).fetchone()[0]
            else:
                return _ecm.conn.execute(sql).fetchone()[0]
    except Exception:
        return 0


def _shard_query_df(table: str, sql: str, params=None):
    """356号方案：读分库权威副本返回 DataFrame

    423号运行验证：_ecm._query_df 读主库 read_conn，而 daily_cache/
    daily_basic_cache/opportunity_tags_cache 权威副本已在分库（主库残留
    旧数据致 treemap 滞后约10个交易日）——统一改走 sharding_manager。
    """
    import pandas as _pd
    from app.data.sharding_manager import sharding_manager
    db_name = sharding_manager.get_db_for_table(table)
    if db_name:
        conn = sharding_manager.get_connection(db_name)
        return _pd.read_sql(sql, conn, params=params)
    return _pd.read_sql(sql, _ecm.read_conn, params=params)


def _shard_fetchall(table: str, sql: str, params=None):
    """356号方案：读分库返回多行"""
    from app.data.sharding_manager import sharding_manager
    db_name = sharding_manager.get_db_for_table(table)
    if db_name:
        conn = sharding_manager.get_connection(db_name)
        return conn.execute(sql, params or []).fetchall()
    return _ecm.read_conn.execute(sql, params or []).fetchall()


def run_integrity_check(backfill_days: int = 1):
    """启动/巡检时执行：检查缺失数据并用批量 API 补采"""
    _ensure_pd()
    today = datetime.now().strftime('%Y%m%d')
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    logger.info("开始完整性检查...")

    # 指数日线检查：4只指数代码在 daily_cache 中的记录数（356号：从分库读取）
    idx_codes = BROAD_INDEX_CODES  # 438号缺口①：含 HS300/000300.SH，动态占位
    idx_checks = []
    for offset in range(0, backfill_days):
        d = (datetime.now() - timedelta(days=offset))
        ds = d.strftime('%Y-%m-%d')
        if not _is_trading_day(d):  # 跳过周末与法定节假日（432号 R4）
            continue
        if offset == 0 and not _is_today_data_ready():
            # 432号 R4：今日指数数据未发布（<18:00），跳过今日检查（历史日期不受限）
            continue
        try:
            placeholders = ','.join('?' * len(idx_codes))
            cnt = _query_table('daily_cache',
                f"SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND ts_code IN ({placeholders})",
                [ds] + idx_codes)
        except Exception:
            cnt = 0
        if cnt < len(idx_codes):
            idx_checks.append(ds)

    checks = [
        ('daily_cache',     _batch_daily,      DAILY_THRESHOLD,  '日线'),
        ('daily_basic_cache', _batch_daily_basic, BASIC_THRESHOLD, '基本面'),
        ('moneyflow_cache', _batch_moneyflow,   MF_THRESHOLD,    '资金流向'),
        ('stk_limit_cache', _batch_stk_limit,   LIMIT_THRESHOLD, '涨跌停'),
        ('lhb_cache',       _batch_lhb,         LHB_THRESHOLD,   '龙虎榜'),
        # concept_cache 无 trade_date 字段，跳过日期检查（355号方案修复方案5）
    ]

    # concept_cache 特殊检查：无 trade_date 字段，仅检查是否有数据（356号：从分库读取）
    try:
        concept_cnt = _query_table('concept_cache', "SELECT COUNT(*) FROM concept_cache")
        if concept_cnt == 0:
            logger.info("  [概念] 空表，触发补采...")
            concept_added = _batch_concept()
            logger.info(f"    → 补采 {concept_added} 条")
        else:
            logger.info(f"  [概念] {concept_cnt} 行 ✅")
    except Exception as e:
        logger.warning(f"  概念检查失败: {e}")

    # 龙虎榜席位明细（278号方案独立检查：lhb_detail_cache）
    # 432号 R4：当日数据未发布（盘前/非交易日）不检查——top_inst 盘后才发布，盘前必空
    try:
        if not _is_today_data_ready():
            logger.info("  [龙虎榜席位] 当日数据未发布（<18:00 或非交易日），跳过")
        else:
            detail_cnt = _check_count('lhb_detail_cache', today_fmt) if today_fmt else 0
            if detail_cnt == 0:
                logger.info("  [龙虎榜席位] 今日无数据，补采...")
                detail_added = _batch_lhb_detail(today)
                logger.info(f"    → 补采 {detail_added} 条")
            else:
                logger.info(f"  [龙虎榜席位] {detail_cnt} 行 ✅")
    except Exception as e:
        logger.warning(f"  龙虎榜席位检查失败: {e}")

    # 320号 F1：K 线深度检查（策略引擎需要 ≥130 根，不足则标签/九层解读 K 线维度失效）
    try:
        _backfill_all_insufficient_kline(threshold=130, max_codes=200)
    except Exception as e:
        logger.warning(f"  [K线深度] 检查失败: {e}")

    # 融资融券检查（355号方案+363号F55-3修复：支持多天增量回补，356号：从分库读取）
    try:
        margin_latest = _query_table('margin_cache', "SELECT MAX(trade_date) FROM margin_cache")
        if margin_latest is None:
            # 空表，触发补采
            logger.info("  [融资融券] 空表，触发补采...")
            added = _batch_margin(today)
            logger.info(f"    → 补采 {added} 条")
        else:
            # 检查时效性：滞后不超过7天
            from datetime import datetime as _dt
            # 兼容 YYYYMMDD 和 YYYY-MM-DD 两种日期格式
            _date_str = str(margin_latest).replace('-', '')
            latest_date = _dt.strptime(_date_str, '%Y%m%d')
            _today_str = today.replace('-', '') if isinstance(today, str) else _dt.now().strftime('%Y%m%d')
            today_date = _dt.strptime(_today_str, '%Y%m%d')
            days_lag = (today_date - latest_date).days
            if days_lag > 7:
                logger.info(f"  [融资融券] 滞后 {days_lag} 天，触发范围补采...")
                # 363号F55-3修复：一次性回补多天滞后（timedelta 已在模块顶部导入）
                start_date = (latest_date + timedelta(days=1)).strftime('%Y-%m-%d')
                added = _batch_margin_range(start_date, today)
                logger.info(f"    → 范围补采 {added} 条 ({start_date} ~ {today})")
            else:
                logger.info(f"  [融资融券] 最新 {margin_latest}，滞后 {days_lag} 天 ✅")
    except Exception as e:
        logger.warning(f"  融资融券检查失败: {e}")

    # 财务指标补充检查（非每日判断，仅检查有无数据，356号：从分库读取）
    try:
        fina_cnt = _query_table('fina_indicator_cache', "SELECT COUNT(*) FROM fina_indicator_cache")
        if fina_cnt < 100:
            logger.info(f"  [财务指标] {fina_cnt}行 (需≥100)，触发补采...")
            _batch_fina_indicator(today)
    except Exception as e:
        logger.warning(f"  财务指标检查失败: {e}")

    # ── 4 类后台低优数据检查（空表时触发补采，非每日必须，356号：从分库读取）──
    # 363号F55-2修复：adj_factor增加时效性检查（滞后>3天触发补采）
    # 441号D·通道②增强：非空表也做「个股级覆盖核对」——原实现仅空表触发批量补采，
    # 抓不到「非空表+个股缺失」（如 stk_holder 曾缺 456 只深市个股）。三表空表→
    # 批量补采；非空表→ _reconcile_cache_coverage 逐 active_code 核对缺失单只补采。
    batch_background = [
        ('top10_holders_cache', _batch_top10_holders, '前十大股东'),
        ('stk_holder_cache',    _batch_stk_holder,    '股东人数'),
        ('finance_report_cache', _batch_finance_report, '扩展财务'),
    ]
    empty_tables = []
    for table, batch_fn, label in batch_background:
        try:
            cnt = _query_table(table, f"SELECT COUNT(*) FROM {table}")
            if cnt == 0:
                logger.info(f"  [{label}] 空表，触发补采...")
                empty_tables.append(table)
                added = batch_fn()
                logger.info(f"    → 补采 {added} 条")
            else:
                logger.info(f"  [{label}] {cnt} 行，进入个股覆盖核对")
        except Exception as e:
            logger.warning(f"  [{label}] 检查失败: {e}")
    # 441号D·通道②增强：非空表（含本轮刚批量补采的表）按 active_code 核对个股级缺失
    # 并单只补采（_reconcile_cache_coverage 内部逐一处理三表）。空表本轮已批量补采，
    # 其覆盖由下一轮巡检收敛；三表全空时跳过覆盖核对避免重复全市场单只补采。
    if len(empty_tables) < len(batch_background):
        for table, _batch_fn, label in batch_background:
            if table in empty_tables:
                continue
            try:
                _reconcile_cache_coverage()
                break  # 单次覆盖巡检即覆盖三表，避免重复取 active 池
            except Exception as e:
                logger.warning(f"  [{label}] 覆盖核对失败: {e}")
    else:
        logger.info("  三张富字段素材表均空，本轮已批量补采，跳过覆盖核对（下轮收敛）")

    # adj_factor单独检查：空表或时效性滞后>3个交易日时触发补采
    # 432号 R1：改读分年表 adj_factor_cache_YYYY（356号拆分后写入只落分年表，
    # 主表 adj_factor_cache 自拆分起停更——读主表 MAX(trade_date) 恒滞后 → 每次
    # 开机/巡检触发 _batch_adj_factor 全历史重采约 250 万条）
    try:
        adj_latest = _get_adj_latest_date()
        if adj_latest is None:
            logger.info("  [复权因子] 无分年表数据，触发补采...")
            added = _batch_adj_factor()
            logger.info(f"    → 补采 {added} 条")
        else:
            from datetime import datetime as _dt
            # 兼容 YYYYMMDD 和 YYYY-MM-DD 两种日期格式
            _date_str = str(adj_latest).replace('-', '')
            latest_date = _dt.strptime(_date_str, '%Y%m%d')
            _today_str = today.replace('-', '') if isinstance(today, str) else _dt.now().strftime('%Y%m%d')
            today_date = _dt.strptime(_today_str, '%Y%m%d')
            # 432号 R3：滞后按交易日口径（周末/节假日不计）
            days_lag = _lag_trading_days(latest_date, today_date)
            if days_lag > 3:
                logger.info(f"  [复权因子] 滞后 {days_lag} 个交易日（阈值3天），触发补采...")
                added = _batch_adj_factor()
                logger.info(f"    → 补采 {added} 条")
            else:
                logger.info(f"  [复权因子] 最新 {adj_latest}，滞后 {days_lag} 个交易日 ✅")
    except Exception as e:
        logger.warning(f"  [复权因子] 检查失败: {e}")

    # 财务表空表检查：balancesheet/cashflow/forecast（356号：从分库读取）
    for table, batch_fn, label in [
        ('balancesheet_cache', _batch_balancesheet, '资产负债表'),
        ('cashflow_cache', _batch_cashflow, '现金流量表'),
        ('forecast_cache', _batch_forecast, '业绩预告'),
    ]:
        try:
            cnt = _query_table(table, f"SELECT COUNT(*) FROM {table}")
            if cnt == 0:
                logger.info(f"  [{label}] 空表，触发补采...")
                n = batch_fn()
                logger.info(f"    → 补采 {n} 条")
        except Exception as e:
            logger.warning(f"  [{label}] 检查失败: {e}")

    # 检查今日数据（432号 R4：仅"交易日且当日数据已发布"后检查——
    # Tushare 日线一般 17-18 点才发布，盘前/盘中检查当日必然空返回；节假日亦跳过）
    _today_checkable = _is_today_data_ready()
    if not _today_checkable:
        logger.info("  今日数据检查：非交易日或当日数据未发布（<18:00），跳过")
    for table, batch_fn, threshold, label in checks:
        if not _today_checkable:
            continue
        cnt = _check_count(table, today_fmt)
        if cnt < threshold:
            logger.info(f"  [{label}] 今日 {cnt}行 (需≥{threshold})，补采...")
            added = batch_fn(today)
            logger.info(f"    → 补采 {added} 条")
        else:
            logger.info(f"  [{label}] 今日 {cnt}行 ✅")

    # 量比自算：基于 daily_cache 回写 volume_ratio（Tushare 免费 API 不提供该字段）
    _compute_volume_ratio(today)

    # 回退补采最近 N 个交易日（检查前一天的完整性）
    if backfill_days > 1:
        for offset in range(1, backfill_days):
            d = (datetime.now() - timedelta(days=offset))
            ds = d.strftime('%Y%m%d')
            df = d.strftime('%Y-%m-%d')
            if not _is_trading_day(d):  # 跳过周末与法定节假日（432号 R4）
                continue
            for table, batch_fn, threshold, label in checks:
                cnt = _check_count(table, df)
                if cnt < threshold:
                    logger.info(f"  [{label}] {df} {cnt}行，补采...")
                    batch_fn(ds)

    # 独立检查指数日线（因 index_daily_cache 为空表，不走通用 _check_count）
    for idx_date in idx_checks:
        ds_api = idx_date.replace('-', '')
        logger.info(f"  [指数日线] {idx_date} 4只指数数据不足，补采...")
        _batch_index_daily(ds_api)

    # 申万行业指数完整性检查（31 个行业，缺失/陈旧时 sw_daily 区间回填）
    import tushare as _ts_sw, pandas as _pd_sw
    pro = _ts_sw.pro_api()
    try:
        have_rows = _shard_fetchall(
            'daily_cache', "SELECT MAX(trade_date) AS d, ts_code FROM daily_cache "
                           "WHERE ts_code LIKE '801%.SI' GROUP BY ts_code")
        latest_by_code = {r[1]: r[0] for r in have_rows}
        missing = [c for c in SW_INDEX_CODES if c not in latest_by_code]
        stale = []
        for c in SW_INDEX_CODES:
            d = latest_by_code.get(c)
            if d is not None and _lag_trading_days(
                    _pd_sw.to_datetime(d), datetime.now()) > 1:
                stale.append(c)
        if missing or stale:
            today_key = f'sw_index_backfilled:{datetime.now().strftime("%Y%m%d")}'
            try:
                done_row = _ecm.conn.execute(
                    "SELECT value FROM cache_metadata WHERE key=?", [today_key]
                ).fetchone()
                if done_row:
                    logger.info(f"  [申万行业指数] 当日已回填尝试过（缺 {len(missing)} 缺/存 {len(stale)} 陈旧，跳过）")
                    # 不return——继续执行后续完整性检查和管道驱动
            except Exception:
                pass
            # 区间回填：全量（缺失）或 60 日（陈旧）——sw_daily 一次可取整段
            backfill_days = 90 if missing else 60
            start = (datetime.now() - timedelta(days=backfill_days + 10)).strftime('%Y%m%d')
            end = datetime.now().strftime('%Y%m%d')
            ok = 0
            for code in (missing + stale):
                try:
                    raw = _ts(pro.sw_daily, ts_code=code, start_date=start, end_date=end)
                    if raw is None or raw.empty:
                        continue
                    df = raw.rename(columns=_SW_DAILY_COL_MAP)
                    if 'trade_date' in df.columns:
                        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                    extra = [c for c in df.columns if c not in _SW_DAILY_KEEP]
                    if extra:
                        df = df.drop(columns=extra)
                    _ecm.cache_daily_data(df)
                    ok += 1
                except Exception as e:
                    logger.debug(f"行业指数 {code} 回填失败: {e}")
            logger.info(f"  [申万行业指数] 回填 {ok}/{len(missing + stale)} 个（缺 {len(missing)}，陈旧 {len(stale)}）")
            try:
                _ecm.conn.execute(
                    "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                    [today_key, str(len(missing) + len(stale))]
                )
                _ecm.conn.commit()
            except Exception:
                pass
        else:
            logger.info(f"  [申万行业指数] 完整且时效正常（{len(SW_INDEX_CODES)} 个）✅")
    except Exception as e:
        logger.warning(f"  申万行业指数检查失败: {e}")

    # ── 355号方案规则4.2：数据时效性审查（进阶层）──
    try:
        _check_data_timeliness()
    except Exception as e:
        logger.warning(f"  数据时效性检查失败: {e}")

    # ── 355号方案规则4.3：数据值合理性审查（质量层）──
    try:
        _check_data_quality()
    except Exception as e:
        logger.warning(f"  数据质量检查失败: {e}")

    # ── 355号方案规则4.4：数据一致性审查（一致性层）──
    try:
        _check_data_consistency()
    except Exception as e:
        logger.warning(f"  数据一致性检查失败: {e}")

    logger.info("完整性检查完成")
    
    # 自选股分钟数据完整性检查（后台线程，不阻塞主循环）
    try:
        threading.Thread(target=_check_watchlist_minute, daemon=True).start()
    except Exception:
        pass


def _check_data_timeliness():
    """355号方案规则4.2：数据时效性审查（进阶层）

    检查项：数据最新日期与当前日期的差距
    时效性标准：
    - 核心数据（daily_cache等）：滞后不超过1天
    - 补充数据（margin_cache等）：滞后不超过7天
    - 背景数据（fina_indicator等）：滞后不超过30天
    """
    today = datetime.now()

    # 核心数据时效性检查（滞后不超过1天）
    core_tables = [
        ('daily_cache', '日线'),
        ('daily_basic_cache', '基本面'),
        ('moneyflow_cache', '资金流向'),
        ('stk_limit_cache', '涨跌停'),
    ]

    for table, label in core_tables:
        try:
            latest = _query_table(table, f"SELECT MAX(trade_date) FROM {table}")
            if latest:
                latest_date = datetime.strptime(str(latest), '%Y-%m-%d') if isinstance(latest, str) else latest
                # 432号 R3：滞后按交易日口径（周末/节假日不计，周五数据周一不再误告警）
                days_lag = _lag_trading_days(latest_date, today)
                if days_lag > 1:
                    logger.warning(f"  [时效性] {label}({table}) 滞后 {days_lag} 个交易日")
                else:
                    logger.debug(f"  [时效性] {label}({table}) 滞后 {days_lag} 个交易日 ✅")
        except Exception as e:
            logger.debug(f"  {label}时效性检查失败: {e}")

    # 补充数据时效性检查（滞后不超过7天）
    supplement_tables = [
        ('margin_cache', '融资融券'),
        ('adj_factor_cache', '复权因子'),
    ]

    for table, label in supplement_tables:
        try:
            # 432号 R1：复权因子读分年表（主表自拆分起停更，读主表恒滞后）
            if table == 'adj_factor_cache':
                latest = _get_adj_latest_date()
            else:
                latest = _query_table(table, f"SELECT MAX(trade_date) FROM {table}")
            if latest:
                latest_date = datetime.strptime(str(latest), '%Y-%m-%d') if isinstance(latest, str) else latest
                # 432号 R3：滞后按交易日口径（周末/节假日不计）
                days_lag = _lag_trading_days(latest_date, today)
                if days_lag > 7:
                    logger.warning(f"  [时效性] {label}({table}) 滞后 {days_lag} 个交易日")
                else:
                    logger.debug(f"  [时效性] {label}({table}) 滞后 {days_lag} 个交易日 ✅")
        except Exception as e:
            logger.debug(f"  {label}时效性检查失败: {e}")

    # 背景数据时效性检查（滞后不超过30天）
    background_tables = [
        ('fina_indicator_cache', '财务指标'),
        ('income_cache', '利润表'),
        ('balancesheet_cache', '资产负债表'),
        ('cashflow_cache', '现金流量表'),
    ]

    for table, label in background_tables:
        try:
            latest = _query_table(table, f"SELECT MAX(trade_date) FROM {table}")
            if latest:
                latest_date = datetime.strptime(str(latest), '%Y-%m-%d') if isinstance(latest, str) else latest
                days_lag = (today - latest_date).days
                if days_lag > 30:
                    logger.warning(f"  [时效性] {label}({table}) 滞后 {days_lag} 天")
                else:
                    logger.debug(f"  [时效性] {label}({table}) 滞后 {days_lag} 天 ✅")
        except Exception as e:
            logger.debug(f"  {label}时效性检查失败: {e}")

    logger.debug("  [时效性] 检查完成")


def _check_data_quality():
    """355号方案规则4.3：数据值合理性审查（质量层）

    检查项：
    - 价格字段：close/open/high/low > 0
    - 成交量字段：vol/amount >= 0
    - 涨跌幅字段：-20% <= pct_chg <= 20%（排除新股上市首日）
    - 基本面字段：pe/pb/tot_mv > 0
    """
    _ensure_pd()
    today_fmt = datetime.now().strftime('%Y-%m-%d')

    # 检查价格字段异常（356号：从分库读取）
    try:
        price_anomaly = _query_table('daily_cache', """
            SELECT COUNT(*) FROM daily_cache
            WHERE trade_date = ? AND (close <= 0 OR open <= 0 OR high <= 0 OR low <= 0)
        """, [today_fmt])
        if price_anomaly > 0:
            logger.warning(f"  [数据质量] 价格异常记录: {price_anomaly} 条")
    except Exception as e:
        logger.debug(f"  价格异常检查失败: {e}")

    # 检查成交量字段异常
    try:
        vol_anomaly = _query_table('daily_cache', """
            SELECT COUNT(*) FROM daily_cache
            WHERE trade_date = ? AND (vol < 0 OR amount < 0)
        """, [today_fmt])
        if vol_anomaly > 0:
            logger.warning(f"  [数据质量] 成交量异常记录: {vol_anomaly} 条")
    except Exception as e:
        logger.debug(f"  成交量异常检查失败: {e}")

    # 检查涨跌幅异常（排除新股上市首日）— 363号F55-1修复：AND改为OR
    try:
        pct_anomaly = _query_table('daily_cache', """
            SELECT COUNT(*) FROM daily_cache
            WHERE trade_date = ? AND (pct_chg > 20 OR pct_chg < -20)
        """, [today_fmt])
        if pct_anomaly > 0:
            logger.warning(f"  [数据质量] 涨跌幅异常记录: {pct_anomaly} 条")
    except Exception as e:
        logger.debug(f"  涨跌幅异常检查失败: {e}")

    logger.debug("  [数据质量] 检查完成")


def _check_data_consistency():
    """355号方案规则4.4：数据一致性审查（一致性层）

    检查项：
    - 跨表一致性：daily_cache与daily_basic_cache的ts_code交集
    - 时间一致性：同一股票在不同表的日期对齐（363号F55-5新增）
    - 逻辑一致性：high >= close >= low
    """
    today_fmt = datetime.now().strftime('%Y-%m-%d')

    # 检查跨表一致性：daily_cache与daily_basic_cache的ts_code交集
    try:
        daily_codes = set(row[0] for row in _shard_fetchall(
            'daily_cache', "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date = ?", [today_fmt]))
        basic_codes = set(row[0] for row in _shard_fetchall(
            'daily_basic_cache', "SELECT DISTINCT ts_code FROM daily_basic_cache WHERE trade_date = ?", [today_fmt]))

        if daily_codes and basic_codes:
            missing_in_basic = daily_codes - basic_codes
            missing_in_daily = basic_codes - daily_codes
            if missing_in_basic:
                logger.warning(f"  [数据一致性] daily_basic缺失: {len(missing_in_basic)} 只股票")
            if missing_in_daily:
                logger.warning(f"  [数据一致性] daily_cache缺失: {len(missing_in_daily)} 只股票")
    except Exception as e:
        logger.debug(f"  跨表一致性检查失败: {e}")

    # 363号F55-5修复：检查时间一致性（同一股票在不同表的日期差不超过3天）
    # 424号P0-3：daily_cache(market_cache.db) 与 daily_basic_cache(market_cache.db) 同库，可单 SQL JOIN
    try:
        time_check = _shard_fetchall(
            'daily_cache', """
            SELECT COUNT(*) FROM (
                SELECT d.ts_code,
                       MAX(d.trade_date) as daily_date,
                       MAX(b.trade_date) as basic_date,
                       JULIANDAY(MAX(d.trade_date)) - JULIANDAY(MAX(b.trade_date)) as date_diff
                FROM daily_cache d
                JOIN daily_basic_cache b ON d.ts_code = b.ts_code
                WHERE d.trade_date >= date(?, '-7 days')
                  AND b.trade_date >= date(?, '-7 days')
                GROUP BY d.ts_code
                HAVING ABS(date_diff) > 3
            )
        """, [today_fmt, today_fmt])[0][0]
        if time_check > 0:
            logger.warning(f"  [数据一致性] 时间不一致: {time_check} 只股票跨表日期差>3天")
    except Exception as e:
        logger.debug(f"  时间一致性检查失败: {e}")

    # 检查逻辑一致性：high >= close >= low
    try:
        logic_anomaly = _shard_fetchall(
            'daily_cache', """
            SELECT COUNT(*) FROM daily_cache
            WHERE trade_date = ? AND (high < close OR close < low)
        """, [today_fmt])[0][0]
        if logic_anomaly > 0:
            logger.warning(f"  [数据一致性] 逻辑异常记录: {logic_anomaly} 条 (high < close 或 close < low)")
    except Exception as e:
        logger.debug(f"  逻辑一致性检查失败: {e}")

    logger.debug("  [数据一致性] 检查完成")


def _check_watchlist_minute():
    """检查自选股分钟数据完整性，缺失时触发后台补采"""
    try:
        from app.data.minute_backfill import get_watchlist_stocks, run_backfill_all
        codes = get_watchlist_stocks()
        if not codes:
            return
        
        # 检查哪些自选股缺失分钟数据
        missing_5min = []
        for code in codes:
            cnt = _shard_fetchall(
                'minute_kline_cache',
                'SELECT COUNT(*) FROM minute_kline_cache WHERE ts_code=? AND freq="5min"',
                [code]
            )[0][0]
            if cnt == 0:
                missing_5min.append(code)
        
        if not missing_5min:
            logger.info(f"  [自选股分钟] {len(codes)} 只全部有分钟数据 ✅")
            return
        
        logger.info(f"  [自选股分钟] {len(codes)} 只中 {len(missing_5min)} 只缺失分钟数据，触发补采...")
        run_backfill_all(ts_codes=missing_5min)
        logger.info(f"  [自选股分钟] 补采完成")
    except Exception as e:
        logger.warning(f"  [自选股分钟] 检查失败: {e}")


# ══════════════════════════════════════════════════════════
# 日终同步
# ══════════════════════════════════════════════════════════

_SYNCED_TODAY = False


def run_daily_sync():
    """15:30 触发：日终批量同步 + 后台任务触发

    COL-1~COL-6（日线/基本面/资金流/涨跌停/龙虎榜/概念）已由管道驱动
    _drive_pipeline() 统一管理，此处只执行管道未覆盖的额外同步。

    373号方案§五决策点#1：合并 run_daily_sync 与 _drive_pipeline 重叠的
    COL 采集调用，消除交易日重复工作。
    """
    global _SYNCED_TODAY
    today = datetime.now().strftime('%Y%m%d')
    logger.info("=== 日终同步开始 ===")

    # ── 管道未覆盖的额外数据采集（COL-1~COL-6 由 _drive_pipeline 管理） ──
    tasks = [
        ('index_daily_cache', _batch_index_daily, '指数日线'),
        ('lhb_detail_cache',  _batch_lhb_detail,  '龙虎榜席位'),
    ]

    for table, batch_fn, label in tasks:
        try:
            added = batch_fn(today)
            logger.info(f"  {label}: {added} 条")
        except Exception as e:
            logger.warning(f"  {label} 失败: {e}")

    # 量比自算（Tushare 免费 API 不提供 volume_ratio，计算层自算）
    _compute_volume_ratio(today)

    # 相对强弱批量计算（438号缺口③：全市场双基准超额收益持久化）
    try:
        _compute_relative_strength(today)
    except Exception as e:
        logger.warning(f"  相对强弱批量计算失败: {e}")

    # 形态评分批量计算（353/358号方案：日终批量 + 缓存）
    try:
        _batch_pattern_score(today)
    except Exception as e:
        logger.warning(f"  形态评分批量计算失败: {e}")

    # ── 补齐空表（迭代4）──
    try:
        n = _batch_margin(today)
        logger.info(f"  融资融券: {n} 条")
    except Exception as e:
        logger.warning(f"  融资融券同步失败: {e}")
    # 注：_batch_concept 已由管道 COL-6 统一管理，不再此处重复调用
    try:
        n = _batch_index_member()
        logger.info(f"  指数成分股: {n} 条")
    except Exception as e:
        logger.warning(f"  指数成分股同步失败: {e}")
    try:
        n = _batch_win_rate()
        logger.info(f"  策略胜率: {n} 条")
    except Exception as e:
        logger.warning(f"  策略胜率计算失败: {e}")

    # ── 日终补充：4 类后台低优数据（非每日必须，补采空表）──
    for batch_fn, label in [
        (_batch_adj_factor,    '复权因子'),
        (_batch_top10_holders, '前十大股东'),
        (_batch_stk_holder,    '股东人数'),
        (_batch_finance_report,'扩展财务'),
    ]:
        try:
            n = batch_fn()
            if n > 0:
                logger.info(f"  {label}: {n} 条")
        except Exception as e:
            logger.warning(f"  {label} 同步失败: {e}")

    # 指标预计算已由管道驱动统一管理（_drive_pipeline），不再单独触发

    # 财务数据同步（后台低优，不阻塞主同步流程）
    try:
        threading.Thread(target=_run_financial_sync, daemon=True).start()
        logger.info("  财务数据同步已触发（后台）")
    except Exception as e:
        logger.warning(f"  财务数据同步触发失败: {e}")

    # 414号R20: 移除v1(Tushare)回填，仅保留v2(mootdx)
    # try:
    #     threading.Thread(target=_run_minute_backfill, daemon=True).start()
    #     logger.info("  分钟K线回填已触发（后台）")
    # except Exception as e:
    #     logger.warning(f"  分钟K线回填触发失败: {e}")

    # 自选股分钟数据闲时补采（后台低优，使用 mootdx 填充历史数据）
    try:
        threading.Thread(target=_run_minute_backfill_v2, daemon=True).start()
        logger.info("  分钟数据闲时补采已触发（后台）")
    except Exception as e:
        logger.warning(f"  分钟数据闲时补采触发失败: {e}")

    # 信号验证回算 T+5/T+10/T+20（345号第③层核查激活，后台低优）
    # 2026-08-16 新增：scheduler_manager 仅 API 进程注册回算；daemon 模式
    # （DATA_DAEMON_RUNNING=1）由日终同步后触发，避免双调度。
    try:
        threading.Thread(target=_run_signal_checkpoint, daemon=True).start()
        logger.info("  信号验证回算已触发（后台）")
    except Exception as e:
        logger.warning(f"  信号验证回算触发失败: {e}")

    _SYNCED_TODAY = True
    logger.info("=== 日终同步完成 ===")


def _write_factor_signals(codes):
    """兜底写入：对无法运行完整策略信号的股票，写入基于因子的简化信号"""
    _ensure_pd()
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    try:
        from app.data.factor_precompute import FactorPrecomputeManager
        fpm = FactorPrecomputeManager(_ecm)
        for ts_code in codes[:200]:  # 限200只避免过长
            try:
                df = _ecm.get_cached_daily(ts_code)
                if df is None or len(df) < 30:
                    continue
                closes = df['close'].values
                if len(closes) < 20:
                    continue
                # 简单动量+波动率评分
                mom = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0
                vol = float(df['close'].std()) / max(float(df['close'].mean()), 1e-9) if len(df) > 0 else 0.5
                score = max(0.0, min(1.0, (mom + 5) / 20 + (1 - vol)))
                signal = 'BUY' if score >= 0.6 else ('WATCH' if score >= 0.4 else 'NEUTRAL')
                signals = [{
                    'signal_date': today_fmt,
                    'strategy_name': '因子评分系统',
                    'confidence': round(score, 2),
                    'signal': signal,
                }]
                # 适配 strategy_signal_detail 表格式（287号方案统一存储）
                result_dict = {
                    'ts_code': ts_code,
                    'trade_date': today_fmt.replace('-', ''),
                    'signals': {},
                    'market_context': {},
                    'data_availability': {'kline': True},
                }
                for idx, sig in enumerate(signals):
                    key = f'factor_fallback_{idx}'
                    result_dict['signals'][key] = {
                        'strategy_name': sig.get('strategy_name', ''),
                        'direction': 'bullish' if sig.get('signal') == 'BUY' else ('bearish' if sig.get('signal') == 'SELL' else 'neutral'),
                        'confidence': sig.get('confidence', 0),
                        'signal': 'BULLISH' if sig.get('signal') == 'BUY' else ('BEARISH' if sig.get('signal') == 'SELL' else 'NEUTRAL'),
                        'signal_label': sig.get('signal', 'NEUTRAL'),
                        'evidence': [f"因子评分: {sig.get('confidence', 0)}"],
                        'status_recognition': {},
                        'raw_detail': sig,
                    }
                _ecm.cache_signal_detail(ts_code, result_dict)
            except Exception as e:
                failed += 1
                continue
        logger.info(f"因子信号兜底写入完成（{len(codes[:200])} 只）")
    except Exception as e:
        logger.warning(f"因子信号兜底写入失败: {e}")

def _run_with_timeout(func, timeout_sec: float = 30.0, desc: str = ""):
    """单只计算超时保护（327阶段4）：超时返回 None 并记录日志，不中断全量

    用独立线程执行 func，超过 timeout_sec 未完成则视为卡死跳过。
    超时后**不等待后台线程**（不用 with shutdown(wait=True)——
    那会在超时后仍阻塞主流程，使保护形同虚设）。
    后台线程置为 daemon（随进程结束），该只结果丢弃，主流程立即继续。

    Returns:
        func() 的返回值，超时返回 None
    """
    import concurrent.futures as _cf
    _exe = _cf.ThreadPoolExecutor(max_workers=1)
    try:
        fut = _exe.submit(func)
        return fut.result(timeout=timeout_sec)
    except _cf.TimeoutError:
        logger.warning(f"  [超时] {desc} 超过 {timeout_sec}s 未完成，跳过该只（不中断全量）")
        return None
    except Exception as e:
        logger.debug(f"  [单只] {desc} 失败: {type(e).__name__}")
        return None
    finally:
        # 不等待：shutdown(wait=False) 立即返回，后台线程继续跑但不再阻塞主流程
        try:
            _exe.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


def _precompute_preset_combos(codes):
    """预计算常用因子值并写入 factor_cache（通过 FactorRegistry）"""
    _ensure_pd()
    try:
        from app.data.factor_precompute import FactorPrecomputeManager
        from app.factors import get_factor_registry
    except ImportError as e:
        logger.warning(f"因子模块导入失败，跳过因子预计算: {e}")
        return

    # 将旧中文因子名映射到 FactorRegistry 英文名
    FACTOR_NAME_MAP = {
        '20日动量': 'QLIB_ROC_20', '5日动量': 'QLIB_ROC_5', '动量因子(MOM)': 'QLIB_ROC_20',
        '短期动量': 'QLIB_ROC_5', '动量': 'QLIB_ROC_20',
        '14日RSI': 'QLIB_RSI_14', '5日量比': 'VOL_RATIO_5',
        '量比': 'VOL_RATIO_5', '20日换手率': 'VOL_RATIO_20',
        '20日波动率': 'VOLATILITY_20', '低波因子': 'VOLATILITY_20',
        '20日均线乖离率': 'BIAS_20', '均线乖离率': 'BIAS_20',
        '5日反转因子': 'QLIB_REVERSAL_5',
    }

    reg = get_factor_registry()
    # 找出所有可映射的因子名
    mapped_factors = {}
    for cn_name, en_name in FACTOR_NAME_MAP.items():
        if reg.get_factor_class(en_name) is not None:
            mapped_factors[cn_name] = en_name

    if not mapped_factors:
        logger.info("因子预计算: 无可用因子")
        return

    logger.info(f"因子预计算: {len(mapped_factors)} 个因子, {len(codes)} 只股票")
    fpm = FactorPrecomputeManager(_ecm)
    precomputed = 0
    timeout_count = 0
    # 414号R12/13: 增加per-factor失败统计
    factor_fail_counts = {}  # {factor_name: count}
    for code in codes:
        try:
            # 327阶段4：单只因子计算超时保护（防止单只卡死拖垮全量）
            def _factor_one(c=code, _fpm=fpm, _mf=mapped_factors, _ffc=factor_fail_counts):
                df = _ecm.get_cached_daily(c)
                if df is None or len(df) < 30:
                    return 'skip'
                for cn_name, en_name in _mf.items():
                    try:
                        _fpm.precompute_factor(c, df, en_name)
                    except Exception:
                        _ffc[en_name] = _ffc.get(en_name, 0) + 1
                return 'ok'
            r = _run_with_timeout(_factor_one, timeout_sec=30.0,
                                  desc=f"因子 {code}")
            if r is None:
                timeout_count += 1
            elif r == 'ok':
                precomputed += 1
        except Exception:
            continue
    # 414号R12/13: 日志增加per-factor失败统计
    fail_detail = ', '.join(f"{k}:{v}" for k, v in sorted(factor_fail_counts.items(), key=lambda x: -x[1])[:5]) if factor_fail_counts else ''
    logger.info(f"因子预计算完成: {precomputed}/{len(codes)} 只" +
                (f", 超时 {timeout_count}" if timeout_count else '') +
                (f", 失败因子: {fail_detail}" if fail_detail else ''))


def _precompute_sector_heat(codes):
    """板块热度持久化（B3 根治：独立管道步骤 RAW-2B）

    419号方案B2 原将板块热度写盘嵌在 RAW-2（_precompute_raw_features）内，
    导致两个问题：
    1. 触发时机依赖 RAW-2 重跑——当天 RAW-2 已 done 时重启 daemon 会跳过，
       sector_heat_cache 永不回填。
    2. 写盘用共享 _ecm.conn + _execute（无 busy_timeout），与 daemon 主循环
       写锁竞争，实测报 "database is locked"。

    本函数抽离为独立步骤，在 RAW-2 完成后、SIG 前执行；写盘用独立短连接
    （参考 _batch_write_signal_detail 的写锁根治模式），DELETE + executemany +
    单次 commit，busy_timeout=10s 防极端长事务阻塞。
    """
    _ensure_ecm()
    _ensure_pd()
    if not codes:
        return
    from app import create_app
    _flask_app = create_app()
    with _flask_app.app_context():
        from app.engine.framework.sector_rotation_model import SectorRotationModel
        sr = SectorRotationModel()
        # 批量加载日线
        all_data: dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = _ecm.get_cached_daily(code)
                if df is not None and not df.empty:
                    all_data[code] = df
            except Exception:
                pass
        # 构建 indicator_ma_dict（MA优先从预计算表读取，对齐 dim5 副本类行为）
        indicator_ma_dict = {}
        for code in all_data.keys():
            try:
                ind_df = _ecm.get_indicators_wide(code)
                if ind_df is not None and not ind_df.empty:
                    ma_cols = [c for c in ind_df.columns if c.startswith('ma')]
                    if ma_cols:
                        indicator_ma_dict[code] = ind_df[ma_cols]
            except Exception:
                pass
        sr.compute_all_heat(all_data, indicator_ma_dict=indicator_ma_dict)
        _sh = sr._cache.get('all_heat')
        if not _sh:
            logger.warning("板块热度预计算为空，跳过写盘")
            return
        # 取最新交易日
        _sh_date_row = _shard_fetchall(
            'daily_cache', "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
        _sh_date = _sh_date_row[0][0] if _sh_date_row else ''
        if not _sh_date:
            logger.warning("无交易日数据，跳过板块热度写盘")
            return
        # 独立短连接写盘（避免与主循环写锁竞争）
        # 426号 P1-2：sector_heat_cache 已登记 compute_cache.db 路由，
        # 写盘改走分库连接（原直连 _ecm.db_path 总库空壳，读方已切分库路由）。
        from app.data.sharding_manager import sharding_manager as _sh_mgr
        _sh_db = _sh_mgr.get_db_for_table('sector_heat_cache')
        try:
            conn = _sh_mgr.get_connection(_sh_db)
            lock = _sh_mgr.get_write_lock(_sh_db)
            with lock:
                conn.execute("DELETE FROM sector_heat_cache WHERE stat_date = ?", [_sh_date])
                rows = [
                    (_sh_date, ind,
                     str(info.get('heat_level', 'none')),
                     float(info.get('strength', 0.0)),
                     int(info.get('rank', -1)),
                     int(info.get('stock_count', 0)))
                    for ind, info in _sh.items()
                ]
                conn.executemany(
                    "INSERT INTO sector_heat_cache "
                    "(stat_date, industry, heat_level, strength, rank, stock_count) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    rows
                )
                conn.commit()
            logger.info(f"板块热度持久化完成: {len(rows)} 个行业 (stat_date={_sh_date}, db={_sh_db})")
        except Exception as e:
            logger.warning(f"板块热度写盘失败: {e}")


def _precompute_market_stats(target_date: str | None = None):
    """411号Phase 10：全市场级统计预计算

    426号 P0-1 修复：7 项源查询改走分库路由（_shard_fetchall），源表空壳/
    无当日数据时统计项置 None 显式标记——任一统计项无源数据即告警且不落库，
    不再写入兜底常量（原实现读总库空壳表返回空集 → else 兜底 0.5/0.1，
    造成格式正确、结果错误的假数据入库并经 RAW-2 污染 pre_feat_cache）。

    target_date：统计目标交易日（'YYYY-MM-DD'）。缺省时锚定 daily_cache 最大交易日
      （443号R6：原 now-1 硬算在周一/假期后落在非交易日 → 统计项全 None 不落库 → RAW-2 落空）。
    """
    global _market_stats_cache
    _ensure_ecm()
    try:
        from datetime import datetime, timedelta
        if target_date:
            today = target_date
        else:
            # 锚定 daily_basic_cache 最新交易日（统计项公共依赖表；daily 常领先 1 日，
            # 若锚 daily 会在 daily_basic/stk_limit 滞后时置空——443号R6 实测）
            try:
                from app.data.sharding_manager import sharding_manager
                _ms_conn = sharding_manager.get_connection(
                    sharding_manager.get_db_for_table('daily_basic_cache'))
                _ms_row = _ms_conn.execute(
                    "SELECT trade_date FROM daily_basic_cache ORDER BY trade_date DESC LIMIT 1"
                ).fetchone()
                today = str(_ms_row[0]) if _ms_row and _ms_row[0] else \
                    (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            except Exception:
                today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        stats: dict[str, object] = {}
        _row_counts: dict[str, int] = {}

        def _missing(table: str) -> bool:
            """源表空壳/未登记检测（分库口径 0 行 → 告警，防 _shard_fetchall 静默降级总库）"""
            if table in _row_counts:
                return _row_counts[table] <= 0
            from app.data.sharding_manager import sharding_manager
            try:
                n = sharding_manager.get_table_row_count(table)
            except Exception as e:
                logger.warning(f"426 P0-1 源表行数检测失败 {table}: {e}")
                n = 0
            _row_counts[table] = n
            if n <= 0:
                logger.warning(f"426 P0-1 源表为空壳或未登记: {table}（分库行数={n}）")
            return n <= 0

        def _run(name: str, table: str, fn) -> None:
            """执行单项市场统计；无源数据/异常 → None 显式标记（命中兜底即告警）"""
            if _missing(table):
                stats[name] = None
                return
            try:
                val = fn()
                stats[name] = val
                if val is None:
                    logger.warning(f"426 P0-1 {name} 无 {today} 日源数据（置 None，不落库）")
            except Exception as e:
                logger.warning(f"426 P0-1 {name} 计算失败: {e}")
                stats[name] = None

        # 1. MA20强势股占比（daily_cache → market_cache.db 分库）
        # 426号 阶段三复核：原查询在窗口函数子查询内先 WHERE trade_date=? 过滤，
        # 每只股票仅剩当日 1 行 → SMA_20=当日 close → close>SMA_20 恒 False →
        # ma20_ratio 恒 0.0（P0-1 修复的隐藏残留假值）。窗口须在全历史计算后
        # 再按当日过滤（正确口径 09-11 = 0.252）。
        def _ma20_ratio():
            rows = _shard_fetchall('daily_cache', """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN close > SMA_20 THEN 1 ELSE 0 END) as above
                FROM (
                    SELECT ts_code, trade_date, close,
                           AVG(close) OVER (PARTITION BY ts_code ORDER BY trade_date
                                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as SMA_20
                    FROM daily_cache
                )
                WHERE trade_date = ?
            """, [today])
            if not rows or not rows[0] or not rows[0][0] or rows[0][0] <= 0:
                return None
            return (rows[0][1] or 0) / rows[0][0]
        _run('ma20_ratio', 'daily_cache', _ma20_ratio)

        # 2. 换手率分位（daily_basic_cache → market_cache.db 分库）
        def _turnover_percentile():
            rows = _shard_fetchall('daily_basic_cache',
                "SELECT AVG(turnover_rate) FROM daily_basic_cache WHERE trade_date=?", [today])
            if not rows or rows[0][0] is None:
                return None
            avg_turnover = float(rows[0][0])
            hist = _shard_fetchall('daily_basic_cache',
                "SELECT AVG(turnover_rate) FROM daily_basic_cache WHERE trade_date >= date(?, '-60 days')",
                [today])
            hist_avg = float(hist[0][0]) if hist and hist[0][0] else avg_turnover
            if hist_avg <= 0:
                return None
            return max(0, min(1, avg_turnover / hist_avg))
        _run('turnover_percentile', 'daily_basic_cache', _turnover_percentile)

        # 3. 涨跌停比（daily_cache JOIN stk_limit_cache → market_cache.db 分库）
        def _limit_ratio():
            rows = _shard_fetchall('daily_cache', """
                SELECT
                    SUM(CASE WHEN high_limit = close THEN 1 ELSE 0 END) as up,
                    SUM(CASE WHEN low_limit = close THEN 1 ELSE 0 END) as down
                FROM daily_cache d
                JOIN stk_limit_cache l ON d.ts_code=l.ts_code AND d.trade_date=l.trade_date
                WHERE d.trade_date = ?
            """, [today])
            if not rows or not rows[0] or (rows[0][0] is None and rows[0][1] is None):
                return None
            up = float(rows[0][0] or 0)
            down = float(rows[0][1] or 0)
            return max(0.1, up / max(down, 1))
        _run('limit_ratio', 'daily_cache', _limit_ratio)

        # 4. RSI中位数分位（indicator_other → compute_cache.db 分库）
        def _rsi_percentile():
            rows = _shard_fetchall('indicator_other',
                "SELECT AVG(rsi14) FROM indicator_other WHERE trade_date=? AND rsi14 IS NOT NULL", [today])
            if not rows or rows[0][0] is None:
                return None
            avg_rsi = float(rows[0][0])
            hist = _shard_fetchall('indicator_other',
                "SELECT AVG(rsi14) FROM indicator_other WHERE trade_date >= date(?, '-60 days') AND rsi14 IS NOT NULL",
                [today])
            hist_avg = float(hist[0][0]) if hist and hist[0][0] else 50.0
            if hist_avg <= 0:
                return None
            return max(0, min(1, (avg_rsi - 30) / 40))
        _run('rsi_percentile', 'indicator_other', _rsi_percentile)

        # 5. ERP分位（daily_basic_cache → market_cache.db 分库）
        def _erp_percentile():
            # 447号 T3a-2：ERP = 1/PE_TTM - 10年国债利率（对齐知识库 research-bociasicscv190a:58，
            # 复用 dim7 CN_10Y_BOND_YIELD_PCT；原实现 1/PE 未减国债）。
            # 归一化口径（447号 用户拍板）：A股盈利收益率普遍低于国债，ERP 绝对值恒为负，
            # 比值归一化对负值失效 → 改为「当日 ERP 绝对值在近252日历史中的分位(rank%)」，
            # 负值自然落入低分位，保持 0~1 语义。
            from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT
            bond_yield = float(CN_10Y_BOND_YIELD_PCT)
            rows = _shard_fetchall('daily_basic_cache',
                """SELECT d.trade_date, AVG(c.pe_ttm) AS pe FROM (
                    SELECT DISTINCT trade_date
                    FROM daily_basic_cache
                    WHERE trade_date <= ? AND pe_ttm > 0
                    ORDER BY trade_date DESC LIMIT 252
                ) d JOIN daily_basic_cache c ON c.trade_date = d.trade_date AND c.pe_ttm > 0
                GROUP BY d.trade_date ORDER BY d.trade_date""", [today])
            if not rows:
                return None
            erp_series = []
            for _, pe in rows:
                if pe is not None and float(pe) > 0:
                    erp_series.append(1 / float(pe) * 100 - bond_yield)
            if not erp_series:
                return None
            erp_today = erp_series[-1]  # 按 trade_date 升序，最后一条即当日
            # 历史绝对分位：当日值在「当日+历史」序列中小于它的占比
            count_less = sum(1 for v in erp_series if v < erp_today)
            return max(0, min(1, count_less / len(erp_series)))
        _run('erp_percentile', 'daily_basic_cache', _erp_percentile)

        # 5b. 股债收益差分位（daily_basic_cache → market_cache.db 分库）——447号 T3a-2
        #     股债收益差 = 全市场中位股息率(dv_ttm) - 10年国债利率（知识库 research-bociasicscv190a:60）
        #     归一化口径（447号 用户拍板）：股息率普遍低于国债，收益差绝对值恒为负，
        #     比值归一化对负值失效 → 改为「当日中位股息率-国债 在近252日历史差分位(rank%)」。
        def _median_dv_by_day():
            """近252交易日按日分组的中位股息率（ROW_NUMBER 窗口：奇数取中位、偶数取中间两均）"""
            return """SELECT d.trade_date, AVG(m.dv_median) FROM (
                SELECT DISTINCT trade_date FROM daily_basic_cache
                WHERE trade_date <= ? AND dv_ttm > 0
                ORDER BY trade_date DESC LIMIT 252
            ) d JOIN (
                SELECT trade_date, AVG(dv_ttm) AS dv_median FROM (
                    SELECT trade_date, dv_ttm,
                           ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY dv_ttm) rn,
                           COUNT(*) OVER (PARTITION BY trade_date) cnt
                    FROM daily_basic_cache WHERE dv_ttm > 0
                ) WHERE rn BETWEEN cnt * 0.5 AND cnt * 0.5 + 1
                GROUP BY trade_date
            ) m ON m.trade_date = d.trade_date
            GROUP BY d.trade_date ORDER BY d.trade_date"""

        def _dv_bond_diff():
            from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT
            bond_yield = float(CN_10Y_BOND_YIELD_PCT)
            rows = _shard_fetchall('daily_basic_cache',
                _median_dv_by_day(), [today])
            if not rows:
                return None
            diff_series = []
            for _, dv in rows:
                if dv is not None and float(dv) > 0:
                    diff_series.append(float(dv) - bond_yield)
            if not diff_series:
                return None
            diff_today = diff_series[-1]  # 按 trade_date 升序，最后一条即当日
            # 历史绝对分位：当日值在「当日+历史」序列中小于它的占比
            count_less = sum(1 for v in diff_series if v < diff_today)
            return max(0, min(1, count_less / len(diff_series)))
        _run('dv_bond_diff', 'daily_basic_cache', _dv_bond_diff)

        # 6. 融资余额趋势（margin_cache → market_cache.db 分库）
        def _margin_trend():
            recent = _shard_fetchall('margin_cache', """
                SELECT trade_date, SUM(rzye) as total
                FROM margin_cache
                WHERE trade_date >= date(?, '-10 days')
                GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5
            """, [today])
            if len(recent) < 2:
                return None
            latest = float(recent[0][1])
            oldest = float(recent[-1][1])
            if oldest <= 0:
                return None
            change_pct = (latest - oldest) / oldest
            return max(0, min(1, 0.5 + change_pct * 10))
        _run('margin_trend', 'margin_cache', _margin_trend)

        # 7. PE分位（daily_basic_cache → market_cache.db 分库）
        def _pe_percentile():
            rows = _shard_fetchall('daily_basic_cache',
                "SELECT AVG(pe_ttm) FROM daily_basic_cache WHERE trade_date=? AND pe_ttm > 0", [today])
            if not rows or rows[0][0] is None:
                return None
            avg_pe = float(rows[0][0])
            hist = _shard_fetchall('daily_basic_cache',
                "SELECT AVG(pe_ttm) FROM daily_basic_cache WHERE trade_date >= date(?, '-252 days') AND pe_ttm > 0",
                [today])
            hist_pe = float(hist[0][0]) if hist and hist[0][0] else avg_pe
            if hist_pe <= 0:
                return None
            return max(0, min(1, avg_pe / hist_pe))
        _run('pe_percentile', 'daily_basic_cache', _pe_percentile)

        stats['computed_at'] = today
        # 任一统计项无源数据 → 告警且不落库（426号 P0-1：假值禁止入库/注入 RAW-2）
        # 447号 T3a-2：dv_bond_diff 为新增可选增强项（股债收益差），当日股息率缺源时
        # 仅自身 None（framework 慢线回退 _compute_dv_bond_diff），不拖垮核心 7 项落库
        _missing_items = [k for k, v in stats.items() if v is None and k != 'computed_at'
                          and k != 'dv_bond_diff']
        if _missing_items:
            logger.warning(f"426 P0-1 市场级统计存在无源数据项: {_missing_items}，本次不落库、不注入RAW-2")
            _market_stats_cache = {}
            return
        _market_stats_cache = stats
        # 414号R8: 持久化到SQLite，daemon重启后可恢复
        # 局部引用并判空窄化（_ecm 全局为 Optional，避免 union-attr 类型告警）
        _ecm_ref = _ecm
        if _ecm_ref is None:
            logger.warning("市场级统计持久化跳过: ECM 未初始化")
            return
        try:
            _ecm_ref.cache_market_stats(stats)
        except Exception as e:
            logger.warning(f"市场级统计持久化失败: {e}")
        logger.info(f"市场级统计预计算完成: {len(stats)}个指标（{today}）")

    except Exception as e:
        logger.warning(f"市场级统计预计算失败: {e}")


def _pick_volume_ratio(_db, trade_date):
    """461-10：跨表日期对齐挑选量比真值（供 _raw2_one volume_price 组调用，纯函数便于单测）。

    - 优先取与 trade_date 同日的 volume_ratio（回补/target_date 截断时避免取到更新日期错日）。
    - 缺当日数据时回退 latest 非空量比（容忍采集滞后，维持 459 R4-b 兜底语义）。
    - 无可用量比返回 1.0 兜底。
    """
    try:
        if _db is None or getattr(_db, 'empty', True) or not hasattr(_db, 'columns') or 'volume_ratio' not in _db.columns:
            return 1.0
        _td = str(trade_date).replace('-', '')[:8]
        _db_d = _db.copy()
        _tds = _db_d['trade_date'].astype(str).str.replace('-', '').str[:8]
        _m = _tds == _td
        _sub = _db_d[_m]['volume_ratio'].dropna() if _m.any() else _db_d['volume_ratio'].dropna()
        if not _sub.empty:
            return float(_sub.iloc[-1])
    except Exception:
        pass
    return 1.0


def _precompute_raw_features(codes, target_date: str | None = None):
    """原料加工环节：特征提取（RAW-2 FEAT）→ 写入 pre_feat_cache

    357号方案：从 _precompute_l2_labels 中提取纯原料加工步骤，
    仅计算10组特征（valuation/sentiment/sector/style/timing/volume_price/chanlun/chip/event/depth），
    写入 pre_feat_cache（JSON格式，54字段）。

    不含阶段判定/主力在场/机会潜力/仲裁等判定层操作（移到JUD环节）。

    Args:
        codes: 股票代码列表
        target_date: 426号 P1-3 回补参数——限定特征计算的目标交易日
            （'YYYY-MM-DD'）。提供时每只股票的日线在计算前截断到该日，
            trade_date 取该日，用于定向回补历史缺口（08-31~09-08 等）。
            缺省时保持原行为（每只股票取自身最新交易日）。
    """
    _ensure_pd()
    if not codes:
        return
    logger.info(f"RAW-2 原料加工开始: {len(codes)} 只...")

    _ensure_ecm()
    from app import create_app
    _flask_app = create_app()

    with _flask_app.app_context():
        # 延迟导入各引擎
        from app.opportunity_atlas.valuation_estimator import ValuationEngine
        from app.services.market_sentiment_service import MarketSentimentService
        from app.engine.framework.sector_rotation_model import SectorRotationModel
        from app.opportunity_atlas.time_rhythm_engine import TimeRhythmEngine
        from app.engine.framework.volume_price_strategy import VolumePriceStrategy
        from app.engine.framework.chanlun_strategy import get_chanlun_tags as _get_chanlun_tags
        from app.data.chip_distribution_service import ChipDistributionEstimator
        from app.opportunity_atlas.event_monitor import EventMonitor
        from app.opportunity_atlas.tag_extractor import (
            extract_chanlun_deep_tags, extract_chip_deep_tags,
            extract_fund_risk_tags,
        )
        # 365号批次A：新增引擎导入（pre_feat_cache扩展字段）
        def _calc_volatility_percentile(df_local):
            """波动率历史分位"""
            import math as _math
            close = df_local['close'].astype(float)
            returns = close.pct_change().dropna()
            if len(returns) >= 20:
                vol_20d = returns.rolling(20).std() * _math.sqrt(252)
                vol_20d = vol_20d.dropna()
                if len(vol_20d) >= 2:
                    current_vol = vol_20d.iloc[-1]
                    return float((vol_20d < current_vol).sum() / len(vol_20d))
            return 0.5
        from app.engine.framework.chip_strategy import MainForceScorer
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        # 370号修复：classify_attribute已删除（dim1_signal_engine中有同名函数），此处未使用，移除import
        # 443号R5：calc_vol_ratio 原仅供 vp_health_ext 段（已删），import 一并移除

        # 各引擎初始化
        from app.data import DataManager
        dm = DataManager()
        ve = ValuationEngine()
        ms = MarketSentimentService()
        sr = SectorRotationModel()
        tre = TimeRhythmEngine()
        vps = VolumePriceStrategy()
        cde = ChipDistributionEstimator()
        em = EventMonitor()

        # 截面基准构建
        try:
            ve.build_composite_percentile(dm.cache)
        except Exception as _e:
            # 461-12：截面复合分位构建失败（降级不影响主流程），记日志防静默吞
            logger.warning(f"RAW 截面 composite_percentile 构建失败: {_e}")
        try:
            ve.build_fcf_percentile(dm.cache)
        except Exception as _e:
            # 461-12：截面 FCF 分位构建失败（降级），记日志防静默吞
            logger.warning(f"RAW 截面 fcf_percentile 构建失败: {_e}")

        # 批量加载日线数据
        all_data: dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = _ecm.get_cached_daily(code)
                if df is not None and not df.empty:
                    all_data[code] = df
            except Exception as _e:
                # 461-12：单只日线加载失败（降级），记日志防静默吞
                logger.debug(f"RAW 日线加载失败 [{code}]: {_e}")
        logger.info(f"  日线数据加载完成: {len(all_data)}/{len(codes)} 只")

        # 预计算板块热度（v3.0：传递indicator_ma_dict避免dim引擎直接调用DataManager）
        try:
            indicator_ma_dict = {}
            for code in all_data.keys():
                try:
                    ind_df = _ecm.get_indicators_wide(code)
                    if ind_df is not None and not ind_df.empty:
                        ma_cols = [c for c in ind_df.columns if c.startswith('ma')]
                        if ma_cols:
                            indicator_ma_dict[code] = ind_df[ma_cols]
                except Exception as _e:
                    # 461-12：单只均线预计算失败（降级），记日志防静默吞
                    logger.debug(f"RAW 均线预计算失败 [{code}]: {_e}")
            # 442号缺陷④：RAW-2 经 _raw_pool.submit 线程池执行，线程内无 Flask app_context，
            # compute_all_heat 内部 get_stock_industry_batch 依赖 db.session → RuntimeError 被静默吞
            # → sr._cache['all_heat'] 恒空 → sector_heat 全 none（84% 板块数据不足）。
            # 参照 RAW-2B _precompute_sector_heat 的 app_context 先例，包一层应用上下文。
            from app import create_app as _create_app
            _raw_app = _create_app()
            with _raw_app.app_context():
                sr.compute_all_heat(all_data, indicator_ma_dict=indicator_ma_dict)
            # 板块热度持久化已抽离为独立管道步骤 RAW-2B（_precompute_sector_heat），
            # 在 RAW-2 完成后、SIG 前执行，用独立短连接避免与主循环写锁竞争。
            # 此处仅保留 compute_all_heat 预热 sr._cache['all_heat'] 供下方 sr.evaluate 消费。
        except Exception as _e:
            # 461-12：板块热度预热失败（442 已修复 app_context，此处降级），记日志防静默吞
            logger.warning(f"RAW 板块热度预热失败: {_e}")

        # 市场情绪全局值
        _sentiment_phase_global = 'neutral'
        try:
            last_date_row = _shard_fetchall(
                'daily_cache', "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
            if last_date_row:
                last_date = last_date_row[0][0]
                limit_up = _shard_fetchall(
                    'daily_cache', "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg > 9.9",
                    [last_date])[0][0]
                limit_down = _shard_fetchall(
                    'daily_cache', "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg < -9.9",
                    [last_date])[0][0]
                sealing_rate = 0.0
                try:
                    rows = _shard_fetchall(
                        'daily_cache',
                        "SELECT high, close, pct_chg FROM daily_cache "
                        "WHERE trade_date=? AND pct_chg > 5",
                        [last_date])
                    touched = sealed = 0
                    for high, close, pct in rows:
                        prev_close = close / (1 + pct / 100)
                        if high >= prev_close * 1.099:
                            touched += 1
                            if close >= prev_close * 1.099:
                                sealed += 1
                    if touched > 0:
                        sealing_rate = round(sealed / touched * 100, 1)
                except Exception as _e:
                    # 461-12：封板率统计失败（降级用默认 0.0），记日志防静默吞
                    logger.debug(f"RAW 封板率统计失败: {_e}")
                # 447号 T2a：fallback 枚举对齐源 A 六段论（ice/ferment/climax/ebb），删 recovery；
                # climax 门槛对齐源 A（limit_up>80 且 sealing>75），无 max_board_height 时可辨识档归
                # sprout/regression 兜底→ferment（同源 A else 默认语义）
                if limit_up > 80 and sealing_rate > 75:
                    _sentiment_phase_global = 'climax'
                elif (limit_up < 40 and sealing_rate < 40) or limit_down > 20:
                    _sentiment_phase_global = 'ebb'
                elif limit_up < 20 and sealing_rate < 40:
                    _sentiment_phase_global = 'ice'
                else:
                    _sentiment_phase_global = 'ferment'
        except Exception as _e:
            # 461-12：市场情绪全局值构建失败（降级 neutral），记日志防静默吞
            logger.warning(f"RAW 市场情绪全局值构建失败: {_e}")

        t0 = time.time()
        succeeded = 0
        # 414号R9: RAW-2异常统计
        failed = 0
        group_failures = {}  # {group_name: count}
        commit_count = 0
        BATCH_SIZE = 500
        trade_date = None
        _progress_n = 0  # 428 P1-2 动作②：每 500 只输出一次进度日志（诊断慢股票）

        def _raw2_one(code):
            nonlocal trade_date
            df = all_data.get(code)
            if df is None or df.empty or len(df) < 5:
                return ({}, trade_date)  # 数据不足，外层静默跳过
            # 426号 P1-3：回补时按 target_date 截断（特征按当日口径计算，
            # trade_date 收敛为目标日；正常管道 target_date=None 行为不变）
            if target_date:
                df = df[df['trade_date'].astype(str).str[:10] <= target_date]
                if df.empty or len(df) < 5:
                    return ({}, trade_date)  # 数据不足，外层静默跳过
            if trade_date is None:
                trade_date = str(df['trade_date'].iloc[-1])[:10]

            features = {}

            # 1. 估值特征（17字段）
            try:
                v_tags = ve.compute_tags(code)
                if v_tags:
                    # 461-9：裸 pe/pb/ps_percentile + roe 白名单空键——ve.compute_tags return
                    # 只产 _5y 变体（pe_percentile_5y 等）与 composite_rating 等，无裸三键、无 roe；
                    # 裸 pe_percentile 仅市场级(market_stats, 461-8 已隔离)。移除死白名单，_5y 保留。
                    features['valuation'] = {k: v for k, v in v_tags.items()
                        if k in ('pe_percentile_5y', 'pb_percentile_5y', 'ps_percentile_5y',
                                 'valuation_level', 'valuation_deviation',
                                 'fcf_yield', 'dividend_yield', 'composite_rating',
                                 'revenue_growth', 'fina_health',
                                 'asset_anchor_rating', 'earnings_anchor_rating',
                                 'cashflow_anchor_rating', 'adjusted_anchor_rating',
                                 'roce_pass', 'value_trap')}
            except Exception as e:
                logger.warning(f"RAW估值特征失败 [{code}]: {e}")

            # 2. 情绪特征（1字段：sentiment_phase；461-13 删 bociasi_signal 死键）
            try:
                _sent = {}
                # sentiment_phase：始终写入（默认neutral）
                try:
                    sentiment = ms.get_sentiment_phase()
                    if sentiment.get('data_available'):
                        _sent['sentiment_phase'] = sentiment['phase']
                        _sent_metrics = sentiment.get('metrics') or {}
                        # 447号 T1a：补写涨停家数/封板率（源自 sentiment_pool_cache，
                        # 供 daemon RAW 温度与 dim5 实时温度消费，消灭 7 输入仅传 3）
                        if isinstance(_sent_metrics.get('limit_up_count'), int):
                            _sent['limit_up_count'] = _sent_metrics['limit_up_count']
                        if isinstance(_sent_metrics.get('sealing_rate'), (int, float)):
                            _sent['sealing_rate'] = float(_sent_metrics['sealing_rate'])
                    else:
                        _sent['sentiment_phase'] = _sentiment_phase_global or 'neutral'
                except Exception:
                    _sent['sentiment_phase'] = _sentiment_phase_global or 'neutral'
                features['sentiment'] = _sent
            except Exception as e:
                logger.warning(f"RAW情绪特征失败 [{code}]: {e}")

            # 3. 板块特征（2字段：sector_heat + sector_rank；461-13 删 sector_momentum/is_sector_leader 死键）
            try:
                # 442号缺陷④：_raw2_one 经 _run_with_timeout 在子线程执行（无 app_context），
                # sr.evaluate 的 get_stock_industry 依赖 db.session → 调用处包应用上下文
                with _raw_app.app_context():
                    sector = sr.evaluate(code)
                features['sector'] = {
                    'sector_heat': sector.get('sector_heat', 0),
                    # 442号缺陷④：evaluate 返回键为 'rank'/'strength'
                    # 键名错位致恒 0）——对齐返回键
                    'sector_rank': sector.get('rank', 0),
                }
            except Exception as e:
                logger.warning(f"RAW板块特征失败 [{code}]: {e}")

            # 4. 风格特征（1字段：style_exposure；461-13 删 size_factor 死键）
            try:
                style = _compute_style_exposure(code, {}, df)
                features['style'] = {
                    'style_exposure': style if isinstance(style, str) else 'balanced',
                }
            except Exception as e:
                logger.warning(f"RAW风格特征失败 [{code}]: {e}")

            # 5. 时间特征（3字段）
            if len(df) >= 30:
                try:
                    tr_tags = tre.compute_tags(df)
                    if tr_tags:
                        # 461-9：cycle_position/turnover_signal 白名单空键——
                        # TimeRhythmEngine.compute_tags 只产 time_rhythm，另两键从不产，移除死白名单
                        features['timing'] = {k: v for k, v in tr_tags.items()
                            if k in ('time_rhythm',)}
                except Exception as e:
                    logger.warning(f"RAW时间特征失败 [{code}]: {e}")

            # 6. 量价特征（6字段）
            if len(df) >= 20:
                try:
                    vp_tags = vps._detect_kline_patterns(df)
                    _simple = {}
                    _add_vp_simple_tags(df, _simple)
                    # 459号 R4-b + 461-10：量比接真实生产点 _compute_volume_ratio 已回写
                    # daily_basic_cache.volume_ratio，此处读真值（不再恒 1.0），并按特征
                    # trade_date 跨表日期对齐（回补避免错日），见 _pick_volume_ratio。
                    _db = None
                    try:
                        _db = _ecm.get_cached_daily_basic(code)
                    except Exception as _e:
                        # 461-12：daily_basic 读取失败，量比回退，记日志防静默吞
                        logger.debug(f"RAW量价 daily_basic 读取失败 [{code}]: {_e}")
                        _db = None
                    _vr = _pick_volume_ratio(_db, trade_date)
                    features['volume_price'] = {
                        'kline_pattern': vp_tags.get('pattern_signal', 'none'),
                        'ma_alignment': _simple.get('ma_alignment', 'neutral'),
                        'volume_price_fit': _simple.get('volume_price_fit', 'neutral'),
                        'volume_ratio': _vr,
                    }
                except Exception as e:
                    logger.warning(f"RAW量价特征失败 [{code}]: {e}")

            # 7. 缠论特征（5字段）
            if len(df) >= 30:
                try:
                    from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
                    cl = ChanlunAnalyzer()
                    cl_result = cl.analyze(df)
                    cl_tags = _get_chanlun_tags(cl_result)
                    # 461-9：trend_direction/zhongshu_count/bi_count/duan_count 白名单空键——
                    # get_chanlun_tags 只产 buy_sell_point，另 4 键从不产（461-7 已改直读 cl_result['trend']），
                    # 移除死白名单
                    features['chanlun'] = {k: v for k, v in (cl_tags or {}).items()
                        if k in ('buy_sell_point',)}
                except Exception as e:
                    logger.warning(f"RAW缠论特征失败 [{code}]: {e}")

            # 8. 筹码特征（4字段）
            if len(df) >= 30:
                try:
                    chip_tags = cde.get_tags(df)
                    # 461-9：asr/cyqkl 白名单空键——ChipDistributionEstimator.get_tags 只产
                    # chip_position/chip_concentration，另两键从不产（dim4:5676/5685 读但恒 None，
                    # 移除后行为不变），清理死白名单
                    features['chip'] = {k: v for k, v in (chip_tags or {}).items()
                        if k in ('chip_position', 'chip_concentration')}
                except Exception as e:
                    logger.warning(f"RAW筹码特征失败 [{code}]: {e}")

            # 9. 事件特征（4字段，含dim6消费的event_details/event_risk_factors；461-13 删 catalyst_impact 死键）
            try:
                _evt_tags = {}
                _update_with_event_tags(code, _evt_tags)
                features['event'] = {
                    'catalyst_event': _evt_tags.get('catalyst_event', 'none'),
                    'event_composite_score': _evt_tags.get('event_composite_score', 0),
                    'event_details': _evt_tags.get('event_details', []),
                    'event_risk_factors': _evt_tags.get('event_risk_factors', []),
                }
            except Exception as e:
                logger.warning(f"RAW事件特征失败 [{code}]: {e}")

            # 10. 深度字段（8字段）——461-6：接线真生产者，替代 460 死键
            #     原实现从 extract_*_deep_tags 取键名（缠论/chip_deep/fund_risk 组），
            #     与本组 8 键（hold_float_ratio/.../presence_evidence）错位 → 恒 None → 扁平化整组丢弃，
            #     导致 dim6/status_engine 的 main_force_phase/main_force_presence 缺省。
            #     现改接真实生产者：PhaseDetectionEngine（main_force_phase/phase_confidence）、
            #     MainForceScorer（fund_flow/capital_nature）、_compute_main_force_presence（主在场）、
            #     及 hold_float_ratio/turnover_rate 补生产。
            try:
                _depth = {}
                # ① 主力阶段（PhaseDetectionEngine：main_force_phase/phase_confidence）
                try:
                    from app.opportunity_atlas.phase_detector import PhaseDetectionEngine
                    _extra = {}
                    _cl_tags = features.get('chanlun', {})
                    if _cl_tags.get('buy_sell_point'):
                        _extra['buy_sell_point'] = _cl_tags['buy_sell_point']
                    _phase = PhaseDetectionEngine().compute_tags(code, df, extra_tags=_extra) or {}
                    _depth['main_force_phase'] = _phase.get('main_force_phase')
                    _depth['phase_confidence'] = _phase.get('phase_confidence')
                    # 461-7：PhaseDetectionEngine 已产出 price_position（120日分位，真实 SSOT）/
                    # trend_alignment（up/down/mixed/no_trend），原先被丢弃——补进 depth 供 derived 消费。
                    _depth['price_position'] = _phase.get('price_position')
                    _depth['trend_alignment'] = _phase.get('trend_alignment')
                except Exception as _e:
                    logger.debug(f"RAW深度主力阶段失败 [{code}]: {_e}")
                # ② 资金流向/资金属性（MainForceScorer：fund_flow/capital_nature）
                try:
                    from app.engine.framework.chip_strategy import MainForceScorer
                    _mfs = MainForceScorer().get_tags(code) or {}
                    _depth['fund_flow'] = _mfs.get('fund_flow')
                    _depth['capital_nature'] = _mfs.get('capital_nature')
                except Exception as _e:
                    logger.debug(f"RAW深度资金标签失败 [{code}]: {_e}")
                # ③ 主力在场证据（_compute_main_force_presence：main_force_presence/presence_evidence）
                try:
                    _pres = _compute_main_force_presence(code, _ecm)
                    _depth['main_force_presence'] = _pres.get('main_force_presence')
                    _depth['presence_evidence'] = _pres.get('presence_evidence')
                except Exception as _e:
                    logger.debug(f"RAW深度主力在场失败 [{code}]: {_e}")
                # ④ hold_float_ratio/turnover_rate 补生产（461-6：控盘度/换手率
                #    ——hold_float_ratio 从 top10_holders_cache 前十大股东合计/均值；
                #    turnover_rate 接 daily_basic.turnover_rate 实时列）
                try:
                    _hf_n = 0
                    _hf_sum = 0.0
                    try:
                        for _r in (_ecm.get_cached_top10_holders(code) or []):
                            _hr = _r.get('hold_float_ratio') if isinstance(_r, dict) else None
                            if _hr is None:
                                continue
                            try:
                                _hf_sum += float(_hr)
                                _hf_n += 1
                            except (TypeError, ValueError):
                                # 461-12：单条持仓比例非法，跳过该项，记日志防静默吞
                                logger.debug(f"RAW控盘度持仓比例非数值 [{code}]: {_hr!r}")
                    except Exception as _e:
                        # 461-12：前十大股东读取失败，hold_float_ratio 不产，记日志防静默吞
                        logger.debug(f"RAW控盘度 top10 股东读取失败 [{code}]: {_e}")
                    if _hf_n:
                        _depth['hold_float_ratio'] = str(round(_hf_sum / _hf_n, 4))
                    try:
                        _tb = _ecm.get_cached_daily_basic(code)
                        if _tb is not None and not _tb.empty and 'turnover_rate' in _tb.columns:
                            _tr = _tb['turnover_rate'].dropna()
                            if not _tr.empty:
                                _depth['turnover_rate'] = str(round(float(_tr.iloc[-1]), 2))
                    except Exception as _e:
                        # 461-12：换手率读取失败，turnover_rate 不产，记日志防静默吞
                        logger.debug(f"RAW换手率读取失败 [{code}]: {_e}")
                except Exception as _e:
                    logger.debug(f"RAW深度控盘/换手失败 [{code}]: {_e}")
                features['depth'] = {
                    'hold_float_ratio': _depth.get('hold_float_ratio'),
                    'turnover_rate': _depth.get('turnover_rate'),
                    'main_force_phase': _depth.get('main_force_phase'),
                    'phase_confidence': _depth.get('phase_confidence'),
                    'fund_flow': _depth.get('fund_flow'),
                    'capital_nature': _depth.get('capital_nature'),
                    'main_force_presence': _depth.get('main_force_presence'),
                    'presence_evidence': _depth.get('presence_evidence'),
                    'price_position': _depth.get('price_position'),
                    'trend_alignment': _depth.get('trend_alignment'),
                }
            except Exception as e:
                logger.warning(f"RAW深度字段失败 [{code}]: {e}")

            # 预提取各特征组引用（供后续扩展字段使用）
            _cl = features.get('chanlun', {})
            _vp_f = features.get('volume_price', {})
            _chip_f = features.get('chip', {})
            _depth_f = features.get('depth', {})

            # 11. 衍生特征（从已有特征组中提取下游消费方需要的扁平key）
            try:
                _derived = {}
                _val = features.get('valuation', {})
                # 461-7：位置维统一接真实 SSOT——
                #   price_position 来自 PhaseDetectionEngine（120日价格分位 120 日分位，low/mid/high_zone，
                #     已在 depth 组接线），不再用 buy_sell_point 代理；support_resistance 接
                #     shared_support_resistance.calc_support_resistance（唯一源，460 §四 ✅ 一致项），
                #     替代原 `_depth_f.get('support_resistance','{}')`（depth 组从无此键 → 恒 '{}' 假值）。
                _derived['price_position'] = _depth_f.get('price_position', 'mid_zone')
                try:
                    import json as _json
                    _sr = calc_support_resistance(df)
                    _derived['support_resistance'] = _json.dumps({
                        'support': _sr.get('support_price'),
                        'resistance': _sr.get('resistance_price'),
                    }, ensure_ascii=False)
                except Exception as _e:
                    # 461-12：support_resistance JSON 化失败，兜底 '{}'，记日志防静默吞
                    logger.debug(f"RAW衍生 support_resistance 计算失败 [{code}]: {_e}")
                    _derived['support_resistance'] = '{}'
                # 风险维
                # 461-4：volatility_level 移除 derived 量比代理（量比≠波动率，语义错误），
                # 统一由 risk_ext `_calc_volatility(df,...)`（未年化 20 日 std 档位）SSOT 产出。
                # 461-7：risk_level 保持现状单源（用户拍板）——HIGH iff 主力出货(distributing)，
                #         作 dim6 缠论风险输入的真实来源，偏"判定"语义，符合 445 冻结不越界。
                _derived['risk_level'] = 'HIGH' if _depth_f.get('main_force_phase') == 'distributing' else 'LOW'
                # 信号确认
                _derived['right_side_confirm'] = 'strong_confirm' if _cl.get('buy_sell_point', '') in ('first_buy', 'second_buy') and _vp_f.get('volume_price_fit') == 'healthy' else 'unconfirmed'
                _derived['pattern_signal'] = _vp_f.get('kline_pattern', 'none')
                # 生命信号
                _derived['active_signal'] = _cl.get('buy_sell_point', '') if _cl.get('buy_sell_point', '') not in ('none',) else None
                # 状态标签（461-7：state_label 接 chanlun 缠论 trend 真值（up/down/unknown），
                #   替代原 trend_direction（chanlun get_chanlun_tags 从不产该键 → 恒 'unknown' 假值）；
                #   trend_alignment 接 PhaseDetectionEngine trend_alignment（up_aligned/down_aligned/
                #   mixed/no_trend 原始值域，多周期斜率一致），替代原 trend_direction×ma_alignment 代理
                #   （trend_direction 无生产 → 恒 'misaligned' 假值）。透传原值，与 status_engine:676 /
                #   arbiter:226 的 `== 'up_aligned'/'down_aligned'` 冲突检测判读一致。
                _cl_trend = _cl.get('trend_direction', '')
                if _cl_trend not in ('up', 'down', '上升', '下降'):
                    _cl_trend = (cl_result.get('trend', 'unknown') if 'cl_result' in dir() else 'unknown')
                _derived['state_label'] = '上升' if _cl_trend in ('up', '上升') else ('下降' if _cl_trend in ('down', '下降') else '盘整')
                _derived['trend_alignment'] = _depth_f.get('trend_alignment', 'no_trend')
                # 利润比（461-7：profit_ratio 由 chip_fund_ext 单源生产，derived 不再从 chip_position
                #   （字符串枚举，非数值）代理——derived 组序在 chip_fund_ext(13) 之前，此键会被其后写
                #   覆盖，removed 该假生产，避免 chip_fund_ext 缺失时以错误类型泄漏）。
                if _derived:
                    features['derived'] = _derived
            except Exception as e:
                logger.warning(f"RAW衍生特征失败 [{code}]: {e}")

            # 12. 风险边界扩展字段（365号批次A / Phase 2）
            try:
                _risk_feat = {}
                if len(df) >= 20:
                    _risk_feat['volatility_percentile'] = _calc_volatility_percentile(df)
                else:
                    _risk_feat['volatility_percentile'] = None
                # 411号Phase 9：几何化指标+波动率预计算
                # 461-11：几何化指标统一由 shared.calc_support_resistance（唯一 SSOT）产出，
                #         替代原 dim6.calc_geometric 副本；signal_days/dist_to_prev_high_pct 已并入 shared。
                try:
                    from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
                    from app.opportunity_atlas.dimensions.dim6_risk_engine import _calc_volatility
                    geo = calc_support_resistance(df)
                    _risk_feat['support_price'] = geo.get('support_price')
                    _risk_feat['resistance_price'] = geo.get('resistance_price')
                    _risk_feat['dist_to_support_pct'] = geo.get('dist_to_support_pct')
                    _risk_feat['dist_to_resistance_pct'] = geo.get('dist_to_resistance_pct')
                    _risk_feat['risk_reward'] = geo.get('risk_reward')
                    _risk_feat['signal_days'] = geo.get('signal_days')
                    _risk_feat['dist_to_prev_high_pct'] = geo.get('dist_to_prev_high_pct')
                    vol = _calc_volatility(df, {})
                    _risk_feat['atr_14d'] = vol.get('atr_14d', 0)
                    _risk_feat['atr_pct'] = vol.get('atr_pct', 0)
                    _risk_feat['volatility_level'] = vol.get('level', 'unknown')
                except Exception as _e:
                    # 461-12：几何/波动率预计算失败，risk_ext 留空，记日志防静默吞
                    logger.debug(f"RAW风险几何/波动率计算失败 [{code}]: {_e}")
                features['risk_ext'] = _risk_feat
            except Exception as e:
                logger.warning(f"RAW风险扩展字段失败 [{code}]: {e}")

            # 13. 资金筹码扩展字段（365号批次A / Phase 3）
            try:
                _chip_fund_feat = {}
                # 411号Phase 7：筹码指标预计算（SSRP/ASR/concentration/profit_ratio/cyqkl）
                # 424号§10决策②：先算 chip_bins（cde.estimate），再算聚合指标，
                # 供 get_sub_scores 消费，避免完整分布被重复计算两次。
                try:
                    # 443号R1：cde.estimate() 返回 4 元组 (chip_dist, min_price, max_price, price_step)，
                    # 须解包并把 numpy 分布数组转成 ChipIndicators.calculate_all_indicators 期望的
                    # dict 列表（price_bin/chip_ratio）；此前单变量接收元组→迭代 numpy 数组抛
                    # TypeError→被 except: pass 静默吞→ssrp/asr/concentration/profit_ratio/cyqkl/rsi 全市场 0%。
                    chip_dist, min_price, max_price, price_step = cde.estimate(df)
                    if chip_dist is not None and len(chip_dist) > 0 and price_step > 0:
                        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import ChipIndicators
                        ci = ChipIndicators()
                        current_price = float(df['close'].values[-1])
                        chip_bins = [
                            {
                                'price_bin': round(min_price + bin_idx * price_step + price_step / 2, 2),
                                'chip_ratio': round(float(chip_dist[bin_idx]), 4),
                            }
                            for bin_idx in range(len(chip_dist))
                        ]
                        chip_result = ci.calculate_all_indicators(
                            chip_bins, current_price, kline_data=df, ts_code=code) or {}
                        _chip_fund_feat['ssrp'] = chip_result.get('ssrp')
                        _chip_fund_feat['asr'] = chip_result.get('asr')
                        _chip_fund_feat['concentration'] = chip_result.get('concentration')
                        _chip_fund_feat['profit_ratio'] = chip_result.get('profit_ratio')
                        _chip_fund_feat['cyqkl'] = chip_result.get('cyqkl')
                        _chip_fund_feat['rsi'] = chip_result.get('rsi')
                except Exception as e:
                    logger.warning(f"RAW筹码指标计算失败 [{code}]: {e}")
                # fund_flow_strength: 大单净流入强度（0-1）
                # 424号§10决策②：传入已预计算的 chip_fund_ext，避免 _score_chip_distribution 重复计算完整分布
                try:
                    mfs = MainForceScorer()
                    _sub = mfs.get_sub_scores(df, symbol=code, chip_fund_ext=_chip_fund_feat)
                    _chip_fund_feat['fund_flow_strength'] = min(1.0, max(0.0, (_sub.get('total', 0) or 0) / 10.0))
                except Exception as _e:
                    # 461-12：fund_flow_strength 计算失败，兜底 None，记日志防静默吞
                    logger.debug(f"RAW筹码 fund_flow_strength 计算失败 [{code}]: {_e}")
                    _chip_fund_feat['fund_flow_strength'] = None
                # chip_transfer: 筹码转移方向
                _chip_fund_feat['chip_transfer'] = _depth_f.get('main_force_phase', 'unknown') if _depth_f.get('main_force_phase') in ('lifting', 'distributing') else 'neutral'
                # control_degree: 控盘度
                _chip_fund_feat['control_degree'] = _depth.get('hold_float_ratio')
                features['chip_fund_ext'] = _chip_fund_feat
            except Exception as e:
                logger.warning(f"RAW资金筹码扩展字段失败 [{code}]: {e}")

            # 15. 411号Phase 8：5日资金聚合预计算
            try:
                _fund_5d_feat = {}
                try:
                    mf_df = dm.get_cached_moneyflow(code)
                    if mf_df is not None and not mf_df.empty and len(mf_df) >= 5:
                        net_lg = mf_df['net_lg_amount'].dropna().astype(float)
                        if len(net_lg) >= 5:
                            net_5d = float(net_lg.iloc[-5:].sum())
                            _fund_5d_feat['net_lg_5d'] = net_5d
                            pos_count = int((net_lg.iloc[-5:] > 0).sum())
                            _fund_5d_feat['net_lg_5d_positive_ratio'] = pos_count / 5.0
                            # 461-13 删 net_lg_5d_consecutive 死键（app 层零消费者）
                except Exception as _e:
                    # 461-12：5日资金聚合失败，fund_5d_ext 留空，记日志防静默吞
                    logger.debug(f"RAW 5日资金聚合内层失败 [{code}]: {_e}")
                features['fund_5d_ext'] = _fund_5d_feat
            except Exception as e:
                logger.debug(f"RAW 5日资金聚合失败 [{code}]: {e}")

            # 16. 411号Phase 11：估值指标预计算
            try:
                _val_feat = {}
                try:
                    # PE/PB/PS历史分位、FCF收益率、YoY增长率等
                    # 从daily_basic_cache读取当前PE/PB/PS
                    db_df = dm.get_cached_daily_basic(code)
                    if db_df is not None and not db_df.empty:
                        latest = db_df.iloc[-1]
                        _val_feat['pe_ttm'] = float(latest.get('pe_ttm', 0) or 0)
                        _val_feat['pb'] = float(latest.get('pb', 0) or 0)
                        _val_feat['ps_ttm'] = float(latest.get('ps_ttm', 0) or 0)
                        _val_feat['total_mv'] = float(latest.get('total_mv', 0) or 0)
                except Exception as _e:
                    # 461-12：daily_basic 估值读取失败，估值字段留空，记日志防静默吞
                    logger.debug(f"RAW估值指标 PE/PB 读取失败 [{code}]: {_e}")
                # 财务健康指标
                try:
                    fina_df = dm.get_cached_fina_indicator(code)
                    if fina_df is not None and not fina_df.empty:
                        latest_fina = fina_df.iloc[-1]
                        _val_feat['roe'] = float(latest_fina.get('roe', 0) or 0)
                        _val_feat['roce'] = float(latest_fina.get('roce', 0) or 0)
                        _val_feat['grossprofit_margin'] = float(latest_fina.get('grossprofit_margin', 0) or 0)
                except Exception as _e:
                    # 461-12：财务健康读取失败，财务字段留空，记日志防静默吞
                    logger.debug(f"RAW估值指标财务读取失败 [{code}]: {_e}")
                features['valuation_ext'] = _val_feat
            except Exception as e:
                logger.debug(f"RAW估值指标失败 [{code}]: {e}")

            # 17. 411号Phase 12：成本价预计算
            try:
                _cost_feat = {}
                try:
                    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import MainForceScorer
                    mfs = MainForceScorer()
                    _latest_close = float(df['close'].values[-1]) if len(df) > 0 else 0.0
                    _cost_feat['main_force_cost'] = mfs._calc_main_force_cost(code, _latest_close) if len(df) >= 20 and code else None
                    _cost_feat['margin_cost_price'] = mfs._calc_margin_cost_price(code, _latest_close) if code and _latest_close > 0 else None
                except Exception as _e:
                    # 461-12：成本价预计算失败，cost_ext 留空，记日志防静默吞
                    logger.debug(f"RAW成本价计算失败 [{code}]: {_e}")
                features['cost_ext'] = _cost_feat
            except Exception as e:
                logger.debug(f"RAW成本价失败 [{code}]: {e}")

            # 18. 411号Phase 13：量指标预计算（461-13 删 volatility_20d/roc_20 死键，vol_ma 被 volume_price_strategy 消费）
            try:
                _vol_feat = {}
                if len(df) >= 20:
                    close = df['close'].astype(float)
                    vol = df['vol'].astype(float) if 'vol' in df.columns else df['amount'].astype(float)
                    # 量MA
                    _vol_feat['vol_ma5'] = float(vol.rolling(5).mean().iloc[-1]) if len(vol) >= 5 else None
                    _vol_feat['vol_ma10'] = float(vol.rolling(10).mean().iloc[-1]) if len(vol) >= 10 else None
                    _vol_feat['vol_ma20'] = float(vol.rolling(20).mean().iloc[-1]) if len(vol) >= 20 else None
                features['volume_ext'] = _vol_feat
            except Exception as e:
                logger.debug(f"RAW量指标失败 [{code}]: {e}")

            # 14. 情绪环境扩展字段（365号批次A+B / Phase 4）
            try:
                from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
                _emotion_feat = {}
                # emotion_temperature: 0-100温度值
                _sent = features.get('sentiment', {})
                _sect = features.get('sector', {})
                _vp_f_em = features.get('volume_price', {})
                _emotion_feat['emotion_temperature'] = calc_emotion_temperature(
                    sentiment_phase=_sent.get('sentiment_phase', 'neutral'),
                    limit_up_count=_sent.get('limit_up_count', 0) if isinstance(_sent.get('limit_up_count'), int) else 0,
                    sealing_rate=_sent.get('sealing_rate', 50.0) if isinstance(_sent.get('sealing_rate'), (int, float)) else 50.0,
                    sector_rank=_sect.get('sector_rank'),
                    volume_price_fit=_vp_f_em.get('volume_price_fit', 'neutral'),
                    # 447号 T1a：breadth 用全市场 MA20 强势股占比（market_stats），
                    # margin_change_pct RAW 预计算无逐股融资余额可靠源，保留默认（中性 50）
                    breadth=(_market_stats_cache.get('ma20_ratio') if _market_stats_cache
                             and isinstance(_market_stats_cache.get('ma20_ratio'), (int, float)) else None),
                )
                # market_emotion: 市场情绪阶段
                _emotion_feat['market_emotion'] = _sent.get('sentiment_phase', 'neutral')
                # sector_emotion: 板块情绪
                _emotion_feat['sector_emotion'] = 'hot' if (_sect.get('sector_rank') or 999) <= 10 else 'normal'
                # stock_emotion: 个股情绪
                _emotion_feat['stock_emotion'] = 'positive' if _vp_f_em.get('volume_price_fit') == 'healthy' else ('negative' if _vp_f_em.get('volume_price_fit') == 'diverging' else 'neutral')
                # 447号 T1a：涨停家数/封板率 透传 emotion_ext，供 dim5 实时温度（data_context['emotion_ext']）
                if isinstance(_sent.get('limit_up_count'), int):
                    _emotion_feat['limit_up_count'] = _sent['limit_up_count']
                if isinstance(_sent.get('sealing_rate'), (int, float)):
                    _emotion_feat['sealing_rate'] = float(_sent['sealing_rate'])
                features['emotion_ext'] = _emotion_feat
            except Exception as e:
                logger.warning(f"RAW情绪扩展字段失败 [{code}]: {e}")

            # 15. 量价健康扩展字段（365号批次A / Phase 5）——443号R5 删除：
            # vp_score 恒 None 占位、vp_state_type/volume_energy 无消费者（412 §8.4 删无消费者预计算）

            # 16. 结构位置扩展字段（365号批次A / Phase 6）
            try:
                _struct_feat = {}
                _sr_result = calc_support_resistance(df)
                _struct_feat['support_price'] = _sr_result.get('support_price')
                _struct_feat['resistance_price'] = _sr_result.get('resistance_price')
                # indicator_status: 均线排列+趋势方向综合
                _ma = _vp_f.get('ma_alignment', '')
                _trend = _cl.get('trend_direction', '')
                _struct_feat['indicator_status'] = f"ma={_ma},trend={_trend}"
                features['structure_ext'] = _struct_feat
            except Exception as e:
                logger.warning(f"RAW结构位置扩展字段失败 [{code}]: {e}")

            # 19. market_stats：全市场级统计（供dim5 BociasiQuadrant消费）
            # ponytail: market_stats是全市场共享数据，所有股票写入相同值
            try:
                features['market_stats'] = _market_stats_cache if _market_stats_cache else {}
            except Exception:
                features['market_stats'] = {}

            return features, trade_date

        for code in codes:
            # 428 P1-2 动作②：进度日志（每 500 只）
            _progress_n += 1
            if _progress_n % 500 == 0:
                logger.info(f"  [RAW-2] 进度: {_progress_n}/{len(codes)} (succeeded={succeeded}, failed={failed}, {time.time()-t0:.1f}s)")
            try:
                _res = _run_with_timeout(lambda: _raw2_one(code), timeout_sec=60.0, desc=f"RAW-2 特征 {code}")
                if _res is None:
                    failed += 1  # 428 P1-2 动作③：单股超时或特征计算异常
                    continue
                features, trade_date = _res
                if not features:
                    continue  # 数据不足静默跳过（不计数 failed）
                # 写入 pre_feat_cache
                if features:
                    _ecm.cache_pre_feat(code, trade_date, features)
                    succeeded += 1
                    commit_count += 1
                    if commit_count >= BATCH_SIZE:
                        _ecm.conn.commit()
                        commit_count = 0

            except Exception:
                failed += 1
                continue
        if commit_count > 0:
            _ecm.conn.commit()

        elapsed = time.time() - t0
        # 414号R9: 增加失败统计日志
        logger.info(f"RAW-2 原料加工完成: {succeeded}/{len(codes)} 只, 失败 {failed}, 耗时 {elapsed:.1f}s"
                    f", trade_date={trade_date}")
        _last_step_counts['RAW-2'] = f"{succeeded}/{len(codes)} stocks (fail={failed})"


def _add_vp_simple_tags(df, tags):
    """计算简单量价标签：ma_alignment / volume_price_fit / volatility_level（461-13 删 gap_type/breakout_attempts 死算）"""
    closes = df['close'].values
    opens = df['open'].values if 'open' in df.columns else closes
    highs = df['high'].values if 'high' in df.columns else closes
    lows = df['low'].values if 'low' in df.columns else closes
    vols = df['vol'].values if 'vol' in df.columns else np.ones(len(closes))

    if len(closes) >= 20:
        ma5 = np.mean(closes[-5:])
        ma10 = np.mean(closes[-10:])
        ma20 = np.mean(closes[-20:])
        ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else 0
        # ma_alignment
        if ma5 > ma10 > ma20 > ma60 and ma60 > 0:
            tags['ma_alignment'] = 'bullish'
        elif ma5 < ma10 < ma20 < ma60 and ma60 > 0:
            tags['ma_alignment'] = 'bearish'
        else:
            tags['ma_alignment'] = 'mixed'

        # volume_price_fit: 价格趋势 vs 量能趋势
        if len(closes) >= 10:
            price_trend = closes[-1] / closes[-10] - 1
            vol_trend = np.mean(vols[-5:]) / max(np.mean(vols[-10:-5]), 1) - 1
            # 308号硬缺口④调优：收紧背离与健康阈值，减少过度否决/过度乐观
            if price_trend > 0.02 and vol_trend > 0.15:
                tags['volume_price_fit'] = 'healthy'  # 放量上涨（量增≥15%）
            elif price_trend < -0.02 and vol_trend < -0.1:
                tags['volume_price_fit'] = 'healthy'  # 缩量下跌（卖压减轻）
            elif price_trend > 0.02 and vol_trend < -0.2:
                tags['volume_price_fit'] = 'diverging'  # 显著缩量上涨(背离，vt<-20%)
            elif abs(price_trend) < 0.01 and vol_trend > 0.2:
                tags['volume_price_fit'] = 'diverging'  # 放量滞涨
            else:
                tags['volume_price_fit'] = 'neutral'

        # volatility_level: 20日波动率
        if len(closes) >= 20:
            returns = np.diff(closes[-21:]) / closes[-21:-1]
            vol = np.std(returns) * 100
            if vol > 3:
                tags['volatility_level'] = 'high'
            elif vol > 1.5:
                tags['volatility_level'] = 'medium'
            else:
                tags['volatility_level'] = 'low'

        # pattern_signal: EnhancedPatternDetector 完整形态检测（308号/309号 S1）
        # 45+ 种规则（预涨/预跌/黑马/K线反转），预跌型优先（否决语义：风险信号比确认信号更重要）
        if len(closes) >= 5:
            try:
                from app.engine.framework.volume_price_strategy import EnhancedPatternDetector
                detector = EnhancedPatternDetector()
                pats = detector.detect_all(closes, opens, highs, lows, vols)
                if pats:
                    # 预跌型优先：若同时存在预涨/预跌形态，取预跌（保守，供闸门2否决）
                    bearish = [p for p in pats if '预跌' in p]
                    bullish = [p for p in pats if ('预涨' in p or '黑马' in p)]
                    if bearish:
                        tags['pattern_signal'] = bearish[0].split('(')[0]
                    elif bullish:
                        tags['pattern_signal'] = bullish[0].split('(')[0]
                    else:
                        tags['pattern_signal'] = pats[0].split('(')[0]
                else:
                    tags['pattern_signal'] = 'none'
            except Exception:
                # 兜底：回退到简单双底/突破检测
                tags['pattern_signal'] = _simple_pattern_fallback(lows, highs, closes)


def _simple_pattern_fallback(lows, highs, closes) -> str:
    """EnhancedPatternDetector 不可用时的简单形态兜底检测"""
    try:
        if len(closes) >= 5:
            recent_low = np.min(lows[-5:])
            recent_high = np.max(highs[-5:])
            mid = (recent_low + recent_high) / 2
            dips = sum(1 for i in range(-5, 0) if abs(lows[i] - recent_low) / max(recent_low, 1) < 0.01)
            if dips >= 2 and closes[-1] > mid:
                return 'double_bottom'
            if len(closes) >= 20 and closes[-1] > np.max(highs[-20:-1]) * 1.02:
                return 'breakout'
    except Exception:
        pass
    return 'none'


def _update_with_event_tags(ts_code: str, tags: dict):
    """调用 EventMonitor 获取事件标签（P2.1）"""
    from app.opportunity_atlas.event_monitor import EventMonitor
    em = EventMonitor()
    em_tags = em.compute_tags(ts_code)
    if em_tags:
        tags.update(em_tags)


def _add_upward_driver(df, tags):
    """计算 upward_driver 上涨驱动力标签（302号§三 收益分解框架）"""
    closes = df['close'].values
    opens = df['open'].values
    if len(closes) < 20:
        return
    n = min(20, len(closes))
    overnight_returns = np.abs(np.array([
        (opens[-(i+1)] / closes[-(i+2)] - 1) for i in range(n-1)
    ]))
    intraday_returns = np.abs(np.array([
        (closes[-(i+1)] / opens[-(i+1)] - 1) for i in range(n-1)
    ]))
    total_returns = overnight_returns + intraday_returns
    if total_returns.sum() < 0.01:
        tags['upward_driver'] = 'no_upward'
        return
    overnight_ratio = overnight_returns.sum() / total_returns.sum()
    extreme_count = sum(1 for r in intraday_returns if r > 0.03)
    extreme_ratio = extreme_count / max(len(intraday_returns), 1)
    if overnight_ratio > 0.4 and extreme_ratio < 0.3:
        tags['upward_driver'] = 'info_driven'
    elif extreme_ratio > 0.4 and overnight_ratio < 0.2:
        tags['upward_driver'] = 'emotion_driven'
    elif overnight_ratio > 0.25:
        tags['upward_driver'] = 'mixed'
    else:
        tags['upward_driver'] = 'no_upward'


def _classify_opportunity_type(tags: dict) -> dict:
    """规则树：根据多标签联合判定机会类型（307号§3.1.3，画像速览摘要）

    返回 {'opportunity_type': ..., 'opportunity_label': ...}
    """
    mfp  = tags.get('main_force_phase')
    fina = tags.get('fina_health')
    val  = tags.get('valuation_level')
    sp   = tags.get('sentiment_phase')
    sh   = tags.get('sector_heat')
    vl   = tags.get('volatility_level')
    dy   = tags.get('dividend_yield')
    ce   = tags.get('catalyst_event', 'none')

    # 类型 → (标识, 中文标签)
    def _t(t, label):
        return {'opportunity_type': t, 'opportunity_label': label}

    # R0: 跨维仲裁 avoid 降级（321号 S3：规则树互斥——回避态强制降级，
    #     不再输出"主力建仓观察/慢牛上涨"等看多类型，修 T2 矛盾）
    if tags.get('opportunity_state') == 'avoid':
        return _t('avoid_only', '回避·仅观察')

    # R1: 危险区
    if mfp == 'distributing' and fina == 'fail':
        return _t('danger_zone', '出货已确认，风险区域')
    if mfp == 'distributing' and val in ('high', 'extreme_high'):
        return _t('danger_overval', '出货+高估，风险区域')

    # R2: 价值底部区
    if mfp == 'building' and fina == 'pass' and val in ('extreme_low', 'low'):
        return _t('value_bottom', '估值底部，基本面优质')

    # R3: 建仓在高位
    if mfp == 'building' and val in ('high', 'extreme_high'):
        return _t('build_high', '建仓在高位，矛盾信号')

    # R4: 主力建仓观察
    if mfp == 'building':
        return _t('building_watch', '主力建仓观察')

    # R5: 主升浪
    if mfp == 'lifting' and sp == 'climax' and sh in ('top_10', 'top_20'):
        return _t('main_upsurge', '趋势加速，动量充分')
    # R6: 慢牛
    if mfp == 'lifting' and sh in ('none', 'normal'):
        return _t('steady_rise', '慢牛上涨')
    # R7: 拉升基线
    if mfp == 'lifting':
        return _t('lifting_general', '拉升阶段')

    # R8: 洗盘热点
    if mfp == 'washing' and sh in ('top_10', 'top_20'):
        return _t('wash_hot', '洗盘热点，关注突破')
    # R9: 洗盘基线
    if mfp == 'washing':
        return _t('wash_general', '洗盘整理')

    # R10: 优质不明
    if fina == 'pass' and val in ('extreme_low', 'low'):
        return _t('quality_unknown', '优质不明')

    # R11: 高股息策略
    if dy is not None:
        try:
            if float(dy) > 3:
                return _t('dividend_play', '高股息收益')
        except (ValueError, TypeError):
            pass

    # R12: 事件驱动
    if ce and ce not in ('', 'none', 'None') and vl == 'high':
        return _t('event_driven', '事件催化，快进快出')
    # R13: 事件观察
    if ce and ce not in ('', 'none', 'None'):
        return _t('event_watch', '事件观察')

    # R14: 冷门价值
    if fina == 'pass' and sh in ('none', 'normal') and val in ('fair', 'extreme_low', 'low'):
        return _t('cold_value', '冷门价值')

    # R15: 无信号
    if mfp in (None, '', 'unknown'):
        return _t('no_signal', '无明确信号')

    # 兜底：根据情绪阶段确定基线
    if sp == 'ice':
        return _t('sentiment_ice', '情绪冰点')
    if sp == 'climax':
        return _t('sentiment_climax', '情绪高潮')
    if sp == 'ebb':
        return _t('sentiment_ebb', '情绪退潮')
    return _t('default', '一般机会')


def _build_opportunity_profile(tags: dict) -> dict:
    """七维机会画像（307号§3.1.2）：七个维度独立判定、并列呈现

    每维输出 {状态, 红绿灯}：🟢 好 / 🟡 中性 / 🔴 风险
    返回 {'opportunity_profile': {维度: {status, light}}, ...}
    """
    def _light(v, green, red):
        return '🟢' if v in green else ('🔴' if v in red else '🟡')

    mfp = tags.get('main_force_phase')
    fina = tags.get('fina_health')
    val = tags.get('valuation_level')
    ff = tags.get('fund_flow')
    ce = tags.get('catalyst_event', 'none')
    sp = tags.get('sentiment_phase')

    # 风险：财务健康 + 出货
    risk_status = ('安全' if fina == 'pass' else
                   '危险' if fina == 'fail' or mfp == 'distributing' else '警戒')
    risk_light = '🟢' if risk_status == '安全' else ('🔴' if risk_status == '危险' else '🟡')

    # 价值：估值水平
    val_status = ('低估' if val in ('low', 'extreme_low') else
                  '高估' if val in ('high', 'extreme_high') else '合理')
    val_light = '🟢' if val_status == '低估' else ('🔴' if val_status == '高估' else '🟡')

    # 趋势：主力阶段
    trend_map = {
        'building': ('建仓', '🟡'), 'washing': ('洗盘', '🟡'), 'lifting': ('拉升', '🟢'),
        'distributing': ('出货', '🔴'), None: ('不明', '🟡'), '': ('不明', '🟡'),
        'unknown': ('不明', '🟡'),
    }
    trend_status, trend_light = trend_map.get(mfp, ('不明', '🟡'))

    # 量价：量价配合
    vpf = tags.get('volume_price_fit')
    vp_status = '健康' if vpf == 'healthy' else ('背离' if vpf == 'diverging' else '中性')
    vp_light = '🟢' if vp_status == '健康' else ('🔴' if vp_status == '背离' else '🟡')

    # 资金：资金流 + 筹码
    ff_status = '流入' if ff == '5d_inflow' else ('流出' if ff == '5d_outflow' else '中性')
    ff_light = '🟢' if ff_status == '流入' else ('🔴' if ff_status == '流出' else '🟡')

    # 情绪：市场情绪 + 板块热度（447号 T2a：六段论 ice/sprout/ferment/climax/ebb/regression，去 recovery）
    sp_status = {'ice': '冰点', 'sprout': '萌芽', 'ferment': '发酵', 'climax': '高潮', 'ebb': '退潮', 'regression': '回归'}.get(sp, '中性')
    sp_light = '🟡' if sp_status == '冰点' else ('🔴' if sp_status in ('高潮', '退潮') else '🟢')

    # 事件：催化剂（L3修复：三态 正向🟢/负向🔴/无⚪，307号§3.1.9）
    # 正向/负向分类与 L4 VOTE_MAP catalyst_event 保持一致
    _POS_EVENTS = {'earnings', 'lhb', 'concept', 'buyback', 'breakout', 'new_high', 'profit_growth'}
    _NEG_EVENTS = {'pledge', 'float', 'reduce', 'fraud_sign', 'regulatory', 'lawsuit', 'decline'}
    ce = str(ce or 'none').strip()
    if ce == 'none' or ce == 'None' or ce == '':
        ev_status, ev_light = '无事件', '⚪'
    elif ce in _POS_EVENTS:
        ev_status, ev_light = f'正向({ce})', '🟢'
    elif ce in _NEG_EVENTS:
        ev_status, ev_light = f'负向({ce})', '🔴'
    else:
        ev_status, ev_light = f'事件({ce})', '🟡'

    return {'opportunity_profile': {
        'risk': {'status': risk_status, 'light': risk_light},
        'value': {'status': val_status, 'light': val_light},
        'trend': {'status': trend_status, 'light': trend_light},
        'volume_price': {'status': vp_status, 'light': vp_light},
        'fund': {'status': ff_status, 'light': ff_light},
        'sentiment': {'status': sp_status, 'light': sp_light},
        'event': {'status': ev_status, 'light': ev_light},
    }}


# 各机会类型的证据标签集（307号§3.1.7 证据计数）
_TYPE_EVIDENCE = {
    'value_bottom': ['main_force_phase', 'fina_health', 'valuation_level',
                     'price_position', 'trend_alignment', 'chip_concentration',
                     'signal_strength'],
    'building_watch': ['main_force_phase', 'price_position', 'fund_flow',
                       'chip_concentration', 'trend_alignment'],
    'build_high': ['main_force_phase', 'valuation_level'],
    'main_upsurge': ['main_force_phase', 'sentiment_phase', 'sector_heat',
                     'trend_alignment', 'signal_strength'],
    'steady_rise': ['main_force_phase', 'sector_heat', 'trend_alignment', 'ma_alignment'],
    'wash_hot': ['main_force_phase', 'sector_heat', 'chip_concentration'],
    'wash_general': ['main_force_phase', 'chip_concentration', 'volume_price_fit'],
    'danger_zone': ['main_force_phase', 'fina_health'],
    'danger_overval': ['main_force_phase', 'valuation_level'],
    'dividend_play': ['dividend_yield', 'fina_health'],
    'event_driven': ['catalyst_event', 'volatility_level'],
    'event_watch': ['catalyst_event'],
    'cold_value': ['fina_health', 'sector_heat', 'valuation_level'],
    'quality_unknown': ['fina_health', 'valuation_level'],
    'no_signal': ['main_force_phase'],
    # 2026-08-10 325档案修复：补 6 类缺证据模板
    # （原缺失致 evidence_count=0 达 597 只）
    'avoid_only': ['fina_health', 'valuation_level', 'catalyst_event',
                   'main_force_phase', 'volume_price_fit', 'price_position',
                   'right_side_confirm'],
    'sentiment_ice': ['sentiment_phase', 'sector_heat', 'volatility_level',
                      'price_position', 'main_force_phase'],
    'sentiment_ebb': ['sentiment_phase', 'sector_heat', 'volatility_level',
                      'price_position', 'main_force_phase'],
    'sentiment_climax': ['sentiment_phase', 'sector_heat', 'volatility_level',
                         'price_position', 'main_force_phase'],
    'lifting_general': ['main_force_phase', 'trend_alignment', 'ma_alignment',
                        'volume_price_fit', 'signal_strength'],
}


def _count_evidence(opportunity_type: str, tags: dict) -> dict:
    """多标签共识证据计数（307号§3.1.7）

    统计共同支持该机会类型判定的标签命中数，输出证据数与可信度。
    """
    evidence_tags = _TYPE_EVIDENCE.get(opportunity_type, [])
    hit = 0
    total = len(evidence_tags)
    for t in evidence_tags:
        v = tags.get(t)
        if v is not None and v not in ('', 'none', 'None', 'unknown', 0):
            hit += 1
    # 可信度分档：≥5 强共识 / 3-4 中等 / 1-2 弱
    if hit >= 5:
        confidence = 'confident'
    elif hit >= 3:
        confidence = 'plausible'
    else:
        confidence = 'weak'
    return {'evidence_count': hit, 'evidence_total': total, 'confidence': confidence}


def _compute_opportunity_meta(tags: dict):
    """机会元信息（307号）：七维画像 + 机会类型摘要 + 证据计数

    替代 306号 _compute_hold_period 的三字段输出（hold_period/hold_period_days/hold_status_type）。
    """
    # 七维画像
    profile = _build_opportunity_profile(tags)
    # 画像为嵌套 dict，序列化为 JSON 字符串以便落库至 opportunity_tags_cache（309号 S3）
    profile['opportunity_profile'] = json.dumps(
        profile['opportunity_profile'], ensure_ascii=False)
    tags.update(profile)

    # 机会类型摘要
    type_result = _classify_opportunity_type(tags)
    tags.update(type_result)

    # 证据计数
    ev = _count_evidence(type_result['opportunity_type'], tags)
    tags.update(ev)

    # 入场/退出条件（307号§3.2/§3.3，结构化 JSON）
    try:
        tags.update(_compute_entry_signals(type_result['opportunity_type'], tags))
    except Exception:
        pass
    try:
        tags.update(_compute_exit_conditions(type_result['opportunity_type'], tags))
    except Exception:
        pass


# 各机会类型入场条件模板（307号§3.2，右侧确认 + 类型特定条件）
_ENTRY_SIGNAL_TEMPLATES = {
    'value_bottom': [
        {'desc': '估值仍在低估区间（low/extreme_low）', 'check': 'valuation_level in (low, extreme_low)'},
        {'desc': '基本面未恶化（fina_health=pass）', 'check': 'fina_health == pass'},
        {'desc': '右侧确认：放量站上MA20 或 底分型回踩确认', 'check': 'right_side_confirm in (基础确认, 强确认)'},
    ],
    'building_watch': [
        {'desc': '主力阶段仍在建仓（building）', 'check': 'main_force_phase == building'},
        {'desc': '突破建仓成本区间上沿（放量）', 'check': 'right_side_confirm in (基础确认, 强确认)'},
    ],
    'main_upsurge': [
        {'desc': '主力阶段拉升（lifting）', 'check': 'main_force_phase == lifting'},
        {'desc': '回踩关键支撑（MA10）不破时入场，不追高', 'check': 'close > ma10'},
    ],
    'steady_rise': [
        {'desc': '主力阶段拉升（lifting）', 'check': 'main_force_phase == lifting'},
        {'desc': '价格沿MA20缓步上行', 'check': 'close > ma20'},
        {'desc': '无超买信号', 'check': 'not overbought'},
    ],
    'dividend_play': [
        {'desc': '股息率 > 3%', 'check': 'dividend_yield > 3'},
        {'desc': '价格未出现急涨（避免均值回归）', 'check': 'pct_chg < 5'},
        {'desc': '基本面未恶化（fina_health=pass）', 'check': 'fina_health == pass'},
    ],
    'event_driven': [
        {'desc': '催化剂事件确认', 'check': 'catalyst_event != none'},
        {'desc': '放量启动', 'check': 'volume_price_fit == healthy'},
        {'desc': '设置严格止损位后入场', 'check': 'stop_loss_set'},
    ],
    'wash_hot': [
        {'desc': '洗盘结束信号（缩量到极致后放量）', 'check': 'volume_price_fit == healthy'},
        {'desc': '突破洗盘区间上沿', 'check': 'right_side_confirm in (基础确认, 强确认)'},
    ],
    'wash_general': [
        {'desc': '洗盘结束需站上短期均线', 'check': 'right_side_confirm in (基础确认, 强确认)'},
    ],
    'danger_zone': [
        {'desc': '无条件——危险区不应入场', 'check': 'never'},
    ],
    'danger_overval': [
        {'desc': '无条件——出货+高估不应入场', 'check': 'never'},
    ],
}

# 各机会类型退出条件模板（307号§3.3，任一满足即退出）
_EXIT_CONDITION_TEMPLATES = {
    'value_bottom': [
        {'desc': '估值回到 fair 以上', 'check': 'valuation_level in (fair, high, extreme_high)'},
        {'desc': '基本面恶化（fina_health in (fail, suspicious)）', 'check': 'fina_health in (fail, suspicious)'},
        {'desc': '出货信号（main_force_phase → distributing）', 'check': 'main_force_phase == distributing'},
    ],
    'building_watch': [
        {'desc': '跌破建仓成本区间下沿（建仓失败）', 'check': 'close < build_cost_low'},
        {'desc': '主力阶段变为 distributing', 'check': 'main_force_phase == distributing'},
    ],
    'main_upsurge': [
        {'desc': '顶分型 + 量价背离', 'check': 'top_fractal and volume_price_fit == diverging'},
        {'desc': '跌破 MA10/MA20', 'check': 'close < ma10 or close < ma20'},
        {'desc': '主力阶段变为 distributing', 'check': 'main_force_phase == distributing'},
    ],
    'steady_rise': [
        {'desc': '跌破 MA20 且 3 日内未收回', 'check': 'close < ma20'},
        {'desc': '出货信号', 'check': 'main_force_phase == distributing'},
    ],
    'event_driven': [
        {'desc': '催化剂事件已兑现', 'check': 'catalyst_event == consumed'},
        {'desc': '高波动消退（volatility 恢复正常）', 'check': 'volatility_level == low'},
        {'desc': '反向技术信号', 'check': 'right_side_confirm == 否决'},
    ],
    'dividend_play': [
        {'desc': '股息率跌破 2%', 'check': 'dividend_yield < 2'},
        {'desc': '基本面恶化（fina_health=fail）', 'check': 'fina_health == fail'},
    ],
    'wash_hot': [
        {'desc': '跌破洗盘区间下沿', 'check': 'close < wash_low'},
        {'desc': '主力阶段变为 distributing', 'check': 'main_force_phase == distributing'},
    ],
    'danger_zone': [
        {'desc': '无条件——已入场者立即退出', 'check': 'always'},
    ],
    'danger_overval': [
        {'desc': '无条件——已入场者立即退出', 'check': 'always'},
    ],
}


def _compute_entry_signals(opportunity_type: str, tags: dict) -> dict:
    """入场条件（307号§3.2）：按机会类型返回结构化入场条件列表

    满足判定叠加 L4 共识率 ≥55% 门禁（入场条件 = 右侧确认 AND L4 共识率）。
    """
    templates = _ENTRY_SIGNAL_TEMPLATES.get(opportunity_type)
    if not templates:
        templates = [{'desc': '一般机会：等待右侧确认信号', 'check': 'right_side_confirm in (基础确认, 强确认)'}]
    # 附加 L4 共识率门禁（307号§3.2：入场条件 = 类型条件 AND 共识率 ≥55%）
    result = templates + [
        {'desc': 'L4 共识率 ≥ 65%（方向可信度门禁）', 'check': 'consensus_rate >= 0.65'},
    ]
    return {'entry_signals': json.dumps(result, ensure_ascii=False)}


def _compute_exit_conditions(opportunity_type: str, tags: dict) -> dict:
    """退出条件（307号§3.3）：按机会类型返回结构化退出条件列表

    任一满足即退出；与 L4 估值跟踪退出（300号§2.2）并列。
    """
    templates = _EXIT_CONDITION_TEMPLATES.get(opportunity_type)
    if not templates:
        templates = [
            {'desc': '技术面走坏（右侧确认变为否决）', 'check': 'right_side_confirm == 否决'},
            {'desc': '出货信号（main_force_phase → distributing）', 'check': 'main_force_phase == distributing'},
        ]
    result = templates + [
        {'desc': 'L4 估值跟踪退出触发（估值修复完成）', 'check': 'valuation_tracking.action == exit'},
    ]
    return {'exit_conditions': json.dumps(result, ensure_ascii=False)}


# 各机会类型的基础确认信号（308号§四映射表，STEP 2）
_BASE_CONFIRM = {
    'value_bottom':   'ma20',   # 放量站上MA20
    'building_watch': 'chip',   # 突破建仓成本区上沿
    'build_high':     'ma10',   # 高位需更强确认（回踩MA10不破）
    'main_upsurge':   'ma10',   # 回踩MA10不破
    'steady_rise':    'ma20',   # MA20之上稳步上行
    'wash_hot':       'chip',   # 突破洗盘区间上沿（筹码峰近似）
    'wash_general':   'ma10',   # 洗盘结束需站上短均线
    'dividend_play':  'ma20',   # 价格低位企稳（站上MA20）
    'event_driven':   'ma10',   # 放量启动后站上MA10
    'event_watch':    'ma10',
    'cold_value':     'ma20',
    'quality_unknown':'ma20',
}


def _check_right_side_confirm(opportunity_type: str, tags: dict, df: 'pd.DataFrame') -> dict:
    """闸门2右侧确认三档判定（309号§7.1，308号）

    判定流程：
      STEP 1 否决检查（一票否决）：缠论卖点 / 量价背离 / 预跌形态
      STEP 2 基础确认（必选）：按机会类型查均线/筹码确认信号
      STEP 3 增强确认（加分）：缠论二买三买 / 预涨黑马形态 / 级别验证

    输出: right_side_confirm = 强确认|基础确认|未确认|否决
         confirm_evidence = [命中信号列表]
    """
    confirm_evidence = []
    bs = tags.get('buy_sell_point', 'none')
    vpf = tags.get('volume_price_fit', 'neutral')
    pat = tags.get('pattern_signal', 'none')

    # ── STEP 1 否决检查（一票否决） ──
    # 2026-08-10 325档案修复：收缩否决面——仅强卖点（趋势顶背驰 first_sell /
    # 盘整背驰 first_sell_p）一票否决；弱卖点（third_sell 中枢破位/second_sell
    # 确认）降级"未确认"走 STEP2 基础确认闸（原四值全否决致否决率 49.9%、
    # 86% 由缠论卖点触发，avoid 65% 主驱动）
    if bs in ('first_sell', 'first_sell_p'):
        return {'right_side_confirm': '否决',
                'confirm_evidence': json.dumps([f'缠论强卖点 {bs}'],
                                               ensure_ascii=False)}
    if bs in ('second_sell', 'third_sell'):
        return {'right_side_confirm': '未确认',
                'confirm_evidence': json.dumps([f'缠论弱卖点 {bs}，降级观望'],
                                               ensure_ascii=False)}
    if vpf == 'diverging':
        return {'right_side_confirm': '否决', 'confirm_evidence': json.dumps(['量价背离'], ensure_ascii=False)}
    if pat and '预跌' in str(pat):
        return {'right_side_confirm': '否决', 'confirm_evidence': json.dumps([f'预跌形态 {pat}'], ensure_ascii=False)}

    # ── STEP 2 基础确认（按机会类型） ──
    base_key = _BASE_CONFIRM.get(opportunity_type, 'ma20')
    base_ok = False
    has_df = df is not None and not df.empty and 'close' in df.columns
    closes = df['close'].values if has_df else None
    if closes is not None and len(closes) >= 20:
        price = closes[-1]
        if base_key == 'ma20':
            ma20 = float(df['close'].tail(20).mean())
            vol20 = float(df['vol'].tail(20).mean()) if 'vol' in df.columns else 0
            vol5 = float(df['vol'].tail(5).mean()) if 'vol' in df.columns and len(df) >= 5 else 0
            # 放量站上 MA20：收盘 > MA20 且近5日均量 ≥ 20日均量
            if price > ma20 and vol5 >= vol20:
                base_ok = True
                confirm_evidence.append('放量站上20日均线')
        elif base_key == 'ma10':
            ma10 = float(df['close'].tail(10).mean())
            if price > ma10:
                base_ok = True
                confirm_evidence.append('站上10日均线')
        elif base_key == 'chip':
            # 筹码峰近似：收盘价处于近60日区间上1/3（突破区间上沿的简化判定）
            if len(closes) >= 60:
                hi60 = (float(df['high'].tail(60).max()) if 'high' in df.columns
                        else float(closes[-60:].max()))
                lo60 = (float(df['low'].tail(60).min()) if 'low' in df.columns
                        else float(closes[-60:].min()))
                if price >= lo60 + (hi60 - lo60) * 0.75:
                    base_ok = True
                    confirm_evidence.append('突破60日区间上沿')
    if not base_ok:
        return {'right_side_confirm': '未确认',
                'confirm_evidence': json.dumps(confirm_evidence or ['基础确认信号未满足'], ensure_ascii=False)}

    # ── STEP 3 增强确认（加分） ──
    enhance = 0
    if bs in ('second_buy', 'third_buy', 'third_buy_a', 'third_buy_b'):
        enhance += 1
        confirm_evidence.append(f'缠论{bs}')
    if pat and ('预涨' in str(pat) or '黑马' in str(pat)):
        enhance += 1
        confirm_evidence.append(f'形态确认 {pat}')
    # 级别验证：周线向上近似（收盘 > 20周均线≈100日均线）
    if closes is not None and len(closes) >= 100:
        ma100 = float(df['close'].tail(100).mean())
        if closes[-1] > ma100:
            enhance += 1
            confirm_evidence.append('中期趋势向上')
    # S7二期（308号P3）：趋势线/123法则检测（结构反转确认）
    if df is not None and len(df) >= 30:
        try:
            from app.engine.framework.trend_structure_detector import TrendStructureDetector
            _tsd = TrendStructureDetector()
            _ts = _tsd.detect(df)
            if _ts and _ts.get('signal') in ('123_buy_breakout', 'higher_low'):
                enhance += 1
                confirm_evidence.append('123法则结构反转')
        except Exception:
            pass

    level = '强确认' if enhance >= 2 else '基础确认'
    return {'right_side_confirm': level,
            'confirm_evidence': json.dumps(confirm_evidence, ensure_ascii=False)}


def _compute_style_exposure(ts_code: str, tags: dict, df: 'pd.DataFrame' = None) -> str:
    """计算 style_exposure 标签（295号§3.2 标签12）

    基于行业分类和市值判定风格归属：
    - 金融/银行 → large_value
    - 科技/高研发 → large_growth（如果大市值）或 small_growth
    - 周期行业 → small_value（如果小市值）或 large_value

    2026-08-10 修复：大小盘判定改用市值（原用 sector_heat 板块热度——
    茅台等超大盘股板块热度低被判 small，75.8% 落 cyclical 失真）。
    """
    vl = tags.get('valuation_level', 'fair')
    
    # 简单的行业风格映射
    try:
        from app.data import DataManager
        dm = DataManager()
        industry = dm.get_stock_industry(ts_code)
    except Exception:
        industry = None

    if not industry:
        return 'none'

    # 2026-08-10 修复：大小盘用市值判定（>500亿=大盘；daily_basic.total_mv 单位万元）
    is_large = False
    try:
        _basic = dm.get_cached_daily_basic(ts_code)
        if _basic is not None and not _basic.empty and 'total_mv' in _basic.columns:
            _mv = float(_basic['total_mv'].iloc[-1])
            is_large = _mv * 1e4 > 5e10  # 500亿元
    except Exception:
        pass
    is_value = vl in ('extreme_low', 'low')

    if industry in ('银行', '非银金融'):
        return 'large_value'
    elif industry in ('电子', '计算机', '通信', '电力设备', '国防军工', '医药生物'):
        return 'large_growth' if is_large else 'small_growth'
    elif industry in ('钢铁', '有色金属', '煤炭', '石油石化', '基础化工', '房地产', '建筑材料'):
        return 'large_value' if is_large else 'small_value'
    elif is_large and is_value:
        return 'large_value'
    elif is_large:
        return 'large_growth'
    elif is_value:
        return 'small_value'
    else:
        return 'cyclical'


def _precompute_single(ts_code: str):
    """单只股票策略预计算（P6增量触发用）

    用于自选股变动/开机自检时对单只股票执行策略预计算并写入缓存。
    不阻塞调用方，异常仅日志记录。

    注意：如果日线数据不足 60 行，说明数据采集未完成，
    先请求数据补采，跳过预计算，下次循环再试。
    """
    try:
        # 检查日线数据就绪性（问题4修复）
        df = _ecm.get_cached_daily(ts_code)
        if df is None or len(df) < 60:
            _ecm.request_data('per_stock', ts_code)
            logger.debug(f"  {ts_code} 日线不足 {len(df) if df is not None else 0} 行，先补采")
            return

        from app.engine.unified_core import UnifiedStrategyCore
        core = UnifiedStrategyCore()
        result = core.compute(ts_code)
        _ecm.cache_signal_detail(ts_code, result.to_dict())
        logger.debug(f"  单只预计算完成: {ts_code}")
    except Exception as e:
        logger.debug(f"  单只预计算跳过 ({ts_code}): {e}")


# ══════════════════════════════════════════════════════════
# Treemap 快照构建（305号§2.2.2）
# ══════════════════════════════════════════════════════════

def _get_active_codes(today_fmt: str = None) -> list[str]:
    """获取当日活跃股票代码列表（356号：从分库读取）

    441号A根治：剔除指数代码——本函数是全管道（RAW/SIG/JUD）统一股票池入口，
    原实现直取 daily_cache 全部 ts_code 未剔指数，致 SIG 目标混入指数（.SI/399.SZ/宽基），
    引发 dim1 对指数类的 stk_holder 误报补采。剔除集 = BROAD_INDEX_CODES + SW_INDEX_CODES
    + 通用段规则（.SI 后缀 / 399 开头深市指数段），不误伤个股。
    """
    if today_fmt is None:
        today_fmt = datetime.now().strftime('%Y-%m-%d')
    try:
        from app.data.sharding_manager import sharding_manager
        conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_cache'))
        rows = conn.execute(
            "SELECT ts_code FROM daily_cache WHERE trade_date=? GROUP BY ts_code ORDER BY ts_code",
            [today_fmt]
        ).fetchall()
        if not rows:
            row = conn.execute(
                "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            if row:
                today_fmt = row[0]
                rows = conn.execute(
                    "SELECT ts_code FROM daily_cache WHERE trade_date=? GROUP BY ts_code ORDER BY ts_code",
                    [today_fmt]
                ).fetchall()
        _index_exclude = set(BROAD_INDEX_CODES) | set(SW_INDEX_CODES)
        codes = [
            r[0] for r in rows
            if r[0] not in _index_exclude
            and not r[0].endswith('.SI')
            and not r[0].startswith('399')
        ]
        return codes if codes else []
    except Exception as e:
        logger.warning(f"_get_active_codes 分库查询失败: {e}")
        return []


def _compute_main_force_presence(code: str, ecm) -> dict:
    """主力在场判定（313号 §十：行为证据主导，不参与机会强度核心）

    行为证据（真实主力活动痕迹）：
      1. 龙虎榜近 30 日有席位记录 → strong（游资/机构席位证据）
      2. 股东户数环比减少 ≥5% → moderate（筹码集中吸筹证据）
      3. 融资余额 30 日增幅 >50% → risk（散户杠杆接盘/出货风险，知识库反向指标）
      无任何证据 → none

    Returns:
        {'main_force_presence': 'strong'|'moderate'|'risk'|'none',
         'presence_evidence': JSON 证据列表}
    """
    evidence = []
    presence = 'none'
    try:
        n_lhb = ecm.conn.execute(
            "SELECT COUNT(*) FROM lhb_cache WHERE ts_code=? "
            "AND trade_date >= date('now','-30 day')", [code]).fetchone()[0]
        if n_lhb and n_lhb > 0:
            evidence.append(f"龙虎榜 {min(n_lhb, 5)} 次")
            presence = 'strong'
    except Exception:
        pass
    try:
        rows = ecm.conn.execute(
            "SELECT end_date, holder_number FROM stk_holder_cache "
            "WHERE ts_code=? ORDER BY end_date DESC LIMIT 2", [code]).fetchall()
        if len(rows) >= 2 and rows[0][1] and rows[1][1]:
            prev, cur = float(rows[1][1]), float(rows[0][1])
            if prev > 0 and (prev - cur) / prev >= 0.05:
                evidence.append(f"股东户数减少 {(prev - cur) / prev * 100:.0f}%")
                if presence == 'none':
                    presence = 'moderate'
    except Exception:
        pass
    try:
        rows = ecm.conn.execute(
            "SELECT trade_date, rzye FROM margin_cache WHERE ts_code=? "
            "ORDER BY trade_date DESC LIMIT 1", [code]).fetchall()
        if rows and rows[0][1]:
            cur_f = float(rows[0][1])
            # 融资余额最早记录（30 日窗口内）：字符串日期直接比较（修复：原 date() 截断 bug）
            oldest = ecm.conn.execute(
                "SELECT rzye FROM margin_cache WHERE ts_code=? AND trade_date <= ? "
                "ORDER BY trade_date ASC LIMIT 1", [code, str(rows[0][0])]).fetchall()
            if oldest and oldest[0][0]:
                old_f = float(oldest[0][0])
                if old_f > 0 and (cur_f - old_f) / old_f > 0.5:
                    evidence.append("融资余额暴增 >50%")
                    presence = 'risk'
    except Exception:
        pass
    return {
        'main_force_presence': presence,
        'presence_evidence': json.dumps(evidence, ensure_ascii=False),
    }


def _compute_snapshot_consensus_rate(t: dict) -> float:
    """轻量 L4 共识率（313号 §五：闸门3 颜色细分）— 用 VOTE_MAP 对快照可用标签投票

    共识率 = 优势方向票 / 方向票总数（316号 P2：中性票不稀释方向共识；与 L4 _compute_consensus 同口径）
    """
    try:
        from app.opportunity_atlas.cross_validate import VOTE_MAP
        bullish = bearish = total = 0
        for tag_name, val in t.items():
            if val is None or val == '':
                continue
            mapping = VOTE_MAP.get(tag_name)
            if mapping is None:
                continue
            v = 0
            if tag_name == 'signal_strength':
                try:
                    fv = float(val)
                    v = 1 if fv >= 70.0 else (-1 if fv <= 40.0 else 0)
                except (ValueError, TypeError):
                    v = 0
            else:
                v = mapping.get(val, mapping.get(str(val), 0))
            if v > 0:
                bullish += 1
            elif v < 0:
                bearish += 1
            total += 1
        if total < 3:
            return 0.0
        direction_active = bullish + bearish
        if direction_active == 0:
            return 0.0
        if bullish > bearish:
            return round(bullish / direction_active, 3)
        if bearish > bullish:
            return round(bearish / direction_active, 3)
        return 0.0
    except Exception:
        return 0.0


def _jud_enrich_with_meta(codes: list[str]):
    """371号JUD接入：机会分类+潜力评分+右侧确认（预计算写入缓存供treemap使用）

    在 _build_status_snapshot 之后、_build_treemap_snapshot 之前调用。
    从 pre_feat_cache 加载原料标签，运行：
      1. _compute_opportunity_meta → opportunity_type/label/profile/evidence_count/entry/exit
      2. PotentialEngine.compute_potential → signal_strength/potential_breakdown
      3. _check_right_side_confirm → right_side_confirm/confirm_evidence
    结果写入模块级 _jud_meta_cache 供 treemap_snapshot 读取。
    """
    global _ecm, _jud_meta_cache
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    t0 = time.time()
    logger.info(f"JUD机会判定预计算: {len(codes)} 只...")

    _jud_meta_cache = {}  # 清空上轮缓存

    from app import create_app
    _flask_app = create_app()
    with _flask_app.app_context():
        from app.opportunity_atlas.status_engine import StatusEngine
        from app.data import DataManager
        dm = DataManager()
        se = StatusEngine()

        # PotentialEngine初始化（一次性构建截面百分位基准）
        pe = None
        try:
            from app.opportunity_atlas.potential_engine import PotentialEngine
            pe = PotentialEngine()
            pe.build_percentile_tables(dm.cache)
        except Exception as e:
            logger.warning(f"PotentialEngine初始化失败: {e}")

        enriched = 0
        for code in codes:
            try:
                # 从 pre_feat_cache 加载原料标签并扁平化
                pre_feat = _ecm.get_pre_feat(code)
                if not pre_feat:
                    continue
                tags = se._flatten_pre_feat(pre_feat)
                if not tags:
                    continue

                # 1. opportunity_meta（机会分类 + 七维画像 + 证据计数 + 入场/退出）
                try:
                    _compute_opportunity_meta(tags)
                except Exception:
                    pass

                # 2. right_side_confirm（右侧确认三档判定）
                try:
                    df = _ecm.get_cached_daily(code)
                    if df is not None and len(df) > 0:
                        _rsc_result = _check_right_side_confirm(
                            tags.get('opportunity_type', ''), tags, df)
                        if _rsc_result:
                            tags.update(_rsc_result)
                except Exception:
                    pass

                # 3. PotentialEngine signal_strength（潜力评分）
                if pe:
                    try:
                        mf_strength = None
                        try:
                            from app.opportunity_atlas.potential_engine import compute_fund_strength
                            mf_strength = compute_fund_strength(dm.cache, code)
                        except Exception:
                            pass
                        pot = pe.compute_potential(tags, mf_strength)
                        if pot:
                            tags.update(pot)
                    except Exception:
                        pass

                # 4. 写入模块级缓存供 treemap_snapshot 读取
                _jud_meta_cache[code] = {
                    'opportunity_type': tags.get('opportunity_type'),
                    'opportunity_label': tags.get('opportunity_label'),
                    'opportunity_profile': tags.get('opportunity_profile'),
                    'signal_strength': tags.get('signal_strength'),
                    'potential_breakdown': tags.get('potential_breakdown'),
                    'right_side_confirm': tags.get('right_side_confirm'),
                    'confirm_evidence': tags.get('confirm_evidence'),
                    'evidence_count': tags.get('evidence_count'),
                    'phase_confidence': tags.get('phase_confidence'),
                    'entry_signals': tags.get('entry_signals'),
                    'exit_conditions': tags.get('exit_conditions'),
                }
                enriched += 1
            except Exception:
                continue

    logger.info(f"  JUD机会判定完成: {enriched}/{len(codes)} 只 ({time.time()-t0:.1f}s)")


def _build_treemap_snapshot(codes: list[str]):
    """日终预计算完成后，构建 treemap_snapshot 快照表（S1 管道环节）

    修复 2026-08-02：函数内使用 pd.notna 但未导入 pandas → INSERT 全失败

    从 daily_cache / daily_basic_cache / opportunity_tags_cache 提取最新数据，
    平铺写入 treemap_snapshot 表（4800 行 × ~25 列 ≈ 2-3 MB）。
    使用原子表替换避免读写不一致。
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    import pandas as pd  # 修复 2026-08-02：函数内 pd.notna 依赖
    t0 = time.time()
    logger.info(f"构建 treemap_snapshot 快照: {len(codes)} 只...")

    if not codes:
        logger.info("  无活跃股票，跳过快照构建")
        return

    # 1. 元数据（名称 + 行业）
    # SQLAlchemy ORM 需 Flask app context（309号 S1：此前缺 context 导致连续2天 failed）
    from app import create_app
    _flask_app = create_app()
    with _flask_app.app_context():
        from app.data import DataManager
        dm = DataManager()
        meta = dm.get_stock_meta_batch(codes)
    if not meta:
        logger.warning("  元数据为空，跳过快照构建")
        return

    # 2. 最新日线（每只最新一条，用子查询避免全表扫描）
    ph = ','.join('?' for _ in codes)
    # 423号：daily_cache 已分库（356号），改走分库权威副本（主库残留旧数据致滞后）
    daily_df = _shard_query_df('daily_cache', f"""
        SELECT ts_code, close, pct_chg, trade_date, amount, open, high, low FROM daily_cache
        WHERE (ts_code, trade_date) IN (
            SELECT ts_code, MAX(trade_date) FROM daily_cache
            WHERE ts_code IN ({ph}) GROUP BY ts_code
        )
    """, codes)

    # 3. 最新基本面（423号：daily_basic_cache 分库权威副本）
    basic_df = _shard_query_df('daily_basic_cache', f"""
        SELECT ts_code, total_mv, pe, pb, turnover_rate, circ_mv FROM daily_basic_cache
        WHERE (ts_code, trade_date) IN (
            SELECT ts_code, MAX(trade_date) FROM daily_basic_cache
            WHERE ts_code IN ({ph}) GROUP BY ts_code
        )
    """, codes)

    # 4. L2 标签（平铺：每只一行，每标签一列）
    # 修复 2026-08-04：原 MAX(CASE...) 取历史累积行的最大/字典序最大（如 fina_health 取到旧
    # suspicious、sentiment_phase 取到旧 recovery），改为先取每 (ts_code, tag_name) 最新一行再平铺
    # 423号：opportunity_tags_cache 分库权威副本在 compute_cache.db（主库残留旧数据）
    tags_df = _shard_query_df('opportunity_tags_cache', f"""
        SELECT ts_code,
               MAX(CASE WHEN tag_name='signal_strength'     THEN CAST(tag_value AS REAL) END) as signal_strength,
               MAX(CASE WHEN tag_name='valuation_level'     THEN tag_value END) as valuation_level,
               MAX(CASE WHEN tag_name='valuation_deviation' THEN CAST(tag_value AS REAL) END) as valuation_deviation,
               MAX(CASE WHEN tag_name='main_force_phase'    THEN tag_value END) as main_force_phase,
               MAX(CASE WHEN tag_name='phase_confidence'    THEN CAST(tag_value AS REAL) END) as phase_confidence,
               MAX(CASE WHEN tag_name='sentiment_phase'     THEN tag_value END) as sentiment_phase,
               MAX(CASE WHEN tag_name='sector_heat'         THEN tag_value END) as sector_heat,
               MAX(CASE WHEN tag_name='fina_health'         THEN tag_value END) as fina_health,
               MAX(CASE WHEN tag_name='opportunity_type'    THEN tag_value END) as opportunity_type,
               MAX(CASE WHEN tag_name='trend_alignment'     THEN tag_value END) as trend_alignment,
               MAX(CASE WHEN tag_name='price_position'      THEN tag_value END) as price_position,
               MAX(CASE WHEN tag_name='fund_flow'           THEN tag_value END) as fund_flow,
               MAX(CASE WHEN tag_name='capital_nature'      THEN tag_value END) as capital_nature,
               MAX(CASE WHEN tag_name='chip_concentration'  THEN tag_value END) as chip_concentration,
               MAX(CASE WHEN tag_name='volatility_level'    THEN tag_value END) as volatility_level,
               MAX(CASE WHEN tag_name='dividend_yield'      THEN CAST(tag_value AS REAL) END) as dividend_yield,
               MAX(CASE WHEN tag_name='composite_rating'    THEN CAST(tag_value AS REAL) END) as composite_rating,
               MAX(CASE WHEN tag_name='opportunity_label'   THEN tag_value END) as opportunity_label,
               MAX(CASE WHEN tag_name='evidence_count'      THEN CAST(tag_value AS INTEGER) END) as evidence_count,
               MAX(CASE WHEN tag_name='right_side_confirm'  THEN tag_value END) as right_side_confirm,
               MAX(CASE WHEN tag_name='confirm_evidence'    THEN tag_value END) as confirm_evidence,
               MAX(CASE WHEN tag_name='opportunity_profile' THEN tag_value END) as opportunity_profile,
               MAX(CASE WHEN tag_name='entry_signals'       THEN tag_value END) as entry_signals,
               MAX(CASE WHEN tag_name='exit_conditions'     THEN tag_value END) as exit_conditions,
               MAX(CASE WHEN tag_name='catalyst_event'      THEN tag_value END) as catalyst_event,
               MAX(CASE WHEN tag_name='buy_sell_point'      THEN tag_value END) as buy_sell_point,
               MAX(CASE WHEN tag_name='pattern_signal'      THEN tag_value END) as pattern_signal,
               MAX(CASE WHEN tag_name='ma_alignment'        THEN tag_value END) as ma_alignment,
               MAX(CASE WHEN tag_name='main_force_presence' THEN tag_value END) as main_force_presence,
               MAX(CASE WHEN tag_name='presence_evidence'  THEN tag_value END) as presence_evidence,
               MAX(CASE WHEN tag_name='opportunity_state'  THEN tag_value END) as opportunity_state,
               MAX(CASE WHEN tag_name='state_evidence'     THEN tag_value END) as state_evidence
        FROM (
            SELECT ts_code, tag_name, tag_value,
                   ROW_NUMBER() OVER (PARTITION BY ts_code, tag_name ORDER BY id DESC) rn
            FROM opportunity_tags_cache
            WHERE ts_code IN ({ph})
        )
        WHERE rn = 1
        GROUP BY ts_code
    """, codes)

    # 5. 构建行数据字典
    daily_map = {r['ts_code']: r for _, r in daily_df.iterrows()} if not daily_df.empty else {}
    basic_map = {r['ts_code']: r for _, r in basic_df.iterrows()} if not basic_df.empty else {}
    tags_map = {r['ts_code']: r for _, r in tags_df.iterrows()} if not tags_df.empty else {}

    # 5a. 371号JUD接入：用 _jud_meta_cache 覆盖 opportunity_tags_cache 中的富化字段
    #     （_jud_enrich_with_meta 在 _build_status_snapshot 之后已预计算）
    _meta_overlaid = 0
    for _code, _meta in _jud_meta_cache.items():
        if _code not in tags_map:
            # 无 tags 基础数据时，创建空 dict 供覆盖
            tags_map[_code] = {}
        _t = tags_map[_code]
        for _k, _v in _meta.items():
            if _v is not None:
                _t[_k] = _v
        _meta_overlaid += 1
    if _meta_overlaid:
        logger.info(f"  treemap: 371号JUD预计算覆盖 {_meta_overlaid} 只")

    # 5b. 成品仓 status_snapshot（336号 S2.5：快照字段来源切 L1/L2 输出——
    #     consensus_rate/conflict/opportunity_state/state_evidence 读 status_engine 成品，
    #     消除 tags 轻量投票口径；status_snapshot 由管道 S1 先行构建）
    status_map: dict = {}
    try:
        # 421号R4a补充修复：status_snapshot 在 snapshot_cache.db 分库，
        # 改经 sharding_manager 读（_query_df 读主库会 miss 分库新数据）
        from app.data.sharding_manager import sharding_manager
        _tm_conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('treemap_snapshot'))
        _ss_rows = sharding_manager.execute_query(
            'status_snapshot',
            "SELECT ts_code, consensus_rate, conflict_evidence, opportunity_state, state_evidence"
            " FROM status_snapshot")
        if _ss_rows:
            status_map = {r[0]: {'ts_code': r[0], 'consensus_rate': r[1],
                                  'conflict_evidence': r[2], 'opportunity_state': r[3],
                                  'state_evidence': r[4]} for r in _ss_rows}
    except Exception as e:
        logger.warning(f"status_snapshot 读取失败（快照字段回退 tags 口径）: {e}")

    # 6. 原子表替换写入
    NEW_TABLE = 'treemap_snapshot_new'
    # 建新表（结构与目标表一致）
    _tm_conn.execute(f"DROP TABLE IF EXISTS {NEW_TABLE}")
    _tm_conn.execute(f"""
        CREATE TABLE {NEW_TABLE} (
            ts_code TEXT PRIMARY KEY, name TEXT, industry TEXT,
            close REAL, pct_chg REAL, total_mv REAL, trade_date TEXT,
            open REAL, high REAL, low REAL, amplitude REAL,
            pe REAL, pb REAL,
            amount REAL, turnover_rate REAL, circ_mv REAL,
            signal_strength REAL, valuation_level TEXT, valuation_deviation REAL,
            main_force_phase TEXT, phase_confidence REAL,
            sentiment_phase TEXT, sector_heat TEXT, fina_health TEXT,
            opportunity_type TEXT, trend_alignment TEXT, price_position TEXT,
            fund_flow TEXT, capital_nature TEXT, chip_concentration TEXT,
            volatility_level TEXT, dividend_yield REAL, composite_rating REAL,
            opportunity_label TEXT, evidence_count INTEGER,
            right_side_confirm TEXT, confirm_evidence TEXT, opportunity_profile TEXT,
            entry_signals TEXT, exit_conditions TEXT,
            consensus_rate REAL,
            conflict TEXT,
            main_force_presence TEXT,
            presence_evidence TEXT,
            opportunity_state TEXT,
            state_evidence TEXT,
            snapshot_date TEXT DEFAULT (date('now'))
        )
    """)

    written = 0
    for code in codes:
        m = meta.get(code, {})
        d = daily_map.get(code, {})
        b = basic_map.get(code, {})
        t = tags_map.get(code, {})
        try:
            _tm_conn.execute(f"""
                INSERT INTO {NEW_TABLE}
                (ts_code, name, industry, close, pct_chg, total_mv, trade_date,
                 open, high, low, amplitude,
                 pe, pb,
                 amount, turnover_rate, circ_mv,
                 signal_strength, valuation_level, valuation_deviation, main_force_phase,
                 phase_confidence, sentiment_phase, sector_heat, fina_health, opportunity_type,
                 trend_alignment, price_position, fund_flow, capital_nature,
                 chip_concentration, volatility_level, dividend_yield, composite_rating,
                 opportunity_label, evidence_count,
                 right_side_confirm, confirm_evidence, opportunity_profile,
                 entry_signals, exit_conditions, consensus_rate, conflict, main_force_presence,
                 presence_evidence, opportunity_state, state_evidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                code, m.get('name', ''), m.get('industry', ''),
                float(d['close']) if pd.notna(d.get('close')) else None,
                float(d['pct_chg']) if pd.notna(d.get('pct_chg')) else None,
                float(b['total_mv']) if pd.notna(b.get('total_mv')) else None,
                str(d['trade_date']) if pd.notna(d.get('trade_date')) else None,
                _safe_float(d.get('open')), _safe_float(d.get('high')), _safe_float(d.get('low')),
                (_safe_float(d.get('high')) - _safe_float(d.get('low'))) / max(_safe_float(d.get('close')), 1e-9) * 100,
                _safe_float(b.get('pe')), _safe_float(b.get('pb')),
                _safe_float(d.get('amount')), _safe_float(b.get('turnover_rate')),
                _safe_float(b.get('circ_mv')),
                _safe_float(t.get('signal_strength')),
                t.get('valuation_level'), _safe_float(t.get('valuation_deviation')),
                t.get('main_force_phase'), _safe_float(t.get('phase_confidence')),
                t.get('sentiment_phase'), t.get('sector_heat'),
                t.get('fina_health'), t.get('opportunity_type'),
                t.get('trend_alignment'), t.get('price_position'),
                t.get('fund_flow'), t.get('capital_nature'),
                t.get('chip_concentration'), t.get('volatility_level'),
                _safe_float(t.get('dividend_yield')),
                _safe_float(t.get('composite_rating')),
                t.get('opportunity_label'), _safe_int(t.get('evidence_count')),
                t.get('right_side_confirm'), t.get('confirm_evidence'),
                t.get('opportunity_profile'),
                t.get('entry_signals'), t.get('exit_conditions'),
                (status_map.get(code, {}).get('consensus_rate')
                 if code in status_map else _compute_snapshot_consensus_rate(t)),
                status_map.get(code, {}).get('conflict_evidence') if code in status_map else None,
                t.get('main_force_presence'),
                t.get('presence_evidence'),
                status_map.get(code, {}).get('opportunity_state')
                if code in status_map else t.get('opportunity_state'),
                status_map.get(code, {}).get('state_evidence')
                if code in status_map else t.get('state_evidence'),
            ))
            written += 1
        except Exception:
            continue
    _tm_conn.commit()

    # 370号O5：归档逻辑已移至OUT步骤（_out_transmit_seven_dim），此处不再归档

    # 原子切换
    _tm_conn.execute("DROP TABLE IF EXISTS treemap_snapshot")
    _tm_conn.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO treemap_snapshot")
    _tm_conn.commit()

    # 423号：写后校验（覆盖率）——失败记审计告警，不抛
    try:
        _td = str(daily_df['trade_date'].max()) if not daily_df.empty else ''
        if _td:
            from app.data.stg_quality import WriteGateway
            _wg = WriteGateway(_ecm)
            _r = _wg.validate_after_write('treemap_snapshot', _td,
                                          expected_count=len(codes))
            _wg.write_audit('treemap_snapshot', _td, rows=written, result=_r)
            if not _r.passed:
                logger.warning(f"[QA] treemap_snapshot 写后校验未通过: {_r.issues}")
    except Exception as e:
        logger.debug(f"treemap_snapshot 写后校验异常: {e}")

    elapsed = time.time() - t0
    logger.info(f"treemap_snapshot 构建完成: {written}/{len(codes)} 只, 耗时 {elapsed:.1f}s")


def _out_transmit_seven_dim(codes: list[str]):
    """370号方案 OUT步骤：七维透传 + 归档 + 自选股变更检测

    统一归档逻辑（原分散在JUD的_build_status_snapshot/_build_treemap_snapshot中）：
    1. seven_dim_json → status_snapshot.one_liner_detail（七维透传）
    2. status_snapshot → status_snapshot_history（16列完整归档）
    3. treemap_snapshot → treemap_snapshot_history（47列完整归档）
    4. watchlist_status_diff（自选股状态变更检测）
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    t0 = time.time()
    logger.info(f"OUT步骤: 七维透传+归档+变更检测: {len(codes)} 只...")

    # 获取最新交易日
    trade_date = ''
    try:
        _rows = _shard_fetchall('daily_cache', 'SELECT MAX(trade_date) FROM daily_cache')
        trade_date = str(_rows[0][0]) if _rows and _rows[0][0] else ''
    except Exception:
        pass

    # 421号R4a补充修复：status_snapshot/history 写读统一走 snapshot_cache.db 分库
    # （JUD _build_status_snapshot 已切分库；此处 OUT 透传+归档同库，消除读写分叉）
    from app.data.sharding_manager import sharding_manager
    _snap_conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('status_snapshot'))

    # ── 1. 七维透传：seven_dim_json → one_liner_detail ──
    if trade_date:
        try:
            # 421号R4a：status_snapshot 与 strategy_signal_detail 同属 snapshot_cache.db
            # 分库（sharding 路由），整条 UPDATE 在分库连接上执行（此前用主库 _ecm.conn
            # 跨库子查询静默 0 行——375号问题#6 同源）。
            _snap_conn.execute("""
                UPDATE status_snapshot SET one_liner_detail = (
                    SELECT ssd.seven_dim_json
                    FROM strategy_signal_detail ssd
                    WHERE ssd.ts_code = status_snapshot.ts_code
                    AND ssd.trade_date = ?
                    AND ssd.seven_dim_json IS NOT NULL
                )
                WHERE status_snapshot.trade_date = ?
            """, [trade_date, trade_date])
            _snap_conn.commit()
            updated = _snap_conn.execute("SELECT changes()").fetchone()[0]
            logger.info(f"  七维透传: {updated} 只 one_liner_detail 已更新")
        except Exception as e:
            logger.warning(f"七维透传失败: {e}")

    # ── 2. 归档 status_snapshot → status_snapshot_history（16列完整）──
    try:
        _snap_conn.execute("""
            CREATE TABLE IF NOT EXISTS status_snapshot_history (
                ts_code TEXT, snapshot_date TEXT, trade_date TEXT,
                dim_states TEXT, status_bar TEXT, opportunity_state TEXT,
                state_evidence TEXT, conflict_evidence TEXT, consensus_rate REAL,
                direction TEXT, l0 TEXT, lifecycle TEXT, advice_params TEXT,
                summary_text TEXT, one_liner_detail TEXT, dim_engine_results TEXT,
                PRIMARY KEY (ts_code, snapshot_date)
            )
        """)
        _snap_conn.execute("""
            INSERT OR REPLACE INTO status_snapshot_history
                (ts_code, snapshot_date, trade_date, dim_states, status_bar,
                 opportunity_state, state_evidence, conflict_evidence, consensus_rate,
                 direction, l0, lifecycle, advice_params,
                 summary_text, one_liner_detail, dim_engine_results)
            SELECT ts_code, snapshot_date, trade_date, dim_states, status_bar,
                   opportunity_state, state_evidence, conflict_evidence, consensus_rate,
                   direction, l0, lifecycle, advice_params,
                   summary_text, one_liner_detail, dim_engine_results
            FROM status_snapshot
            WHERE dim_engine_results IS NOT NULL
        """)
        _snap_conn.commit()
        logger.info("  归档: status_snapshot → status_snapshot_history")
    except Exception as e:
        logger.warning(f"status_snapshot归档失败: {e}")

    # ── 3. 归档 treemap_snapshot → treemap_snapshot_history ──
    try:
        _snap_conn.execute("""
            CREATE TABLE IF NOT EXISTS treemap_snapshot_history (
                ts_code TEXT, snapshot_date TEXT, name TEXT, industry TEXT,
                close REAL, pct_chg REAL, total_mv REAL, trade_date TEXT,
                open REAL, high REAL, low REAL, amplitude REAL, pe REAL, pb REAL,
                amount REAL, turnover_rate REAL, circ_mv REAL, signal_strength REAL,
                valuation_level TEXT, valuation_deviation REAL, main_force_phase TEXT,
                phase_confidence REAL, sentiment_phase TEXT, sector_heat TEXT,
                fina_health TEXT, opportunity_type TEXT, trend_alignment TEXT,
                price_position TEXT, fund_flow TEXT, capital_nature TEXT,
                chip_concentration TEXT, volatility_level TEXT, dividend_yield REAL,
                composite_rating REAL, opportunity_label TEXT, evidence_count INTEGER,
                right_side_confirm TEXT, confirm_evidence TEXT, opportunity_profile TEXT,
                entry_signals TEXT, exit_conditions TEXT, consensus_rate REAL,
                conflict TEXT, main_force_presence TEXT, presence_evidence TEXT,
                opportunity_state TEXT, state_evidence TEXT,
                PRIMARY KEY (ts_code, snapshot_date)
            )
        """)
        # 显式列名归档：历史表残留旧列 seven_dim_report（370号S6 已废弃），
        # 若用 SELECT * 会因列数不匹配（48 vs 47）失败。此处按显式列对齐，
        # 废弃列留空。
        _tm_cols = (
            "ts_code, name, industry, close, pct_chg, total_mv, trade_date,"
            " open, high, low, amplitude, pe, pb, amount, turnover_rate, circ_mv,"
            " signal_strength, valuation_level, valuation_deviation, main_force_phase,"
            " phase_confidence, sentiment_phase, sector_heat, fina_health, opportunity_type,"
            " trend_alignment, price_position, fund_flow, capital_nature,"
            " chip_concentration, volatility_level, dividend_yield, composite_rating,"
            " opportunity_label, evidence_count, right_side_confirm, confirm_evidence,"
            " opportunity_profile, entry_signals, exit_conditions, consensus_rate,"
            " conflict, main_force_presence, presence_evidence, opportunity_state,"
            " state_evidence, snapshot_date"
        )
        _snap_conn.execute(
            f"INSERT OR REPLACE INTO treemap_snapshot_history ({_tm_cols}) "
            f"SELECT {_tm_cols} FROM treemap_snapshot"
        )
        _snap_conn.commit()
        logger.info("  归档: treemap_snapshot → treemap_snapshot_history")
    except Exception as e:
        logger.warning(f"treemap_snapshot归档失败: {e}")

    # ── 4. 自选股状态变更检测（watchlist_status_diff）──
    try:
        _ecm.conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist_status_diff (
                ts_code TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                prev_date TEXT NOT NULL,
                consensus_rate_change REAL,
                direction_change TEXT,
                opportunity_state_change TEXT,
                risk_level_change TEXT,
                changed_dims TEXT,
                change_summary TEXT,
                advice_changed INTEGER DEFAULT 0,
                PRIMARY KEY (ts_code, snapshot_date)
            )
        """)
        # 获取上一交易日
        prev_date = ''
        try:
            prev_row = _snap_conn.execute(
                "SELECT DISTINCT trade_date FROM status_snapshot "
                "WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 1",
                [trade_date]
            ).fetchone()
            prev_date = prev_row[0] if prev_row else ''
        except Exception:
            pass

        if trade_date and prev_date:
            # 获取自选股列表
            watchlist_codes = set()
            try:
                wl_rows = _ecm.conn.execute(
                    "SELECT DISTINCT ts_code FROM opportunity_library "
                    "WHERE lib_level != 'done'"
                ).fetchall()
                watchlist_codes = {r[0] for r in wl_rows}
            except Exception:
                pass

            if watchlist_codes:
                changes = []
                for code in watchlist_codes:
                    try:
                        cur = _snap_conn.execute(
                            "SELECT consensus_rate, direction, opportunity_state "
                            "FROM status_snapshot WHERE ts_code=? AND trade_date=?",
                            [code, trade_date]
                        ).fetchone()
                        prev = _snap_conn.execute(
                            "SELECT consensus_rate, direction, opportunity_state "
                            "FROM status_snapshot WHERE ts_code=? AND trade_date=?",
                            [code, prev_date]
                        ).fetchone()
                        if cur and prev:
                            cr_change = (cur[0] or 0) - (prev[0] or 0)
                            d_change = cur[1] != prev[1]
                            o_change = cur[2] != prev[2]
                            if abs(cr_change) > 0.05 or d_change or o_change:
                                summary_parts = []
                                if abs(cr_change) > 0.05:
                                    summary_parts.append(f"共识率{cr_change:+.0%}")
                                if d_change:
                                    summary_parts.append(f"方向{prev[1]}→{cur[1]}")
                                if o_change:
                                    summary_parts.append(f"状态{prev[2]}→{cur[2]}")
                                changes.append((
                                    code, trade_date, prev_date,
                                    cr_change, f"{prev[1]}→{cur[1]}" if d_change else None,
                                    f"{prev[2]}→{cur[2]}" if o_change else None,
                                    None, None,
                                    '; '.join(summary_parts),
                                    1 if d_change or o_change else 0,
                                ))
                    except Exception:
                        continue

                if changes:
                    _ecm.conn.executemany(
                        "INSERT OR REPLACE INTO watchlist_status_diff "
                        "(ts_code, snapshot_date, prev_date, consensus_rate_change, "
                        "direction_change, opportunity_state_change, risk_level_change, "
                        "changed_dims, change_summary, advice_changed) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        changes
                    )
                    _ecm.conn.commit()
                    logger.info(f"  变更检测: {len(changes)} 只自选股状态变化")
                else:
                    logger.info("  变更检测: 无自选股状态变化")
    except Exception as e:
        logger.warning(f"自选股变更检测失败: {e}")

    logger.info(f"OUT完成: {time.time() - t0:.1f}s")


def _build_status_snapshot(codes: list[str]):
    """337号 §3/§4：日频现状成品生成（S2 status_engine → status_snapshot 表）

    全市场结构化落库（九维状态/状态条/opportunity_state/conflict/共识），
    与 treemap_snapshot 同管道、原子表替换。
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    t0 = time.time()
    logger.info(f"构建 status_snapshot 现状成品: {len(codes)} 只...")
    if not codes:
        return

    from app import create_app
    _flask_app = create_app()
    with _flask_app.app_context():
        from app.opportunity_atlas.status_engine import StatusEngine
        engine = StatusEngine()
        # 数据交易日（从日线取，独立于 treemap_snapshot——S1 先行构建时序）
        trade_date = ''
        try:
            _rows = _shard_fetchall('daily_cache', 'SELECT MAX(trade_date) FROM daily_cache')
            trade_date = str(_rows[0][0]) if _rows and _rows[0][0] else ''
        except Exception:
            pass

        _NEW = 'status_snapshot_new'
        # 421号R4a补充修复：status_snapshot 写路径切分库（snapshot_cache.db）
        # 此前用 _ecm.conn（主库）写入，而 OUT 透传读分库 → 读写分叉
        # （375号T1只切读方，写方遗留主库；JUD 21:30 重跑证实主库有新批次、
        #   分库仍为旧批次）。与 status_signal_detail/treemap_snapshot 同库对齐。
        from app.data.sharding_manager import sharding_manager
        _snap_conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('status_snapshot'))
        _snap_conn.execute(f"DROP TABLE IF EXISTS {_NEW}")
        _snap_conn.execute(f"""
            CREATE TABLE {_NEW} (
                ts_code TEXT PRIMARY KEY, snapshot_date TEXT, trade_date TEXT,
                dim_states TEXT, status_bar TEXT, opportunity_state TEXT,
                state_evidence TEXT, conflict_evidence TEXT, consensus_rate REAL,
                direction TEXT, l0 TEXT, lifecycle TEXT, advice_params TEXT,
                summary_text TEXT, one_liner_detail TEXT, dim_engine_results TEXT,
                created_at TEXT
            )
        """)
        written = 0
        # 373号修复：generate_summary_text函数不存在，使用内联替代
        def _gen_summary(r):
            try:
                ds = r.get('dim_states')
                dims = _json.loads(ds) if isinstance(ds, str) else (ds or {})
                greens = sum(1 for d in dims.values() if d.get('light') == 'green')
                reds = sum(1 for d in dims.values() if d.get('light') == 'red')
                total = greens + reds
                direction = r.get('direction', 'neutral')
                if direction == 'bullish':
                    return f"整体偏多（{greens}维看多/{reds}维看空）"
                elif direction == 'bearish':
                    return f"整体偏空（{reds}维看空/{greens}维看多）"
                else:
                    return f"多空均衡（{greens}维看多/{reds}维看空）"
            except Exception:
                return ''
        # 370号修正：预取 dim_results_json（SIG预计算），避免JUD重复计算维度引擎
        _dim_cache = {}
        try:
            # 421号R4a：改走 sharding_manager 读 snapshot_cache.db 分库
            from app.data.sharding_manager import sharding_manager
            _placeholders = ','.join(['?' for _ in codes])
            _rows = sharding_manager.execute_query(
                'strategy_signal_detail',
                f"SELECT ts_code, dim_results_json FROM strategy_signal_detail "
                f"WHERE ts_code IN ({_placeholders}) AND dim_results_json IS NOT NULL",
                codes
            )
            for _r in _rows:
                try:
                    _dim_cache[_r[0]] = _json.loads(_r[1]) if _r[1] else None
                except Exception:
                    pass
        except Exception:
            pass
        # 370号S6：build_seven_dim_report已废弃，one_liner_detail由OUT从seven_dim_json透传
        for code in codes:
            try:
                row = engine.evaluate(code, dim_results=_dim_cache.get(code))
                if not row:
                    continue
                # 364a Phase 1：生成summary_text
                summary_text = _gen_summary(row)
                # 370号S6：one_liner_detail不再在此生成，由OUT从strategy_signal_detail.seven_dim_json透传
                _snap_conn.execute(
                    f"INSERT OR REPLACE INTO {_NEW} (ts_code, snapshot_date, trade_date,"
                    f" dim_states, status_bar, opportunity_state, state_evidence,"
                    f" conflict_evidence, consensus_rate, direction, l0, lifecycle, advice_params,"
                    f" summary_text, one_liner_detail, dim_engine_results)"
                    f" VALUES (?, date('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [code, trade_date, row['dim_states'], row['status_bar'],
                     row['opportunity_state'], row['state_evidence'],
                     row['conflict_evidence'], row['consensus_rate'],
                     row['direction'], row['l0'], row['lifecycle'], row['advice_params'],
                     summary_text, None,
                     row.get('dim_engine_results')])
                written += 1
            except Exception as e:
                logger.warning(f"status_snapshot {code} 生成失败: {e}")
        _snap_conn.commit()
        # 370号O5：归档逻辑已移至OUT步骤（_out_transmit_seven_dim），此处不再归档
        logger.info(f"  status_snapshot 构建完成: {written}/{len(codes)} 只")
        _last_step_counts['JUD'] = f"{written}/{len(codes)} stocks"
        # 原子替换
        _snap_conn.execute("DROP TABLE IF EXISTS status_snapshot")
        _snap_conn.execute(f"ALTER TABLE {_NEW} RENAME TO status_snapshot")
        _snap_conn.commit()
        # 423号：写后校验（覆盖率）——失败记审计告警，不抛（避免原子替换后重试丢数据）
        if trade_date:
            try:
                from app.data.stg_quality import WriteGateway
                _wg = WriteGateway(_ecm)
                _r = _wg.validate_after_write('status_snapshot', trade_date,
                                              expected_count=len(codes))
                _wg.write_audit('status_snapshot', trade_date, rows=written, result=_r)
                if not _r.passed:
                    logger.warning(f"[QA] status_snapshot 写后校验未通过: {_r.issues}")
            except Exception as e:
                logger.debug(f"status_snapshot 写后校验异常: {e}")


def _safe_float(v):
    if v is None or v == '' or v == 'None':
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v):
    if v is None or v == '' or v == 'None':
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


# ══════════════════════════════════════════════════════════
# 管道驱动（305号§9，取代定时窗口）
# ══════════════════════════════════════════════════════════

def _is_trading_day(d: datetime) -> bool:
    """432号 R3/R4：是否为交易日（跳过周末与法定节假日）"""
    try:
        from app.utils.trading_hours import is_holiday
        return not is_holiday(d)
    except ImportError:
        return d.weekday() < 5


def _lag_trading_days(latest_date, today) -> int:
    """432号 R3：latest 之后到今天之间的交易日缺口数（周末/节假日不计）

    原自然日口径把周末计入滞后（周五数据周一开机恒判"滞后3天"→ HIGH 补采）。
    """
    if hasattr(latest_date, 'date'):
        latest_date = latest_date.date()
    if hasattr(today, 'date'):
        today = today.date()
    lag = 0
    d = latest_date + timedelta(days=1)
    while d <= today:
        if _is_trading_day(d):
            lag += 1
        d += timedelta(days=1)
    return lag


def _recent_trade_date(offset: int = 0) -> str:
    """432号 R2：返回最近第 offset+1 个交易日的 YYYYMMDD（跳过周末/节假日）

    用于复权因子批量补采的"最近交易日"（原实现用昨天，周末/节假日必空）。
    """
    d = datetime.now()
    n = offset
    for _ in range(45):  # 最多回溯 45 个自然日（覆盖国庆/春节长假）
        if _is_trading_day(d):
            if n == 0:
                return d.strftime('%Y%m%d')
            n -= 1
        d -= timedelta(days=1)
    return None


def _is_today_data_ready() -> bool:
    """432号 R4：今日数据是否已可检查/补采（交易日且 Tushare 当日数据已发布）

    Tushare 日线系列（daily/daily_basic/moneyflow/stk_limit/top_list 等）一般在
    收盘后 17-18 点才发布，盘前/盘中检查当日数据必然空返回。
    """
    return _is_market_day() and datetime.now().hour >= 18


def _get_adj_latest_date():
    """432号 R1：分年表最新复权因子日期（356号拆分后写入只落分年表，
    主表 adj_factor_cache 自拆分起停更——读主表 MAX(trade_date) 恒滞后）"""
    for _yr in range(datetime.now().year, 2000, -1):
        _tbl = f'adj_factor_cache_{_yr}'
        try:
            from app.data.sharding_manager import sharding_manager as _sm
            if _sm.table_exists(_tbl):
                _cand = _query_table(_tbl, f"SELECT MAX(trade_date) FROM {_tbl}")
                if _cand:
                    return _cand
        except Exception:
            continue
    return None


def _is_market_day() -> bool:
    """判断是否为交易日（考虑法定节假日）

    使用 trading_hours.py 的 is_holiday() 函数判断，
    替代原有的仅判断工作日逻辑（weekday < 5）。
    """
    try:
        from app.utils.trading_hours import is_holiday
        return not is_holiday(datetime.now())
    except ImportError:
        # 降级：如果 trading_hours 模块不可用，仅判断工作日
        return datetime.now().weekday() < 5


def _is_pipeline_complete(pipeline_date: str) -> bool:
    """检查当日管道是否已全部完成"""
    try:
        row = _ecm.conn.execute(
            "SELECT COUNT(*) FROM pipeline_status "
            "WHERE pipeline_date=? AND step_id IN ('COL-1','COL-2','COL-3','COL-4','COL-5','COL-6','COL-7',"
            "'RAW-1','RAW-2','RAW-3','RAW-2B','SIG','JUD','OUT','QA-CHECK') AND status='done'",
            [pipeline_date]
        ).fetchone()
        return row and row[0] >= 15  # 15 个环节全 done（B3 RAW-2B；423号 QA-CHECK）
    except Exception:
        return False


def _all_steps_done(status: dict, step_ids: list[str]) -> bool:
    return all(status.get(s, {}).get('status') == 'done' for s in step_ids)


def _is_precompute_in_progress() -> bool:
    """SIG/RAW-2/OUT 重算是否进行中（写锁死锁根治，2026-08-16）

    重算期间（pending/running 未完成）跳过完整性检查等批量写操作，
    避免与 compute_batch 4 worker 的写锁竞争。
    基于最新数据日期（与 _drive_pipeline 同口径，327阶段2数据驱动）。
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    try:
        data_date = _get_latest_data_date()
        if not data_date:
            return False
        data_date_compact = data_date.replace('-', '')
        row = _ecm.conn.execute(
            "SELECT COUNT(*) FROM pipeline_status "
            "WHERE pipeline_date=? AND step_id IN ('SIG','RAW-2','OUT') AND status!='done'",
            [data_date_compact]
        ).fetchone()
        return bool(row and row[0] > 0)
    except Exception:
        return False


def _has_failed(status: dict, step_ids: list[str]) -> bool:
    return any(status.get(s, {}).get('status') == 'failed' for s in step_ids)


def _consume_sync_requests_batch():
    """消费 sync_requests 积压队列（327阶段5：主循环与启动时复用）

    非24h开机时，API 调用层可能堆积 full_*/per_stock 请求——
    daemon 启动后立即消费，不等主循环首个 tick。
    """
    pending = _ecm.consume_pending_requests()
    # 423号 B2：sync_requests 积压深度上报 monitor（健康监控）
    try:
        from app.data.monitor import monitor
        monitor.record_metric('sync_requests_pending', len(pending))
    except Exception:
        pass
    processed = 0
    MAX_PER_TICK = 50  # 每tick最多处理50条，避免阻塞管道
    # 429号修复：finance_report/stk_holder 请求按 ts_code 单只补采（原实现每条都触发
    # 全量 500 只扫描，1-2 分钟/条 → 积压风暴阻塞主循环）。先按 ts_code 去重合并，
    # 每只只补采一次，再批量标记所有对应请求 done，避免重复扫描与重复 API 调用。
    # 注意：去重后仍可能达数千只（finance 4957 + stk_holder 3893），若一次性全补采
    # 仍会阻塞主循环数小时。故每 tick 只补采 MAX_PER_TICK 只（跨两类合计），
    # 其余请求保持 pending 留待下轮，避免重蹈积压风暴。
    _finance_codes = set()
    _stk_holder_codes = set()
    for req in pending:
        if req['task_type'] == 'finance_report' and req.get('ts_code'):
            _finance_codes.add(req['ts_code'])
        elif req['task_type'] == 'stk_holder' and req.get('ts_code'):
            _stk_holder_codes.add(req['ts_code'])
    # 本轮实际补采的代码集合（受 MAX_PER_TICK 上限约束），仅这些请求标记 done
    # 单只补采复用模块级辅助（441号D：429号单只路径统一收口）
    _backfilled = set()
    # 先补采去重后的 finance_report/stk_holder 单只集合（每只一次，跨两类合计 ≤ MAX_PER_TICK）。
    # 预算对半分配，避免 finance 独占预算导致 stk_holder 永不补采。
    _half = MAX_PER_TICK // 2
    _fin_done = 0
    for code in _finance_codes:
        if _fin_done >= _half:
            break
        try:
            _sync_single_finance(code)
            _backfilled.add(code)
        except Exception as e:
            logger.warning(f"  finance_report 单只补采失败 {code}: {e}")
        _fin_done += 1
    _stk_done = 0
    for code in _stk_holder_codes:
        if _stk_done >= _half:
            break
        try:
            _sync_single_stk_holder(code)
            _backfilled.add(code)
        except Exception as e:
            logger.warning(f"  stk_holder 单只补采失败 {code}: {e}")
        _stk_done += 1
    processed = _fin_done + _stk_done
    for req in pending:
        # finance_report/stk_holder：仅当该代码本轮已补采才标记 done（标记为廉价操作，
        # 不受 MAX_PER_TICK 限制）；未补采的保持 pending 留待下轮。
        if req['task_type'] in ('finance_report', 'stk_holder'):
            if req.get('ts_code') in _backfilled:
                _ecm.mark_request_done(req['id'])
                logger.info(f"  sync_request {req['id']} 完成（{req['task_type']} {req.get('ts_code')}）")
            continue
        # 其余任务类型受 MAX_PER_TICK 上限约束
        if processed >= MAX_PER_TICK:
            logger.info(f"  sync_requests 本轮处理 {processed} 条，剩余下轮继续")
            break
        # 425号 C-3：HIGH 补采窗口下，前端展示类请求让路（仅核心依赖类消费，留待下轮）；
        # NORMAL 模式零影响（保持 429 限流行为）。核心类目标 financial/history 库，天然分库隔离。
        if _get_collect_priority() == 'HIGH' and req['task_type'] not in _SYNC_CORE_TYPES:
            continue
        logger.info(f"消费 sync_requests: id={req['id']} type={req['task_type']} ts_code={req.get('ts_code')}")
        try:
            # 跳过已过时的 factor_precompute 请求（P3 管道会统一处理）
            if req['task_type'] == 'factor_precompute':
                _ecm.mark_request_done(req['id'])
                continue
            elif req['task_type'] == 'full_daily':
                _batch_daily(datetime.now().strftime('%Y%m%d'))
                _batch_daily_basic(datetime.now().strftime('%Y%m%d'))
            elif req['task_type'] == 'full_moneyflow':
                _batch_moneyflow(datetime.now().strftime('%Y%m%d'))
            elif req['task_type'] == 'full_basic':
                _batch_daily_basic(datetime.now().strftime('%Y%m%d'))
            elif req['task_type'] == 'full_stock_list':
                _batch_stock_list()
            elif req['task_type'] == 'per_stock':
                _batch_daily(datetime.now().strftime('%Y%m%d'))
            elif req['task_type'] == 'adj_factor':
                _batch_adj_factor()
            elif req['task_type'] == 'top10_holders':
                _batch_top10_holders()
            elif req['task_type'] == 'margin':
                _batch_margin(datetime.now().strftime('%Y%m%d'))
            elif req['task_type'] == 'concept':
                _batch_concept()
            elif req['task_type'] == 'precompute_strategy':
                _precompute_single(req.get('ts_code', ''))
            _ecm.mark_request_done(req['id'])
            logger.info(f"  sync_request {req['id']} 完成")
        except Exception as e:
            _ecm.mark_request_failed(req['id'])
            logger.warning(f"  sync_request {req['id']} 失败: {e}")
        processed += 1


def _recover_stale_running(timeout_hours: float = 4.0) -> int:
    """清理超时 running 残留，防止管道永久阻塞（327阶段1）

    daemon 重启/崩溃后，旧 running 记录无法被 mark_step_running 重置
    （仅接受 pending/failed→running），导致后续环节永不触发、快照陈旧。
    将超过 timeout_hours 未完成的 running 统一重置为 pending，让管道自愈。

    Returns: 重置的环节数
    """
    try:
        rc = _ecm.conn.execute(
            "UPDATE pipeline_status SET status='pending', detail='stale running 重置' "
            "WHERE status='running' AND started_at < datetime('now','localtime', ?)",
            [f'-{int(timeout_hours)} hours']
        ).rowcount
        if rc > 0:
            _ecm.conn.commit()
            logger.info(f"  [管道自愈] 清理 {rc} 个超时 running 环节（>{timeout_hours}h）")
        return rc
    except Exception as e:
        logger.warning(f"  [管道自愈] 清理超时 running 失败: {e}")
        return 0


def _get_latest_data_date() -> str:
    """获取 daily_cache 最新完整交易日（YYYY-MM-DD），无数据返回 None（327阶段2）

    数据驱动核心：管道基于"最新数据日期"而非"当前日期"推进——
    非24h开机/错过15:30/隔日启动时，用已有最新数据自动补算，而非等待"今天"。

    356号方案修复：daily_cache 已迁移到 market_cache.db，必须通过 _query_table 路由读取
    （之前直接从 _ecm.conn 读 stock_cache.db 导致拿到旧日期 2026-08-21）。
    """
    try:
        # 优先从分库读取（daily_cache 已路由到 market_cache.db）
        count = _query_table('daily_cache',
            "SELECT COUNT(*) FROM daily_cache")
        if count and count > 0:
            row = _query_table('daily_cache',
                "SELECT trade_date FROM daily_cache "
                "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1")
            if row:
                return str(row)
    except Exception:
        pass
    # 回退：从分库读取（兼容 _query_table 异常场景）
    try:
        row = _shard_fetchall(
            'daily_cache', "SELECT trade_date FROM daily_cache "
            "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1")
        if row:
            return str(row[0][0])
    except Exception:
        pass
    return None


def _audit_data_freshness() -> str:
    """数据年龄审计（327阶段2）：检查数据最新日期 vs 当前交易日，返回状态

    Returns:
        'fresh' 数据为当前交易日
        'stale' 数据滞后（错过日终/隔日开机）
        'empty' 无数据
    """
    latest = _get_latest_data_date()
    if not latest:
        logger.info("  [数据审计] daily_cache 无数据")
        return 'empty'
    today = datetime.now().strftime('%Y-%m-%d')
    if latest == today:
        logger.info(f"  [数据审计] 数据最新 {latest}，为当前交易日 ✅")
        return 'fresh'
    logger.info(f"  [数据审计] 数据最新 {latest}，滞后于今日 {today}——将基于 {latest} 补算")
    return 'stale'


def _drive_pipeline():
    """管道驱动：检查当前状态，推进到下一个可执行的环节

    每 30s tick 由主循环调用一次。每次只推进一个环节。
    327阶段2：数据驱动——基于 daily_cache 最新交易日（非当前日期）推进，
    实现任意时间开机（含错过15:30/隔日）自动补算。

    355号方案规则11：分时段采集策略
    - 交易时段(trading)：执行盘中实时采集
    - 准备时段(preparing)：执行数据准备和系统检查
    - 结算时段(settlement)：执行日终数据采集
    - 维护时段(maintenance)：执行数据维护和备份
    """
    # 327阶段1：先清理超时 running 残留（防止重启后永久卡死）
    _recover_stale_running()

    # 355号方案规则11：分时段采集策略
    try:
        from app.utils.trading_hours import get_session_for_collection
        collection_session = get_session_for_collection()
        logger.debug(f"当前采集时段: {collection_session}")
    except ImportError:
        collection_session = 'maintenance'

    # 327阶段2：确定有效数据日期（最新完整交易日）
    data_date = _get_latest_data_date()
    if not data_date:
        return  # 无数据，等采集
    data_date_compact = data_date.replace('-', '')

    # Guard: 非交易日跳过（周末/节假日，但若数据日期是最近交易日仍可补算）
    if not _is_market_day() and _is_pipeline_complete(data_date_compact):
        return

    # Guard: 该数据日期的管道已完成
    if _is_pipeline_complete(data_date_compact):
        return

    # 数据量门槛（该数据日期行数充足才推进，防止半载数据触发）
    # 356号：从分库读取（daily_cache 已迁移到 market_cache.db）
    has_data = _query_table('daily_cache',
        "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [data_date]) >= 4000
    if not has_data:
        logger.debug(f"管道数据未就绪: {data_date} 行数不足4000，等待下一tick")
        return  # 数据未完整到达，下一 tick 再检查

    today_fmt = data_date
    today = data_date_compact

    # 确保当日管道环节已初始化
    _ecm.ensure_pipeline_steps(today)
    status = _ecm.load_pipeline_status(today)

    # ── 采集阶段 C1→C6 ──
    # 327阶段2修正：数据驱动下，若 COL-1~COL-6 未全部 done 且数据日期已完整，
    # 直接标记 done 跳过（数据已存在，避免用 data_date 重采旧日期）。
    # 注意：COL-6 概念板块无日期需独立采集；若采集环节已 done 则正常 continue。
    # 数据缺失场景由完整性检查（run_integrity_check）独立补采，不在此阻塞。
    COLLECT = ['COL-1', 'COL-2', 'COL-3', 'COL-4', 'COL-5', 'COL-6']
    for sid, func, arg in [
        ('COL-1', _batch_daily, today_fmt),
        ('COL-2', _batch_daily_basic, today_fmt),
        ('COL-3', _batch_moneyflow, today_fmt),
        ('COL-4', _batch_stk_limit, today_fmt),
        ('COL-5', _batch_lhb, today_fmt),
        ('COL-6', _batch_concept, None),
    ]:
        if status.get(sid, {}).get('status') in ('done', 'running'):
            continue
        # 数据日期已完整 → 采集环节直接标记 done（数据已存在，无需重采）
        if sid != 'COL-6':  # COL-6 概念板块需独立采集（无日期）
            _ecm.conn.execute(
                "UPDATE pipeline_status SET status='done', "
                "completed_at=datetime('now','localtime'), "
                "detail='数据已完整，采集跳过' WHERE pipeline_date=? AND step_id=?",
                [today, sid]
            )
            _ecm.conn.commit()
            continue
        _run_pipeline_step(today, sid, func, arg)
        return  # 每 tick 只推进一个环节

    # COL-1~COL-6 有 failed？重试
    if _has_failed(status, COLLECT):
        for sid in COLLECT:
            if status.get(sid, {}).get('status') == 'failed':
                rc = status[sid].get('retry_count', 0)
                if rc < 3:
                    _ecm.conn.execute(
                        "UPDATE pipeline_status SET status='pending', retry_count=? "
                        "WHERE pipeline_date=? AND step_id=?",
                        [rc + 1, today, sid]
                    )
                    _ecm.conn.commit()
                return  # 每 tick 重试一个

    # 进入 RAW 阶段：需要 COL-1~COL-6 全部 done
    if not _all_steps_done(status, COLLECT):
        # 426号 P0-4-⑤：RAW 触发条件日志——记录为何 RAW 未启动（COL 待完成清单）
        _raw_wait = [s for s in COLLECT if status.get(s, {}).get('status') != 'done']
        logger.debug(f"[管道] RAW 等待采集完成: {_raw_wait}（下一 tick 再检查）")
        return

    codes = _get_active_codes(today_fmt)
    if not codes:
        # 426号 P0-4-⑤：无活跃代码时说明 RAW 暂停原因
        logger.debug(f"[管道] {today} 无活跃股票代码，RAW 步骤暂停")
        return

    # 373号Batch2：COL-7 财务全量同步（非阻塞：失败时跳过，不阻塞RAW）
    if status.get('COL-7', {}).get('status') != 'done':
        def _col_financial(_codes):
            global _ecm
            if _ecm is None:
                from app.data.enhanced_cache_manager import get_ecm_instance
                _ecm = get_ecm_instance()
            batch_size = 500
            for i in range(0, len(_codes), batch_size):
                batch = _codes[i:i+batch_size]
                # 424号P0-4：财务函数已收敛 TushareProvider 且接受 codes 参数
                # （原实现把 codes 列表误当 limit_days/trade_date 传入，致财务同步退化）
                try: _batch_fina_indicator(batch)
                except Exception as _e: logger.debug(f"COL-7 财务指标同步失败跳过: {_e}")
                try: _batch_income_recent(batch)
                except Exception as _e: logger.debug(f"COL-7 收入同步失败跳过: {_e}")
                try: _batch_balancesheet(batch)
                except Exception as _e: logger.debug(f"COL-7 资产负债同步失败跳过: {_e}")
                try: _batch_cashflow(batch)
                except Exception as _e: logger.debug(f"COL-7 现金流同步失败跳过: {_e}")
                try: _batch_forecast(batch)
                except Exception as _e: logger.debug(f"COL-7 业绩预告同步失败跳过: {_e}")
            logger.info(f"  财务全量同步完成: {len(_codes)} 只")
        try:
            _run_pipeline_step(today, 'COL-7', _col_financial, codes)
        except Exception as e:
            logger.warning(f"COL-7 财务同步失败（跳过，不阻塞管道）: {e}")
            # 标记为done以便管道继续
            _ecm.conn.execute(
                "UPDATE pipeline_status SET status='done', detail='部分失败已跳过' "
                "WHERE pipeline_date=? AND step_id='COL-7'", [today])
            _ecm.conn.commit()
        return

    # ── 原料数据加工阶段 RAW-1(IND) → RAW-2(FEAT) → RAW-3(FAC) ──
    if not codes:
        return

    # 411号Phase 10：市场级统计预计算（在RAW步骤前执行）
    try:
        _precompute_market_stats()
    except Exception as e:
        logger.warning(f"市场级统计预计算失败: {e}")

    # 373号Batch1：RAW三步真正并行（三步读同一源表写不同表，无数据依赖）
    RAW_STEPS = {'RAW-1': _precompute_indicators, 'RAW-2': _precompute_raw_features, 'RAW-3': _precompute_preset_combos}
    unfinished_raw = [s for s in RAW_STEPS if status.get(s, {}).get('status') != 'done']
    if unfinished_raw:
        # 426号 P0-4-⑤：RAW 触发条件日志——记录待执行/续算步骤及上一状态
        # （pending=首次或重试、running=重启续算、failed=上轮失败重试）
        _raw_state = {s: status.get(s, {}).get('status') for s in unfinished_raw}
        logger.info(f"[管道] RAW 并行提交: {_raw_state}（可被打断但可续：未完成步骤保 pending，"
                    f"重启后从断点续算，写路径 INSERT OR REPLACE 幂等）")
        import concurrent.futures
        # 卡死根治：原用 `with ThreadPoolExecutor` —— 其 __exit__ 隐式 shutdown(wait=True)，
        # 当某 RAW 步骤超过 1800s 仍运行，fut.result(timeout=1800) 抛超时后 with 退出
        # 会再次阻塞主循环直到该线程结束，超时保护形同虚设。改为显式 shutdown(wait=False)，
        # 超时的后台线程置 daemon 随进程结束，主循环不被拖住。
        _raw_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        # 428 P1-2：跟踪每步结果——仅成功步骤标 done；超时/失败步骤保持非 done，
        # 交由下 tick 426 续算机制重跑（不静默标记不完整数据为完成）。
        _raw_done = {}
        try:
            futures = {s: _raw_pool.submit(RAW_STEPS[s], codes) for s in unfinished_raw}
            for s, fut in futures.items():
                try:
                    fut.result(timeout=1800)
                    _raw_done[s] = True
                except concurrent.futures.TimeoutError:
                    logger.warning(f"{s} 并行执行超过1800s未完成，后台线程继续但不再阻塞主循环；"
                                   f"步骤保持未完成，下 tick 续算（428 P1-2）")
                    _raw_done[s] = False
                except Exception as e:
                    logger.warning(f"{s} 并行执行失败: {e}；步骤保持未完成，下 tick 续算（428 P1-2）")
                    _raw_done[s] = False
        finally:
            # 不等待超时线程；后台 daemon 线程随进程结束，主流程立即继续
            try:
                _raw_pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        # 仅对成功步骤记录完成；超时/失败步骤不标 done，保持待续算
        for s, ok in _raw_done.items():
            if ok:
                _ecm.mark_step_done(today, s, f"OK parallel ({s})")
                logger.info(f"  [管道] {s} → done (parallel)")
            else:
                logger.warning(f"  [管道] {s} 未完成，保留待办，下 tick 续算（428 P1-2）")
        _last_step_counts['RAW'] = f"{len(_raw_done)} steps parallel"
        return

    if not _all_steps_done(status, list(RAW_STEPS.keys())):
        return

    # ── 板块热度持久化 RAW-2B（B3 根治：独立于 RAW-2 触发，避免写锁竞争）──
    if status.get('RAW-2B', {}).get('status') != 'done':
        _run_pipeline_step(today, 'RAW-2B', _precompute_sector_heat, codes)
        return

    # ── 策略分析阶段 SIG ──
    if status.get('SIG', {}).get('status') != 'done':
        def _sig_build(_codes):
            _precompute_strategy_signals(_codes)
        _run_pipeline_step(today, 'SIG', _sig_build, codes)
        return

    if _has_failed(status, ['SIG']):
        for sid in ['SIG']:
            if status.get(sid, {}).get('status') == 'failed':
                rc = status[sid].get('retry_count', 0)
                if rc < 3:
                    _ecm.conn.execute(
                        "UPDATE pipeline_status SET status='pending', retry_count=? "
                        "WHERE pipeline_date=? AND step_id=?",
                        [rc + 1, today, sid]
                    )
                    _ecm.conn.commit()
                return

    if not _all_steps_done(status, ['SIG']):
        return

    # ── 判定及操作建议阶段 JUD（370号方案S4）──
    if status.get('JUD', {}).get('status') != 'done':
        def _jud_build(_codes):
            _build_status_snapshot(_codes)
            # 371号JUD接入：PotentialEngine + opportunity_meta
            _jud_enrich_with_meta(_codes)
            _build_treemap_snapshot(_codes)
        _run_pipeline_step(today, 'JUD', _jud_build, codes)
        return

    if _has_failed(status, ['JUD']):
        for sid in ['JUD']:
            if status.get(sid, {}).get('status') == 'failed':
                rc = status[sid].get('retry_count', 0)
                if rc < 3:
                    _ecm.conn.execute(
                        "UPDATE pipeline_status SET status='pending', retry_count=? "
                        "WHERE pipeline_date=? AND step_id=?",
                        [rc + 1, today, sid]
                    )
                    _ecm.conn.commit()
                return

    if not _all_steps_done(status, ['JUD']):
        return

    # ── 成品仓阶段 OUT（370号方案S6：简化，仅做七维透传+归档）──
    if status.get('OUT', {}).get('status') != 'done':
        def _out_build(_codes):
            _out_transmit_seven_dim(_codes)
        _run_pipeline_step(today, 'OUT', _out_build, codes)
        return

    # 371号P0#2：OUT成品表完整性验证
    if status.get('OUT', {}).get('status') == 'done':
        _verify_out_completeness(today)

    # ── 423号：仓储质量校验 QA-CHECK（OUT 完成后、管道完成前）──
    _qa_row = status.get('QA-CHECK', {})
    _qa_st = _qa_row.get('status')
    if _qa_st in ('failed', 'pending'):
        # 等待补算完成：被 QA 调度的步骤（RAW/SIG/JUD/OUT）尚在 pending/running 时
        # 保持 QA-CHECK pending，不递增 retry（补算 SIG/JUD 需数十分钟，立即重试无意义）
        _inflight = [s for s in ('RAW-1', 'RAW-2', 'RAW-3', 'RAW-2B', 'SIG', 'JUD', 'OUT')
                     if status.get(s, {}).get('status') in ('pending', 'running')]
        if _inflight:
            if _qa_st != 'pending':
                _ecm.conn.execute(
                    "UPDATE pipeline_status SET status='pending', "
                    "detail='等待补算: '||? WHERE pipeline_date=? AND step_id='QA-CHECK'",
                    [','.join(_inflight), today])
                _ecm.conn.commit()
            return
    if _qa_row.get('status') == 'failed':
        _rc = _qa_row.get('retry_count', 0)
        if _rc >= 3:
            # 重试超限：告警升级 + 标记 done（detail 留痕），避免死循环；
            # 数据缺口由次日开盘前 R3 多轮核查与完整性检查兜底
            _alert_qa_failure(today, _qa_row)
            _ecm.conn.execute(
                "UPDATE pipeline_status SET status='done', "
                "detail='QA重试超限已告警: '||COALESCE(detail,'') "
                "WHERE pipeline_date=? AND step_id='QA-CHECK'", [today])
            _ecm.conn.commit()
        else:
            _ecm.conn.execute(
                "UPDATE pipeline_status SET status='pending', retry_count=? "
                "WHERE pipeline_date=? AND step_id='QA-CHECK'",
                [_rc + 1, today])
            _ecm.conn.commit()
        return
    if status.get('QA-CHECK', {}).get('status') != 'done':
        # 传 compact today（_run_qa_check 内部转换为 trade_date 格式做数据校验）
        _run_pipeline_step(today, 'QA-CHECK', _run_qa_check, today)
        return

    logger.info(f"  [管道] 今日全链路完成 ✅")


def _verify_out_completeness(pipeline_date: str):
    """371号P0#2：验证OUT成品表数据完整性"""
    try:
        # 421号R4a补充修复：treemap/status_snapshot 已切 snapshot_cache.db 分库，
        # 完整性验证改走分库连接（主库不再写入成品表）
        from app.data.sharding_manager import sharding_manager
        _v_conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('status_snapshot'))
        # treemap_snapshot行数
        row = _v_conn.execute("SELECT COUNT(*) FROM treemap_snapshot").fetchone()
        treemap_count = row[0] if row else 0

        # status_snapshot行数和one_liner填充率
        row = _v_conn.execute("SELECT COUNT(*), SUM(CASE WHEN one_liner_detail IS NOT NULL THEN 1 ELSE 0 END) FROM status_snapshot").fetchone()
        status_count = row[0] if row else 0
        oneliner_count = row[1] if row and row[1] else 0

        # 活跃股票数（423号：daily_cache 分库权威副本，主库残留已清理）
        row = _shard_fetchall('daily_cache',
            "SELECT COUNT(DISTINCT ts_code) FROM daily_cache WHERE trade_date=?",
            [pipeline_date])
        active_count = row[0][0] if row and row[0][0] else 0

        # 记录到pipeline_status
        if active_count > 0:
            treemap_pct = treemap_count / active_count * 100
            oneliner_pct = oneliner_count / status_count * 100 if status_count > 0 else 0
            detail = f"treemap={treemap_count}({treemap_pct:.0f}%) status={status_count} oneliner={oneliner_count}({oneliner_pct:.0f}%)"
            _ecm.conn.execute(
                "INSERT OR REPLACE INTO pipeline_status (pipeline_date, step_id, step_name, status, detail) VALUES (?, 'OUT-CHECK', '成品表完整性', 'done', ?)",
                [pipeline_date, detail]
            )
            _ecm.conn.commit()

            if treemap_pct < 80:
                logger.warning(f"  [管道] OUT完整性警告: treemap覆盖仅{treemap_pct:.0f}%")
            if oneliner_pct < 50:
                logger.warning(f"  [管道] OUT完整性警告: one_liner填充仅{oneliner_pct:.0f}%")
            else:
                logger.info(f"  [管道] OUT完整性: {detail}")
    except Exception as e:
        logger.warning(f"OUT完整性验证失败: {e}")


# ══════════════════════════════════════════════════════════
# 423号：仓储质量校验（QA-CHECK 步骤）
# ══════════════════════════════════════════════════════════

_stg_checker = None
_stg_scheduler = None


def _get_stg_components():
    """延迟初始化 STG 质量组件（避免 import 环）"""
    global _stg_checker, _stg_scheduler
    if _stg_checker is None:
        from app.data.stg_quality import QualityChecker, RecomputeScheduler
        _stg_checker = QualityChecker(_ecm)
        _stg_scheduler = RecomputeScheduler(_ecm)
    return _stg_checker, _stg_scheduler


class QACheckError(Exception):
    """423号：仓储质量校验未通过（QA-CHECK failed → 管道重试）"""


def _run_qa_check(pipeline_date: str):
    """423号 QA-CHECK 步骤主体：单轮校验 + 补算调度，失败抛异常触发重试

    事件驱动（非阻塞）：本函数只执行一轮校验与调度，由主循环下一 tick
    在补算完成后重新触发；重试次数超限由 _drive_pipeline 告警升级。
    pipeline_date 为 compact 'YYYYMMDD'（pipeline_status 用）；校验数据时
    转换为 trade_date 格式（'YYYY-MM-DD'，对齐各数据表日期列）。
    """
    checker, scheduler = _get_stg_components()
    from app.data.stg_quality import run_quality_round
    # compact → trade_date 格式（数据表日期列用 '-' 分隔）
    check_date = (f'{pipeline_date[:4]}-{pipeline_date[4:6]}-{pipeline_date[6:]}'
                  if len(pipeline_date) == 8 else pipeline_date)
    outcome = run_quality_round(check_date, checker, scheduler,
                                status_date=pipeline_date)
    # G7：校验失败率 + 写锁冲突计数上报 monitor
    try:
        from app.data.monitor import monitor
        from app.data.stg_quality import get_write_lock_conflicts
        monitor.record_metric('qa_check_failed', outcome['failed_count'])
        for _tbl, _cnt in get_write_lock_conflicts().items():
            monitor.record_metric(f'write_lock_conflict_{_tbl}', _cnt)
    except Exception:
        pass
    # 423号 B5：写锁冲突基线快照持久化（qa_audit_log 特例表名，供收益对比）
    try:
        from app.data.stg_quality import WriteGateway, get_write_lock_conflicts
        _wg = WriteGateway(_ecm)
        _wg.write_audit('_write_lock_baseline', pipeline_date, rows=0,
                        extra=json.dumps(get_write_lock_conflicts(), ensure_ascii=False))
    except Exception:
        pass
    if not outcome['passed']:
        _failed = [r for r in outcome['results'] if not r['passed']]
        _issues = []
        for r in _failed:
            _issues.extend(r.get('issues', []))
        raise QACheckError(
            f"仓储质量校验未通过: {outcome['failed_count']}项失败, "
            f"已调度补算 {len(outcome['scheduled'])} 项, 问题: {'; '.join(_issues[:5])}")
    logger.info(f"  [QA] 仓储质量校验通过: {len(outcome['results'])} 项全部 passed")


def _alert_qa_failure(pipeline_date: str, row: dict):
    """423号 L2 告警：QA-CHECK 重试超限（>3 次）→ monitor 告警 + AlertNotifier + 日志"""
    _detail = row.get('detail', '')
    logger.error(f"[QA] 仓储质量校验连续失败（{pipeline_date}）: {_detail}")
    try:
        from app.data.monitor import monitor
        monitor.create_alert(
            'ERROR', '仓储质量校验失败',
            f"{pipeline_date} QA-CHECK 重试超限: {_detail}",
            source='qa_check',
        )
    except Exception as e:
        logger.warning(f"QA 告警发送失败: {e}")
    # 423号 B4：接线统一告警通知器（alert_notifier 写 JSONL + logging，预留 webhook/email 扩展）
    try:
        from app.services.alert_notifier import AlertNotifier
        AlertNotifier().send(
            'QA_CHECK_FAILED', 'qa_check', f"{pipeline_date} QA-CHECK 重试超限: {_detail}",
            severity='ALERT', metadata={'pipeline_date': pipeline_date})
    except Exception as e:
        logger.warning(f"QA AlertNotifier 发送失败: {e}")

def _run_history_qa_patrol(limit: int = 3):
    """423号 G8：历史日期 QA 巡检——最近 N 个交易日轻量检测（不自动补算历史）

    检测 strategy_signal_detail/status_snapshot/treemap_snapshot 缺失并记日志；
    历史补算风险大（全市场重跑），仅告警留痕，由完整性检查/人工处置。
    """
    checker, _ = _get_stg_components()
    try:
        rows = _shard_fetchall('daily_cache',
            "SELECT DISTINCT trade_date FROM daily_cache "
            "ORDER BY trade_date DESC LIMIT ?", [limit])
    except Exception:
        return
    for (d,) in rows:
        d = str(d)
        if not d:
            continue
        for table in ['strategy_signal_detail', 'status_snapshot', 'treemap_snapshot']:
            try:
                r = checker.check_table(table, d)
                if not r.passed:
                    logger.warning(f"[QA-巡检] 历史日期 {d} {table} 缺失: {r.issues}")
            except Exception:
                pass

def _run_pipeline_step(pipeline_date: str, step_id: str, func, arg):
    """执行单个管道环节，记录状态（含幂等锁）"""
    if not _ecm.mark_step_running(pipeline_date, step_id):
        return  # 另一个 tick 已抢到锁

    t0 = time.time()
    try:
        if arg is not None:
            func(arg)
        else:
            func()
        # 371号P0#3：记录成功/失败计数
        count_info = _last_step_counts.pop(step_id, None)
        elapsed = time.time() - t0
        if count_info:
            detail = f"OK ({elapsed:.1f}s) {count_info}"
        else:
            detail = f"OK ({elapsed:.1f}s)"
        _ecm.mark_step_done(pipeline_date, step_id, detail)
        logger.info(f"  [管道] {step_id} → done ({detail})")
    except Exception as e:
        detail = f"ERROR: {e} ({time.time() - t0:.1f}s)"
        _ecm.mark_step_failed(pipeline_date, step_id, detail)
        logger.warning(f"  [管道] {step_id} → failed ({detail})")


def _precompute_indicators(codes):
    """包装原有的指标预计算逻辑（P1）"""
    _ensure_ecm()
    _ensure_pd()
    from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
    mgr = PrecomputeIndicatorManager(_ecm)
    ok = 0
    for code in codes:
        try:
            df = _ecm.get_cached_daily(code)
            # 414号R6: 阈值从30提高到60，确保MA60/MACD有效
            if df is not None and len(df) >= 60:
                # 卡死根治：单只指标计算包超时（与 RAW-3 因子单只一致）。
                # 纯本地内存计算，子线程无 Flask context 依赖，可安全包装。
                def _calc_one(_code=code, _df=df):
                    return mgr.precompute_all_indicators(_code, _df)
                r = _run_with_timeout(_calc_one, timeout_sec=60.0, desc=f"RAW-1 指标 {code}")
                if r:
                    ok += 1
        except Exception:
            pass
    logger.info(f"指标预计算完成: {ok}/{len(codes)} 只")
    # 423号 B1：indicator_* 写后校验 + 审计（cache_indicators_wide 直写分库，校验兜底）
    try:
        from app.data.stg_quality import WriteGateway
        _td = _shard_fetchall('daily_cache', 'SELECT MAX(trade_date) FROM daily_cache')
        _td_s = str(_td[0][0]) if _td and _td[0][0] else ''
        if _td_s:
            _wg = WriteGateway(_ecm)
            for _t in ('indicator_ma', 'indicator_macd', 'indicator_other'):
                _r = _wg.validate_after_write(_t, _td_s)
                _wg.write_audit(_t, _td_s, result=_r)
                if not _r.passed:
                    logger.warning(f"[QA] {_t} 写后校验未通过: {_r.issues}")
    except Exception as e:
        logger.debug(f"indicator 写后校验异常: {e}")


def _precompute_strategy_signals(codes):
    """包装原有的策略信号预计算逻辑（P2）"""
    _ensure_ecm()
    # 2026-08-11 修复：P2 前置预热周线缓存——缠论 long 周期依赖周线（_get_weekly_data）。
    # 原实现缓存 miss 时直调 mootdx TCP（292号红线违规 + 连接失败 3.6s sleep/只，
    # 致 P2 耗时 1.6h）；现周线改为日线聚合 + 缓存（缠论 4.5s→0.06s/只），
    # 此处批量预热确保全市场周线就绪（增量：只补缺失股票）。
    try:
        _prewarm_weekly_cache(codes)
    except Exception as e:
        logger.warning(f"周线缓存预热失败（不影响 P2 主流程）: {e}")
    try:
        from app.engine.unified_core import UnifiedStrategyCore
        core = UnifiedStrategyCore()
        results = core.compute_batch(codes, max_workers=4)
        # 2026-08-16 修复（P2 写锁死锁根治）：原实现逐只 cache_signal_detail
        # （共享 conn + _write_lock + busy_timeout=30s），4 worker 高频写与 daemon
        # 主循环写冲突——持锁 worker 阻塞于 SQLite 写锁等待，其余 worker 阻塞于
        # _write_lock，形成锁链死锁（lldb 实证 4 线程 PyThread_acquire_lock_timed
        # + 1 线程 _pysqlite_query_execute）；5571 次单独 commit 放大为卡死数小时
        # 且 strategy_signal_detail 零写入。改为单连接批量 INSERT（executemany +
        # 一次 commit），写路径从 5571 次短事务收敛为 1 次批量事务。
        # 421号R1：批量写改走 sharding_manager 路由 snapshot_cache.db 分库。
        import json as _json
        rows = []
        # 370号修正：预计算dim_results_json（供JUD步骤消费）——单引擎复用
        try:
            from app.opportunity_atlas.status_engine import StatusEngine as _SE
            _se_engine = _SE()
        except Exception:
            _se_engine = None
        for ts_code, result in results.items():
            try:
                rd = result.to_dict()
                # 370号修正：预计算dim_results_json（供JUD步骤消费）——436号B2 提前到
                # seven_dim 之前，因 seven_dim 改由同循环的 dim_results 派生（dim8 整体归集）
                dim_results = None
                _tags = {}
                if _se_engine:
                    try:
                        _tags = _se_engine._load_tags(ts_code)
                        _signals = _se_engine._load_signals(ts_code)
                        if _tags or _signals:
                            _lifecycle = _se_engine._signal_lifecycle(ts_code, _tags, _signals)
                            # 421号补充修复：SIG 预计算路径补传 ts_code——此前遗漏导致
                            # dim1 门禁 ts_code 为空、跳过数据预加载，data_context 全 null、
                            # quality_level=failed（与 JUD 主路径 status_engine.py:88 对齐）
                            dim_results = _se_engine._build_dim_engine_results(_tags, _signals, {}, _lifecycle, ts_code=ts_code)
                    except Exception:
                        dim_results = None
                # 436号S5：七维现状描述由 dim8 整体归集器从 dim_results 组装（替代
                # 废弃的 generate_seven_dim_from_signals 空壳路径）；dim_results 缺失 →
                # seven_dim 写 NULL（前端回退 opportunity_profile，保持降级语义）
                seven_dim = None
                if dim_results:
                    try:
                        from app.opportunity_atlas.status_engine import build_seven_dim_from_dim_results
                        seven_dim = build_seven_dim_from_dim_results(dim_results, tags=_tags, ts_code=ts_code)
                    except Exception:
                        seven_dim = None
                rows.append((ts_code, rd.get('trade_date', datetime.now().strftime('%Y-%m-%d')),
                             _json.dumps(rd, ensure_ascii=False, default=str), 1,
                             _json.dumps(seven_dim, ensure_ascii=False) if seven_dim else None,
                             _json.dumps(dim_results, ensure_ascii=False, default=str) if dim_results else None))
            except Exception:
                continue
        _batch_write_signal_detail(rows)
        count = len(rows)
        logger.info(f"策略信号预计算完成: {count}/{len(codes)} 只")
        _last_step_counts['SIG'] = f"{count}/{len(codes)} stocks"
        if count == 0 and codes:
            logger.info("策略信号全部失败，回退到因子信号写入...")
            _write_factor_signals(codes)
    except SignalWriteError:
        # 421号R3：写失败透传到 _run_pipeline_step → SIG failed → 管道自动重试
        # （不落入因子回退，因子回退仅用于计算全失败场景）
        raise
    except Exception as e:
        logger.warning(f"策略信号预计算整体失败: {e}")
        _write_factor_signals(codes)


class SignalWriteError(Exception):
    """421号R3：SIG 信号批量写失败专用异常

    与计算类失败区分：写失败 → 抛出 → _run_pipeline_step 标记 SIG failed
    → 管道自动重试（≤3 次）；计算失败 → 回退 _write_factor_signals（392号§2.4）。
    """

def _batch_write_signal_detail(rows):
    """批量写 strategy_signal_detail（P2 写锁死锁根治，2026-08-16）

    421号R1：写库目标对齐 357 号分库标准——改走 sharding_manager 路由到
    snapshot_cache.db（分库），不再直连主库 _ecm.db_path（消除与主库采集/
    主循环写者的锁竞争）。execute_batch_insert 带分库级 _write_locks 串行化，
    且分库连接 busy_timeout=30000（sharding_manager.get_connection 内配置）。

    421号R3：失败不再静默降级——抛出 SignalWriteError 由上层标记 SIG failed
    触发管道自动重试（此前静默 warning + SIG done 掩盖数据缺失；注释声称的
    "完整性检查兜底补写"实际不存在）。
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    if not rows:
        return
    try:
        # 423号 G3：写前 SIG 结果自检（signal_json/dim_results_json/seven_dim_json）
        from app.data.stg_quality import QualityChecker, WriteGateway
        _sig_issues = QualityChecker(_ecm).validate_signal_rows(rows)
        if _sig_issues:
            _summary = '; '.join(_sig_issues[:5])
            logger.warning(f"SIG 结果自检未通过（将触发 SIG 重试）: {_summary}")
            raise SignalWriteError(f"SIG 结果自检失败: {_summary}")
        # 423号：统一走 WriteGateway（写前格式校验 → 分库写入 → 写后行数校验 → 审计）
        _trade_date = rows[0][1]
        _wg_result = WriteGateway(_ecm).write_batch(
            'strategy_signal_detail',
            rows,
            _trade_date,
            "INSERT OR REPLACE INTO strategy_signal_detail "
            "(ts_code, trade_date, signal_json, schema_version, cached_at, seven_dim_json, dim_results_json) "
            "VALUES (?, ?, ?, ?, datetime('now','localtime'), ?, ?)",
        )
        if not _wg_result.passed:
            raise SignalWriteError(
                f"strategy_signal_detail 写后校验失败: {'; '.join(_wg_result.issues[:3])}")
    except SignalWriteError:
        raise
    except Exception as e:
        logger.warning(f"批量写 strategy_signal_detail 失败（将触发 SIG 重试）: {e}")
        raise SignalWriteError(f"strategy_signal_detail 批量写失败: {e}")


def _prewarm_weekly_cache(codes):
    """批量预热周线缓存（从 daily_cache 聚合 freq='W'，零数据源直调）

    P2 缠论 long 周期需要周线；日线聚合成本低（~82s/全市场），
    只补缺失股票（已有缓存跳过），增量维护。
    """
    import pandas as _pd
    _ensure_pd()
    # 找出缺周线缓存的股票
    rows = _shard_fetchall(
        'minute_kline_cache', "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE freq='W'")
    cached_set = {r[0] for r in rows}
    missing = [c for c in codes if c not in cached_set]
    if not missing:
        return
    logger.info(f"  周线缓存预热: 缺 {len(missing)} 只，从日线聚合...")
    try:
        # 分批（每批 500 只）拉日线聚合，避免单次查询过大
        for i in range(0, len(missing), 500):
            batch = missing[i:i+500]
            ph = ','.join('?' for _ in batch)
            # 423号：daily_cache 已分库（356号），改走分库权威副本（主库残留旧数据致周线滞后）
            df = _shard_query_df(
                'daily_cache',
                f"SELECT ts_code, trade_date, open, high, low, close, vol, amount "
                f"FROM daily_cache WHERE ts_code IN ({ph}) ORDER BY ts_code, trade_date",
                batch
            )
            if df.empty:
                continue
            df['trade_date'] = _pd.to_datetime(df['trade_date'])
            from app.data import DataManager
            dm = DataManager()
            for ts_code, g in df.groupby('ts_code'):
                if len(g) < 60:
                    continue
                try:
                    wk = g.resample('W-FRI', on='trade_date').agg(
                        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
                        close=('close', 'last'), vol=('vol', 'sum'), amount=('amount', 'sum'),
                    ).dropna().reset_index()
                    if wk.empty:
                        continue
                    wk['ts_code'] = ts_code
                    wk['trade_date'] = wk['trade_date'].dt.strftime('%Y-%m-%d')
                    wk['trade_time'] = wk['trade_date']
                    dm._cache_minute_to_ecm(wk, ts_code, 'W')
                except Exception:
                    continue
        logger.info(f"  周线缓存预热完成（批次 {i//500+1}）")
    except Exception as e:
        logger.warning(f"周线缓存预热失败: {e}")



def _run_financial_sync():
    """后台同步财务数据（低优，全市场约5-10分钟）"""
    _ensure_pd()
    logger.info("财务数据同步开始...")
    today = datetime.now().strftime('%Y%m%d')
    try:
        _batch_fina_indicator(today)
    except Exception as e:
        logger.warning(f"财务指标同步异常: {e}")
    try:
        _batch_income_recent()
    except Exception as e:
        logger.warning(f"利润表同步异常: {e}")
    try:
        _batch_balancesheet()
    except Exception as e:
        logger.warning(f"资产负债表同步异常: {e}")
    try:
        _batch_cashflow()
    except Exception as e:
        logger.warning(f"现金流量表同步异常: {e}")
    try:
        _batch_forecast()
    except Exception as e:
        logger.warning(f"业绩预告同步异常: {e}")
    logger.info("财务数据同步完成")


def _batch_backfill_minute_kline(trade_date: str = None):
    """日终补齐分钟K线数据

    用 Tushare pro_bar 补齐今日有日线但缺分钟数据的股票。
    后台低优，每次最多处理 500 只，避免拖慢主流程。
    """
    _ensure_pd()
    if trade_date is None:
        trade_date = datetime.now().strftime('%Y%m%d')
    # 414号P2.3: 使用传入的trade_date参数而非datetime.now()
    trade_date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

    # Step 1: 获取今日有日线数据的股票列表
    try:
        daily_stocks = _shard_fetchall(
            'daily_cache', "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?", [trade_date_fmt])
        daily_stocks = [r[0] for r in daily_stocks]
    except Exception as e:
        logger.warning(f"[分钟回填] 查询日线股票列表失败: {e}")
        return

    if not daily_stocks:
        logger.info(f"[分钟回填] 今日无日线数据，跳过")
        return

    # Step 2: 查询已有分钟数据的股票
    try:
        minute_stocks = _shard_fetchall(
            'minute_kline_cache', "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE trade_date=?", [trade_date_fmt])
        minute_stocks = set(r[0] for r in minute_stocks)
    except Exception:
        minute_stocks = set()

    # Step 3: 计算缺失股票（2026-08-12 328号P1：多轮补齐，覆盖全市场未开机日）
    # 原单轮限 500 只——未开机日全市场缺分钟（数千只）只能补 500，完整性不足。
    # 改为循环补齐：每轮取缺失前 500 只补采，补完刷新缺失集，最多 MAX_ROUNDS 轮。
    import tushare as ts
    pro = ts.pro_api()
    MAX_ROUNDS = 8   # 每轮 500 只，最多 8 轮 = 4000 只（覆盖全市场）
    total_ok = 0
    for round_idx in range(MAX_ROUNDS):
        # 刷新缺失集（每轮结束后重新查已补齐的）
        try:
            minute_stocks = set(r[0] for r in _shard_fetchall(
                'minute_kline_cache', "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE trade_date=?", [trade_date_fmt]))
        except Exception:
            minute_stocks = set()
        missing = [s for s in daily_stocks if s not in minute_stocks][:500]
        if not missing:
            logger.info(f"[分钟回填] 今日分钟数据已完整 ({len(daily_stocks)} 只, 共{round_idx}轮)")
            break

        logger.info(f"[分钟回填] 第{round_idx+1}轮: 补齐 {len(missing)} 只 (已有 {len(minute_stocks)}/{len(daily_stocks)})")

        # Step 4: 逐只调用 Tushare pro_bar 补齐
        ok = 0
        for i, code in enumerate(missing):
            try:
                raw = ts.pro_bar(ts_code=code, start_date=trade_date, end_date=trade_date, freq='1min', adj='qfq')
                if raw is not None and not raw.empty:
                    # pro_bar 分钟数据返回 trade_time，需提取 trade_date
                    if 'trade_time' in raw.columns:
                        raw['trade_date'] = pd.to_datetime(raw['trade_time']).dt.date
                    elif 'trade_date' in raw.columns:
                        raw['trade_date'] = pd.to_datetime(raw['trade_date']).dt.date
                    # 列名统一: vol → volume
                    if 'vol' in raw.columns and 'volume' not in raw.columns:
                        raw['volume'] = raw['vol']
                        raw = raw.drop(columns=['vol'])
                    _ecm.cache_minute_kline(raw)
                    ok += 1
                if (i + 1) % 100 == 0:
                    logger.info(f"[分钟回填] 进度: {i+1}/{len(missing)}, 成功 {ok}")
            except Exception as e:
                logger.debug(f"[分钟回填] {code} 失败: {e}")
                continue
        total_ok += ok
        logger.info(f"[分钟回填] 第{round_idx+1}轮完成: 成功 {ok}/{len(missing)} 只")

    logger.info(f"[分钟回填] 全部轮次完成: 成功 {total_ok} 只")


def _run_minute_backfill():
    """后台分钟K线回填包装"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    global _ecm
    if _ecm is None:
        _ecm = get_ecm_instance()
    today = datetime.now().strftime('%Y%m%d')
    _batch_backfill_minute_kline(today)


def _run_minute_backfill_v2():
    """自选股分钟数据闲时补采（使用 mootdx 填充历史数据）"""
    try:
        from app.data.minute_backfill import run_backfill_all
        result = run_backfill_all()
        logger.info(f"  分钟数据闲时补采: 5min={result.get('5min', 0)}, "
                    f"1min={result.get('1min', 0)}, 聚合={result.get('aggregate', 0)}")
    except Exception as e:
        logger.warning(f"  分钟数据闲时补采失败: {e}")


def _run_signal_checkpoint():
    """信号验证回算 T+5/T+10/T+20（345号第③层核查激活，2026-08-16）

    daemon 模式回算入口（scheduler_manager 仅 API 进程注册；daemon 在
    日终同步后触发）。回算写 app.db（API 业务库），daemon 只写 stock_cache.db，
    无锁冲突；DataManager 读 stock_cache.db 在日终同步后数据完整。
    """
    try:
        import os as _os
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm_local = get_ecm_instance()
        # 回算依赖 app.db 的 Flask SQLAlchemy 模型——通过 API 进程的 create_app
        # 上下文执行；daemon 不持有 Flask app，直接操作 app.db SQLite。
        import sqlite3 as _sq
        import json as _json
        db_path = _os.path.join(_os.environ.get('DATA_DIR', 'data'), 'app.db')
        if not _os.path.exists(db_path):
            logger.warning("  信号验证回算: app.db 不存在，跳过")
            return
        conn = _sq.connect(db_path, timeout=15)
        cur = conn.cursor()
        # 读取待回算信号（已达 T+N 且未完成对应检查点）
        import datetime as _dt
        today = _dt.date.today()
        rows = cur.execute(
            "SELECT id, ts_code, signal_date, signal_type, confidence, entry_price, "
            "target_price, risk_line, signal_snapshot, verification_status "
            "FROM signal_records WHERE verification_status != 'completed'"
        ).fetchall()
        # 用 daily_cache 回算（只读 stock_cache.db）
        ec = _sq.connect(f"file:{_ecm_local.db_path}?mode=ro", uri=True, timeout=15)
        updated = 0
        for rid, ts_code, sdate, stype, conf, entry, target, risk, snap, status in rows:
            sdate_dt = _dt.date.fromisoformat(str(sdate)) if isinstance(sdate, str) else sdate
            # 回算 T+5/10/20（已达的检查点）
            for off, field in ((5, 't5'), (10, 't10'), (20, 't20')):
                if status in ('completed',) or (off == 5 and status != 'pending') \
                   or (off == 10 and status not in ('pending', 't5_checked')) \
                   or (off == 20 and status not in ('pending', 't5_checked', 't10_checked')):
                    continue
                cutoff = today - _dt.timedelta(days=off)
                if sdate_dt > cutoff:
                    continue  # T+N 未到
                # 取信号日后第 N 个交易日
                rows2 = ec.execute(
                    "SELECT close FROM daily_cache WHERE ts_code=? AND trade_date >= ? "
                    "ORDER BY trade_date LIMIT ?", (ts_code, sdate_dt.strftime('%Y-%m-%d'), off + 1)
                ).fetchall()
                if len(rows2) < off + 1:
                    continue
                sig_price = rows2[0][0]
                chk_price = rows2[off][0]
                if not sig_price:
                    continue
                ret = round((chk_price - sig_price) / sig_price, 4)
                bullish = stype in ('BULLISH', 'WATCH')
                is_win = ret > 0 if bullish else ret < 0
                # 更新检查点
                new_status = 't5_checked' if off == 5 else ('t10_checked' if off == 10 else 'completed')
                cur.execute(
                    f"UPDATE signal_records SET price_{field}=?, return_{field}=?, "
                    f"is_win_{field}d=?, verification_status=? WHERE id=?",
                    (chk_price, ret, is_win, new_status, rid)
                )
                status = new_status
                updated += 1
        conn.commit()
        conn.close()
        ec.close()
        logger.info(f"  信号验证回算完成: 更新 {updated} 条检查点")
    except Exception as e:
        logger.warning(f"  信号验证回算失败: {e}")


# 426号 S3/D1：保留期下限（356号 规则10 时效为最低标准——超期不删、不足告警）。
# pre_feat_cache 不纳入：功能 2026-08-19 才启用，1 年下限必然误报，其覆盖
# 由阶段三回补专项保障（每日 ≥5000 行验证）。
_RETENTION_MIN_DAYS = {
    'daily_cache': 1095,           # 日线 3 年
    'minute_kline_cache': 180,     # 分钟 6 个月（v1.5：原清理调用传 30 天，与 356 规则不符，已校正）
    'factor_cache': 365,           # 预计算 1 年
}
_RETENTION_DATE_COLS = {
    'daily_cache': 'trade_date',
    'minute_kline_cache': 'trade_date',
    'factor_cache': 'trade_date',
}


def _check_data_retention():
    """保留期下限保障检查（426号 S3/D1 改造，替代原删除语义的 _run_data_cleanup）

    356号 规则10 时效为最低标准：各表覆盖不得低于下限（日线 3 年/分钟 6 月/预计算 1 年），
    超过下限的数据一律保留、不删除；覆盖不足（数据缺失）记录告警，交由回补机制处理。
    每月 1 日顺带执行一次 VACUUM（存储维护，不删数据）。
    """
    today = datetime.now().date()
    gaps = []
    for table, min_days in _RETENTION_MIN_DAYS.items():
        col = _RETENTION_DATE_COLS[table]
        cutoff = (today - timedelta(days=min_days)).strftime('%Y-%m-%d')
        try:
            df = _ecm._query_shard(table, f"SELECT MIN({col}) AS min_d FROM {table}")
        except Exception as e:
            logger.warning(f"保留期检查 {table} 失败: {e}")
            continue
        if df is None or df.empty or df.iloc[0]['min_d'] is None:
            logger.warning(f"保留期检查 {table}: 无数据（低于最低保留期 {min_days} 天），需确认是否回补")
            gaps.append(table)
            continue
        min_d = str(df.iloc[0]['min_d'])
        if min_d > cutoff:
            logger.warning(f"保留期检查 {table}: 最早数据 {min_d} 晚于最低保留期截止 {cutoff}（{min_days} 天），覆盖不足，需确认是否回补")
            gaps.append(table)
        else:
            logger.info(f"保留期检查 {table}: 覆盖至 {min_d}，满足最低保留期 {min_days} 天（超期数据保留，未删除）")
    if gaps:
        logger.warning(f"保留期检查完成：{len(gaps)} 张表覆盖不足 {gaps}（规则时效为最低标准，未删除任何数据）")
    else:
        logger.info("保留期检查完成：全部表满足最低保留期（未删除任何数据）")

    # 每月执行一次 VACUUM（原逻辑保留）
    if datetime.now().day == 1:
        try:
            _ecm.vacuum_db()
        except Exception as e:
            logger.warning(f"VACUUM 失败: {e}")


# ══════════════════════════════════════════════════════════
# 主循环
# ══════════════════════════════════════════════════════════

# _is_market_day 在管道驱动模块中已定义（305号§9）


def _is_market_hours() -> bool:
    """是否为交易时段（9:00-15:30）"""
    h = datetime.now().hour
    return 9 <= h <= 15


def _wal_maintenance_all_dbs():
    """424号P0-2：遍历全部分库执行 WAL checkpoint 与大小监控

    原实现只处理总库 stock_cache.db（_ecm.wal_checkpoint + 硬编码
    stock_cache.db-wal 大小检测），compute_cache.db-wal 达 5.26GB 处于
    监控盲区。本函数经 sharding_manager 获取全部分库名，对每库执行
    PASSIVE checkpoint，并返回各分库 WAL 大小供监控告警。

    Returns:
        dict: {db_name: wal_size_mb}，供调用方记录监控指标
    """
    import sqlite3 as _sq
    from app.data.sharding_manager import sharding_manager

    data_dir = os.environ.get('DATA_DIR', 'data')
    duckdb_dir = os.path.join(data_dir, 'duckdb')
    wal_sizes = {}

    # 全部分库名（去重）+ 总库 + market_snapshot.db
    db_names = set(sharding_manager.get_all_db_names())
    db_names.add('stock_cache.db')
    db_names.add('market_snapshot.db')

    for db_name in sorted(db_names):
        db_path = os.path.join(duckdb_dir, db_name)
        if not os.path.exists(db_path):
            continue
        # 1. PASSIVE checkpoint（轻量非阻塞）
        try:
            _con = _sq.connect(db_path, timeout=10)
            try:
                _con.execute('PRAGMA wal_checkpoint(PASSIVE)')
            finally:
                _con.close()
        except Exception as e:
            logger.warning(f"WAL checkpoint 失败 ({db_name}): {e}")
        # 2. WAL 大小
        try:
            wal_path = db_path + '-wal'
            if os.path.exists(wal_path):
                wal_sizes[db_name] = os.path.getsize(wal_path) / 1024 / 1024
        except OSError:
            pass

    return wal_sizes


def _wal_truncate_all_dbs():
    """426号 S4/D2：非交易时段对全部分库执行 TRUNCATE 深收缩（PASSIVE 的补充）

    PASSIVE 无法截断存在读标记的 WAL（compute_cache.db-wal 曾达 5.66 GiB）；
    TRUNCATE 需无活跃读事务，失败自动降级 PASSIVE（与 wal_maintenance.py 同法，
    独立连接 + busy_timeout）。返回各库收缩前后大小供日志核对。
    """
    import sqlite3 as _sq

    from app.data.sharding_manager import sharding_manager

    data_dir = os.environ.get('DATA_DIR', 'data')
    duckdb_dir = os.path.join(data_dir, 'duckdb')
    db_names = set(sharding_manager.get_all_db_names())
    db_names.add('stock_cache.db')
    db_names.add('market_snapshot.db')
    shrunk = []
    for db_name in sorted(db_names):
        db_path = os.path.join(duckdb_dir, db_name)
        wal_path = db_path + '-wal'
        if not os.path.exists(db_path):
            continue
        before = os.path.getsize(wal_path) / 1024 / 1024 if os.path.exists(wal_path) else 0
        try:
            _con = _sq.connect(db_path, timeout=30)
            try:
                _r = _con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if _r and _r[0] != 0:
                    _con.execute('PRAGMA wal_checkpoint(PASSIVE)')  # busy → 降级合并
            finally:
                _con.close()
        except Exception as e:
            logger.warning(f"WAL TRUNCATE 失败 ({db_name}): {e}")
        after = os.path.getsize(wal_path) / 1024 / 1024 if os.path.exists(wal_path) else 0
        if before > 1 or after > 1:
            shrunk.append(f"{db_name}: {before:.1f}→{after:.1f}MB")
    if shrunk:
        logger.info(f"WAL TRUNCATE 维护完成: {' '.join(shrunk)}")
    return shrunk


def _check_daily_sync_backfill():
    """开机兜底：如果当前 >15:35 且今日日终同步未执行，立即触发（Task 2）

    daemon 可能在 15:30-15:35 窗口期不在运行（崩溃/重启），
    用日线数据量判断日终同步是否已被执行。
    """
    now = datetime.now()
    if now.weekday() >= 5:
        logger.info("  [日终兜底] 非交易日，跳过")
        return
    if now.hour < 15 or (now.hour == 15 and now.minute <= 35):
        return  # 还没到窗口，等主循环正常触发

    today_fmt = now.strftime('%Y-%m-%d')
    try:
        cnt = _shard_fetchall(
            'daily_cache', "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [today_fmt])[0][0]
        if cnt >= 5000:
            logger.info(f"  [日终兜底] 今日日终同步已完成（日线{cnt}行），跳过")
            return
        logger.info(f"  [日终兜底] 检测到今日日终同步未执行（日线{cnt}行），触发补采...")
        run_daily_sync()
    except Exception as e:
        logger.warning(f"  [日终兜底] 自检失败: {e}")


def _maybe_monthly_ic_recalc(data_dir: str) -> None:
    """433 批次1：月度 IC 重估轻钩子（earn-only；幂等靠 ic_weights.json last_recalc 月份）

    触发条件：本月未算（last_recalc 月份 != 当前自然月）。每月第一次满足即触发一次
    重算（重算实测 ~3.4s，_run_with_timeout 保护，不阻塞主循环）；daemon 若整月未运行，
    下月启动后因 last_recalc 仍是更早月份而自动补跑。失败不阻塞主循环（try/except 包裹）。
    """
    import json as _json
    from datetime import datetime as _dt
    try:
        state_file = os.path.join(data_dir, 'ic_weights.json')
        report_file = os.path.join(data_dir, 'ic_weights_report.json')
        now_m = _dt.now().strftime('%Y-%m')
        # 幂等：ic_weights.json.last_recalc（ok 落盘）或 ic_weights_report.json.recalc_at
        #（每次重估含 no_signal 都写）任一命中本月 → 跳过。433 批次4：no_signal 不写
        # last_recalc，必须用 report.recalc_at 兜底，否则每 30s tick 重复触发。
        last_m = None
        for f in (state_file, report_file):
            if os.path.exists(f):
                try:
                    with open(f, encoding='utf-8') as fh:
                        _payload = _json.load(fh)
                    last_m = _payload.get('last_recalc') or _payload.get('recalc_at')
                except Exception:
                    last_m = None
                if last_m:
                    break
        if last_m and str(last_m).startswith(now_m):
            return  # 本月已算

        # 数据齐备：daily_cache 近 30 交易日（recompute 内部二次校验，不满足返回 insufficient_data）
        from app.opportunity_atlas import potential_engine as _pe
        from app.opportunity_atlas.potential_engine import run_monthly_ic_recalc
        _pe.IC_WEIGHTS_FILE = os.path.join(data_dir, 'ic_weights.json')
        _run_with_timeout(lambda: run_monthly_ic_recalc(_ecm, data_dir),
                          timeout_sec=300, desc='月度 IC 重估（earn-only）')
        logger.info("月度 IC 重估（earn-only）钩子完成")
    except Exception as e:
        logger.warning(f"月度 IC 重估异常: {e}")


def main():
    global _ecm, _running, _retention_checked

    logger.info("data_daemon 启动")
    logger.info(f"DATA_DIR={os.environ.get('DATA_DIR')}")

    # 初始化 ECM——统一走全局单例（get_ecm_instance）
    # 修复 2026-08-15：原 main 直接构造 EnhancedCacheManager() 与采集器/其他模块的
    # get_ecm_instance() 单例并存（双实例、各自 _write_lock 不互斥）→ 并发写同库
    # 触发 SQLite 写锁（实测全天 831 次 "database is locked"；双连接并发写复现 100% 失败）
    from app.data.enhanced_cache_manager import get_ecm_instance
    _ecm = get_ecm_instance()
    logger.info("ECM 就绪（全局单例）")

    # 414号R8: 启动时从SQLite恢复市场级统计缓存
    global _market_stats_cache
    try:
        _market_stats_cache = _ecm.get_cached_market_stats() or {}
        if _market_stats_cache:
            logger.info(f"从SQLite恢复市场级统计缓存: {len(_market_stats_cache)}个指标")
    except Exception as e:
        logger.warning(f"恢复市场级统计缓存失败: {e}")

    # 356号方案：初始化分库管理器（指向正确的 data 目录）
    from app.data.sharding_manager import init_sharding
    # 使用项目根目录下的 data 目录，而不是 backend/data
    data_dir = os.environ.get('DATA_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
    init_sharding(data_dir)
    logger.info(f"分库管理器就绪 (data_dir: {data_dir})")

    # 430号§9-6：注入 IC 权重文件路径（potential_engine 读侧生效）
    try:
        from app.opportunity_atlas import potential_engine as _pe
        _pe.IC_WEIGHTS_FILE = os.path.join(data_dir, 'ic_weights.json')
        logger.info(f"IC 权重文件已注入: {_pe.IC_WEIGHTS_FILE}")
    except Exception as e:
        logger.warning(f"IC 权重注入失败: {e}")

    # 426号 S1/D8：启动自检——打印未登记分库路由的表清单（静默丢写风险面）
    try:
        from app.data.sharding_manager import sharding_manager as _sm
        _unmapped = _sm.list_unmapped_tables(total_conn=_ecm.conn)
        if _unmapped:
            logger.warning(f"未登记分库路由的表清单（{len(_unmapped)}）: {_unmapped}")
        else:
            logger.info("未登记分库路由的表: 无")
    except Exception as e:
        logger.warning(f"未登记表自检失败: {e}")

    # 启动采集器
    collectors = _start_collectors()

    # 信号处理
    def _signal_handler(sig, frame):
        global _running
        logger.info("收到停止信号...")
        _running = False
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 启动完整性检查（回溯最近3个交易日）
    _ensure_pd()
    # 327阶段2：开机数据审计（日志记录数据新鲜度，供运维核查）
    try:
        _audit_data_freshness()
    except Exception as e:
        logger.warning(f"数据审计异常: {e}")
    # 425号 C-1：启动补采闭环——核心数据滞后 >1 天 → HIGH 补采（mootdx 降频让路）；
    # 无滞后则普通模式执行（保持现状行为）。补采后 QA 校验由管道 QA-CHECK 衔接。
    _run_priority_integrity_check(backfill_days=3)

    # 启动回填：指数日线 & 资金流历史数据（25天，供 Dashboard 图表展示）
    try:
        _backfill_index_daily(25)
    except Exception as e:
        logger.warning(f"指数日线回填失败: {e}")
    try:
        _backfill_moneyflow(25)
    except Exception as e:
        logger.warning(f"资金流回填失败: {e}")

    # 管道驱动兜底：开机后自动从断点恢复
    # 替代 _check_daily_sync_backfill() + _check_precompute_status()
    _drive_pipeline()

    # 327阶段5：启动时立即消费 sync_requests 积压（非24h开机时调用层
    # 堆积的 full_* 请求立即处理，不等主循环首个 30s tick）
    try:
        _consume_sync_requests_batch()
    except Exception as e:
        logger.warning(f"启动时消费 sync_requests 失败: {e}")

    # 主循环（每 30 秒检查一次）
    _last_patrol = 0
    _last_ckpt = 0
    _last_truncate = 0
    _last_session = None  # 355号方案规则11：时段切换跟踪

    logger.info("data_daemon 进入主循环（管道驱动）")
    while _running:
        _tick_start = time.time()
        now = datetime.now()
        ts = time.time()

        # 355号方案规则11：时段切换机制
        try:
            from app.utils.trading_hours import get_current_session, get_session_for_collection
            current_session = get_current_session()
            collection_session = get_session_for_collection()

            # 检测时段切换
            if _last_session is not None and _last_session != current_session:
                logger.info(f"时段切换: {_last_session} → {current_session} (采集时段: {collection_session})")

                # 时段切换时执行相应操作
                if current_session == 'close' and _last_session == 'afternoon':
                    # 收盘处理时段开始，触发日终同步
                    logger.info("收盘处理时段开始，触发日终同步...")
                    try:
                        run_daily_sync()
                    except Exception as e:
                        logger.warning(f"日终同步失败: {e}")

                elif current_session == 'morning' and _last_session in ('off', 'night'):
                    # 开盘前时段结束，上午盘开始
                    logger.info("上午盘开始，启动盘中采集...")

            _last_session = current_session
        except ImportError:
            pass

        # ── WAL 周期 checkpoint（2026-08-06 根治③）──
        # 2026-08-12 328号P0：交易时段（API 5s推送活跃，读竞争致 busy=1 全失败）
        # 降频至 30 分钟；非交易时段正常 5 分钟执行——避开读高峰，WAL 可有效收缩
        # （原固定 5 分钟在交易时段撞上 API 读 → 158 次全失败 → WAL 膨胀 7.6G）
        _ckpt_interval = 300 if not _is_market_hours() else 1800
        if ts - _last_ckpt > _ckpt_interval:
            try:
                # 424号P0-2：遍历全部分库执行 checkpoint（原只处理总库）
                _wal_maintenance_all_dbs()
                _last_ckpt = ts
            except Exception as e:
                logger.warning(f"WAL checkpoint 失败: {e}")

        # ── 426号 S4/D2：非交易时段每小时间隔执行 TRUNCATE 深收缩 ──
        # PASSIVE 无法截断有读标记的 WAL；TRUNCATE 需无活跃读事务，失败自动
        # 降级 PASSIVE。非交易时段（周末/盘后）读竞争低，深收缩可靠执行。
        if not _is_market_hours() and ts - _last_truncate > 3600:
            _last_truncate = ts
            try:
                _wal_truncate_all_dbs()
            except Exception as e:
                logger.warning(f"WAL TRUNCATE 维护失败: {e}")

        # ── WAL 阈值告警（2026-08-12 328号 L3）──
        # WAL 超过 2GB 提示膨胀（自动 checkpoint 被读阻塞时只增不减）；
        # 非交易时段 + 管道空闲时提示执行收缩（backend/wal_maintenance.py）。
        if not _is_market_hours():
            try:
                # 424号P0-2：遍历所有分库 WAL 大小（原只统计总库 stock_cache.db-wal）
                _wal_sizes = _wal_maintenance_all_dbs()
                _max_wal_mb = max(_wal_sizes.values()) if _wal_sizes else 0
                _max_wal_db = max(_wal_sizes, key=_wal_sizes.get) if _wal_sizes else ''

                # 356号方案：集成监控告警
                try:
                    from app.data.monitor import monitor
                    for _db, _mb in _wal_sizes.items():
                        monitor.record_metric(f'wal_size_mb_{_db}', _mb)
                    monitor.record_metric('wal_size_mb', _max_wal_mb)
                    if _max_wal_mb > 2048:
                        monitor.create_alert(
                            'WARNING',
                            'WAL文件过大',
                            f'WAL文件大小 {_max_wal_mb:.0f}MB（{_max_wal_db}）超过阈值 2GB',
                            source='wal_monitor',
                            metrics={'wal_size_mb': _max_wal_mb}
                        )
                except Exception:
                    pass

                if _max_wal_mb > 2048:
                    logger.warning(
                        f"WAL 达 {_max_wal_mb:.0f}MB（{_max_wal_db}，>2GB）——建议执行收缩: "
                        f"python backend/wal_maintenance.py --once"
                    )
                # 423号 B3：WAL 阈值整合（>500MB 触发 checkpoint）——非交易时段且距上次
                # >1h 时执行 PASSIVE 合并（轻量非阻塞；TRUNCATE 深收缩由 wal_maintenance
                # 守护在管道空闲时执行，二者互补）。_wal_maintenance_all_dbs 已在上方
                # 周期 checkpoint 中对所有分库执行 PASSIVE，此处仅告警。
            except OSError:
                pass

        # ── sync_requests 队列消费（327阶段5：抽取为函数，主循环与启动时复用） ──
        try:
            _consume_sync_requests_batch()
        except Exception as e:
            logger.warning(f"sync_requests 消费异常: {e}")

        # ── 管道驱动（替代15:30-15:35定时窗口 + 兜底，305号§9） ──
        try:
            _drive_pipeline()
        except Exception as e:
            logger.warning(f"管道驱动异常: {e}")

        # ── 433批次1：月度 IC 重估轻钩子（earn-only；幂等、~3.4s、不阻塞主循环） ──
        try:
            _maybe_monthly_ic_recalc(data_dir)
        except Exception as e:
            logger.warning(f"月度 IC 重估钩子异常: {e}")

        # ── 保留期检查（日终完成后触发一次，305号§9兼容；426号 S3/D1：原数据清理
        #    改为下限保障检查——不删除超期数据，仅告警覆盖不足） ──
        if _is_pipeline_complete(datetime.now().strftime('%Y%m%d')):
            if not _retention_checked:
                try:
                    _check_data_retention()
                    _retention_checked = True
                except Exception as e:
                    logger.warning(f"保留期检查异常: {e}")

        # ── 定时巡检（每整点，非交易时段，不变） ──
        if now.minute == 0 and (now.hour < 9 or now.hour >= 16):
            if ts - _last_patrol > 1800:
                _last_patrol = ts
                if _is_market_day():
                    # 2026-08-16 修复（写锁死锁根治）：SIG/RAW-2/OUT 重算期间
                    # 跳过完整性检查——run_integrity_check 批量补采写库（长事务）
                    # 与 compute_batch 4 worker 的写锁竞争（lldb 实证 4 线程
                    # PyThread_acquire_lock_timed 锁链死锁 + strategy_signal_detail
                    # 零写入）。重算完成（OUT done）后恢复完整性检查。
                    if _is_precompute_in_progress():
                        logger.info("定时巡检：预计算进行中，跳过完整性检查（避免写锁竞争）")
                    else:
                        logger.info("定时巡检...")
                        # 425号 C-1：整点巡检同样挂 HIGH（核心滞后 → 高优补采 + mootdx 降频）
                        _run_priority_integrity_check(backfill_days=1)
                        # 423号 G8：历史日期缺口巡检（最近3个交易日 QA 轻量检测）
                        try:
                            _run_history_qa_patrol()
                        except Exception as e:
                            logger.warning(f"历史 QA 巡检异常: {e}")

        # 425号 C-4：主循环 tick 时长上报（验收量化依据——HIGH 补采窗口 vs 基线对照）
        try:
            from app.data.monitor import monitor
            monitor.record_metric('main_loop_tick_ms', (time.time() - _tick_start) * 1000)
        except Exception as e:
            logger.debug(f"tick 时长指标上报失败: {e}")

        time.sleep(30)

    # 清理
    _stop_collectors()
    logger.info("data_daemon 已停止")


if __name__ == '__main__':
    main()
