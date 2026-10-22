"""
仪表盘 Dashboard 数据服务
集中封装 213号 全部 8 个数据方法。

⚠️ 数据完整性约束（见 _项目运行手册.md §13）：
  生产环境下，数据源不可用时**不得**使用模拟数据替代。
  所有 mock 方法保留仅供开发/原型测试，不得在生产路径中被调用。
  数据不可用时返回 None，由路由层返回 503 错误响应。
"""
import logging
import os
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from app.data import DataManager

logger = logging.getLogger(__name__)

# 四大指数配置
INDEX_CONFIG = [
    {'ts_code': '000001.SH', 'name': '上证指数'},
    {'ts_code': '399001.SZ', 'name': '深圳成指'},
    {'ts_code': '899050.BJ', 'name': '北证50'},
    {'ts_code': '399006.SZ', 'name': '创业板指'},
]

# 固定行业列表（申万一级子集，与原型一致）
SECTOR_NAMES = ['半导体', 'AI', '军工', '新能源', '医药', '消费', '金融', '地产']
OUT_SECTOR_NAMES = ['地产', '建筑', '钢铁', '零售', '纺织']



class DashboardService:
    """仪表盘数据服务 — 8 个数据方法（不含 mock 降级）"""

    def __init__(self):
        self._data_manager = None
        self._tushare = None

    @property
    def data_manager(self):
        if self._data_manager is None:
            from app.data import DataManager
            self._data_manager = DataManager()
        return self._data_manager

    # ──────────────────────────────────────────────
    # 1. 指数行情总览（用于 market/overview 增强）
    # ──────────────────────────────────────────────
    def get_index_summary(self) -> Optional[Dict]:
        """获取四大指数行情 + 迷你K线 + 总成交额
        （239号架构：盘中读 as_market_snapshot，盘后读 daily_cache）"""
        indexes = []
        total_volume = 0
        _any_live = False

        # 盘中：直接从 InMemoryStateStore 读取（全局数据体系架构：mootdx TCP → store）
        # 526 B3 单位契约：live amount=mootdx 元（原样）；DB amount=Tushare 千元（×1000=元）。
        # 两端换算后均以「元」入 total_volume，勿单侧改缩放否则混合源 1000× 错位。
        try:
            from app.data.in_memory_store import store as mem_store
            snapshot = mem_store.get_snapshot()
            live_map = {}
            # 526 B18：{ts_code: row} 字典 O(1) 查，替代 O(indices×rows) 嵌套线性扫描
            snapshot_by_code = {}
            for r in snapshot:
                snapshot_by_code[r.get('ts_code')] = r
            for cfg in INDEX_CONFIG:
                code = cfg['ts_code']
                r = snapshot_by_code.get(code)
                if r is not None:
                    live_map[code] = {
                        'price': float(r.get('price', 0)),
                        'change_pct': float(r.get('change_pct', 0)),
                        'change_value': float(r.get('change', 0)),
                        'amount': self._safe_float(r.get('amount', 0)),  # mootdx 元
                    }
        except Exception:
            live_map = {}

        for idx_cfg in INDEX_CONFIG:
            try:
                code = idx_cfg['ts_code']
                live = live_map.get(code, {})

                # 从 daily_cache 获取历史日线（用于迷你K线 + 前收盘价）
                hist_data = self._try_get_index_daily(code)
                prev_close = None
                mini_kline = []
                ma60 = None
                ret_60d = None
                above_ma60 = None
                if hist_data and len(hist_data) > 0:
                    # hist_data 是旧→新排序
                    latest_hist = (
                        hist_data[-1] if isinstance(hist_data[-1], dict)
                        else hist_data.iloc[-1].to_dict()
                    )
                    # 526 B4：pre_close 优先；无则回退前一日收盘（兼容 dict/DataFrame 行）
                    prev_close_val = None
                    if latest_hist.get('pre_close') is not None:
                        prev_close_val = float(latest_hist['pre_close'])
                    elif len(hist_data) > 1:
                        prev_hist = (
                            hist_data[-2] if isinstance(hist_data[-2], dict)
                            else hist_data.iloc[-2].to_dict()
                        )
                        prev_close_val = float(prev_hist.get('close', 0) or 0)
                    prev_close = prev_close_val if prev_close_val is not None else 0
                    # 迷你K线（最近20交易日）
                    _sorted = hist_data if (
                        len(hist_data) > 1
                        and hist_data[0].get('trade_date', '')
                        <= hist_data[-1].get('trade_date', '')
                    ) else hist_data[::-1]
                    mini_kline = self._build_mini_kline(_sorted[-20:])
                    # 527 批次3：指数 60 日线（需 61 行才能算近60日涨跌）
                    if len(_sorted) > 60:
                        closes60 = [self._safe_float(r.get('close', 0)) for r in _sorted[-60:]]
                        latest_close = float(_sorted[-1].get('close', 0))
                        ma60 = round(sum(closes60) / len(closes60), 2)
                        prev60_close = float(_sorted[-61].get('close', 0))
                        if prev60_close > 0:
                            ret_60d = round((latest_close / prev60_close - 1) * 100, 2)
                        above_ma60 = latest_close >= ma60 if ma60 else None

                # 价格优先用实时快照，没有则用历史
                if live:
                    price = live['price']
                    change_pct = live['change_pct']
                    change_amount = live['change_value']
                    amount = live['amount']
                    _any_live = True
                    # 如果 has 实时数据但没有历史前收盘价，用实时涨跌幅推算
                    if prev_close is None and change_pct != 0:
                        prev_close = price / (1 + change_pct / 100) if change_pct != -100 else price
                elif prev_close is not None and hist_data:
                    # 没有实时数据，用历史最新日线
                    latest_hist = (
                        hist_data[-1] if isinstance(hist_data[-1], dict)
                        else hist_data.iloc[-1].to_dict()
                    )
                    price = float(latest_hist.get('close', latest_hist.get('value', 0)))
                    change = price - prev_close
                    change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                    change_amount = change
                    amount = self._safe_float(latest_hist.get('amount', 0)) * 1000
                else:
                    # 无实时也无历史 → 跳过
                    logger.warning(f"指数 {code} 无数据: 实时快照和历史日线均不可用")
                    continue

                indexes.append({
                    'ts_code': code,
                    'name': idx_cfg['name'],
                    'price': round(price, 2),
                    'change_pct': round(change_pct, 2),
                    'change_amount': round(change_amount, 2),
                    'mini_kline': mini_kline,
                    'amount': amount,
                    # 527 批次3：指数 60 日线（daily_cache 88 行；None=历史不足60日）
                    'ma60': ma60,
                    'ret_60d': ret_60d,
                    'above_ma60': above_ma60,
                    # 526 B17：live 实为 InMemoryStateStore（mootdx TCP）→ 标注修正（原误标 AKShare）
                    'source': 'mootdx 实时行情' if live else '日线缓存',
                })
                total_volume += amount
            except Exception as e:
                logger.warning(f"指数 {idx_cfg['ts_code']} 获取失败，已跳过: {e}")

        if not indexes:
            logger.error("四大指数行情全部不可用")
            return None

        # 成交额同比变化（基于daily_cache历史数据推算）
        # Tushare index_daily 的 amount 单位是千元，需 ×1000 转为元
        volume_change_pct = 0
        try:
            from app.data.sharding_manager import sharding_manager
            _conn = sharding_manager.get_connection(sharding_manager.get_db_for_table('daily_cache'))
            _idx_codes = ['000001.SH', '399001.SZ', '899050.BJ', '399006.SZ']
            _placeholders = ','.join(['?' for _ in _idx_codes])
            _today_row = _conn.execute(
                f"SELECT SUM(amount) as total FROM daily_cache WHERE ts_code IN ({_placeholders}) "
                "AND trade_date = (SELECT MAX(trade_date) FROM daily_cache)",
                _idx_codes
            ).fetchone()
            _prev_date = _conn.execute(
                "SELECT trade_date FROM daily_cache WHERE ts_code='000001.SH' "
                "AND trade_date < (SELECT MAX(trade_date) FROM daily_cache) "
                "ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            _prev_row = None
            if _prev_date:
                _prev_row = _conn.execute(
                    f"SELECT SUM(amount) as total FROM daily_cache WHERE ts_code IN ({_placeholders}) "
                    f"AND trade_date = ?",
                    _idx_codes + [_prev_date[0]]
                ).fetchone()
            if _today_row and _today_row[0] and _prev_row and _prev_row[0] and _prev_row[0] > 0:
                # amount 单位千元 → 元（×1000），与 total_volume（元）对齐
                today_amt = _today_row[0] * 1000
                prev_amt = _prev_row[0] * 1000
                volume_change_pct = round((today_amt - prev_amt) / prev_amt * 100, 1)
        except Exception as e:
            # 526 B19：volume_change 失败静默变 0 与真实 0% 不可区分——补 debug 日志
            logger.debug(f"成交额同比变化计算失败: {e}")

        # 516 批次3（Q4）：附「数据日/是否实时」以便前端按数据时效标注（不再一律显示「交易中」）
        _dd = self._try_get_latest_trade_date() or ''
        data_date = (
            f"{_dd[:4]}-{_dd[4:6]}-{_dd[6:8]}"
            if (len(_dd) == 8 and _dd.isdigit()) else _dd
        )

        result = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'market_status': self._detect_market_status(),
            'data_is_live': _any_live,
            'data_date': data_date,
            'total_volume': total_volume,
            'total_volume_change_pct': volume_change_pct,
            'indexes': indexes,
        }

        # 部分成功时附注说明
        if len(indexes) < len(INDEX_CONFIG):
            loaded = {i['ts_code'] for i in indexes}
            failed = [c['name'] for c in INDEX_CONFIG if c['ts_code'] not in loaded]
            result['notice'] = f"以下指数数据不可用: {', '.join(failed)}"

        return result

    # ──────────────────────────────────────────────
    # 2. 迷你K线（用于 chart/kline?mini=true）
    # ──────────────────────────────────────────────
    def get_mini_kline(self, ts_code: str, limit: int = 20) -> Optional[Dict]:
        """获取指定指数的迷你K线数据"""
        try:
            data = self._try_get_index_daily(ts_code)
            if data and len(data) > 0:
                # 数据可能升序（DuckDB）或降序（Tushare），统一升序后取最近 limit 条
                _sorted = data if (
                    len(data) > 1
                    and data[0].get('trade_date', '') <= data[-1].get('trade_date', '')
                ) else data[::-1]
                mini_kline = self._build_mini_kline(_sorted[-limit:])
                name = ts_code
                for idx in INDEX_CONFIG:
                    if idx['ts_code'] == ts_code:
                        name = idx['name']
                        break
                return {
                    'ts_code': ts_code,
                    'name': name,
                    'kline': mini_kline,
                }
        except Exception as e:
            logger.warning(f"迷你K线获取失败 {ts_code}: {e}")

        logger.error(f"迷你K线数据不可用: {ts_code}")
        return None

    # ──────────────────────────────────────────────
    # 3. 成交额柱状图（index-daily）
    # ──────────────────────────────────────────────
    def get_market_volume(self, days: int = 20) -> Optional[Dict]:
        """四大交易所合计成交额（近N交易日）"""
        try:
            all_dates = set()
            exchange_data = {}
            active_indices = 0
            for idx_cfg in INDEX_CONFIG:
                data = self._try_get_index_daily(idx_cfg['ts_code'])
                if data is None or len(data) == 0:
                    logger.warning(f"跳过无数据的指数: {idx_cfg['ts_code']}")
                    continue
                active_indices += 1
                for row in data:
                    d = row if isinstance(row, dict) else row.to_dict()
                    raw_date = d.get('trade_date', d.get('date', ''))
                    # 保留完整 YYYYMMDD 作为 key 避免不同年份数据混淆
                    # 526 B15：datetime.date/pd.Timestamp（含 00:00:00 时间尾巴）不再走 else
                    if isinstance(raw_date, datetime):
                        date_key = raw_date.strftime('%Y%m%d')
                    elif isinstance(raw_date, str) and len(raw_date) == 8 and raw_date.isdigit():
                        date_key = raw_date
                    elif isinstance(raw_date, str) and '-' in raw_date:
                        parts = raw_date.split('-')
                        # 截掉可能的 'HH:MM:SS' 时间尾巴（pd.Timestamp str 含空格）
                        day = parts[2][:2] if len(parts) > 2 else ''
                        date_key = f"{parts[0]}{parts[1]}{day}"
                    elif hasattr(raw_date, 'strftime'):  # datetime.date / pd.Timestamp
                        date_key = raw_date.strftime('%Y%m%d')
                    else:
                        date_key = str(raw_date)

                    amount = self._safe_float(d.get('amount', 0)) * 1000
                    if date_key not in exchange_data:
                        exchange_data[date_key] = {
                            'date_key': date_key,
                            'total_amount': 0,
                            'amount_per_exchange': {},
                            'pct_chg': None
                        }
                    exchange_data[date_key]['total_amount'] += amount
                    exchange_data[date_key]['amount_per_exchange'][idx_cfg['ts_code']] = amount
                    # 用上证指数（第一个）的涨跌幅作为市场方向
                    if exchange_data[date_key]['pct_chg'] is None:
                        exchange_data[date_key]['pct_chg'] = self._safe_float(d.get('pct_chg', 0))
                    all_dates.add(date_key)

            if active_indices == 0:
                logger.error("所有指数数据均不可用")
                return None

            # 按 YYYYMMDD 排序取最近 days 条
            sorted_dates = sorted(all_dates, reverse=True)[:days]
            sorted_dates.reverse()  # 从小到大排列
            days_list = []
            for dk in sorted_dates:
                days_list.append({
                    'date': f"{dk[4:6]}/{dk[6:8]}",
                    'total_amount': exchange_data[dk]['total_amount'],
                    'amount_per_exchange': exchange_data[dk]['amount_per_exchange'],
                    'pct_chg': exchange_data[dk].get('pct_chg', 0),
                })
            avg_amount = (
                sum(d['total_amount'] for d in days_list) / len(days_list)
                if days_list else 0
            )

            return {
                'exchange_summary': '上证+深证+北证50+创业板（含指数成分重叠）',
                'days': days_list,
                'average_amount': round(avg_amount, 2),
                'updated_at': datetime.now().strftime('%Y-%m-%d'),
            }
        except Exception as e:
            logger.error(f"成交额数据全部不可用: {e}")
            return None

    # ──────────────────────────────────────────────
    # 4. 涨跌幅榜（daily-top）
    # ──────────────────────────────────────────────
    def get_daily_top(self, type: str = 'up', limit: int = 10) -> Optional[Dict]:
        """涨幅榜/跌幅榜 — AKShare 实时优先 → DB 前一完整交易日（239号架构：不直接调 Tushare）。

        535 P1：DB 降级不再取 daily_cache 最新日（10-21 仅 95 只残行），
        改用 `_get_best_trade_date(before=today)` 锚定前一完整交易日。
        """
        # 1. AkshareDataReader 读取（DuckDB as_* 表）
        try:
            from app.data.akshare_reader import reader
            top_list = reader.get_top_stocks(type=type, limit=limit)
            if top_list and len(top_list) > 0:
                stocks = []
                for s in top_list:
                    pct = float(s.get('change_pct', 0))
                    stocks.append({
                        'ts_code': s.get('ts_code', ''),
                        'name': s.get('name', s.get('ts_code', '')),
                        'price': round(float(s.get('price', 0)), 2),
                        'change_pct': round(pct, 2),
                        'change_pct_display': f"{'+' if pct >= 0 else ''}{round(pct, 2)}%",
                    })
                return {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'type': type,
                    'title': '涨幅前十' if type == 'up' else '跌幅前十',
                    'source': 'AKShare 实时行情',
                    'stocks': stocks,
                }
        except Exception:
            pass

        # 2. 降级：从 DuckDB 查询前一完整交易日
        try:
            ecm = self.data_manager.cache
            today = datetime.now().strftime('%Y-%m-%d')
            last_date = self._get_best_trade_date(before=today)
            if not last_date:
                date_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT DISTINCT trade_date FROM daily_cache "
                    "ORDER BY trade_date DESC LIMIT 1")
                if date_df is None or date_df.empty:
                    logger.error("涨跌幅榜: DuckDB 无任何历史数据")
                    return None
                last_date = str(date_df['trade_date'].iloc[0])

            all_df = ecm._query_shard(
                'daily_cache',
                "SELECT * FROM daily_cache WHERE trade_date = ? ORDER BY pct_chg DESC",
                [last_date])
            if all_df is None or all_df.empty:
                logger.error("涨跌幅榜: DuckDB 查询为空")
                return None

            ts_codes = all_df['ts_code'].unique().tolist()
            name_map = self._get_stock_names(ts_codes)
            stock_map = {code: info.get('name', '')
                         for code, info in name_map.items()}
            if not stock_map and self.data_manager:
                try:
                    basic = self.data_manager.get_stock_list()
                    if basic:
                        stock_map = {r.get('ts_code', ''): r.get('name', '')
                                     for r in basic}
                except Exception as e:
                    logger.warning(f"涨跌幅榜 get_stock_list 名称兜底失败: {e}")

            all_df['name'] = all_df['ts_code'].map(
                lambda x: stock_map.get(x) or x)
            sort_asc = (type == 'down')
            top_df = all_df.sort_values('pct_chg', ascending=sort_asc).head(limit)

            stocks = []
            for _, row in top_df.iterrows():
                pct = float(row.get('pct_chg', 0))
                stocks.append({
                    'ts_code': row.get('ts_code', ''),
                    'name': row.get('name', row.get('ts_code', '')),
                    'price': round(float(row.get('close', 0)), 2),
                    'change_pct': round(pct, 2),
                    'change_pct_display': f"{'+' if pct >= 0 else ''}{round(pct, 2)}%",
                })
            return {
                'date': str(last_date),
                'type': type,
                'title': '涨幅前十' if type == 'up' else '跌幅前十',
                'source': 'DuckDB 盘后数据（前一完整交易日）',
                'stocks': stocks,
            }
        except Exception as e:
            logger.error(f"涨跌幅榜 DuckDB 降级失败: {e}")

        logger.error("涨跌幅榜: 所有数据源不可用")
        return None

    # ──────────────────────────────────────────────
    # 523：全市场日终散点（eod-snapshot）
    # ──────────────────────────────────────────────
    def get_eod_snapshot(self) -> Optional[Dict]:
        """全市场前一交易日日终散点数据（523号）。

        Part1：流通市值 × 涨跌幅（X=circ_mv、Y=pct_chg）
        Part2：高开/低开 × 高收/低收 四象限（X=(open-pre_close)/pre_close、Y=(close-open)/open）

        数据源：daily_cache ⋈ daily_basic_cache（前一完整交易日，inner join 天然排除指数）。
        533 批次回归修正（534号）：不再取 daily_basic 最新日，改为
        `_get_best_trade_date(before=today)` 固定前一完整交易日；若 join 后样本不足
        （<1000 只），自动回退到再前一交易日，并返回 data_quality。
        pre_close 无独立列，由 pct_chg 精确推导（Tushare 口径含除权）：
          pre_close = close / (1 + pct_chg/100)
        """
        try:
            from app.models import Stock

            ecm = self.data_manager.cache
            today = datetime.now().strftime('%Y-%m-%d')
            min_stocks = 1000
            as_of = self._get_best_trade_date(before=today)

            candidates = []
            if as_of:
                candidates.append(as_of)
                prev = self._get_best_trade_date(before=as_of)
                if prev and prev not in candidates:
                    candidates.append(prev)
            else:
                # 非交易日/无完整日线时，退回 daily_basic 最近两个日期，
                # 由下方的样本量守卫挑选更完整的一天。
                date_df = ecm._query_shard(
                    'daily_basic_cache',
                    "SELECT DISTINCT trade_date FROM daily_basic_cache "
                    "ORDER BY trade_date DESC LIMIT 2")
                if date_df is not None and not date_df.empty:
                    candidates = [str(d) for d in date_df['trade_date'].tolist()]

            if not candidates:
                logger.error("全市场日终散点: daily_cache/daily_basic_cache 无任何历史数据")
                return None

            merged = None
            last_date = None
            for cand in candidates:
                daily_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT ts_code, open, close, pct_chg FROM daily_cache "
                    "WHERE trade_date = ?", [cand])
                if daily_df is None or daily_df.empty:
                    continue
                basic_df = ecm._query_shard(
                    'daily_basic_cache',
                    "SELECT ts_code, circ_mv, total_mv FROM daily_basic_cache "
                    "WHERE trade_date = ?", [cand])
                if basic_df is None or basic_df.empty:
                    continue
                # inner join → 天然排除指数（daily 独有行＝指数/行业指数）
                cand_merged = daily_df.merge(basic_df, on='ts_code', how='inner')
                if cand_merged.empty:
                    continue
                if merged is None or len(cand_merged) > len(merged):
                    merged, last_date = cand_merged, cand
                if len(cand_merged) >= min_stocks:
                    merged, last_date = cand_merged, cand
                    break

            if merged is None or merged.empty or not last_date:
                logger.error("全市场日终散点: 候选交易日均无有效 join 数据")
                return None

            data_quality = 'ok' if len(merged) >= min_stocks else 'low_sample'

            # 名称补齐（同 get_daily_top：Stock 表 → get_stock_list 兜底）
            ts_codes = merged['ts_code'].unique().tolist()
            stock_map = {}
            try:
                for s in Stock.query.filter(Stock.ts_code.in_(ts_codes)).all():
                    stock_map[s.ts_code] = s.name
            except Exception as e:
                # 526 B19：名称填充失败静默变空名——补 debug 日志
                logger.debug(f"eod-snapshot Stock 名称查询失败: {e}")
            if not stock_map:
                try:
                    basic = self.data_manager.get_stock_list()
                    if basic:
                        for r in basic:
                            stock_map[r.get('ts_code', '')] = r.get('name', '')
                except Exception as e:
                    logger.debug(f"eod-snapshot get_stock_list 名称兜底失败: {e}")

            stocks = []
            for _, row in merged.iterrows():
                close = float(row.get('close') or 0)
                pct = float(row.get('pct_chg') or 0)
                # 526 B16：pct 越界（≤-100 或 >100）时 pre_close 推导失真
                # （denom 极小/负 → X 轴散点错位）——越界回退 close，不参与推导
                if -100 < pct <= 100:
                    denom = 1 + pct / 100.0
                    pre_close = close / denom if abs(denom) > 1e-9 else close
                else:
                    pre_close = close
                stocks.append({
                    'ts_code': str(row.get('ts_code', '')),
                    'name': stock_map.get(row.get('ts_code', ''), ''),
                    'open': round(float(row.get('open') or 0), 2),
                    'close': round(close, 2),
                    'pre_close': round(pre_close, 2),
                    'pct_chg': round(pct, 2),
                    'circ_mv': float(row.get('circ_mv') or 0),
                    'total_mv': float(row.get('total_mv') or 0),
                })

            return {
                'trade_date': str(last_date),
                'count': len(stocks),
                'data_quality': data_quality,
                'source': 'DuckDB 盘后数据',
                'stocks': stocks,
                # 530 批次1：状态结果说明——近5交易日涨跌平家数 + 四象限计数
                # 534：summary_5d 同步锚定 last_date，排除盘中残行
                'summary_5d': self._get_eod_summary_5d(ecm, as_of=last_date),
            }
        except Exception as e:
            logger.error(f"全市场日终散点获取失败: {e}")
            return None

    def _get_eod_summary_5d(self, ecm, as_of: Optional[str] = None) -> list:
        """近5交易日涨跌平家数 + 四象限计数（530 批次1，状态结果说明数据源）。

        口径对齐主散点：daily_cache ⋈ daily_basic_cache（inner join 天然排除指数）；
        pre_close 由 pct_chg 推导（同 get_eod_snapshot，Tushare 口径含除权）。
        四象限：高开低开×高收低收（X=(open-pre)/pre、Y=(close-open)/open）。
        534：as_of 指定时只取 <= as_of 的交易日，排除盘中残行（如 10-21 仅 95 只）。
        返回升序 [{date, up_count, down_count, flat_count, quad:{gg,gd,dg,dd}}]。
        """
        try:
            if as_of:
                dates_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT DISTINCT trade_date FROM daily_cache "
                    "WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 5",
                    [as_of])
            else:
                dates_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT DISTINCT trade_date FROM daily_cache "
                    "ORDER BY trade_date DESC LIMIT 5")
            if dates_df is None or dates_df.empty:
                return []
            dates = [str(d) for d in dates_df['trade_date'].tolist()]
            summary = []
            for d in dates:
                daily_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT ts_code, open, close, pct_chg FROM daily_cache WHERE trade_date = ?",
                    [d])
                basic_df = ecm._query_shard(
                    'daily_basic_cache',
                    "SELECT ts_code FROM daily_basic_cache WHERE trade_date = ?",
                    [d])
                if daily_df is None or daily_df.empty or basic_df is None or basic_df.empty:
                    continue
                merged = daily_df.merge(basic_df, on='ts_code', how='inner')
                if merged.empty:
                    continue
                up = int((merged['pct_chg'].astype(float) > 0).sum())
                down = int((merged['pct_chg'].astype(float) < 0).sum())
                flat = int((merged['pct_chg'].astype(float) == 0).sum())
                gg = gd = dg = dd = 0
                for _, row in merged.iterrows():
                    op = float(row.get('open') or 0)
                    cl = float(row.get('close') or 0)
                    pct = float(row.get('pct_chg') or 0)
                    if op <= 0 or cl <= 0:
                        continue
                    if -100 < pct <= 100:
                        denom = 1 + pct / 100.0
                        pre = cl / denom if abs(denom) > 1e-9 else cl
                    else:
                        pre = cl
                    if pre <= 0:
                        continue
                    gap = (op - pre) / pre * 100
                    body = (cl - op) / op * 100
                    if gap >= 0 and body >= 0:
                        gg += 1
                    elif gap >= 0 and body < 0:
                        gd += 1
                    elif gap < 0 and body >= 0:
                        dg += 1
                    else:
                        dd += 1
                summary.append({
                    'date': d,
                    'up_count': up, 'down_count': down, 'flat_count': flat,
                    'quad': {'gg': gg, 'gd': gd, 'dg': dg, 'dd': dd},
                })
            summary.sort(key=lambda x: x['date'])
            return summary
        except Exception as e:
            logger.warning(f"eod-snapshot summary_5d 聚合失败: {e}")
            return []

    # ──────────────────────────────────────────────
    # 5. 板块涨跌幅（sector-sector）
    # ──────────────────────────────────────────────
    def get_sector_changes(self, top_n: int = 8,
                           use_intraday: bool = False) -> Optional[Dict]:
        """行业板块涨跌幅 — 默认固定上一完整交易日，降级 DB daily_data 聚合。

        2026-10-21 目检拍板：默认 use_intraday=False，避免盘中板块快照
        （东方财富细分行业，5min 刷新）导致横轴分类漂移；仅显式传 True 时
        才走 AKShare 盘中快照。
        528 号 批次2：取数改全量（原 `get_sector_rankings()` 默认 top_n=20，
        DB 回退 `ORDER BY change_pct DESC LIMIT 20` 前 20 全为正涨幅 → losers 恒空，
        跌幅 TOP5 缺失的根因）——改传 top_n=None 取全行业，双侧分别取 top5。
        """
        # 固定上一工作日（today 之前最近完整交易日），避免收盘入库后切日
        today = datetime.now().strftime('%Y-%m-%d')
        as_of = self._get_best_trade_date(before=today)
        # 528 号 批次2：板块连续涨/跌 + 近5日累积涨跌（daily_cache 多日按行业聚合）
        streaks = self._get_sector_streaks(as_of=as_of)
        # 530号 批次3：板块近20日每日平均涨跌幅序列（近20日板块涨跌折线数据源）
        # 531 号：由 20 日序列派生近 5 日序列 + 每行文字总结（不新增 DB 查询）
        history_20d = self._get_sector_history_20d(as_of=as_of)
        history_5d = self._build_sector_history_5d(history_20d)
        # 1. 尝试 AkshareDataReader 读取
        try:
            if not use_intraday:
                rankings = []
            else:
                from app.data.akshare_reader import reader
                rankings = reader.get_sector_rankings(top_n=None)
            if rankings and len(rankings) >= top_n:
                all_sectors = []
                for s in rankings:
                    name = s.get('sector_name', s.get('name', ''))
                    change_pct = s.get('change_pct', 0)
                    if not name or str(name).strip().lower() in ('nan', 'none', ''):
                        continue  # 跳过无效数据，降级到 DB
                    all_sectors.append({
                        'name': name,
                        'change_pct': change_pct,
                        'lead_stock': '',
                        'up_count': s.get('up_count', 0),
                        'down_count': s.get('down_count', 0),
                    })
                if len(all_sectors) >= top_n:
                    all_sectors.sort(key=lambda x: x['change_pct'], reverse=True)
                    gainers = [s for s in all_sectors if s['change_pct'] > 0][:5]
                    losers = [s for s in all_sectors if s['change_pct'] <= 0]
                    losers.reverse()
                    losers = losers[:5]
                    return {
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'gainers': gainers,
                        'losers': losers,
                        'streaks': streaks,
                        'history_20d': history_20d,
                        'history_5d': history_5d,
                        'source': '东方财富行业板块（盘中）',
                    }
        except Exception as e:
            logger.warning(f"板块涨跌幅 reader 不可用，降级 DB: {e}")

        # 2. 降级：从 DuckDB 最新交易日聚合行业涨跌幅
        try:
            import pandas as pd

            from app.models import Stock

            ecm = self.data_manager.cache
            # 固定上一工作日（today 之前最近完整交易日），避免收盘入库后切日
            last_date = as_of
            if not last_date:
                raise ValueError("无上一交易日数据")
            date_label = str(last_date)

            # 取该日全市场 pct_chg + ts_code
            all_df = ecm._query_shard(
                'daily_cache',
                "SELECT ts_code, pct_chg FROM daily_cache WHERE trade_date = ?",
                [last_date])
            if all_df.empty:
                logger.error("板块涨跌幅 DuckDB: 当日无数据")
                raise ValueError("DuckDB daily_cache 当日无数据，走 Tushare 降级")

            # 531/530 口径：优先申万一级 31 类（与净流入/热度/近5日走势一致）；
            # 原 Stock.industry 为东财二级 110 类，小样本行业会产生 -6% 级极端值。
            ts_codes = all_df['ts_code'].unique().tolist()
            industry_map = {}
            try:
                from app.data.sw_industry_map import get_sw_industry_map, normalize_code
                sw_map = get_sw_industry_map(ecm)
                industry_map = {c: sw_map.get(normalize_code(c)) for c in ts_codes}
                industry_map = {k: v for k, v in industry_map.items() if v}
            except Exception:
                industry_map = {}
            # 申万映射不可用时回退 Stock.industry（110 类）
            if len(industry_map) < 10:
                try:
                    for s in Stock.query.filter(Stock.ts_code.in_(ts_codes)).all():
                        if s.industry:
                            industry_map[s.ts_code] = s.industry
                except Exception:
                    pass
                if len(industry_map) < 10:
                    try:
                        if self.data_manager:
                            basic = self.data_manager.get_stock_list()
                            if basic:
                                for r in basic:
                                    if r.get('industry'):
                                        industry_map[r.get('ts_code', '')] = r['industry']
                    except Exception:
                        pass
            # 前两条路都失败时，返回现有数据（不再降级到 Tushare — 260 §11 V2 修复）
            if len(industry_map) < 10:
                logger.info(f"行业映射不完整 ({len(industry_map)} 条)，使用现有数据")

            all_df['industry'] = all_df['ts_code'].map(lambda x: industry_map.get(x, None))
            all_df = all_df.dropna(subset=['industry'])
            all_df['industry'] = all_df['industry'].astype(str)

            # 按行业聚合
            agg = all_df.groupby('industry').agg(
                avg_pct=('pct_chg', 'mean'),
                stock_count=('pct_chg', 'count')
            ).reset_index().sort_values('avg_pct', ascending=False)

            if not agg.empty:
                all_sectors = []
                for _, r in agg.iterrows():
                    change_pct = round(float(r['avg_pct'] or 0), 2)
                    all_sectors.append({
                        'name': r['industry'],
                        'change_pct': change_pct,
                        'lead_stock': '',
                        'up_count': 0,
                        'down_count': 0,
                    })
                gainers = [s for s in all_sectors if s['change_pct'] > 0][:5]
                losers = [s for s in all_sectors if s['change_pct'] <= 0]
                losers.reverse()
                losers = losers[:5]
                # DB 聚合也可能出现单边行情，此时只返回有数据的一侧
                return {
                    'date': date_label,
                    'cached_at': date_label,
                    'gainers': gainers,
                    'losers': losers,
                    'streaks': streaks,
                    'history_20d': history_20d,
                    'history_5d': history_5d,
                    'source': 'DuckDB daily_cache 聚合',
                }
        except Exception as e:
            logger.error(f"板块涨跌幅 DuckDB 降级失败: {e}")

        logger.error("板块涨跌幅: 所有数据源不可用")
        return None

    def _get_sector_streaks(self, days: int = 6, min_streak: int = 2,
                            as_of: Optional[str] = None) -> Dict:
        """板块连续涨/跌 + 近5日累积涨跌（528 号 批次2）。

        数据源：daily_cache 多日按行业聚合（DuckDB）→ 每行业近 days 个交易日
        平均涨跌幅 → 从最新往回数连续上涨/下跌天数（streak）→ 近5日累积涨跌
        （最后 5 日行业平均 pct_chg 之和，近似口径）。
        返回 {'up': [...], 'down': [...]}（各按天数降序，取前 5）；失败返回空两侧。
        """
        try:
            ecm = self.data_manager.cache
            if as_of:
                dates_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT DISTINCT trade_date FROM daily_cache "
                    "WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?",
                    [str(as_of), days])
            else:
                dates_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT DISTINCT trade_date FROM daily_cache "
                    "ORDER BY trade_date DESC LIMIT ?", [days])
            if dates_df is None or dates_df.empty:
                return {'up': [], 'down': []}
            dates = sorted(str(d) for d in dates_df['trade_date'].tolist())
            if len(dates) < 2:
                return {'up': [], 'down': []}
            placeholders = ','.join('?' for _ in dates)
            all_df = ecm._query_shard(
                'daily_cache',
                f"SELECT trade_date, ts_code, pct_chg FROM daily_cache "
                f"WHERE trade_date IN ({placeholders})", dates)
            if all_df is None or all_df.empty:
                return {'up': [], 'down': []}

            ts_codes = all_df['ts_code'].unique().tolist()
            industry_map = {}
            try:
                from app.data.sw_industry_map import get_sw_industry_map, normalize_code
                sw_map = get_sw_industry_map(ecm)
                industry_map = {c: sw_map.get(normalize_code(c)) for c in ts_codes}
                industry_map = {k: v for k, v in industry_map.items() if v}
            except Exception:
                industry_map = {}
            if len(industry_map) < 10:
                from app import db as _flask_db
                from app.models import Stock
                try:
                    # 对齐 get_sector_moneyflow 的 db.session.query 模式（可测性一致，
                    # Stock.query 描述符在无 app context 时触发 session 绑定）
                    for s in _flask_db.session.query(
                            Stock.ts_code, Stock.industry).filter(
                            Stock.ts_code.in_(ts_codes)).all():
                        if s.industry:
                            industry_map[s.ts_code] = s.industry
                except Exception:
                    pass
            if len(industry_map) < 10:
                return {'up': [], 'down': []}

            all_df['industry'] = all_df['ts_code'].map(lambda x: industry_map.get(x, None))
            all_df = all_df.dropna(subset=['industry'])
            if all_df.empty:
                return {'up': [], 'down': []}

            agg = all_df.groupby(['industry', 'trade_date'])['pct_chg'].mean().reset_index()
            up, down = [], []
            for ind, grp in agg.groupby('industry'):
                grp = grp.sort_values('trade_date')
                series = grp['pct_chg'].tolist()
                if len(series) < 2:
                    continue
                up_days = 0
                for v in reversed(series):
                    if v > 0:
                        up_days += 1
                    else:
                        break
                down_days = 0
                for v in reversed(series):
                    if v < 0:
                        down_days += 1
                    else:
                        break
                cum_5d = round(float(sum(series[-5:])), 2)
                if up_days >= min_streak:
                    up.append({'industry': ind, 'days': up_days, 'cum_5d': cum_5d})
                if down_days >= min_streak:
                    down.append({'industry': ind, 'days': down_days, 'cum_5d': cum_5d})
            up.sort(key=lambda x: (-x['days'], -x['cum_5d']))
            down.sort(key=lambda x: (-x['days'], x['cum_5d']))
            return {'up': up[:5], 'down': down[:5]}
        except Exception as e:
            logger.warning(f"板块连续涨跌聚合失败: {e}")
            return {'up': [], 'down': []}

    def _get_sector_history_20d(self, days: int = 20,
                               as_of: Optional[str] = None) -> Dict:
        """板块近 N 日每日平均涨跌幅序列（530号 批次3/第二轮：近20日板块涨跌折线数据源）。

        数据源：daily_cache 近 days 个交易日按**申万一级 31 类**聚合日均 pct_chg
        （530 第二轮：原东财二级 110 类碎行业改申万一级，与板块热度同口径）。
        返回 {'dates': [...升序], 'avg': [全市场每日均值...], 'industries': {industry: [逐日值...]}}；
        映射缺失/失败返回空 dict（不阻断主接口）。
        """
        try:
            ecm = self.data_manager.cache
            if as_of:
                dates_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT DISTINCT trade_date FROM daily_cache "
                    "WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?",
                    [str(as_of), days])
            else:
                dates_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT DISTINCT trade_date FROM daily_cache "
                    "ORDER BY trade_date DESC LIMIT ?", [days])
            if dates_df is None or dates_df.empty:
                return {}
            dates = sorted(str(d) for d in dates_df['trade_date'].tolist())
            if len(dates) < 2:
                return {}
            placeholders = ','.join('?' for _ in dates)
            all_df = ecm._query_shard(
                'daily_cache',
                f"SELECT trade_date, ts_code, pct_chg FROM daily_cache "
                f"WHERE trade_date IN ({placeholders})", dates)
            if all_df is None or all_df.empty:
                return {}

            from app.data.sw_industry_map import get_sw_industry_map, normalize_code
            ts_codes = all_df['ts_code'].unique().tolist()
            sw_map = get_sw_industry_map(ecm)
            if not sw_map:
                logger.warning("板块近20日历史聚合: 申万一级映射为空，跳过")
                return {}
            industry_map = {c: sw_map.get(normalize_code(c)) for c in ts_codes}
            industry_map = {k: v for k, v in industry_map.items() if v}
            if not industry_map or (len(ts_codes) >= 10 and len(industry_map) < 10):
                return {}

            all_df['industry'] = all_df['ts_code'].map(lambda x: industry_map.get(x, None))
            all_df = all_df.dropna(subset=['industry'])
            if all_df.empty:
                return {}
            # 每行业每日均值 + 全市场每日均值（avg 基准线）
            agg = all_df.groupby(['industry', 'trade_date'])['pct_chg'].mean().reset_index()
            market_avg = all_df.groupby('trade_date')['pct_chg'].mean()
            industries = {}
            for ind, grp in agg.groupby('industry'):
                grp = grp.sort_values('trade_date')
                d2v = dict(zip(grp['trade_date'], grp['pct_chg']))
                industries[str(ind)] = [round(float(d2v.get(d, 0.0) or 0.0), 2) for d in dates]
            avg = [round(float(market_avg.get(d, 0.0) or 0.0), 2) for d in dates]
            return {'dates': dates, 'avg': avg, 'industries': industries}
        except Exception as e:
            logger.warning(f"板块近20日历史聚合失败: {e}")
            return {}

    def _build_sector_history_5d(self, history: Dict) -> Dict:
        """531：由近20日序列派生近5交易日序列 + 每行文字总结（不新增 DB 查询）。

        返回 {'dates': [5], 'avg': [5], 'industries': {ind: [5]},
              'summary': {ind: 一句话}, 'avg_summary': 一句话}
        """
        if not history or not history.get('dates'):
            return {}
        dates = list(history['dates'])
        n = min(5, len(dates))
        if n < 2:
            return {}
        d5 = dates[-n:]
        industries = {}
        summary = {}
        for ind, vals in (history.get('industries') or {}).items():
            v = [float(x or 0.0) for x in list(vals)[-n:]]
            industries[ind] = v
            summary[ind] = self._summarize_pct_5d(v)
        avg = [float(x or 0.0) for x in list(history.get('avg') or [])[-n:]]
        return {
            'dates': d5,
            'industries': industries,
            'avg': avg,
            'summary': summary,
            'avg_summary': self._summarize_pct_5d(avg),
        }

    @staticmethod
    def _summarize_pct_5d(vals) -> str:
        """531：板块近5日涨跌一句话总结（每日行业平均 pct_chg，升序）。

        口径说明：累计＝5 日日均涨跌幅之和（近似值，非复利/市值加权）。
        """
        vals = [float(v) for v in (vals or []) if v is not None]
        if not vals:
            return ''
        total = sum(vals)
        up = sum(1 for v in vals if v > 0)
        down = sum(1 for v in vals if v < 0)
        last = vals[-1]
        if len(vals) >= 4 and up >= 4 and last > 0:
            shape = '持续上行'
        elif len(vals) >= 4 and down >= 4 and last < 0:
            shape = '持续下行'
        elif len(vals) >= 4 and vals[0] > 0 and vals[1] > 0 and last < 0 and vals[-2] < 0:
            shape = '先扬后抑'
        elif len(vals) >= 4 and vals[0] < 0 and vals[1] < 0 and last > 0 and vals[-2] > 0:
            shape = '先抑后扬'
        elif up > down and last > 0:
            shape = '震荡上行'
        elif down > up and last < 0:
            shape = '震荡下行'
        else:
            shape = '震荡整理'
        return (f"近5日累计{total:+.1f}%（日均涨跌之和）｜{up}涨{down}跌"
                f"｜{shape}，末日{last:+.1f}%")

    # ──────────────────────────────────────────────
    # 7. 全市场资金流向（moneyflow-summary）
    # ──────────────────────────────────────────────
    def get_moneyflow_summary(self, days: int = 20) -> Optional[Dict]:
        """全市场资金流向趋势（DuckDB 缓存 → Tushare 备选回退）"""
        # ── 代理环境变量免疫（与 tushare_provider.py 同步） ──────────
        for _key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
                     'http_proxy', 'https_proxy', 'all_proxy']:
            os.environ.pop(_key, None)

        # 1. DuckDB 缓存（244号全局数据体系：Service 层只读消费）
        try:
            end = datetime.now()
            start = end - timedelta(days=days * 2)
            dm = DataManager()
            cached = dm.get_cached_moneyflow(
                start_date=start.strftime('%Y-%m-%d'),
                end_date=end.strftime('%Y-%m-%d')
            )
            if cached is not None:
                if isinstance(cached, pd.DataFrame) and not cached.empty:
                    records = cached.to_dict('records')
                    result = self._aggregate_moneyflow_by_date(
                        records, days,
                        source_label='DuckDB 资金流向缓存'
                    )
                    if result:
                        has_nonzero = any(
                            abs(d.get('main_force_net_inflow', 0)) > 0.01
                            or abs(d.get('retail_net_inflow', 0)) > 0.01
                            for d in result.get('days', [])
                        )
                        if has_nonzero:
                            return result
                        logger.warning("DuckDB 资金流缓存全部为零值，跳过")
                elif isinstance(cached, list) and len(cached) > 0:
                    result = self._aggregate_moneyflow_by_date(
                        cached, days,
                        source_label='DuckDB 资金流向缓存'
                    )
                    if result:
                        has_nonzero = any(
                            abs(d.get('main_force_net_inflow', 0)) > 0.01
                            or abs(d.get('retail_net_inflow', 0)) > 0.01
                            for d in result.get('days', [])
                        )
                        if has_nonzero:
                            return result
                        logger.warning("DuckDB 资金流缓存全部为零值（list），跳过")
        except Exception as e:
            logger.warning(f"缓存资金流向查询失败: {e}")

        logger.warning("资金流向: 缓存不可用")
        return None

    # ──────────────────────────────────────────────
    # 8. 板块资金流向（sector-moneyflow）
    # ──────────────────────────────────────────────
    @staticmethod
    def _pick_latest_trade_date(date_counts) -> Optional[str]:
        """513 #D1：从 {交易日: 记录数} 中取「最新」且记录数≥50 的交易日。

        原实现取「记录数最多」者；记录数并列时 max 命中先出现的旧日期，
        导致板块资金流向静默回退旧交易日（2026-10-13 实证：10-12 与 10-09
        记录数并列 5573 → 返回 10-09，而源已含 10-12）。
        """
        valid = [d for d, c in date_counts.items() if c >= 50]
        if not valid:
            return None

        def _key(d):
            # 归一为可比较的 YYYYMMDD（兼容 datetime / 'YYYY-MM-DD' / 'YYYYMMDD'）
            if hasattr(d, 'strftime'):
                return d.strftime('%Y%m%d')
            return ''.join(ch for ch in str(d) if ch.isdigit())[:8]

        return max(valid, key=_key)

    def get_sector_moneyflow(self, top_n: int = 8, stocks_per_sector: int = 3,
                             industry_scope: str = 'sw') -> Optional[Dict]:
        """行业板块资金流向 + 个股Top3（DuckDB 缓存 → Tushare 备选回退）

        531 号：默认 `industry_scope='sw'`（申万一级 31 类，与板块热度/走势同口径）；
        `industry_scope='eastmoney'` 保留东财二级 110 类（dim8 板块定位句等既有消费方）。
        """
        # ── 代理环境变量免疫（与 tushare_provider.py 同步） ──────────
        for _key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
                     'http_proxy', 'https_proxy', 'all_proxy']:
            os.environ.pop(_key, None)

        # 1. 行业映射（531：默认申万一级 31 类；eastmoney 分支保留旧 Stock.industry）
        industry_map = {}
        if industry_scope == 'eastmoney':
            try:
                from app import db
                from app.models import Stock
                stocks = db.session.query(Stock.ts_code, Stock.industry).filter(
                    Stock.industry.isnot(None), Stock.industry != ''
                ).all()
                for s in stocks:
                    if s.ts_code and s.industry:
                        industry_map[s.ts_code] = s.industry
            except Exception as e:
                logger.warning(f"行业映射读取失败: {e}")
            if len(industry_map) < 10:
                logger.error(f"行业映射数据不足 ({len(industry_map)} 条)，无法聚合板块资金流向")
                return None
        else:
            from app.data.sw_industry_map import get_sw_industry_map
            industry_map = get_sw_industry_map(
                getattr(getattr(self, 'data_manager', None), 'cache', None))
            if not industry_map:
                logger.error("申万一级行业映射为空，无法聚合板块资金流向")
                return None

        # 2. 从 DuckDB moneyflow_cache 读取最新交易日的资金流向数据
        try:
            dm = DataManager()
            end = datetime.now()
            # 531：窗口放宽到 12 自然日，保证拿到近 5 个交易日（原 5 日仅约 3~4 个交易日）
            start = end - timedelta(days=12)
            cached = dm.get_cached_moneyflow(
                start_date=start.strftime('%Y-%m-%d'),
                end_date=end.strftime('%Y-%m-%d')
            )
            if cached is None:
                logger.warning("板块资金流向: DuckDB 缓存为空")
                return None

            if isinstance(cached, pd.DataFrame):
                records = cached.to_dict('records')
            elif isinstance(cached, list):
                records = cached
            else:
                logger.warning(f"板块资金流向: 缓存格式异常 {type(cached)}")
                return None

            if len(records) < 50:
                logger.warning(f"板块资金流向: 缓存记录数不足 ({len(records)})")
                return None

            from collections import Counter
            date_counts = Counter(r.get('trade_date', '') for r in records)
            # 513 #D1：取「最新」有足够数据的交易日（原按记录数最多，并列时静默回退旧日）
            best_date = self._pick_latest_trade_date(date_counts)
            if not best_date:
                logger.warning(f"板块资金流向: 无足够数据的交易日 ({date_counts})")
                return None

            day_records = [r for r in records if r.get('trade_date') == best_date]
            date_str = best_date
            if isinstance(date_str, datetime):
                date_str = date_str.strftime('%Y%m%d')
            elif hasattr(date_str, 'strftime'):
                date_str = date_str.strftime('%Y%m%d')
            elif isinstance(date_str, str):
                date_str = date_str.replace('-', '')

            result = self._aggregate_sector_moneyflow(
                day_records, industry_map, top_n, stocks_per_sector, date_str
            )
            # 531：近5交易日逐日净流入（申万一级；records 取最新5个交易日）
            # 原 527/528 用「近5自然日全量累计」，窗口仅约3~4个交易日，且无逐日序列。
            mf_dates = sorted({self._norm_trade_date(r.get('trade_date'))
                               for r in records if r.get('trade_date')})
            last5 = mf_dates[-5:]
            from collections import defaultdict as _dd
            sector_daily = _dd(lambda: {d: 0.0 for d in last5})
            for r in records:
                d = self._norm_trade_date(r.get('trade_date'))
                if d not in last5:
                    continue
                ind = self._industry_of(r.get('ts_code', ''), industry_map)
                _sf = self._safe_float
                net = _sf(r.get('buy_lg_amount', 0)) + _sf(r.get('buy_elg_amount', 0)) \
                      - _sf(r.get('sell_lg_amount', 0)) - _sf(r.get('sell_elg_amount', 0))
                sector_daily[ind][d] += net
            sector_net_5d = {ind: sum(v.values()) for ind, v in sector_daily.items()}

            def _enrich_sector_rows(items):
                for s in items:
                    vals = [sector_daily.get(s.get('name'), {}).get(d, 0.0) / 1e4
                            for d in last5]
                    s['net_5d'] = round(sum(vals), 1)
                    s['series_5d'] = [round(v, 2) for v in vals]
                    s['trend_text'] = self._summarize_net_5d(vals)

            _enrich_sector_rows(result.get('sectors') or [])
            _enrich_sector_rows(result.get('out_sectors') or [])
            result['window_5d'] = last5
            top5 = sorted(sector_net_5d.items(), key=lambda x: -x[1])[:5]
            result['trend_5d'] = [
                {'industry': k, 'net_inflow_5d': round(v / 1e4, 1)} for k, v in top5
            ]
            bottom5 = sorted(sector_net_5d.items(), key=lambda x: x[1])[:5]
            result['trend_5d_out'] = [
                {'industry': k, 'net_inflow_5d': round(v / 1e4, 1)} for k, v in bottom5
            ]
            return result
        except Exception as e:
            logger.warning(f"板块资金流向 DuckDB 聚合失败: {e}")

        logger.warning("板块资金流向: 缓存不可用")
        return None

    # ──────────────────────────────────────────────
    # 9. 聚合仪表盘（测试用 — 一次性返回全部数据）
    # ──────────────────────────────────────────────
    def get_dashboard_full(self) -> Optional[Dict]:
        """聚合仪表盘全部数据（一次调用替代 7 次独立请求）"""
        result = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

        try:
            overview = self.get_index_summary()
            if overview:
                result['market_overview'] = overview
        except Exception:
            pass

        try:
            volume = self.get_market_volume()
            if volume:
                result['market_volume'] = volume
        except Exception:
            pass

        try:
            moneyflow = self.get_moneyflow_summary()
            if moneyflow:
                result['moneyflow_summary'] = moneyflow
        except Exception:
            pass

        try:
            sector = self.get_sector_changes()
            if sector:
                result['sector_changes'] = sector
        except Exception:
            pass

        try:
            sec_mf = self.get_sector_moneyflow()
            if sec_mf:
                result['sector_moneyflow'] = sec_mf
        except Exception:
            pass

        try:
            top_up = self.get_daily_top(type='up', limit=10)
            if top_up:
                result['daily_top_up'] = top_up
            top_down = self.get_daily_top(type='down', limit=10)
            if top_down:
                result['daily_top_down'] = top_down
        except Exception:
            pass

        # 533 批次1：大盘总览面板并入聚合载荷
        try:
            overview_panel = self.get_market_overview_panel()
            if overview_panel:
                result['market_overview_panel'] = overview_panel
        except Exception:
            pass

        # 533 批次2：涨停生态并入聚合载荷
        try:
            limit_ecology = self.get_limit_ecology()
            if limit_ecology:
                result['limit_ecology'] = limit_ecology
        except Exception:
            pass

        # 533 批次3：市场资金与杠杆30日并入聚合载荷
        try:
            flows_30d = self.get_market_flows_30d()
            if flows_30d:
                result['market_flows_30d'] = flows_30d
        except Exception:
            pass

        # 524 批次1'：大盘监控三只读接口并入聚合载荷（Q6 全选）
        try:
            breadth = self.get_market_breadth()
            if breadth:
                result['market_breadth'] = breadth
        except Exception:
            pass

        try:
            state = self.get_market_state()
            if state:
                result['market_state'] = state
        except Exception:
            pass

        try:
            emotion = self.get_market_emotion()
            if emotion:
                result['market_emotion'] = emotion
        except Exception:
            pass

        # 524 批次3：板块热度并入聚合载荷（L4 板块卡增强）
        try:
            heat = self.get_sector_heat()
            if heat:
                result['sector_heat'] = heat
        except Exception:
            pass

        # 524 批次4：市场预警并入聚合载荷（L5 预警列表）
        try:
            alerts = self.get_market_alerts()
            if alerts:
                result['market_alerts'] = alerts
        except Exception:
            pass

        # 526 B7：result 恒含 timestamp，原 `if not result` 死分支——改 len<=1 判「空收集」
        if len(result) <= 1:
            return None
        return result

    # ──────────────────────────────────────────────
    # 524 批次1'：大盘监控只读接口（breadth/state/emotion）
    # ──────────────────────────────────────────────
    def get_market_breadth(self) -> Optional[Dict]:
        """市场宽度（524 号 L2 面板原料）：涨跌家数 + 宽度指标。

        数据源：daily_cache⋈daily_basic_cache（前一完整交易日，inner join 纯股票，
                同 523 eod-snapshot 模式）+ E2 market_stats_cache（ma20_ratio/limit_ratio）。
        535 P1：不再取 daily_cache 最新日（10-21 仅 95 只残行），改用
        `_get_best_trade_date(before=today)`；join 样本 <1000 时自动回退再前一交易日。
        全只读，不写任何表。
        """
        try:
            ecm = self.data_manager.cache
            today = datetime.now().strftime('%Y-%m-%d')
            min_stocks = 1000
            as_of = self._get_best_trade_date(before=today)
            candidates = []
            if as_of:
                candidates.append(as_of)
                prev = self._get_best_trade_date(before=as_of)
                if prev and prev not in candidates:
                    candidates.append(prev)
            else:
                date_df = ecm._query_shard(
                    'daily_basic_cache',
                    "SELECT DISTINCT trade_date FROM daily_basic_cache "
                    "ORDER BY trade_date DESC LIMIT 2")
                if date_df is not None and not date_df.empty:
                    candidates = [str(d) for d in date_df['trade_date'].tolist()]

            if not candidates:
                logger.error("市场宽度: daily_cache/daily_basic_cache 无任何历史数据")
                return None

            merged = None
            last_date = None
            for cand in candidates:
                daily_df = ecm._query_shard(
                    'daily_cache',
                    "SELECT ts_code, pct_chg FROM daily_cache WHERE trade_date = ?",
                    [cand])
                if daily_df is None or daily_df.empty:
                    continue
                basic_df = ecm._query_shard(
                    'daily_basic_cache',
                    "SELECT ts_code FROM daily_basic_cache WHERE trade_date = ?",
                    [cand])
                if basic_df is None or basic_df.empty:
                    continue
                cand_merged = daily_df.merge(basic_df, on='ts_code', how='inner')
                if cand_merged.empty:
                    continue
                if merged is None or len(cand_merged) > len(merged):
                    merged, last_date = cand_merged, cand
                if len(cand_merged) >= min_stocks:
                    merged, last_date = cand_merged, cand
                    break

            if merged is None or merged.empty or not last_date:
                logger.error("市场宽度: 候选交易日均无有效 join 数据")
                return None

            count = len(merged)
            data_quality = 'ok' if count >= min_stocks else 'low_sample'
            up = int((merged['pct_chg'] > 0).sum())
            down = int((merged['pct_chg'] < 0).sum())
            flat = count - up - down

            stats = ecm.get_cached_market_stats() or {}
            history = []
            try:
                hist_df = ecm._query_shard(
                    'market_stats_cache',
                    "SELECT stat_date, ma20_ratio, limit_ratio, turnover_percentile "
                    "FROM market_stats_cache ORDER BY stat_date DESC LIMIT 20")
                if hist_df is not None and not hist_df.empty:
                    for _, hr in hist_df.iterrows():
                        history.append({
                            'stat_date': str(hr.get('stat_date', '')),
                            'ma20_ratio': round(float(hr.get('ma20_ratio', 0) or 0) * 100, 1),
                            'limit_ratio': float(hr.get('limit_ratio', 0) or 0),
                            'turnover_percentile': round(float(hr.get('turnover_percentile', 0) or 0) * 100, 1),
                        })
                    history.reverse()
            except Exception:
                pass
            return {
                'trade_date': str(last_date),
                'count': count,
                'data_quality': data_quality,
                'up_count': up,
                'down_count': down,
                'flat_count': flat,
                'up_ratio': round(up / count * 100, 1),
                'down_ratio': round(down / count * 100, 1),
                'ma20_ratio': round(float(stats.get('ma20_ratio', 0)) * 100, 1),
                'limit_ratio': float(stats.get('limit_ratio', 0)),
                'turnover_percentile': round(float(stats.get('turnover_percentile', 0)) * 100, 1),
                'history': history,
                'source': 'DuckDB 盘后数据（前一完整交易日）',
            }
        except Exception as e:
            logger.error(f"市场宽度获取失败: {e}")
            return None

    def get_market_overview_panel(self) -> Optional[Dict]:
        """大盘总览面板（533 号批次1）：前一交易日日终锚定 + 涨跌平 + 近5日强弱家数。

        数据源：daily_cache ⋈ daily_basic_cache（与 523/524 宽度同口径，inner join
        天然排除指数/基金）。`as_of` 固定 today 之前最近完整交易日，避免盘中或
        收盘逐步入库导致数据日切换。全只读，不写任何表。
        """
        try:
            import pandas as pd

            today = datetime.now().strftime('%Y-%m-%d')
            as_of = self._get_best_trade_date(before=today)
            if not as_of:
                logger.error("大盘总览: 无上一交易日数据")
                return None
            prev_date = self._get_best_trade_date(before=as_of)

            ecm = self.data_manager.cache
            dates_df = ecm._query_shard(
                'daily_cache',
                "SELECT DISTINCT trade_date FROM daily_cache "
                "WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 5",
                [as_of])
            if dates_df is None or dates_df.empty:
                logger.error("大盘总览: 近5日交易日为空")
                return None
            dates = sorted(self._norm_trade_date(v)
                           for v in dates_df['trade_date'].tolist())
            placeholders = ','.join('?' for _ in dates)
            df = ecm._query_shard(
                'daily_cache',
                f"SELECT d.trade_date, d.pct_chg FROM daily_cache d "
                f"JOIN daily_basic_cache b "
                f"  ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date "
                f"WHERE d.trade_date IN ({placeholders})", dates)
            if df is None or df.empty:
                logger.error("大盘总览: 近5日涨跌数据为空")
                return None

            by_date = {}
            for raw_date, grp in df.groupby('trade_date'):
                d = self._norm_trade_date(raw_date)
                s = pd.to_numeric(grp['pct_chg'], errors='coerce').dropna()
                total = int(s.count())
                if not total:
                    continue
                up = int((s > 0).sum())
                down = int((s < 0).sum())
                flat = int((s == 0).sum())
                strong = int((s >= 5).sum())
                weak = int((s <= -5).sum())
                by_date[d] = {
                    'trade_date': d,
                    'count': total,
                    'up_count': up,
                    'down_count': down,
                    'flat_count': flat,
                    'up_ratio': round(up / total * 100, 1),
                    'down_ratio': round(down / total * 100, 1),
                    'flat_ratio': round(flat / total * 100, 1),
                    'strong_count': strong,
                    'weak_count': weak,
                    'up_down_ratio': round(up / down, 2) if down else None,
                }

            if as_of not in by_date:
                logger.error(f"大盘总览: as_of={as_of} 无聚合结果")
                return None

            rows = [by_date[d] for d in dates if d in by_date]
            return {
                'as_of': as_of,
                'prev_trade_date': prev_date,
                'breadth': by_date[as_of],
                'prev_breadth': by_date.get(prev_date) if prev_date else None,
                'strong_weak_5d': {
                    'dates': [r['trade_date'] for r in rows],
                    'strong': [r['strong_count'] for r in rows],
                    'weak': [r['weak_count'] for r in rows],
                    'thresholds': {'strong': 5, 'weak': -5},
                },
                'source': 'DuckDB daily_cache ⋈ daily_basic_cache（前一交易日日终）',
            }
        except Exception as e:
            logger.error(f"大盘总览获取失败: {e}")
            return None

    @staticmethod
    def _get_stock_names(ts_codes) -> Dict:
        """Stock 名称/东财行业补全（只取列、分批查询，避免脏行拖垮整批）。

        537 P1：原实现用 `Stock.query` 加载全实体；stocks 表个别 list_date
        存成整数时，SQLAlchemy 解析 Date 列抛 TypeError，整批结果全丢。
        这里只 select 需要的列，并按 900 个代码分批，单批失败不影响其他批。
        """
        codes = [str(c) for c in (ts_codes or []) if c]
        if not codes:
            return {}
        out: Dict = {}
        try:
            from app import db
            from app.models import Stock
            for i in range(0, len(codes), 900):
                batch = codes[i:i + 900]
                try:
                    rows = db.session.query(
                        Stock.ts_code, Stock.name, Stock.industry).filter(
                        Stock.ts_code.in_(batch)).all()
                    out.update({r[0]: {'name': r[1] or '',
                                       'industry': r[2] or ''}
                                for r in rows})
                except Exception as e:
                    logger.warning(
                        f"Stock 名称补全分批失败（{i}~{i + len(batch)}）: {e}")
        except Exception as e:
            logger.warning(f"Stock 名称补全不可用: {e}")
        return out

    def get_limit_ecology(self) -> Optional[Dict]:
        """涨停生态（533 号批次2）：涨停/跌停对比 + 行业个股 + 昨涨停今表现 + 连板 + 5日封板率。

        数据源（拍板：不用 sentiment_pool_cache——其日期错位）：
          - 涨停/炸板/连板：`limit_detail_cache`（Tushare limit_list_d U/Z）；
          - 跌停：`daily_cache + stk_limit_cache` 反算（close <= low_limit）；
          - 行业：申万一级 `stock_sw_industry` 映射，保留 Tushare/东财明细行业。
        所有日期锚定 today 之前最近完整交易日 `as_of`。全只读。
        """
        try:
            import math

            today = datetime.now().strftime('%Y-%m-%d')
            as_of = self._get_best_trade_date(before=today)
            if not as_of:
                logger.error("涨停生态: 无上一交易日数据")
                return None
            prev_date = self._get_best_trade_date(before=as_of)
            ecm = self.data_manager.cache

            dates_df = ecm._query_shard(
                'daily_cache',
                "SELECT DISTINCT trade_date FROM daily_cache "
                "WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 5",
                [as_of])
            if dates_df is None or dates_df.empty:
                logger.error("涨停生态: 近5日交易日为空")
                return None
            dates = sorted(self._norm_trade_date(v)
                           for v in dates_df['trade_date'].tolist())

            from app.data.sw_industry_map import get_sw_industry_map, normalize_code
            try:
                sw_map = get_sw_industry_map(ecm) or {}
            except Exception:
                sw_map = {}

            def _sw(code):
                return sw_map.get(normalize_code(str(code))) or ''

            def _int(v, default=0):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return default

            def _float(v):
                try:
                    f = float(v)
                    return round(f, 2) if math.isfinite(f) else None
                except (TypeError, ValueError):
                    return None

            # 涨停明细（Tushare U）
            up_df = ecm._query_shard(
                'limit_detail_cache',
                "SELECT ts_code, name, industry, pct_chg, limit_times, open_times, "
                "first_time, last_time FROM limit_detail_cache "
                "WHERE trade_date = ? AND limit_type = 'U'", [as_of])
            # 537 P1：区分「当日无涨停」与「当日明细缺失」。
            # limit_detail_cache 整日 0 行时不能把 up.count=0 当成真实行情。
            detail_cnt_df = ecm._query_shard(
                'limit_detail_cache',
                "SELECT COUNT(*) AS n FROM limit_detail_cache "
                "WHERE trade_date = ?", [as_of])
            try:
                limit_detail_count = int(detail_cnt_df.iloc[0].get('n') or 0)
            except Exception:
                limit_detail_count = len(up_df) if up_df is not None else 0
            up_stocks = []
            if up_df is not None and not up_df.empty:
                for r in up_df.to_dict('records'):
                    ts = str(r.get('ts_code') or '')
                    detail_ind = str(r.get('industry') or '')
                    up_stocks.append({
                        'ts_code': ts,
                        'name': str(r.get('name') or ts),
                        'industry': _sw(ts) or detail_ind or '其他',
                        'detail_industry': detail_ind,
                        'pct_chg': _float(r.get('pct_chg')),
                        'limit_times': _int(r.get('limit_times'), 1),
                        'open_times': _int(r.get('open_times'), 0),
                        'first_time': str(r.get('first_time') or ''),
                        'last_time': str(r.get('last_time') or ''),
                    })
            up_stocks.sort(key=lambda x: (-x['limit_times'],
                                          -(x['pct_chg'] or 0), x['ts_code']))

            # 跌停反算（daily + stk_limit；inner join daily_basic 排除指数）
            down_df = ecm._query_shard(
                'daily_cache',
                "SELECT d.ts_code, d.close, d.pct_chg, s.low_limit "
                "FROM daily_cache d "
                "JOIN stk_limit_cache s ON d.ts_code = s.ts_code "
                "  AND d.trade_date = s.trade_date "
                "JOIN daily_basic_cache b ON b.ts_code = d.ts_code "
                "  AND b.trade_date = d.trade_date "
                "WHERE d.trade_date = ? AND d.close <= s.low_limit + 0.001",
                [as_of])
            down_rows = ([] if down_df is None or down_df.empty
                         else down_df.to_dict('records'))
            down_names = self._get_stock_names(
                [str(r.get('ts_code') or '') for r in down_rows])
            down_stocks = []
            for r in down_rows:
                ts = str(r.get('ts_code') or '')
                nm = down_names.get(ts, {})
                detail_ind = nm.get('industry') or ''
                down_stocks.append({
                    'ts_code': ts,
                    'name': nm.get('name') or ts,
                    'industry': _sw(ts) or detail_ind or '其他',
                    'detail_industry': detail_ind,
                    'pct_chg': _float(r.get('pct_chg')),
                    'limit_times': 1,
                    'open_times': 0,
                    'first_time': '',
                    'last_time': '',
                })
            down_stocks.sort(key=lambda x: ((x['pct_chg'] or 0), x['ts_code']))

            def _industries(items, top_n=6):
                from collections import defaultdict
                groups = defaultdict(list)
                for s in items:
                    groups[s['industry']].append(s)
                out = [{'industry': ind, 'count': len(lst), 'stocks': lst[:5]}
                       for ind, lst in groups.items()]
                out.sort(key=lambda x: (-x['count'], x['industry']))
                return out[:top_n]

            # 再之前一个交易日涨停 → 本日表现
            prev_limit = {
                'date': prev_date or '', 'total': 0, 'up_count': 0,
                'down_count': 0, 'flat_count': 0, 'avg_pct': None,
                'win_rate': None, 'stocks': [], 'distribution': [],
            }
            if prev_date:
                prev_df = ecm._query_shard(
                    'limit_detail_cache',
                    "SELECT l.ts_code, l.name, l.industry, l.limit_times, "
                    "d.pct_chg FROM limit_detail_cache l "
                    "LEFT JOIN daily_cache d ON d.ts_code = l.ts_code "
                    "  AND d.trade_date = ? "
                    "WHERE l.trade_date = ? AND l.limit_type = 'U'",
                    [as_of, prev_date])
                prev_stocks = []
                if prev_df is not None and not prev_df.empty:
                    for r in prev_df.to_dict('records'):
                        ts = str(r.get('ts_code') or '')
                        detail_ind = str(r.get('industry') or '')
                        prev_stocks.append({
                            'ts_code': ts,
                            'name': str(r.get('name') or ts),
                            'industry': _sw(ts) or detail_ind or '其他',
                            'detail_industry': detail_ind,
                            'limit_times': _int(r.get('limit_times'), 1),
                            'pct_chg': _float(r.get('pct_chg')),
                        })
                prev_stocks.sort(key=lambda x: (-(x['pct_chg'] or -999),
                                                x['ts_code']))
                total = len(prev_stocks)
                up_c = sum(1 for s in prev_stocks
                           if s['pct_chg'] is not None and s['pct_chg'] > 0)
                down_c = sum(1 for s in prev_stocks
                             if s['pct_chg'] is not None and s['pct_chg'] < 0)
                vals = [s['pct_chg'] for s in prev_stocks
                        if s['pct_chg'] is not None]
                bins = [('<-5%', lambda v: v < -5),
                        ('-5%~0', lambda v: -5 <= v < 0),
                        ('0~5%', lambda v: 0 <= v < 5),
                        ('≥5%', lambda v: v >= 5)]
                prev_limit.update({
                    'total': total,
                    'up_count': up_c,
                    'down_count': down_c,
                    'flat_count': total - up_c - down_c,
                    'avg_pct': round(sum(vals) / len(vals), 2) if vals else None,
                    'win_rate': round(up_c / total * 100, 1) if total else None,
                    'stocks': prev_stocks,
                    'distribution': [
                        {'label': label,
                         'count': sum(1 for v in vals if fn(v))}
                        for label, fn in bins
                    ],
                })

            # 连板天梯 + 板数分布
            boards = [s for s in up_stocks if s['limit_times'] >= 2]
            board_dist = {}
            for s in up_stocks:
                board_dist[s['limit_times']] = board_dist.get(s['limit_times'], 0) + 1

            # 近5日封板率 = U/(U+Z)
            seal_map = {}
            placeholders = ','.join('?' for _ in dates)
            seal_df = ecm._query_shard(
                'limit_detail_cache',
                "SELECT trade_date, "
                "SUM(CASE WHEN limit_type='U' THEN 1 ELSE 0 END) AS up_cnt, "
                "SUM(CASE WHEN limit_type='Z' THEN 1 ELSE 0 END) AS zha_cnt "
                "FROM limit_detail_cache "
                f"WHERE trade_date IN ({placeholders}) GROUP BY trade_date",
                dates)
            if seal_df is not None and not seal_df.empty:
                for r in seal_df.to_dict('records'):
                    seal_map[self._norm_trade_date(r.get('trade_date'))] = (
                        _int(r.get('up_cnt')), _int(r.get('zha_cnt')))
            seal_rows = []
            for d in dates:
                up_c, zha_c = seal_map.get(d, (0, 0))
                seal_rows.append({
                    'date': d, 'limit_up': up_c, 'zhaban': zha_c,
                    'rate': (round(up_c / (up_c + zha_c) * 100, 1)
                             if up_c + zha_c else None),
                })

            return {
                'as_of': as_of,
                'data_available': limit_detail_count > 0,
                'limit_detail_count': limit_detail_count,
                'prev_trade_date': prev_date,
                'up': {
                    'count': len(up_stocks),
                    'industries': _industries(up_stocks),
                    'stocks': up_stocks,
                },
                'down': {
                    'count': len(down_stocks),
                    'industries': _industries(down_stocks),
                    'stocks': down_stocks,
                },
                'prev_limit_up': prev_limit,
                'boards': {
                    'count': len(boards),
                    'max_height': max((s['limit_times'] for s in up_stocks),
                                      default=0),
                    'distribution': [{'days': k, 'count': v}
                                     for k, v in sorted(board_dist.items())],
                    'stocks': boards,
                },
                'sealing_5d': {'dates': dates, 'rows': seal_rows},
                'source': ('Tushare limit_detail_cache U/Z + '
                           'DuckDB daily/stk_limit（跌停反算）'),
            }
        except Exception as e:
            logger.error(f"涨停生态获取失败: {e}")
            return None

    @staticmethod
    def _split_complete_rows(rows, min_cov: float = 0.8):
        """537 P1：剔除覆盖度骤降的日期，返回 (保留行, 不完整日期列表)。

        以当日行数 n 的中位数为基线；n < 中位数 × min_cov 视为不完整。
        n 缺失或为 0 时无法判定，保留（兼容旧数据/单测桩）。
        """
        if not rows:
            return [], []
        nums = sorted(int(r.get('n') or 0) for r in rows
                      if int(r.get('n') or 0) > 0)
        if not nums:
            return list(rows), []
        threshold = nums[len(nums) // 2] * min_cov
        kept, partial = [], []
        for r in rows:
            n = int(r.get('n') or 0)
            if n and n < threshold:
                partial.append(r.get('date', ''))
            else:
                kept.append(r)
        return kept, partial

    def get_market_flows_30d(self) -> Optional[Dict]:
        """市场资金与杠杆30日（533号批次3）：5日行业资金×涨跌 + 30日ETF份额 + 30日融资。

        数据源：moneyflow_cache + daily_cache（申万一级）、fund_share_cache（ETF份额，
        fd_share 万份 -> 亿份）、margin_cache（rzye/rzmje/rzrqye 万元 -> 亿元）。
        所有日期锚定 today 之前最近完整交易日 as_of；全只读。
        """
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            as_of = self._get_best_trade_date(before=today)
            if not as_of:
                logger.error("市场资金30日: 无上一交易日数据")
                return None
            ecm = self.data_manager.cache

            dates_df = ecm._query_shard(
                'daily_cache',
                "SELECT DISTINCT trade_date FROM daily_cache "
                "WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 5",
                [as_of])
            dates5 = []
            if dates_df is not None and not dates_df.empty:
                dates5 = sorted(self._norm_trade_date(v)
                                for v in dates_df['trade_date'].tolist())

            industry_rows = []
            if len(dates5) >= 2:
                history = self._get_sector_history_20d(days=5, as_of=as_of)
                change_map = {}
                for ind, vals in (history.get('industries') or {}).items():
                    change_map[str(ind)] = round(
                        sum(float(v or 0) for v in vals), 2)

                from app.data.sw_industry_map import get_sw_industry_map
                sw_map = get_sw_industry_map(ecm) or {}
                placeholders = ','.join('?' for _ in dates5)
                mf_df = ecm._query_shard(
                    'moneyflow_cache',
                    "SELECT ts_code, buy_lg_amount, buy_elg_amount, "
                    "sell_lg_amount, sell_elg_amount FROM moneyflow_cache "
                    f"WHERE trade_date IN ({placeholders})", dates5)
                net_by_ind = {}
                if mf_df is not None and not mf_df.empty:
                    for r in mf_df.to_dict('records'):
                        code = str(r.get('ts_code') or '')
                        ind = sw_map.get(code.split('.')[0]) or ''
                        if not ind:
                            continue
                        net = (self._safe_float(r.get('buy_lg_amount'))
                               + self._safe_float(r.get('buy_elg_amount'))
                               - self._safe_float(r.get('sell_lg_amount'))
                               - self._safe_float(r.get('sell_elg_amount')))
                        net_by_ind[ind] = net_by_ind.get(ind, 0.0) + net
                for ind in sorted(set(change_map) | set(net_by_ind)):
                    industry_rows.append({
                        'industry': ind,
                        'net_inflow_5d': round(net_by_ind.get(ind, 0.0) / 1e4, 1),
                        'change_5d': round(change_map.get(ind, 0.0), 2),
                    })
                industry_rows.sort(key=lambda x: -x['net_inflow_5d'])

            etf_dates, etf_net, etf_total, etf_top = [], [], [], []
            etf_cum = None
            etf_partial = []
            try:
                fdf = ecm._query_shard(
                    'fund_share_cache',
                    "SELECT trade_date, SUM(fd_share) AS total_share, "
                    "COUNT(*) AS n "
                    "FROM fund_share_cache WHERE fund_type = 'ETF' "
                    "AND trade_date <= ? GROUP BY trade_date "
                    "ORDER BY trade_date DESC LIMIT 31", [as_of])
                rows = []
                if fdf is not None and not fdf.empty:
                    rows = sorted(
                        ({'date': self._norm_trade_date(r.get('trade_date')),
                          'total': float(r.get('total_share') or 0),
                          'n': int(r.get('n') or 0)}
                         for r in fdf.to_dict('records')),
                        key=lambda x: x['date'])
                rows, etf_partial = self._split_complete_rows(rows)
                if len(rows) >= 2:
                    first, last = rows[0], rows[-1]
                    for i in range(1, len(rows)):
                        cur, prev = rows[i], rows[i - 1]
                        etf_dates.append(cur['date'])
                        etf_total.append(round(cur['total'] / 1e4, 1))
                        etf_net.append(round(
                            (cur['total'] - prev['total']) / 1e4, 1))
                    etf_cum = round(
                        (last['total'] - first['total']) / 1e4, 1)
                    top_df = ecm._query_shard(
                        'fund_share_cache',
                        "SELECT a.ts_code, a.fd_share - b.fd_share AS delta "
                        "FROM fund_share_cache a "
                        "JOIN fund_share_cache b ON a.ts_code = b.ts_code "
                        "WHERE a.trade_date = ? AND b.trade_date = ? "
                        "AND a.fund_type = 'ETF' "
                        "ORDER BY delta DESC LIMIT 8",
                        [last['date'], first['date']])
                    top_rows = ([] if top_df is None or top_df.empty
                                else top_df.to_dict('records'))
                    codes = [str(r.get('ts_code') or '') for r in top_rows]
                    name_map = {}
                    if codes:
                        try:
                            ph = ','.join('?' for _ in codes)
                            ndf = ecm._query_shard(
                                'etf_industry_map',
                                "SELECT ts_code, fund_name FROM etf_industry_map "
                                f"WHERE ts_code IN ({ph})", codes)
                            if ndf is not None and not ndf.empty:
                                name_map = {
                                    str(r.get('ts_code')):
                                    str(r.get('fund_name') or '')
                                    for r in ndf.to_dict('records')}
                        except Exception:
                            name_map = {}
                    for r in top_rows:
                        code = str(r.get('ts_code') or '')
                        etf_top.append({
                            'ts_code': code,
                            'name': name_map.get(code) or code,
                            'net_share': round(
                                float(r.get('delta') or 0) / 1e4, 1),
                        })
            except Exception as e:
                logger.warning(f"市场资金30日: ETF份额聚合失败: {e}")

            margin_dates, margin_balance, margin_buy = [], [], []
            short_balance, margin_net = [], []
            margin_latest, margin_cum = {}, None
            margin_partial = []
            try:
                mdf = ecm._query_shard(
                    'margin_cache',
                    "SELECT trade_date, SUM(rzye) AS rzye, "
                    "SUM(rzmje) AS rzmje, SUM(rzrqye) AS rzrqye, "
                    "COUNT(*) AS n "
                    "FROM margin_cache WHERE trade_date <= ? "
                    "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 31",
                    [as_of])
                rows = []
                if mdf is not None and not mdf.empty:
                    rows = sorted(
                        ({'date': self._norm_trade_date(r.get('trade_date')),
                          'rzye': float(r.get('rzye') or 0),
                          'rzmje': float(r.get('rzmje') or 0),
                          'rzrqye': float(r.get('rzrqye') or 0),
                          'n': int(r.get('n') or 0)}
                         for r in mdf.to_dict('records')),
                        key=lambda x: x['date'])
                rows, margin_partial = self._split_complete_rows(rows)
                if len(rows) >= 2:
                    for i in range(1, len(rows)):
                        cur, prev = rows[i], rows[i - 1]
                        margin_dates.append(cur['date'])
                        margin_balance.append(round(cur['rzye'] / 1e8, 1))
                        margin_buy.append(round(cur['rzmje'] / 1e8, 1))
                        short_balance.append(round(
                            (cur['rzrqye'] - cur['rzye']) / 1e8, 1))
                        margin_net.append(round(
                            (cur['rzye'] - prev['rzye']) / 1e8, 1))
                    margin_cum = round(sum(margin_net), 1)
                    last = rows[-1]
                    margin_latest = {
                        'date': last['date'],
                        'margin_balance': round(last['rzye'] / 1e8, 1),
                        'margin_buy': round(last['rzmje'] / 1e8, 1),
                        'short_balance': round(
                            (last['rzrqye'] - last['rzye']) / 1e8, 1),
                    }
            except Exception as e:
                logger.warning(f"市场资金30日: 融资聚合失败: {e}")

            return {
                'as_of': as_of,
                'industry_flow_5d': {
                    'dates': dates5,
                    'industries': industry_rows,
                },
                'etf_30d': {
                    'dates': etf_dates,
                    'net_share': etf_net,
                    'total_share': etf_total,
                    'cumulative_net_share': etf_cum,
                    'top_etfs': etf_top,
                    'partial_dates': etf_partial,
                    'data_quality': 'partial' if etf_partial else 'ok',
                },
                'margin_30d': {
                    'dates': margin_dates,
                    'margin_balance': margin_balance,
                    'margin_buy': margin_buy,
                    'short_balance': short_balance,
                    'net_buy': margin_net,
                    'cumulative_net_buy': margin_cum,
                    'latest': margin_latest,
                    'partial_dates': margin_partial,
                    'data_quality': 'partial' if margin_partial else 'ok',
                },
                'source': ('DuckDB moneyflow/daily（申万一级）+ '
                           'fund_share_cache + margin_cache'),
            }
        except Exception as e:
            logger.error(f"市场资金30日获取失败: {e}")
            return None

    def get_market_state(self) -> Optional[Dict]:
        """大盘状态（524 号 L1 页头徽标原料）：4 状态·状态机。

        数据源：E2 market_stats_cache（turnover_percentile/limit_ratio）
                + BenchmarkService 沪深300 近60日趋势（481 _index_trend_sentence 同源）。
        判定规则（wiki《状态机市场识别模型》简化落地，阈值可拍板调整）：
          - 高波动：turnover_percentile ≥ 0.85 且指数近20日 |涨跌| ≥ 5%
          - 上升趋势：指数近20日涨跌 ≥ 3% 且收盘 ≥ 60日线
          - 下降趋势：指数近20日涨跌 ≤ -3% 且收盘 ≤ 60日线
          - 盘整：近20日 |涨跌| < 2% 且 turnover_percentile < 0.4
          - 震荡：其余（默认）
        """
        try:
            ecm = self.data_manager.cache
            stats = ecm.get_cached_market_stats()
            turnover_pct = float(stats.get('turnover_percentile', 0.5))
            limit_ratio = float(stats.get('limit_ratio', 0))

            from app.services.benchmark_service import BenchmarkIndex, BenchmarkService
            bs = BenchmarkService(self.data_manager)
            df = bs.get_index_daily(BenchmarkIndex.HS300)
            ret20 = ret60 = price = ma60 = None
            if df is not None and not df.empty:
                df = df.sort_values('trade_date')
                # 525 A2：dropna 过滤 NaN 收盘价（否则 NaN 传播至 price/ma60 →
                # _classify_state 比较 NaN 全落 ranging 静默降级）
                closes = df['close'].astype(float).dropna()
                if len(closes) > 0:
                    price = float(closes.iloc[-1])
                if len(closes) >= 21:
                    ret20 = float(round((closes.iloc[-1] / closes.iloc[-21] - 1) * 100, 2))
                if len(closes) >= 61:
                    ret60 = float(round((closes.iloc[-1] / closes.iloc[-61] - 1) * 100, 2))
                if len(closes) >= 60:
                    ma60 = float(closes.iloc[-60:].mean())

            state, state_label = self._classify_state(turnover_pct, ret20, price, ma60)

            return {
                'state': state,
                'state_label': state_label,
                'data_date': stats.get('computed_at', ''),
                'basis': {
                    'hs300_ret_20d': ret20,
                    'hs300_ret_60d': ret60,
                    'hs300_close': price,
                    'hs300_ma60': ma60,
                    'turnover_percentile': round(turnover_pct * 100, 1),
                    'limit_ratio': limit_ratio,
                },
                'source': 'DuckDB market_stats + BenchmarkService',
            }
        except Exception as e:
            logger.error(f"大盘状态获取失败: {e}")
            return None

    @staticmethod
    def _classify_state(turnover_pct: float, ret20, price, ma60):
        """4 状态·状态机判定（524 号 Q1 拍板；供 get_market_state / get_market_alerts 复用）。

        规则（wiki《状态机市场识别模型》简化落地，阈值可拍板调整）：
          - 高波动：turnover ≥ 0.85 且近20日 |涨跌| ≥ 5%
          - 上升趋势：近20日涨跌 ≥ 3% 且收盘 ≥ 60日线
          - 下降趋势：近20日涨跌 ≤ -3% 且收盘 ≤ 60日线
          - 盘整：近20日 |涨跌| < 2% 且 turnover < 0.4
          - 震荡：其余（默认）
        """
        state, state_label = 'ranging', '震荡'
        if turnover_pct >= 0.85 and ret20 is not None and abs(ret20) >= 5:
            state, state_label = 'high_volatility', '高波动'
        elif ret20 is not None and ret20 >= 3 and price is not None and ma60 is not None and price >= ma60:
            state, state_label = 'trend_up', '上升趋势'
        elif ret20 is not None and ret20 <= -3 and price is not None and ma60 is not None and price <= ma60:
            state, state_label = 'trend_down', '下降趋势'
        elif ret20 is not None and abs(ret20) < 2 and turnover_pct < 0.4:
            state, state_label = 'consolidation', '盘整'
        return state, state_label

    def get_market_emotion(self, trade_date: Optional[str] = None) -> Optional[Dict]:
        """市场情绪（524 号 L3 温度计原料）：六段论阶段 + 涨停生态指标。

        535 P1：优先使用 `limit_detail_cache` 的权威涨停/跌停/连板/封板率
        （与 `/market/limit-ecology` 一致），不再让 sentiment_pool 的
        日期错位数据（10-20 池 102 家）与涨停生态 54 家并存。
        sentiment_pool 仅在 limit_detail 不可用时回退。
        """
        try:
            from app.services.market_sentiment_service import MarketSentimentService
            mss = MarketSentimentService(self.data_manager)
            if trade_date is None:
                today = datetime.now().strftime('%Y-%m-%d')
                as_of = self._get_best_trade_date(before=today)
                trade_date = as_of.replace('-', '') if as_of else None

            eco = self.get_limit_ecology()
            eco_date = str((eco or {}).get('as_of') or '').replace('-', '')
            eco_up = int((eco or {}).get('up', {}).get('count') or 0)
            eco_down = int((eco or {}).get('down', {}).get('count') or 0)
            if (eco and eco.get('data_available', True)
                    and (not trade_date or eco_date == trade_date)
                    and (eco_up + eco_down) > 0):
                up = eco_up
                down = eco_down
                boards = eco.get('boards') or {}
                seal_rows = (eco.get('sealing_5d') or {}).get('rows') or []
                sealing = (float(seal_rows[-1].get('rate') or 0.0)
                           if seal_rows else 0.0)
                metrics = {
                    'limit_up_count': up,
                    'limit_down_count': down,
                    'max_board_height': int(boards.get('max_height') or 0),
                    'sealing_rate': sealing,
                    'up_down_ratio': round(up / max(down, 1), 2),
                }
                phase_data = mss.get_sentiment_phase(
                    trade_date=trade_date, metrics_override=metrics)
                source = 'limit_detail_cache 涨停生态 + 六段论'
            else:
                phase_data = mss.get_sentiment_phase(trade_date=trade_date)
                source = 'sentiment_pool_cache 六段论（limit_detail 不可用回退）'

            return {
                'phase': phase_data.get('phase', 'neutral'),
                'phase_label': phase_data.get('phase_label', '情绪中性'),
                'metrics': phase_data.get('metrics', {}),
                'data_available': phase_data.get('data_available', False),
                'data_date': trade_date or '',
                'source': source,
            }
        except Exception as e:
            logger.error(f"市场情绪获取失败: {e}")
            return None

    def get_sector_heat(self, top_n: int = 8) -> Optional[Dict]:
        """板块热度/排名（524 号 L4，530号 批次2 方向 B：改读资金热度表）。

        数据源：优先 `sector_fund_heat_cache`（530号 RAW-2D 预计算——板块近5日主力净流入
        ÷ 流通市值占比排序，消除成分股基数差异，方向 B 独立表）；为空（RAW-2D 未跑）时
        回退 `sector_heat_cache`（MA5>MA20 个股占比，419 方案B3）。
        → `{date, count, source, sectors:[{industry, heat_level, rank, ratio|strength,
        net_inflow_5d, circ_mv, stock_count, prev_rank}]}`
        全只读；rank 越小越热（升序取 top_n）。heat_level 枚举 top_10/top_20/normal/none。
        527 批次2：附前一日 rank（prev_rank）供前端「排名变化/新进榜」说明。
        """
        try:
            ecm = self.data_manager.cache
            # 530号 方向 B：优先资金热度（sector_fund_heat_cache）
            fund_heat = ecm.get_cached_sector_fund_heat()
            source = 'fund'
            if fund_heat:
                heat = fund_heat
                heat_date_col = 'sector_fund_heat_cache'
                heat_getter = ecm.get_cached_sector_fund_heat
            else:
                heat = ecm.get_cached_sector_heat()
                source = 'trend'
                heat_date_col = 'sector_heat_cache'
                heat_getter = ecm.get_cached_sector_heat
            if not heat:
                logger.error("板块热度: sector_fund_heat_cache 与 sector_heat_cache 均无数据")
                return None
            sectors = []
            for ind, info in heat.items():
                if not ind or str(ind).strip().lower() in ('nan', 'none', ''):
                    continue
                if source == 'fund':
                    sectors.append({
                        'industry': str(ind),
                        'heat_level': str(info.get('heat_level', 'none')),
                        'ratio': float(info.get('ratio', 0.0)),
                        'net_inflow_5d': float(info.get('net_inflow_5d', 0.0)),
                        'circ_mv': float(info.get('circ_mv', 0.0)),
                        'rank': int(info.get('rank', 999)),
                    })
                else:
                    sectors.append({
                        'industry': str(ind),
                        'heat_level': str(info.get('heat_level', 'none')),
                        'strength': float(info.get('strength', 0.0)),
                        'rank': int(info.get('rank', 999)),
                        'stock_count': int(info.get('stock_count', 0)),
                    })
            sectors.sort(key=lambda x: x['rank'])
            date = ''
            try:
                date_df = ecm._query_shard(
                    heat_date_col, "SELECT MAX(stat_date) AS d FROM " + heat_date_col)
                if date_df is not None and not date_df.empty and date_df['d'].iloc[0]:
                    date = str(date_df['d'].iloc[0])
            except Exception:
                pass
            # 527 批次2：前一日 rank 对比（prev_rank；同源表读上一 stat_date 全行业）
            prev_rank_map = {}
            try:
                dates_df = ecm._query_shard(
                    heat_date_col,
                    "SELECT DISTINCT stat_date FROM " + heat_date_col +
                    " ORDER BY stat_date DESC LIMIT 2")
                if dates_df is not None and not dates_df.empty and len(dates_df) >= 2:
                    prev_date = str(dates_df['stat_date'].iloc[1])
                    prev_heat = heat_getter(stat_date=prev_date)
                    for ind, info in prev_heat.items():
                        if not ind or str(ind).strip().lower() in ('nan', 'none', ''):
                            continue
                        prev_rank_map[str(ind)] = int(info.get('rank', 999))
            except Exception:
                pass
            for s in sectors:
                s['prev_rank'] = prev_rank_map.get(s['industry'])
            return {
                'date': date,
                'count': len(sectors),
                'source': ('DuckDB sector_fund_heat_cache（资金占比，方向 B）'
                           if source == 'fund' else 'DuckDB sector_heat_cache（趋势，MA5>MA20）'),
                'sectors': sectors[:top_n],
            }
        except Exception as e:
            logger.error(f"板块热度获取失败: {e}")
            return None

    def get_sector_heat_dim(self, top_n: int = 31) -> Optional[Dict]:
        """板块热度五维（532 号批次3）：31 行业全量 + KPI + 阶段判定依据。

        数据源：RAW-2E 独立表 `sector_heat_dim_cache`（compute_cache.db）。
        旧 `sector_heat_cache` / `sector_fund_heat_cache` 不参与本方法；无数据返回 None。
        """
        try:
            payload = self.data_manager.get_cached_sector_heat_dim()
            rows = payload.get('rows') or []
            if not rows:
                logger.warning("板块热度五维: sector_heat_dim_cache 无数据")
                return None

            from app.data.sector_heat_dim import load_config
            from app.engine.framework.sector_heat_composite import DEFAULT_CONFIG
            cfg = load_config() or {}
            th = {**DEFAULT_CONFIG['thresholds'], **(cfg.get('thresholds') or {})}
            healthy_vp = set(cfg.get('healthy_vp') or DEFAULT_CONFIG['healthy_vp'])
            prev_rank = payload.get('prev_rank') or {}
            prev_date = payload.get('prev_date') or ''

            def _num(v):
                try:
                    return None if v is None else float(v)
                except (TypeError, ValueError):
                    return None

            sectors = []
            for r in rows:
                res = _num(r.get('rps_resonance')) or 0.0
                rps20 = _num(r.get('rps_20'))
                rps60 = _num(r.get('rps_60'))
                rps120 = _num(r.get('rps_120'))
                up = _num(r.get('up_ratio'))
                fund_ratio = _num(r.get('fund_ratio'))
                vp_state = str(r.get('vp_state') or '')
                limit_up = _num(r.get('limit_up_ratio'))
                zhaban = _num(r.get('zhaban_ratio'))
                amount_share = _num(r.get('amount_share'))
                crowding = _num(r.get('dim_sentiment'))
                vol_ratio = _num(r.get('vol_ratio_5d'))

                rules = {
                    'overheat': bool(
                        (limit_up is not None and zhaban is not None
                         and limit_up >= th['limit_up_ratio'] and zhaban >= th['zhaban_ratio'])
                        or (amount_share is not None and rps120 is not None
                            and amount_share >= th['amount_share']
                            and rps120 >= th['rps120_overheat'])
                        or (crowding is not None and crowding >= th['crowding_overheat'])),
                    'mainline': bool(
                        res >= 2 and up is not None and up >= th['up_ratio_main']
                        and fund_ratio is not None and fund_ratio > 0
                        and vp_state in healthy_vp),
                    'pulse': bool(
                        rps20 is not None and rps20 >= th['rps_very_strong']
                        and ((rps60 is not None and rps60 < 60)
                             or (up is not None and up < th['up_ratio_weak']))),
                    'cold': bool(
                        rps20 is not None and rps20 < th['rps_cold']
                        and vol_ratio is not None and vol_ratio < th['vol_cold']
                        and fund_ratio is not None and fund_ratio > 0),
                }

                flags = list(r.get('flags') or [])
                coverage = r.get('coverage') or {}
                if coverage.get('etf') is False:
                    if 'etf_coverage_low' not in flags:
                        flags.append('etf_coverage_low')
                elif 'etf_coverage_low' in flags:
                    flags.remove('etf_coverage_low')

                sectors.append({**r, 'flags': flags, 'rules': rules,
                                'prev_rank': prev_rank.get(r.get('industry'))})

            scores = [s['quality_score'] for s in sectors
                      if s.get('quality_score') is not None]
            median_quality = round(statistics.median(scores), 2) if scores else None

            prev_median = None
            if prev_date:
                try:
                    prev_payload = self.data_manager.get_cached_sector_heat_dim(
                        stat_date=prev_date)
                    prev_scores = [x['quality_score'] for x in (prev_payload.get('rows') or [])
                                   if x.get('quality_score') is not None]
                    if prev_scores:
                        prev_median = statistics.median(prev_scores)
                except Exception:
                    prev_median = None

            stage_counts = {k: 0 for k in
                            ('mainline', 'pulse', 'overheat', 'cold', 'neutral')}
            for s in sectors:
                stage = s.get('stage', 'neutral')
                stage_counts[stage] = stage_counts.get(stage, 0) + 1

            etf_ok = sum(1 for s in sectors
                         if (s.get('coverage') or {}).get('etf') is True)
            coverage = {
                'etf_pct': round(etf_ok / len(sectors) * 100, 1),
                'northbound': any(bool((s.get('coverage') or {}).get('northbound'))
                                  for s in sectors),
            }

            sectors.sort(key=lambda x: (x.get('rank') is None, x.get('rank') or 999,
                                        x.get('industry') or ''))
            return {
                'date': payload.get('date') or '',
                'prev_date': prev_date,
                'count': len(sectors),
                'stage_counts': stage_counts,
                'median_quality': median_quality,
                'median_quality_delta': (
                    round(median_quality - prev_median, 2)
                    if median_quality is not None and prev_median is not None else None),
                'coverage': coverage,
                'sectors': sectors[:top_n],
            }
        except Exception as e:
            logger.error(f"板块热度五维获取失败: {e}")
            return None

    def get_market_alerts(self) -> Optional[Dict]:
        """市场预警（524 号 L5）：四条规则 + 建议输出（建议型、非强制，495 B1）。

        数据源：emotion（R1 冰点）/ market_stats 近20日 margin_trend + HS300 近5日
        （R2 拥挤背离）/ breadth（R3 宽度极端）/ 前日 vs 今日 4 状态（R4 状态切换）。
        全只读；规则与阈值可拍板调整（wiki《关键交易日识别与验证框架》《情绪拥挤度
        因子》《状态机市场识别模型》依据）。
        """
        try:
            alerts = []

            # R1 冰点 → 关键上涨窗口（六段论 ice；涨停生态萎缩）
            emotion = self.get_market_emotion()
            if (emotion and emotion.get('data_available', True)
                    and emotion.get('phase') == 'ice'):
                alerts.append({
                    'level': 'info',
                    'type': 'ice_window',
                    'title': '情绪冰点，接近关键上涨窗口',
                    'detail': '六段论进入冰点期（涨停家数萎缩、最高连板低、封板率低），'
                              '历史经验上冰点+慢线极值后关键上涨日概率上升（建议型，非强制）',
                    'source': 'market/emotion phase=ice',
                })

            # R2 融资拥挤背离 → 顶部风险（margin_trend 近20日 80 分位 + HS300 近5日涨幅≤0）
            try:
                ecm = self.data_manager.cache
                mdf = ecm._query_shard(
                    'market_stats_cache',
                    "SELECT stat_date, margin_trend FROM market_stats_cache "
                    "ORDER BY stat_date DESC LIMIT 20")
                if mdf is not None and not mdf.empty:
                    vals = [float(v) for v in mdf['margin_trend'].tolist()
                            if v is not None and v == v]
                    if len(vals) >= 10:
                        s_vals = sorted(vals)
                        # 525 A3：小样本 80 分位有偏——近20日窗口 len≈10 时
                        # int(len*0.8)-1 取 index 7（第三大），非严格 80 分位；
                        # 仅作拥挤度提示（建议型），可接受，不做精确分位
                        p80 = s_vals[int(len(s_vals) * 0.8) - 1]
                        cur = float(vals[0])  # 最新日（DESC 首行）
                        if cur >= p80:
                            from app.services.benchmark_service import (
                                BenchmarkIndex,
                                BenchmarkService,
                            )
                            bs = BenchmarkService(self.data_manager)
                            bdf = bs.get_index_daily(BenchmarkIndex.HS300)
                            ret5 = None
                            if bdf is not None and not bdf.empty:
                                closes = bdf['close'].astype(float).tolist()
                                if len(closes) >= 6:
                                    ret5 = float((closes[-1] / closes[-6] - 1) * 100)
                            if ret5 is not None and ret5 <= 0:
                                alerts.append({
                                    'level': 'warning',
                                    'type': 'crowding_top',
                                    'title': '融资拥挤背离，警惕顶部风险',
                                    'detail': f'融资增速处于近20日 80 分位上方（当前 {cur:.2f}），'
                                              f'但沪深300 近5日涨幅 {ret5:.2f}%≤0——资金与价格背离'
                                              '（建议型，非强制）',
                                    'source': 'market_stats.margin_trend + HS300',
                                })
            except Exception as e:
                logger.debug(f"R2 拥挤背离计算失败: {e}")

            # R3 宽度极端 → 反转提示（上涨占比 ≥85% 或 ≤15%）
            breadth = self.get_market_breadth()
            if breadth and breadth.get('up_ratio') is not None:
                up_r = float(breadth['up_ratio'])
                if up_r >= 85:
                    alerts.append({
                        'level': 'warning',
                        'type': 'breadth_extreme',
                        'title': '上涨宽度极端，警惕短线反转',
                        'detail': f'上涨家数占比 {up_r:.1f}%≥85%，市场短线过热'
                                  '（建议型，非强制）',
                        'source': 'market/breadth up_ratio',
                    })
                elif up_r <= 15:
                    alerts.append({
                        'level': 'info',
                        'type': 'breadth_extreme',
                        'title': '下跌宽度极端，警惕情绪修复',
                        'detail': f'上涨家数占比 {up_r:.1f}%≤15%，市场极度低迷'
                                  '（建议型，非强制）',
                        'source': 'market/breadth up_ratio',
                    })

            # R4 状态切换 → 风控提示（前日 vs 今日 4 状态不同且含趋势/高波动参与）
            today = self.get_market_state()
            if today and today.get('state'):
                prev_state = self._get_prev_market_state()
                cur_state = today['state']
                if prev_state and prev_state != cur_state:
                    _big = {'trend_up', 'trend_down', 'high_volatility'}
                    if prev_state in _big or cur_state in _big:
                        alerts.append({
                            'level': 'danger',
                            'type': 'state_switch',
                            'title': f'大盘状态切换：{prev_state} → {cur_state}',
                            'detail': '4 状态·状态机发生切换且涉及趋势/高波动——'
                                      '波动环境变化，注意仓位与风险控制（建议型，非强制）',
                            'source': 'market/state 前日 vs 今日',
                        })

            return {
                'date': (today or {}).get('data_date', ''),
                'count': len(alerts),
                'alerts': alerts,
                'source': 'DuckDB market_stats + HS300 + emotion + breadth',
            }
        except Exception as e:
            logger.error(f"市场预警获取失败: {e}")
            return None

    def _get_prev_market_state(self) -> Optional[str]:
        """前一交易日 4 状态（524 L5 R4 状态切换对比）。

        取 market_stats_cache 倒数第二日 turnover_percentile + HS300 剔除最新一日
        后重算 ret20/ma60，复用 `_classify_state`。
        """
        try:
            ecm = self.data_manager.cache
            sdf = ecm._query_shard(
                'market_stats_cache',
                "SELECT * FROM market_stats_cache ORDER BY stat_date DESC LIMIT 2")
            if sdf is None or sdf.empty or len(sdf) < 2:
                return None
            prev = sdf.iloc[1]
            turnover_pct = float(prev.get('turnover_percentile', 0.5))

            from app.services.benchmark_service import BenchmarkIndex, BenchmarkService
            bs = BenchmarkService(self.data_manager)
            bdf = bs.get_index_daily(BenchmarkIndex.HS300)
            if bdf is None or bdf.empty or len(bdf) < 62:
                return None
            closes = bdf['close'].astype(float).tolist()
            closes = closes[:-1]  # 剔除最新一日（今日）
            if len(closes) < 61:
                return None
            price = float(closes[-1])
            ret20 = float((closes[-1] / closes[-21] - 1) * 100)
            ma60 = float(sum(closes[-60:]) / 60)
            state, _ = self._classify_state(turnover_pct, ret20, price, ma60)
            return state
        except Exception as e:
            logger.debug(f"前日状态计算失败: {e}")
            return None

    # ──────────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────────

    @staticmethod
    def _safe_float(v, default=0.0):
        """安全转换 float，处理 NaN/None"""
        try:
            f = float(v)
            if f != f:  # NaN != NaN
                return default
            return f
        except (ValueError, TypeError):
            return default

    def _try_get_latest_trade_date(self) -> Optional[str]:
        """获取最近可用的交易日（YYYYMMDD），优先 DuckDB daily_cache → 推算"""
        try:
            ecm = self.data_manager.cache
            date_df = ecm._query_shard(
                'daily_cache',
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
            if not date_df.empty:
                return str(date_df['trade_date'].iloc[0]).replace('-', '')
        except Exception:
            pass
        # 推算：如果今日为周末，取上周五
        today = datetime.now()
        weekday = today.weekday()
        if weekday == 5:  # 周六
            return (today - timedelta(days=1)).strftime('%Y%m%d')
        elif weekday == 6:  # 周日
            return (today - timedelta(days=2)).strftime('%Y%m%d')
        return today.strftime('%Y%m%d')

    def _get_best_trade_date(self, min_stocks: int = 1000,
                             before: Optional[str] = None) -> Optional[str]:
        """获取最近且数据充足的交易日。

        before 指定上界（不含），用于“固定上一工作日”：传 today 可排除
        当日盘中/收盘逐步入库的数据，避免数据日中途切换。
        """
        try:
            ecm = self.data_manager.cache
            sql = "SELECT trade_date, COUNT(*) as cnt FROM daily_cache "
            params: list = []
            if before:
                sql += "WHERE trade_date < ? "
                params.append(str(before))
            sql += "GROUP BY trade_date HAVING cnt >= ? ORDER BY trade_date DESC LIMIT 1"
            params.append(min_stocks)
            df = ecm._query_shard('daily_cache', sql, params)
            if not df.empty:
                return str(df['trade_date'].iloc[0])
        except Exception:
            pass
        if before:
            return None
        return self._try_get_latest_trade_date()

    def _try_get_index_daily(self, ts_code: str) -> Optional[List]:
        """获取指数日线数据：仅从 SQLite daily_cache 读取（全局数据体系 §2.3）

        不允许直调 Tushare/AKShare API（违反架构红线规则）。
        如 SQLite 中无数据，返回 None，由调用方降级处理。
        """
        try:
            if self.data_manager:
                df = self.data_manager.get_cached_daily_data(ts_code)
                if df is not None and not df.empty:
                    return df.to_dict('records')
        except Exception:
            pass
        # 无可用的缓存数据，返回 None（由调用方决定是否降级展示）
        return None

    def _build_mini_kline(self, data: List) -> List:
        """从原始数据构建迷你K线格式"""
        mini = []
        for item in data:
            if isinstance(item, dict):
                row = item
            else:
                try:
                    row = item.to_dict()
                except AttributeError:
                    continue

            trade_date = row.get('trade_date', row.get('date', ''))
            if isinstance(trade_date, datetime):
                date_str = trade_date.strftime('%m/%d')
            elif isinstance(trade_date, str) and len(trade_date) == 8:
                date_str = f"{trade_date[4:6]}/{trade_date[6:8]}"
            elif isinstance(trade_date, str) and '-' in trade_date:
                parts = trade_date.split('-')
                date_str = f"{parts[1]}/{parts[2]}"
            elif isinstance(trade_date, str):
                date_str = trade_date
            else:
                date_str = str(trade_date)

            mini.append({
                'date': date_str,
                'open': float(row.get('open', 0)),
                'close': float(row.get('close', 0)),
                'low': float(row.get('low', 0)),
                'high': float(row.get('high', 0)),
            })
        return mini

    def _detect_market_status(self) -> str:
        """检测当前市场状态"""
        try:
            from app.utils.trading_hours import is_trading_time
            if is_trading_time():
                return 'trading'
        except ImportError:
            pass
        now = datetime.now()
        # 简单判断：工作日 9:30-15:00 为交易时段
        if now.weekday() < 5 and (
            (now.hour == 9 and now.minute >= 30) or
            (10 <= now.hour <= 13) or
            (now.hour == 14)
        ):
            return 'trading'
        # 周末判断
        if now.weekday() >= 5:
            return 'holiday'
        return 'closed'

    # ──────────────────────────────────────────────
    # ── 真实数据聚合方法 ──

    def _aggregate_moneyflow_by_date(
        self, records: List, max_days: int = 20, source_label: str = '',
    ) -> Dict:
        """从缓存资金流向记录按日聚合为 dashboard 格式"""
        from collections import defaultdict
        _sf = self._safe_float
        daily = defaultdict(lambda: {'main': 0.0, 'retail': 0.0})
        dates_found = set()
        for r in records:
            d = r.get('trade_date', '')
            if isinstance(d, datetime):
                d = d.strftime('%Y%m%d')
            elif hasattr(d, 'strftime'):
                d = d.strftime('%Y%m%d')
            elif isinstance(d, str):
                d = d.replace('-', '')
            net_main = _sf(r.get('net_lg_amount')) + _sf(r.get('net_elg_amount'))
            # 526 B5：net_sm_amount 显式 is None 判空（合法 0.0 不再触发 buy-sell 兜底）
            net_sm = r.get('net_sm_amount')
            net_retail = (
                _sf(net_sm)
                if net_sm is not None
                else (_sf(r.get('buy_sm_amount')) - _sf(r.get('sell_sm_amount')))
            )
            daily[d]['main'] += net_main
            daily[d]['retail'] += net_retail
            dates_found.add(d)

        sorted_dates = sorted(dates_found, reverse=True)[:max_days]
        days_list = []
        for d in sorted_dates:
            days_list.append({
                'date': f"{d[4:6]}/{d[6:8]}",
                'main_force_net_inflow': round(daily[d]['main'] / 1e4, 1),
                'retail_net_inflow': round(daily[d]['retail'] / 1e4, 1),
            })
        days_list.reverse()
        return {
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'cached_at': sorted_dates[0] if sorted_dates else '',
            'source': source_label or '资金流向',
            'days': days_list,
        }

    @staticmethod
    def _norm_trade_date(v) -> str:
        """统一交易日为 YYYY-MM-DD（moneyflow_cache 可能返回 str/date/datetime/YYYYMMDD）"""
        s = str(v or '')
        if len(s) >= 10 and s[4] in '-/':
            return s[:10].replace('/', '-')
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return s[:10]

    @staticmethod
    def _industry_of(code, industry_map: Dict) -> str:
        """531：行业映射查找（申万映射键为 6 位代码，东财映射键为 ts_code）"""
        if not code:
            return '其他'
        c = str(code)
        return industry_map.get(c) or industry_map.get(c.split('.')[0]) or '其他'

    @staticmethod
    def _summarize_net_5d(vals) -> str:
        """531：板块近5日净流入一句话总结（亿元，升序）"""
        vals = [float(v) for v in (vals or []) if v is not None]
        if not vals:
            return ''
        total = sum(vals)
        inflow_days = sum(1 for v in vals if v > 0)
        last = vals[-1]
        if inflow_days >= 4 and last > 0:
            shape = '持续净流入'
        elif inflow_days <= 1 and last < 0:
            shape = '持续净流出'
        elif vals[0] > 0 and last < 0:
            shape = '流入转流出'
        elif vals[0] < 0 and last > 0:
            shape = '流出转流入'
        else:
            shape = '流入流出交替'
        return f"近5日累计{total:+.1f}亿｜{inflow_days}日净流入｜{shape}，末日{last:+.1f}亿"

    def _aggregate_sector_moneyflow(self, raw: List, industry_map: Dict,
                                    top_n: int, stocks_per_sector: int, trade_date: str) -> Dict:
        """Aggregate per-stock moneyflow into sector-level + top stocks"""
        from collections import defaultdict
        sector_agg = defaultdict(lambda: {'net': 0.0, 'stocks': {}})

        for r in raw:
            code = r.get('ts_code', '')
            ind = self._industry_of(code, industry_map)
            _sf = self._safe_float
            net = _sf(r.get('buy_lg_amount', 0)) + _sf(r.get('buy_elg_amount', 0)) \
                  - _sf(r.get('sell_lg_amount', 0)) - _sf(r.get('sell_elg_amount', 0))
            sector_agg[ind]['net'] += net
            if code not in sector_agg[ind]['stocks']:
                sector_agg[ind]['stocks'][code] = {
                    'ts_code': code,
                    'name': code,  # will fill from data manager below
                    'net': 0.0,
                }
            sector_agg[ind]['stocks'][code]['net'] += net

        # 尝试从 DB 获取中文名称（避免 DataManager DuckDB 初始化失败）
        try:
            from app import db
            from app.models import Stock
            stocks = db.session.query(Stock.ts_code, Stock.name).all()
            name_map = {s.ts_code: s.name for s in stocks if s.name and s.ts_code}
            for ind_name in sector_agg:
                for code in sector_agg[ind_name]['stocks']:
                    if code in name_map:
                        sector_agg[ind_name]['stocks'][code]['name'] = name_map[code]
        except Exception:
            pass

        # 构建板块列表
        # 516 批次1（P1）：流入板块取净额最大前 N；流出板块取净额最负前 N。
        # 原实现对所有板块一律取「净额最大」前 N → 流出板块误列板块内净流入个股。
        all_sectors = []
        for name, data in sector_agg.items():
            stock_list = sorted(data['stocks'].values(), key=lambda x: x['net'], reverse=True)
            net_inflow = round(data['net'] / 1e4, 1)
            picked = (
                stock_list[:stocks_per_sector]
                if net_inflow > 0
                else sorted(stock_list, key=lambda x: x['net'])[:stocks_per_sector]
            )
            top_stocks = []
            for s in picked:
                top_stocks.append({
                    'ts_code': s.get('ts_code', s['name']),
                    'name': s['name'],
                    'net_inflow': round(s['net'] / 1e4, 2),
                })
            all_sectors.append({
                'name': name,
                'net_inflow': net_inflow,
                'stocks': top_stocks,
            })

        # 正→流入，负→流出
        inflow = [s for s in all_sectors if s['net_inflow'] > 0]
        outflow = [s for s in all_sectors if s['net_inflow'] <= 0]
        inflow.sort(key=lambda x: x['net_inflow'], reverse=True)
        outflow.sort(key=lambda x: x['net_inflow'])  # 最负在前

        return {
            'date': trade_date[:4] + '-' + trade_date[4:6] + '-' + trade_date[6:8],
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'source': 'DuckDB moneyflow_cache 聚合',
            'sectors': inflow[:top_n],
            'out_sectors': outflow[:top_n],
        }


