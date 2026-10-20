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
                    # 527 批次3：指数 60 日线（daily_cache 88 行，算 ma60/近60日涨跌/站上与否）
                    ma60 = None
                    ret_60d = None
                    above_ma60 = None
                    if len(_sorted) >= 60:
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
        """涨幅榜/跌幅榜 — AKShare 实时优先 → DB 最新交易日（239号架构：不直接调 Tushare）"""
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

        # 2. 降级：从 DuckDB 查询最新交易日
        try:
            import pandas as pd

            from app.models import Stock

            ecm = self.data_manager.cache
            # 查询 daily_cache 最新日期
            date_df = ecm._query_shard(
                'daily_cache',
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
            if date_df.empty:
                logger.error("涨跌幅榜: DuckDB 无任何历史数据")
                raise ValueError("DuckDB daily_cache 无日期记录，走 Tushare 降级")
            last_date = date_df['trade_date'].iloc[0]

            # 取该日全市场数据
            all_df = ecm._query_shard(
                'daily_cache',
                "SELECT * FROM daily_cache WHERE trade_date = ? ORDER BY pct_chg DESC",
                [last_date])
            if all_df.empty:
                logger.error("涨跌幅榜: DuckDB 查询为空")
                raise ValueError("DuckDB daily_cache 当日无数据，走 Tushare 降级")

            # 补齐股票名称（从 PG Stock 表）
            ts_codes = all_df['ts_code'].unique().tolist()
            stock_map = {}
            try:
                for s in Stock.query.filter(Stock.ts_code.in_(ts_codes)).all():
                    stock_map[s.ts_code] = s.name
            except Exception as e:
                # 526 B19：名称填充失败静默变空名——补 debug 日志
                logger.debug(f"涨跌幅榜 Stock 名称查询失败: {e}")
            # ponytail: 如果 Stock 表为空，从 DataManager 获取一次
            # （全局数据体系 §2.4 例外：降级场景）
            if not stock_map:
                try:
                    if self.data_manager:
                        basic = self.data_manager.get_stock_list()
                        if basic:
                            for r in basic:
                                stock_map[r.get('ts_code', '')] = r.get('name', '')
                except Exception as e:
                    logger.debug(f"涨跌幅榜 get_stock_list 名称兜底失败: {e}")

            all_df['name'] = all_df['ts_code'].map(lambda x: stock_map.get(x, ''))
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
                'source': 'DuckDB 盘后数据',
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

        数据源：daily_cache ⋈ daily_basic_cache（最新交易日，inner join 天然排除指数）。
        pre_close 无独立列，由 pct_chg 精确推导（Tushare 口径含除权）：
          pre_close = close / (1 + pct_chg/100)
        """
        try:
            from app.models import Stock

            ecm = self.data_manager.cache
            # 最新交易日
            date_df = ecm._query_shard(
                'daily_cache',
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
            if date_df is None or date_df.empty:
                logger.error("全市场日终散点: daily_cache 无任何历史数据")
                return None
            last_date = date_df['trade_date'].iloc[0]

            daily_df = ecm._query_shard(
                'daily_cache',
                "SELECT ts_code, open, close, pct_chg FROM daily_cache WHERE trade_date = ?",
                [last_date])
            if daily_df is None or daily_df.empty:
                logger.error("全市场日终散点: 当日无日线数据")
                return None

            basic_df = ecm._query_shard(
                'daily_basic_cache',
                "SELECT ts_code, circ_mv, total_mv FROM daily_basic_cache WHERE trade_date = ?",
                [last_date])
            if basic_df is None or basic_df.empty:
                logger.error("全市场日终散点: 当日无 daily_basic 数据")
                return None

            # inner join → 天然排除指数（daily 独有行＝指数/行业指数）
            merged = daily_df.merge(basic_df, on='ts_code', how='inner')

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
                'source': 'DuckDB 盘后数据',
                'stocks': stocks,
            }
        except Exception as e:
            logger.error(f"全市场日终散点获取失败: {e}")
            return None

    # ──────────────────────────────────────────────
    # 5. 板块涨跌幅（sector-sector）
    # ──────────────────────────────────────────────
    def get_sector_changes(self, top_n: int = 8) -> Optional[Dict]:
        """行业板块涨跌幅 — AKShare 实时优先，降级 DB daily_data 聚合

        528 号 批次2：取数改全量（原 `get_sector_rankings()` 默认 top_n=20，
        DB 回退 `ORDER BY change_pct DESC LIMIT 20` 前 20 全为正涨幅 → losers 恒空，
        跌幅 TOP5 缺失的根因）——改传 top_n=None 取全行业，双侧分别取 top5。
        """
        # 528 号 批次2：板块连续涨/跌 + 近5日累积涨跌（daily_cache 多日按行业聚合）
        streaks = self._get_sector_streaks()
        # 1. 尝试 AkshareDataReader 读取
        try:
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
                        'source': '东方财富行业板块（盘中）',
                    }
        except Exception as e:
            logger.warning(f"板块涨跌幅 reader 不可用，降级 DB: {e}")

        # 2. 降级：从 DuckDB 最新交易日聚合行业涨跌幅
        try:
            import pandas as pd

            from app.models import Stock

            ecm = self.data_manager.cache
            # 取最近数据充足的交易日
            best_date = self._get_best_trade_date()
            if not best_date:
                raise ValueError("无不含日线数据")
            last_date = best_date
            date_label = str(last_date)

            # 取该日全市场 pct_chg + ts_code
            all_df = ecm._query_shard(
                'daily_cache',
                "SELECT ts_code, pct_chg FROM daily_cache WHERE trade_date = ?",
                [last_date])
            if all_df.empty:
                logger.error("板块涨跌幅 DuckDB: 当日无数据")
                raise ValueError("DuckDB daily_cache 当日无数据，走 Tushare 降级")

            # 补齐行业信息（从 PG Stock 表），两步法
            ts_codes = all_df['ts_code'].unique().tolist()
            industry_map = {}
            try:
                for s in Stock.query.filter(Stock.ts_code.in_(ts_codes)).all():
                    if s.industry:
                        industry_map[s.ts_code] = s.industry
            except Exception:
                pass
            # ponytail: Stock 行业表为空时从 DataManager 获取一次（全局数据体系 §2.4 例外）
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
                    'source': 'DuckDB daily_cache 聚合',
                }
        except Exception as e:
            logger.error(f"板块涨跌幅 DuckDB 降级失败: {e}")

        logger.error("板块涨跌幅: 所有数据源不可用")
        return None

    def _get_sector_streaks(self, days: int = 6, min_streak: int = 2) -> Dict:
        """板块连续涨/跌 + 近5日累积涨跌（528 号 批次2）。

        数据源：daily_cache 多日按行业聚合（DuckDB）→ 每行业近 days 个交易日
        平均涨跌幅 → 从最新往回数连续上涨/下跌天数（streak）→ 近5日累积涨跌
        （最后 5 日行业平均 pct_chg 之和，近似口径）。
        返回 {'up': [...], 'down': [...]}（各按天数降序，取前 5）；失败返回空两侧。
        """
        try:
            ecm = self.data_manager.cache
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

            from app import db as _flask_db
            from app.models import Stock
            ts_codes = all_df['ts_code'].unique().tolist()
            industry_map = {}
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

    def get_sector_moneyflow(self, top_n: int = 8, stocks_per_sector: int = 3) -> Optional[Dict]:
        """行业板块资金流向 + 个股Top3（DuckDB 缓存 → Tushare 备选回退）"""
        # ── 代理环境变量免疫（与 tushare_provider.py 同步） ──────────
        for _key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
                     'http_proxy', 'https_proxy', 'all_proxy']:
            os.environ.pop(_key, None)

        # 1. 行业映射：从 SQLite Stock 表取
        industry_map = {}
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

        # 2. 从 DuckDB moneyflow_cache 读取最新交易日的资金流向数据
        try:
            dm = DataManager()
            end = datetime.now()
            start = end - timedelta(days=5)
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
            # 527 批次3：板块净流入多日聚合——近5日窗口内每板块净流入累计
            # （moneyflow_cache 59 日可用；前端可作「板块近5日趋势」一句话说明）
            # 528 批次2：补净流出侧 trend_5d_out（近5日净流出 top5，与净流入对称，
            # 前端作「净流出较多板块」提示）
            sector_net_5d = {}
            try:
                for r in records:
                    ind = industry_map.get(r.get('ts_code', ''), '其他')
                    _sf = self._safe_float
                    net = _sf(r.get('buy_lg_amount', 0)) + _sf(r.get('buy_elg_amount', 0)) \
                          - _sf(r.get('sell_lg_amount', 0)) - _sf(r.get('sell_elg_amount', 0))
                    sector_net_5d[ind] = sector_net_5d.get(ind, 0.0) + net
                top5 = sorted(sector_net_5d.items(), key=lambda x: -x[1])[:5]
                result['trend_5d'] = [
                    {'industry': k, 'net_inflow_5d': round(v / 1e4, 1)} for k, v in top5
                ]
                bottom5 = sorted(sector_net_5d.items(), key=lambda x: x[1])[:5]
                result['trend_5d_out'] = [
                    {'industry': k, 'net_inflow_5d': round(v / 1e4, 1)} for k, v in bottom5
                ]
            except Exception:
                result['trend_5d'] = []
                result['trend_5d_out'] = []
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

        数据源：E3 daily_cache⋈daily_basic_cache（最新交易日，inner join 纯股票，
                同 523 eod-snapshot 模式）+ E2 market_stats_cache（ma20_ratio/limit_ratio）。
        全只读，不写任何表。
        """
        try:
            ecm = self.data_manager.cache
            date_df = ecm._query_shard(
                'daily_cache',
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1")
            if date_df is None or date_df.empty:
                logger.error("市场宽度: daily_cache 无历史数据")
                return None
            last_date = str(date_df['trade_date'].iloc[0])

            daily_df = ecm._query_shard(
                'daily_cache',
                "SELECT ts_code, pct_chg FROM daily_cache WHERE trade_date = ?",
                [last_date])
            if daily_df is None or daily_df.empty:
                logger.error("市场宽度: 当日无日线数据")
                return None

            basic_df = ecm._query_shard(
                'daily_basic_cache',
                "SELECT ts_code FROM daily_basic_cache WHERE trade_date = ?",
                [last_date])
            if basic_df is None or basic_df.empty:
                logger.error("市场宽度: 当日无 daily_basic 数据")
                return None

            merged = daily_df.merge(basic_df, on='ts_code', how='inner')
            count = len(merged)
            if count == 0:
                logger.error("市场宽度: join 后无纯股票")
                return None
            up = int((merged['pct_chg'] > 0).sum())
            down = int((merged['pct_chg'] < 0).sum())
            flat = count - up - down

            stats = ecm.get_cached_market_stats()  # E2，最新 stat_date
            # 527 批次3：市场宽度历史序列（market_stats_cache 近20日 ma20_ratio/limit/turnover）
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
                    history.reverse()  # 升序
            except Exception:
                pass
            return {
                'trade_date': last_date,
                'count': count,
                'up_count': up,
                'down_count': down,
                'flat_count': flat,
                'up_ratio': round(up / count * 100, 1),
                'down_ratio': round(down / count * 100, 1),
                'ma20_ratio': round(float(stats.get('ma20_ratio', 0)) * 100, 1),
                'limit_ratio': float(stats.get('limit_ratio', 0)),
                'turnover_percentile': round(float(stats.get('turnover_percentile', 0)) * 100, 1),
                'history': history,   # 527 批次3：近20日宽度序列（升序）
                'source': 'DuckDB 盘后数据',
            }
        except Exception as e:
            logger.error(f"市场宽度获取失败: {e}")
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

    def get_market_emotion(self) -> Optional[Dict]:
        """市场情绪（524 号 L3 温度计原料）：六段论阶段 + 涨停生态指标。

        数据源：MarketSentimentService（273a 方案，sentiment_pool_cache → 六段论映射）。
        ⚠️ BOCIASI 市场级聚合输出当前无现成实现（dim5 BOCIASI 为个股级）——
        批次3 前端如需 BOCIASI 徽标需先建市场级聚合（524 档登记）。
        """
        try:
            from app.services.market_sentiment_service import MarketSentimentService
            mss = MarketSentimentService(self.data_manager)
            phase_data = mss.get_sentiment_phase()
            return {
                'phase': phase_data.get('phase', 'neutral'),
                'phase_label': phase_data.get('phase_label', '情绪中性'),
                'metrics': phase_data.get('metrics', {}),
                'data_available': phase_data.get('data_available', False),
                'source': 'sentiment_pool_cache 六段论',
            }
        except Exception as e:
            logger.error(f"市场情绪获取失败: {e}")
            return None

    def get_sector_heat(self, top_n: int = 8) -> Optional[Dict]:
        """板块热度/排名（524 号 L4）：sector_heat_cache 最新日全行业。

        数据源：E1 `sector_heat_cache`（compute_cache.db，long 格式每行业一行）
        → `{date, count, sectors:[{industry, heat_level, strength, rank, stock_count, prev_rank}]}`
        全只读；rank 越小越热（升序取 top_n）。heat_level 枚举：
        top_10/top_20/...（419 号方案B3 板块热度，481 号已修复取最新日全行业）。
        527 批次2：附前一日 rank（prev_rank）供前端「排名变化/新进榜」说明（get_cached_sector_heat
        支持 stat_date 参数，读上一 stat_date 全行业对比；无前日数据时 prev_rank=None）。
        """
        try:
            ecm = self.data_manager.cache
            heat = ecm.get_cached_sector_heat()
            if not heat:
                logger.error("板块热度: sector_heat_cache 无数据")
                return None
            sectors = []
            for ind, info in heat.items():
                if not ind or str(ind).strip().lower() in ('nan', 'none', ''):
                    continue
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
                    'sector_heat_cache', "SELECT MAX(stat_date) AS d FROM sector_heat_cache")
                if date_df is not None and not date_df.empty and date_df['d'].iloc[0]:
                    date = str(date_df['d'].iloc[0])
            except Exception:
                pass
            # 527 批次2：前一日 rank 对比（prev_rank）
            prev_rank_map = {}
            try:
                dates_df = ecm._query_shard(
                    'sector_heat_cache',
                    "SELECT DISTINCT stat_date FROM sector_heat_cache "
                    "ORDER BY stat_date DESC LIMIT 2")
                if dates_df is not None and not dates_df.empty and len(dates_df) >= 2:
                    prev_date = str(dates_df['stat_date'].iloc[1])
                    prev_heat = ecm.get_cached_sector_heat(stat_date=prev_date)
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
                'source': 'DuckDB sector_heat_cache',
                'sectors': sectors[:top_n],
            }
        except Exception as e:
            logger.error(f"板块热度获取失败: {e}")
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
            if emotion and emotion.get('phase') == 'ice':
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

    def _get_best_trade_date(self, min_stocks: int = 1000) -> Optional[str]:
        """获取最近且数据充足的交易日（避免当日数据未同步时取到残缺日期）"""
        try:
            import pandas as pd

            ecm = self.data_manager.cache
            df = ecm._query_shard(
                'daily_cache',
                "SELECT trade_date, COUNT(*) as cnt FROM daily_cache "
                "GROUP BY trade_date HAVING cnt >= ? ORDER BY trade_date DESC LIMIT 1",
                [min_stocks])
            if not df.empty:
                return str(df['trade_date'].iloc[0])
        except Exception:
            pass
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

    def _aggregate_sector_moneyflow(self, raw: List, industry_map: Dict,
                                    top_n: int, stocks_per_sector: int, trade_date: str) -> Dict:
        """Aggregate per-stock moneyflow into sector-level + top stocks"""
        from collections import defaultdict
        sector_agg = defaultdict(lambda: {'net': 0.0, 'stocks': {}})

        for r in raw:
            code = r.get('ts_code', '')
            ind = industry_map.get(code, '其他')
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


