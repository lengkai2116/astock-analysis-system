"""配置加载兼容壳（431号 F1：两套加载器已合并）

本模块原为独立加载器（自有 _CONFIG_DIR 解析与 @lru_cache），现退化为**薄再导出壳**：
实现与权威入口已统一到 backend/config/__init__.py（430号 §9 第 3 条的权威 yaml 位置）。

保留本模块仅为兼容既有消费方（app/opportunity_atlas/{status_engine,arbiter,
advice_builder,advice_engine}.py），不要在此新增加载逻辑。
"""
from config import (
    _CONFIG_DIR,
    get_signal_registry,
    get_status_engine_config,
    load_yaml,
)

__all__ = ['_CONFIG_DIR', 'load_yaml', 'get_status_engine_config', 'get_signal_registry']
