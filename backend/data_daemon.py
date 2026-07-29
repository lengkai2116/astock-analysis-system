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
            logger.info("MootdxCollector 已启动（快照:东财HTTP, 分钟:mootdx）")
        else:
            logger.warning("MootdxCollector 启动失败（降级模式不可用）")
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

    # 申万一级行业指数（31个）
    sw_codes = [
        '801010.SI','801020.SI','801030.SI','801040.SI','801050.SI',
        '801080.SI','801110.SI','801120.SI','801130.SI','801140.SI',
        '801150.SI','801160.SI','801170.SI','801180.SI','801200.SI',
        '801210.SI','801230.SI','801710.SI','801720.SI','801730.SI',
        '801740.SI','801750.SI','801760.SI','801770.SI','801780.SI',
        '801790.SI','801880.SI','801890.SI',
    ]
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
    """全市场融资融券个股明细 — 1 次 API 调用"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    raw = _ts(pro.margin_detail, trade_date=trade_date)
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
    """全市场财务指标 — 后台低优任务"""
    _ensure_pd()
    import tushare as ts
    pro = ts.pro_api()
    total = 0
    try:
        # Tushare fina_indicator 可指定 period 获取最近一期
        df = _ts(pro.fina_indicator, period=trade_date)
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
        ('concept_cache',   _batch_concept,     0,               '概念'),
    ]

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

    # ── 4 类后台低优数据检查（空表时触发补采，非每日必须）──
    batch_background = [
        ('adj_factor_cache',    _batch_adj_factor,    '复权因子'),
        ('top10_holders_cache', _batch_top10_holders, '前十大股东'),
        ('stk_holder_cache',    _batch_stk_holder,    '股东人数'),
        ('finance_report_cache', _batch_finance_report, '扩展财务'),
    ]
    for table, batch_fn, label in batch_background:
        try:
            cnt = _ecm.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if cnt == 0:
                logger.info(f"  [{label}] 空表，触发补采...")
                added = batch_fn()
                logger.info(f"    → 补采 {added} 条")
            else:
                logger.info(f"  [{label}] {cnt} 行 ✅")
        except Exception as e:
            logger.warning(f"  [{label}] 检查失败: {e}")

    # 检查今日数据
    for table, batch_fn, threshold, label in checks:
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

    # 申万行业指数完整性检查（31个行业，缺失时回填60日）
    try:
        sw_cnt = _ecm.conn.execute(
            "SELECT COUNT(DISTINCT ts_code) FROM daily_cache WHERE ts_code LIKE '801%.SI'"
        ).fetchone()[0]
        if sw_cnt < 31:
            logger.info(f"  [申万行业指数] 当前 {sw_cnt}/31 个，触发回填...")
            today_str = datetime.now().strftime('%Y%m%d')
            for offset in range(60):
                d = (datetime.now() - timedelta(days=offset))
                if d.weekday() >= 5:
                    continue
                ds = d.strftime('%Y%m%d')
                _batch_index_daily(ds)
            logger.info(f"  [申万行业指数] 回填完成（近60个交易日）")
    except Exception as e:
        logger.warning(f"  申万行业指数检查失败: {e}")

    logger.info("完整性检查完成")
    
    # 自选股分钟数据完整性检查（后台线程，不阻塞主循环）
    try:
        threading.Thread(target=_check_watchlist_minute, daemon=True).start()
    except Exception:
        pass


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

    # 自选股分钟数据闲时补采（后台低优，使用 mootdx 填充历史数据）
    try:
        threading.Thread(target=_run_minute_backfill_v2, daemon=True).start()
        logger.info("  分钟数据闲时补采已触发（后台）")
    except Exception as e:
        logger.warning(f"  分钟数据闲时补采触发失败: {e}")

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
    for code in codes:
        try:
            df = _ecm.get_cached_daily(code)
            if df is None or len(df) < 30:
                continue
            for cn_name, en_name in mapped_factors.items():
                try:
                    fpm.precompute_factor(code, df, en_name)
                except Exception:
                    pass
            precomputed += 1
        except Exception:
            continue
    logger.info(f"因子预计算完成: {precomputed}/{len(codes)} 只")

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

    # ── 策略信号预计算（UnifiedStrategyCore，287号方案 v2.3） ──
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

    # ── 3. PRESET_COMBOS 因子值预计算（写入 factor_cache） ──
    try:
        _precompute_preset_combos(codes)
    except Exception as e:
        logger.warning(f"PRESET_COMBOS 因子预计算失败: {e}")

    # ── 4. L2 标签预计算（机会图谱，294号§三梯队7） ──
    try:
        _precompute_l2_labels(codes)
    except Exception as e:
        logger.warning(f"L2标签预计算失败: {e}")


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

        # 各引擎延迟初始化
        ve = ValuationEngine()
        pd_engine = PhaseDetectionEngine()
        ms = MarketSentimentService()
        sr = SectorRotationModel()
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
                if limit_up > 80:
                    _sentiment_phase_global = 'climax'
                elif limit_up > 30:
                    _sentiment_phase_global = 'recovery'
                elif limit_up < 10 and limit_down > 20:
                    _sentiment_phase_global = 'ebb'
                elif limit_up < 5:
                    _sentiment_phase_global = 'ice'
                else:
                    _sentiment_phase_global = 'recovery'
        except Exception:
            pass

        t0 = time.time()
        succeeded = 0
        commit_count = 0
        BATCH_SIZE = 500

        for code in codes:
            try:
                tags = {}

                # 1. 估值引擎产出（P0.1）— 只需要 ts_code
                try:
                    v_tags = ve.compute_tags(code)
                    if v_tags:
                        tags.update(v_tags)
                except Exception:
                    pass

                # 2. 阶段判定引擎产出（P0.2）— 使用预加载的日线数据
                df = all_data.get(code)
                if df is not None and len(df) >= 30:
                    try:
                        p_tags = pd_engine.compute_tags(code, df)
                        if p_tags:
                            tags.update(p_tags)
                    except Exception:
                        pass

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
                        vp_tags = vps.get_tags(df)
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

                    # 5. 聚合衍生 → signal_strength
                try:
                    tags['signal_strength'] = _compute_signal_strength(tags)
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

                # 6. 写入数据库
                if len(tags) > 0:
                    _ecm.write_tags(code, tags)
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
        logger.info(f"L2标签预计算完成: {succeeded}/{len(codes)} 只, 耗时 {elapsed:.1f}s")


def _add_vp_simple_tags(df, tags):
    """计算简单量价标签：ma_alignment / volume_price_fit / volatility_level / gap_type / breakout_attempts"""
    closes = df['close'].values
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
            if price_trend > 0.02 and vol_trend > 0.1:
                tags['volume_price_fit'] = 'healthy'  # 放量上涨
            elif price_trend < -0.02 and vol_trend < -0.1:
                tags['volume_price_fit'] = 'healthy'  # 缩量下跌
            elif price_trend > 0.02 and vol_trend < -0.1:
                tags['volume_price_fit'] = 'diverging'  # 缩量上涨(背离)
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

        # pattern_signal: 简单的K线形态检测（替代 KlinePatternAdapter，因依赖 Flask）
        if len(closes) >= 5:
            # 双底形态：最近5日形成两次探底
            recent_low = np.min(lows[-5:])
            recent_high = np.max(highs[-5:])
            mid = (recent_low + recent_high) / 2
            dips = sum(1 for i in range(-5, 0) if abs(lows[i] - recent_low) / max(recent_low, 1) < 0.01)
            if dips >= 2 and closes[-1] > mid:
                tags['pattern_signal'] = 'double_bottom'
            # 突破形态：价格突破近期高点
            elif len(closes) >= 20 and closes[-1] > np.max(highs[-20:-1]) * 1.02:
                tags['pattern_signal'] = 'breakout'
            else:
                tags['pattern_signal'] = 'none'


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


def _compute_signal_strength(tags: dict) -> float:
    """计算 signal_strength 衍生标签（不含 catalyst_event 维度）

    计算公式：
      基础分 0-10:
        main_force_phase=building→7.0, washing→5.5, lifting→6.0,
                          distributing→2.0, unknown→3.0
        + valuation_level=extreme_low→+1.5, low→+1.0, fair→0.0, high→-1.0, extreme_high→-2.0
        + trend_alignment=up_aligned→+1.0, down_aligned→-1.0
      ⇒ 范围控制在 0-10

      置信度调整 ×0.8~×1.0:
        phase_confidence < 0.6 → ×0.8, 0.6-0.8 → ×0.9, > 0.8 → ×1.0

      环境调整 ×0.7~×1.0:
        sentiment_phase=ebb→×0.7, climax→×0.85, recovery→×1.0, ice→×0.9

    ⚠ 不含 catalyst_event 维度（P2.1 未就绪）
    """
    # 基础分
    base = 3.0  # 默认

    mfp = str(tags.get('main_force_phase', 'unknown'))
    phase_map = {'building': 7.0, 'washing': 5.5, 'lifting': 6.0,
                 'distributing': 2.0, 'unknown': 3.0}
    base = phase_map.get(mfp, 3.0)

    # 估值调整
    vl = str(tags.get('valuation_level', 'fair'))
    val_map = {'extreme_low': 1.5, 'low': 1.0, 'fair': 0.0,
               'high': -1.0, 'extreme_high': -2.0}
    base += val_map.get(vl, 0.0)

    # 趋势调整（使用 trend_alignment，与295号标签体系一致）
    ta = str(tags.get('trend_alignment', 'no_trend'))
    trend_map = {'up_aligned': 1.0, 'down_aligned': -1.0, 'mixed': 0.0, 'no_trend': 0.0}
    base += trend_map.get(ta, 0.0)

    base = max(0.0, min(10.0, base))

    # 置信度调整
    pc = tags.get('phase_confidence')
    confidence_factor = 1.0
    if pc is not None:
        try:
            pc_f = float(pc)
            if pc_f < 0.6:
                confidence_factor = 0.8
            elif pc_f < 0.8:
                confidence_factor = 0.9
        except (ValueError, TypeError):
            pass

    # 环境调整
    sp = str(tags.get('sentiment_phase', ''))
    env_map = {'ebb': 0.7, 'climax': 0.85, 'recovery': 1.0, 'ice': 0.9}
    env_factor = env_map.get(sp, 1.0)

    strength = base * confidence_factor * env_factor
    return round(max(0.0, min(10.0, strength)), 1)


def _compute_style_exposure(ts_code: str, tags: dict, df: 'pd.DataFrame' = None) -> str:
    """计算 style_exposure 标签（295号§3.2 标签12）
    
    基于行业分类和市值判定风格归属：
    - 金融/银行 → large_value
    - 科技/高研发 → large_growth（如果大市值）或 small_growth
    - 周期行业 → small_value（如果小市值）或 large_value
    """
    vl = tags.get('valuation_level', 'fair')
    sector = tags.get('sector_heat', 'none')
    
    # 简单的行业风格映射
    try:
        from app.data import DataManager
        dm = DataManager()
        industry = dm.get_stock_industry(ts_code)
    except Exception:
        industry = None

    if not industry:
        return 'none'

    is_large = sector in ('top_10', 'top_20')
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


def _build_treemap_snapshot(codes: list[str]):
    """日终预计算完成后，构建 treemap_snapshot 快照表（S1 管道环节）

    从 daily_cache / daily_basic_cache / opportunity_tags_cache 提取最新数据，
    平铺写入 treemap_snapshot 表（4800 行 × ~25 列 ≈ 2-3 MB）。
    使用原子表替换避免读写不一致。
    """
    t0 = time.time()
    logger.info(f"构建 treemap_snapshot 快照: {len(codes)} 只...")

    if not codes:
        logger.info("  无活跃股票，跳过快照构建")
        return

    # 1. 元数据（名称 + 行业）
    from app.data import DataManager
    dm = DataManager()
    meta = dm.get_stock_meta_batch(codes)
    if not meta:
        logger.warning("  元数据为空，跳过快照构建")
        return

    # 2. 最新日线（每只最新一条，用子查询避免全表扫描）
    ph = ','.join('?' for _ in codes)
    daily_df = _ecm._query_df(f"""
        SELECT ts_code, close, pct_chg, trade_date FROM daily_cache
        WHERE (ts_code, trade_date) IN (
            SELECT ts_code, MAX(trade_date) FROM daily_cache
            WHERE ts_code IN ({ph}) GROUP BY ts_code
        )
    """, codes)

    # 3. 最新基本面
    basic_df = _ecm._query_df(f"""
        SELECT ts_code, total_mv FROM daily_basic_cache
        WHERE (ts_code, trade_date) IN (
            SELECT ts_code, MAX(trade_date) FROM daily_basic_cache
            WHERE ts_code IN ({ph}) GROUP BY ts_code
        )
    """, codes)

    # 4. L2 标签（平铺：每只一行，每标签一列）
    tags_df = _ecm._query_df(f"""
        SELECT ts_code,
               MAX(CASE WHEN tag_name='signal_strength'     THEN tag_value END) as signal_strength,
               MAX(CASE WHEN tag_name='valuation_level'     THEN tag_value END) as valuation_level,
               MAX(CASE WHEN tag_name='valuation_deviation' THEN tag_value END) as valuation_deviation,
               MAX(CASE WHEN tag_name='main_force_phase'    THEN tag_value END) as main_force_phase,
               MAX(CASE WHEN tag_name='phase_confidence'    THEN tag_value END) as phase_confidence,
               MAX(CASE WHEN tag_name='sentiment_phase'     THEN tag_value END) as sentiment_phase,
               MAX(CASE WHEN tag_name='sector_heat'         THEN tag_value END) as sector_heat,
               MAX(CASE WHEN tag_name='fina_health'         THEN tag_value END) as fina_health,
               MAX(CASE WHEN tag_name='hold_period'         THEN tag_value END) as hold_period,
               MAX(CASE WHEN tag_name='trend_alignment'     THEN tag_value END) as trend_alignment,
               MAX(CASE WHEN tag_name='price_position'      THEN tag_value END) as price_position,
               MAX(CASE WHEN tag_name='fund_flow'           THEN tag_value END) as fund_flow,
               MAX(CASE WHEN tag_name='capital_nature'      THEN tag_value END) as capital_nature,
               MAX(CASE WHEN tag_name='chip_concentration'  THEN tag_value END) as chip_concentration,
               MAX(CASE WHEN tag_name='volatility_level'    THEN tag_value END) as volatility_level,
               MAX(CASE WHEN tag_name='dividend_yield'      THEN tag_value END) as dividend_yield,
               MAX(CASE WHEN tag_name='composite_rating'    THEN tag_value END) as composite_rating
        FROM opportunity_tags_cache
        WHERE ts_code IN ({ph})
        GROUP BY ts_code
    """, codes)

    # 5. 构建行数据字典
    daily_map = {r['ts_code']: r for _, r in daily_df.iterrows()} if not daily_df.empty else {}
    basic_map = {r['ts_code']: r for _, r in basic_df.iterrows()} if not basic_df.empty else {}
    tags_map = {r['ts_code']: r for _, r in tags_df.iterrows()} if not tags_df.empty else {}

    # 6. 原子表替换写入
    NEW_TABLE = 'treemap_snapshot_new'
    # 建新表（结构与目标表一致）
    _ecm.conn.execute(f"DROP TABLE IF EXISTS {NEW_TABLE}")
    _ecm.conn.execute(f"""
        CREATE TABLE {NEW_TABLE} (
            ts_code TEXT PRIMARY KEY, name TEXT, industry TEXT,
            close REAL, pct_chg REAL, total_mv REAL, trade_date TEXT,
            signal_strength REAL, valuation_level TEXT, valuation_deviation REAL,
            main_force_phase TEXT, phase_confidence REAL,
            sentiment_phase TEXT, sector_heat TEXT, fina_health TEXT,
            hold_period TEXT, trend_alignment TEXT, price_position TEXT,
            fund_flow TEXT, capital_nature TEXT, chip_concentration TEXT,
            volatility_level TEXT, dividend_yield REAL, composite_rating REAL,
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
                 signal_strength, valuation_level, valuation_deviation, main_force_phase,
                 phase_confidence, sentiment_phase, sector_heat, fina_health, hold_period,
                 trend_alignment, price_position, fund_flow, capital_nature,
                 chip_concentration, volatility_level, dividend_yield, composite_rating)
                VALUES (?,?,?,?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?)
            """, (
                code, m.get('name', ''), m.get('industry', ''),
                float(d['close']) if pd.notna(d.get('close')) else None,
                float(d['pct_chg']) if pd.notna(d.get('pct_chg')) else None,
                float(b['total_mv']) if pd.notna(b.get('total_mv')) else None,
                str(d['trade_date']) if pd.notna(d.get('trade_date')) else None,
                _safe_float(t.get('signal_strength')),
                t.get('valuation_level'), _safe_float(t.get('valuation_deviation')),
                t.get('main_force_phase'), _safe_float(t.get('phase_confidence')),
                t.get('sentiment_phase'), t.get('sector_heat'),
                t.get('fina_health'), t.get('hold_period'),
                t.get('trend_alignment'), t.get('price_position'),
                t.get('fund_flow'), t.get('capital_nature'),
                t.get('chip_concentration'), t.get('volatility_level'),
                _safe_float(t.get('dividend_yield')),
                _safe_float(t.get('composite_rating')),
            ))
            written += 1
        except Exception:
            continue
    _ecm.conn.commit()

    # 原子切换
    _ecm.conn.execute("DROP TABLE IF EXISTS treemap_snapshot")
    _ecm.conn.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO treemap_snapshot")
    _ecm.conn.commit()

    elapsed = time.time() - t0
    logger.info(f"treemap_snapshot 构建完成: {written}/{len(codes)} 只, 耗时 {elapsed:.1f}s")


def _safe_float(v):
    if v is None or v == '' or v == 'None':
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ══════════════════════════════════════════════════════════
# 管道驱动（305号§9，取代定时窗口）
# ══════════════════════════════════════════════════════════

def _is_market_day() -> bool:
    return datetime.now().weekday() < 5


def _is_pipeline_complete(pipeline_date: str) -> bool:
    """检查当日管道是否已全部完成"""
    try:
        row = _ecm.conn.execute(
            "SELECT COUNT(*) FROM pipeline_status "
            "WHERE pipeline_date=? AND step_id IN ('C1','C2','C3','C4','C5','C6',"
            "'P1','P2','P3','P4','S1') AND status='done'",
            [pipeline_date]
        ).fetchone()
        return row and row[0] >= 11  # 11 个环节全 done
    except Exception:
        return False


def _all_steps_done(status: dict, step_ids: list[str]) -> bool:
    return all(status.get(s, {}).get('status') == 'done' for s in step_ids)


def _has_failed(status: dict, step_ids: list[str]) -> bool:
    return any(status.get(s, {}).get('status') == 'failed' for s in step_ids)


def _drive_pipeline():
    """管道驱动：检查当前状态，推进到下一个可执行的环节

    每 30s tick 由主循环调用一次。每次只推进一个环节。
    """
    today = datetime.now().strftime('%Y%m%d')

    # Guard: 非交易日跳过
    if not _is_market_day():
        return

    # Guard: 今日管道已完成
    if _is_pipeline_complete(today):
        return

    # Guard: 交易日判断（数据驱动，非时间驱动）
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    has_data = _ecm.conn.execute(
        "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [today_fmt]
    ).fetchone()[0] >= 4000
    if not has_data:
        return  # 数据未到达，下一 tick 再检查

    # 确保当日管道环节已初始化
    _ecm.ensure_pipeline_steps(today)
    status = _ecm.load_pipeline_status(today)

    # ── 采集阶段 C1→C6 ──
    COLLECT = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']
    for sid, func, arg in [
        ('C1', _batch_daily, today_fmt),
        ('C2', _batch_daily_basic, today_fmt),
        ('C3', _batch_moneyflow, today_fmt),
        ('C4', _batch_stk_limit, today_fmt),
        ('C5', _batch_lhb, today_fmt),
        ('C6', _batch_concept, None),
    ]:
        if status.get(sid, {}).get('status') in ('done', 'running'):
            continue
        _run_pipeline_step(today, sid, func, arg)
        return  # 每 tick 只推进一个环节

    # C1~C6 有 failed？重试
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

    # 进入 P 阶段：需要 C1~C6 全部 done
    if not _all_steps_done(status, COLLECT):
        return

    # ── 预计算阶段 P1→P4 ──
    codes = _get_active_codes(today_fmt)
    if not codes:
        return

    PRECOMPUTE = ['P1', 'P2', 'P3', 'P4']
    for sid, func in [
        ('P1', lambda: _precompute_indicators(codes)),
        ('P2', lambda: _precompute_strategy_signals(codes)),
        ('P3', lambda: _precompute_preset_combos(codes)),
        ('P4', lambda: _precompute_l2_labels(codes)),
    ]:
        if status.get(sid, {}).get('status') in ('done', 'running'):
            continue
        _run_pipeline_step(today, sid, func, None)
        return

    if _has_failed(status, PRECOMPUTE):
        for sid in PRECOMPUTE:
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

    if not _all_steps_done(status, PRECOMPUTE):
        return

    # ── 快照构建阶段 S1 ──
    if status.get('S1', {}).get('status') != 'done':
        _run_pipeline_step(today, 'S1', lambda: _build_treemap_snapshot(codes), None)
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
        logger.info(f"策略信号预计算完成: {count}/{len(codes)} 只")
        if count == 0 and codes:
            logger.info("策略信号全部失败，回退到因子信号写入...")
            _write_factor_signals(codes)
    except Exception as e:
        logger.warning(f"策略信号预计算整体失败: {e}")
        _write_factor_signals(codes)


def _check_precompute_status(today: str):
    """开机自检：检查当日预计算完整性，按当前时间决策是否需要补算

    决策逻辑：
      - 非交易日 → 跳过
      - 9:30 前  → 跳过（尚未开盘，预计算无意义）
      - 当前 > 15:30 → 全市场检查 strategy_signal_detail → 缺失则全量预计算
      - 9:30~15:30  → 检查自选股 → 缺失的发起增量请求
    """
    from datetime import datetime
    now = datetime.now()
    if now.weekday() >= 5:
        logger.info("  [P6自检] 非交易日，跳过")
        return

    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()

    hour = now.hour
    minute = now.minute

    if hour < 9 or (hour == 9 and minute < 30):
        logger.info("  [P6自检] 盘中前（<9:30），跳过预计算检查")
        return

    # >15:30: 全市场预计算完整性检查
    if hour > 15 or (hour == 15 and minute >= 30):
        logger.info("  [P6自检] 日终后，检查全市场预计算完整性...")
        today_fmt = datetime.now().strftime('%Y-%m-%d')
        try:
            row = ecm.conn.execute(
                "SELECT COUNT(*) FROM strategy_signal_detail WHERE trade_date=?",
                [today_fmt]
            ).fetchone()
            count = row[0] if row else 0
        except Exception:
            count = 0
        need_precompute = (count == 0)
        # 同时检查 L2 标签是否已预计算（opportunity_tags_cache）
        try:
            tag_row = ecm.conn.execute(
                "SELECT COUNT(*) FROM opportunity_tags_cache"
            ).fetchone()
            tag_count = tag_row[0] if tag_row else 0
        except Exception:
            tag_count = 0
        if tag_count == 0:
            logger.info("  [P6自检] opportunity_tags_cache 为空，需触L2标签预计算")
            need_precompute = True
        if need_precompute:
            logger.info(f"  [P6自检] 触发全量预计算")
            _run_precompute()
        else:
            logger.info(f"  [P6自检] 当日已有预计算数据 ({count}只策略信号, {tag_count}条标签) ✅")
        return

    # 9:30~15:30: 检查全市场预计算完整性（含 L2 标签）
    logger.info("  [P6自检] 盘中，检查全市场预计算完整性...")

    # 检查 daily_cache 是否有今日数据（若有则说明是交易日且有数据可算）
    today_fmt = datetime.now().strftime('%Y-%m-%d')
    try:
        has_today_data = ecm.conn.execute(
            "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [today_fmt]
        ).fetchone()[0] > 0
    except Exception:
        has_today_data = False

    need_precompute = False

    if has_today_data:
        # 检查 strategy_signal_detail
        try:
            row = ecm.conn.execute(
                "SELECT COUNT(*) FROM strategy_signal_detail WHERE trade_date=?",
                [today_fmt]
            ).fetchone()
            if row and row[0] == 0:
                need_precompute = True
        except Exception:
            need_precompute = True

        # 检查 opportunity_tags_cache
        if not need_precompute:
            try:
                tag_row = ecm.conn.execute(
                    "SELECT COUNT(*) FROM opportunity_tags_cache"
                ).fetchone()
                if not tag_row or tag_row[0] == 0:
                    need_precompute = True
            except Exception:
                need_precompute = True

    if need_precompute:
        logger.info(f"  [P6自检] 有今日数据但无预计算，触发全量预计算")
        # 后台线程执行，不阻塞启动流程
        threading.Thread(target=_run_precompute, daemon=True).start()
        logger.info("  [P6自检] 全量预计算已在后台启动")
        return

    # 盘中无全量数据或无预计算缺失 → 走自选股增量检查
    logger.info("  [P6自检] 检查盘中自选股增量请求...")
    watchlist_codes = []
    try:
        import sqlite3
        data_dir = os.environ.get('DATA_DIR', '')
        app_db = os.path.join(data_dir, 'app.db') if data_dir else ''
        if app_db and os.path.exists(app_db):
            conn = sqlite3.connect(app_db)
            rows = conn.execute("SELECT ts_code FROM watchlist").fetchall()
            watchlist_codes = [r[0] for r in rows]
            conn.close()
    except Exception:
        watchlist_codes = []
    except Exception:
        watchlist_codes = []

    if not watchlist_codes:
        logger.info("  [P6自检] 无自选股，跳过")
        return

    today_fmt = datetime.now().strftime('%Y%m%d')
    logger.info(f"  [P6自检] 自选股 {len(watchlist_codes)} 只，检查缓存...")
    need_count = 0
    for code in watchlist_codes:
        try:
            has = ecm.has_signal_detail(code, today_fmt)
            if not has:
                _ecm.request_data('precompute_strategy', code)
                need_count += 1
        except Exception:
            _ecm.request_data('precompute_strategy', code)
            need_count += 1
    if need_count:
        logger.info(f"  [P6自检] 发起 {need_count}/{len(watchlist_codes)} 只增量预计算请求")
    else:
        logger.info(f"  [P6自检] 自选股全部有缓存 ✅")


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


def _run_minute_backfill_v2():
    """自选股分钟数据闲时补采（使用 mootdx 填充历史数据）"""
    try:
        from app.data.minute_backfill import run_backfill_all
        result = run_backfill_all()
        logger.info(f"  分钟数据闲时补采: 5min={result.get('5min', 0)}, "
                    f"1min={result.get('1min', 0)}, 聚合={result.get('aggregate', 0)}")
    except Exception as e:
        logger.warning(f"  分钟数据闲时补采失败: {e}")


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

    # 管道驱动兜底：开机后自动从断点恢复
    # 替代 _check_daily_sync_backfill() + _check_precompute_status()
    _drive_pipeline()

    # 主循环（每 30 秒检查一次）
    _last_patrol = 0

    logger.info("data_daemon 进入主循环（管道驱动）")
    while _running:
        now = datetime.now()
        ts = time.time()

        # ── sync_requests 队列消费（不变） ──
        try:
            pending = _ecm.consume_pending_requests()
            for req in pending:
                logger.info(f"消费 sync_requests: id={req['id']} type={req['task_type']} ts_code={req.get('ts_code')}")
                try:
                    if req['task_type'] == 'full_daily':
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
        except Exception as e:
            logger.warning(f"sync_requests 消费异常: {e}")

        # ── 管道驱动（替代15:30-15:35定时窗口 + 兜底，305号§9） ──
        try:
            _drive_pipeline()
        except Exception as e:
            logger.warning(f"管道驱动异常: {e}")

        # ── 数据清理（日终完成后触发一次，305号§9兼容） ──
        if _is_pipeline_complete(datetime.now().strftime('%Y%m%d')):
            if not getattr(_running, '_cleanup_done', False):
                try:
                    _run_data_cleanup()
                    _running._cleanup_done = True  # type: ignore
                except Exception as e:
                    logger.warning(f"数据清理异常: {e}")

        # ── 定时巡检（每整点，非交易时段，不变） ──
        if now.minute == 0 and (now.hour < 9 or now.hour >= 16):
            if ts - _last_patrol > 1800:
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
