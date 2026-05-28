"""
量化交易框架 - Algorithm Framework
参考 QuantConnect LEAN 的模块化架构设计
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np


class UniverseSelectionModel(ABC):
    """
    股票池选择模型
    负责从全市场股票中筛选出符合条件的候选股票
    """
    
    @abstractmethod
    def select(self, date_time: datetime, data: Any) -> List[str]:
        """
        在指定时间选择股票池
        
        Args:
            date_time: 选择时间
            data: 市场数据
        
        Returns:
            股票代码列表
        """
        pass
    
    @property
    def name(self) -> str:
        """模型名称"""
        return self.__class__.__name__


class AlphaModel(ABC):
    """
    信号生成模型
    负责生成交易信号 (Insights)
    """
    
    @abstractmethod
    def generate_insights(self, data: pd.DataFrame) -> List[Dict]:
        """
        生成洞察信号
        
        Args:
            data: 市场数据
        
        Returns:
            洞察信号列表，每个信号包含方向、强度、时间等信息
        """
        pass
    
    @property
    def name(self) -> str:
        """模型名称"""
        return self.__class__.__name__


class Insight:
    """
    洞察信号类
    表示策略对某只股票的交易观点
    """
    
    # 方向常量
    LONG = 1
    FLAT = 0
    SHORT = -1
    
    def __init__(
        self, 
        symbol: str,
        direction: int,
        confidence: float,
        weight: float,
        reason: str = ''
    ):
        """
        Args:
            symbol: 股票代码
            direction: 方向 (1=LONG, 0=FLAT, -1=SHORT)
            confidence: 置信度 (0-1)
            weight: 权重 (0-1)
            reason: 理由描述
        """
        self.symbol = symbol
        self.direction = direction
        self.confidence = confidence
        self.weight = weight
        self.reason = reason
        self.created_at = datetime.now()
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'direction_name': {1: 'LONG', 0: 'FLAT', -1: 'SHORT'}.get(self.direction, 'UNKNOWN'),
            'confidence': self.confidence,
            'weight': self.weight,
            'reason': self.reason,
            'created_at': self.created_at
        }


class PortfolioConstructionModel(ABC):
    """
    投资组合构建模型
    负责从洞察信号转换为目标持仓
    """
    
    @abstractmethod
    def create_targets(self, insights: List[Insight], current_portfolio: Dict) -> Dict:
        """
        创建投资组合目标
        
        Args:
            insights: 洞察信号列表
            current_portfolio: 当前持仓
        
        Returns:
            目标持仓配置
        """
        pass
    
    @property
    def name(self) -> str:
        """模型名称"""
        return self.__class__.__name__


class RiskManagementModel(ABC):
    """
    风险管理模型
    负责风险控制和止损止盈
    """
    
    @abstractmethod
    def on_data(self, insights: List[Insight], targets: Dict, current_portfolio: Dict) -> Dict:
        """
        处理数据，调整持仓，应用风险规则
        
        Args:
            insights: 洞察信号列表
            targets: 目标持仓
            current_portfolio: 当前持仓
        
        Returns:
            调整后的目标持仓
        """
        pass
    
    @property
    def name(self) -> str:
        """模型名称"""
        return self.__class__.__name__


class ExecutionModel(ABC):
    """
    执行模型
    负责将目标持仓转换为具体的执行订单
    """
    
    @abstractmethod
    def execute(self, targets: Dict, current_portfolio: Dict) -> List[Dict]:
        """
        执行订单列表
        
        Args:
            targets: 目标持仓
            current_portfolio: 当前持仓
        
        Returns:
            执行订单列表
        """
        pass
    
    @property
    def name(self) -> str:
        """模型名称"""
        return self.__class__.__name__


class Algorithm(ABC):
    """
    算法类 - 框架核心
    管理整个策略流程
    """
    
    def __init__(self, name: str = 'Algorithm'):
        self.name = name
        self._universe_selection: Optional[UniverseSelectionModel] = None
        self._alpha: Optional[AlphaModel] = None
        self._portfolio_construction: Optional[PortfolioConstructionModel] = None
        self._risk_management: Optional[RiskManagementModel] = None
        self._execution: Optional[ExecutionModel] = None
        self._portfolio: Dict = {}
        self._initialized = False
    
    def set_universe_selection(self, model: UniverseSelectionModel):
        """设置股票池选择模型"""
        self._universe_selection = model
    
    def set_alpha(self, model: AlphaModel):
        """设置alpha模型"""
        self._alpha = model
    
    def set_portfolio_construction(self, model: PortfolioConstructionModel):
        """设置投资组合构建模型"""
        self._portfolio_construction = model
    
    def set_risk_management(self, model: RiskManagementModel):
        """设置风险管理模型"""
        self._risk_management = model
    
    def set_execution(self, model: ExecutionModel):
        """设置执行模型"""
        self._execution = model
    
    def initialize(self):
        """初始化算法"""
        self._initialized = True
    
    def on_data(self, date_time: datetime, data: Any) -> Tuple[List, Dict]:
        """
        数据事件处理
        
        Args:
            date_time: 时间戳
            data: 市场数据
        
        Returns:
            (洞察信号列表, 执行订单列表)
        """
        if not self._initialized:
            self.initialize()
        
        # 1. 选择股票池
        universe = []
        if self._universe_selection:
            universe = self._universe_selection.select(date_time, data)
        
        # 2. 生成信号
        insights = []
        if self._alpha:
            insights = self._alpha.generate_insights(data)
        
        # 3. 构建投资组合目标
        targets = {}
        if self._portfolio_construction:
            targets = self._portfolio_construction.create_targets(
                insights, self._portfolio.copy()
            )
        
        # 4. 风险管理
        if self._risk_management:
            targets = self._risk_management.on_data(insights, targets, self._portfolio.copy())
        
        # 5. 执行订单
        orders = []
        if self._execution:
            orders = self._execution.execute(targets, self._portfolio.copy())
        
        # 更新当前持仓（模拟）
        self._update_portfolio(targets)
        
        return insights, orders
    
    def _update_portfolio(self, targets: Dict):
        """更新持仓（模拟）"""
        self._portfolio = targets.copy()
    
    def get_portfolio(self) -> Dict:
        """获取当前持仓"""
        return self._portfolio.copy()
    
    def set_portfolio(self, portfolio: Dict):
        """设置初始持仓"""
        self._portfolio = portfolio.copy()


class EqualWeightPortfolioConstruction(PortfolioConstructionModel):
    """
    等权重投资组合构建
    将所有洞察信号等权重分配
    """
    
    def create_targets(self, insights: List[Insight], current_portfolio: Dict) -> Dict:
        if not insights:
            return current_portfolio
        
        long_insights = [i for i in insights if i.direction == Insight.LONG]
        
        if not long_insights:
            return current_portfolio
        
        # 等权重分配
        weight = 1.0 / len(long_insights)
        
        targets = {}
        for insight in long_insights:
            targets[insight.symbol] = {
                'symbol': insight.symbol,
                'target_weight': weight,
                'confidence': insight.confidence
            }
        
        return targets


class StopLossRiskManagement(RiskManagementModel):
    """
    止损风险管理
    简单的止损止盈控制
    """
    
    def __init__(self, stop_loss_threshold: float = 0.08):
        """
        Args:
            stop_loss_threshold: 止损阈值，默认8%
        """
        self.stop_loss_threshold = stop_loss_threshold
    
    def on_data(self, insights: List[Insight], targets: Dict, current_portfolio: Dict) -> Dict:
        """应用风险规则"""
        adjusted = targets.copy()
        return adjusted