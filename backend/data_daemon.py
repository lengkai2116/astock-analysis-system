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

def _ts(pro_func, *args, **kwargs):
    """带速率限制的 Tushare API 调用"""
    global _ts_last_call
    elapsed = time.time() - _ts_last_call
    if elapsed < _TS_MIN_INTERVAL:
        time.sleep(_TS_MIN_INTERVAL - elapsed)
    _ts_last_call = time.time()
    return pro_func(*args, **kwargs)

# 补充：stk_mins 极严限流（1次/分钟）
_ts_minute_last_call = 0.0
_TS_MINUTE_INTERVAL = 60.0

def _ts_minute(pro_func, *args, **kwargs):
    """极严限流的分钟数据接口（1次/分钟）"""
    global _ts_minute_last_call
    elapsed = time.time() - _ts_minute_last_call
    if elapsed < _TS_MINUTE_INTERVAL:
        time.sleep(_TS_MINUTE_INTERVAL - elapsed)
    _ts_minute_last_call = time.time()
    return pro_func(*args, **kwargs)

# ── 全局引用 ──
_running = True
_cleanup_done = False  # 数据清理一次性标记（日终完成后执行一次；修复 2026-08-04：原挂在 bool _running 上必然失败）
_ecm = None


# ══════════════════════════════════════════════════════════
# 采集器管理
# ══════════════════════════════════════════════════════════

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
    try:
        # 获取最近5个交易日
        dates = _ecm.conn.execute(
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
        rows = _ecm.conn.execute(
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
                _ecm.conn.execute(
                    "UPDATE daily_basic_cache SET volume_ratio = ? WHERE ts_code = ? AND trade_date = ?",
                    [r['volume_ratio'], r['ts_code'], today]
                )
                updated += 1
        _ecm.conn.commit()
        if updated > 0:
            logger.info(f"  [量比] 自算回写 {updated} 条")
        return updated
    except Exception as e:
        logger.warning(f"  [量比] 计算失败: {e}")
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


# 申万一级行业指数代码（28 个，2026-08-12 修正：原注释误写 31，且完整性检查用错阈值致回填死循环）
SW_INDEX_CODES = [
    '801010.SI', '801020.SI', '801030.SI', '801040.SI', '801050.SI',
    '801080.SI', '801110.SI', '801120.SI', '801130.SI', '801140.SI',
    '801150.SI', '801160.SI', '801170.SI', '801180.SI', '801200.SI',
    '801210.SI', '801230.SI', '801710.SI', '801720.SI', '801730.SI',
    '801740.SI', '801750.SI', '801760.SI', '801770.SI', '801780.SI',
    '801790.SI', '801880.SI', '801890.SI',
]


def _batch_index_daily(trade_date: str) -> int:
    """四大指数日线 + 申万行业指数日线 — 批量 API 调用"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0

    # 四大宽基指数
    for code in ['000001.SH', '399001.SZ', '899050.BJ', '399006.SZ']:
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

    # 申万一级行业指数（28 个，模块级常量 SW_INDEX_CODES）
    sw_codes = SW_INDEX_CODES
    sw_count = 0
    for code in sw_codes:
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
            sw_count += 1
        except Exception as e:
            logger.debug(f"行业指数 {code} 同步失败: {e}")
    if sw_count > 0:
        logger.info(f"  申万行业指数: {sw_count}/{len(sw_codes)} 个")
    total += sw_count
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
    import tushare as ts
    pro = ts.pro_api()
    raw = _ts(pro.margin_detail, trade_date=trade_date)
    if raw is None or raw.empty:
        # 非交易日降级：使用 daily_cache 中的最新交易日
        try:
            latest = _ecm.conn.execute(
                "SELECT MAX(trade_date) FROM daily_cache"
            ).fetchone()[0]
            if latest:
                # 统一格式为 YYYYMMDD（Tushare API 要求）
                fallback = latest.replace('-', '')
                if fallback != trade_date:
                    raw = _ts(pro.margin_detail, trade_date=fallback)
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
    """363号F55-3修复：支持日期范围的融资融券增量回补"""
    from datetime import datetime as _dt, timedelta
    start = _dt.strptime(start_date, '%Y-%m-%d')
    end = _dt.strptime(end_date, '%Y-%m-%d')
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
                    _ecm.cache_fina_indicator_data(df)
                    total = len(df)
                    logger.info(f"  [财务指标] 同步 {total} 条")
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

                for code in stock_codes:
                    try:
                        df = _ts(pro.fina_indicator, ts_code=code)
                        if df is not None and not df.empty:
                            # 获取最新的财务指标
                            df_sorted = df.sort_values('end_date', ascending=False)
                            latest = df_sorted.iloc[0:1]  # 只取最新一期

                            for col in ['end_date', 'ann_date']:
                                if col in latest.columns:
                                    latest[col] = pd.to_datetime(latest[col]).dt.date

                            _ecm.cache_fina_indicator_data(latest)
                            total += 1
                    except Exception as e:
                        pass  # 跳过失败的股票

                logger.info(f"  [财务指标] 逐只同步完成，共 {total} 条")
        except Exception as e:
            logger.warning(f"  [财务指标] 获取股票列表失败: {e}")

    except Exception as e:
        logger.warning(f"  [财务指标] 批量同步失败: {e}")
    return total


def _find_kline_insufficient(threshold: int = 130, limit: int = 5000) -> list:
    """320号 F1：找出 daily_cache K 线不足 threshold 根的股票

    策略引擎需要 ≥130 根 K 线（缠论/量价门槛），不足则机会图谱标签与
    九层解读的 K 线依赖维度同时失效。
    """
    global _ecm
    if _ecm is None:
        from app.data.enhanced_cache_manager import get_ecm_instance
        _ecm = get_ecm_instance()
    try:
        rows = _ecm.conn.execute(
            "SELECT ts_code, COUNT(*) cnt FROM daily_cache GROUP BY ts_code HAVING cnt < ? LIMIT ?",
            [threshold, limit]
        ).fetchall()
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
    """全市场复权因子 — 批量按 trade_date（替代逐只500次）
    实测 pro.adj_factor(trade_date=date) 可返回全市场数据，
    等价于逐只调用但只需 1 次 API 请求。
    """
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    # 用最近交易日
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    try:
        raw = _ts(pro.adj_factor, trade_date=yesterday)
        if raw is not None and not raw.empty:
            df = raw.copy()
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            _ecm.cache_adj_factor_data(df)
            return len(df)
    except Exception:
        pass
    # 降级：逐只（仅当批量失败时）
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache"
    ).fetchall()
    codes = [r[0] for r in codes[:500]]
    total = 0
    for code in codes:
        try:
            raw = _ts(pro.adj_factor, ts_code=code)
            if raw is not None and not raw.empty:
                df = raw.copy()
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                _ecm.cache_adj_factor_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [复权因子] 降级逐只同步 {total} 条 (共 {len(codes)} 只)")
    return total


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
    codes = _ecm.conn.execute("SELECT DISTINCT ts_code FROM daily_cache").fetchall()
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
    codes = _ecm.conn.execute("SELECT DISTINCT ts_code FROM daily_cache").fetchall()
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


def _batch_finance_report() -> int:
    """全市场扩展财务指标（273a 排雷指标）

    后台低优，每次最多处理 500 只。
    使用 pro.fina_indicator 带 FINA_FIELDS_EXTENDED 字段集。
    """
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache"
    ).fetchall()
    codes = [r[0] for r in codes[:500]]
    FINA_FIELDS_EXTENDED = (
        'ts_code,end_date,roce,dt_eps,profit_dedt,'
        'q_sales,q_profit,q_eps,yoy_tr,yoy_profit,'
        'bps,ocfps,quick_ratio,free_cashflow_ps'
    )
    total = 0
    for code in codes:
        try:
            raw = _ts(pro.fina_indicator, ts_code=code, fields=FINA_FIELDS_EXTENDED)
            if raw is not None and not raw.empty:
                df = raw.copy()
                for col in ['end_date', 'ann_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col]).dt.date
                _ecm.cache_finance_report_data(df)
                total += len(df)
        except Exception:
            continue
    logger.info(f"  [扩展财务] 同步 {total} 条 (共 {len(codes)} 只)")
    return total


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

    # 获取当日有数据的所有股票（与 _run_precompute 同模式）
    try:
        rows = _ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?",
            [td_fmt]
        ).fetchall()
        if not rows:
            # 非交易日回退：用最新交易日
            row = _ecm.conn.execute(
                "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            if row:
                td_fmt = row[0]
                rows = _ecm.conn.execute(
                    "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?",
                    [td_fmt]
                ).fetchall()
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
            raw = _ts(pro.income, ts_code=code, start_date=None, end_date=None)
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
            raw = _ts(pro.balancesheet, ts_code=code, start_date=None, end_date=None)
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
            raw = _ts(pro.cashflow, ts_code=code, start_date=None, end_date=None)
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
            raw = _ts(pro.forecast, ts_code=code, start_date=None, end_date=None)
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


def run_integrity_check(backfill_days: int = 1):
    """启动/巡检时执行：检查缺失数据并用批量 API 补采"""
    _ensure_pd()
    today = datetime.now().strftime('%Y%m%d')
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    logger.info("开始完整性检查...")

    # 指数日线检查：4只指数代码在 daily_cache 中的记录数（356号：从分库读取）
    idx_codes = ['000001.SH', '399001.SZ', '899050.BJ', '399006.SZ']
    idx_checks = []
    for offset in range(0, backfill_days):
        d = (datetime.now() - timedelta(days=offset))
        ds = d.strftime('%Y-%m-%d')
        if d.weekday() >= 5:
            continue
        try:
            cnt = _query_table('daily_cache',
                "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND ts_code IN (?,?,?,?)",
                [ds] + idx_codes)
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
    try:
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
    batch_background = [
        ('top10_holders_cache', _batch_top10_holders, '前十大股东'),
        ('stk_holder_cache',    _batch_stk_holder,    '股东人数'),
        ('finance_report_cache', _batch_finance_report, '扩展财务'),
    ]
    for table, batch_fn, label in batch_background:
        try:
            cnt = _query_table(table, f"SELECT COUNT(*) FROM {table}")
            if cnt == 0:
                logger.info(f"  [{label}] 空表，触发补采...")
                added = batch_fn()
                logger.info(f"    → 补采 {added} 条")
            else:
                logger.info(f"  [{label}] {cnt} 行 ✅")
        except Exception as e:
            logger.warning(f"  [{label}] 检查失败: {e}")

    # adj_factor单独检查：空表或时效性滞后>3天时触发补采（356号：从分库读取）
    try:
        adj_cnt = _query_table('adj_factor_cache', "SELECT COUNT(*) FROM adj_factor_cache")
        if adj_cnt == 0:
            logger.info("  [复权因子] 空表，触发补采...")
            added = _batch_adj_factor()
            logger.info(f"    → 补采 {added} 条")
        else:
            adj_latest = _query_table('adj_factor_cache', "SELECT MAX(trade_date) FROM adj_factor_cache")
            if adj_latest:
                from datetime import datetime as _dt
                # 兼容 YYYYMMDD 和 YYYY-MM-DD 两种日期格式
                _date_str = str(adj_latest).replace('-', '')
                latest_date = _dt.strptime(_date_str, '%Y%m%d')
                _today_str = today.replace('-', '') if isinstance(today, str) else _dt.now().strftime('%Y%m%d')
                today_date = _dt.strptime(_today_str, '%Y%m%d')
                days_lag = (today_date - latest_date).days
                if days_lag > 3:
                    logger.info(f"  [复权因子] 滞后 {days_lag} 天（阈值3天），触发补采...")
                    added = _batch_adj_factor()
                    logger.info(f"    → 补采 {added} 条")
                else:
                    logger.info(f"  [复权因子] {adj_cnt} 行，最新 {adj_latest} ✅")
            else:
                logger.info(f"  [复权因子] {adj_cnt} 行 ✅")
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

    # 检查今日数据（非交易日跳过，数据量必然为0）
    _is_weekday = datetime.now().weekday() < 5
    if not _is_weekday:
        logger.info("  今日为非交易日，跳过今日数据检查")
    for table, batch_fn, threshold, label in checks:
        if not _is_weekday:
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

    # 申万行业指数完整性检查（28 个行业，缺失时回填60日）
    try:
        have_rows = _ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM daily_cache WHERE ts_code LIKE '801%.SI'"
        ).fetchall()
        have_set = {r[0] for r in have_rows}
        # 2026-08-12 修正：用实际 sw_codes 列表对比（原硬编码 31，实际 28，
        # 致 sw_cnt<31 恒真 → 每次完整性检查都回填 60 天 → 死循环阻塞主循环）
        missing = [c for c in SW_INDEX_CODES if c not in have_set]
        if missing:
            # 2026-08-12 修正2：回填后仍缺（如 801020 数据源永久缺失）不应每 tick 重试
            # 60 天回填（死循环阻塞主循环）——检查当日是否已尝试过回填，是则跳过
            today_key = f'sw_index_backfilled:{datetime.now().strftime("%Y%m%d")}'
            try:
                done_row = _ecm.conn.execute(
                    "SELECT value FROM cache_metadata WHERE key=?", [today_key]
                ).fetchone()
                if done_row:
                    logger.info(f"  [申万行业指数] 当日已回填尝试过（缺 {len(missing)} 个，跳过）")
                    # 不return——继续执行后续完整性检查和管道驱动
            except Exception:
                pass
            logger.info(f"  [申万行业指数] 缺 {len(missing)}/{len(SW_INDEX_CODES)} 个（{missing[:3]}...），跳过（数据源缺失）")
            # 记录当日已尝试（避免死循环；次日数据源恢复时自动重试）
            try:
                _ecm.conn.execute(
                    "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                    [today_key, str(len(missing))]
                )
                _ecm.conn.commit()
            except Exception:
                pass
        else:
            logger.info(f"  [申万行业指数] 完整（{len(SW_INDEX_CODES)} 个）✅")
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
            _query_table(table, f"SELECT MAX(trade_date) FROM {table}")
            if latest:
                latest_date = datetime.strptime(str(latest), '%Y-%m-%d') if isinstance(latest, str) else latest
                days_lag = (today - latest_date).days
                if days_lag > 1:
                    logger.warning(f"  [时效性] {label}({table}) 滞后 {days_lag} 天")
                else:
                    logger.debug(f"  [时效性] {label}({table}) 滞后 {days_lag} 天 ✅")
        except Exception as e:
            logger.debug(f"  {label}时效性检查失败: {e}")

    # 补充数据时效性检查（滞后不超过7天）
    supplement_tables = [
        ('margin_cache', '融资融券'),
        ('adj_factor_cache', '复权因子'),
    ]

    for table, label in supplement_tables:
        try:
            _query_table(table, f"SELECT MAX(trade_date) FROM {table}")
            if latest:
                latest_date = datetime.strptime(str(latest), '%Y-%m-%d') if isinstance(latest, str) else latest
                days_lag = (today - latest_date).days
                if days_lag > 7:
                    logger.warning(f"  [时效性] {label}({table}) 滞后 {days_lag} 天")
                else:
                    logger.debug(f"  [时效性] {label}({table}) 滞后 {days_lag} 天 ✅")
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
            _query_table(table, f"SELECT MAX(trade_date) FROM {table}")
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
        daily_codes = set(row[0] for row in _ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date = ?",
            [today_fmt]
        ).fetchall())
        basic_codes = set(row[0] for row in _ecm.conn.execute(
            "SELECT DISTINCT ts_code FROM daily_basic_cache WHERE trade_date = ?",
            [today_fmt]
        ).fetchall())

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
    try:
        time_check = _ecm.conn.execute("""
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
        """, [today_fmt, today_fmt]).fetchone()[0]
        if time_check > 0:
            logger.warning(f"  [数据一致性] 时间不一致: {time_check} 只股票跨表日期差>3天")
    except Exception as e:
        logger.debug(f"  时间一致性检查失败: {e}")

    # 检查逻辑一致性：high >= close >= low
    try:
        logic_anomaly = _ecm.conn.execute("""
            SELECT COUNT(*) FROM daily_cache
            WHERE trade_date = ? AND (high < close OR close < low)
        """, [today_fmt]).fetchone()[0]
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
            cnt = _ecm.conn.execute(
                'SELECT COUNT(*) FROM minute_kline_cache WHERE ts_code=? AND freq="5min"',
                [code]
            ).fetchone()[0]
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
        ('lhb_detail_cache', _batch_lhb_detail, '龙虎榜席位'),
        ('concept_cache',    _batch_concept,    '概念板块'),
    ]

    for table, batch_fn, label in tasks:
        try:
            added = batch_fn(today)
            logger.info(f"  {label}: {added} 条")
        except Exception as e:
            logger.warning(f"  {label} 失败: {e}")

    # 量比自算（Tushare 免费 API 不提供 volume_ratio，计算层自算）
    _compute_volume_ratio(today)

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
    # 旧代码 _run_precompute 与管道驱动竞争写入，导致数据丢失

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
            except Exception:
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
    for code in codes:
        try:
            # 327阶段4：单只因子计算超时保护（防止单只卡死拖垮全量）
            def _factor_one(c=code, _fpm=fpm, _mf=mapped_factors):
                df = _ecm.get_cached_daily(c)
                if df is None or len(df) < 30:
                    return 'skip'
                for cn_name, en_name in _mf.items():
                    try:
                        _fpm.precompute_factor(c, df, en_name)
                    except Exception:
                        pass
                return 'ok'
            r = _run_with_timeout(_factor_one, timeout_sec=30.0,
                                  desc=f"因子 {code}")
            if r is None:
                timeout_count += 1
            elif r == 'ok':
                precomputed += 1
        except Exception:
            continue
    logger.info(f"因子预计算完成: {precomputed}/{len(codes)} 只" +
                (f"，超时跳过 {timeout_count} 只" if timeout_count else ""))

def _run_precompute():
    """后台预计算指标（仅当日有日线数据的活跃股票，非交易日自动回退到最近交易日）"""
    _ensure_pd()
    logger.info("指标预计算开始...")
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    codes = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?",
        [today_fmt]
    ).fetchall()
    if not codes:
        # 非交易日无数据，用最近交易日
        row = _ecm.conn.execute(
            "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if row:
            today_fmt = row[0]
            codes = _ecm.conn.execute(
                "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?",
                [today_fmt]
            ).fetchall()
            logger.info(f" 今日无数据，回退到最近交易日: {today_fmt}")
        else:
            logger.info(" 数据库无日线数据，跳过预计算")
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

    # ── 3. PRESET_COMBOS 因子值预计算（写入 factor_cache） ──
    try:
        _precompute_preset_combos(codes)
    except Exception as e:
        logger.warning(f"PRESET_COMBOS 因子预计算失败: {e}")

    # ── 3.5 RAW-2 原料加工特征提取（357号方案 → pre_feat_cache） ──
    try:
        _precompute_raw_features(codes)
    except Exception as e:
        logger.warning(f"RAW-2原料加工失败: {e}")

    # ── 4. [已废弃] L2标签预计算 → 已由RAW-2替代 ──
    # try:
    #     _precompute_l2_labels(codes)
    # except Exception as e:
    #     logger.warning(f"L2标签预计算失败: {e}")

    # ── 5. 策略信号预计算（UnifiedStrategyCore，287号方案 v2.3） ──
    # 333号 v3.0 管道顺序：P4 标签先算当日 → P2 后算（P2 消费当日标签，杜绝"标签昨日/数据今日"时序错位）
    try:
        from app.engine.unified_core import UnifiedStrategyCore
        core = UnifiedStrategyCore()
        results = core.compute_batch(codes, max_workers=4)
        count = 0
        for ts_code, result in results.items():
            try:
                _ecm.cache_signal_detail(ts_code, result.to_dict())
                count += 1
            except Exception:
                continue
        logger.info(f"策略信号预计算完成: {count}/{len(codes)} 只 (UnifiedStrategyCore)")
        if count == 0 and codes:
            logger.info("策略信号全部失败，回退到因子信号写入...")
            _write_factor_signals(codes)
    except Exception as e:
        logger.warning(f"策略信号预计算整体失败: {e}")


def _precompute_l2_labels(codes):
    """L2标签预计算：估值引擎+阶段判定+情绪+板块 → 聚合写入 opportunity_tags_cache

    执行顺序（对所有活跃股）：
      1. 估值标签（ValuationEngine）→ 写入 tags
      2. 阶段判定标签（PhaseDetectionEngine）→ 写入 tags
      3. 情绪标签（MarketSentimentService）→ 写入 tags
      4. 板块标签（SectorRotationModel）→ 写入 tags
      5. 聚合衍生：计算 signal_strength → 写入 tags
      6. 批量写入 opportunity_tags_cache
    """
    _ensure_pd()
    if not codes:
        return
    logger.info(f"L2标签预计算开始: {len(codes)} 只...")

    # 创建 Flask app context（供 ValuationEngine/MarketSentimentService/SectorRotationModel 使用 ORM）
    from app import create_app
    _flask_app = create_app()

    with _flask_app.app_context():
        # 延迟导入各引擎（只在 precompute 时加载，不占用主循环内存）
        from app.opportunity_atlas.valuation_estimator import ValuationEngine
        from app.opportunity_atlas.phase_detector import PhaseDetectionEngine
        from app.services.market_sentiment_service import MarketSentimentService
        from app.engine.framework.sector_rotation_model import SectorRotationModel
        # 313号：机会潜力强度引擎（7 维截面百分位 + IC 加权 + 综合公式）
        from app.opportunity_atlas.potential_engine import PotentialEngine, compute_fund_strength
        from app.opportunity_atlas import potential_engine as _pe_module
        import os as _os
        _pe_module.IC_WEIGHTS_FILE = _os.path.join(
            _os.environ.get('DATA_DIR', 'data'), 'ic_weights.json')

        # 各引擎延迟初始化
        ve = ValuationEngine()
        pd_engine = PhaseDetectionEngine()
        ms = MarketSentimentService()
        sr = SectorRotationModel()
        # 315号方案B：估值引擎 composite 截面百分位基准（level 分档用，precompute 前一次）
        try:
            ve.build_composite_percentile(_ecm)
        except Exception as e:
            logger.warning(f"  估值截面基准构建失败: {e}")
        # 315号 F5：FCF yield 截面基准（锚3 相对化）
        try:
            ve.build_fcf_percentile(_ecm)
        except Exception as e:
            logger.warning(f"  FCF 截面基准构建失败: {e}")
        # 313号：潜力引擎 + 全市场截面百分位基准（precompute 前一次）
        _potential_engine = PotentialEngine()
        try:
            _potential_engine.build_percentile_tables(_ecm)
            logger.info("  机会潜力引擎截面基准构建完成")
        except Exception as e:
            logger.warning(f"  潜力截面构建失败: {e}")
        # IC 滚动重估（313 §4.2 第三层：月度——权重文件超 30 天未更新则重估）
        try:
            import time as _time
            if (not _os.path.exists(_pe_module.IC_WEIGHTS_FILE)
                    or _time.time() - _os.path.getmtime(_pe_module.IC_WEIGHTS_FILE) > 30 * 86400):
                logger.info("  IC 权重月度重估中...")
                _new_w = _pe_module.recompute_ic_weights(_ecm)
                _pe_module.save_ic_weights(_new_w)
                logger.info(f"  IC 权重已更新: {_new_w}")
        except Exception as e:
            logger.warning(f"  IC 重估跳过: {e}")
        # P2.5 引擎：时间节奏
        from app.opportunity_atlas.time_rhythm_engine import TimeRhythmEngine
        tre = TimeRhythmEngine()
        # P2.5 引擎：量价标签（VolumePriceStrategy + ChipDistribution + MainForce）
        from app.engine.framework.volume_price_strategy import VolumePriceStrategy
        vps = VolumePriceStrategy()
        from app.engine.framework.chanlun_strategy import get_chanlun_tags as _get_chanlun_tags
        from app.data.chip_distribution_service import ChipDistributionEstimator
        cde = ChipDistributionEstimator()
        # P2.1 引擎：事件监控器
        from app.opportunity_atlas.event_monitor import EventMonitor
        em = EventMonitor()

        # 批量预加载全市场日线数据（减少逐只 SQL 查询）
        all_data: dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = _ecm.get_cached_daily(code)
                if df is not None and not df.empty:
                    all_data[code] = df
            except Exception:
                pass
        logger.info(f"  日线数据加载完成: {len(all_data)}/{len(codes)} 只")

        # 预计算板块热度（全市场一次性计算）
        try:
            sr.compute_all_heat(all_data)
        except Exception as e:
            logger.warning(f"  板块热度预计算失败: {e}")

        # 预计算市场情绪（从 daily_cache 数据估算，替代 sentiment_pool 数据源缺失）
        # 342号核查修复（2026-08-16）：单指标涨停数>80 判 climax 与知识库《情绪周期四阶段模型》
        # 多条件（涨停 50-100+封板率>75%+指数拉升+天量）不符，弱市（08-14 涨停84/跌停18）被误判
        # climax 99.98%。升级为 涨停数 + 估算封板率 + 跌停数 多条件判定。
        _sentiment_phase_global = 'neutral'
        try:
            last_date_row = _ecm.conn.execute(
                "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            if last_date_row:
                last_date = last_date_row[0]
                limit_up = _ecm.conn.execute(
                    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg > 9.9",
                    [last_date]
                ).fetchone()[0]
                limit_down = _ecm.conn.execute(
                    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg < -9.9",
                    [last_date]
                ).fetchone()[0]
                # 估算封板率：触板（high>=prev_close*1.099）中收盘封住的比例
                sealing_rate = 0.0
                try:
                    rows = _ecm.conn.execute(
                        "SELECT high, close, pct_chg FROM daily_cache "
                        "WHERE trade_date=? AND pct_chg > 5",
                        [last_date]
                    ).fetchall()
                    touched = sealed = 0
                    for high, close, pct in rows:
                        prev_close = close / (1 + pct / 100)
                        if high >= prev_close * 1.099:
                            touched += 1
                            if close >= prev_close * 1.099:
                                sealed += 1
                    if touched > 0:
                        sealing_rate = round(sealed / touched * 100, 1)
                except Exception:
                    sealing_rate = 0.0
                # 四阶段映射（对齐知识库《情绪周期四阶段模型》）
                if limit_up > 50 and sealing_rate > 75:
                    _sentiment_phase_global = 'climax'
                elif (limit_up < 40 and sealing_rate < 40) or limit_down > 20:
                    _sentiment_phase_global = 'ebb'
                elif limit_up < 20 and sealing_rate < 40:
                    _sentiment_phase_global = 'ice'
                else:
                    _sentiment_phase_global = 'recovery'
        except Exception:
            pass

        t0 = time.time()
        succeeded = 0
        commit_count = 0
        BATCH_SIZE = 500
        _val_fail = 0            # 估值引擎失败计数（2026-08-04：静默吞异常排查）
        _val_fail_samples = []   # 估值失败样例（最多记 10 条）
        _engine_fail = 0         # 整只失败计数（外层异常）

        for code in codes:
            try:
                tags = {}
                df = all_data.get(code)   # 2026-08-04 修复：循环开头取 df（原缺失→首只 NameError 跳过、后续量价/缠论用上一只错位 df→buy_sell_point 等标签不落库→闸门2 无输入）

                # 1. 估值引擎产出（P0.1）— 只需要 ts_code
                try:
                    v_tags = ve.compute_tags(code)
                    if v_tags:
                        tags.update(v_tags)
                except Exception as e:
                    _val_fail += 1
                    if len(_val_fail_samples) < 10:
                        _val_fail_samples.append(f"{code}: {type(e).__name__}: {e}")

                # 3. 情绪引擎产出（P0.5）— 不需要 ts_code
                try:
                    sentiment = ms.get_sentiment_phase()
                    if sentiment.get('data_available'):
                        tags['sentiment_phase'] = sentiment['phase']
                    elif _sentiment_phase_global != 'neutral':
                        tags['sentiment_phase'] = _sentiment_phase_global
                except Exception:
                    if _sentiment_phase_global != 'neutral':
                        tags['sentiment_phase'] = _sentiment_phase_global

                # 4. 板块热度（P0.6）— 从缓存读取预计算结果
                try:
                    sector = sr.evaluate(code)
                    tags['sector_heat'] = sector.get('sector_heat', 'none')
                except Exception:
                    pass

                # 5. style_exposure（295号§3.2 标签12）
                try:
                    tags['style_exposure'] = _compute_style_exposure(code, tags, df)
                except Exception:
                    pass

                # 5b. time_rhythm（P2.5，302号§四）— 需要日线数据
                if df is not None and len(df) >= 30:
                    try:
                        tr_tags = tre.compute_tags(df)
                        if tr_tags:
                            tags.update(tr_tags)
                    except Exception:
                        pass

                    # 5c. VolumePrice 量价标签 + 缠论买点 + 筹码（P2.5）
                    try:
                        vp_tags = vps._detect_kline_patterns(df)
                        if vp_tags:
                            tags.update(vp_tags)
                    except Exception:
                        pass
                    # volume_price_fit / volatility_level / ma_alignment（简单计算）
                    try:
                        _add_vp_simple_tags(df, tags)
                    except Exception:
                        pass
                    # 缠论买卖点
                    try:
                        from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
                        cl = ChanlunAnalyzer()
                        cl_result = cl.analyze(df)
                        cl_tags = _get_chanlun_tags(cl_result)
                        if cl_tags:
                            tags.update(cl_tags)
                    except Exception:
                        pass
                    # 筹码分布
                    try:
                        chip_tags = cde.get_tags(df)
                        if chip_tags:
                            tags.update(chip_tags)
                    except Exception:
                        pass

                    # 2. 阶段判定引擎产出（312号：8 维度加权共识）— 移到缠论/情绪/板块之后，
                    #    以接入 buy_sell_point / sentiment_phase / sector_heat / capital_nature
                    # 2026-08-10 修复：capital_nature 生产者接入（MainForceScorer 此前
                    #    无 precompute 调用 → 100% unknown；lhb 数据充足 3308 行）
                    try:
                        from app.engine.framework.chip_strategy import MainForceScorer
                        _mf_tags = MainForceScorer().get_tags(code)
                        if _mf_tags.get('capital_nature'):
                            tags['capital_nature'] = _mf_tags['capital_nature']
                    except Exception:
                        pass
                    df = all_data.get(code)
                    if df is not None and len(df) >= 30:
                        try:
                            # 327阶段4：单只阶段判定超时保护（历史 600218 卡死点——
                            # compute_tags 死循环拖垮 P4 全量）
                            def _phase_one(c=code, _df=df, _pd=pd_engine,
                                           _tags=tags):
                                return _pd.compute_tags(c, _df, extra_tags={
                                    'buy_sell_point': _tags.get('buy_sell_point'),
                                    'sentiment_phase': _tags.get('sentiment_phase'),
                                    'sector_heat': _tags.get('sector_heat'),
                                    'capital_nature': _tags.get('capital_nature'),
                                })
                            p_tags = _run_with_timeout(
                                _phase_one, timeout_sec=30.0,
                                desc=f"阶段判定 {code}")
                            if p_tags:
                                tags.update(p_tags)
                        except Exception:
                            pass

                    # 5. 机会潜力强度已由 4c2 计算（313号 v4 替代 311 旧评分）

                    # 323号 S0：深度字段落库（缠论结构 + 筹码分布 + 资金风险）
                    # 367号：统一使用 extract_chip_deep_tags，不再依赖 _last_chip_indicators
                    try:
                        from app.opportunity_atlas.tag_extractor import (
                            extract_chanlun_deep_tags, extract_chip_deep_tags,
                            extract_fund_risk_tags, DEEP_TAG_GROUPS,
                        )
                        _deep = {}
                        _deep.update(extract_chanlun_deep_tags(code))
                        _deep.update(extract_fund_risk_tags(code))
                        _deep.update(extract_chip_deep_tags(code))
                        # 带 tag_group 写入（dict 格式显式指定 group）
                        _deep_meta = {}
                        for _k, _v in _deep.items():
                            _g = DEEP_TAG_GROUPS.get(_k, 'unknown')
                            _deep_meta[_k] = {'value': _v, 'group': _g, 'source': 'PrecomputeL2Labels'}
                        if _deep_meta:
                            tags.update(_deep_meta)
                    except Exception:
                        pass

                # 兜底标签
                for _mandatory_tag, _default_val in [
                    ('pattern_signal', 'none'), ('capital_nature', 'unknown'),
                ]:
                    if _mandatory_tag not in tags:
                        tags[_mandatory_tag] = _default_val

                # 4b. 事件监控（P2.1）
                try:
                    _update_with_event_tags(code, tags)
                except Exception:
                    pass

                # 4c. upward_driver（P2.1 收益分解, 302号§三）
                if df is not None and len(df) >= 20:
                    try:
                        _add_upward_driver(df, tags)
                    except Exception:
                        pass

                # 4c2. 机会潜力强度（313号 v4 §四）— 替代旧 signal_strength 主力评分；
                #     移到事件之后（事件标签已就绪），消费方 opportunity_meta/闸门在其后
                try:
                    mf_strength = compute_fund_strength(_ecm, code)
                    _roe = None
                    try:
                        _r = _ecm._query_df(
                            "SELECT roe FROM fina_indicator_cache WHERE ts_code=? "
                            "ORDER BY end_date DESC LIMIT 1", [code])
                        if not _r.empty:
                            _roe = _r["roe"].iloc[0]
                    except Exception:
                        pass
                    tags["roe"] = _roe if _roe is not None else 0
                    pot = _potential_engine.compute_potential(tags, mf_strength)
                    tags.update(pot)
                except Exception:
                    pass

                # 4c3. 主力在场判定（313号 §十：行为证据主导——龙虎榜/股东户数/融资异动）
                try:
                    mfp = _compute_main_force_presence(code, _ecm)
                    tags.update(mfp)
                except Exception:
                    pass

                # 4d. 机会元信息（307号：七维画像 + 机会类型摘要 + 证据计数，替代306号持有周期）
                try:
                    _compute_opportunity_meta(tags)
                except Exception:
                    pass

                # 4e. 闸门2右侧确认（309号§7.1：否决/基础/增强三档判定）
                try:
                    rc = _check_right_side_confirm(tags.get('opportunity_type', 'default'), tags, df)
                    tags.update(rc)
                except Exception:
                    pass

                # 4f. 跨维仲裁（321号：机会状态机 + 显式仲裁优先级表 P0-P7）
                #     输入 4 链标签（含 4e 闸门2 结果），输出单一 opportunity_state +
                #     state_evidence；消费点（颜色/建议/verdict/仓位）从状态派生。
                try:
                    from app.opportunity_atlas.arbiter import arbitrate
                    arb = arbitrate(tags)
                    if arb.get('opportunity_state'):
                        tags.update(arb)
                except Exception:
                    # 2026-08-10 325档案修复：仲裁异常兜底写 wait（原静默跳过致
                    # opportunity_state 缺失；停牌/退市股不参与预计算
                    # 也走此兜底）
                    tags.setdefault('opportunity_state', 'wait')
                    tags.setdefault('state_evidence', '仲裁异常，保守等待')

                # 4g. 机会类型 avoid 降级（321号 S3：规则树互斥，修 T2）
                #     4d 在仲裁前执行（state 未生成），此处按仲裁结果重判机会类型：
                #     avoid 态 → "回避·仅观察"；非 avoid 保持 4d 原判定。
                if tags.get('opportunity_state') == 'avoid':
                    try:
                        type_result = _classify_opportunity_type(tags)
                        tags.update(type_result)
                    except Exception:
                        pass

                # 6. 写入数据库
                if len(tags) > 0:
                    _ecm.write_tags(code, tags)
                    succeeded += 1
                    commit_count += 1
                    if commit_count >= BATCH_SIZE:
                        _ecm.conn.commit()
                        commit_count = 0

            except Exception:
                _engine_fail += 1
                continue

        if commit_count > 0:
            _ecm.conn.commit()

        elapsed = time.time() - t0
        _val_summary = f"，估值引擎失败 {_val_fail} 只"
        if _val_fail_samples:
            _val_summary += "（样例: " + "; ".join(_val_fail_samples[:3]) + "）"
        logger.info(f"L2标签预计算完成: {succeeded}/{len(codes)} 只, 耗时 {elapsed:.1f}s"
                    f"{_val_summary}，整只失败 {_engine_fail} 只")


def _chip_tags_from_indicators(indicators: dict) -> dict:
    """[已废弃] 从 phase_detector._last_chip_indicators 提取筹码深度字段（323号 S0）

    367号：此函数已废弃，统一使用 extract_chip_deep_tags() 替代。
    保留供向后兼容使用，待后续版本删除。
    """
    import json as _json
    out = {}
    if not indicators:
        return out
    if isinstance(indicators.get('main_peak'), dict):
        pk = indicators['main_peak'].get('price')
        if pk is not None:
            try:
                out['chip_peak'] = str(round(float(pk), 2))
            except (TypeError, ValueError):
                pass
    for key in ('asr', 'cyqkl', 'concentration', 'profit_ratio', 'ssrp',
                'sandwich_zone', 'retail_vs_institutional', 'sentiment_crowding',
                'sentiment_crowding_label', 'fake_institution',
                'asr_status', 'concentration_status', 'cyqkl_status',
                'peak_count', 'peak_type', 'avg_vol_100', 'vol_ratio'):
        if key in indicators and indicators[key] is not None:
            v = indicators[key]
            out[key] = _json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
    return out


def _precompute_raw_features(codes):
    """原料加工环节：特征提取（RAW-2 FEAT）→ 写入 pre_feat_cache

    357号方案：从 _precompute_l2_labels 中提取纯原料加工步骤，
    仅计算10组特征（valuation/sentiment/sector/style/timing/volume_price/chanlun/chip/event/depth），
    写入 pre_feat_cache（JSON格式，54字段）。

    不含阶段判定/主力在场/机会潜力/仲裁等判定层操作（移到JUD环节）。

    Args:
        codes: 股票代码列表
    """
    _ensure_pd()
    if not codes:
        return
    logger.info(f"RAW-2 原料加工开始: {len(codes)} 只...")

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
        from app.opportunity_atlas.risk_boundary_builder import _calc_volatility_percentile
        from app.engine.framework.chip_strategy import MainForceScorer
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        from app.opportunity_atlas.dimensions.shared_vol_ratio import calc_vol_ratio
        from app.opportunity_atlas.signal_attribute_classifier import classify_attribute
        from app.opportunity_atlas.signal_decay_detector import detect_decay

        # 各引擎初始化
        ve = ValuationEngine()
        ms = MarketSentimentService()
        sr = SectorRotationModel()
        tre = TimeRhythmEngine()
        vps = VolumePriceStrategy()
        cde = ChipDistributionEstimator()
        em = EventMonitor()

        # 截面基准构建
        try:
            ve.build_composite_percentile(_ecm)
        except Exception:
            pass
        try:
            ve.build_fcf_percentile(_ecm)
        except Exception:
            pass

        # 批量加载日线数据
        all_data: dict[str, pd.DataFrame] = {}
        for code in codes:
            try:
                df = _ecm.get_cached_daily(code)
                if df is not None and not df.empty:
                    all_data[code] = df
            except Exception:
                pass
        logger.info(f"  日线数据加载完成: {len(all_data)}/{len(codes)} 只")

        # 预计算板块热度
        try:
            sr.compute_all_heat(all_data)
        except Exception:
            pass

        # 市场情绪全局值
        _sentiment_phase_global = 'neutral'
        try:
            last_date_row = _ecm.conn.execute(
                "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            if last_date_row:
                last_date = last_date_row[0]
                limit_up = _ecm.conn.execute(
                    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg > 9.9",
                    [last_date]
                ).fetchone()[0]
                limit_down = _ecm.conn.execute(
                    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg < -9.9",
                    [last_date]
                ).fetchone()[0]
                sealing_rate = 0.0
                try:
                    rows = _ecm.conn.execute(
                        "SELECT high, close, pct_chg FROM daily_cache "
                        "WHERE trade_date=? AND pct_chg > 5",
                        [last_date]
                    ).fetchall()
                    touched = sealed = 0
                    for high, close, pct in rows:
                        prev_close = close / (1 + pct / 100)
                        if high >= prev_close * 1.099:
                            touched += 1
                            if close >= prev_close * 1.099:
                                sealed += 1
                    if touched > 0:
                        sealing_rate = round(sealed / touched * 100, 1)
                except Exception:
                    pass
                if limit_up > 50 and sealing_rate > 75:
                    _sentiment_phase_global = 'climax'
                elif (limit_up < 40 and sealing_rate < 40) or limit_down > 20:
                    _sentiment_phase_global = 'ebb'
                elif limit_up < 20 and sealing_rate < 40:
                    _sentiment_phase_global = 'ice'
                else:
                    _sentiment_phase_global = 'recovery'
        except Exception:
            pass

        t0 = time.time()
        succeeded = 0
        commit_count = 0
        BATCH_SIZE = 500
        trade_date = None

        for code in codes:
            try:
                df = all_data.get(code)
                if df is None or df.empty or len(df) < 5:
                    continue
                if trade_date is None:
                    trade_date = str(df['trade_date'].iloc[-1])[:10]

                features = {}

                # 1. 估值特征（17字段）
                try:
                    v_tags = ve.compute_tags(code)
                    if v_tags:
                        features['valuation'] = {k: v for k, v in v_tags.items()
                            if k in ('pe_percentile', 'pb_percentile', 'ps_percentile',
                                     'pe_percentile_5y', 'pb_percentile_5y', 'ps_percentile_5y',
                                     'valuation_level', 'valuation_deviation',
                                     'fcf_yield', 'dividend_yield', 'composite_rating',
                                     'revenue_growth', 'roe', 'fina_health',
                                     'asset_anchor_rating', 'earnings_anchor_rating',
                                     'cashflow_anchor_rating', 'adjusted_anchor_rating')}
                except Exception as e:
                    logger.warning(f"RAW估值特征失败 [{code}]: {e}")

                # 2. 情绪特征（2字段：sentiment_phase + bociasi_signal）
                try:
                    _sent = {}
                    # sentiment_phase：始终写入（默认neutral）
                    try:
                        sentiment = ms.get_sentiment_phase()
                        if sentiment.get('data_available'):
                            _sent['sentiment_phase'] = sentiment['phase']
                        else:
                            _sent['sentiment_phase'] = _sentiment_phase_global or 'neutral'
                    except Exception:
                        _sent['sentiment_phase'] = _sentiment_phase_global or 'neutral'
                    # bociasi_signal：跨市场资金情绪（读HS300指数）
                    try:
                        from app.services.benchmark_service import BenchmarkService
                        bm = BenchmarkService()
                        idx_df = bm.get_index_daily('000300.SH')
                        if idx_df is not None and len(idx_df) >= 20:
                            idx_close = idx_df['close'].values
                            fast = float(np.mean(idx_close[-5:]))
                            slow = float(np.mean(idx_close[-20:]))
                            _sent['bociasi_signal'] = 'bullish' if fast > slow else 'bearish'
                        else:
                            _sent['bociasi_signal'] = 'neutral'
                    except Exception:
                        _sent['bociasi_signal'] = 'neutral'
                    features['sentiment'] = _sent
                except Exception as e:
                    logger.warning(f"RAW情绪特征失败 [{code}]: {e}")

                # 3. 板块特征（4字段）
                try:
                    sector = sr.evaluate(code)
                    features['sector'] = {
                        'sector_heat': sector.get('sector_heat', 0),
                        'sector_momentum': sector.get('sector_momentum', 0),
                        'sector_rank': sector.get('sector_rank', 0),
                        'is_sector_leader': sector.get('is_sector_leader', False),
                    }
                except Exception as e:
                    logger.warning(f"RAW板块特征失败 [{code}]: {e}")

                # 4. 风格特征（2字段：style_exposure + size_factor）
                try:
                    style = _compute_style_exposure(code, {}, df)
                    _sz = 'unknown'
                    try:
                        _db = _ecm.get_cached_daily_basic(code)
                        if _db is not None and not _db.empty and 'circ_mv' in _db.columns:
                            circ = float(_db['circ_mv'].iloc[-1] or 0)
                            if circ > 5e10:
                                _sz = 'large_cap'
                            elif circ > 1e10:
                                _sz = 'mid_cap'
                            else:
                                _sz = 'small_cap'
                    except Exception:
                        pass
                    features['style'] = {
                        'style_exposure': style if isinstance(style, str) else 'balanced',
                        'size_factor': _sz,
                    }
                except Exception as e:
                    logger.warning(f"RAW风格特征失败 [{code}]: {e}")

                # 5. 时间特征（3字段）
                if len(df) >= 30:
                    try:
                        tr_tags = tre.compute_tags(df)
                        if tr_tags:
                            features['timing'] = {k: v for k, v in tr_tags.items()
                                if k in ('time_rhythm', 'cycle_position', 'turnover_signal')}
                    except Exception as e:
                        logger.warning(f"RAW时间特征失败 [{code}]: {e}")

                # 6. 量价特征（6字段）
                if len(df) >= 20:
                    try:
                        vp_tags = vps._detect_kline_patterns(df)
                        _simple = {}
                        _add_vp_simple_tags(df, _simple)
                        features['volume_price'] = {
                            'kline_pattern': vp_tags.get('pattern_signal', 'none'),
                            'ma_alignment': _simple.get('ma_alignment', 'neutral'),
                            'volume_price_fit': _simple.get('volume_price_fit', 'neutral'),
                            'gap_type': _simple.get('gap_type', 'none'),
                            'breakout_attempts': _simple.get('breakout_attempts', 0),
                            'vol_price_ratio': _simple.get('vol_price_ratio', 1.0),
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
                        features['chanlun'] = {k: v for k, v in (cl_tags or {}).items()
                            if k in ('trend_direction', 'zhongshu_count', 'buy_sell_point',
                                     'bi_count', 'duan_count')}
                    except Exception as e:
                        logger.warning(f"RAW缠论特征失败 [{code}]: {e}")

                # 8. 筹码特征（4字段）
                if len(df) >= 30:
                    try:
                        chip_tags = cde.get_tags(df)
                        features['chip'] = {k: v for k, v in (chip_tags or {}).items()
                            if k in ('chip_position', 'chip_concentration', 'asr', 'cyqkl')}
                    except Exception as e:
                        logger.warning(f"RAW筹码特征失败 [{code}]: {e}")

                # 9. 事件特征（3字段）
                try:
                    _evt_tags = {}
                    _update_with_event_tags(code, _evt_tags)
                    features['event'] = {
                        'catalyst_event': _evt_tags.get('catalyst_event', 'none'),
                        'catalyst_impact': _evt_tags.get('catalyst_impact', 'neutral'),
                        'event_composite_score': _evt_tags.get('event_composite_score', 0),
                    }
                except Exception as e:
                    logger.warning(f"RAW事件特征失败 [{code}]: {e}")

                # 10. 深度字段（8字段，独立调用不依赖 phase_detector）
                try:
                    _depth = {}
                    _depth.update(extract_chanlun_deep_tags(code))
                    _depth.update(extract_chip_deep_tags(code))
                    _depth.update(extract_fund_risk_tags(code))
                    features['depth'] = {
                        'hold_float_ratio': _depth.get('hold_float_ratio'),
                        'turnover_rate': _depth.get('turnover_rate'),
                        'main_force_phase': _depth.get('main_force_phase'),
                        'phase_confidence': _depth.get('phase_confidence'),
                        'fund_flow': _depth.get('fund_flow'),
                        'capital_nature': _depth.get('capital_nature'),
                        'main_force_presence': _depth.get('main_force_presence'),
                        'presence_evidence': _depth.get('presence_evidence'),
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
                    # 位置维
                    _derived['price_position'] = 'low_zone' if _cl.get('buy_sell_point', '') in ('first_buy', 'second_buy') else ('high_zone' if _cl.get('buy_sell_point', '') in ('first_sell', 'second_sell') else 'mid')
                    _derived['support_resistance'] = _depth_f.get('support_resistance', '{}')
                    # 风险维
                    _derived['volatility_level'] = _vp_f.get('vol_price_ratio', 1.0) and ('high' if abs(float(_vp_f.get('vol_price_ratio', 1.0) or 1) - 1) > 0.5 else 'low')
                    _derived['risk_level'] = 'HIGH' if _depth_f.get('main_force_phase') == 'shipping' else 'LOW'
                    # 信号确认
                    _derived['right_side_confirm'] = 'strong_confirm' if _cl.get('buy_sell_point', '') in ('first_buy', 'second_buy') and _vp_f.get('volume_price_fit') == 'healthy' else 'unconfirmed'
                    _derived['pattern_signal'] = _vp_f.get('kline_pattern', 'none')
                    # 生命信号
                    _derived['active_signal'] = _cl.get('buy_sell_point', '') if _cl.get('buy_sell_point', '') not in ('none',) else None
                    # 状态标签
                    _derived['state_label'] = _cl.get('trend_direction', 'unknown')
                    _derived['trend_alignment'] = 'aligned' if _cl.get('trend_direction') == 'up' and _vp_f.get('ma_alignment') == 'bullish' else 'misaligned'
                    # 利润比
                    _derived['profit_ratio'] = _chip_f.get('chip_position', 0)
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
                    features['risk_ext'] = _risk_feat
                except Exception as e:
                    logger.warning(f"RAW风险扩展字段失败 [{code}]: {e}")

                # 13. 资金筹码扩展字段（365号批次A / Phase 3）
                try:
                    _chip_fund_feat = {}
                    # fund_flow_strength: 大单净流入强度（0-1）
                    try:
                        mfs = MainForceScorer()
                        _sub = mfs.get_sub_scores(df, symbol=code)
                        _chip_fund_feat['fund_flow_strength'] = min(1.0, max(0.0, (_sub.get('total', 0) or 0) / 10.0))
                    except Exception:
                        _chip_fund_feat['fund_flow_strength'] = None
                    # chip_transfer: 筹码转移方向
                    _chip_fund_feat['chip_transfer'] = _depth_f.get('main_force_phase', 'unknown') if _depth_f.get('main_force_phase') in ('accumulating', 'shipping') else 'neutral'
                    # control_degree: 控盘度
                    _chip_fund_feat['control_degree'] = _depth.get('hold_float_ratio')
                    features['chip_fund_ext'] = _chip_fund_feat
                except Exception as e:
                    logger.warning(f"RAW资金筹码扩展字段失败 [{code}]: {e}")

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
                    )
                    # market_emotion: 市场情绪阶段
                    _emotion_feat['market_emotion'] = _sent.get('sentiment_phase', 'neutral')
                    # sector_emotion: 板块情绪
                    _emotion_feat['sector_emotion'] = 'hot' if (_sect.get('sector_rank') or 999) <= 10 else 'normal'
                    # stock_emotion: 个股情绪
                    _emotion_feat['stock_emotion'] = 'positive' if _vp_f_em.get('volume_price_fit') == 'healthy' else ('negative' if _vp_f_em.get('volume_price_fit') == 'diverging' else 'neutral')
                    features['emotion_ext'] = _emotion_feat
                except Exception as e:
                    logger.warning(f"RAW情绪扩展字段失败 [{code}]: {e}")

                # 15. 量价健康扩展字段（365号批次A / Phase 5）
                try:
                    _vp_health_feat = {}
                    # vp_score: 10分制评分（占位，使用粗略估算）
                    _vp_health_feat['vp_score'] = None  # 待 vp_health_builder 独立函数就绪后填充
                    # vp_state_type: 量价状态类型
                    _vp_stage = _vp_f.get('kline_pattern', '')
                    _vp_health_feat['vp_state_type'] = 'fast_line' if '突破' in str(_vp_stage) else ('slow_line' if '回踩' in str(_vp_stage) else 'background')
                    # volume_energy: 量能强度
                    if len(df) >= 5:
                        _vols = df['volume'].values
                        _avg5 = float(_vols[-5:].mean()) if len(_vols) >= 5 else float(_vols.mean())
                        _vr = calc_vol_ratio(float(_vols[-1]), _avg5)
                        _vp_health_feat['volume_energy'] = min(1.0, max(0.0, (_vr - 0.5) / 2.0)) if _vr else None
                    else:
                        _vp_health_feat['volume_energy'] = None
                    features['vp_health_ext'] = _vp_health_feat
                except Exception as e:
                    logger.warning(f"RAW量价健康扩展字段失败 [{code}]: {e}")

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

                # 17. 信号确认扩展字段（365号批次A / Phase 7）
                try:
                    _signal_feat = {}
                    _signal_feat['signal_attribute'] = _derived.get('right_side_confirm', 'unconfirmed')
                    # decay_score: 衰减检测
                    try:
                        _decay_result = detect_decay(_derived)
                        _signal_feat['decay_score'] = _decay_result.get('overall_score', 0)
                    except Exception:
                        _signal_feat['decay_score'] = None
                    # resonance_score: 共振评分（占位）
                    _signal_feat['resonance_score'] = None
                    features['signal_ext'] = _signal_feat
                except Exception as e:
                    logger.warning(f"RAW信号确认扩展字段失败 [{code}]: {e}")

                # 写入 pre_feat_cache
                if features:
                    _ecm.cache_pre_feat(code, trade_date, features)
                    succeeded += 1
                    commit_count += 1
                    if commit_count >= BATCH_SIZE:
                        _ecm.conn.commit()
                        commit_count = 0

            except Exception:
                continue

        if commit_count > 0:
            _ecm.conn.commit()

        elapsed = time.time() - t0
        logger.info(f"RAW-2 原料加工完成: {succeeded}/{len(codes)} 只, 耗时 {elapsed:.1f}s"
                    f", trade_date={trade_date}")


def _add_vp_simple_tags(df, tags):
    """计算简单量价标签：ma_alignment / volume_price_fit / volatility_level / gap_type / breakout_attempts"""
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

        # gap_type: 最近5日跳空
        gap_found = False
        for i in range(-min(5, len(closes)), 0):
            if i < -1:
                prev_high = highs[i-1] if abs(i-1) < len(highs) else highs[i]
                cur_low = lows[i]
                if cur_low > prev_high * 1.005:
                    tags['gap_type'] = 'common' if abs(i) > 2 else 'breakaway'
                    gap_found = True
                    break
        if not gap_found:
            tags['gap_type'] = 'none'

        # breakout_attempts: 近60日突破尝试次数
        if len(closes) >= 60:
            current = closes[-1]
            nearby_mask = np.abs(closes[-60:] - current) / max(current, 1) < 0.03
            vol_avg = np.mean(vols[-60:])
            attempts = 0
            for j in range(len(closes) - 60, len(closes)):
                if nearby_mask[j - (len(closes) - 60)] and vols[j] > vol_avg * 1.5:
                    attempts += 1
            tags['breakout_attempts'] = min(attempts, 4)

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

    # 情绪：市场情绪 + 板块热度
    sp_status = {'ice': '冰点', 'recovery': '复苏', 'climax': '高潮', 'ebb': '退潮'}.get(sp, '中性')
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
    # 画像为嵌套 dict，序列化为 JSON 字符串以便 write_tags 落库（309号 S3）
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
    """获取当日活跃股票代码列表"""
    if today_fmt is None:
        today_fmt = datetime.now().strftime('%Y-%m-%d')
    rows = _ecm.conn.execute(
        "SELECT ts_code FROM daily_cache WHERE trade_date=? "
        "GROUP BY ts_code ORDER BY ts_code",
        [today_fmt]
    ).fetchall()
    if not rows:
        row = _ecm.conn.execute(
            "SELECT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if row:
            today_fmt = row[0]
            rows = _ecm.conn.execute(
                "SELECT ts_code FROM daily_cache WHERE trade_date=? "
                "GROUP BY ts_code ORDER BY ts_code", [today_fmt]
            ).fetchall()
    return [r[0] for r in rows] if rows else []


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


def _build_treemap_snapshot(codes: list[str]):
    """日终预计算完成后，构建 treemap_snapshot 快照表（S1 管道环节）

    修复 2026-08-02：函数内使用 pd.notna 但未导入 pandas → INSERT 全失败

    从 daily_cache / daily_basic_cache / opportunity_tags_cache 提取最新数据，
    平铺写入 treemap_snapshot 表（4800 行 × ~25 列 ≈ 2-3 MB）。
    使用原子表替换避免读写不一致。
    """
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
    daily_df = _ecm._query_df(f"""
        SELECT ts_code, close, pct_chg, trade_date, amount, open, high, low FROM daily_cache
        WHERE (ts_code, trade_date) IN (
            SELECT ts_code, MAX(trade_date) FROM daily_cache
            WHERE ts_code IN ({ph}) GROUP BY ts_code
        )
    """, codes)

    # 3. 最新基本面
    basic_df = _ecm._query_df(f"""
        SELECT ts_code, total_mv, pe, pb, turnover_rate, circ_mv FROM daily_basic_cache
        WHERE (ts_code, trade_date) IN (
            SELECT ts_code, MAX(trade_date) FROM daily_basic_cache
            WHERE ts_code IN ({ph}) GROUP BY ts_code
        )
    """, codes)

    # 4. L2 标签（平铺：每只一行，每标签一列）
    # 修复 2026-08-04：原 MAX(CASE...) 取历史累积行的最大/字典序最大（如 fina_health 取到旧
    # suspicious、sentiment_phase 取到旧 recovery），改为先取每 (ts_code, tag_name) 最新一行再平铺
    tags_df = _ecm._query_df(f"""
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

    # 5b. 成品仓 status_snapshot（336号 S2.5：快照字段来源切 L1/L2 输出——
    #     consensus_rate/conflict/opportunity_state/state_evidence 读 status_engine 成品，
    #     消除 tags 轻量投票口径；status_snapshot 由管道 S1 先行构建）
    status_map: dict = {}
    try:
        _ss_df = _ecm._query_df(
            "SELECT ts_code, consensus_rate, conflict_evidence, opportunity_state, state_evidence"
            " FROM status_snapshot")
        if _ss_df is not None and not _ss_df.empty:
            status_map = {r['ts_code']: r.to_dict() for _, r in _ss_df.iterrows()}
    except Exception as e:
        logger.warning(f"status_snapshot 读取失败（快照字段回退 tags 口径）: {e}")

    # 6. 原子表替换写入
    NEW_TABLE = 'treemap_snapshot_new'
    # 建新表（结构与目标表一致）
    _ecm.conn.execute(f"DROP TABLE IF EXISTS {NEW_TABLE}")
    _ecm.conn.execute(f"""
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
            _ecm.conn.execute(f"""
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
    _ecm.conn.commit()

    # 346号：原子替换前归档 treemap 历史快照（ts_code+snapshot_date 复合主键幂等）
    try:
        _ecm.conn.execute("""
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
        _ecm.conn.execute("""
            INSERT OR REPLACE INTO treemap_snapshot_history
                SELECT ts_code, snapshot_date, name, industry,
                close, pct_chg, total_mv, trade_date,
                open, high, low, amplitude, pe, pb,
                amount, turnover_rate, circ_mv, signal_strength,
                valuation_level, valuation_deviation, main_force_phase,
                phase_confidence, sentiment_phase, sector_heat,
                fina_health, opportunity_type, trend_alignment,
                price_position, fund_flow, capital_nature,
                chip_concentration, volatility_level, dividend_yield,
                composite_rating, opportunity_label, evidence_count,
                right_side_confirm, confirm_evidence, opportunity_profile,
                entry_signals, exit_conditions, consensus_rate,
                conflict, main_force_presence, presence_evidence,
                opportunity_state, state_evidence
                FROM treemap_snapshot
        """)
        _ecm.conn.commit()
        # B7修复：同步 treemap_snapshot_history 到分库 snapshot_cache.db
        try:
            from app.data.sharding_manager import sharding_manager
            shard_db = sharding_manager.get_db_for_table('treemap_snapshot_history')
            if shard_db:
                shard_conn = sharding_manager.get_connection(shard_db)
                # 确保分库表存在
                shard_conn.execute("""
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
                # 从主库读取数据写入分库
                rows = _ecm.conn.execute("SELECT * FROM treemap_snapshot_history").fetchall()
                if rows:
                    cols = 'ts_code,snapshot_date,name,industry,close,pct_chg,total_mv,trade_date,open,high,low,amplitude,pe,pb,amount,turnover_rate,circ_mv,signal_strength,valuation_level,valuation_deviation,main_force_phase,phase_confidence,sentiment_phase,sector_heat,fina_health,opportunity_type,trend_alignment,price_position,fund_flow,capital_nature,chip_concentration,volatility_level,dividend_yield,composite_rating,opportunity_label,evidence_count,right_side_confirm,confirm_evidence,opportunity_profile,entry_signals,exit_conditions,consensus_rate,conflict,main_force_presence,presence_evidence,opportunity_state,state_evidence'
                    ph = ','.join(['?' for _ in cols.split(',')])
                    shard_conn.executemany(
                        f"INSERT OR REPLACE INTO treemap_snapshot_history ({cols}) VALUES ({ph})",
                        rows)
                    shard_conn.commit()
                    logger.debug(f"treemap_snapshot_history 分库同步: {len(rows)} 行")
        except Exception as e:
            logger.warning(f"treemap_snapshot_history 分库同步失败: {e}")
    except Exception as e:
        logger.warning(f"treemap_snapshot 历史归档失败: {e}")

    # 原子切换
    _ecm.conn.execute("DROP TABLE IF EXISTS treemap_snapshot")
    _ecm.conn.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO treemap_snapshot")
    _ecm.conn.commit()

    elapsed = time.time() - t0
    logger.info(f"treemap_snapshot 构建完成: {written}/{len(codes)} 只, 耗时 {elapsed:.1f}s")


def _build_status_snapshot(codes: list[str]):
    """337号 §3/§4：日频现状成品生成（S2 status_engine → status_snapshot 表）

    全市场结构化落库（九维状态/状态条/opportunity_state/conflict/共识），
    与 treemap_snapshot 同管道、原子表替换。
    """
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
            _row = _ecm.read_conn.execute(
                "SELECT MAX(trade_date) FROM daily_cache").fetchone()
            trade_date = _row[0] if _row else ''
        except Exception:
            pass

        _NEW = 'status_snapshot_new'
        _ecm.conn.execute(f"DROP TABLE IF EXISTS {_NEW}")
        _ecm.conn.execute(f"""
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
        from app.opportunity_atlas.status_engine import generate_summary_text
        from app.opportunity_atlas.status_engine import build_seven_dim_report
        from app.opportunity_atlas.dimensions.shared_support_resistance import calc_support_resistance
        for code in codes:
            try:
                row = engine.evaluate(code)
                if not row:
                    continue
                # 366号步骤2：计算geo参数并传入build_seven_dim_report
                geo = {}
                try:
                    df = _ecm.get_cached_daily(code)
                    if df is not None and not df.empty:
                        geo = calc_support_resistance(df) or {}
                except Exception:
                    pass
                # 364a Phase 1：生成summary_text和one_liner_detail
                summary_text = generate_summary_text(row)
                one_liner = build_seven_dim_report(row, geo=geo)
                one_liner_json = json.dumps(one_liner, ensure_ascii=False)
                _ecm.conn.execute(
                    f"INSERT OR REPLACE INTO {_NEW} (ts_code, snapshot_date, trade_date,"
                    f" dim_states, status_bar, opportunity_state, state_evidence,"
                    f" conflict_evidence, consensus_rate, direction, l0, lifecycle, advice_params,"
                    f" summary_text, one_liner_detail, dim_engine_results)"
                    f" VALUES (?, date('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [code, trade_date, row['dim_states'], row['status_bar'],
                     row['opportunity_state'], row['state_evidence'],
                     row['conflict_evidence'], row['consensus_rate'],
                     row['direction'], row['l0'], row['lifecycle'], row['advice_params'],
                     summary_text, one_liner_json,
                     row.get('dim_engine_results')])
                written += 1
            except Exception as e:
                logger.warning(f"status_snapshot {code} 生成失败: {e}")
        _ecm.conn.commit()
        # 346号：原子替换前归档历史快照（多交易日保留，342号 §6.2 / G3.3 依赖）
        # 将当前 status_snapshot 数据追加到 status_snapshot_history（ts_code+snapshot_date
        # 复合主键，同一日重复构建幂等覆盖）。
        try:
            _ecm.conn.execute("""
                CREATE TABLE IF NOT EXISTS status_snapshot_history (
                    ts_code TEXT, snapshot_date TEXT, trade_date TEXT,
                    dim_states TEXT, status_bar TEXT, opportunity_state TEXT,
                    state_evidence TEXT, conflict_evidence TEXT, consensus_rate REAL,
                    direction TEXT, l0 TEXT, lifecycle TEXT, advice_params TEXT,
                    PRIMARY KEY (ts_code, snapshot_date)
                )
            """)
            _ecm.conn.execute("""
                INSERT OR REPLACE INTO status_snapshot_history
                    (ts_code, snapshot_date, trade_date, dim_states, status_bar,
                     opportunity_state, state_evidence, conflict_evidence, consensus_rate,
                     direction, l0, lifecycle, advice_params)
                SELECT ts_code, snapshot_date, trade_date, dim_states, status_bar,
                       opportunity_state, state_evidence, conflict_evidence, consensus_rate,
                       direction, l0, lifecycle, advice_params
                FROM status_snapshot
            """)
            _ecm.conn.commit()
            # B7修复：同步 status_snapshot_history 到分库 snapshot_cache.db
            try:
                from app.data.sharding_manager import sharding_manager
                shard_db = sharding_manager.get_db_for_table('status_snapshot_history')
                if shard_db:
                    shard_conn = sharding_manager.get_connection(shard_db)
                    shard_conn.execute("""
                        CREATE TABLE IF NOT EXISTS status_snapshot_history (
                            ts_code TEXT, snapshot_date TEXT, trade_date TEXT,
                            dim_states TEXT, status_bar TEXT, opportunity_state TEXT,
                            state_evidence TEXT, conflict_evidence TEXT, consensus_rate REAL,
                            direction TEXT, l0 TEXT, lifecycle TEXT, advice_params TEXT,
                            PRIMARY KEY (ts_code, snapshot_date)
                        )
                    """)
                    rows = _ecm.conn.execute("SELECT * FROM status_snapshot_history").fetchall()
                    if rows:
                        cols = 'ts_code,snapshot_date,trade_date,dim_states,status_bar,opportunity_state,state_evidence,conflict_evidence,consensus_rate,direction,l0,lifecycle,advice_params'
                        ph = ','.join(['?' for _ in cols.split(',')])
                        shard_conn.executemany(
                            f"INSERT OR REPLACE INTO status_snapshot_history ({cols}) VALUES ({ph})",
                            rows)
                        shard_conn.commit()
                        logger.debug(f"status_snapshot_history 分库同步: {len(rows)} 行")
            except Exception as e:
                logger.warning(f"status_snapshot_history 分库同步失败: {e}")
        except Exception as e:
            logger.warning(f"status_snapshot 历史归档失败: {e}")
        _ecm.conn.execute("DROP TABLE IF EXISTS status_snapshot")
        _ecm.conn.execute(f"ALTER TABLE {_NEW} RENAME TO status_snapshot")
        logger.info(f"status_snapshot 构建完成: {written}/{len(codes)} 只, 耗时 {time.time()-t0:.1f}s")


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
            "WHERE pipeline_date=? AND step_id IN ('COL-1','COL-2','COL-3','COL-4','COL-5','COL-6',"
            "'RAW-1','RAW-2','RAW-3','SIG','OUT') AND status='done'",
            [pipeline_date]
        ).fetchone()
        return row and row[0] >= 11  # 11 个环节全 done
    except Exception:
        return False


def _all_steps_done(status: dict, step_ids: list[str]) -> bool:
    return all(status.get(s, {}).get('status') == 'done' for s in step_ids)


def _is_precompute_in_progress() -> bool:
    """P2/P4/S1 重算是否进行中（P2 写锁死锁根治，2026-08-16）

    重算期间（pending/running 未完成）跳过完整性检查等批量写操作，
    避免与 P2 compute_batch 4 worker 的写锁竞争。
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
    processed = 0
    MAX_PER_TICK = 50  # 每tick最多处理50条，避免阻塞管道
    for req in pending:
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
            elif req['task_type'] == 'stk_holder':
                _batch_stk_holder()
            elif req['task_type'] == 'finance_report':
                _batch_finance_report()
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
        if processed >= MAX_PER_TICK:
            logger.info(f"  sync_requests 本轮处理 {processed} 条，剩余下轮继续")
            break


def _recover_stale_running(timeout_hours: float = 4.0) -> int:
    """清理超时 running 残留，防止管道永久阻塞（327阶段1）

    daemon 重启/崩溃后，旧 running 记录无法被 mark_step_running 重置
    （仅接受 pending/failed→running），导致 P4/S1 永不触发、快照陈旧。
    将超过 timeout_hours 未完成的 running 统一重置为 pending，让管道自愈。

    Returns: 重置的环节数
    """
    try:
        rc = _ecm.conn.execute(
            "UPDATE pipeline_status SET status='pending', detail='stale running 重置' "
            "WHERE status='running' AND started_at < datetime('now', ?)",
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
    """
    try:
        row = _ecm.conn.execute(
            "SELECT trade_date FROM daily_cache "
            "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if row:
            return str(row[0])
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
                "UPDATE pipeline_status SET status='done', completed_at=CURRENT_TIMESTAMP, "
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
        return

    # ── 原料数据加工阶段 RAW-1(IND) → RAW-2(FEAT) → RAW-3(FAC) ──
    codes = _get_active_codes(today_fmt)
    if not codes:
        return

    # 353号总纲：RAW-1(IND) → RAW-2(FEAT) → RAW-3(FAC)
    RAW_STEPS = ['RAW-1', 'RAW-2', 'RAW-3']
    for sid, func in [
        ('RAW-1', lambda: _precompute_indicators(codes)),
        ('RAW-2', lambda: _precompute_raw_features(codes)),
        ('RAW-3', lambda: _precompute_preset_combos(codes)),
    ]:
        if status.get(sid, {}).get('status') in ('done', 'running'):
            continue
        _run_pipeline_step(today, sid, func, None)
        return

    if _has_failed(status, RAW_STEPS):
        for sid in RAW_STEPS:
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

    if not _all_steps_done(status, RAW_STEPS):
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

    # ── 成品仓阶段 OUT ──
    if status.get('OUT', {}).get('status') != 'done':
        def _out_build(_codes):
            _build_status_snapshot(_codes)
            _build_treemap_snapshot(_codes)
        _run_pipeline_step(today, 'OUT', _out_build, codes)
        return

    logger.info(f"  [管道] 今日全链路完成 ✅")


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
        detail = f"OK ({time.time() - t0:.1f}s)"
        _ecm.mark_step_done(pipeline_date, step_id, detail)
        logger.info(f"  [管道] {step_id} → done ({detail})")
    except Exception as e:
        detail = f"ERROR: {e} ({time.time() - t0:.1f}s)"
        _ecm.mark_step_failed(pipeline_date, step_id, detail)
        logger.warning(f"  [管道] {step_id} → failed ({detail})")


def _precompute_indicators(codes):
    """包装原有的指标预计算逻辑（P1）"""
    _ensure_pd()
    from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
    mgr = PrecomputeIndicatorManager(_ecm)
    ok = 0
    for code in codes:
        try:
            df = _ecm.get_cached_daily(code)
            if df is not None and len(df) >= 30 and mgr.precompute_all_indicators(code, df):
                ok += 1
        except Exception:
            pass
    logger.info(f"指标预计算完成: {ok}/{len(codes)} 只")


def _precompute_strategy_signals(codes):
    """包装原有的策略信号预计算逻辑（P2）"""
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
        import json as _json
        rows = []
        for ts_code, result in results.items():
            try:
                rd = result.to_dict()
                rows.append((ts_code, rd.get('trade_date', datetime.now().strftime('%Y-%m-%d')),
                             _json.dumps(rd, ensure_ascii=False, default=str), 1))
            except Exception:
                continue
        _batch_write_signal_detail(rows)
        count = len(rows)
        logger.info(f"策略信号预计算完成: {count}/{len(codes)} 只")
        if count == 0 and codes:
            logger.info("策略信号全部失败，回退到因子信号写入...")
            _write_factor_signals(codes)
    except Exception as e:
        logger.warning(f"策略信号预计算整体失败: {e}")
        _write_factor_signals(codes)


def _batch_write_signal_detail(rows):
    """批量写 strategy_signal_detail（P2 写锁死锁根治，2026-08-16）

    用独立短连接一次性 executemany + commit：与 daemon 主循环的共享写连接解耦，
    单次批量事务替代逐只 INSERT，避免 4 worker × 5571 次短事务在 SQLite 写锁
    上的锁链死锁。短 busy_timeout（10s）防极端长事务阻塞；失败静默降级
    （P4 完整性检查会兜底补写）。
    """
    if not rows:
        return
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(_ecm.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.executemany(
            "INSERT OR REPLACE INTO strategy_signal_detail "
            "(ts_code, trade_date, signal_json, schema_version, cached_at) "
            "VALUES (?, ?, ?, ?, datetime('now','localtime'))",
            rows
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"批量写 strategy_signal_detail 失败: {e}")


def _prewarm_weekly_cache(codes):
    """批量预热周线缓存（从 daily_cache 聚合 freq='W'，零数据源直调）

    P2 缠论 long 周期需要周线；日线聚合成本低（~82s/全市场），
    只补缺失股票（已有缓存跳过），增量维护。
    """
    import sqlite3 as _sqlite3
    import pandas as _pd
    _ensure_pd()
    # 找出缺周线缓存的股票
    rows = _ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE freq='W'"
    ).fetchall()
    cached_set = {r[0] for r in rows}
    missing = [c for c in codes if c not in cached_set]
    if not missing:
        return
    logger.info(f"  周线缓存预热: 缺 {len(missing)} 只，从日线聚合...")
    db_path = _ecm.db_path
    con = _sqlite3.connect(db_path)
    try:
        # 分批（每批 500 只）拉日线聚合，避免单次查询过大
        for i in range(0, len(missing), 500):
            batch = missing[i:i+500]
            ph = ','.join('?' for _ in batch)
            df = _pd.read_sql(
                f"SELECT ts_code, trade_date, open, high, low, close, vol, amount "
                f"FROM daily_cache WHERE ts_code IN ({ph}) ORDER BY ts_code, trade_date",
                con, params=batch
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
    finally:
        con.close()



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
            minute_stocks = set(r[0] for r in _ecm.conn.execute(
                "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE trade_date=?",
                [trade_date_fmt]
            ).fetchall())
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

    # D1: 旧 indicator_cache EAV 表已于 2026-07-19 停止写入，清理逻辑已移除

    try:
        _ecm.clean_factor_cache(one_year_ago)
    except Exception as e:
        logger.warning(f"清理 factor_cache 失败: {e}")

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

# _is_market_day 在管道驱动模块中已定义（305号§9）


def _is_market_hours() -> bool:
    """是否为交易时段（9:00-15:30）"""
    h = datetime.now().hour
    return 9 <= h <= 15


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
        cnt = _ecm.conn.execute(
            "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [today_fmt]
        ).fetchone()[0]
        if cnt >= 5000:
            logger.info(f"  [日终兜底] 今日日终同步已完成（日线{cnt}行），跳过")
            return
        logger.info(f"  [日终兜底] 检测到今日日终同步未执行（日线{cnt}行），触发补采...")
        run_daily_sync()
    except Exception as e:
        logger.warning(f"  [日终兜底] 自检失败: {e}")


def main():
    global _ecm, _running, _cleanup_done

    logger.info("data_daemon 启动")
    logger.info(f"DATA_DIR={os.environ.get('DATA_DIR')}")

    # 初始化 ECM——统一走全局单例（get_ecm_instance）
    # 修复 2026-08-15：原 main 直接构造 EnhancedCacheManager() 与采集器/其他模块的
    # get_ecm_instance() 单例并存（双实例、各自 _write_lock 不互斥）→ 并发写同库
    # 触发 SQLite 写锁（实测全天 831 次 "database is locked"；双连接并发写复现 100% 失败）
    from app.data.enhanced_cache_manager import get_ecm_instance
    _ecm = get_ecm_instance()
    logger.info("ECM 就绪（全局单例）")

    # 356号方案：初始化分库管理器（指向正确的 data 目录）
    from app.data.sharding_manager import init_sharding
    init_sharding(os.environ.get('DATA_DIR', 'data'))
    logger.info("分库管理器就绪")

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
    run_integrity_check(backfill_days=3)

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
    _last_session = None  # 355号方案规则11：时段切换跟踪

    logger.info("data_daemon 进入主循环（管道驱动）")
    while _running:
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
                _ecm.wal_checkpoint('PASSIVE')
                _last_ckpt = ts
            except Exception as e:
                logger.warning(f"WAL checkpoint 失败: {e}")

        # ── WAL 阈值告警（2026-08-12 328号 L3）──
        # WAL 超过 2GB 提示膨胀（自动 checkpoint 被读阻塞时只增不减）；
        # 非交易时段 + 管道空闲时提示执行收缩（backend/wal_maintenance.py）。
        if not _is_market_hours():
            try:
                _wal_mb = os.path.getsize(
                    os.path.join(
                        os.environ.get('DATA_DIR', 'data'), 'duckdb', 'stock_cache.db-wal'
                    )
                ) / 1024 / 1024

                # 356号方案：集成监控告警
                try:
                    from app.data.monitor import monitor
                    monitor.record_metric('wal_size_mb', _wal_mb)
                    if _wal_mb > 2048:
                        monitor.create_alert(
                            'WARNING',
                            'WAL文件过大',
                            f'WAL文件大小 {_wal_mb:.0f}MB 超过阈值 2GB',
                            source='wal_monitor',
                            metrics={'wal_size_mb': _wal_mb}
                        )
                except Exception:
                    pass

                if _wal_mb > 2048:
                    logger.warning(
                        f"WAL 达 {_wal_mb:.0f}MB（>2GB）——建议执行收缩: "
                        f"python backend/wal_maintenance.py --once"
                    )
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

        # ── 数据清理（日终完成后触发一次，305号§9兼容） ──
        if _is_pipeline_complete(datetime.now().strftime('%Y%m%d')):
            if not _cleanup_done:
                try:
                    _run_data_cleanup()
                    _cleanup_done = True
                except Exception as e:
                    logger.warning(f"数据清理异常: {e}")

        # ── 定时巡检（每整点，非交易时段，不变） ──
        if now.minute == 0 and (now.hour < 9 or now.hour >= 16):
            if ts - _last_patrol > 1800:
                _last_patrol = ts
                if _is_market_day():
                    # 2026-08-16 修复（P2 写锁死锁根治）：P2/P4/S1 重算期间
                    # 跳过完整性检查——run_integrity_check 批量补采写库（长事务）
                    # 与 P2 compute_batch 4 worker 的写锁竞争（lldb 实证 4 线程
                    # PyThread_acquire_lock_timed 锁链死锁 + strategy_signal_detail
                    # 零写入）。重算完成（S1 done）后恢复完整性检查。
                    if _is_precompute_in_progress():
                        logger.info("定时巡检：预计算进行中，跳过完整性检查（避免写锁竞争）")
                    else:
                        logger.info("定时巡检...")
                        run_integrity_check(backfill_days=1)

        time.sleep(30)

    # 清理
    _stop_collectors()
    logger.info("data_daemon 已停止")


if __name__ == '__main__':
    main()
