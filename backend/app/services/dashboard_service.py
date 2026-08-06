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

        # 盘中：直接从 InMemoryStateStore 读取（全局数据体系架构：mootdx TCP → store）
        try:
            from app.data.in_memory_store import store as mem_store
            snapshot = mem_store.get_snapshot()
            live_map = {}
            for cfg in INDEX_CONFIG:
                code = cfg['ts_code']
                for r in snapshot:
                    if r.get('ts_code') == code:
                        live_map[code] = {
                            'price': float(r.get('price', 0)),
                            'change_pct': float(r.get('change_pct', 0)),
                            'change_value': float(r.get('change', 0)),
                            'amount': self._safe_float(r.get('amount', 0)),
                        }
                        break
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
                    prev_close_val = (
                        float(latest_hist.get('pre_close', 0))
                        or float(hist_data[-2].get('close', 0))
                        if len(hist_data) > 1 else 0
                    )
                    prev_close = prev_close_val
                    # 迷你K线（最近20交易日）
                    _sorted = hist_data if (
                        len(hist_data) > 1
                        and hist_data[0].get('trade_date', '')
                        <= hist_data[-1].get('trade_date', '')
                    ) else hist_data[::-1]
                    mini_kline = self._build_mini_kline(_sorted[-20:])

                # 价格优先用实时快照，没有则用历史
                if live:
                    price = live['price']
                    change_pct = live['change_pct']
                    change_amount = live['change_value']
                    amount = live['amount']
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
                    'source': 'AKShare 实时行情' if live else '日线缓存',
                })
                total_volume += amount
            except Exception as e:
                logger.warning(f"指数 {idx_cfg['ts_code']} 获取失败，已跳过: {e}")

        if not indexes:
            logger.error("四大指数行情全部不可用")
            return None

        # 成交额同比变化（基于daily_cache历史数据推算，若无则默认为 0）
        volume_change_pct = 0

        result = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'market_status': self._detect_market_status(),
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
                    if isinstance(raw_date, datetime):
                        date_key = raw_date.strftime('%Y%m%d')
                    elif isinstance(raw_date, str) and len(raw_date) == 8 and raw_date.isdigit():
                        date_key = raw_date
                    elif isinstance(raw_date, str) and '-' in raw_date:
                        parts = raw_date.split('-')
                        date_key = f"{parts[0]}{parts[1]}{parts[2]}"
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
                'exchange_summary': '上证+深证+北证50+创业板',
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

            from app.data.enhanced_cache_manager import get_ecm_instance
            from app.models import Stock

            ecm = get_ecm_instance()
            # 查询 daily_cache 最新日期
            date_df = pd.read_sql(
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1",
                ecm.conn
            )
            if date_df.empty:
                logger.error("涨跌幅榜: DuckDB 无任何历史数据")
                raise ValueError("DuckDB daily_cache 无日期记录，走 Tushare 降级")
            last_date = date_df['trade_date'].iloc[0]

            # 取该日全市场数据
            all_df = pd.read_sql(
                "SELECT * FROM daily_cache WHERE trade_date = ? ORDER BY pct_chg DESC",
                ecm.conn, params=[last_date]
            )
            if all_df.empty:
                logger.error("涨跌幅榜: DuckDB 查询为空")
                raise ValueError("DuckDB daily_cache 当日无数据，走 Tushare 降级")

            # 补齐股票名称（从 PG Stock 表）
            ts_codes = all_df['ts_code'].unique().tolist()
            stock_map = {}
            try:
                for s in Stock.query.filter(Stock.ts_code.in_(ts_codes)).all():
                    stock_map[s.ts_code] = s.name
            except Exception:
                pass
            # ponytail: 如果 Stock 表为空，从 DataManager 获取一次
            # （全局数据体系 §2.4 例外：降级场景）
            if not stock_map:
                try:
                    if self.data_manager:
                        basic = self.data_manager.get_stock_list()
                        if basic:
                            for r in basic:
                                stock_map[r.get('ts_code', '')] = r.get('name', '')
                except Exception:
                    pass

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
    # 5. 板块涨跌幅（sector-sector）
    # ──────────────────────────────────────────────
    def get_sector_changes(self, top_n: int = 8) -> Optional[Dict]:
        """行业板块涨跌幅 — AKShare 实时优先，降级 DB daily_data 聚合"""
        # 1. 尝试 AkshareDataReader 读取
        try:
            from app.data.akshare_reader import reader
            rankings = reader.get_sector_rankings()
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
                        'source': '东方财富行业板块（盘中）',
                    }
        except Exception as e:
            logger.warning(f"板块涨跌幅 reader 不可用，降级 DB: {e}")

        # 2. 降级：从 DuckDB 最新交易日聚合行业涨跌幅
        try:
            import pandas as pd

            from app.data.enhanced_cache_manager import get_ecm_instance
            from app.models import Stock

            ecm = get_ecm_instance()
            # 取最近数据充足的交易日
            best_date = self._get_best_trade_date()
            if not best_date:
                raise ValueError("无不含日线数据")
            last_date = best_date
            date_label = str(last_date)

            # 取该日全市场 pct_chg + ts_code
            all_df = pd.read_sql(
                "SELECT ts_code, pct_chg FROM daily_cache WHERE trade_date = ?",
                ecm.conn, params=[last_date]
            )
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
                    'source': 'DuckDB daily_cache 聚合',
                }
        except Exception as e:
            logger.error(f"板块涨跌幅 DuckDB 降级失败: {e}")

        logger.error("板块涨跌幅: 所有数据源不可用")
        return None

    # ──────────────────────────────────────────────
    # 6. AI雷达+策略信号汇总（dashboard/summary）
    # ──────────────────────────────────────────────
    def get_dashboard_summary(self) -> Optional[Dict]:
        """AI交易机会雷达 + 策略信号汇总 — 从 DuckDB daily_cache 提取"""
        try:
            import pandas as pd

            from app.data.enhanced_cache_manager import get_ecm_instance
            from app.models import Stock

            ecm = get_ecm_instance()
            best_date = self._get_best_trade_date()
            if not best_date:
                logger.error("dashboard/summary DuckDB: 无历史数据")
                raise ValueError("DuckDB daily_cache 无日期记录，走 Tushare 降级")
            last_date = best_date
            date_label = str(last_date)

            # 取该日全市场数据
            all_df = pd.read_sql(
                "SELECT ts_code, close, pct_chg FROM daily_cache WHERE trade_date = ?",
                ecm.conn, params=[last_date]
            )
            if all_df.empty:
                logger.error("dashboard/summary DuckDB: 当日无数据")
                raise ValueError("DuckDB daily_cache 当日无数据，走 Tushare 降级")

            # 补齐名称（从 PG Stock 表）
            ts_codes = all_df['ts_code'].unique().tolist()
            name_map = {}
            try:
                for s in Stock.query.filter(Stock.ts_code.in_(ts_codes)).all():
                    name_map[s.ts_code] = s.name
            except Exception:
                pass
            all_df['name'] = all_df['ts_code'].map(lambda x: name_map.get(x, x))

            # Top 8 涨幅股
            top_df = all_df.nlargest(8, 'pct_chg')
            radar_stocks = []
            for _, r in top_df.iterrows():
                pct = float(r['pct_chg'] or 0)
                direction = 'bullish' if pct > 3 else ('bearish' if pct < -3 else 'watch')
                radar_stocks.append({
                    'ts_code': r['ts_code'],
                    'name': r['name'],
                    'score': min(95, max(40, int(50 + pct * 5))),
                    'direction': direction,
                    'price': round(float(r['close'] or 0), 2),
                    'change_pct': round(pct, 2),
                })

            # 行情信号计数
            total_stocks = len(all_df)

            return {
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'update_note': f'来自 DuckDB daily_cache · {date_label} · {total_stocks} 只',
                'radar_stocks': radar_stocks,
                'total_signals': total_stocks,
            }
        except Exception as e:
            logger.error(f"dashboard/summary DuckDB 降级失败: {e}")

        logger.error("dashboard/summary: 所有数据源不可用")
        return None
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
                            or abs(d.get('retail_net_outflow', 0)) > 0.01
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
            best_date = max(date_counts, key=lambda d: date_counts[d]) if date_counts else None
            if not best_date or date_counts.get(best_date, 0) < 50:
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

            return self._aggregate_sector_moneyflow(
                day_records, industry_map, top_n, stocks_per_sector, date_str
            )
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
            summary = self.get_dashboard_summary()
            if summary:
                result['dashboard_summary'] = summary
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

        if not result:
            return None
        return result

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
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            date_df = pd.read_sql(
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 1"
            , ecm.conn)
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

            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            df = pd.read_sql(
                "SELECT trade_date, COUNT(*) as cnt FROM daily_cache "
                "GROUP BY trade_date HAVING cnt >= ? ORDER BY trade_date DESC LIMIT 1",
                ecm.conn, params=[min_stocks]
            )
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
            net_retail = (
                _sf(r.get('net_sm_amount'))
                or (_sf(r.get('buy_sm_amount')) - _sf(r.get('sell_sm_amount')))
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
                'retail_net_outflow': round(daily[d]['retail'] / 1e4, 1),
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
        all_sectors = []
        for name, data in sector_agg.items():
            stock_list = sorted(data['stocks'].values(), key=lambda x: x['net'], reverse=True)
            top_stocks = []
            for s in stock_list[:stocks_per_sector]:
                top_stocks.append({
                    'ts_code': s.get('ts_code', s['name']),
                    'name': s['name'],
                    'net_inflow': round(s['net'] / 1e4, 2),
                })
            all_sectors.append({
                'name': name,
                'net_inflow': round(data['net'] / 1e4, 1),
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
            'out_sectors': outflow[:5],
        }


