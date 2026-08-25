"""
配置管理器（355号方案规则8）
===================================
提供配置文件的读取、验证和管理功能。

配置管理规则：
1. 配置文件必须纳入版本控制
2. 配置变更必须经过审批
3. 变更后必须进行测试验证
4. 必须支持配置回滚
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import shutil

logger = logging.getLogger(__name__)


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'config')
        self.config_dir = os.path.abspath(config_dir)
        self._configs: Dict[str, Dict] = {}
        self._config_history: Dict[str, list] = {}
        
    def load_config(self, config_name: str) -> Dict:
        """加载配置文件
        
        Args:
            config_name: 配置文件名（不含扩展名）
            
        Returns:
            配置字典
        """
        config_path = os.path.join(self.config_dir, f'{config_name}.yaml')
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            if config is None:
                config = {}
                
            self._configs[config_name] = config
            
            # 记录加载历史
            if config_name not in self._config_history:
                self._config_history[config_name] = []
            self._config_history[config_name].append({
                'action': 'load',
                'timestamp': datetime.now().isoformat(),
                'config_path': config_path
            })
            
            logger.info(f"加载配置文件: {config_path}")
            return config
            
        except FileNotFoundError:
            logger.warning(f"配置文件不存在: {config_path}")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"配置文件解析失败: {config_path}, {e}")
            return {}
            
    def save_config(self, config_name: str, config: Dict) -> bool:
        """保存配置文件
        
        Args:
            config_name: 配置文件名（不含扩展名）
            config: 配置字典
            
        Returns:
            是否保存成功
        """
        config_path = os.path.join(self.config_dir, f'{config_name}.yaml')
        
        try:
            # 备份原配置
            if os.path.exists(config_path):
                backup_path = f"{config_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                shutil.copy2(config_path, backup_path)
                
            # 保存新配置
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
                
            self._configs[config_name] = config
            
            # 记录保存历史
            if config_name not in self._config_history:
                self._config_history[config_name] = []
            self._config_history[config_name].append({
                'action': 'save',
                'timestamp': datetime.now().isoformat(),
                'config_path': config_path
            })
            
            logger.info(f"保存配置文件: {config_path}")
            return True
            
        except Exception as e:
            logger.error(f"保存配置文件失败: {config_path}, {e}")
            return False
            
    def get_config(self, config_name: str, key: str = None, default: Any = None) -> Any:
        """获取配置值
        
        Args:
            config_name: 配置文件名
            key: 配置键（支持点号分隔的嵌套键）
            default: 默认值
            
        Returns:
            配置值
        """
        if config_name not in self._configs:
            self.load_config(config_name)
            
        config = self._configs.get(config_name, {})
        
        if key is None:
            return config
            
        # 支持点号分隔的嵌套键
        keys = key.split('.')
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
                
        return value if value is not None else default
        
    def set_config(self, config_name: str, key: str, value: Any) -> bool:
        """设置配置值
        
        Args:
            config_name: 配置文件名
            key: 配置键（支持点号分隔的嵌套键）
            value: 配置值
            
        Returns:
            是否设置成功
        """
        if config_name not in self._configs:
            self.load_config(config_name)
            
        config = self._configs.get(config_name, {})
        
        # 支持点号分隔的嵌套键
        keys = key.split('.')
        current = config
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
            
        current[keys[-1]] = value
        
        return self.save_config(config_name, config)
        
    def validate_config(self, config_name: str, schema: Dict) -> bool:
        """验证配置是否符合schema
        
        Args:
            config_name: 配置文件名
            schema: 验证schema
            
        Returns:
            是否验证通过
        """
        config = self.get_config(config_name)
        
        def _validate(obj, schema, path=''):
            if isinstance(schema, dict):
                if not isinstance(obj, dict):
                    logger.error(f"配置验证失败: {path} 应为字典")
                    return False
                for key, sub_schema in schema.items():
                    if key not in obj:
                        if sub_schema.get('required', False):
                            logger.error(f"配置验证失败: {path}.{key} 是必需的")
                            return False
                    else:
                        if not _validate(obj[key], sub_schema, f"{path}.{key}"):
                            return False
            elif isinstance(schema, list):
                if not isinstance(obj, list):
                    logger.error(f"配置验证失败: {path} 应为列表")
                    return False
            return True
            
        return _validate(config, schema)
        
    def rollback_config(self, config_name: str) -> bool:
        """回滚配置到上一个版本
        
        Args:
            config_name: 配置文件名
            
        Returns:
            是否回滚成功
        """
        config_path = os.path.join(self.config_dir, f'{config_name}.yaml')
        
        # 查找最新的备份文件
        backup_files = []
        for f in os.listdir(self.config_dir):
            if f.startswith(f'{config_name}.yaml.bak.'):
                backup_files.append(f)
                
        if not backup_files:
            logger.warning(f"没有找到 {config_name} 的备份文件")
            return False
            
        # 按时间排序，取最新的
        backup_files.sort(reverse=True)
        latest_backup = os.path.join(self.config_dir, backup_files[0])
        
        try:
            shutil.copy2(latest_backup, config_path)
            self.load_config(config_name)
            
            # 记录回滚历史
            if config_name not in self._config_history:
                self._config_history[config_name] = []
            self._config_history[config_name].append({
                'action': 'rollback',
                'timestamp': datetime.now().isoformat(),
                'backup_file': latest_backup
            })
            
            logger.info(f"配置回滚成功: {config_name} → {latest_backup}")
            return True
            
        except Exception as e:
            logger.error(f"配置回滚失败: {config_name}, {e}")
            return False


# 全局单例
config_manager = ConfigManager()


def init_config():
    """初始化配置"""
    # 加载默认配置
    config_manager.load_config('data_sources')
    
    logger.info("配置管理器初始化完成")
