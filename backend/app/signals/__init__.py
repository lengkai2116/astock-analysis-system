"""
信号生成系统
基于技术指标生成买入/卖出信号
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from app.indicators import TechnicalIndicatorEngine


class SignalGenerator:
    def __init__(self):
        self.indicator_engine = TechnicalIndicatorEngine()
    
    def generate_all_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        生成所有类型的信号
        """
        signals = []
        
        if len(df) < 30:
            return signals
            
        # 计算指标
        df_with_indicators = self.indicator_engine.calculate_all_indicators(df)
        
        # MA信号
        ma_signals = self.generate_ma_signals(df_with_indicators)
        signals.extend(ma_signals)
        
        # MACD信号
        macd_signals = self.generate_macd_signals(df_with_indicators)
        signals.extend(macd_signals)
        
        # RSI信号
        rsi_signals = self.generate_rsi_signals(df_with_indicators)
        signals.extend(rsi_signals)
        
        # KDJ信号
        kdj_signals = self.generate_kdj_signals(df_with_indicators)
        signals.extend(kdj_signals)
        
        # BOLL信号
        boll_signals = self.generate_boll_signals(df_with_indicators)
        signals.extend(boll_signals)
        
        # 多指标共振信号
        resonance_signals = self.generate_resonance_signals(df_with_indicators)
        signals.extend(resonance_signals)
        
        return signals
    
    def generate_ma_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        基于MA均线生成信号
        - 金叉：MA5上穿MA10或MA20 -> 买入
        - 死叉：MA5下穿MA10或MA20 -> 卖出
        """
        signals = []
        
        if len(df) < 21:
            return signals
            
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            
            if pd.isna(prev['ma5']) or pd.isna(curr['ma5']):
                continue
                
            if pd.notna(prev['ma10']) and pd.notna(curr['ma10']):
                # MA5金叉MA10
                if prev['ma5'] <= prev['ma10'] and curr['ma5'] > curr['ma10']:
                    signals.append({
                        'ts_code': curr['ts_code'],
                        'signal_type': 'buy',
                        'signal_date': curr['trade_date'],
                        'entry_price': float(curr['close']),
                        'confidence': 0.6,
                        'reason': 'MA5上穿MA10金叉',
                        'indicators': {'type': 'ma_cross', 'fast': 5, 'slow': 10}
                    })
                
                # MA5死叉MA10
                elif prev['ma5'] >= prev['ma10'] and curr['ma5'] < curr['ma10']:
                    signals.append({
                        'ts_code': curr['ts_code'],
                        'signal_type': 'sell',
                        'signal_date': curr['trade_date'],
                        'entry_price': float(curr['close']),
                        'confidence': 0.6,
                        'reason': 'MA5下穿MA10死叉',
                        'indicators': {'type': 'ma_cross', 'fast': 5, 'slow': 10}
                    })
            
            if pd.notna(prev['ma20']) and pd.notna(curr['ma20']):
                # MA5金叉MA20
                if prev['ma5'] <= prev['ma20'] and curr['ma5'] > curr['ma20']:
                    signals.append({
                        'ts_code': curr['ts_code'],
                        'signal_type': 'buy',
                        'signal_date': curr['trade_date'],
                        'entry_price': float(curr['close']),
                        'confidence': 0.7,
                        'reason': 'MA5上穿MA20金叉',
                        'indicators': {'type': 'ma_cross', 'fast': 5, 'slow': 20}
                    })
                
                # MA5死叉MA20
                elif prev['ma5'] >= prev['ma20'] and curr['ma5'] < curr['ma20']:
                    signals.append({
                        'ts_code': curr['ts_code'],
                        'signal_type': 'sell',
                        'signal_date': curr['trade_date'],
                        'entry_price': float(curr['close']),
                        'confidence': 0.7,
                        'reason': 'MA5下穿MA20死叉',
                        'indicators': {'type': 'ma_cross', 'fast': 5, 'slow': 20}
                    })
        
        return signals
    
    def generate_macd_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        基于MACD生成信号
        - DIF上穿DEA（金叉） -> 买入
        - DIF下穿DEA（死叉） -> 卖出
        - MACD柱由负转正 -> 买入
        - MACD柱由正转负 -> 卖出
        """
        signals = []
        
        if len(df) < 30:
            return signals
            
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            
            if pd.isna(prev['macd_dif']) or pd.isna(curr['macd_dif']):
                continue
                
            # DIF上穿DEA金叉
            if prev['macd_dif'] <= prev['macd_dea'] and curr['macd_dif'] > curr['macd_dea']:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'buy',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.75,
                    'reason': 'MACD金叉',
                    'indicators': {'type': 'macd_cross', 'direction': 'up'}
                })
            
            # DIF下穿DEA死叉
            elif prev['macd_dif'] >= prev['macd_dea'] and curr['macd_dif'] < curr['macd_dea']:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'sell',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.75,
                    'reason': 'MACD死叉',
                    'indicators': {'type': 'macd_cross', 'direction': 'down'}
                })
            
            if pd.notna(prev['macd_hist']) and pd.notna(curr['macd_hist']):
                # MACD柱由负转正
                if prev['macd_hist'] <= 0 and curr['macd_hist'] > 0:
                    signals.append({
                        'ts_code': curr['ts_code'],
                        'signal_type': 'buy',
                        'signal_date': curr['trade_date'],
                        'entry_price': float(curr['close']),
                        'confidence': 0.65,
                        'reason': 'MACD柱由负转正',
                        'indicators': {'type': 'macd_hist', 'direction': 'up'}
                    })
                
                # MACD柱由正转负
                elif prev['macd_hist'] >= 0 and curr['macd_hist'] < 0:
                    signals.append({
                        'ts_code': curr['ts_code'],
                        'signal_type': 'sell',
                        'signal_date': curr['trade_date'],
                        'entry_price': float(curr['close']),
                        'confidence': 0.65,
                        'reason': 'MACD柱由正转负',
                        'indicators': {'type': 'macd_hist', 'direction': 'down'}
                    })
        
        return signals
    
    def generate_rsi_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        基于RSI生成信号
        - RSI上穿30（超卖反弹）-> 买入
        - RSI下穿70（超买回调）-> 卖出
        """
        signals = []
        
        if len(df) < 20:
            return signals
            
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            
            if pd.isna(prev['rsi14']) or pd.isna(curr['rsi14']):
                continue
                
            # RSI上穿30
            if prev['rsi14'] <= 30 and curr['rsi14'] > 30:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'buy',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.7,
                    'reason': 'RSI上穿30，超卖反弹',
                    'indicators': {'type': 'rsi', 'level': 30, 'direction': 'up'}
                })
            
            # RSI下穿70
            elif prev['rsi14'] >= 70 and curr['rsi14'] < 70:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'sell',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.7,
                    'reason': 'RSI下穿70，超买回调',
                    'indicators': {'type': 'rsi', 'level': 70, 'direction': 'down'}
                })
        
        return signals
    
    def generate_kdj_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        基于KDJ生成信号
        - K上穿D（金叉） -> 买入
        - K下穿D（死叉） -> 卖出
        """
        signals = []
        
        if len(df) < 20:
            return signals
            
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            
            if pd.isna(prev['kdj_k']) or pd.isna(curr['kdj_k']) or pd.isna(prev['kdj_d']) or pd.isna(curr['kdj_d']):
                continue
                
            # K上穿D
            if prev['kdj_k'] <= prev['kdj_d'] and curr['kdj_k'] > curr['kdj_d']:
                confidence = 0.65
                if curr['kdj_k'] < 30:
                    confidence = 0.8
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'buy',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': confidence,
                    'reason': 'KDJ金叉',
                    'indicators': {'type': 'kdj_cross', 'direction': 'up', 'k_value': float(curr['kdj_k'])}
                })
            
            # K下穿D
            elif prev['kdj_k'] >= prev['kdj_d'] and curr['kdj_k'] < curr['kdj_d']:
                confidence = 0.65
                if curr['kdj_k'] > 70:
                    confidence = 0.8
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'sell',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': confidence,
                    'reason': 'KDJ死叉',
                    'indicators': {'type': 'kdj_cross', 'direction': 'down', 'k_value': float(curr['kdj_k'])}
                })
        
        return signals
    
    def generate_boll_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        基于BOLL布林带生成信号
        - 价格跌破下轨 -> 超卖买入
        - 价格突破上轨 -> 超买卖出
        """
        signals = []
        
        if len(df) < 25:
            return signals
            
        for i in range(1, len(df)):
            curr = df.iloc[i]
            
            if pd.isna(curr['boll_lower']) or pd.isna(curr['boll_upper']):
                continue
                
            # 价格跌破下轨
            if curr['close'] < curr['boll_lower']:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'buy',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.7,
                    'reason': '价格跌破布林带下轨',
                    'indicators': {'type': 'boll', 'band': 'lower', 'price': float(curr['close'])}
                })
            
            # 价格突破上轨
            elif curr['close'] > curr['boll_upper']:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'sell',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.7,
                    'reason': '价格突破布林带上轨',
                    'indicators': {'type': 'boll', 'band': 'upper', 'price': float(curr['close'])}
                })
        
        return signals
    
    def generate_resonance_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        生成多指标共振信号
        多个指标同时发出同方向信号时，触发高置信度信号
        """
        signals = []
        
        if len(df) < 30:
            return signals
            
        for i in range(5, len(df)):
            curr = df.iloc[i]
            
            buy_count = 0
            sell_count = 0
            buy_reasons = []
            sell_reasons = []
            
            if pd.notna(curr.get('ma5')) and pd.notna(curr.get('ma10')):
                if curr['ma5'] > curr['ma10']:
                    buy_count += 1
                    buy_reasons.append('MA5>MA10')
                elif curr['ma5'] < curr['ma10']:
                    sell_count += 1
                    sell_reasons.append('MA5<MA10')
            
            if pd.notna(curr.get('macd_dif')) and pd.notna(curr.get('macd_dea')):
                if curr['macd_dif'] > curr['macd_dea']:
                    buy_count += 1
                    buy_reasons.append('DIF>DEA')
                elif curr['macd_dif'] < curr['macd_dea']:
                    sell_count += 1
                    sell_reasons.append('DIF<DEA')
            
            if pd.notna(curr.get('kdj_k')) and pd.notna(curr.get('kdj_d')):
                if curr['kdj_k'] > curr['kdj_d']:
                    buy_count += 1
                    buy_reasons.append('K>D')
                elif curr['kdj_k'] < curr['kdj_d']:
                    sell_count += 1
                    sell_reasons.append('K<D')
            
            if pd.notna(curr.get('rsi14')):
                if 30 < curr['rsi14'] < 50:
                    buy_count += 0.5
                    buy_reasons.append('RSI低位')
                elif 50 < curr['rsi14'] < 70:
                    sell_count += 0.5
                    sell_reasons.append('RSI高位')
            
            if buy_count >= 2.5:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'buy',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.9,
                    'reason': f'多指标共振：{", ".join(buy_reasons)}',
                    'indicators': {'type': 'resonance', 'indicators': buy_reasons}
                })
            
            if sell_count >= 2.5:
                signals.append({
                    'ts_code': curr['ts_code'],
                    'signal_type': 'sell',
                    'signal_date': curr['trade_date'],
                    'entry_price': float(curr['close']),
                    'confidence': 0.9,
                    'reason': f'多指标共振：{", ".join(sell_reasons)}',
                    'indicators': {'type': 'resonance', 'indicators': sell_reasons}
                })
        
        return signals