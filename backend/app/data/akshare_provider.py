"""
AkshareProvider — 免费的实时/盘中数据提供者
=============================================
提供基于 AKShare（东方财富/新浪数据源）的实时行情、历史K线、资金流向等数据。
作为盘中数据源配置在 DataSourceManager，priority=-1（最高优先级）。

数据源对比：
  - AKShare: 免费，3-15s延迟，东方财富源，适用于盘中快速查询
  - Tushare: 5000分，T+1权威数据，适用于盘后存档
  - QMT: 券商直连，<1s延迟，适用于升级后的实时行情
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

_ak = None


def _get_ak():
    """惰性导入 akshare 单例，避免未安装时 import 错误"""
    global _ak
    if _ak is None:
        try:
            import akshare as ak
            _ak = ak
        except ImportError:
            logger.warning("akshare 未安装，请运行: pip install akshare>=1.14.0")
            return None
    return _ak


# ── 代码格式转换 ──────────────────────────────────────────

def _parse_ts_code(ts_code: str) -> tuple:
    """将 ts_code (600519.SH) 转换为 (symbol, prefix, full_symbol)"""
    symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
    if ts_code.endswith('.SH'):
        prefix = 'sh'
    elif ts_code.endswith('.SZ'):
        prefix = 'sz'
    elif ts_code.endswith('.BJ'):
        prefix = 'bj'
    else:
        # 尝试通过数字前缀识别
        if ts_code.startswith('6'):
            prefix = 'sh'
        elif ts_code.startswith(('0', '3')):
            prefix = 'sz'
        elif ts_code.startswith('8'):
            prefix = 'bj'
        else:
            prefix = ''
    return symbol, prefix, prefix + symbol


def _safe_float(val) -> float:
    """安全转 float，失败返回 0.0"""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _safe_str(val) -> str:
    """安全转 str，None 时返回空字符串"""
    return str(val) if val is not None else ''


# ── 股票名称/指数名称查询 ────────────────────────────────

_STOCK_NAME_MAP = {
    '600519.SH': '贵州茅台', '000001.SZ': '平安银行',
    '000002.SZ': '万科A', '000858.SZ': '五粮液',
    '000063.SZ': '中兴通讯', '601318.SH': '中国平安',
    '600036.SH': '招商银行', '000333.SZ': '美的集团',
    '600000.SH': '浦发银行', '002415.SZ': '海康威视',
    '601166.SH': '兴业银行', '000651.SZ': '格力电器',
    '002594.SZ': '比亚迪', '300750.SZ': '宁德时代',
    '601012.SH': '隆基绿能', '600276.SH': '恒瑞医药',
    '601398.SH': '工商银行', '600900.SH': '长江电力',
    '688981.SH': '中芯国际', '002714.SZ': '牧原股份',
}

_INDEX_NAME_MAP = {
    '000001.SH': '上证指数', '399001.SZ': '深证成指',
    '399006.SZ': '创业板指', '000300.SH': '沪深300',
    '000016.SH': '上证50', '000905.SH': '中证500',
    '000688.SH': '科创50', '399852.SZ': '中证1000',
}


def _get_stock_name(ts_code: str) -> str:
    """获取股票中文名称（内置映射+代码回退）"""
    return _STOCK_NAME_MAP.get(ts_code, ts_code)


def _get_index_name(ts_code: str) -> str:
    """获取指数中文名称"""
    return _INDEX_NAME_MAP.get(ts_code, ts_code)


# ══════════════════════════════════════════════════════════════
# AkshareProvider — 主类
# ══════════════════════════════════════════════════════════════

class AkshareProvider:
    """AKShare 数据提供者 — 覆盖 15 个 API 方法

    所有方法均使用 try/except 容错，失败返回 None/[]。
    本层不缓存（由上层 TieredMemoryCache 负责）。
    """

    def __init__(self):
        self.name = "Akshare"
        self.source = "东方财富"

    # ── 1. 实时盘口（stock_bid_ask_em）──

    def get_realtime_quote(self, ts_code: str) -> Optional[Dict]:
        """获取单只股票实时盘口数据（卖一~卖五/买一~买五）

        返回 28 字段：股票信息 + 现价/涨跌/开盘/最高/最低/昨收 + 五档盘口 + 成交量/额/换手
        """
        ak = _get_ak()
        if ak is None:
            return None
        try:
            symbol, _, _ = _parse_ts_code(ts_code)
            df = ak.stock_bid_ask_em(symbol=symbol)
            if df is None or df.empty:
                return None
            record = df.set_index('item')['value'].to_dict()
            return {
                'ts_code': ts_code,
                'name': _get_stock_name(ts_code),
                'price': _safe_float(record.get('最新', 0)),
                'change': _safe_float(record.get('涨跌', 0)),
                'change_pct': _safe_float(record.get('涨幅', 0)),
                'open': _safe_float(record.get('今开', 0)),
                'high': _safe_float(record.get('最高', 0)),
                'low': _safe_float(record.get('最低', 0)),
                'prev_close': _safe_float(record.get('昨收', 0)),
                'volume': _safe_float(record.get('总手', 0)),
                'amount': _safe_float(record.get('金额', 0)),
                'bid_price': _safe_float(record.get('buy_1', 0)),
                'ask_price': _safe_float(record.get('sell_1', 0)),
                'bid_vol': _safe_float(record.get('buy_1_vol', 0)),
                'ask_vol': _safe_float(record.get('sell_1_vol', 0)),
                'turnover_rate': _safe_float(record.get('换手', 0)),
                'pe': _safe_float(record.get('市盈率', 0)),
                'amplitude': _safe_float(record.get('振幅', 0)),
                'high_52w': _safe_float(record.get('52周最高', 0)),
                'low_52w': _safe_float(record.get('52周最低', 0)),
                'timestamp': datetime.now().isoformat(),
                'source': 'akshare',
            }
        except Exception as e:
            logger.error(f"Akshare get_realtime_quote({ts_code}) 失败: {e}")
            return None

    # ── 2. 实时行情快照（stock_zh_a_spot_em）──

    def get_realtime_spot(self, ts_code: str) -> Optional[Dict]:
        """获取单只股票实时行情快照（28 字段）

        通过全市场快照按代码过滤，适用于批量查询场景。
        """
        try:
            snapshot = self.get_market_snapshot()
            if not snapshot:
                return None
            for s in snapshot:
                if s.get('ts_code') == ts_code:
                    return s
            return None
        except Exception as e:
            logger.error(f"Akshare get_realtime_spot({ts_code}) 失败: {e}")
            return None

    def get_market_snapshot(self) -> List[Dict]:
        """获取全市场股票实时行情快照

        单次调用返回约 5000 只 A 股的实时数据（最新价/涨跌幅/成交量/PE/PB 等）。
        缓存策略：上层 TieredMemoryCache — realtime 级别 3s TTL。
        """
        ak = _get_ak()
        if ak is None:
            return []
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.iterrows():
                results.append({
                    'ts_code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'price': _safe_float(row.get('最新价', 0)),
                    'change': _safe_float(row.get('涨跌额', 0)),
                    'change_pct': _safe_float(row.get('涨跌幅', 0)),
                    'open': _safe_float(row.get('今开', 0)),
                    'high': _safe_float(row.get('最高', 0)),
                    'low': _safe_float(row.get('最低', 0)),
                    'prev_close': _safe_float(row.get('昨收', 0)),
                    'volume': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'turnover_rate': _safe_float(row.get('换手率', 0)),
                    'pe': _safe_float(row.get('市盈率-动态', 0)),
                    'pb': _safe_float(row.get('市净率', 0)),
                    'amplitude': _safe_float(row.get('振幅', 0)),
                    'circ_mv': _safe_float(row.get('流通市值', 0)),
                    'total_mv': _safe_float(row.get('总市值', 0)),
                    'volume_ratio': _safe_float(row.get('量比', 0)),
                    'timestamp': datetime.now().isoformat(),
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_market_snapshot() 失败: {e}")
            return []

    def get_batch_quotes(self, ts_codes: List[str]) -> List[Dict]:
        """批量获取指定股票列表的实时行情（通过全市场快照过滤）"""
        snapshot = self.get_market_snapshot()
        if not snapshot:
            return []
        code_set = set(ts_codes)
        return [s for s in snapshot if s.get('ts_code') in code_set]

    def get_realtime_quotes(self, ts_codes: List[str]) -> List[Dict]:
        """兼容方法：get_batch_quotes 的别名"""
        return self.get_batch_quotes(ts_codes)

    # ── 3. 指数行情（index_zh_a_hist）──

    def get_index_daily(self, ts_code: str) -> Optional[Dict]:
        """获取指数日线数据（盘中返回包含今日实时数据）"""
        ak = _get_ak()
        if ak is None:
            return None
        try:
            symbol, prefix, _ = _parse_ts_code(ts_code)
            # index_zh_a_hist 需要 sh000001 格式
            df = ak.index_zh_a_hist(symbol=prefix + symbol, period='daily',
                                     start_date='20200101', end_date=datetime.now().strftime('%Y%m%d'))
            if df is None or df.empty:
                return None
            latest = df.iloc[-1]
            return {
                'ts_code': ts_code,
                'name': _get_index_name(ts_code),
                'value': _safe_float(latest.get('收盘', 0)),
                'change': _safe_float(latest.get('涨跌额', 0)),
                'change_pct': _safe_float(latest.get('涨跌幅', 0)),
                'open': _safe_float(latest.get('开盘', 0)),
                'high': _safe_float(latest.get('最高', 0)),
                'low': _safe_float(latest.get('最低', 0)),
                'volume': _safe_float(latest.get('成交量', 0)),
                'amount': _safe_float(latest.get('成交额', 0)),
                'trade_date': str(latest.get('日期', '')),
                'timestamp': datetime.now().isoformat(),
                'source': 'akshare',
            }
        except Exception as e:
            logger.error(f"Akshare get_index_daily({ts_code}) 失败: {e}")
            return None

    def get_index_realtime(self, ts_code: str) -> Optional[Dict]:
        """获取指数实时行情（通过 stock_bid_ask_em）—— 保留原 AkShareRealtimeProvider 兼容"""
        ak = _get_ak()
        if ak is None:
            return None
        try:
            symbol, _, full_symbol = _parse_ts_code(ts_code)
            df = ak.stock_bid_ask_em(symbol=full_symbol)
            if df is None or df.empty:
                return None
            record = df.set_index('item')['value'].to_dict()
            return {
                'ts_code': ts_code,
                'name': _get_index_name(ts_code),
                'value': _safe_float(record.get('最新', 0)),
                'change': _safe_float(record.get('涨跌', 0)),
                'change_pct': _safe_float(record.get('涨幅', 0)),
                'open': _safe_float(record.get('今开', 0)),
                'high': _safe_float(record.get('最高', 0)),
                'low': _safe_float(record.get('最低', 0)),
                'prev_close': _safe_float(record.get('昨收', 0)),
                'volume': _safe_float(record.get('总手', 0)),
                'amount': _safe_float(record.get('金额', 0)),
                'timestamp': datetime.now().isoformat(),
                'source': 'akshare',
            }
        except Exception as e:
            logger.error(f"Akshare get_index_realtime({ts_code}) 失败: {e}")
            return None

    # ── 4. 日线数据（stock_zh_a_hist）──

    def get_daily_data(self, ts_code: str,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict]:
        """获取股票日线数据（盘中调用时包含当日未收盘 K 线）

        支持复权参数。无 start/end 时默认取最近 1 年。
        """
        ak = _get_ak()
        if ak is None:
            return []
        try:
            symbol, _, _ = _parse_ts_code(ts_code)
            if not start_date:
                start_date = '20250101'
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')
            df = ak.stock_zh_a_hist(symbol=symbol, period='daily',
                                     start_date=start_date, end_date=end_date,
                                     adjust='qfq')  # 前复权
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.iterrows():
                results.append({
                    'ts_code': ts_code,
                    'trade_date': str(row.get('日期', '')),
                    'open': _safe_float(row.get('开盘', 0)),
                    'high': _safe_float(row.get('最高', 0)),
                    'low': _safe_float(row.get('最低', 0)),
                    'close': _safe_float(row.get('收盘', 0)),
                    'pre_close': _safe_float(row.get('昨收', 0)),
                    'change': _safe_float(row.get('涨跌额', 0)),
                    'pct_chg': _safe_float(row.get('涨跌幅', 0)),
                    'volume': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'turnover_rate': _safe_float(row.get('换手率', 0)),
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_daily_data({ts_code}) 失败: {e}")
            return []

    # ── 5. 分钟 K 线（stock_zh_a_hist_min_em）──

    def get_minute_data(self, ts_code: str, freq: str = '15min',
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> List[Dict]:
        """获取分钟 K 线数据

        频率支持: 1min / 5min / 15min / 30min / 60min
        """
        ak = _get_ak()
        if ak is None:
            return []
        try:
            symbol, _, _ = _parse_ts_code(ts_code)
            df = ak.stock_zh_a_hist_min_em(symbol=symbol, period=freq,
                                            start_date=start_date or '',
                                            end_date=end_date or '')
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.iterrows():
                results.append({
                    'trade_time': str(row.get('时间', '')),
                    'open': _safe_float(row.get('开盘', 0)),
                    'high': _safe_float(row.get('最高', 0)),
                    'low': _safe_float(row.get('最低', 0)),
                    'close': _safe_float(row.get('收盘', 0)),
                    'vol': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_minute_data({ts_code}, {freq}) 失败: {e}")
            return []

    # ── 6. 资金流向（stock_individual_fund_flow）──

    def get_moneyflow(self, ts_code: str,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> List[Dict]:
        """获取个股资金流向"""
        ak = _get_ak()
        if ak is None:
            return []
        try:
            symbol, _, _ = _parse_ts_code(ts_code)
            if not start_date:
                start_date = (datetime.now().replace(day=1)).strftime('%Y%m%d')
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')
            df = ak.stock_individual_fund_flow(stock=symbol, market='sh',
                                                start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.iterrows():
                results.append({
                    'ts_code': ts_code,
                    'trade_date': str(row.get('日期', '')),
                    'close': _safe_float(row.get('收盘价', 0)),
                    'change_pct': _safe_float(row.get('涨跌幅', 0)),
                    'net_lg_amount': _safe_float(row.get('主力净流入-净额', 0)),
                    'net_lg_ratio': _safe_float(row.get('主力净流入-净占比', 0)),
                    'net_super_lg_amount': _safe_float(row.get('超大单净流入-净额', 0)),
                    'net_super_lg_ratio': _safe_float(row.get('超大单净流入-净占比', 0)),
                    'net_lg_single_amount': _safe_float(row.get('大单净流入-净额', 0)),
                    'net_lg_single_ratio': _safe_float(row.get('大单净流入-净占比', 0)),
                    'net_mid_amount': _safe_float(row.get('中单净流入-净额', 0)),
                    'net_mid_ratio': _safe_float(row.get('中单净流入-净占比', 0)),
                    'net_sm_amount': _safe_float(row.get('小单净流入-净额', 0)),
                    'net_sm_ratio': _safe_float(row.get('小单净流入-净占比', 0)),
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_moneyflow({ts_code}) 失败: {e}")
            return []

    # ── 7. 板块/概念排行 ──

    def get_sector_rankings(self) -> List[Dict]:
        """获取行业板块实时涨幅排行"""
        ak = _get_ak()
        if ak is None:
            return []
        try:
            df = ak.stock_board_industry_em()
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.iterrows():
                results.append({
                    'name': str(row.get('板块名称', '')),
                    'code': str(row.get('板块代码', '')),
                    'index_price': _safe_float(row.get('最新价', 0)),
                    'change_pct': _safe_float(row.get('涨跌幅', 0)),
                    'up_count': int(row.get('上涨家数', 0)),
                    'down_count': int(row.get('下跌家数', 0)),
                    'volume': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'lead_stock': str(row.get('领涨股票', '')),
                    'lead_change_pct': _safe_float(row.get('领涨涨幅', 0)),
                    'timestamp': datetime.now().isoformat(),
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_sector_rankings() 失败: {e}")
            return []

    def get_concept_rankings(self) -> List[Dict]:
        """获取概念板块实时涨幅排行"""
        ak = _get_ak()
        if ak is None:
            return []
        try:
            df = ak.stock_board_concept_em()
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.iterrows():
                results.append({
                    'name': str(row.get('板块名称', '')),
                    'code': str(row.get('板块代码', '')),
                    'index_price': _safe_float(row.get('最新价', 0)),
                    'change_pct': _safe_float(row.get('涨跌幅', 0)),
                    'up_count': int(row.get('上涨家数', 0)),
                    'down_count': int(row.get('下跌家数', 0)),
                    'volume': _safe_float(row.get('成交量', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'lead_stock': str(row.get('领涨股票', '')),
                    'lead_change_pct': _safe_float(row.get('领涨涨幅', 0)),
                    'timestamp': datetime.now().isoformat(),
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_concept_rankings() 失败: {e}")
            return []

    # ── 8. 新闻（stock_news_em）──

    def get_news(self, start_date: Optional[str] = None,
                  end_date: Optional[str] = None) -> List[Dict]:
        """获取盘中财经新闻"""
        ak = _get_ak()
        if ak is None:
            return []
        try:
            df = ak.stock_news_em()
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.head(50).iterrows():
                results.append({
                    'title': str(row.get('标题', '')),
                    'url': str(row.get('链接', '')),
                    'pub_time': str(row.get('发布时间', '')),
                    'content': str(row.get('内容', '')),
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_news() 失败: {e}")
            return []

    # ── 9. 涨跌停池（stock_zt_pool_em）──

    def get_limit_pool(self) -> Dict:
        """获取当日涨停/跌停股票池"""
        ak = _get_ak()
        if ak is None:
            return {'up': [], 'down': []}
        try:
            result = {'up': [], 'down': []}
            # 涨停
            df_up = ak.stock_zt_pool_em(symbol='涨停')
            if df_up is not None and not df_up.empty:
                for _, row in df_up.iterrows():
                    result['up'].append({
                        'ts_code': str(row.get('代码', '')),
                        'name': str(row.get('名称', '')),
                        'price': _safe_float(row.get('最新价', 0)),
                        'change_pct': _safe_float(row.get('涨跌幅', 0)),
                        'turnover_rate': _safe_float(row.get('换手率', 0)),
                        'amount': _safe_float(row.get('成交额', 0)),
                        'limit_up_times': int(row.get('连板', 1)),
                    })
            # 跌停
            df_down = ak.stock_zt_pool_em(symbol='跌停')
            if df_down is not None and not df_down.empty:
                for _, row in df_down.iterrows():
                    result['down'].append({
                        'ts_code': str(row.get('代码', '')),
                        'name': str(row.get('名称', '')),
                        'price': _safe_float(row.get('最新价', 0)),
                        'change_pct': _safe_float(row.get('涨跌幅', 0)),
                        'turnover_rate': _safe_float(row.get('换手率', 0)),
                        'amount': _safe_float(row.get('成交额', 0)),
                    })
            return result
        except Exception as e:
            logger.error(f"Akshare get_limit_pool() 失败: {e}")
            return {'up': [], 'down': []}

    # ── 10. 龙虎榜（stock_lhb_detail_em）──

    def get_lhb_detail(self, trade_date: Optional[str] = None) -> List[Dict]:
        """获取龙虎榜数据"""
        ak = _get_ak()
        if ak is None:
            return []
        try:
            if not trade_date:
                trade_date = datetime.now().strftime('%Y%m%d')
            df = ak.stock_lhb_detail_em(start_date=trade_date, end_date=trade_date)
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.head(100).iterrows():
                results.append({
                    'ts_code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'reason': str(row.get('上榜原因', '')),
                    'close': _safe_float(row.get('收盘价', 0)),
                    'change_pct': _safe_float(row.get('涨跌幅', 0)),
                    'buy_amount': _safe_float(row.get('买入额', 0)),
                    'sell_amount': _safe_float(row.get('卖出额', 0)),
                    'net_amount': _safe_float(row.get('净额', 0)),
                    'amount': _safe_float(row.get('成交额', 0)),
                    'trade_date': trade_date,
                    'source': 'akshare',
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_lhb_detail() 失败: {e}")
            return []

    # ── 11. 连接测试 ──

    def test_connection(self) -> bool:
        """测试 AKShare 连接是否正常"""
        ak = _get_ak()
        if ak is None:
            return False
        try:
            df = ak.stock_zh_a_spot_em()
            return df is not None and not df.empty
        except Exception as e:
            logger.error(f"Akshare 连接测试失败: {e}")
            return False

    def get_stock_list(self) -> List[Dict]:
        """获取全部 A 股股票列表"""
        ak = _get_ak()
        if ak is None:
            return []
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return []
            results = []
            for _, row in df.iterrows():
                results.append({
                    'ts_code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'industry': str(row.get('行业', '')),
                })
            return results
        except Exception as e:
            logger.error(f"Akshare get_stock_list() 失败: {e}")
            return []

    # ── 盘口（get_orderbook — get_realtime_quote 的别名）──

    def get_orderbook(self, ts_code: str) -> Optional[Dict]:
        """获取盘口五档数据（get_realtime_quote 别名）"""
        return self.get_realtime_quote(ts_code)

    # ── `_route_provider` 兼容方法 ──

    def get_index_member(self, index_code: str) -> List[Dict]:
        """获取指数成分股（AKShare 暂不支持，返回空列表）"""
        logger.warning(f"Akshare 暂不支持 get_index_member({index_code})")
        return []

    def get_adj_factor(self, ts_code: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取复权因子（AKShare 通过 get_daily_data 含复权数据）"""
        return self.get_daily_data(ts_code, start_date, end_date)

    def get_top_list(self, trade_date: str = None, ts_code: str = None) -> List[Dict]:
        """龙虎榜（get_lhb_detail 别名）"""
        return self.get_lhb_detail(trade_date)

    def get_stk_limit(self, ts_code: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        """涨跌停限制（AKShare 暂不支持）"""
        logger.warning(f"Akshare 暂不支持 get_stk_limit({ts_code})")
        return []


# ══════════════════════════════════════════════════════════════
# 向后兼容：保留 AkShareRealtimeProvider 类名
# ══════════════════════════════════════════════════════════════

class AkShareRealtimeProvider(AkshareProvider):
    """保留旧类名用于向后兼容 —— 直接继承 AkshareProvider"""
    pass


# ══════════════════════════════════════════════════════════════
# 自测
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    provider = AkshareProvider()

    logger.info("=== AkshareProvider 自测 ===")

    # 1. 连接测试
    ok = provider.test_connection()
    logger.info(f"1. 连接测试: {'✅' if ok else '❌'}")
    if not ok:
        sys.exit(1)

    # 2. 实时盘口
    logger.info("2. 贵州茅台盘口:")
    q = provider.get_realtime_quote('600519.SH')
    if q:
        logger.info(f"   最新价: {q['price']}  涨跌幅: {q['change_pct']}%")

    # 3. 批量行情
    logger.info("3. 自选股批量行情:")
    stocks = ['600519.SH', '000001.SZ', '000002.SZ', '601318.SH', '000858.SZ']
    quotes = provider.get_batch_quotes(stocks)
    for q in quotes:
        logger.info(f"   {q['name']}({q['ts_code']}): {q['price']} ({q['change_pct']:+.2f}%)")

    # 4. 板块排行
    logger.info("4. 行业板块排行:")
    sectors = provider.get_sector_rankings()
    if sectors:
        for s in sectors[:5]:
            logger.info(f"   {s['name']}: {s['change_pct']:+.2f}%")

    # 5. 涨跌停池
    logger.info("5. 涨跌停池:")
    pool = provider.get_limit_pool()
    logger.info(f"   涨停: {len(pool.get('up', []))} 只")
    logger.info(f"   跌停: {len(pool.get('down', []))} 只")

    logger.info("=== 自测完成 ===")
