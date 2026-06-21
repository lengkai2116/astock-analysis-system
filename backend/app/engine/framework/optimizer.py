"""
参数优化引擎
支持网格搜索、随机搜索等优化方法
"""
from typing import Dict, List, Optional, Any, Callable, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
import itertools



import logging
logger = logging.getLogger(__name__)
class ParameterOptimizer:
    """
    参数优化器基类
    """
    
    def __init__(self, param_space: Dict[str, List]):
        """
        Args:
            param_space: 参数空间定义 {param_name: [possible_values]}
        """
        self.param_space = param_space
        self.best_params = None
        self.best_score = -np.inf
        self.all_results = []
    
    def optimize(self, objective_func: Callable, max_iterations: Optional[int] = None) -> Dict:
        """
        执行优化
        
        Args:
            objective_func: 目标函数，接收参数dict，返回评分
            max_iterations: 最大迭代次数
        
        Returns:
            优化结果
        """
        raise NotImplementedError
    
    def get_results(self) -> List[Dict]:
        """获取所有结果"""
        return self.all_results


class GridSearchOptimizer(ParameterOptimizer):
    """
    网格搜索优化器
    穷举所有参数组合
    """
    
    def __init__(self, param_space: Dict[str, List]):
        super().__init__(param_space)
        self._generate_param_combinations()
    
    def _generate_param_combinations(self):
        """生成所有参数组合"""
        param_names = list(self.param_space.keys())
        param_values = list(self.param_space.values())
        
        self.param_combinations = []
        for combo in itertools.product(*param_values):
            self.param_combinations.append(dict(zip(param_names, combo)))
    
    def optimize(self, objective_func: Callable, max_iterations: Optional[int] = None) -> Dict:
        """执行网格搜索"""
        logger.info(f"网格搜索: {len(self.param_combinations)} 组参数组合")
        
        max_iter = max_iterations or len(self.param_combinations)
        
        for i, params in enumerate(self.param_combinations[:max_iter]):
            try:
                score = objective_func(params)
                
                self.all_results.append({
                    'params': params,
                    'score': score,
                    'iteration': i
                })
                
                if score > self.best_score:
                    self.best_score = score
                    self.best_params = params
                
                if (i + 1) % 10 == 0:
                    logger.info(f"已完成 {i+1}/{min(max_iter, len(self.param_combinations))}, 当前最佳: {self.best_score:.4f}")
            
            except Exception as e:
                logger.info(f"参数组合 {i} 执行失败: {e}")
                continue
        
        return {
            'best_params': self.best_params,
            'best_score': self.best_score,
            'total_iterations': len(self.all_results),
            'all_results': self.all_results
        }


class RandomSearchOptimizer(ParameterOptimizer):
    """
    随机搜索优化器
    从参数空间中随机采样
    """
    
    def __init__(self, param_space: Dict[str, List], seed: int = 42):
        super().__init__(param_space)
        self.seed = seed
        np.random.seed(seed)
    
    def _random_sample(self) -> Dict:
        """随机采样参数组合"""
        params = {}
        for name, values in self.param_space.items():
            params[name] = np.random.choice(values)
        return params
    
    def optimize(self, objective_func: Callable, max_iterations: int = 100) -> Dict:
        """执行随机搜索"""
        logger.info(f"随机搜索: {max_iterations} 次迭代")
        
        for i in range(max_iterations):
            params = self._random_sample()
            
            try:
                score = objective_func(params)
                
                self.all_results.append({
                    'params': params,
                    'score': score,
                    'iteration': i
                })
                
                if score > self.best_score:
                    self.best_score = score
                    self.best_params = params
                
                if (i + 1) % 10 == 0:
                    logger.info(f"已完成 {i+1}/{max_iterations}, 当前最佳: {self.best_score:.4f}")
            
            except Exception as e:
                logger.info(f"迭代 {i} 执行失败: {e}")
                continue
        
        return {
            'best_params': self.best_params,
            'best_score': self.best_score,
            'total_iterations': len(self.all_results),
            'all_results': self.all_results
        }


class ParameterSensitivityAnalysis:
    """
    参数敏感性分析
    """
    
    def __init__(self, optimizer: ParameterOptimizer):
        self.optimizer = optimizer
    
    def analyze(self) -> Dict:
        """
        分析参数敏感性
        
        Returns:
            敏感性分析结果
        """
        if not self.optimizer.all_results:
            logger.warning("请先运行优化")
            return {}
        
        results = self.optimizer.all_results
        param_names = list(self.optimizer.param_space.keys())
        
        sensitivity = {}
        
        for param in param_names:
            # 计算该参数不同取值的平均分数
            param_values = {}
            
            for result in results:
                val = result['params'][param]
                score = result['score']
                
                if val not in param_values:
                    param_values[val] = []
                
                param_values[val].append(score)
            
            # 计算统计量
            stats = {}
            for val, scores in param_values.items():
                stats[val] = {
                    'mean': np.mean(scores),
                    'std': np.std(scores),
                    'count': len(scores),
                    'max': np.max(scores),
                    'min': np.min(scores)
                }
            
            sensitivity[param] = {
                'stats_by_value': stats,
                'sensitivity_score': self._calculate_sensitivity(stats)
            }
        
        # 按敏感性排序
        sorted_params = sorted(sensitivity.items(), 
                              key=lambda x: x[1]['sensitivity_score'], 
                              reverse=True)
        
        return {
            'sensitivity': sensitivity,
            'sorted_params': [name for name, _ in sorted_params],
            'analysis_timestamp': datetime.now()
        }
    
    def _calculate_sensitivity(self, stats: Dict) -> float:
        """计算参数敏感性评分"""
        if len(stats) <= 1:
            return 0.0
        
        means = [s['mean'] for s in stats.values()]
        return np.std(means)


def create_objective_function(backtest_func, data) -> Callable:
    """
    创建目标函数（辅助函数）
    
    Args:
        backtest_func: 回测函数，接收 params 和 data
        data: 回测数据
    
    Returns:
        目标函数
    """
    def objective(params: Dict) -> float:
        try:
            result = backtest_func(params, data)
            return result.get('sharpe_ratio', 0.0)
        except Exception as e:
            logger.info(f"回测失败: {e}")
            return -np.inf
    
    return objective


def simple_backtest_example(params: Dict, data: pd.DataFrame) -> Dict:
    """
    简单回测示例函数
    
    Args:
        params: 参数字典
        data: 市场数据
    
    Returns:
        回测结果
    """
    # 这是一个示例，实际需要实现真实的回测逻辑
    # 这里使用随机评分作为演示
    import random
    base_score = 0.5 + random.random() * 0.5
    
    # 根据参数调整评分
    score_adj = 0
    if params.get('lookback_period', 120) > 100:
        score_adj += 0.1
    if params.get('rsi_upper', 70) < 80:
        score_adj += 0.05
    
    return {
        'sharpe_ratio': base_score + score_adj,
        'total_return': base_score * 0.2,
        'max_drawdown': -0.1 * base_score,
        'params': params
    }


PRESET_GRIDS = {
    'chanlun': {'name': '缠论策略', 'params': {'lookback_period': [60, 80, 100, 120, 140, 160, 180]}, 'default': 120, 'description': '缠论窗口参数平原验证'},
    'volume_price': {'name': '量价策略', 'params': {'lookback_period': [60, 80, 100, 120, 140, 160, 180]}, 'default': 120, 'description': '量价窗口参数平原验证'},
    'chip': {'name': '筹码策略', 'params': {'lookback_period': [40, 60, 80, 100, 120]}, 'default': 120, 'description': '筹码窗口参数平原验证'},
    'factor': {'name': '因子策略', 'params': {'lookback_period': [14, 20, 30, 40]}, 'default': 20, 'description': '因子窗口参数平原验证'},
}

def get_preset_grid(name: str) -> Optional[Dict]:
    return PRESET_GRIDS.get(name)

def list_preset_grids() -> List[str]:
    return list(PRESET_GRIDS.keys())

def run_preset_grid_search(name: str, objective_function: callable, optimizer_type: str = 'grid') -> Dict:
    preset = get_preset_grid(name)
    if not preset:
        raise ValueError(f"Unknown preset: {name}, available: {list_preset_grids()}")
    if optimizer_type == 'grid':
        from app.engine.framework.optimizer import GridSearchOptimizer
        optimizer = GridSearchOptimizer(preset['params'], objective_function)
    else:
        from app.engine.framework.optimizer import RandomSearchOptimizer
        optimizer = RandomSearchOptimizer(preset['params'], objective_function, n_iter=20)
    result = optimizer.optimize()
    result['preset_name'] = name
    result['preset_description'] = preset['description']
    return result