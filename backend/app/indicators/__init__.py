"""
技术指标计算引擎 - 优化版（向量化计算）
支持：MA、MACD、RSI、KDJ、BOLL、VOL指标
优化说明：避免多次DataFrame拷贝，统一向量化计算
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, List


class TechnicalIndicatorEngine:
    def __init__(self):
        pass
    
    def calculate_all_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算所有技术指标（优化版：避免多次DataFrame拷贝）
        df 需要包含：ts_code, trade_date, open, high, low, close, vol
        """
        if len(df) < 20:
            return df.copy()
        
        # 只拷贝一次DataFrame
        result = df.copy()
        
        # 直接在result上计算所有指标，避免中间拷贝
        
        # 1. 计算MA
        if len(result) >= 5:
            result['ma5'] = result['close'].rolling(window=5).mean()
        if len(result) >= 10:
            result['ma10'] = result['close'].rolling(window=10).mean()
        if len(result) >= 20:
            result['ma20'] = result['close'].rolling(window=20).mean()
        
        # 2. 计算MACD
        if len(result) >= 26:
            close = result['close'].values
            
            # 直接用Series的ewm，避免额外拷贝
            ema12 = result['close'].ewm(span=12, adjust=False).mean()
            ema26 = result['close'].ewm(span=26, adjust=False).mean()
            dif = ema12 - ema26
            dea = dif.ewm(span=9, adjust=False).mean()
            macd_hist = 2 * (dif - dea)
            
            result['macd_dif'] = dif
            result['macd_dea'] = dea
            result['macd_hist'] = macd_hist
        
        # 3. 计算RSI
        if len(result) >= 15:
            close = result['close']
            delta = close.diff()
            # 更安全的方式处理第一个元素
            if len(delta) > 0 and pd.isna(delta.iloc[0]):
                delta.iloc[0] = 0
            
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            
            # 避免除零
            avg_loss_safe = avg_loss.where(avg_loss != 0, 1e-10)
            
            rs = avg_gain / avg_loss_safe
            result['rsi14'] = 100 - (100 / (1 + rs))
        
        # 4. 计算KDJ
        if len(result) >= 9:
            low_min = result['low'].rolling(window=9).min()
            high_max = result['high'].rolling(window=9).max()
            
            rsv = (result['close'] - low_min) / (high_max - low_min) * 100
            k = rsv.ewm(com=2, adjust=False).mean()
            d = k.ewm(com=2, adjust=False).mean()
            j = 3 * k - 2 * d
            
            result['kdj_k'] = k
            result['kdj_d'] = d
            result['kdj_j'] = j
        
        # 5. 计算BOLL
        if len(result) >= 20:
            mid = result['close'].rolling(window=20).mean()
            std = result['close'].rolling(window=20).std()
            upper = mid + (std * 2)
            lower = mid - (std * 2)
            
            result['boll_upper'] = upper
            result['boll_middle'] = mid
            result['boll_mid'] = mid
            result['boll_lower'] = lower
        
        # 6. 计算成交量指标
        if len(result) >= 5:
            result['vol_ma5'] = result['vol'].rolling(window=5).mean()
        if len(result) >= 10:
            result['vol_ma10'] = result['vol'].rolling(window=10).mean()
        
        return result
    
    # 保留单个方法以保持向后兼容
    def calculate_ma(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算移动平均线：MA5, MA10, MA20（向后兼容）
        """
        result = df.copy()
        
        if len(result) >= 5:
            result['ma5'] = result['close'].rolling(window=5).mean()
        if len(result) >= 10:
            result['ma10'] = result['close'].rolling(window=10).mean()
        if len(result) >= 20:
            result['ma20'] = result['close'].rolling(window=20).mean()
            
        return result
    
    def calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算MACD指标：DIF, DEA, HIST（向后兼容）
        """
        result = df.copy()
        
        if len(result) < 26:
            return result
            
        close = result['close'].values
        
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
        macd_hist = 2 * (dif - dea)
        
        result['macd_dif'] = dif
        result['macd_dea'] = dea
        result['macd_hist'] = macd_hist
        
        return result
    
    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        计算RSI相对强弱指标（向后兼容）
        """
        result = df.copy()
        
        if len(result) < period + 1:
            return result
            
        close = result['close'].values
        
        delta = np.diff(close)
        delta = np.insert(delta, 0, 0)
        
        gain = np.maximum(delta, 0)
        loss = -np.minimum(delta, 0)
        
        avg_gain = pd.Series(gain).rolling(window=period).mean().values
        avg_loss = pd.Series(loss).rolling(window=period).mean().values
        
        avg_loss = np.where(avg_loss == 0, 1e-10, avg_loss)
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        result['rsi14'] = rsi
        
        return result
    
    def calculate_kdj(self, df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
        """
        计算KDJ随机指标（向后兼容）
        """
        result = df.copy()
        
        if len(result) < n:
            return result
            
        low_min = result['low'].rolling(window=n).min()
        high_max = result['high'].rolling(window=n).max()
        
        rsv = (result['close'] - low_min) / (high_max - low_min) * 100
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        j = 3 * k - 2 * d
        
        result['kdj_k'] = k
        result['kdj_d'] = d
        result['kdj_j'] = j
        
        return result
    
    def calculate_boll(self, df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> pd.DataFrame:
        """
        计算BOLL布林带指标（向后兼容）
        """
        result = df.copy()
        
        if len(result) < period:
            return result
            
        mid = result['close'].rolling(window=period).mean()
        std = result['close'].rolling(window=period).std()
        upper = mid + (std * std_dev)
        lower = mid - (std * std_dev)
        
        result['boll_upper'] = upper
        result['boll_middle'] = mid
        result['boll_mid'] = mid
        result['boll_lower'] = lower
        
        return result
    
    def calculate_vol_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算成交量指标：VOL_MA5, VOL_MA10（向后兼容）
        """
        result = df.copy()
        
        if len(result) >= 5:
            result['vol_ma5'] = result['vol'].rolling(window=5).mean()
        if len(result) >= 10:
            result['vol_ma10'] = result['vol'].rolling(window=10).mean()
            
        return result
    
    def get_latest_indicators(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        获取最新日期的指标数据
        """
        if len(df) == 0:
            return None
            
        result = self.calculate_all_indicators(df)
        latest = result.iloc[-1]
        
        return {
            'ts_code': latest.get('ts_code'),
            'trade_date': latest.get('trade_date'),
            'ma5': float(latest['ma5']) if pd.notna(latest.get('ma5')) else None,
            'ma10': float(latest['ma10']) if pd.notna(latest.get('ma10')) else None,
            'ma20': float(latest['ma20']) if pd.notna(latest.get('ma20')) else None,
            'macd_dif': float(latest['macd_dif']) if pd.notna(latest.get('macd_dif')) else None,
            'macd_dea': float(latest['macd_dea']) if pd.notna(latest.get('macd_dea')) else None,
            'macd_hist': float(latest['macd_hist']) if pd.notna(latest.get('macd_hist')) else None,
            'rsi14': float(latest['rsi14']) if pd.notna(latest.get('rsi14')) else None,
            'kdj_k': float(latest['kdj_k']) if pd.notna(latest.get('kdj_k')) else None,
            'kdj_d': float(latest['kdj_d']) if pd.notna(latest.get('kdj_d')) else None,
            'kdj_j': float(latest['kdj_j']) if pd.notna(latest.get('kdj_j')) else None,
            'boll_upper': float(latest['boll_upper']) if pd.notna(latest.get('boll_upper')) else None,
            'boll_mid': float(latest['boll_mid']) if pd.notna(latest.get('boll_mid')) else None,
            'boll_lower': float(latest['boll_lower']) if pd.notna(latest.get('boll_lower')) else None,
            'vol_ma5': float(latest['vol_ma5']) if pd.notna(latest.get('vol_ma5')) else None,
            'vol_ma10': float(latest['vol_ma10']) if pd.notna(latest.get('vol_ma10')) else None
        }