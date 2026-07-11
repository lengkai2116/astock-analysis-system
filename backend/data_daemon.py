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
import os, sys, time, threading, signal, logging
from datetime import datetime, timedelta

# ── 环境准备 ──
for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]
os.environ['DATA_DAEMON_RUNNING'] = '1'
os.environ.setdefault('DATA_DIR', '/Users/kalence/Desktop/01-A股股票分析系统/data')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] data_daemon: %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(
            os.path.dirname(__file__), 'logs', 'data_daemon.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('data_daemon')

# ── 全局引用 ──
_running = True
_ecm = None


# ══════════════════════════════════════════════════════════
# 采集器管理
# ══════════════════════════════════════════════════════════

def _start_collectors():
    """启动 mootdx + AKShare 采集器"""
    ok = []
    try:
        from app.data.mootdx_collector import mootdx_collector
        if mootdx_collector.start():
            ok.append('mootdx')
            logger.info("MootdxCollector 已启动")
        else:
            logger.warning("MootdxCollector 未启动（客户端不可用）")
    except Exception as e:
        logger.warning(f"MootdxCollector 启动失败: {e}")

    try:
        from app.data.akshare_collector import akshare_collector
        akshare_collector.start()
        ok.append('akshare')
        logger.info("AkshareCollector 已启动")
    except Exception as e:
        logger.warning(f"AkshareCollector 启动失败: {e}")

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
    df = pro.daily(trade_date=trade_date)
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
    df = pro.daily_basic(trade_date=trade_date)
    if df is None or df.empty:
        return 0
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    _ecm.cache_daily_basic_data(df)
    return len(df)


def _batch_moneyflow(trade_date: str) -> int:
    """全市场资金流向 — 1 次 API 调用"""
    import tushare as ts
    pro = ts.pro_api()
    raw = pro.moneyflow(trade_date=trade_date)
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


def _batch_index_daily(trade_date: str) -> int:
    """四大指数日线 — 批量 API 调用"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    for code in ['000001.SH', '399001.SZ', '899050.BJ', '399006.SZ']:
        try:
            raw = pro.index_daily(ts_code=code, trade_date=trade_date)
            if raw is None or raw.empty:
                continue
            df = raw.copy()
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            # 保留 daily_cache 有的字段
            daily_cols = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg'}
            extra = [c for c in df.columns if c not in daily_cols]
            if extra:
                df = df.drop(columns=extra)
            _ecm.cache_daily_data(df)
            total += len(df)
        except Exception as e:
            logger.warning(f"指数 {code} 同步失败: {e}")
    return total


def _batch_stk_limit(trade_date: str) -> int:
    """全市场涨跌停 — 1 次 API 调用"""
    import tushare as ts
    pro = ts.pro_api()
    raw = pro.stk_limit(trade_date=trade_date)
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
    raw = pro.top_list(trade_date=trade_date)
    if raw is None or raw.empty:
        return 0
    df = raw.rename(columns={
        'pct_change': 'change_pct', 'l_buy': 'buy_amount',
        'l_sell': 'sell_amount', 'net_rate': 'buy_rate',
        'amount_rate': 'sell_rate'
    })
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
    _ecm.cache_lhb_data(df)
    return len(df)


def _batch_margin(trade_date: str) -> int:
    """全市场融资融券个股明细 — 1 次 API 调用"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    raw = pro.margin_detail(trade_date=trade_date)
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


def _batch_concept() -> int:
    """全市场概念板块及成分股 — 2 次 API 调用"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    # 1. 获取概念列表
    concept_list = pro.concept()
    if concept_list is None or concept_list.empty:
        return 0
    # 2. 获取每个概念的成分股
    detail_records = []
    for _, row in concept_list.iterrows():
        concept_code = row.get('code') or row.get('concept_code')
        concept_name = row.get('name') or row.get('concept_name')
        if not concept_code:
            continue
        try:
            detail = pro.concept_detail(id=concept_code)
            if detail is not None and not detail.empty:
                for _, d in detail.iterrows():
                    detail_records.append({
                        'ts_code': d.get('ts_code'),
                        'concept_name': concept_name or concept_code,
                        'concept_code': concept_code,
                    })
        except Exception as e:
            logger.debug(f"概念 {concept_code} 详情获取失败: {e}")
    # 存概念列表（兼容 pro.concept() 输出）
    try:
        _ecm.cache_concept_data(concept_list)
    except Exception as e:
        logger.warning(f"概念列表缓存失败: {e}")
    # 存成分股映射
    if detail_records:
        _ecm.cache_concept_data(pd.DataFrame(detail_records))
    total = len(concept_list) + len(detail_records)
    logger.info(f"概念板块同步完成: {len(concept_list)} 个概念, {len(detail_records)} 条成分股映射")
    return total


def _batch_index_member() -> int:
    """指数成分股 — 对主要指数逐一查询"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    main_indices = ['000300.SH', '000016.SH', '000905.SH', '399006.SZ']
    for code in main_indices:
        try:
            raw = pro.index_member(ts_code=code)
            if raw is not None and not raw.empty:
                df = raw.copy()
                if 'in_date' in df.columns:
                    df['in_date'] = pd.to_datetime(df['in_date']).dt.date
                _ecm.cache_index_member_data(df)
                total += len(df)
        except Exception as e:
            logger.warning(f"指数 {code} 成分股同步失败: {e}")
    return total


def _batch_win_rate() -> int:
    """策略胜率计算 — 从历史信号计算，不调外部 API"""
    _ensure_pd()
    try:
        from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
        manager = PrecomputeIndicatorManager()
        manager.compute_win_rates()
        win_df = manager.get_win_rates()
        if win_df is not None and not win_df.empty:
            _ecm.cache_win_rates(win_df)
            return len(win_df)
    except Exception as e:
        logger.warning(f"胜率计算失败: {e}")
    return 0


def _batch_fina_indicator(trade_date: str = None) -> int:
    """全市场财务指标 — 后台低优任务"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    try:
        # Tushare fina_indicator 可指定 period 获取最近一期
        df = pro.fina_indicator(period=trade_date)
        if df is not None and not df.empty:
            for col in ['end_date', 'ann_date']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col]).dt.date
            _ecm.cache_fina_indicator_data(df)
            total = len(df)
            logger.info(f"  [财务指标] 同步 {total} 条")
    except Exception as e:
        logger.warning(f"  [财务指标] 批量同步失败: {e}")
    return total


def _batch_income_recent(limit_days: int = 90) -> int:
    """增量同步最近一期利润表 — 后台低优"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache"
    ).fetchall()
    codes = [r[0] for r in codes[:500]]  # 限500只，避免过长
    for code in codes:
        try:
            raw = pro.income(ts_code=code, start_date=None, end_date=None)
            if raw is not None and not raw.empty:
                if 'end_date' in raw.columns:
                    raw['end_date'] = pd.to_datetime(raw['end_date']).dt.date
                if 'ann_date' in raw.columns:
                    raw['ann_date'] = pd.to_datetime(raw['ann_date']).dt.date
                _ecm.cache_income_data(raw)
                total += len(raw)
        except Exception:
            continue
    logger.info(f"  [利润表] 增量同步 {total} 条 (共 {len(codes)} 只)")
    return total


def _batch_balancesheet(limit_days: int = 90) -> int:
    """增量同步最近一期资产负债表 — 后台低优"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache"
    ).fetchall()
    codes = [r[0] for r in codes[:500]]
    for code in codes:
        try:
            raw = pro.balancesheet(ts_code=code, start_date=None, end_date=None)
            if raw is not None and not raw.empty:
                for col in ['end_date', 'ann_date', 'f_ann_date']:
                    if col in raw.columns:
                        raw[col] = pd.to_datetime(raw[col]).dt.date
                _ecm.cache_balancesheet_data(raw)
                total += len(raw)
        except Exception:
            continue
    logger.info(f"  [资产负债表] 同步 {total} 条 (共 {len(codes)} 只)")
    return total


def _batch_cashflow(limit_days: int = 90) -> int:
    """增量同步最近一期现金流量表 — 后台低优"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache"
    ).fetchall()
    codes = [r[0] for r in codes[:500]]
    for code in codes:
        try:
            raw = pro.cashflow(ts_code=code, start_date=None, end_date=None)
            if raw is not None and not raw.empty:
                for col in ['end_date', 'ann_date', 'f_ann_date']:
                    if col in raw.columns:
                        raw[col] = pd.to_datetime(raw[col]).dt.date
                _ecm.cache_cashflow_data(raw)
                total += len(raw)
        except Exception:
            continue
    logger.info(f"  [现金流量表] 同步 {total} 条 (共 {len(codes)} 只)")
    return total


def _batch_forecast(limit_days: int = 90) -> int:
    """增量同步最近一期业绩预告 — 后台低优"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache"
    ).fetchall()
    codes = [r[0] for r in codes[:500]]
    for code in codes:
        try:
            raw = pro.forecast(ts_code=code, start_date=None, end_date=None)
            if raw is not None and not raw.empty:
                for col in ['end_date', 'ann_date']:
                    if col in raw.columns:
                        raw[col] = pd.to_datetime(raw[col]).dt.date
                _ecm.cache_forecast_data(raw)
                total += len(raw)
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
        globals()['pd'] = pd
        IMPORT_PD = True


def _check_count(table: str, trade_date: str) -> int:
    try:
        return _ecm.conn.execute(
            f"SELECT COUNT(*) FROM \"{table}\" WHERE trade_date=?", [trade_date]
        ).fetchone()[0]
    except Exception:
        return 0


def run_integrity_check(backfill_days: int = 1):
    """启动/巡检时执行：检查缺失数据并用批量 API 补采"""
    _ensure_pd()
    today = datetime.now().strftime('%Y%m%d')
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    logger.info("开始完整性检查...")

    # 指数日线检查：4只指数代码在 daily_cache 中的记录数
    idx_codes = ['000001.SH', '399001.SZ', '899050.BJ', '399006.SZ']
    idx_checks = []
    for offset in range(0, backfill_days):
        d = (datetime.now() - timedelta(days=offset))
        ds = d.strftime('%Y-%m-%d')
        if d.weekday() >= 5:
            continue
        try:
            cnt = _ecm.conn.execute(
                "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND ts_code IN (?,?,?,?)",
                [ds] + idx_codes
            ).fetchone()[0]
        except Exception:
            cnt = 0
        if cnt < 4:
            idx_checks.append(ds)

    checks = [
        ('daily_cache',     _batch_daily,      DAILY_THRESHOLD,  '日线'),
        ('daily_basic_cache', _batch_daily_basic, BASIC_THRESHOLD, '基本面'),
        ('moneyflow_cache', _batch_moneyflow,   MF_THRESHOLD,    '资金流向'),
        ('stk_limit_cache', _batch_stk_limit,   LIMIT_THRESHOLD, '涨跌停'),
        ('lhb_cache',       _batch_lhb,         LHB_THRESHOLD,   '龙虎榜'),
    ]

    # 融资融券单独检查（margin_detail 非每日必须，空表时补采）
    try:
        margin_cnt = _check_count('margin_cache', today_fmt) if today_fmt else 0
        if margin_cnt == 0:
            logger.info("  [融资融券] 空表，触发补采...")
            added = _batch_margin(today)
            logger.info(f"    → 补采 {added} 条")
        else:
            logger.info(f"  [融资融券] {margin_cnt} 行 ✅")
    except Exception as e:
        logger.warning(f"  融资融券检查失败: {e}")

    # 财务指标补充检查（非每日判断，仅检查有无数据）
    try:
        fina_cnt = _ecm.conn.execute(
            "SELECT COUNT(*) FROM fina_indicator_cache"
        ).fetchone()[0]
        if fina_cnt < 100:
            logger.info(f"  [财务指标] {fina_cnt}行 (需≥100)，触发补采...")
            _batch_fina_indicator(today)
    except Exception as e:
        logger.warning(f"  财务指标检查失败: {e}")

    # 检查今日数据
    for table, batch_fn, threshold, label in checks:
        cnt = _check_count(table, today_fmt)
        if cnt < threshold:
            logger.info(f"  [{label}] 今日 {cnt}行 (需≥{threshold})，补采...")
            added = batch_fn(today)
            logger.info(f"    → 补采 {added} 条")
        else:
            logger.info(f"  [{label}] 今日 {cnt}行 ✅")

    # 回退补采最近 N 个交易日（检查前一天的完整性）
    if backfill_days > 1:
        for offset in range(1, backfill_days):
            d = (datetime.now() - timedelta(days=offset))
            ds = d.strftime('%Y%m%d')
            df = d.strftime('%Y-%m-%d')
            if d.weekday() >= 5:  # 跳过周末
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

    logger.info("完整性检查完成")


# ══════════════════════════════════════════════════════════
# 日终同步
# ══════════════════════════════════════════════════════════

_SYNCED_TODAY = False


def run_daily_sync():
    """15:30 触发：批量 API 同步 5 类数据"""
    global _SYNCED_TODAY
    today = datetime.now().strftime('%Y%m%d')
    logger.info("=== 日终同步开始 ===")

    tasks = [
        ('daily_cache',      _batch_daily,      '日线'),
        ('daily_basic_cache',_batch_daily_basic,'基本面'),
        ('moneyflow_cache',  _batch_moneyflow,  '资金流向'),
        ('stk_limit_cache',  _batch_stk_limit,  '涨跌停'),
        ('index_daily_cache',_batch_index_daily,'指数日线'),
        ('lhb_cache',        _batch_lhb,        '龙虎榜'),
    ]

    for table, batch_fn, label in tasks:
        try:
            added = batch_fn(today)
            logger.info(f"  {label}: {added} 条")
        except Exception as e:
            logger.warning(f"  {label} 失败: {e}")

    # ── 补齐空表（迭代4）──
    try:
        n = _batch_margin(today)
        logger.info(f"  融资融券: {n} 条")
    except Exception as e:
        logger.warning(f"  融资融券同步失败: {e}")
    try:
        n = _batch_concept()
        logger.info(f"  概念板块: {n} 条")
    except Exception as e:
        logger.warning(f"  概念板块同步失败: {e}")
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

    # 触发指标预计算（后台线程）
    try:
        threading.Thread(target=_run_precompute, daemon=True).start()
        logger.info("  指标预计算已触发（后台）")
    except Exception as e:
        logger.warning(f"  指标预计算触发失败: {e}")

    # 财务数据同步（后台低优，不阻塞主同步流程）
    try:
        threading.Thread(target=_run_financial_sync, daemon=True).start()
        logger.info("  财务数据同步已触发（后台）")
    except Exception as e:
        logger.warning(f"  财务数据同步触发失败: {e}")

    # 分钟K线回填（后台低优，补齐盘中未覆盖的股票）
    try:
        threading.Thread(target=_run_minute_backfill, daemon=True).start()
        logger.info("  分钟K线回填已触发（后台）")
    except Exception as e:
        logger.warning(f"  分钟K线回填触发失败: {e}")

    _SYNCED_TODAY = True
    logger.info("=== 日终同步完成 ===")


def _run_precompute():
    """后台预计算指标（仅当日有日线数据的活跃股票）"""
    _ensure_pd()
    logger.info("指标预计算开始...")
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?",
        [today_fmt]
    ).fetchall()
    if not codes:
        logger.info(" 今日无日线数据，跳过预计算")
        return
    codes = [r[0] for r in codes]
    logger.info(f" 活跃股票: {len(codes)} 只")
    from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
    mgr = PrecomputeIndicatorManager(_ecm)
    ok = 0
    for code in codes:
        try:
            df = _ecm.get_cached_daily(code)
            if len(df) >= 30:
                if mgr.precompute_all_indicators(code, df):
                    ok += 1
        except Exception:
            pass
    logger.info(f"指标预计算完成: {ok}/{len(codes)} 只")

    # ── 策略信号预计算（仅活跃股票） ──
    try:
        from app.services.signal_computation_service import SignalComputationService
        scs = SignalComputationService()
        count = 0
        for ts_code in codes:
            try:
                signals = scs.compute_for_stock(ts_code)
                if signals:
                    _ecm.cache_strategy_signals(ts_code, signals)
                    count += 1
            except Exception:
                continue
        logger.info(f"策略信号预计算完成: {count}/{len(codes)} 只")
    except Exception as e:
        logger.warning(f"策略信号预计算失败: {e}")


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
    trade_date_fmt = datetime.now().strftime('%Y-%m-%d')

    # Step 1: 获取今日有日线数据的股票列表
    try:
        daily_stocks = _ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?",
            [trade_date_fmt]
        ).fetchall()
        daily_stocks = [r[0] for r in daily_stocks]
    except Exception as e:
        logger.warning(f"[分钟回填] 查询日线股票列表失败: {e}")
        return

    if not daily_stocks:
        logger.info(f"[分钟回填] 今日无日线数据，跳过")
        return

    # Step 2: 查询已有分钟数据的股票
    try:
        minute_stocks = _ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE trade_date=?",
            [trade_date_fmt]
        ).fetchall()
        minute_stocks = set(r[0] for r in minute_stocks)
    except Exception:
        minute_stocks = set()

    # Step 3: 计算缺失股票，限500只
    missing = [s for s in daily_stocks if s not in minute_stocks][:500]
    if not missing:
        logger.info(f"[分钟回填] 今日分钟数据已完整 ({len(daily_stocks)} 只)")
        return

    logger.info(f"[分钟回填] 需补齐 {len(missing)} 只 (已有 {len(minute_stocks)} 只, 共 {len(daily_stocks)} 只)")

    # Step 4: 逐只调用 Tushare pro_bar 补齐
    import tushare as ts
    pro = ts.pro_api()
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

    logger.info(f"[分钟回填] 完成: 成功 {ok}/{len(missing)} 只")


def _run_minute_backfill():
    """后台分钟K线回填包装"""
    from app.data.enhanced_cache_manager import get_ecm_instance
    global _ecm
    if _ecm is None:
        _ecm = get_ecm_instance()
    today = datetime.now().strftime('%Y%m%d')
    _batch_backfill_minute_kline(today)


def _run_data_cleanup():
    """执行数据清理（迭代5：日期格式统一 + 存储清理）"""
    today = datetime.now().strftime('%Y%m%d')

    # 计算各表的清理截止日期
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
    three_years_ago = (datetime.now() - timedelta(days=1095)).strftime('%Y%m%d')
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')

    try:
        _ecm.clean_stk_limit_cache(one_year_ago)
    except Exception as e:
        logger.warning(f"清理 stk_limit_cache 失败: {e}")

    try:
        _ecm.clean_lhb_cache(one_year_ago)
    except Exception as e:
        logger.warning(f"清理 lhb_cache 失败: {e}")

    try:
        _ecm.clean_fina_indicator_cache(three_years_ago)
    except Exception as e:
        logger.warning(f"清理 fina_indicator_cache 失败: {e}")

    try:
        _ecm.clean_minute_cache(thirty_days_ago)
    except Exception as e:
        logger.warning(f"清理 minute_cache 失败: {e}")

    # 每月执行一次 VACUUM
    if datetime.now().day == 1:
        try:
            _ecm.vacuum_db()
        except Exception as e:
            logger.warning(f"VACUUM 失败: {e}")

    logger.info("数据清理完成")


# ══════════════════════════════════════════════════════════
# 主循环
# ══════════════════════════════════════════════════════════

def _is_market_day() -> bool:
    """粗略判断是否为交易日（周一至周五）"""
    return datetime.now().weekday() < 5


def _is_market_hours() -> bool:
    """是否为交易时段（9:00-15:30）"""
    h = datetime.now().hour
    return 9 <= h <= 15


def main():
    global _ecm, _running

    logger.info("data_daemon 启动")
    logger.info(f"DATA_DIR={os.environ.get('DATA_DIR')}")

    # 初始化 ECM
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    _ecm = EnhancedCacheManager()
    logger.info("ECM 就绪")

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
    run_integrity_check(backfill_days=3)

    # 主循环（每 30 秒检查一次）
    _last_patrol = 0
    _daily_sync_triggered = False

    logger.info("data_daemon 进入主循环")
    while _running:
        now = datetime.now()
        ts = time.time()

        # ── 日终同步 (15:30-15:35，5分钟窗口避免错过) ──
        if now.hour == 15 and 30 <= now.minute <= 35 and not _daily_sync_triggered:
            _daily_sync_triggered = True
            run_daily_sync()
            _run_data_cleanup()  # 日终同步完成后执行清理

        # 重置日终同步标记（离开15:30-15:35窗口后重置）
        if not (now.hour == 15 and 30 <= now.minute <= 35):
            _daily_sync_triggered = False

        # ── 定时巡检（每整点，非交易时段） ──
        if now.minute == 0 and (now.hour < 9 or now.hour >= 16):
            if ts - _last_patrol > 1800:  # 至少间隔30分钟
                _last_patrol = ts
                if _is_market_day():
                    logger.info("定时巡检...")
                    run_integrity_check(backfill_days=1)

        time.sleep(30)

    # 清理
    _stop_collectors()
    logger.info("data_daemon 已停止")


if __name__ == '__main__':
    main()
