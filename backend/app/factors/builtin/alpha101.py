"""
Alpha101因子 - Kakushadze的101个公式因子
文件路径：backend/app/factors/builtin/alpha101.py
参考：https://arxiv.org/abs/1901.08916
"""
import pandas as pd
import numpy as np
from ..base import BaseFactor, FactorParam


class Alpha001(BaseFactor):
    """Alpha1: (-1"""
    name = "Alpha001"
    name_cn = "Alpha1"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha1因子"
    formula = "(rank(ts_argmax(signedpower(returns, 2), 5) - 0.5) * -1"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        returns = data['close'].pct_change()
        
        def find_max_day(series):
            if len(series) < 2:
                return np.nan
            return series.argmax()
        
        max_pos = returns.rolling(window=5).apply(find_max_day, raw=True)
        ranks = max_pos.rank(pct=True)
        
        return (ranks - 0.5) * -1


class Alpha002(BaseFactor):
    """Alpha2: (-1 * delta(close, 1)"""
    name = "Alpha002"
    name_cn = "Alpha2"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha2因子"
    formula = "-1 * delta(close, 1)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -1 * data['close'].diff(1)


class Alpha003(BaseFactor):
    """Alpha3: (-1 * delta(close, 1))"""
    name = "Alpha003"
    name_cn = "Alpha3"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha3因子"
    formula = "ts_rank(close, 10)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=10).rank(pct=True)


class Alpha004(BaseFactor):
    """Alpha4: ts_rank(delta(close, 1), 10)"""
    name = "Alpha004"
    name_cn = "Alpha4"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha4因子"
    formula = "ts_rank(delta(close, 1), 10)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        delta_close = data['close'].diff(1)
        return delta_close.rolling(window=10).rank(pct=True)


class Alpha005(BaseFactor):
    """Alpha5: ts_rank(close, 20)"""
    name = "Alpha005"
    name_cn = "Alpha5"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha5因子"
    formula = "ts_rank(close, 20)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=20).rank(pct=True)


class Alpha006(BaseFactor):
    """Alpha6: (-1 * corr(high, volume, 5))"""
    name = "Alpha006"
    name_cn = "Alpha6"
    category = "alpha101"
    subcategory = "correlation"
    description = "经典Alpha6因子"
    formula = "-1 * correlation(high, volume, 5)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -1 * data['high'].rolling(window=5).corr(data['vol'])


class Alpha007(BaseFactor):
    """Alpha7: (-1 * correlation(open, volume, 10))"""
    name = "Alpha007"
    name_cn = "Alpha7"
    category = "alpha101"
    subcategory = "correlation"
    description = "经典Alpha7因子"
    formula = "-1 * correlation(open, volume, 10)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -1 * data['open'].rolling(window=10).corr(data['vol'])


class Alpha008(BaseFactor):
    """Alpha8: (-1 * correlation(high, volume, 10))"""
    name = "Alpha008"
    name_cn = "Alpha8"
    category = "alpha101"
    subcategory = "correlation"
    description = "经典Alpha8因子"
    formula = "-1 * correlation(high, volume, 10)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -1 * data['high'].rolling(window=10).corr(data['vol'])


class Alpha009(BaseFactor):
    """Alpha9: ts_min(close, 5)"""
    name = "Alpha009"
    name_cn = "Alpha9"
    category = "alpha101"
    subcategory = "technical"
    description = "经典Alpha9因子"
    formula = "ts_min(close, 5)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=5).min()


class Alpha010(BaseFactor):
    """Alpha10: ts_max(close, 5)"""
    name = "Alpha010"
    name_cn = "Alpha10"
    category = "alpha101"
    subcategory = "technical"
    description = "经典Alpha10因子"
    formula = "ts_max(close, 5)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].rolling(window=5).max()


class Alpha011(BaseFactor):
    """Alpha11: (delta(close, 5) / delay(close, 5))"""
    name = "Alpha011"
    name_cn = "Alpha11"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha11因子"
    formula = "delta(close, 5) / delay(close, 5)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return data['close'].diff(5) / data['close'].shift(5).replace(0, np.nan)


class Alpha012(BaseFactor):
    """Alpha12: (close - low) / (high - low + 0.001)"""
    name = "Alpha012"
    name_cn = "Alpha12"
    category = "alpha101"
    subcategory = "position"
    description = "经典Alpha12因子"
    formula = "(close - low) / (high - low + 0.001)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return (data['close'] - data['low']) / (data['high'] - data['low'] + 0.001)


class Alpha013(BaseFactor):
    """Alpha13: (-1 * (close - open))"""
    name = "Alpha013"
    name_cn = "Alpha13"
    category = "alpha101"
    subcategory = "technical"
    description = "经典Alpha13因子"
    formula = "-1 * (close - open)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -1 * (data['close'] - data['open'])


class Alpha014(BaseFactor):
    """Alpha14: (-1 * (close - open))"""
    name = "Alpha014"
    name_cn = "Alpha14"
    category = "alpha101"
    subcategory = "technical"
    description = "经典Alpha14因子"
    formula = "-1 * (close - open)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        return -1 * (data['close'] - data['open'])


class Alpha015(BaseFactor):
    """Alpha15: (rank(delta(close, 1), 10)"""
    name = "Alpha015"
    name_cn = "Alpha15"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha15因子"
    formula = "rank(delta(close, 1), 10)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        delta_close = data['close'].diff(1)
        return delta_close.rolling(window=10).rank(pct=True)


class Alpha016(BaseFactor):
    """Alpha16: (-1 * (close - ts_min(low, 5))"""
    name = "Alpha016"
    name_cn = "Alpha16"
    category = "alpha101"
    subcategory = "technical"
    description = "经典Alpha16因子"
    formula = "-1 * (close - ts_min(low, 5))"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        min_low = data['low'].rolling(window=5).min()
        return -1 * (data['close'] - min_low)


class Alpha017(BaseFactor):
    """Alpha17: (-1 * (close - ts_max(high, 5))"""
    name = "Alpha017"
    name_cn = "Alpha17"
    category = "alpha101"
    subcategory = "technical"
    description = "经典Alpha17因子"
    formula = "-1 * (close - ts_max(high, 5))"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        max_high = data['high'].rolling(window=5).max()
        return -1 * (data['close'] - max_high)


class Alpha018(BaseFactor):
    """Alpha18: (rank(ts_rank(close, 10), 10)"""
    name = "Alpha018"
    name_cn = "Alpha18"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha18因子"
    formula = "rank(ts_rank(close, 10), 10)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        rank1 = data['close'].rolling(window=10).rank(pct=True)
        rank2 = rank1.rolling(window=10).rank(pct=True)
        return rank2


class Alpha019(BaseFactor):
    """Alpha19: (rank(close - open) > rank(high - close))"""
    name = "Alpha019"
    name_cn = "Alpha19"
    category = "alpha101"
    subcategory = "technical"
    description = "经典Alpha19因子"
    formula = "rank(close - open) > rank(high - close)"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        close_open = data['close'] - data['open']
        high_close = data['high'] - data['close']
        
        rank_co = close_open.rolling(window=20).rank(pct=True)
        rank_hc = high_close.rolling(window=20).rank(pct=True)
        
        return (rank_co > rank_hc).astype(float)


class Alpha020(BaseFactor):
    """Alpha20: rank((close - close.shift())"""
    name = "Alpha020"
    name_cn = "Alpha20"
    category = "alpha101"
    subcategory = "momentum"
    description = "经典Alpha20因子"
    formula = "rank(delta(close, 1))"
    source = "Alpha101"
    source_detail = "Alpha101"
    
    params = []
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        delta_close = data['close'].diff(1)
        return delta_close.rolling(window=20).rank(pct=True)
