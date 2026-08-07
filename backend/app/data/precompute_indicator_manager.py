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
            
            # 写入宽表格式（替代旧 EAV 格式，93% 行数压缩）
            if 'ts_code' not in result.columns:
                result['ts_code'] = ts_code
            self.cache_manager.cache_indicators_wide(ts_code, result)
            
            return True
        except Exception as e:
            logger.warning(f"预计算指标失败 [{ts_code}]: {e}")
            return False
    
    def compute_win_rates(self, lookahead: int = 5) -> pd.DataFrame:
        """
        计算策略信号的胜率（基于历史信号后的 N 日价格涨跌）

        对 strategy_signals 表中每个信号，检查 signal_date 之后 lookahead 个交易日的
        价格变化，若方向与信号一致则记为 win。

        320号 F2：数据新鲜度守卫——strategy_signals 旧表已停更（P2 迁移至
        strategy_signal_detail），基于过期数据计算胜率会误导。旧表超过 STALE_DAYS
        未更新时跳过计算并告警，避免产出过期统计。

        Returns:
            pd.DataFrame: [{signal_type, total_count, win_count, win_rate, ...}]
        """
        # ── 320号 F2：数据新鲜度守卫（旧表停更保护） ──
        try:
            _row = self.cache_manager.conn.execute(
                "SELECT MAX(trade_date) FROM strategy_signals").fetchone()
            _max = _row[0] if _row else None
            if _max:
                try:
                    _d = pd.Timestamp(str(_max))
                except Exception:
                    _d = None
                if _d is not None and (pd.Timestamp.now() - _d).days > 3:
                    logger.warning(
                        f"胜率计算跳过: strategy_signals 旧表已停更 {_max} "
                        f"(P2 已迁移至 strategy_signal_detail，待迁移胜率计算)")
                    return pd.DataFrame()
        except Exception:
            pass
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
