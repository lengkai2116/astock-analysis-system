"""
因子基类
所有因子必须继承此基类
"""
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional


class FactorParam:
    """
    因子参数定义
    """
    def __init__(self, name: str, default: Any, param_type: str = "int", 
                 min_val: Optional[float] = None, max_val: Optional[float] = None,
                 description: str = ""):
        self.name = name
        self.default = default
        self.param_type = param_type  # int, float, list, str
        self.min_val = min_val
        self.max_val = max_val
        self.description = description
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "default": self.default,
            "type": self.param_type,
            "min": self.min_val,
            "max": self.max_val,
            "description": self.description
        }


class BaseFactor(ABC):
    """
    因子基类
    """
    
    # 因子元数据
    name: str = ""
    name_cn: str = ""
    category: str = ""
    subcategory: str = ""
    description: str = ""
    formula: str = ""
    source: str = ""
    source_detail: str = ""
    examples: str = ""
    
    # 参数定义
    params: List[FactorParam] = []
    
    # 依赖的数据列
    required_columns: List[str] = ["open", "high", "low", "close", "vol"]
    
    def __init__(self, **kwargs):
        """
        初始化因子
        """
        # 设置参数默认值
        self.param_values = {}
        for param in self.params:
            self.param_values[param.name] = kwargs.get(param.name, param.default)
    
    def get_param(self, name: str) -> Any:
        """
        获取参数值
        """
        return self.param_values.get(name)
    
    def set_param(self, name: str, value: Any):
        """
        设置参数值
        """
        self.param_values[name] = value
    
    def get_params_dict(self) -> Dict:
        """
        获取所有参数字典
        """
        return self.param_values.copy()
    
    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        计算因子
        返回因子序列（索引为data的索引）
        """
        pass
    
    def check_data(self, data: pd.DataFrame) -> bool:
        """
        检查数据是否满足要求
        """
        for col in self.required_columns:
            if col not in data.columns:
                return False
        return True
    
    def get_info(self) -> Dict:
        """
        获取因子信息
        """
        return {
            "name": self.name,
            "name_cn": self.name_cn,
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
            "formula": self.formula,
            "source": self.source,
            "source_detail": self.source_detail,
            "examples": self.examples,
            "params": [p.to_dict() for p in self.params],
            "required_columns": self.required_columns
        }
