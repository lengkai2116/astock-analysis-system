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
        计算策略信号的胜率（基于 strategy_signal_detail + daily_cache）

        363号F57-1修复后迁移：从 strategy_signal_detail 读取信号，
        关联 daily_cache 计算 N 日前瞻收益率，按信号类型聚合胜率。

        Args:
            lookahead: 前瞻交易日数（默认5日）

        Returns:
            pd.DataFrame: [{signal_type, total_count, win_count, win_rate, avg_return}]
        """
        try:
            # 从 strategy_signal_detail 读取信号
            signal_df = self.cache_manager._query_df(
                "SELECT ts_code, trade_date, opportunity_state, consensus_rate "
                "FROM strategy_signal_detail WHERE trade_date IS NOT NULL"
            )
            if signal_df is None or signal_df.empty:
                logger.info("胜率计算: strategy_signal_detail 无数据")
                return pd.DataFrame()

            # 获取所有交易日（用于计算 N 日后收益）
            dates_df = self.cache_manager._query_df(
                "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date"
            )
            if dates_df is None or dates_df.empty:
                return pd.DataFrame()
            all_dates = sorted(dates_df['trade_date'].tolist())
            date_to_idx = {d: i for i, d in enumerate(all_dates)}

            # 按信号类型聚合
            results = []
            for sig_type in signal_df['opportunity_state'].dropna().unique():
                subset = signal_df[signal_df['opportunity_state'] == sig_type]
                win_count = 0
                total_count = 0
                returns = []
                for _, row in subset.iterrows():
                    ts_code = row['ts_code']
                    trade_date = row['trade_date']
                    if trade_date not in date_to_idx:
                        continue
                    idx = date_to_idx[trade_date]
                    target_idx = idx + lookahead
                    if target_idx >= len(all_dates):
                        continue
                    target_date = all_dates[target_idx]
                    # 获取入场价和出场价
                    entry_df = self.cache_manager._query_df(
                        "SELECT close FROM daily_cache WHERE ts_code=? AND trade_date=?",
                        [ts_code, trade_date])
                    exit_df = self.cache_manager._query_df(
                        "SELECT close FROM daily_cache WHERE ts_code=? AND trade_date=?",
                        [ts_code, target_date])
                    if (entry_df is not None and not entry_df.empty and
                        exit_df is not None and not exit_df.empty):
                        entry_price = entry_df.iloc[0]['close']
                        exit_price = exit_df.iloc[0]['close']
                        if entry_price and entry_price > 0:
                            ret = (exit_price - entry_price) / entry_price
                            returns.append(ret)
                            total_count += 1
                            if ret > 0:
                                win_count += 1
                if total_count >= 5:  # 最少5个样本
                    results.append({
                        'signal_type': sig_type,
                        'total_count': total_count,
                        'win_count': win_count,
                        'win_rate': round(win_count / total_count * 100, 1),
                        'avg_return': round(sum(returns) / len(returns) * 100, 2) if returns else 0,
                    })
            if results:
                logger.info(f"胜率计算完成: {len(results)} 种信号类型")
            return pd.DataFrame(results) if results else pd.DataFrame()
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
