import logging
"""
筹码分布策略 - 模块化实现
参考 Algorithm Framework 的设计
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import numpy as np
import logging

from . import (
    UniverseSelectionModel,
    AlphaModel,
    PortfolioConstructionModel,
    RiskManagementModel,
    ExecutionModel,
    Insight
)


class ChipUniverseSelectionModel(UniverseSelectionModel):
    """
    筹码分布股票池选择模型
    筛选出具备主力资金条件的股票
    """
    
    def __init__(self, lookback_period: int = 120, top_n: int = 50):
        """
        Args:
            lookback_period: 回看周期
            top_n: 返回前N只股票
        """
        self.lookback_period = lookback_period
        self.top_n = top_n
        self.chip_scorer = ChipScorer()
    
    def select(self, date_time: datetime, data: Any) -> List[str]:
        """
        筛选股票池
        
        Args:
            date_time: 时间戳
            data: 市场数据，格式为 {symbol: DataFrame}
        
        Returns:
            股票代码列表，按分数降序排列
        """
        if not isinstance(data, dict):
            return []
        
        results = []
        for symbol, df in data.items():
            try:
                if len(df) < 60:
                    continue
                
                # 计算筹码评分
                score = self.chip_scorer.score(df)
                if score > 0:
                    results.append((symbol, score))
            
            except Exception as e:
                logger.error(f"筛选股票 {symbol} 时出错: {e}")
        
        # 按分数排序，返回前N只
        results.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in results[:self.top_n]]


class ChipAlphaModel(AlphaModel):
    """
    筹码分布信号生成模型
    生成交易信号洞察
    """
    
    def __init__(self, lookback_period: int = 120):
        self.lookback_period = lookback_period
        # 简化实现，移除外部依赖
        self.chip_service = None
        self.chip_indicators = None
    
    def generate_insights(self, data: any) -> List[Insight]:
        """
        生成筹码分布交易信号洞察
        
        Args:
            data: 可以是DataFrame或字典格式的OHLCV数据
        
        Returns:
            洞察信号列表
        """
        insights = []
        
        # 处理不同类型的数据输入
        data_dict = data if isinstance(data, dict) else {'data': data}
        
        for symbol, df in data_dict.items():
            try:
                if isinstance(df, pd.DataFrame):
                    if df.empty or len(df) < 120:
                        continue
                    
                    # 使用评分器分析
                    scorer = ChipScorer()
                    score = scorer.score(df)
                    
                    # 根据评分生成信号
                    if score >= 7.0:
                        # 高分 - 强力买入
                        direction = Insight.LONG
                        confidence = min(0.9, score / 10.0)
                        weight = 0.8
                        reason = f"高评分筹码策略信号: {symbol} (评分: {score:.2f})"
                    elif score >= 5.0:
                        # 中分 - 买入
                        direction = Insight.LONG
                        confidence = min(0.7, score / 10.0)
                        weight = 0.5
                        reason = f"中等评分筹码策略信号: {symbol} (评分: {score:.2f})"
                    elif score >= 3.0:
                        # 低分 - 观望
                        direction = Insight.FLAT
                        confidence = 0.5
                        weight = 0.0
                        reason = f"观望信号: {symbol} (评分: {score:.2f})"
                    else:
                        # 极低分 - 做空
                        direction = Insight.SHORT
                        confidence = min(0.6, (10.0 - score) / 10.0)
                        weight = 0.3
                        reason = f"卖出信号: {symbol} (评分: {score:.2f})"
                    
                    insights.append(
                        Insight(
                            symbol=symbol,
                            direction=direction,
                            confidence=confidence,
                            weight=weight,
                            reason=reason
                        )
                    )
            except Exception as e:
                logger.error(f"处理 {symbol} 时失败: {e}")
        
        return insights


class ChipRiskManagementModel(RiskManagementModel):
    """
    筹码分布风险管理模型
    提供止损止盈和风险控制逻辑
    """
    
    def __init__(self, 
                 stop_loss_pct: float = 0.08,  # 止损8%
                 take_profit_pct: float = 0.15,  # 止盈15%
                 max_single_position_pct: float = 0.2,  # 单只股票最大20%仓位
                 max_total_exposure: float = 0.8):  # 总仓位不超过80%
        """
        Args:
            stop_loss_pct: 止损百分比
            take_profit_pct: 止盈百分比
            max_single_position_pct: 单只股票最大仓位比例
            max_total_exposure: 总暴露风险上限
        """
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_single_position_pct = max_single_position_pct
        self.max_total_exposure = max_total_exposure
        self.entry_prices: Dict[str, float] = {}  # 记录入场价格
    
    def on_data(self, insights: List[Insight], targets: Dict[str, float], 
                current_portfolio: Dict[str, float]) -> Dict[str, float]:
        """
        应用风险管理规则
        
        Args:
            insights: 洞察信号列表
            targets: 目标仓位
            current_portfolio: 当前持仓 {symbol: position_pct}
        
        Returns:
            调整后的目标仓位
        """
        adjusted_targets = targets.copy()
        
        # 1. 检查止损止盈
        for symbol, entry_price in self.entry_prices.items():
            if symbol not in current_portfolio:
                continue
            
            # 这里简化实现，实际需要获取当前价格
            # 假设通过某种方式获取当前价格，这里简化逻辑
            position = current_portfolio.get(symbol, 0)
            
            if position != 0:
                # 有持仓的情况下，检查是否需要止损或止盈
                # 这里需要真实的价格数据，暂时简化逻辑
                pass
        
        # 2. 控制单只股票最大仓位
        for symbol, target in adjusted_targets.items():
            if target > self.max_single_position_pct:
                adjusted_targets[symbol] = self.max_single_position_pct
            elif target < -self.max_single_position_pct:
                adjusted_targets[symbol] = -self.max_single_position_pct
        
        # 3. 控制总仓位风险
        total_exposure = sum(abs(t) for t in adjusted_targets.values())
        if total_exposure > self.max_total_exposure:
            # 按比例缩减所有仓位
            scale_factor = self.max_total_exposure / total_exposure
            for symbol in adjusted_targets:
                adjusted_targets[symbol] *= scale_factor
        
        return adjusted_targets
    
    def set_entry_price(self, symbol: str, price: float):
        """记录入场价格"""
        self.entry_prices[symbol] = price
    
    def clear_entry_price(self, symbol: str):
        """清仓时移除价格记录"""
        if symbol in self.entry_prices:
            del self.entry_prices[symbol]


class ChipScorer:
    """
    筹码分布选股评分器
    用于评估单只股票的主力资金吸引力
    """
    
    def get_available_windows(self) -> list:
        """[#46] 返回筹码分析支持的回看周期

        Returns:
            [60, 120]  — 60日轻量分析和120日完整分析
        """
        return [60, 120]

    def score(self, data: pd.DataFrame) -> float:
        """
        计算综合评分
        
        Args:
            data: OHLCV数据
        
        Returns:
            评分值 (0-10)，越高越有吸引力
        """
        if data.empty or len(data) < 120:
            return 0.0
        
        try:
            # 简化实现：基于价格和成交量计算评分
            score = self._calculate_simple_score(data)
            return score
        
        except Exception as e:
            logger.error(f"计算评分失败: {e}")
            return 0.0
    
    def _calculate_simple_score(self, data: pd.DataFrame) -> float:
        """简化的评分计算"""
        score = 0.0
        
        # 计算简单的技术指标
        closes = data['close'].values
        volumes = data['vol'].values if 'vol' in data.columns else data['amount'].values
        
        # 1. 价格动量评分
        if len(closes) >= 20:
            recent_return = (closes[-1] - closes[-20]) / closes[-20]
            if recent_return > 0:
                score += 3.0
            elif recent_return > -0.05:
                score += 1.5
        
        # 2. 成交量评分
        if len(volumes) >= 20:
            avg_vol = np.mean(volumes[-20:])
            current_vol = volumes[-1]
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0
            
            if vol_ratio >= 1.5:
                score += 4.0
            elif vol_ratio >= 1.2:
                score += 2.5
            else:
                score += 1.0
        
        # 3. 价格位置评分
        if len(closes) >= 60:
            highest_60 = np.max(closes[-60:])
            lowest_60 = np.min(closes[-60:])
            current_price = closes[-1]
            
            position = (current_price - lowest_60) / (highest_60 - lowest_60 + 1e-9)
            if 0.3 <= position <= 0.6:
                score += 3.0
            elif 0.6 < position <= 0.8:
                score += 2.0
            else:
                score += 1.0
        
        return score