"""
预计算指标管理器
借鉴Vibe-Trading和Qlib的预计算策略
功能说明：
1. 批量预计算所有指标并缓存
2. 从缓存快速获取指标数据
3. 支持预计算触发
"""
import pandas as pd
from datetime import datetime
from typing import Optional
from app.indicators import TechnicalIndicatorEngine



import logging
logger = logging.getLogger(__name__)
class PrecomputeIndicatorManager:
    """
    预计算指标管理器核心类
    """
    
    def __init__(self, cache_manager):
        """
        初始化预计算管理器
        
        Args:
            cache_manager: EnhancedCacheManager实例
        """
        self.cache_manager = cache_manager
        self.engine = TechnicalIndicatorEngine()
    
    def precompute_all_indicators(self, ts_code: str, df: pd.DataFrame, force: bool = False) -> bool:
        """
        预计算所有指标并批量缓存
        
        Args:
            ts_code: 股票代码
            df: 日线数据DataFrame
            force: 是否强制重新计算（忽略已有缓存）
            
        Returns:
            bool: 是否成功完成预计算
        """
        if len(df) < 30:
            return False
        
        try:
            # 计算所有指标
            result = self.engine.calculate_all_indicators(df)
            
            # 批量缓存指标（旧 EAV 格式，兼容现有消费者）
            self._batch_cache_indicators(result, ts_code)
            
            # 写入宽表格式（新，93% 行数压缩）
            if 'ts_code' not in result.columns:
                result['ts_code'] = ts_code
            self.cache_manager.cache_indicators_wide(ts_code, result)
            
            return True
        except Exception as e:
            logger.warning(f"预计算指标失败 [{ts_code}]: {e}")
            return False
    
    def _batch_cache_indicators(self, df: pd.DataFrame, ts_code: str):
        """
        批量缓存计算好的指标
        
        Args:
            df: 包含指标的DataFrame
            ts_code: 股票代码
        """
        indicator_cols = [
            'ma5', 'ma10', 'ma20',
            'macd_dif', 'macd_dea', 'macd_hist',
            'rsi14',
            'kdj_k', 'kdj_d', 'kdj_j',
            'boll_upper', 'boll_mid', 'boll_lower',
            'vol_ma5', 'vol_ma10'
        ]
        
        records = []
        now = datetime.now().isoformat()
        
        for _, row in df.iterrows():
            for col in indicator_cols:
                val = row.get(col)
                if pd.notna(val):
                    records.append({
                        'ts_code': ts_code,
                        'trade_date': row['trade_date'],
                        'indicator_name': col,
                        'value': float(val),
                        'cached_at': now
                    })
        
        if records:
            self.cache_manager.batch_cache_indicators(records)
    
    def get_precomputed_indicators(self, ts_code: str, indicators: Optional[list] = None) -> pd.DataFrame:
        """
        获取预计算好的指标（优先从缓存）
        
        Args:
            ts_code: 股票代码
            indicators: 需要的指标列表，None表示所有常用指标
            
        Returns:
            pd.DataFrame: 包含指标的DataFrame
        """
        if indicators is None:
            indicators = ['ma5', 'ma10', 'ma20', 'macd_dif', 'rsi14']
        
        result = pd.DataFrame()
        
        for indicator in indicators:
            df = self.cache_manager.get_indicator_data(ts_code, indicator)
            if not df.empty:
                if result.empty:
                    result = df[['trade_date', 'value']].rename(columns={'value': indicator})
                else:
                    # 按trade_date合并
                    temp = df[['trade_date', 'value']].rename(columns={'value': indicator})
                    result = result.merge(temp, on='trade_date', how='outer')
        
        # 按日期排序
        if not result.empty:
            result = result.sort_values('trade_date').reset_index(drop=True)
        
        return result
    
    def get_single_indicator(self, ts_code: str, indicator_name: str) -> pd.DataFrame:
        """
        获取单个预计算指标
        
        Args:
            ts_code: 股票代码
            indicator_name: 指标名称
            
        Returns:
            pd.DataFrame: 指标数据
        """
        return self.cache_manager.get_indicator_data(ts_code, indicator_name)

    def compute_win_rates(self, lookahead: int = 5) -> pd.DataFrame:
        """
        计算策略信号的胜率（基于历史信号后的 N 日价格涨跌）

        对 strategy_signals 表中每个信号，检查 signal_date 之后 lookahead 个交易日的
        价格变化，若方向与信号一致则记为 win。

        Returns:
            pd.DataFrame: [{signal_type, total_count, win_count, win_rate, ...}]
        """
        try:
            # 获取所有历史信号
            sql = """SELECT s.ts_code,
                            SUBSTR(s.trade_date, 1, 4) || '-' || SUBSTR(s.trade_date, 5, 2) || '-' || SUBSTR(s.trade_date, 7, 2) as trade_date_fmt,
                            s.signal_name, s.signal_value, s.signal_level,
                            d.close as entry_close
                     FROM strategy_signals s
                     JOIN daily_cache d ON s.ts_code = d.ts_code
                         AND SUBSTR(s.trade_date, 1, 4) || '-' || SUBSTR(s.trade_date, 5, 2) || '-' || SUBSTR(s.trade_date, 7, 2) = d.trade_date
                     ORDER BY s.ts_code, s.signal_name, s.trade_date"""
            signals_df = self.cache_manager._query_df(sql)

            if signals_df is None or signals_df.empty:
                logger.info("胜率计算: strategy_signals 表无数据，跳过")
                return pd.DataFrame()

            results = []
            for (ts_code, signal_name), grp in signals_df.groupby(['ts_code', 'signal_name']):
                wins = 0
                total = 0
                for _, row in grp.iterrows():
                    trade_date_fmt = row['trade_date_fmt']
                    entry_price = row['entry_close']
                    if pd.isna(entry_price) or entry_price <= 0:
                        continue
                    # 查 lookahead 日后价格（如无数据，说明信号时间太新，跳过）
                    exit_price = self.cache_manager._query_df(
                        """SELECT close FROM daily_cache
                           WHERE ts_code=? AND trade_date>?
                           ORDER BY trade_date LIMIT 1 OFFSET ?""",
                        [ts_code, trade_date_fmt, lookahead - 1]
                    )
                    if exit_price is None or exit_price.empty:
                        continue
                    exit_close = float(exit_price['close'].iloc[-1])
                    ret = (exit_close - entry_price) / entry_price
                    signal_level = str(row.get('signal_level', '')).upper()
                    # 定义"赢": BUY/BULLISH → 涨幅>0, SELL/BEARISH → 跌幅>0, 其余中性不算
                    is_win = False
                    if signal_level in ('BUY', 'BULLISH', 'STRONG_BUY'):
                        is_win = ret > 0.02  # 涨幅 > 2%
                    elif signal_level in ('SELL', 'BEARISH', 'STRONG_SELL'):
                        is_win = ret < -0.02
                    else:
                        # WATCH/NEUTRAL → 小幅波动都算 win（保守防守）
                        is_win = abs(ret) < 0.03
                    total += 1
                    if is_win:
                        wins += 1

                if total > 0:
                    results.append({
                        'signal_type': signal_name,
                        'total_count': total,
                        'win_count': wins,
                        'win_rate': round(wins / total, 4),
                        'lookahead_days': lookahead,
                        'computed_at': datetime.now().isoformat(),
                    })

            result_df = pd.DataFrame(results) if results else pd.DataFrame()
            logger.info(f"胜率计算完成: {len(results)} 个信号类型")
            return result_df
        except Exception as e:
            logger.warning(f"胜率计算失败: {e}")
            return pd.DataFrame()

    def get_win_rates(self) -> pd.DataFrame:
        """获取最近计算的胜率数据（从 win_rate_cache 读取，若无则实时计算）"""
        try:
            cached = self.cache_manager._query_df("SELECT * FROM win_rate_cache")
            if cached is not None and not cached.empty:
                return cached
        except Exception:
            pass
        # 无缓存 → 实时计算
        return self.compute_win_rates()
