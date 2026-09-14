"""配置模块：backend/config/ 是唯一权威配置位置（430号 §9 第 3 条）

431号 F1：合并原两套并存的配置加载器（app/services/status_config.py 与本模块）。
本模块为**唯一实现与权威入口**；app/services/status_config.py 退化为薄再导出壳。

  - load_yaml(name)：通用加载器，唯一缓存机制（@lru_cache）
  - get_status_engine_config() / get_signal_registry()：L2 聚合配置 / 信号注册表
  - load_strategy_config(path=None) / get_strategy_config(reload=False)：筹码策略默认配置

口径（431号 F1）：文件缺失一律返回 {}、不抛错——配置为「可选 + 代码默认值兜底」；
所有加载共用同一个 lru_cache，避免多套缓存导致的行为不一致。
"""
import os
from functools import lru_cache
from typing import Any, Dict

import yaml

# backend/config/ → 加载器与配置文件同处一目录
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_yaml(path: str) -> Dict[str, Any]:
    """按绝对路径读取 yaml；缺失或空文件一律返回 {}"""
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=8)
def load_yaml(name: str) -> Dict[str, Any]:
    """加载 backend/config/ 下的 yaml（唯一缓存机制；文件变更后进程重启生效）"""
    return _read_yaml(os.path.join(_CONFIG_DIR, name))


def get_status_engine_config() -> Dict[str, Any]:
    """L2 聚合配置（共识阈值/维度权重/conflict 规则/L0 系数）"""
    return load_yaml('status_engine.yaml')


def get_signal_registry() -> Dict[str, Any]:
    """右侧信号注册表（5 类信号 × 触发/验证/生命周期）"""
    return load_yaml('signal_registry.yaml')


def load_strategy_config(path: str = None) -> Dict[str, Any]:
    """加载策略配置 YAML 文件（默认 strategy_defaults.yaml，走缓存；显式 path 不走缓存）"""
    if path is None:
        return load_yaml('strategy_defaults.yaml')
    return _read_yaml(path)


def get_strategy_config(reload: bool = False) -> Dict[str, Any]:
    """获取策略配置（reload=True 时清空缓存后重读，即热重载）"""
    if reload:
        load_yaml.cache_clear()
    return load_yaml('strategy_defaults.yaml')
