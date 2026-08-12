from .tushare_provider import TushareProvider
from .enhanced_cache_manager import get_ecm_instance, EnhancedCacheManager
from app.models import Stock
from app import db
from datetime import datetime
import pandas as pd
from sqlalchemy import or_


import logging
logger = logging.getLogger(__name__)
class DataManager:
    def __init__(self):
        self.tushare = TushareProvider()
        self.cache = get_ecm_instance()
        # 加载活跃数据源（支持 AKShare 回退）
        try:
            from .data_source_manager import data_source_manager
            self._source_mgr = data_source_manager
        except Exception:
            self._source_mgr = None
    
    def sync_stock_list(self):
        stocks = self.tushare.get_stock_list()
        
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
                db.session.add(new_stock)
        
        db.session.commit()
        return len(stocks)
    
    def sync_daily_data(self, ts_code, use_cache=True, start_date=None, end_date=None):
        """同步日线数据，优先使用缓存"""
        # 先尝试从缓存获取
        if use_cache:
            cached_df = self.cache.get_cached_daily(ts_code, start_date, end_date)
            if not cached_df.empty:
                logger.info(f"使用缓存数据: {ts_code}")
                return len(cached_df)
        
        # 缓存未命中，从活跃数据源获取（Tushare → AKShare 回退）
        data = self.tushare.get_daily_data(ts_code, start_date, end_date)

        if not data and self._source_mgr:
            try:
                active = self._source_mgr.get_active_source_name()
                if active and active != 'tushare':
                    from .akshare_provider import AkshareProvider
                    akshare = AkshareProvider()
                    data = akshare.get_daily_data(ts_code, start_date, end_date)
                    if data:
                        logger.info(f"从 akshare 获取 {ts_code} 日线数据: {len(data)} 条")
            except Exception as e:
                logger.warning(f"回退 akshare 获取 {ts_code} 数据失败: {e}")

        if not data:
            return 0

        # 转换为DataFrame
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'vol': item.get('vol'),
                'amount': item.get('amount'),
                'pct_chg': item.get('pct_chg')
            })

        if df_data:
            df = pd.DataFrame(df_data)
            # 缓存到增强缓存系统
            self.cache.cache_daily_data(df)
            return len(df)

        return 0

    def sync_all_daily_data(self, max_stocks: int = None, resume_from: str = None) -> int:
        """全量同步所有股票日线数据（带断点续传）

        对每只股票检查 daily_cache 中已有数据的天数：
        - 已有 120 天以上数据 → 跳过（不需要全量覆盖）
        - 数据不足 120 天 → 增量同步（从最后交易日到今日）
        - 完全无数据 → 全量同步

        每 100 只提交一次批次。
        中途失败后可通过 resume_from 参数（ts_code）断点续传。

        Args:
            max_stocks: 最大同步数量（None = 全部）
            resume_from: 从指定 ts_code 开始续传（None = 从头开始）

        Returns:
            同步的记录总数
        """
        stocks = Stock.query.order_by(Stock.ts_code).all()
        count = 0
        skipped = 0
        started = resume_from is None  # resume_from=None 直接开始

        for stock in stocks:
            if resume_from and stock.ts_code == resume_from:
                started = True
            if not started:
                continue

            # 检查已有数据量
            existing_df = self.cache.get_cached_daily(stock.ts_code)
            if not existing_df.empty and len(existing_df) >= 120:
                skipped += 1
                if skipped % 200 == 0:
                    logger.info(f"全量同步跳过已有数据的股票: {skipped} 只")
                continue

            if existing_df.empty:
                # 无数据 → 全量同步（5年）
                cnt = self.sync_daily_data(stock.ts_code, use_cache=False)
            else:
                # 数据不足 → 增量补齐
                last_date = existing_df['trade_date'].max()
                if hasattr(last_date, 'strftime'):
                    start_date = last_date.strftime('%Y%m%d')
                else:
                    start_date = str(last_date).replace('-', '')
                cnt = self.sync_daily_data(
                    stock.ts_code, use_cache=False,
                    start_date=start_date
                )

            count += cnt
            if count % 100 == 0:
                logger.info(f"全量同步进度: {count} 条（跳过 {skipped} 只已有数据）")
                db.session.commit()
            if max_stocks and count >= max_stocks:
                break

        db.session.commit()
        logger.info(f"全量同步完成: {count} 条（跳过 {skipped} 只已有数据）")
        return count
    
    def get_cached_daily_data(self, ts_code, start_date=None, end_date=None, adj=None):
        """从缓存获取日线数据
        Args:
            adj: 复权方式 None=不复权 'hfq'=后复权 'qfq'=前复权
        """
        df = self.cache.get_cached_daily(ts_code, start_date, end_date)
        if df.empty or adj is None:
            return df
        return self._apply_adjust_factor(df, adj)
    
    def _apply_adjust_factor(self, df, adj):
        """对日线DataFrame应用复权因子"""
        if df.empty or adj not in ('hfq', 'qfq'):
            return df
        try:
            ts_code = df['ts_code'].iloc[0]
            df_adj = self.cache.get_cached_adj_factor(ts_code)
            if df_adj is None or df_adj.empty:
                return df
            df_merged = df.merge(df_adj[['trade_date', 'adj_factor']], on='trade_date', how='left')
            df_merged['adj_factor'] = df_merged['adj_factor'].ffill().fillna(1.0)
            if adj == 'hfq':
                # 后复权：以最新复权因子为基准
                base_adj = df_merged['adj_factor'].iloc[-1]
                df_merged['adj_factor'] = df_merged['adj_factor'] / base_adj
            else:
                # 前复权：以最早复权因子为基准
                base_adj = df_merged['adj_factor'].iloc[0]
                df_merged['adj_factor'] = df_merged['adj_factor'] / base_adj
            for col in ['open', 'high', 'low', 'close']:
                if col in df_merged.columns:
                    df_merged[col] = df_merged[col] * df_merged['adj_factor']
            if 'vol' in df_merged.columns:
                df_merged['vol'] = df_merged['vol'] / df_merged['adj_factor'].replace(0, 1)
            df_merged.drop(columns=['adj_factor'], inplace=True)
            return df_merged
        except Exception as e:
            logger.warning("复权计算失败 (%s): %s", df.get('ts_code', '?'), e)
            return df

    def get_cached_daily_batch(self, ts_codes, start_date=None, end_date=None):
        """批量获取日线数据（全量预加载 + 内存分组）"""
        return self.cache.get_cached_daily_batch(ts_codes, start_date, end_date)

    def preload_cache(self):
        """缓存预热 — 从 Stock 表获取股票列表，逐只预热"""
        stocks = Stock.query.all()
        count = 0
        for s in stocks:
            self.get_cached_daily_data(s.ts_code)
            count += 1
            if count % 50 == 0:
                logger.info(f"已预热 {count} 只股票")
        logger.info(f"缓存预热完成: {count} 只股票")

    def get_cache_stats(self):
        """获取缓存统计信息"""
        return self.cache.get_cache_stats()
    
    def get_stock_info(self, ts_code):
        """获取单只股票信息"""
        stock = Stock.query.get(ts_code)
        return stock.to_dict() if stock else None

    def get_stock_meta_batch(self, ts_codes: list[str]) -> dict[str, dict]:
        """批量获取股票元信息（名称 + 行业），减少 ORM 查询次数"""
        rows = db.session.query(Stock.ts_code, Stock.name, Stock.industry).filter(
            Stock.ts_code.in_(ts_codes)
        ).all()
        return {r.ts_code: {'name': r.name, 'industry': r.industry} for r in rows}

    def get_all_ts_codes(self, limit: int = 5000) -> list[str]:
        """获取全市场股票代码列表"""
        rows = Stock.query.with_entities(Stock.ts_code).limit(limit).all()
        return [r.ts_code for r in rows]

    def get_ts_codes_by_industry(self, industry: str, ts_codes: list[str] = None) -> list[str]:
        """按行业筛选股票代码"""
        query = db.session.query(Stock.ts_code).filter(Stock.industry == industry)
        if ts_codes:
            query = query.filter(Stock.ts_code.in_(ts_codes))
        return [r.ts_code for r in query.all()]
    
    def get_stock_list(self, keyword=None, limit=50):
        """
        获取股票列表，支持按代码/名称/行业搜索
        
        Args:
            keyword: 搜索关键词（匹配 ts_code / name / industry）
            limit: 最大返回数量
        """
        query = Stock.query.order_by(Stock.ts_code)
        if keyword:
            query = query.filter(
                or_(
                    Stock.ts_code.ilike(f'%{keyword}%'),
                    Stock.name.ilike(f'%{keyword}%'),
                    Stock.industry.ilike(f'%{keyword}%'),
                )
            )
        stocks = query.limit(limit).all()
        return [s.to_dict() for s in stocks]
    
    def get_stock_industry(self, ts_code: str) -> str | None:
        """通过 DataManager 返回股票行业分类（申万一级），符合 Red Line 5"""
        stock = db.session.query(Stock).filter(Stock.ts_code == ts_code).first()
        return stock.industry if stock else None

    def get_stock_industry_batch(self, ts_codes: list[str]) -> dict[str, str | None]:
        """批量查询行业分类，减少 ORM 查询次数"""
        stocks = db.session.query(Stock.ts_code, Stock.industry).filter(
            Stock.ts_code.in_(ts_codes)
        ).all()
        return {s.ts_code: s.industry for s in stocks}

    # ── Treemap 快照（305号§2.2） ──

    def get_treemap_snapshot(self, ts_codes: list[str]) -> pd.DataFrame:
        """从 treemap_snapshot 表批量读取快照数据（委托 ECM）"""
        return self.cache.get_treemap_snapshot(ts_codes)

    def get_treemap_snapshot_items(self, ts_codes: list[str]) -> list[dict]:
        """获取组装好的快照数据（委托 ECM）"""
        return self.cache.get_treemap_snapshot_items(ts_codes)

    def get_snapshot_max_date(self) -> str | None:
        """获取 treemap_snapshot 最新构建日期（合规整改网关）"""
        try:
            return self.cache.get_snapshot_max_date()
        except Exception:
            return None

    def get_snapshot_data_date(self) -> str | None:
        """获取 treemap_snapshot 的数据交易日（327阶段3：区分构建时间 vs 数据时间）

        快照表 trade_date 列 = 实际数据交易日（如 08-10），snapshot_date = 构建日。
        前端标注"数据截至 trade_date"用，避免将构建日误当数据日。
        """
        try:
            return self.cache.get_snapshot_data_date()
        except Exception:
            return None

    def get_previous_trade_date(self) -> str | None:
        """获取上一交易日（L4 日变检测用，替代调用层直连 daily_cache）"""
        try:
            return self.cache.get_previous_trade_date()
        except Exception:
            return None

    def get_tags_by_date(self, ts_code: str, trade_date: str | None = None) -> dict:
        """获取指定股票在指定日期的标签 dict（L4 日变检测用）

        未指定 trade_date 时返回该股票最新标签（委托 ECM.get_tags）。
        """
        return self.cache.get_tags_by_date(ts_code, trade_date)

    def get_tags_by_group(self, ts_code: str, groups: list[str]) -> dict:
        """按 tag_group 取子集（323号 S0.5：引擎B 差异化取用深度字段）"""
        return self.cache.get_tags_by_group(ts_code, groups)

    def clear_stock_cache(self, ts_code: str) -> bool:
        """清除单只股票缓存（缓存失效路由用，替代调用层直连 DELETE）"""
        return self.cache.clear_stock_cache(ts_code)

    # ── 管道状态（305号§9.2） ──

    def load_pipeline_status(self, pipeline_date: str) -> dict:
        return self.cache.load_pipeline_status(pipeline_date)

    def ensure_pipeline_steps(self, pipeline_date: str):
        self.cache.ensure_pipeline_steps(pipeline_date)

    def mark_step_running(self, pipeline_date: str, step_id: str) -> bool:
        return self.cache.mark_step_running(pipeline_date, step_id)

    def mark_step_done(self, pipeline_date: str, step_id: str, detail: str = ''):
        self.cache.mark_step_done(pipeline_date, step_id, detail)

    def mark_step_failed(self, pipeline_date: str, step_id: str, detail: str = ''):
        self.cache.mark_step_failed(pipeline_date, step_id, detail)

    def get_kline_data(self, ts_code, period='D', start_date=None, end_date=None):
        """
        获取K线数据
        period: D(日线)/W(周线)/M(月线)/1m/5m/15m/30m/60m
        """
        if period == 'D':
            return self.get_cached_daily_data(ts_code, start_date, end_date)
        elif period == 'W':
            return self._get_weekly_data(ts_code, start_date, end_date)
        elif period == 'M':
            return self._get_monthly_data(ts_code, start_date, end_date)
        elif period in ['1m', '5m', '15m', '30m', '60m']:
            return self._get_minute_data(ts_code, period, start_date, end_date)
        else:
            return self.get_cached_daily_data(ts_code, start_date, end_date)
    
    def _get_mootdx_bars(self, ts_code: str, freq: int = 9,
                         start: int = 0, offset: int = 800):
        """从 mootdx(TDX TCP) 获取K线数据，统一返回标准化 DataFrame
        
        Args:
            ts_code: 股票代码（含市场后缀，如 301042.SZ）
            freq: TDX频率码 9=日线 5=周线 2=5分钟 1=1分钟
            start: 起始偏移（用于分页）
            offset: 返回行数上限（最大800）
        
        Returns:
            标准化 DataFrame，列: ts_code, trade_date/trade_time, open, high, low, close, vol, amount
        """
        try:
            from mootdx.quotes import Quotes
            client = Quotes.factory(market='std')
            symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            raw = client.bars(symbol=symbol, frequency=freq, start=start, offset=offset)
            if raw is None or raw.empty:
                return pd.DataFrame()
            # 统一vol列名（mootdx同时返回vol和volume）
            if 'volume' in raw.columns and 'vol' not in raw.columns:
                df = raw.rename(columns={'volume': 'vol'})
            elif 'vol' in raw.columns:
                df = raw.copy()
                if 'volume' in raw.columns:
                    df.drop(columns=['volume'], inplace=True)
            else:
                df = raw.copy()
            df['ts_code'] = ts_code
            if 'date' in df.columns:
                df = df.rename(columns={'date': 'trade_date'})
            elif 'datetime' in df.columns:
                df = df.rename(columns={'datetime': 'trade_time'})
                if 'trade_date' not in df.columns and 'year' in df.columns:
                    df['trade_date'] = pd.to_datetime(
                        df[['year', 'month', 'day']].astype(int).astype(str).agg('-'.join, axis=1)
                    )
            cols = {'ts_code', 'open', 'high', 'low', 'close', 'vol', 'amount'}
            cols_exist = [c for c in cols if c in df.columns]
            return df[cols_exist]
        except Exception as e:
            logger.warning("_get_mootdx_bars(%s) 失败: %s", ts_code, e)
            return pd.DataFrame()
    
    def _get_weekly_data(self, ts_code, start_date=None, end_date=None):
        """获取周线数据，ECM缓存优先"""
        # 查ECM缓存（用 minute_kline_cache freq='W' 存储）
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            df_cached = ecm.get_cached_minute_kline(ts_code, freq='W')
            if df_cached is not None and not df_cached.empty:
                if 'vol' not in df_cached.columns and 'volume' in df_cached.columns:
                    df_cached = df_cached.rename(columns={'volume': 'vol'})
                return df_cached
        except Exception:
            pass

        # 2026-08-11 修复：周线从本地日线聚合并缓存到 ECM（freq='W'）。
        # 原实现在缓存 miss 时直调 mootdx TCP（292号红线：非采集层禁止直调数据源），
        # 且连接失败触发 3.6s sleep 重试——这是 P2 缠论计算慢（4.5s/只）的根因。
        # 现改为：日线聚合优先 + 缓存，消除数据源直调与网络重试（缠论 4.5s→0.05s）。
        daily_data = self.get_cached_daily_data(ts_code, start_date, end_date)
        if not daily_data.empty:
            weekly_df = self._aggregate_daily_to_weekly(daily_data)
            if not weekly_df.empty:
                # 写入 ECM 周线缓存（freq='W'，供后续命中；写入失败不阻塞返回）
                try:
                    wk_cache = weekly_df.copy()
                    # 剔除缓存表不支持的派生列（pct_chg 等），日期转字符串（Timestamp 无法参数化绑定）
                    for _drop_col in ('pct_chg',):
                        if _drop_col in wk_cache.columns:
                            wk_cache = wk_cache.drop(columns=[_drop_col])
                    if 'trade_date' in wk_cache.columns:
                        wk_cache['trade_date'] = wk_cache['trade_date'].astype(str)
                    if 'trade_time' not in wk_cache.columns:
                        wk_cache['trade_time'] = wk_cache['trade_date']
                    self._cache_minute_to_ecm(wk_cache, ts_code, 'W')
                except Exception:
                    pass
                return weekly_df

        # Tushare 备选
        data = self.tushare.get_weekly_data(ts_code, start_date, end_date)
        if not data:
            return pd.DataFrame()
        
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'vol': item.get('vol'),
                'amount': item.get('amount'),
                'pct_chg': item.get('pct_chg')
            })
        df = pd.DataFrame(df_data) if df_data else pd.DataFrame()
        if not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
        return df
    
    def _get_monthly_data(self, ts_code, start_date=None, end_date=None):
        """获取月线数据，优先从本地日线聚合"""
        # 优先使用本地日线聚合，确保数据新鲜
        daily_data = self.get_cached_daily_data(ts_code, start_date, end_date)
        if not daily_data.empty:
            return self._aggregate_daily_to_monthly(daily_data)
        
        # 日线数据不存在时才从Tushare获取
        data = self.tushare.get_monthly_data(ts_code, start_date, end_date)
        if not data:
            return pd.DataFrame()
        
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'vol': item.get('vol'),
                'amount': item.get('amount'),
                'pct_chg': item.get('pct_chg')
            })
        df = pd.DataFrame(df_data) if df_data else pd.DataFrame()
        if not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
        return df
    
    def _get_minute_data(self, ts_code, freq, start_date=None, end_date=None):
        """获取分钟线数据 — ECM缓存优先的cache-on-demand
        
        Args:
            ts_code: 股票代码
            freq: 频率，格式 '5m'/'15m'/'30m'/'60m'
            start_date: 起始日期（未使用，保持接口兼容）
            end_date: 结束日期（未使用，保持接口兼容）
        """
        freq_map = {'1m': '1min', '5m': '5min', '15m': '15min', '30m': '30min', '60m': '60min'}
        ecm_freq = freq_map.get(freq, '5min')
        
        # 第一步：查 ECM 缓存
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            df_cache = ecm.get_cached_minute_kline(ts_code, freq=ecm_freq)
            if df_cache is not None and not df_cache.empty:
                return df_cache
        except Exception:
            pass
        
        # 第二步：从 mootdx 获取数据（P9: 同时通知 daemon 异步补采确保完整性）
        self.request_data('per_stock', ts_code)
        if ecm_freq == '5min':
            df = self._get_mootdx_bars(ts_code, freq=2)
            if not df.empty:
                self._cache_minute_to_ecm(df, ts_code, '5min')
                return df
            # 当 bars(freq=2) 不可用时（非交易时段），用 minutes() 获取1min数据聚合
            try:
                from collections import defaultdict
                today_s = datetime.now().strftime('%Y%m%d')
                df_1min = self._get_mootdx_minutes(ts_code)
                if df_1min is not None and not df_1min.empty:
                    records = df_1min.to_dict('records')
                    # 1min→5min聚合
                    groups = defaultdict(list)
                    for r in records:
                        tt = r.get('trade_time', '')
                        try:
                            ts = tt.split(' ')[1]
                            parts = ts.split(':')
                            slot = (int(parts[0])*60+int(parts[1]))//5
                            key = (tt[:10], slot)
                        except:
                            key = (tt, 0)
                        groups[key].append(r)
                    agg = []
                    for k, bars in sorted(groups.items()):
                        agg.append({
                            'trade_time': bars[0]['trade_time'],
                            'open': float(bars[0]['open']),
                            'high': max(float(b.get('high',0)) for b in bars),
                            'low': min(float(b.get('low',float('inf'))) for b in bars),
                            'close': float(bars[-1]['close']),
                            'amount': sum(float(b.get('amount',0)) for b in bars),
                        })
                    if agg:
                        df_5m = pd.DataFrame(agg)
                        self._cache_minute_to_ecm(df_5m, ts_code, '5min')
                        return df_5m
            except Exception:
                pass
        elif ecm_freq == '1min':
            df = self._get_mootdx_minutes(ts_code)
            if not df.empty:
                self._cache_minute_to_ecm(df, ts_code, '1min')
                return df
        elif ecm_freq in ('15min', '30min', '60min'):
            # 从5min数据聚合为目标频率
            df_5min = None
            try:
                from app.data.enhanced_cache_manager import get_ecm_instance
                ecm = get_ecm_instance()
                df_5min = ecm.get_cached_minute_kline(ts_code, freq='5min')
            except Exception:
                pass
            if df_5min is None or df_5min.empty:
                df_5min = self._get_mootdx_bars(ts_code, freq=2)
            if df_5min is None or df_5min.empty:
                # mootdx bars 断裂，用 minutes + transactions 组合补全天分钟数据
                df_1min = self._get_mootdx_minutes_full(ts_code)
                if df_1min is not None and not df_1min.empty:
                    # 1min → 5min 聚合
                    from collections import defaultdict
                    records = df_1min.to_dict('records')
                    groups = defaultdict(list)
                    for r in records:
                        tt = r.get('trade_time', '')
                        try:
                            ts = tt.split(' ')[1] if ' ' in tt else tt
                            parts = ts.split(':')
                            slot = (int(parts[0]) * 60 + int(parts[1])) // 5
                            key = (tt[:10], slot)
                        except Exception:
                            key = (tt, 0)
                        groups[key].append(r)
                    agg_5min = []
                    for k, bars in sorted(groups.items()):
                        agg_5min.append({
                            'trade_time': bars[0]['trade_time'],
                            'open': float(bars[0]['open']),
                            'high': max(float(b.get('high', 0)) for b in bars),
                            'low': min(float(b.get('low', float('inf'))) for b in bars),
                            'close': float(bars[-1]['close']),
                            'vol': sum(float(b.get('vol', 0)) for b in bars),
                            'amount': 0,
                        })
                    if agg_5min:
                        df_5min = pd.DataFrame(agg_5min)
                        self._cache_minute_to_ecm(df_5min, ts_code, '5min')
            if df_5min is not None and not df_5min.empty:
                # 确保5min缓存已写入
                if df_5min is not None:
                    self._cache_minute_to_ecm(df_5min, ts_code, '5min')
                from app.data.minute_data_manager import MinuteDataManager
                mm = MinuteDataManager()
                records = df_5min.to_dict('records')
                aggregated = mm._resample_minute(records, '5min', ecm_freq)
                if aggregated:
                    df_agg = pd.DataFrame(aggregated)
                    df_agg['ts_code'] = ts_code
                    self._cache_minute_to_ecm(df_agg, ts_code, ecm_freq)
                    return df_agg
        
        # 第三步：Tushare/AKShare 降级移除（292号架构红线8）
        # 数据缺失走 sync_requests 异步补采，不阻塞 API 进程
        # daemon 的 5s 快照聚合会写入分钟数据，下次请求命中缓存
        return pd.DataFrame()
    
    def _cache_minute_to_ecm(self, df, ts_code, freq):
        """将分钟K线写入 ECM minute_kline_cache 持久化"""
        if df.empty:
            return
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            df_copy = df.copy()
            df_copy['ts_code'] = ts_code
            df_copy['freq'] = freq
            # 确保有 trade_time 列供ECM存储
            if 'trade_time' not in df_copy.columns:
                if 'trade_date' in df_copy.columns:
                    df_copy['trade_time'] = df_copy['trade_date'].astype(str)
                else:
                    df_copy['trade_time'] = ''
            # ECM用volume列名
            if 'vol' in df_copy.columns and 'volume' not in df_copy.columns:
                df_copy = df_copy.rename(columns={'vol': 'volume'})
            ecm.cache_minute_kline(df_copy)
        except Exception as e:
            logger.debug("缓存分钟K线失败 (%s/%s): %s", ts_code, freq, e)
    
    def _get_mootdx_minutes(self, ts_code):
        """从 mootdx minutes() 获取当日1分钟数据"""
        try:
            from mootdx.quotes import Quotes
            client = Quotes.factory(market='std')
            symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            today = datetime.now().strftime('%Y%m%d')
            raw = client.minutes(symbol=symbol, date=today)
            if raw is not None and not raw.empty:
                rows = []
                for idx, r in raw.iterrows():
                    hour = 9 + (idx + 30) // 60
                    minute = (idx + 30) % 60
                    trade_time = f"{today[:4]}-{today[4:6]}-{today[6:8]} {hour:02d}:{minute:02d}:00"
                    price = float(r.get('price', 0))
                    if price == 0:
                        continue
                    rows.append({
                        'trade_time': trade_time,
                        'open': price, 'high': price, 'low': price, 'close': price,
                        'vol': int(r.get('vol', 0)),
                    })
                return pd.DataFrame(rows)
        except Exception as e:
            logger.debug("_get_mootdx_minutes(%s) 失败: %s", ts_code, e)
        return pd.DataFrame()
    
    def _get_mootdx_minutes_full(self, ts_code: str, target_date: str = None) -> pd.DataFrame:
        """从 mootdx 获取全天分钟数据（minutes + transactions 合并）

        mootdx minutes() 覆盖 09:30~13:29（240点），
        transactions() 覆盖 11:25~15:29（2000笔逐笔），
        两者合并得到 09:30~15:00 的 1min OHLC bars。

        Returns:
            DataFrame with columns: trade_time, open, high, low, close, vol
        """
        from collections import defaultdict
        from mootdx.quotes import Quotes

        if target_date is None:
            target_date = datetime.now().strftime('%Y%m%d')
        symbol = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        client = Quotes.factory(market='std')

        # 步骤1: 获取 minutes() 数据（09:30~13:29）
        minute_map = {}
        try:
            raw = client.minutes(symbol=symbol, date=target_date)
            if raw is not None and not raw.empty:
                for idx, r in raw.iterrows():
                    hour = 9 + (idx + 30) // 60
                    minute = (idx + 30) % 60
                    key = f"{hour:02d}:{minute:02d}"
                    price = float(r.get('price', 0))
                    if price == 0:
                        continue
                    minute_map[key] = {
                        'open': price, 'high': price, 'low': price, 'close': price,
                        'vol': int(r.get('vol', 0)),
                    }
        except Exception:
            pass

        # 步骤2: 获取 transactions() 逐笔数据（覆盖下午）
        tick_groups = defaultdict(list)
        try:
            raw_t = client.transactions(symbol=symbol, start=0, offset=2000, date=target_date)
            if raw_t is not None and not raw_t.empty:
                for _, r in raw_t.iterrows():
                    t = str(r.get('time', ''))
                    price = float(r.get('price', 0))
                    if price == 0:
                        continue
                    tick_groups[t].append(price)
        except Exception:
            pass

        # 将 transactions tick 聚合为 1min OHLC（跳过 minutes 已覆盖的）
        tm_fmt = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
        for time_key, prices in tick_groups.items():
            if time_key in minute_map:
                continue
            prices_f = [float(p) for p in prices if p]
            if not prices_f:
                continue
            minute_map[time_key] = {
                'open': prices_f[0],
                'high': max(prices_f),
                'low': min(prices_f),
                'close': prices_f[-1],
                'vol': len(prices_f),
            }

        if not minute_map:
            return pd.DataFrame()

        records = []
        for key in sorted(minute_map.keys()):
            r = minute_map[key]
            records.append({
                'trade_time': f"{tm_fmt} {key}:00",
                'open': r['open'], 'high': r['high'],
                'low': r['low'], 'close': r['close'],
                'vol': r['vol'],
            })
        return pd.DataFrame(records)
    
    def _aggregate_daily_to_weekly(self, daily_df):
        """将日线数据聚合为周线数据"""
        if daily_df.empty:
            return pd.DataFrame()
        
        df = daily_df.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        
        # 按周聚合
        weekly = df.resample('W-FRI').agg({
            'ts_code': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'vol': 'sum',
            'amount': 'sum'
        }).dropna()
        
        weekly.reset_index(inplace=True)
        weekly['pct_chg'] = weekly['close'].pct_change() * 100
        return weekly
    
    def _aggregate_daily_to_monthly(self, daily_df):
        """将日线数据聚合为月线数据"""
        if daily_df.empty:
            return pd.DataFrame()
        
        df = daily_df.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        
        # 按月聚合
        monthly = df.resample('M').agg({
            'ts_code': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'vol': 'sum',
            'amount': 'sum'
        }).dropna()
        
        monthly.reset_index(inplace=True)
        monthly['pct_chg'] = monthly['close'].pct_change() * 100
        return monthly
    
    def sync_daily_basic_data(self, ts_code=None, start_date=None, end_date=None, trade_date=None):
        """
        同步每日基础数据（换手率、市盈率、市值等）

        Args:
            ts_code: 股票代码（如果None则获取当日全部）
            start_date: 开始日期
            end_date: 结束日期
            trade_date: 指定交易日（传此参数则获取当日全部股票）

        Returns:
            同步的数据条数
        """
        data = self.tushare.get_daily_basic(ts_code, start_date, end_date, trade_date)

        if not data:
            return 0
        
        # 转换为DataFrame并缓存
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'close': item.get('close'),
                'turnover_rate': item.get('turnover_rate'),
                'turnover_rate_f': item.get('turnover_rate_f'),
                'volume_ratio': item.get('volume_ratio'),
                'pe': item.get('pe'),
                'pe_ttm': item.get('pe_ttm'),
                'pb': item.get('pb'),
                'ps': item.get('ps'),
                'ps_ttm': item.get('ps_ttm'),
                'dv_ratio': item.get('dv_ratio'),
                'dv_ttm': item.get('dv_ttm'),
                'total_share': item.get('total_share'),
                'float_share': item.get('float_share'),
                'free_share': item.get('free_share'),
                'total_mv': item.get('total_mv'),
                'circ_mv': item.get('circ_mv')
            })
        
        if df_data:
            df = pd.DataFrame(df_data)
            self.cache.cache_daily_basic_data(df)
            return len(df)
        
        return 0
    
    def get_cached_daily_basic(self, ts_code, start_date=None, end_date=None):
        """
        从缓存获取每日基础数据
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame
        """
        return self.cache.get_cached_daily_basic(ts_code, start_date, end_date)
    
    def sync_all_daily_basic_data(self, trade_date=None):
        """同步全部股票每日基础数据"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')

        return self.sync_daily_basic_data(trade_date=trade_date)

    def sync_daily_basic_history(self, max_days: int = 120, sleep_sec: float = 0.3) -> int:
        """
        回填 daily_basic_cache 历史数据（方案A：补齐120交易日）

        从 daily_cache 获取最近 max_days 个交易日作为目标日期列表，
        检查 daily_basic_cache 已有哪些日期，对有缺失的日期
        逐日调用 Tushare daily_basic(trade_date=YYYYMMDD) 补全。

        Args:
            max_days: 目标保留的历史交易日数
            sleep_sec: 每两次 API 调用间的间隔（秒），防限流

        Returns:
            补充的总数据条数
        """
        import time

        # 1. 从 daily_cache 获取可用的交易日列表
        target_dates = pd.read_sql("""
            SELECT DISTINCT trade_date FROM daily_cache
            ORDER BY trade_date DESC LIMIT ?
        """, self.cache.conn, params=[max_days])

        if target_dates.empty:
            logger.warning("daily_basic 历史回填: daily_cache 无交易日数据，跳过")
            return 0

        target_dates = target_dates['trade_date'].tolist()
        logger.info(f"daily_basic 历史回填: 目标 {len(target_dates)} 个交易日")

        # 2. 查询 daily_basic_cache 中已有的日期
        existing_dates = set()
        try:
            existing_df = pd.read_sql(
                "SELECT DISTINCT trade_date FROM daily_basic_cache",
                self.cache.conn
            )
            if not existing_df.empty:
                existing_dates = set(existing_df['trade_date'].tolist())
        except Exception:
            pass

        # 3. 计算缺失日期
        missing = [d for d in target_dates if d not in existing_dates]
        missing.sort()  # 从远到近
        logger.info(f"daily_basic 历史回填: 已有 {len(existing_dates)} 天, 需补充 {len(missing)} 天")

        if not missing:
            return 0

        # 4. 逐日调用 Tushare 补全
        total_inserted = 0
        for i, trade_date in enumerate(missing):
            try:
                date_str = trade_date.strftime('%Y%m%d') if hasattr(trade_date, 'strftime') else str(trade_date).replace('-', '')
                data = self.tushare.get_daily_basic(trade_date=date_str)
                if data:
                    df = pd.DataFrame(data)
                    self.cache.cache_daily_basic_data(df)
                    total_inserted += len(df)
                if (i + 1) % 10 == 0:
                    logger.info(f"daily_basic 回填进度: {i+1}/{len(missing)} 天, 已插入 {total_inserted} 条")
                time.sleep(sleep_sec)
            except Exception as e:
                logger.warning(f"daily_basic 回填 {trade_date} 失败: {e}")
                time.sleep(1.0)  # 失败后多等一秒
                continue

        logger.info(f"daily_basic 历史回填完成: 共处理 {len(missing)} 天, 插入 {total_inserted} 条")
        return total_inserted


    def sync_moneyflow_data(self, trade_date=None):
        """同步资金流向数据"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        data = self.tushare.get_moneyflow(trade_date=trade_date)
        if not data:
            return 0
        df_data = []
        for item in data:
            trade_date_str = item.get('trade_date')
            if not trade_date_str:
                continue
            buy_lg = item.get('buy_lg_amount', 0) or 0
            sell_lg = item.get('sell_lg_amount', 0) or 0
            buy_elg = item.get('buy_elg_amount', 0) or 0
            sell_elg = item.get('sell_elg_amount', 0) or 0
            buy_sm = item.get('buy_sm_amount', 0) or 0
            sell_sm = item.get('sell_sm_amount', 0) or 0
            df_data.append({
                'ts_code': item['ts_code'],
                'trade_date': datetime.strptime(trade_date_str, '%Y%m%d').date(),
                'buy_lg_vol': item.get('buy_lg_vol'),
                'buy_lg_amount': buy_lg,
                'sell_lg_vol': item.get('sell_lg_vol'),
                'sell_lg_amount': sell_lg,
                'buy_elg_amount': buy_elg,
                'sell_elg_amount': sell_elg,
                'buy_sm_amount': buy_sm,
                'sell_sm_amount': sell_sm,
                'net_lg_amount': round(float(buy_lg) - float(sell_lg), 2),
                'net_elg_amount': round(float(buy_elg) - float(sell_elg), 2),
                'net_sm_amount': round(float(buy_sm) - float(sell_sm), 2),
            })
        if df_data:
            df = pd.DataFrame(df_data)
            self.cache.cache_moneyflow_data(df)
            return len(df)
        return 0

    def get_cached_moneyflow(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
        """从缓存获取资金流向数据"""
        return self.cache.get_cached_moneyflow(
            ts_code=ts_code, trade_date=trade_date,
            start_date=start_date, end_date=end_date
        )

    def get_cached_stk_holder(self, ts_code):
        """从缓存获取股东户数数据"""
        return self.cache.get_cached_stk_holder(ts_code)

    def get_cached_top10_holders(self, ts_code):
        """从缓存获取前十大股东数据"""
        return self.cache.get_cached_top10_holders(ts_code)

    def get_cached_margin(self, ts_code, start_date=None, end_date=None):
        """从缓存获取融资融券个股数据"""
        return self.cache.get_cached_margin(ts_code, start_date, end_date)

    def get_cached_lhb(self, ts_code, trade_date=None):
        """从缓存获取龙虎榜数据"""
        return self.cache.get_cached_lhb(ts_code, trade_date)

    def get_lhb_detail(self, ts_code: str = None, trade_date: str = None):
        """获取席位级龙虎榜明细

        优先级：
          1. InMemoryStateStore（盘中最新，按 ts_code）
          2. ECM lhb_detail_cache（持久化回退）
        """
        try:
            from app.data.in_memory_store import store as mem_store
            mem_records = mem_store.get_lhb_detail(ts_code)
            if mem_records:
                return pd.DataFrame(mem_records)
        except Exception:
            pass
        return self.cache.get_cached_lhb_detail(ts_code, trade_date)

    def get_cached_fina_indicator(self, ts_code):
        """从缓存获取财务指标"""
        return self.cache.get_cached_fina_indicator(ts_code)

    def get_cached_sentiment_pool(self, trade_date=None):
        """从缓存获取涨跌停情绪池"""
        return self.cache.get_cached_sentiment_pool(trade_date)

    def get_cached_finance_report(self, ts_code):
        """从缓存获取财务排雷报告"""
        return self.cache.get_cached_finance_report(ts_code)

    def get_cached_concept(self, ts_code=None):
        """从缓存获取概念板块数据"""
        return self.cache.get_cached_concept(ts_code)

    def get_cached_income(self, ts_code):
        """从缓存获取利润表"""
        return self.cache.get_cached_income(ts_code)

    def get_cached_balancesheet(self, ts_code):
        """从缓存获取资产负债表"""
        return self.cache.get_cached_balancesheet(ts_code)

    def get_cached_chip_distribution(self, ts_code):
        """从缓存获取筹码分布数据"""
        return self.cache.get_cached_chip_distribution(ts_code)

    # ==========================================
    # 批量数据同步方法（供 scheduler 调用）
    # ==========================================

    def sync_daily_data_range(self, start_date: str, end_date: str = None, mode: str = 'incremental') -> int:
        """同步指定日期范围内所有股票的日线数据

        Args:
            start_date: 起始日期 YYYYMMDD 或 datetime.date
            end_date: 结束日期 YYYYMMDD 或 datetime.date（默认今天）
            mode: 'incremental'（增量）或 'full'（全量强制覆盖）

        Returns:
            同步的记录总数
        """
        from app.models import Stock
        stocks = Stock.query.all()
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        if hasattr(start_date, 'strftime'):
            start_date = start_date.strftime('%Y%m%d')
        if hasattr(end_date, 'strftime'):
            end_date = end_date.strftime('%Y%m%d')

        total = 0
        for stock in stocks:
            cnt = self.sync_daily_data(
                stock.ts_code, use_cache=False,
                start_date=start_date, end_date=end_date
            )
            total += cnt
            if total % 100 == 0:
                logger.info(f"日线同步进度: {total} 条")
        return total

    def sync_index_daily_data(self, trade_date: str = None) -> int:
        """同步指数日线数据到缓存

        Args:
            trade_date: 日期 YYYYMMDD（默认空，表示获取最新）

        Returns:
            缓存的指数记录数
        """
        if not self.tushare or not self.tushare.pro:
            return 0
        total = 0
        index_codes = ['000001.SH', '000300.SH', '399001.SZ', '899050.BJ', '399006.SZ']
        import pandas as pd
        for code in index_codes:
            try:
                raw = self.tushare.get_index_daily(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if not df.empty and 'trade_date' in df.columns:
                        df['trade_date'] = pd.to_datetime(
                            df['trade_date'], format='%Y%m%d'
                        ).dt.date
                    # 过滤仅保留 daily_cache 存在的字段
                    daily_cols = {'ts_code', 'trade_date', 'open', 'high', 'low',
                                  'close', 'vol', 'amount', 'pct_chg'}
                    extra = [c for c in df.columns if c not in daily_cols]
                    if extra:
                        df = df.drop(columns=extra)
                    self.cache.cache_daily_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步指数 {code} 失败: {e}")
        logger.info(f"指数日线缓存同步完成: {total} 条")
        return total

    def sync_adj_factor_data(self, ts_code: str = None, start_date: str = None, end_date: str = None) -> int:
        """同步复权因子数据到缓存

        Args:
            ts_code: 股票代码（None 则同步全部）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            同步的记录数
        """
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        if ts_code:
            raw = self.tushare.get_adj_factor(ts_code, start_date, end_date)
            if raw:
                df = pd.DataFrame(raw)
                # adj_factor 仅含 ts_code/trade_date/adj_factor, 写入独立表
                if not df.empty and 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(
                        df['trade_date'], format='%Y%m%d'
                    ).dt.date
                self.cache.cache_adj_factor_data(df)
                return len(df)
            return 0
        # 同步全部股票
        from app.models import Stock
        stocks = Stock.query.all()
        total = 0
        for stk in stocks:
            raw = self.tushare.get_adj_factor(stk.ts_code, start_date, end_date)
            if raw:
                df = pd.DataFrame(raw)
                if not df.empty and 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(
                        df['trade_date'], format='%Y%m%d'
                    ).dt.date
                self.cache.cache_adj_factor_data(df)
                total += len(df)
        return total

    # ══════════════════════════════════════════════
    # 252号方案：新增批量同步方法
    # ══════════════════════════════════════════════

    def sync_fina_indicator_data(self, ts_code=None) -> int:
        """同步财务指标数据（可指定股票或全市场）"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_fina_indicator(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if not df.empty and 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    if 'ann_date' in df.columns:
                        df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                    self.cache.cache_fina_indicator_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步财务指标 {code} 失败: {e}")
        return total

    def sync_finance_report_data(self, ts_code=None) -> int:
        """273a: 同步扩展财务指标（含 roce/quick_ratio/ocfps，供排雷使用）"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_fina_indicator_extended(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    self.cache.cache_finance_report_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步扩展财务指标 {code} 失败: {e}")
        return total

    def sync_income_data(self, ts_code=None) -> int:
        """同步利润表数据"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_income(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    if 'ann_date' in df.columns:
                        df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                    self.cache.cache_income_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步利润表 {code} 失败: {e}")
        return total

    def sync_balancesheet_data(self, ts_code=None) -> int:
        """同步资产负债表数据"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_balancesheet(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    if 'ann_date' in df.columns:
                        df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                    self.cache.cache_balancesheet_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步资产负债表 {code} 失败: {e}")
        return total

    def sync_cashflow_data(self, ts_code=None) -> int:
        """同步现金流量表数据"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_cashflow(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    if 'ann_date' in df.columns:
                        df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                    self.cache.cache_cashflow_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步现金流量表 {code} 失败: {e}")
        return total

    def sync_forecast_data(self, ts_code=None) -> int:
        """同步业绩预告数据"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_forecast(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    if 'ann_date' in df.columns:
                        df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                    self.cache.cache_forecast_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步业绩预告 {code} 失败: {e}")
        return total

    def sync_margin_data(self, trade_date=None) -> int:
        """同步融资融券个股明细数据（按交易日，全市场一次返回）"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        try:
            data = self.tushare.pro.margin_detail(trade_date=trade_date)
            if data is not None and not data.empty:
                df = data.copy()
                for col in ['name', 'rqchl']:
                    if col in df.columns:
                        df = df.drop(columns=[col])
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                self.cache.cache_margin_data(df)
                return len(df)
        except Exception as e:
            logger.warning(f"同步融资融券失败: {e}")
        return 0

    def sync_stk_limit_data(self, trade_date=None) -> int:
        """同步涨跌停数据（按交易日，全市场一次返回）"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        raw = self.tushare.get_stk_limit(trade_date)
        if raw:
            df = pd.DataFrame(raw)
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            self.cache.cache_stk_limit_data(df)
            return len(df)
        return 0

    def sync_lhb_data(self, trade_date=None) -> int:
        """同步龙虎榜数据（按交易日）"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        raw = self.tushare.get_top_list(trade_date)
        if raw:
            df = pd.DataFrame(raw)
            # 列名映射：Tushare 原始列名 → lhb_cache 表列名
            df = df.rename(columns={
                'pct_change': 'change_pct', 'l_buy': 'buy_amount',
                'l_sell': 'sell_amount', 'net_rate': 'buy_rate',
                'amount_rate': 'sell_rate',
            })
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
            # 只保留 lhb_cache 表有定义的列
            lhb_cols = {'ts_code', 'trade_date', 'name', 'change_pct',
                        'buy_amount', 'sell_amount', 'net_amount',
                        'buy_rate', 'sell_rate'}
            extra = [c for c in df.columns if c not in lhb_cols]
            if extra:
                df = df.drop(columns=extra)
            self.cache.cache_lhb_data(df)
            return len(df)
        return 0

    def sync_lhb_detail_data(self, trade_date=None) -> int:
        """同步龙虎榜席位明细（278号方案：按交易日，Tushare top_inst）

        Returns:
            写入的席位记录数
        """
        if not self.tushare or not self.tushare.pro:
            return 0
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        raw = self.tushare.get_top_inst(trade_date)
        if not raw:
            return 0
        import pandas as pd
        # 映射 Tushare 字段 → lhb_detail_cache 字段
        records = []
        for r in raw:
            ts_code = r.get('ts_code', '')
            if not ts_code:
                continue
            seat_name = r.get('exalter', '')
            if not seat_name:
                continue
            side = r.get('side_label', 'buy')
            records.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'seat_name': seat_name,
                'seat_type': self._classify_seat_name(seat_name),
                'buy_amount': float(r.get('buy', 0)),
                'sell_amount': float(r.get('sell', 0)),
                'net_amount': float(r.get('net_buy', 0) if r.get('net_buy') is not None else (
                    float(r.get('buy', 0)) - float(r.get('sell', 0)))),
                'buy_rank': 0,
                'sell_rank': 0,
                'reason_category': str(r.get('reason', '')),
                'side': side,
                'data_source': 'tushare',
            })
        if records:
            self.cache.cache_lhb_detail_data(records)
        return len(records)

    @staticmethod
    def _classify_seat_name(seat_name: str) -> str:
        """根据席位名称推断类型"""
        seat_lower = seat_name.lower()
        if any(kw in seat_lower for kw in [
            '机构专用', '机构', '基金', '自营', '社保', 'qfii',
            '资产管理', '资管', '保险', '信托', '年金',
        ]):
            return 'institution'
        return 'brokerage'

    def sync_top10_holders_data(self, ts_code=None) -> int:
        """同步前十大股东数据"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_top10_holders(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    if 'ann_date' in df.columns:
                        df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                    self.cache.cache_top10_holders(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步前十大股东 {code} 失败: {e}")
        return total

    def sync_stk_holder_data(self, ts_code=None) -> int:
        """同步股东人数数据"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        stocks = [ts_code] if ts_code else [s.ts_code for s in Stock.query.all()]
        total = 0
        for code in stocks:
            try:
                raw = self.tushare.get_stk_holdernumber(code)
                if raw:
                    df = pd.DataFrame(raw)
                    if 'end_date' in df.columns:
                        df['end_date'] = pd.to_datetime(df['end_date']).dt.date
                    if 'ann_date' in df.columns:
                        df['ann_date'] = pd.to_datetime(df['ann_date']).dt.date
                    self.cache.cache_stk_holder_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步股东人数 {code} 失败: {e}")
        return total

    def sync_concept_data(self) -> int:
        """同步概念分类数据（全量刷新）"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        raw = self.tushare.get_concept()
        if raw:
            df = pd.DataFrame(raw)
            self.cache.cache_concept_data(df)
            return len(df)
        return 0

    def sync_index_member_data(self) -> int:
        """同步指数成分股数据（主要指数）"""
        if not self.tushare or not self.tushare.pro:
            return 0
        import pandas as pd
        index_codes = ['000001.SH', '000300.SH', '000016.SH', '000688.SH',
                       '399001.SZ', '399006.SZ', '399005.SZ']
        total = 0
        for idx_code in index_codes:
            try:
                raw = self.tushare.get_index_member(idx_code)
                if raw:
                    df = pd.DataFrame(raw)
                    self.cache.cache_index_member_data(df)
                    total += len(df)
            except Exception as e:
                logger.warning(f"同步指数成分 {idx_code} 失败: {e}")
        return total

    def sync_financial_all(self) -> int:
        """批量同步全部财务数据"""
        total = 0
        for sync_fn in [self.sync_fina_indicator_data, self.sync_finance_report_data,
                        self.sync_income_data, self.sync_balancesheet_data,
                        self.sync_cashflow_data]:
            try:
                total += sync_fn()
            except Exception as e:
                logger.warning(f"财务数据同步子任务失败: {e}")
        logger.info(f"财务数据批量同步完成: {total} 条")
        return total

    # ══════════════════════════════════════════════

    def get_fina_indicator(self, ts_code, start_date=None, end_date=None):
        """获取财务指标数据（优先读ECM缓存，降级到Tushare）"""
        try:
            df = self.cache.get_cached_fina_indicator(ts_code)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        return self.tushare.get_fina_indicator(ts_code, start_date, end_date)

    def get_income(self, ts_code, start_date=None, end_date=None):
        """获取利润表数据（需5000积分）"""
        return self.tushare.get_income(ts_code, start_date, end_date)

    def get_balancesheet(self, ts_code, start_date=None, end_date=None):
        """获取资产负债表数据（需5000积分）"""
        return self.tushare.get_balancesheet(ts_code, start_date, end_date)

    def get_cashflow(self, ts_code, start_date=None, end_date=None):
        """获取现金流量表数据（需5000积分）"""
        return self.tushare.get_cashflow(ts_code, start_date, end_date)

    def get_top10_holders(self, ts_code, end_date=None):
        """获取前十大股东数据（需5000积分）"""
        return self.tushare.get_top10_holders(ts_code, end_date)

    def get_stk_holdernumber(self, ts_code, start_date=None, end_date=None):
        """获取股东人数数据（需5000积分）"""
        return self.tushare.get_stk_holdernumber(ts_code, start_date, end_date)

    def get_margin(self, ts_code, start_date=None, end_date=None):
        """获取融资融券数据（需5000积分）"""
        return self.tushare.get_margin(ts_code, start_date, end_date)

    def get_forecast(self, ts_code, start_date=None, end_date=None):
        """获取业绩预告数据（需5000积分）"""
        return self.tushare.get_forecast(ts_code, start_date, end_date)

    def get_industry(self, ts_code=None):
        """获取行业分类数据（需5000积分）"""
        return self.tushare.get_industry(ts_code)

    def get_concept(self, ts_code=None):
        """获取概念分类数据（需5000积分）"""
        return self.tushare.get_concept(ts_code)

    def get_index_member(self, index_code):
        """获取指数成分股（需5000积分）"""
        return self.tushare.get_index_member(index_code)

    # ══════════════════════════════════════════════
    # 迭代7：计算层 — 数据源选择 & 预计算数据读取
    # ══════════════════════════════════════════════

    def select_data_source(self, data_type: str = 'indicators') -> str:
        """
        根据当前时间和日终标志位，返回数据源选择：
        - 'eager': 使用预计算结果（日终后）
        - 'lazy': 实时计算 + 缓存
        """
        from datetime import time
        now = datetime.now()
        # 日终判断：当前时间 >= 15:30 表示日终已过
        eod_time = time(15, 30)
        if now.time() >= eod_time and now.weekday() < 5:
            return 'eager'
        return 'lazy'

    def get_cached_indicators(self, ts_code: str, indicators: list = None) -> pd.DataFrame:
        """读取预计算指标（宽表格式，D1: 已移除旧 EAV 降级）"""
        try:
            wide = self.cache.get_indicators_wide(ts_code)
            if wide is not None and not wide.empty:
                return wide
        except Exception:
            pass
        return pd.DataFrame()

    def get_cached_factors(self, ts_code: str, factor_names: list = None) -> pd.DataFrame:
        """读取预计算因子（通过 ECM 统一连接）"""
        if factor_names:
            result = pd.DataFrame()
            for name in factor_names:
                series = self.cache.get_cached_factor(ts_code, name)
                if series is not None:
                    result[name] = series
            return result
        # 未指定因子名时返回所有因子（用于 _compute_factor_signal 批量读取）
        return self.cache.get_cached_factors(ts_code)

    def get_cached_signals(self, ts_code: str, signal_names: list = None) -> pd.DataFrame:
        """读取预计算策略信号"""
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        return ecm.get_strategy_signals(ts_code, signal_names)

    # ── 策略信号详情缓存（287号方案 v2.3） ──

    def cache_signal_detail(self, ts_code: str, result_dict: dict):
        """缓存完整策略信号详情"""
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        ecm.cache_signal_detail(ts_code, result_dict)

    def get_signal_detail(self, ts_code: str, trade_date: str = None) -> dict | None:
        """读取缓存策略信号详情"""
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        return ecm.get_signal_detail(ts_code, trade_date)

    def has_signal_detail(self, ts_code: str, trade_date: str = None) -> bool:
        """检查缓存是否存在"""
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        return ecm.has_signal_detail(ts_code, trade_date)

    # ── 行业指数数据（288号方案 v1.1） ──

    SUB_INDUSTRY_TO_CODE: dict[str, str] = {
        '白酒':'801120.SI','啤酒':'801120.SI','红黄酒':'801120.SI','乳制品':'801120.SI',
        '食品':'801120.SI','软饮料':'801120.SI',
        '半导体':'801080.SI','元器件':'801080.SI','电器仪表':'801080.SI',
        '通信设备':'801080.SI','IT设备':'801080.SI',
        '银行':'801780.SI',
        '证券':'801790.SI','保险':'801790.SI','多元金融':'801790.SI',
        '化学制药':'801150.SI','中成药':'801150.SI','生物制药':'801150.SI',
        '医药商业':'801150.SI','医疗保健':'801150.SI',
        '煤炭开采':'801020.SI','焦炭加工':'801020.SI','石油开采':'801020.SI',
        '石油加工':'801020.SI','石油贸易':'801020.SI',
        '化工原料':'801030.SI','农药化肥':'801030.SI','化纤':'801030.SI',
        '橡胶':'801030.SI','塑料':'801030.SI','染料涂料':'801030.SI','日用化工':'801030.SI',
        '普钢':'801040.SI','特种钢':'801040.SI','钢加工':'801040.SI',
        '铜':'801050.SI','铝':'801050.SI','铅锌':'801050.SI','黄金':'801050.SI',
        '小金属':'801050.SI','矿物制品':'801050.SI',
        '家用电器':'801110.SI',
        '纺织':'801130.SI','服饰':'801130.SI','纺织机械':'801130.SI',
        '造纸':'801140.SI','轻工机械':'801140.SI',
        '水力发电':'801160.SI','火力发电':'801160.SI','新型电力':'801160.SI',
        '供气供热':'801160.SI','水务':'801160.SI','环境保护':'801160.SI',
        '公路':'801170.SI','铁路':'801170.SI','水运':'801170.SI','空运':'801170.SI',
        '机场':'801170.SI','港口':'801170.SI','仓储物流':'801170.SI','公共交通':'801170.SI',
        '全国地产':'801180.SI','区域地产':'801180.SI','房产服务':'801180.SI','园区开发':'801180.SI',
        '百货':'801200.SI','超市连锁':'801200.SI','商贸代理':'801200.SI',
        '其他商业':'801200.SI','批发业':'801200.SI','商品城':'801200.SI','电器连锁':'801200.SI',
        '旅游景点':'801210.SI','旅游服务':'801210.SI','酒店餐饮':'801210.SI','文教休闲':'801210.SI',
        '综合类':'801230.SI',
        '水泥':'801710.SI','玻璃':'801710.SI','陶瓷':'801710.SI','其他建材':'801710.SI',
        '建筑工程':'801720.SI','装修装饰':'801720.SI','建筑':'801720.SI',
        '电气设备':'801730.SI',
        '航空':'801740.SI','船舶':'801740.SI','国防军工':'801740.SI',
        '软件服务':'801750.SI','互联网':'801750.SI','电脑':'801750.SI',
        '出版业':'801760.SI','影视音像':'801760.SI','广告包装':'801760.SI',
        '汽车整车':'801880.SI','汽车配件':'801880.SI','汽车服务':'801880.SI','摩托车':'801880.SI',
        '机床制造':'801890.SI','工程机械':'801890.SI','机械基件':'801890.SI',
        '专用机械':'801890.SI','运输设备':'801890.SI','化工机械':'801890.SI',
        '农业综合':'801010.SI','林业':'801010.SI','渔业':'801010.SI','种植业':'801010.SI',
        '饲料':'801010.SI','农用机械':'801010.SI',
        '电信运营':'801770.SI',
        '路桥':'801170.SI','家居用品':'801140.SI',
    }

    def get_industry_for_stock(self, ts_code: str) -> str | None:
        """获取个股所属行业名"""
        try:
            stk = self.get_stock_info(ts_code)
            if stk:
                return stk.get('industry') or None
            return None
        except Exception:
            return None

    def get_industry_index_data(self, industry_name: str):
        """获取行业指数日线数据"""
        code = self.SUB_INDUSTRY_TO_CODE.get(industry_name)
        if not code:
            return None
        return self.get_cached_daily_data(code)

    def get_all_industry_rankings(self) -> list[dict]:
        """获取所有行业当日涨跌幅排名"""
        rankings = []
        for ind_name, code in self.SUB_INDUSTRY_TO_CODE.items():
            df = self.get_industry_index_data(ind_name)
            if df is not None and not df.empty:
                pct = float(df.iloc[-1].get('pct_chg', 0))
                rankings.append({'name': ind_name, 'code': code, 'pct': pct})
        # 按行业代码去重（只保留每个申万一级行业的最新数据）
        seen = {}
        for r in rankings:
            seen[r['code']] = r  # 后覆盖，保留同一行业的最新子行业结果
        unique = sorted(seen.values(), key=lambda x: x['pct'], reverse=True)
        for i, r in enumerate(unique, 1):
            r['rank'] = i
        return unique

    # ── 机会库网关（Red Line 5 封装，ORM 直读统一收口） ──

    def get_library_ts_codes(self, active_only: bool = True) -> list[str]:
        """获取机会库中股票代码列表"""
        from app.models.opportunity_library import OpportunityLibrary
        query = db.session.query(OpportunityLibrary.ts_code)
        if active_only:
            query = query.filter(OpportunityLibrary.is_active == 1)
        return [r.ts_code for r in query.all()]

    def get_library_entry(self, ts_code: str):
        """获取单只机会库标的"""
        from app.models.opportunity_library import OpportunityLibrary
        return OpportunityLibrary.query.get(ts_code)

    def get_library_active_items(self):
        """获取所有活跃机会库标的（ORM 对象列表）"""
        from app.models.opportunity_library import OpportunityLibrary
        return db.session.query(OpportunityLibrary).filter(
            OpportunityLibrary.is_active == 1,
            OpportunityLibrary.lib_level != 'done',
        ).all()

    # ── sync_requests 队列（调用层→采集层的"数据缺失"信号） ──

    def request_data(self, task_type: str, ts_code: str = None) -> int:
        """数据缺失时写 sync_requests 队列表，通知 daemon 异步补采

        替代旧的 sync_daily_data(use_cache=False) 模式。
        调用层不得直接调数据源，通过此机制通知采集层异步处理。

        Args:
            task_type: 任务类型
                'full_daily': 全市场日线补采
                'full_moneyflow': 全市场资金流向补采
                'full_basic': 全市场基本面补采
                'per_stock': 单只股票补采（ts_code 参数）
                'full_stock_list': 全量股票列表同步
            ts_code: 股票代码（仅 per_stock 需要）

        Returns:
            request_id（可用于 poll_data_ready 轮询）
        """
        return self.cache.request_data(task_type, ts_code)

    def poll_data_ready(self, request_id: int) -> str:
        """轮询 sync_requests 任务状态"""
        return self.cache.poll_data_ready(request_id)
