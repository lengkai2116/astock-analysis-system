"""
因子基类
所有因子必须继承此基类
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd


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

    # 语义标签（与 219 规格书 §2.2 对齐，可选）
    tags: Dict[str, List[str]] = {}

    # 关联因子列表（同类别或逻辑相关的因子名）
    related_factors: List[str] = []

    # 参数定义
    params: List[FactorParam] = []

    # 依赖的数据列
    required_columns: List[str] = ["open", "high", "low", "close", "vol"]

    def __init__(self, **kwargs):
        """
        初始化因子
        """
        # 501 #R5：类级可变属性（params/tags/related_factors/required_columns）每实例拷贝，
        # 避免子类/调用方就地 mutate 污染全局因子定义。
        # required_columns 字符串先归一为列表（#R38）；tags 内层 list 需深拷贝（浅拷贝仍共享）
        self.param_values = {}
        self._params = list(self.params)
        self._tags = {k: list(v) if isinstance(v, (list, tuple)) else v
                      for k, v in (self.tags or {}).items()}
        self._related_factors = list(self.related_factors)
        _req_cols = self.required_columns
        if isinstance(_req_cols, str):
            _req_cols = [_req_cols]
        self._required_columns = list(_req_cols)
        # 501 #R6：默认值按声明类型/范围校验（越界/非法抛 ValueError，不静默透传）
        for param in self._params:
            value = kwargs.get(param.name, param.default)
            self._validate_param_value(param, value)
            self.param_values[param.name] = value

    def get_param(self, name: str) -> Any:
        """
        获取参数值
        """
        return self.param_values.get(name)

    def set_param(self, name: str, value: Any):
        """
        设置参数值（501 #R6：按声明类型/范围校验，非法抛 ValueError）
        """
        for param in self._params:
            if param.name == name:
                self._validate_param_value(param, value)
                self.param_values[name] = value
                return
        self.param_values[name] = value

    def _validate_param_value(self, param: FactorParam, value: Any):
        """501 #R6：按 FactorParam 声明做类型/范围校验（int/float/list/str + min/max）

        None 视为「未传」不校验（沿用默认值路径）；非法值抛 ValueError 而非静默透传
        （原实现 period=0/负数直达 rolling(0)/ewm(com=-1)，产出异常或静默错值）。
        """
        if value is None:
            return
        if param.param_type == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name} 需要 int，收到 {value!r}")
            if param.min_val is not None and value < param.min_val:
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name}={value} 低于下限 {param.min_val}")
            if param.max_val is not None and value > param.max_val:
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name}={value} 超过上限 {param.max_val}")
        elif param.param_type == "float":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name} 需要 float，收到 {value!r}")
            if param.min_val is not None and value < param.min_val:
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name}={value} 低于下限 {param.min_val}")
            if param.max_val is not None and value > param.max_val:
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name}={value} 超过上限 {param.max_val}")
        elif param.param_type == "list":
            if not isinstance(value, (list, tuple)):
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name} 需要 list，收到 {type(value).__name__}")
        elif param.param_type == "str":
            if not isinstance(value, str):
                raise ValueError(
                    f"因子 {self.name} 参数 {param.name} 需要 str，收到 {type(value).__name__}")

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
        检查数据是否满足要求（501 #R38：required_columns 字符串归一为列表；
        #R27：空表/零行直接判 False，避免空序列被当成功结果）
        """
        cols = self._required_columns
        if isinstance(cols, str):
            cols = [cols]
        if data is None or data.empty:
            return False
        for col in cols:
            if col not in data.columns:
                return False
        return True

    def get_info(self) -> Dict:
        """
        获取因子信息（501 #R5：tags/relate/required_columns/params 均返回拷贝，
        调用方 mutate 不再污染类级共享容器）
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
            "tags": {k: list(v) if isinstance(v, (list, tuple)) else v
                     for k, v in self._tags.items()},
            "relate": list(self._related_factors),
            "params": [p.to_dict() for p in self._params],
            "required_columns": list(self._required_columns)
        }
