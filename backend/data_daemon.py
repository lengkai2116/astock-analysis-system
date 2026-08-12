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

    # 320号 F1：K 线深度检查（策略引擎需要 ≥130 根，不足则标签/九层解读 K 线维度失效）
    try:
        _backfill_all_insufficient_kline(threshold=130, max_codes=200)
    except Exception as e:
        logger.warning(f"  [K线深度] 检查失败: {e}")

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
                    # phase_detector 已运行 → _last_chip_indicators 已填充（复用，不重复计算）
                    try:
                        from app.opportunity_atlas.tag_extractor import (
                            extract_chanlun_deep_tags, extract_chip_deep_tags,
                            extract_fund_risk_tags, DEEP_TAG_GROUPS,
                        )
                        _deep = {}
                        _deep.update(extract_chanlun_deep_tags(code))
                        _deep.update(extract_fund_risk_tags(code))
                        # 筹码深度：复用 phase_detector 刚填充的指标，避免重复计算
                        _chip_inds = getattr(pd_engine, '_last_chip_indicators', {}) or {}
                        if _chip_inds:
                            _deep.update(_chip_tags_from_indicators(_chip_inds))
                        else:
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
    """从 phase_detector._last_chip_indicators 提取筹码深度字段（323号 S0）

    复用 phase_detector 已计算的指标（不重复运行引擎），提取 chip_peak/asr/cyqkl 等。
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
                 entry_signals, exit_conditions, consensus_rate, main_force_presence,
                 presence_evidence, opportunity_state, state_evidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                _compute_snapshot_consensus_rate(t),
                t.get('main_force_presence'),
                t.get('presence_evidence'),
                t.get('opportunity_state'),
                t.get('state_evidence'),
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


def _consume_sync_requests_batch():
    """消费 sync_requests 积压队列（327阶段5：主循环与启动时复用）

    非24h开机时，API 调用层可能堆积 full_*/per_stock 请求——
    daemon 启动后立即消费，不等主循环首个 tick。
    """
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
    """
    # 327阶段1：先清理超时 running 残留（防止重启后永久卡死）
    _recover_stale_running()

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
    has_data = _ecm.conn.execute(
        "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [data_date]
    ).fetchone()[0] >= 4000
    if not has_data:
        return  # 数据未完整到达，下一 tick 再检查

    today_fmt = data_date
    today = data_date_compact

    # 确保当日管道环节已初始化
    _ecm.ensure_pipeline_steps(today)
    status = _ecm.load_pipeline_status(today)

    # ── 采集阶段 C1→C6 ──
    # 327阶段2修正：数据驱动下，若 C1-C6 未全部 done 且数据日期已完整，
    # 直接标记 done 跳过（数据已存在，避免用 data_date 重采旧日期）。
    # 注意：C6 概念板块无日期需独立采集；若采集环节已 done 则正常 continue。
    # 数据缺失场景由完整性检查（run_integrity_check）独立补采，不在此阻塞。
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
        # 数据日期已完整 → 采集环节直接标记 done（数据已存在，无需重采）
        if sid != 'C6':  # C6 概念板块需独立采集（无日期）
            _ecm.conn.execute(
                "UPDATE pipeline_status SET status='done', completed_at=CURRENT_TIMESTAMP, "
                "detail='数据已完整，采集跳过' WHERE pipeline_date=? AND step_id=?",
                [today, sid]
            )
            _ecm.conn.commit()
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
    global _ecm, _running, _cleanup_done

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

    logger.info("data_daemon 进入主循环（管道驱动）")
    while _running:
        now = datetime.now()
        ts = time.time()

        # ── WAL 周期 checkpoint（2026-08-06 根治③）──
        # 每 5 分钟 PASSIVE checkpoint 一次：合并已提交帧、防 WAL 无限膨胀
        # （原无 checkpoint，WAL 曾达 86G；PASSIVE 不阻塞读写）
        if ts - _last_ckpt > 300:
            try:
                _ecm.wal_checkpoint('PASSIVE')
                _last_ckpt = ts
            except Exception as e:
                logger.warning(f"WAL checkpoint 失败: {e}")

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
                    logger.info("定时巡检...")
                    run_integrity_check(backfill_days=1)

        time.sleep(30)

    # 清理
    _stop_collectors()
    logger.info("data_daemon 已停止")


if __name__ == '__main__':
    main()
