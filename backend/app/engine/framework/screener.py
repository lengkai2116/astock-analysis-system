"""
多层股票筛选系统
参考 LEAN 的三层筛选架构
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import numpy as np

from . import UniverseSelectionModel, Algorithm
from .chip_strategy import ChipUniverseSelectionModel, ChipScorer


class DarwinRiskFilter:
    """
    达尔文风险过滤 - 第一层筛选
    负责剔除高风险股票
    """
    
    def __init__(self):
        self.filter_rules = [
            self._filter_st,
            self._filter_continuous_loss,
            self._filter_low_liquidity,
            self._filter_high_valuation
        ]
    
    def filter(self, stock_list: List[str], stock_data: Dict[str, pd.DataFrame]) -> List[str]:
        """
        应用风险过滤
        
        Args:
            stock_list: 股票代码列表
            stock_data: 股票数据 {symbol: DataFrame}
        
        Returns:
            通过过滤的股票列表
        """
        passed = []
        
        for symbol in stock_list:
            data = stock_data.get(symbol, pd.DataFrame())
            
            if self._apply_filters(symbol, data):
                passed.append(symbol)
        
        return passed
    
    def _apply_filters(self, symbol: str, data: pd.DataFrame) -> bool:
        """应用所有过滤规则"""
        for rule in self.filter_rules:
            if not rule(symbol, data):
                return False
        return True
    
    def _filter_st(self, symbol: str, data: pd.DataFrame) -> bool:
        """过滤ST股票"""
        # 这里简化处理，实际应该检查股票名称
        return 'ST' not in symbol and '*ST' not in symbol
    
    def _filter_continuous_loss(self, symbol: str, data: pd.DataFrame) -> bool:
        """过滤连续亏损股票"""
        # 简化实现，实际需要财务数据
        return True
    
    def _filter_low_liquidity(self, symbol: str, data: pd.DataFrame) -> bool:
        """过滤低流动性股票"""
        if data.empty or len(data) < 20:
            return False
        
        avg_vol = data['vol'].tail(20).mean()
        # 日均成交量需要大于5000万（简化）
        return avg_vol > 1000000
    
    def _filter_high_valuation(self, symbol: str, data: pd.DataFrame) -> bool:
        """过滤高估值股票"""
        # 简化实现
        return True


class MultiLayerStockScreener:
    """
    多层股票筛选器
    整合三层筛选架构
    """
    
    def __init__(self):
        self.layer1 = DarwinRiskFilter()
        self.layer2_scorer = ChipScorer()
    
    def screen(self, all_stocks: List[str], stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        执行多层筛选
        
        Args:
            all_stocks: 全市场股票列表
            stock_data: 股票数据 {symbol: DataFrame}
        
        Returns:
            筛选结果列表，按评分排序
        """
        print("开始第一层筛选: 风险过滤...")
        layer1_results = self.layer1.filter(all_stocks, stock_data)
        print(f"第一层通过: {len(layer1_results)} 只股票")
        
        print("开始第二层筛选: 主力资金识别...")
        layer2_results = []
        for symbol in layer1_results:
            try:
                data = stock_data.get(symbol, pd.DataFrame())
                if data.empty:
                    continue
                
                score = self.layer2_scorer.score(data)
                if score > 0:
                    layer2_results.append({
                        'symbol': symbol,
                        'score': score
                    })
            
            except Exception as e:
                print(f"处理股票 {symbol} 时出错: {e}")
        
        # 按评分排序
        layer2_results.sort(key=lambda x: x['score'], reverse=True)
        layer2_results = layer2_results[:100]  # 取前100只
        print(f"第二层通过: {len(layer2_results)} 只股票")
        
        print("开始第三层筛选: 多策略验证...")
        layer3_results = self._apply_strategy_validation(layer2_results, stock_data)
        print(f"第三层通过: {len(layer3_results)} 只股票")
        
        return layer3_results
    
    def _apply_strategy_validation(self, candidates: List[Dict], stock_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        第三层: 策略验证（简化实现）
        实际可以添加更多策略验证
        """
        validated = []
        
        for candidate in candidates:
            symbol = candidate['symbol']
            data = stock_data.get(symbol, pd.DataFrame())
            
            if data.empty:
                continue
            
            # 简单的验证逻辑
            if len(data) >= 60:
                candidate['validated'] = True
                candidate['data_points'] = len(data)
                validated.append(candidate)
        
        return validated


class SignalFusion:
    """
    多策略信号融合器
    """
    
    def __init__(self, strategy_weights: Optional[Dict[str, float]] = None):
        """
        Args:
            strategy_weights: 策略权重配置
        """
        self.weights = strategy_weights or {
            'chip': 0.4,
            'chanlun': 0.3,
            'factor': 0.3
        }
    
    def fuse(self, signals_dict: Dict[str, float]) -> Dict:
        """
        融合多策略信号
        
        Args:
            signals_dict: 各策略信号 {strategy_name: signal_value}
                         signal_value: -1=卖, 0=观望, 1=买
        
        Returns:
            融合后的信号结果
        """
        # 归一化权重
        total_weight = sum(w for s, w in self.weights.items() if s in signals_dict)
        
        if total_weight <= 0:
            return {
                'action': 'HOLD',
                'confidence': 0.0,
                'details': signals_dict
            }
        
        # 加权求和
        fused_score = 0.0
        for strategy, weight in self.weights.items():
            if strategy in signals_dict:
                normalized_weight = weight / total_weight
                fused_score += signals_dict[strategy] * normalized_weight
        
        # 确定最终操作
        if fused_score > 0.3:
            action = 'BUY'
        elif fused_score < -0.3:
            action = 'SELL'
        else:
            action = 'HOLD'
        
        # 计算置信度
        confidence = min(0.9, abs(fused_score) * 0.5 + 0.1)
        
        return {
            'action': action,
            'score': fused_score,
            'confidence': confidence,
            'details': signals_dict
        }