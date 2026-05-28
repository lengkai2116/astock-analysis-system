"""配置模块"""
import os
import yaml
from typing import Dict, Any


def load_strategy_config(path: str = None) -> Dict[str, Any]:
    """加载策略配置 YAML 文件"""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), 'strategy_defaults.yaml')
    
    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    return config


# 全局缓存（惰性加载）
_strategy_config: Dict[str, Any] = None


def get_strategy_config(reload: bool = False) -> Dict[str, Any]:
    """获取策略配置（支持热重载）"""
    global _strategy_config
    if _strategy_config is None or reload:
        _strategy_config = load_strategy_config()
    return _strategy_config
