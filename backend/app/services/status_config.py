"""status_engine.yaml / signal_registry.yaml 配置加载（334/336号：版本化可回滚阈值管理）

配置位于项目根 config/ 目录，与 .env 同级。
"""
import os
from functools import lru_cache

import yaml

# backend/app/services/status_config.py → 上3级 = 项目根
_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config',
)


@lru_cache(maxsize=4)
def load_yaml(name: str) -> dict:
    """加载 config 下 yaml（带缓存；文件变更后进程重启生效）"""
    path = os.path.join(_CONFIG_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def get_status_engine_config() -> dict:
    """L2 聚合配置（共识阈值/维度权重/conflict 规则/L0 系数）"""
    return load_yaml('status_engine.yaml')


def get_signal_registry() -> dict:
    """右侧信号注册表（5 类信号 × 触发/验证/生命周期）"""
    return load_yaml('signal_registry.yaml')
