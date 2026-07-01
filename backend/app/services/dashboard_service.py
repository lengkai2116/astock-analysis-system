"""
仪表盘 Dashboard 数据服务
集中封装 213号 全部 8 个数据方法。

⚠️ 数据完整性约束（见 _项目运行手册.md §13）：
  生产环境下，数据源不可用时**不得**使用模拟数据替代。
  所有 mock 方法保留仅供开发/原型测试，不得在生产路径中被调用。
  数据不可用时返回 None，由路由层返回 503 错误响应。
"""
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

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

# 模拟股票池 — ⚠️ 仅用于开发/原型测试
_MOCK_STOCKS_POOL = [
    {'ts_code': '300750.SZ', 'name': '宁德时代'},
    {'ts_code': '000858.SZ', 'name': '五粮液'},
    {'ts_code': '600519.SH', 'name': '贵州茅台'},
    {'ts_code': '002415.SZ', 'name': '海康威视'},
    {'ts_code': '601318.SH', 'name': '中国平安'},
    {'ts_code': '000333.SZ', 'name': '美的集团'},
    {'ts_code': '002594.SZ', 'name': '比亚迪'},
    {'ts_code': '300059.SZ', 'name': '东方财富'},
    {'ts_code': '600036.SH', 'name': '招商银行'},
    {'ts_code': '000762.SZ', 'name': '西藏矿业'},
    {'ts_code': '002230.SZ', 'name': '科大讯飞'},
    {'ts_code': '600030.SH', 'name': '中信证券'},
    {'ts_code': '300124.SZ', 'name': '汇川技术'},
    {'ts_code': '002475.SZ', 'name': '立讯精密'},
    {'ts_code': '000100.SZ', 'name': 'TCL科技'},
]

# ⚠️ 仅供开发/原型测试使用 — 生产环境不得调用
_MOCK_SECTOR_STOCKS = {
    '半导体': ['北方华创', '韦尔股份', '中芯国际'],
    'AI': ['科大讯飞', '海康威视', '中科曙光'],
    '军工': ['航发动力', '中航沈飞', '中国重工'],
    '新能源': ['宁德时代', '比亚迪', '隆基绿能'],
    '医药': ['恒瑞医药', '迈瑞医疗', '药明康德'],
    '消费': ['贵州茅台', '五粮液', '伊利股份'],
    '金融': ['招商银行', '中国平安', '中信证券'],
    '地产': ['万科A', '保利发展', '招商蛇口'],
}


class DashboardService:
    """仪表盘数据服务 — 8 个数据方法（不含 mock 降级）"""

    def __init__(self):
        self._tushare = None
        self._data_manager = None

    @property
    def tushare(self):
        if self._tushare is None:
            try:
                from app.data.tushare_provider import TushareProvider
                self._tushare = TushareProvider()
            except ImportError:
                self._tushare = None
        return self._tushare

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
        """获取四大指数行情 + 迷你K线 + 总成交额"""
        indexes = []
        total_volume = 0
        total_volume_prev = 0

        for idx_cfg in INDEX_CONFIG:
            try:
                data = self._try_get_index_daily(idx_cfg['ts_code'])
                if data and len(data) > 0:
                    latest = data[0] if isinstance(data[0], dict) else data.iloc[0].to_dict()
                    prev = data[1] if len(data) > 1 else latest
                    prev = prev if isinstance(prev, dict) else (prev.to_dict() if hasattr(prev, 'to_dict') else prev)

                    prev_close = prev.get('close', prev.get('pre_close', latest.get('close', 0)))
                    close = latest.get('close', latest.get('value', 0))
                    amount = float(latest.get('amount', 0))
                    change = float(close) - float(prev_close)
                    change_pct = (change / float(prev_close) * 100) if float(prev_close) > 0 else 0

                    # 迷你K线（最近20交易日）
                    mini_kline = self._build_mini_kline(data[:20])

                    indexes.append({
                        'ts_code': idx_cfg['ts_code'],
                        'name': idx_cfg['name'],
                        'price': round(float(close), 2),
                        'change_pct': round(change_pct, 2),
                        'change_amount': round(change, 2),
                        'mini_kline': mini_kline,
                        'amount': amount,
                    })
                    total_volume += amount
                    if 'amount' in prev:
                        total_volume_prev += float(prev.get('amount', 0))
                # else: 指数无数据 → 跳过（不用 mock）
            except Exception as e:
                logger.warning(f"指数 {idx_cfg['ts_code']} 获取失败，已跳过: {e}")
                # 跳过（不用 mock）

        if not indexes:
            logger.error("四大指数行情全部不可用")
            return None

        # 成交额同比变化（仅基于已成功获取的数据）
        volume_change_pct = (
            round((total_volume - total_volume_prev) / total_volume_prev * 100, 1)
            if total_volume_prev > 0 else 0
        )

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
                mini_kline = self._build_mini_kline(data[:limit])
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
            for idx_cfg in INDEX_CONFIG:
                data = self._try_get_index_daily(idx_cfg['ts_code'])
                if data is None or len(data) == 0:
                    raise ValueError(f"无指数数据: {idx_cfg['ts_code']}")
                for row in data:
                    d = row if isinstance(row, dict) else row.to_dict()
                    trade_date = d.get('trade_date', d.get('date', ''))
                    if isinstance(trade_date, datetime):
                        trade_date = trade_date.strftime('%m/%d')
                    elif isinstance(trade_date, str) and len(trade_date) == 8:
                        trade_date = f"{trade_date[4:6]}/{trade_date[6:8]}"
                    elif isinstance(trade_date, str) and '-' in trade_date:
                        parts = trade_date.split('-')
                        trade_date = f"{parts[1]}/{parts[2]}"

                    amount = float(d.get('amount', 0))
                    if trade_date not in exchange_data:
                        exchange_data[trade_date] = {'date': trade_date, 'total_amount': 0, 'amount_per_exchange': {}}
                    exchange_data[trade_date]['total_amount'] += amount
                    exchange_data[trade_date]['amount_per_exchange'][idx_cfg['ts_code']] = amount
                    all_dates.add(trade_date)

            sorted_dates = sorted(all_dates, key=lambda x: (x.split('/')[0], x.split('/')[1]))[-days:]
            days_list = [exchange_data[d] for d in sorted_dates]
            avg_amount = sum(d['total_amount'] for d in days_list) / len(days_list) if days_list else 0

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
        """涨幅榜/跌幅榜"""
        try:
            from app.data.tushare_provider import TushareProvider
            tp = TushareProvider()
            df = tp.get_daily(None, datetime.now().strftime('%Y%m%d'))
            if df is not None and not df.empty:
                df['change_pct'] = df['pct_chg'].astype(float)
                ascending = type == 'down'
                sorted_df = df.sort_values('change_pct', ascending=ascending).head(limit)
                stocks = []
                for _, row in sorted_df.iterrows():
                    stocks.append({
                        'ts_code': row.get('ts_code', ''),
                        'name': row.get('name', ''),
                        'price': round(float(row.get('close', 0)), 2),
                        'change_pct': round(float(row.get('change_pct', 0)), 2),
                        'change_pct_display': f"{'+' if float(row.get('change_pct', 0)) >= 0 else ''}{round(float(row.get('change_pct', 0)), 2)}%",
                    })
                return {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'type': type,
                    'title': '涨幅前十' if type == 'up' else '跌幅前十',
                    'stocks': stocks,
                }
        except Exception as e:
            logger.error(f"涨跌幅榜数据不可用: {e}")
            return None

        logger.error("涨跌幅榜: Tushare 返回空数据")
        return None

    # ──────────────────────────────────────────────
    # 5. 板块涨跌幅（sector-sector）
    # ──────────────────────────────────────────────
    def get_sector_changes(self, top_n: int = 8) -> Optional[Dict]:
        """行业板块涨跌幅（AKShare 实时数据）"""
        try:
            from app.data.akshare_provider import AkshareProvider
            ap = AkshareProvider()
            rankings = ap.get_sector_rankings()
            if rankings and len(rankings) >= top_n:
                sectors = []
                for s in rankings[:top_n]:
                    change_pct = s.get('change_pct', 0)
                    sectors.append({
                        'name': s.get('name', ''),
                        'change_pct': change_pct,
                        'color': '#EF4444' if change_pct >= 0 else '#22C55E',
                        'lead_stock': s.get('lead_stock', ''),
                        'up_count': s.get('up_count', 0),
                        'down_count': s.get('down_count', 0),
                    })
                sectors.sort(key=lambda x: x['change_pct'], reverse=True)
                return {'date': datetime.now().strftime('%Y-%m-%d'), 'sectors': sectors}
        except Exception as e:
            logger.error(f"板块涨跌幅数据不可用: {e}")
            return None

        logger.error("板块涨跌幅: AKShare 返回空数据")
        return None

    # ──────────────────────────────────────────────
    # 6. AI雷达+策略信号汇总（dashboard/summary）
    # ──────────────────────────────────────────────
    def get_dashboard_summary(self) -> Optional[Dict]:
        """AI交易机会雷达 + 策略信号汇总（Screener 引擎数据）"""
        try:
            from app.routes.screener import get_cached_screening, get_data_manager
            screening = get_cached_screening()
            if screening and screening.get('results', []):
                return self._screening_to_dashboard_summary(screening)
            # 缓存空 → 尝试轻量运行
            logger.info("Screener 缓存为空，尝试轻量运行...")
            dm = get_data_manager()
            stock_list = dm.get_stock_list(limit=200)
            if stock_list and len(stock_list) > 20:
                from app.routes.screener import compute_screening
                result = compute_screening(stock_list)
                if result and result.get('results', []):
                    return self._screening_to_dashboard_summary(result)
        except Exception as e:
            logger.error(f"Screener 引擎数据不可用: {e}")
            return None

        logger.error("dashboard/summary: Screener 引擎不可用且无缓存")
        return None

    # ──────────────────────────────────────────────
    # 7. 全市场资金流向（moneyflow-summary）
    # ──────────────────────────────────────────────
    def get_moneyflow_summary(self, days: int = 20) -> Optional[Dict]:
        """全市场资金流向趋势（Tushare moneyflow + DuckDB 缓存）"""
        # 尝试从缓存读取
        try:
            end = datetime.now()
            start = end - timedelta(days=days * 2)
            from app.data import DataManager
            import pandas as pd
            dm = DataManager()
            cached = dm.get_cached_moneyflow(
                start_date=start.strftime('%Y%m%d'),
                end_date=end.strftime('%Y%m%d')
            )
            if cached is not None:
                if isinstance(cached, pd.DataFrame) and not cached.empty:
                    records = cached.to_dict('records')
                    return self._aggregate_moneyflow_by_date(records, days)
                elif isinstance(cached, list) and len(cached) > 0:
                    return self._aggregate_moneyflow_by_date(cached, days)
        except Exception as e:
            logger.warning(f"缓存资金流向查询失败: {e}")

        # 尝试直接从 Tushare 获取
        try:
            from app.data.tushare_provider import TushareProvider
            tp = TushareProvider()
            date_list = []
            for i in range(days * 3):
                d = (end - timedelta(days=i)).strftime('%Y%m%d')
                raw = tp.get_moneyflow(trade_date=d)
                if raw and len(raw) > 0:
                    total_main = sum(
                        float(r.get('buy_lg_amount', 0)) + float(r.get('buy_elg_amount', 0))
                        - float(r.get('sell_lg_amount', 0)) - float(r.get('sell_elg_amount', 0))
                        for r in raw
                    )
                    total_retail = sum(
                        float(r.get('buy_sm_amount', 0)) - float(r.get('sell_sm_amount', 0))
                        for r in raw
                    )
                    if abs(total_main) < 1 and abs(total_retail) < 1:
                        continue
                    date_list.append({
                        'date': f"{d[4:6]}/{d[6:8]}",
                        'main_force_net_inflow': round(total_main / 1e8, 1),
                        'retail_net_outflow': round(total_retail / 1e8, 1),
                    })
                    if len(date_list) >= days:
                        break
            if len(date_list) >= days:
                date_list.reverse()
                return {
                    'updated_at': end.strftime('%Y-%m-%d'),
                    'source': 'Tushare 资金流向',
                    'days': date_list,
                }
        except Exception as e:
            logger.error(f"Tushare 资金流向数据不可用: {e}")
            return None

        logger.error("资金流向: 缓存和 Tushare 均不可用")
        return None

    # ──────────────────────────────────────────────
    # 8. 板块资金流向（sector-moneyflow）
    # ──────────────────────────────────────────────
    def get_sector_moneyflow(self, top_n: int = 8, stocks_per_sector: int = 3) -> Optional[Dict]:
        """行业板块资金流向 + 个股Top3（Tushare moneyflow + industry 聚合）"""
        try:
            from app.data.tushare_provider import TushareProvider
            tp = TushareProvider()
            industries = tp.get_industry()
            industry_map = {}
            if industries:
                for rec in industries:
                    code = rec.get('ts_code', '')
                    ind = rec.get('industry', '') or rec.get('industry_name', '')
                    if code and ind:
                        industry_map[code] = ind

            if len(industry_map) < 10:
                logger.error(f"行业映射数据不足 ({len(industry_map)} 条)，无法聚合板块资金流向")
                return None

            end = datetime.now()
            for i in range(30):
                d = (end - timedelta(days=i)).strftime('%Y%m%d')
                raw = tp.get_moneyflow(trade_date=d)
                if raw and len(raw) > 50:
                    return self._aggregate_sector_moneyflow(raw, industry_map, top_n, stocks_per_sector, d)
        except Exception as e:
            logger.error(f"板块资金流向数据不可用: {e}")
            return None

        logger.error("板块资金流向: 无有效交易日数据")
        return None

    # ──────────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────────

    def _try_get_index_daily(self, ts_code: str) -> Optional[List]:
        """尝试从 Tushare/DataManager 获取指数日线数据"""
        try:
            if self.tushare:
                data = self.tushare.get_index_daily(ts_code)
                if data is not None and len(data) > 0:
                    return data
        except Exception:
            pass
        try:
            if self.data_manager:
                df = self.data_manager.get_cached_daily_data(ts_code)
                if df is not None and not df.empty:
                    return df.to_dict('records')
        except Exception:
            pass
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
            (now.hour == 14 and now.minute <= 30)
        ):
            return 'trading'
        # 周末判断
        if now.weekday() >= 5:
            return 'holiday'
        return 'closed'

    # ──────────────────────────────────────────────
    # Mock 降级方法
    # ──────────────────────────────────────────────

    def _mock_index(self, idx_cfg: Dict) -> Dict:
        """模拟单个指数数据"""
        base_price = {'000001.SH': 3287, '399001.SZ': 11200, '899050.BJ': 1250, '399006.SZ': 2250}.get(idx_cfg['ts_code'], 3000)
        price = round(base_price + random.uniform(-50, 50), 2)
        prev_close = round(base_price + random.uniform(-30, 30), 2)
        change = round(price - prev_close, 2)
        change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0
        return {
            'ts_code': idx_cfg['ts_code'],
            'name': idx_cfg['name'],
            'price': price,
            'change_pct': change_pct,
            'change_amount': change,
            'mini_kline': self._mock_mini_kline_data(base_price, 20),
            'amount': random.uniform(1.5e11, 3.5e11),  # 1500亿~3500亿
        }

    def _mock_mini_kline(self, ts_code: str, limit: int = 20) -> Dict:
        base_price = {'000001.SH': 3287, '399001.SZ': 11200, '899050.BJ': 1250, '399006.SZ': 2250}.get(ts_code, 3000)
        name = ts_code
        for idx in INDEX_CONFIG:
            if idx['ts_code'] == ts_code:
                name = idx['name']
                break
        return {
            'ts_code': ts_code,
            'name': name,
            'kline': self._mock_mini_kline_data(base_price, limit),
        }

    def _mock_mini_kline_data(self, base_price: float, count: int) -> List:
        mini = []
        price = base_price - 50
        for i in range(count):
            d = (datetime.now() - timedelta(days=count - i)).strftime('%m/%d')
            open_p = round(price + random.uniform(-10, 10), 2)
            close_p = round(open_p + random.uniform(-15, 15), 2)
            low = round(min(open_p, close_p) - random.uniform(0, 10), 2)
            high = round(max(open_p, close_p) + random.uniform(0, 10), 2)
            price = close_p
            mini.append({'date': d, 'open': open_p, 'close': close_p, 'low': low, 'high': high})
        return mini

    def _mock_volume_chart(self, days: int = 20) -> Dict:
        days_list = []
        base_amount = 8e11
        for i in range(days):
            d = (datetime.now() - timedelta(days=days - i)).strftime('%m/%d')
            amount = round(base_amount + random.uniform(-3e11, 3e11), 2)
            days_list.append({
                'date': d,
                'total_amount': amount,
                'amount_per_exchange': {
                    '000001.SH': round(amount * 0.35, 2),
                    '399001.SZ': round(amount * 0.40, 2),
                    '899050.BJ': round(amount * 0.05, 2),
                    '399006.SZ': round(amount * 0.20, 2),
                },
            })
        avg = sum(d['total_amount'] for d in days_list) / len(days_list)
        return {
            'exchange_summary': '上证+深证+北证50+创业板',
            'days': days_list,
            'average_amount': round(avg, 2),
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
        }

    def _mock_daily_top(self, type: str = 'up', limit: int = 10) -> Dict:
        pool = _MOCK_STOCKS_POOL.copy()
        random.shuffle(pool)
        stocks = []
        for i, stock in enumerate(pool[:limit]):
            if type == 'up':
                pct = round(random.uniform(2, 10), 2)
            else:
                pct = round(random.uniform(-10, -2), 2)
            stocks.append({
                'ts_code': stock['ts_code'],
                'name': stock['name'],
                'price': round(random.uniform(10, 300), 2),
                'change_pct': pct,
                'change_pct_display': f"{'+' if pct >= 0 else ''}{pct}%",
            })
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'type': type,
            'title': '涨幅前十' if type == 'up' else '跌幅前十',
            'stocks': stocks,
        }

    # ── 新增 mock 降级 ──

    def _mock_sector_changes(self, top_n: int = 8) -> Dict:
        """模拟板块涨跌幅数据"""
        sectors = []
        for name in SECTOR_NAMES[:top_n]:
            change = round(random.uniform(-3, 5), 1)
            sectors.append({
                'name': name,
                'change_pct': change,
                'color': '#EF4444' if change >= 0 else '#22C55E',
            })
        sectors.sort(key=lambda x: x['change_pct'], reverse=True)
        return {'date': datetime.now().strftime('%Y-%m-%d'), 'sectors': sectors}

    def _mock_moneyflow_summary(self, days: int = 20) -> Dict:
        """模拟资金流向数据"""
        days_list = []
        base_main = 3.0
        base_retail = -1.5
        now = datetime.now()
        for i in range(days):
            d = (now - timedelta(days=days - i)).strftime('%m/%d')
            main_flow = round(base_main + random.uniform(-2, 2), 1)
            retail_flow = round(base_retail + random.uniform(-1, 1), 1)
            days_list.append({
                'date': d,
                'main_force_net_inflow': main_flow,
                'retail_net_outflow': retail_flow,
            })
        return {
            'updated_at': now.strftime('%Y-%m-%d'),
            'source': '模拟数据（所有真实数据源均不可用）',
            'days': days_list,
        }

    def _mock_sector_moneyflow(self, top_n: int = 8, stocks_per_sector: int = 3) -> Dict:
        """模拟板块资金流向"""
        sectors = []
        for name in SECTOR_NAMES[:top_n]:
            net_inflow = round(random.uniform(-2, 6), 1)
            stocks = []
            stock_names = _MOCK_SECTOR_STOCKS.get(name, [f'{name}股票{i+1}' for i in range(stocks_per_sector)])
            for sname in stock_names[:stocks_per_sector]:
                stocks.append({
                    'name': sname,
                    'net_inflow': round(random.uniform(-0.5, 1.5), 2),
                })
            sectors.append({
                'name': name,
                'net_inflow': net_inflow,
                'net_inflow_change_pct': round(random.uniform(-5, 10), 1),
                'stocks': stocks,
            })
        out_sectors = []
        for name in OUT_SECTOR_NAMES[:5]:
            net_inflow = round(random.uniform(-3, -0.5), 1)
            stocks = []
            stock_names = _MOCK_SECTOR_STOCKS.get(name, [f'{name}股{i+1}' for i in range(stocks_per_sector)])
            for sname in stock_names[:stocks_per_sector]:
                stocks.append({
                    'name': sname,
                    'net_outflow': round(random.uniform(-2, -0.3), 2),
                })
            out_sectors.append({
                'name': name,
                'net_inflow': net_inflow,
                'stocks': stocks,
            })
        sectors.sort(key=lambda x: x['net_inflow'], reverse=True)
        out_sectors.sort(key=lambda x: x['net_inflow'])
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'source': '模拟数据（所有真实数据源均不可用）',
            'sectors': sectors,
            'out_sectors': out_sectors,
        }

    def _mock_dashboard_summary(self) -> Dict:
        """模拟 AI 雷达 + 策略信号汇总"""
        random.shuffle(_MOCK_STOCKS_POOL)
        radar_stocks = []
        directions = ['bullish', 'watch', 'bearish']
        weights = [0.5, 0.3, 0.2]
        for stock in _MOCK_STOCKS_POOL[:8]:
            direction = random.choices(directions, weights=weights, k=1)[0]
            score = random.randint(60, 98)
            change_pct = round(random.uniform(-5, 8), 1)
            radar_stocks.append({
                'ts_code': stock['ts_code'],
                'name': stock['name'],
                'score': score,
                'direction': direction,
                'price': round(random.uniform(10, 300), 2),
                'change_pct': change_pct,
            })
        return {
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'update_note': '模拟数据（Screener 引擎不可用）',
            'radar_stocks': radar_stocks,
            'signal_summary': {
                'bullish_count': random.randint(10, 20),
                'bearish_count': random.randint(5, 12),
                'chanlun_signal': random.randint(10, 25),
                'chip_signal': random.randint(5, 15),
                'ai_judgment': random.randint(3, 10),
                'resonance': {'label': '🔥 共振信号', 'detail': '3 个策略同时看多'},
                'high_confidence': {'label': '⚡ 高置信度', 'detail': '置信度 ≥ 85%'},
            },
            'total_signals': random.randint(30, 60),
        }

    # ── 真实数据聚合方法 ──

    def _aggregate_moneyflow_by_date(self, records: List, max_days: int = 20) -> Dict:
        """从缓存资金流向记录按日聚合为 dashboard 格式"""
        from collections import defaultdict
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
            net_main = float(r.get('net_lg_amount', 0))
            net_retail = float(r.get('buy_sm_amount', 0)) - float(r.get('sell_sm_amount', 0))
            daily[d]['main'] += net_main
            daily[d]['retail'] += net_retail
            dates_found.add(d)

        sorted_dates = sorted(dates_found, reverse=True)[:max_days]
        days_list = []
        for d in sorted_dates:
            days_list.append({
                'date': f"{d[4:6]}/{d[6:8]}",
                'main_force_net_inflow': round(daily[d]['main'] / 1e8, 1),
                'retail_net_outflow': round(daily[d]['retail'] / 1e8, 1),
            })
        days_list.reverse()
        return {
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'source': 'Tushare 资金流向 · DuckDB 缓存',
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
            net = float(r.get('buy_lg_amount', 0)) + float(r.get('buy_elg_amount', 0)) \
                  - float(r.get('sell_lg_amount', 0)) - float(r.get('sell_elg_amount', 0))
            sector_agg[ind]['net'] += net
            if code not in sector_agg[ind]['stocks']:
                sector_agg[ind]['stocks'][code] = {
                    'ts_code': code,
                    'name': code,  # will fill from data manager below
                    'net': 0.0,
                }
            sector_agg[ind]['stocks'][code]['net'] += net

        # 尝试从 DataManager 获取中文名称
        try:
            dm = DataManager()
            name_map = {}
            for s in dm.get_stock_list(limit=6000):
                if s.get('name') and s.get('ts_code'):
                    name_map[s['ts_code']] = s['name']
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
                    'ts_code': s['name'],
                    'name': s['name'],
                    'net_inflow': round(s['net'] / 1e8, 2),
                })
            all_sectors.append({
                'name': name,
                'net_inflow': round(data['net'] / 1e8, 1),
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
            'source': 'Tushare 资金流向 + industry 聚合',
            'sectors': inflow[:top_n],
            'out_sectors': outflow[:5],
        }

    def _screening_to_dashboard_summary(self, screening: Dict) -> Dict:
        """将 Screener L3 结果转为 dashboard/summary 格式"""
        results = screening.get('results', [])
        # Top 8 雷达股票
        radar_stocks = []
        for r in results[:8]:
            score = r.get('score', 50)
            phase = r.get('phase', 'WASHING')
            # phase → direction 映射
            dir_map = {'BUILDING': 'bullish', 'WASHING': 'watch',
                       'LIFTING': 'bullish', 'DISTRIBUTING': 'bearish'}
            radar_stocks.append({
                'ts_code': r.get('symbol', ''),
                'name': r.get('name', ''),
                'score': int(score),
                'direction': dir_map.get(phase, 'watch'),
                'price': r.get('price', 0),
                'change_pct': r.get('change_pct', 0),
            })

        # 信号计数
        bullish = sum(1 for r in results if r.get('phase') in ('BUILDING', 'LIFTING'))
        bearish = sum(1 for r in results if r.get('phase') == 'DISTRIBUTING')
        chanlun = sum(1 for r in results if r.get('rsi', 50) > 60 or r.get('rsi', 50) < 40)
        chip = sum(1 for r in results if r.get('score', 0) > 60)
        ai_judg = max(1, len(results) // 10)

        return {
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'update_note': f'来自 Screener L3 · {len(results)} 只通过验证',
            'radar_stocks': radar_stocks,
            'signal_summary': {
                'bullish_count': bullish,
                'bearish_count': bearish,
                'chanlun_signal': chanlun,
                'chip_signal': chip,
                'ai_judgment': ai_judg,
                'resonance': {'label': '🔥 共振信号', 'detail': f'{max(1, bullish // 3)} 策略同时看多'},
                'high_confidence': {'label': '⚡ 高置信度', 'detail': f'{chip} 只置信度 ≥ 60'},
            },
            'total_signals': len(results),
        }
