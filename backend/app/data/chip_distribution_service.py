"""
筹码分布服务 - 基于OHLCV估算筹码分布
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from .enhanced_cache_manager import EnhancedCacheManager



import logging
logger = logging.getLogger(__name__)
class ChipDistributionEstimator:
    """
    基于OHLCV的筹码估算器
    
    算法说明：
    1. 价格网格：将历史价格区间切分为N个price_bin
    2. 成交分配：当日成交量按OHLC区间分布到各价格区间
    3. 衰减模型：固定衰减率模拟旧筹码替换
    4. 筹码峰检测：局部最大值检测
    """
    
    def __init__(self, num_bins=150, decay_rate=0.005):
        """
        初始化筹码估算器
        
        Args:
            num_bins: 价格网格数量（默认150）
            decay_rate: 每日旧筹码衰减率（默认0.5%）
        """
        self.num_bins = num_bins
        self.decay_rate = decay_rate
    
    def estimate(self, df_ohlcv: pd.DataFrame) -> Tuple[np.ndarray, float, float, float]:
        """
        估算筹码分布
        
        Args:
            df_ohlcv: 包含ts_code, trade_date, open, high, low, close, vol, amount的DataFrame
            
        Returns:
            (chip_dist, min_price, max_price, price_step)
        """
        if df_ohlcv.empty:
            return np.zeros(self.num_bins), 0, 0, 0
        
        # 确保数据按日期排序
        df_sorted = df_ohlcv.sort_values('trade_date').reset_index(drop=True)
        
        # 1. 确定价格区间
        min_price = df_sorted['low'].min()
        max_price = df_sorted['high'].max()
        
        # 处理价格区间相同的情况
        if max_price <= min_price:
            max_price = min_price * 1.1
            min_price = min_price * 0.9
        
        price_step = (max_price - min_price) / self.num_bins
        
        # 2. 初始化筹码分布
        chip_dist = np.zeros(self.num_bins)
        
        # 3. 逐天估算
        for _, row in df_sorted.iterrows():
            vol = row.get('vol', 0)
            if vol <= 0:
                continue
            
            # 旧筹码衰减
            chip_dist *= (1 - self.decay_rate)
            
            # 分配当日成交量到价格区间
            price_high = row['high']
            price_low = row['low']
            
            if np.isnan(price_high) or np.isnan(price_low) or price_high <= price_low:
                continue
            
            # 计算当前价格区间的有效范围
            start_bin = max(0, int((price_low - min_price) / price_step))
            end_bin = min(self.num_bins - 1, int((price_high - min_price) / price_step))
            
            if start_bin > end_bin:
                continue
            
            # 简单线性分配（均匀分布）
            num_bins_occupied = end_bin - start_bin + 1
            if num_bins_occupied > 0:
                vol_per_bin = vol / num_bins_occupied
                for bin_idx in range(start_bin, end_bin + 1):
                    chip_dist[bin_idx] += vol_per_bin
        
        # 4. 归一化
        total = chip_dist.sum()
        if total > 0:
            chip_dist = chip_dist / total
        
        return chip_dist, min_price, max_price, price_step


class ChipDistributionService:
    """
    筹码分布服务
    """
    
    def __init__(self, cache_manager: EnhancedCacheManager = None):
        self.cache_manager = cache_manager or EnhancedCacheManager()
        self.estimator = ChipDistributionEstimator()
    
    def calculate_chip_distribution(self, 
                                     ts_code: str,
                                     df_ohlcv: pd.DataFrame = None,
                                     lookback_days: int = 120,
                                     data_manager = None) -> Dict:
        """
        计算单只股票的筹码分布
        
        Args:
            ts_code: 股票代码
            df_ohlcv: OHLCV数据（如果None，则从缓存获取）
            lookback_days: 回顾天数（默认120天）
            data_manager: DataManager实例（用于获取数据）
            
        Returns:
            筹码分布数据字典
        """
        # 1. 获取数据
        if df_ohlcv is None and data_manager:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - pd.Timedelta(days=lookback_days)).strftime('%Y-%m-%d')
            df_ohlcv = data_manager.get_cached_daily_data(ts_code, start_date, end_date)
        
        if df_ohlcv is None or df_ohlcv.empty:
            return {
                'ts_code': ts_code,
                'trade_date': None,
                'chip_bins': [],
                'indicators': {}
            }
        
        # 2. 估算筹码分布
        chip_dist, min_price, max_price, price_step = self.estimator.estimate(df_ohlcv)
        
        # 3. 处理结果
        result = self._format_chip_result(ts_code, df_ohlcv, chip_dist, min_price, max_price, price_step)
        
        return result
    
    def _format_chip_result(self, ts_code: str, df_ohlcv: pd.DataFrame, 
                           chip_dist: np.ndarray, min_price: float, 
                           max_price: float, price_step: float) -> Dict:
        """
        格式化筹码分布结果
        """
        latest_date = df_ohlcv['trade_date'].max()
        latest_close = df_ohlcv[df_ohlcv['trade_date'] == latest_date]['close'].iloc[0]
        
        # 构建价格区间数据
        chip_bins = []
        accumulated_ratio = 0
        
        for bin_idx in range(self.estimator.num_bins):
            bin_price = min_price + bin_idx * price_step + price_step / 2
            ratio = float(chip_dist[bin_idx])
            accumulated_ratio += ratio
            
            # 检测筹码峰（局部最大值）
            peak_flag = self._is_peak(chip_dist, bin_idx)
            
            chip_bins.append({
                'price_bin': round(bin_price, 2),
                'chip_ratio': round(ratio, 4),
                'accumulated_ratio': round(accumulated_ratio, 4),
                'peak_flag': peak_flag
            })
        
        # 计算基础指标
        indicators = self._calculate_basic_indicators(chip_bins, latest_close)
        
        return {
            'ts_code': ts_code,
            'trade_date': latest_date.strftime('%Y-%m-%d') if hasattr(latest_date, 'strftime') else str(latest_date),
            'chip_bins': chip_bins,
            'indicators': indicators,
            'price_range': {
                'min': round(min_price, 2),
                'max': round(max_price, 2),
                'step': round(price_step, 2)
            }
        }
    
    def _is_peak(self, chip_dist: np.ndarray, bin_idx: int) -> bool:
        """
        检测局部最大值（筹码峰）
        """
        if bin_idx <= 1 or bin_idx >= len(chip_dist) - 2:
            return False
        
        # 简单的局部最大值检测：比左右两边都大
        left_2 = chip_dist[bin_idx - 2]
        left_1 = chip_dist[bin_idx - 1]
        current = chip_dist[bin_idx]
        right_1 = chip_dist[bin_idx + 1]
        right_2 = chip_dist[bin_idx + 2]
        
        return (current > left_1 and current > right_1 and 
                current > left_2 * 1.1 and current > right_2 * 1.1)
    
    def _calculate_basic_indicators(self, chip_bins: List[Dict], current_price: float) -> Dict:
        """
        计算基础筹码指标
        """
        # SSRP - 市场平均成本
        ssrp = self._calculate_ssrp(chip_bins)
        
        # 筹码集中度 - 前20%价格区间筹码占比
        concentration = self._calculate_concentration(chip_bins, top_pct=0.2)
        
        # 筹码获利率
        profit_ratio = self._calculate_profit_ratio(chip_bins, current_price)
        
        return {
            'ssrp': round(ssrp, 2),
            'concentration': round(concentration, 4),
            'profit_ratio': round(profit_ratio, 4)
        }
    
    def _calculate_ssrp(self, chip_bins: List[Dict]) -> float:
        """
        计算SSRP - 市场平均成本
        """
        total_chips = sum(bin_data['chip_ratio'] for bin_data in chip_bins)
        if total_chips <= 0:
            return 0
        
        weighted_price = sum(bin_data['price_bin'] * bin_data['chip_ratio'] for bin_data in chip_bins)
        return weighted_price / total_chips
    
    def _calculate_concentration(self, chip_bins: List[Dict], top_pct: float = 0.2) -> float:
        """
        计算筹码集中度 - 前N%价格区间筹码占比
        """
        # 找到最大ratio的top_pct个价格区间
        sorted_bins = sorted(chip_bins, key=lambda x: x['chip_ratio'], reverse=True)
        top_count = max(1, int(len(sorted_bins) * top_pct))
        
        return sum(bin_data['chip_ratio'] for bin_data in sorted_bins[:top_count])
    
    def _calculate_profit_ratio(self, chip_bins: List[Dict], current_price: float) -> float:
        """
        计算筹码获利率 - 当前价格以下筹码比例
        """
        return sum(bin_data['chip_ratio'] for bin_data in chip_bins if bin_data['price_bin'] <= current_price)
    
    def cache_chip_distribution(self, ts_code: str, chip_result: Dict) -> bool:
        """
        缓存筹码分布
        """
        try:
            trade_date = chip_result.get('trade_date')
            chip_bins = chip_result.get('chip_bins', [])
            
            if not trade_date or not chip_bins:
                return False
            
            # 格式化日期
            if isinstance(trade_date, str):
                trade_date = pd.to_datetime(trade_date).date()
            
            self.cache_manager.cache_chip_distribution(ts_code, trade_date, chip_bins)
            return True
        except Exception as e:
            logger.warning(r"缓存筹码分布失败: {e}")
            return False
    
    def get_cached_chip_distribution(self, ts_code: str, trade_date: Optional[str] = None) -> pd.DataFrame:
        """
        获取缓存的筹码分布
        """
        if trade_date:
            return self.cache_manager.get_chip_distribution(ts_code, trade_date, trade_date)
        else:
            return self.cache_manager.get_latest_chip_distribution(ts_code)
