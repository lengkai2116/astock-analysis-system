"""
技术指标计算引擎 - 优化版（向量化计算）
支持：MA、MACD、RSI、KDJ、BOLL、VOL指标
优化说明：避免多次DataFrame拷贝，统一向量化计算
"""
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


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
        if len(result) >= 30:
            result['ma30'] = result['close'].rolling(window=30).mean()
        if len(result) >= 60:
            result['ma60'] = result['close'].rolling(window=60).mean()
        # 414号P1.2: 补充MA120/MA250预计算
        if len(result) >= 120:
            result['ma120'] = result['close'].rolling(window=120).mean()
        if len(result) >= 250:
            result['ma250'] = result['close'].rolling(window=250).mean()

        # 2. 计算MACD
        if len(result) >= 26:
            # 501 #R46：删死赋值 `close = result['close'].values`（下方用 result['close'].ewm）

            # 直接用Series的ewm，避免额外拷贝
            ema12 = result['close'].ewm(span=12, adjust=False).mean()
            ema26 = result['close'].ewm(span=26, adjust=False).mean()
            dif = ema12 - ema26
            dea = dif.ewm(span=9, adjust=False).mean()
            macd_hist = 2 * (dif - dea)

            result['macd_dif'] = dif
            result['macd_dea'] = dea
            result['macd_hist'] = macd_hist

        # 3. 计算RSI（414号P1.1: Wilder's EMA, alpha=1/period）
        if len(result) >= 15:
            close = result['close']
            delta = close.diff()
            # 501 #R49：首元素 NaN 置 0 用 fillna——原 `delta.iloc[0] = 0` 是链式赋值
            # （对 .diff() 返回的新 Series 操作，可能 SettingWithCopyWarning/no-op），
            # 与 calculate_rsi 的 np.diff+insert 平滑锚点保持一致
            delta = delta.fillna(0)

            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)

            # Wilder's RSI: ewm(alpha=1/14, adjust=False) 替代 rolling(14).mean()
            avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

            # 502批次4 #R10：RSI 零除数统一（每日 RAW-1）——100*gain/(gain+loss)，全平盘→50 中性
            denom = avg_gain + avg_loss
            rsi14 = 100 * avg_gain / denom
            result['rsi14'] = rsi14.mask(denom == 0, 50.0)

        # 4. 计算KDJ
        if len(result) >= 9:
            low_min = result['low'].rolling(window=9).min()
            high_max = result['high'].rolling(window=9).max()

            # 502批次5 #R13：KDJ 平盘统一（每日 RAW-1）——平盘窗口（high==low）RSV=50 中性
            denom = high_max - low_min
            rsv = (result['close'] - low_min) * 100 / denom
            rsv = rsv.mask(denom == 0, 50.0)
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

        # 7. 计算BBI (Bull and Bear Index) = (MA3 + MA6 + MA12 + MA24) / 4
        if len(result) >= 24:
            ma3 = result['close'].rolling(window=3).mean()
            ma6 = result['close'].rolling(window=6).mean()
            ma12 = result['close'].rolling(window=12).mean()
            ma24 = result['close'].rolling(window=24).mean()
            result['bbi'] = (ma3 + ma6 + ma12 + ma24) / 4

        # 8. 计算ENE (Envelope) = MA25 * (1 ± M/100), M=6
        if len(result) >= 25:
            ma25 = result['close'].rolling(window=25).mean()
            ene_m = 6.0
            result['ene_upper'] = ma25 * (1 + ene_m / 100)
            result['ene_lower'] = ma25 * (1 - ene_m / 100)

        # 9. 计算九转序列 (Nine Turner) —— 501 #R48：向量化替代逐行 .iloc 循环
        # 语义等价：close[i] < close[i-4] 记买入计数（连续段 1..9 截断），反向记卖出；
        # 原实现用有状态 cnt_buy/cnt_sell，现用 shift(4) 比较 + 段内 cumcount 等价实现
        if len(result) >= 8:
            close = result['close']
            lower4 = close < close.shift(4)      # 买入触发
            higher4 = close > close.shift(4)     # 卖出触发
            # 买卖互斥：买入段（lower4 True 且非 higher4）与卖出段（higher4 True 且非 lower4）
            buy_seg = lower4 & ~higher4
            sell_seg = higher4 & ~lower4
            # 段编号：触发状态翻转处开始新段（含首行 NaN→非 NaN 的边界）
            buy_grp = (buy_seg != buy_seg.shift()).cumsum()
            sell_grp = (sell_seg != sell_seg.shift()).cumsum()
            nine_buy = buy_seg.groupby(buy_grp).cumcount() + 1
            nine_sell = sell_seg.groupby(sell_grp).cumcount() + 1
            # 截断 9
            nine_buy = nine_buy.where(nine_buy <= 9, 9)
            nine_sell = nine_sell.where(nine_sell <= 9, 9)
            # 非触发日置 0
            nine_buy = nine_buy.where(buy_seg, 0)
            nine_sell = nine_sell.where(sell_seg, 0)
            result['nine_buy'] = nine_buy.fillna(0).astype(int)
            result['nine_sell'] = nine_sell.fillna(0).astype(int)

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
        414号P1.1: Wilder's EMA, alpha=1/period
        """
        result = df.copy()

        if len(result) < period + 1:
            return result

        close = result['close'].values

        delta = np.diff(close)
        delta = np.insert(delta, 0, 0)

        gain = np.maximum(delta, 0)
        loss = -np.minimum(delta, 0)

        # Wilder's RSI: ewm(alpha=1/period, adjust=False)
        avg_gain = pd.Series(gain).ewm(alpha=1/period, adjust=False).mean().values
        avg_loss = pd.Series(loss).ewm(alpha=1/period, adjust=False).mean().values

        # 502批次4 #R10：RSI 零除数统一（每日 RAW-1）——100*gain/(gain+loss)，全平盘→50 中性
        denom = avg_gain + avg_loss
        with np.errstate(divide='ignore', invalid='ignore'):
            rsi = 100 * avg_gain / denom
        rsi = np.where(denom == 0, 50.0, rsi)

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

        # 502批次5 #R13：KDJ 平盘统一（每日 RAW-1）——平盘窗口（high==low）RSV=50 中性
        # （原 .replace(0,1e-10) 平盘给 0；与因子库 a_stock/momentum KDJ 统一）
        denom = high_max - low_min
        rsv = (result['close'] - low_min) * 100 / denom
        rsv = rsv.mask(denom == 0, 50.0)
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
            'ma30': float(latest['ma30']) if pd.notna(latest.get('ma30')) else None,
            'ma60': float(latest['ma60']) if pd.notna(latest.get('ma60')) else None,
            'ma120': float(latest['ma120']) if pd.notna(latest.get('ma120')) else None,
            'ma250': float(latest['ma250']) if pd.notna(latest.get('ma250')) else None,
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
            'bbi': float(latest['bbi']) if pd.notna(latest.get('bbi')) else None,
            'ene_upper': float(latest['ene_upper']) if pd.notna(latest.get('ene_upper')) else None,
            'ene_lower': float(latest['ene_lower']) if pd.notna(latest.get('ene_lower')) else None,
            'vol_ma5': float(latest['vol_ma5']) if pd.notna(latest.get('vol_ma5')) else None,
            'vol_ma10': float(latest['vol_ma10']) if pd.notna(latest.get('vol_ma10')) else None
        }
