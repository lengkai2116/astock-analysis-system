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

        363号F57-1修复：旧表strategy_signals已删除，胜率计算待迁移到strategy_signal_detail。

        Returns:
            pd.DataFrame: [{signal_type, total_count, win_count, win_rate, ...}]
        """
        # ── 363号F57-1修复：旧表strategy_signals已删除，胜率计算待迁移到新表 ──
        logger.info("胜率计算: 旧表strategy_signals已删除（363号F57-1），胜率计算待迁移到strategy_signal_detail")
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
