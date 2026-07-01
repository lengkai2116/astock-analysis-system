"""
运行时配置管理器（RuntimeConfigManager）

职责：
  1. 启动时从 system_config 表加载全量配置到内存缓存
  2. 提供点号路径读取（get('llm.deepseek_api_key')）
  3. save() → 写入数据库 + 同步更新内存缓存（热更新）
  4. load() → 从数据库重新加载完整配置
  5. reload() → 强制从存储重新加载

生产约束：
  - 无 Redis 依赖，使用内存 dict 缓存
  - 支持 SQLite JSON 列存储
  - 线程安全（写操作加锁）
"""
import json
import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class RuntimeConfigManager:
    """运行时配置管理器（内存缓存 + 数据库持久化）"""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._loaded = False
        self._lock = threading.Lock()

    # ──────────────────────────────────────────
    # 加载与重载
    # ──────────────────────────────────────────

    def load(self) -> Dict[str, Any]:
        """从数据库加载全量配置到内存缓存"""
        with self._lock:
            self._cache = {}
            try:
                from app.models.system_config import SystemConfig
                from app import db
                rows = SystemConfig.query.all()
                for row in rows:
                    self._cache[row.key] = row.value
                self._loaded = True
                logger.info(f"RuntimeConfigManager: 已加载 {len(rows)} 条配置")
            except Exception as e:
                logger.warning(f"RuntimeConfigManager 加载失败: {e}")
                # 系统刚初始化时表可能不存在，使用空缓存降级
                self._loaded = True
            return dict(self._cache)

    def reload(self) -> Dict[str, Any]:
        """强制从数据库重新加载配置"""
        self._loaded = False
        return self.load()

    # ──────────────────────────────────────────
    # 读取
    # ──────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号路径读取

        示例：
          get('llm.provider') → 'deepseek'
          get('llm.deepseek_api_key') → 'sk-xxx'
          get('scheduling.daily_sync.enabled') → True
        """
        if not self._loaded:
            self.load()

        parts = key.split('.')
        value = self._cache
        for p in parts:
            if isinstance(value, dict):
                value = value.get(p)
            else:
                return default
        return value if value is not None else default

    def get_all(self) -> Dict[str, Any]:
        """获取全部配置（用于前端回填）"""
        if not self._loaded:
            self.load()
        return dict(self._cache)

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取某个配置段下的所有子配置"""
        return self.get(section, {})

    # ──────────────────────────────────────────
    # 写入
    # ──────────────────────────────────────────

    def save(self, config: Dict[str, Any]) -> None:
        """全量保存配置到数据库 + 更新内存缓存（热更新）

        config 的顶级 key 会被 upsert 到 system_config 表。
        例如 {'llm': {...}, 'data_source': {...}, 'notification': {...}}
        """
        from app.models.system_config import SystemConfig
        from app import db

        with self._lock:
            for top_key, top_value in config.items():
                if not isinstance(top_key, str) or not top_key.strip():
                    continue
                # Upsert
                existing = SystemConfig.query.get(top_key)
                if existing:
                    existing.value = top_value
                    existing.updated_at = datetime.utcnow()
                else:
                    row = SystemConfig(
                        key=top_key,
                        value=top_value,
                        updated_at=datetime.utcnow()
                    )
                    db.session.add(row)
                # 同步内存缓存
                self._cache[top_key] = top_value

            db.session.commit()
            logger.info(f"RuntimeConfigManager: 已保存 {len(config)} 条配置")

    def save_section(self, section: str, value: Dict[str, Any]) -> None:
        """保存某个配置段（如 'scheduling'）"""
        self.save({section: value})

    def update_item(self, key_path: str, value: Any) -> None:
        """更新单条配置项（支持点号路径）

        示例：update_item('llm.provider', 'deepseek')
        """
        parts = key_path.split('.')
        if len(parts) < 2:
            raise ValueError(f"key_path 至少需要两级（section.item），收到: {key_path}")

        section = parts[0]
        item_parts = parts[1:]

        # 读取当前配置段
        current = self.get(section, {})
        if not isinstance(current, dict):
            current = {}

        # 沿路径深入，自动创建中间节点
        target = current
        for p in item_parts[:-1]:
            if p not in target or not isinstance(target[p], dict):
                target[p] = {}
            target = target[p]
        target[item_parts[-1]] = value

        # 保存整段
        self.save_section(section, current)


# ──────────────────────────────────────────
# 模块单例
# ──────────────────────────────────────────

runtime_config_manager = RuntimeConfigManager()
