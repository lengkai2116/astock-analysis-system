"""
因子注册表
用于动态注册和获取因子
"""
import importlib
import os
from typing import Dict, Type, List, Optional
from .base import BaseFactor



import logging
logger = logging.getLogger(__name__)
class FactorRegistry:
    """
    因子注册表
    """
    
    def __init__(self):
        self._factors: Dict[str, Type[BaseFactor]] = {}
        self._categories: Dict[str, List[str]] = {}
        self._sources: Dict[str, List[str]] = {}
    
    def register(self, factor_class: Type[BaseFactor]):
        """
        注册因子
        """
        name = factor_class.name
        if name in self._factors:
            logger.warning(r"因子 {name} 已存在，将被覆盖")
        
        self._factors[name] = factor_class
        
        # 按类别分组
        category = factor_class.category
        if category not in self._categories:
            self._categories[category] = []
        if name not in self._categories[category]:
            self._categories[category].append(name)
        
        # 按来源分组
        source = factor_class.source
        if source not in self._sources:
            self._sources[source] = []
        if name not in self._sources[source]:
            self._sources[source].append(name)
    
    def get_factor_class(self, name: str) -> Optional[Type[BaseFactor]]:
        """
        获取因子类
        """
        return self._factors.get(name)
    
    def get_factor(self, name: str, **kwargs) -> Optional[BaseFactor]:
        """
        获取因子实例
        """
        factor_class = self.get_factor_class(name)
        if factor_class:
            return factor_class(**kwargs)
        return None
    
    def list_factors(self, category: Optional[str] = None, 
                     source: Optional[str] = None) -> List[str]:
        """
        列出因子名称
        """
        factors = list(self._factors.keys())
        
        if category:
            factors = [f for f in factors if f in self._categories.get(category, [])]
        
        if source:
            factors = [f for f in factors if f in self._sources.get(source, [])]
        
        return sorted(factors)
    
    def list_categories(self) -> List[str]:
        """
        列出所有类别
        """
        return sorted(self._categories.keys())
    
    def list_sources(self) -> List[str]:
        """
        列出所有来源
        """
        return sorted(self._sources.keys())
    
    def get_category_factors(self, category: str) -> List[str]:
        """
        获取某类别的所有因子
        """
        return self._categories.get(category, [])
    
    def get_source_factors(self, source: str) -> List[str]:
        """
        获取某来源的所有因子
        """
        return self._sources.get(source, [])
    
    def get_all_factors_info(self) -> List[Dict]:
        """
        获取所有因子的信息
        """
        result = []
        for name in self._factors:
            factor_class = self._factors[name]
            factor = factor_class()
            result.append(factor.get_info())
        return result
    
    def search_factors(self, keyword: str) -> List[str]:
        """
        搜索因子
        """
        keyword = keyword.lower()
        result = []
        for name, factor_class in self._factors.items():
            if (keyword in name.lower() or 
                keyword in factor_class.name_cn.lower() or 
                keyword in factor_class.description.lower()):
                result.append(name)
        return result


# 全局注册表实例
_global_registry: Optional[FactorRegistry] = None


def get_factor_registry() -> FactorRegistry:
    """
    获取全局因子注册表
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = FactorRegistry()
        # 自动加载内置因子
        _load_builtin_factors(_global_registry)
    return _global_registry


def _load_builtin_factors(registry: FactorRegistry):
    """
    自动加载内置因子
    """
    # 获取当前目录
    current_dir = os.path.dirname(__file__)
    builtin_dir = os.path.join(current_dir, 'builtin')
    
    if not os.path.exists(builtin_dir):
        return
    
    # 遍历builtin目录下的所有模块
    for filename in os.listdir(builtin_dir):
        if filename.endswith('.py') and filename != '__init__.py':
            module_name = filename[:-3]
            try:
                # 导入模块
                module = importlib.import_module(f'.builtin.{module_name}', __package__)
                # 查找所有继承自BaseFactor的类
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, BaseFactor) and 
                        attr != BaseFactor):
                        registry.register(attr)
            except Exception as e:
                logger.warning(r"加载因子模块 {module_name} 失败: {e}")
