#!/usr/bin/env python3
"""初始化 QMT 配置段到 RuntimeConfigManager"""
import sys, os, logging
logging.disable(logging.WARNING)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.runtime_config import runtime_config_manager

QMT_DEFAULT_CONFIG = {
    "enabled": False,            # 是否启用 QMT
    "account_id": "",            # QMT 账户 ID
    "host": "127.0.0.1",         # QMT 服务器地址
    "port": 8000,                # QMT 服务器端口
    "client_path": "",           # xtquant 客户端安装路径
    "auto_connect": False,       # 应用启动时自动连接
    "connect_timeout": 30,       # 连接超时秒数
}

def init_qmt_config():
    app = create_app()
    with app.app_context():
        existing = runtime_config_manager.get('qmt')
        if existing and isinstance(existing, dict) and 'enabled' in existing:
            print(f"QMT 配置已存在，跳过初始化。enabled={existing.get('enabled')}")
            return

        # 如果 env 中有值，优先迁移到 DB
        env_enabled = os.environ.get('QMT_ENABLED', '').lower() == 'true'
        env_account = os.environ.get('QMT_ACCOUNT_ID', '')

        if env_enabled or env_account:
            config = {
                "enabled": env_enabled,
                "account_id": env_account or QMT_DEFAULT_CONFIG["account_id"],
                "host": os.environ.get('QMT_HOST', QMT_DEFAULT_CONFIG["host"]),
                "port": int(os.environ.get('QMT_PORT', QMT_DEFAULT_CONFIG["port"])),
                "client_path": os.environ.get('QMT_CLIENT_PATH', QMT_DEFAULT_CONFIG["client_path"]),
                "auto_connect": env_enabled,
                "connect_timeout": int(os.environ.get('QMT_CONNECT_TIMEOUT', QMT_DEFAULT_CONFIG["connect_timeout"])),
            }
        else:
            config = dict(QMT_DEFAULT_CONFIG)

        runtime_config_manager.save_section('qmt', config)
        print(f"QMT 配置已初始化: enabled={config['enabled']}")

if __name__ == '__main__':
    init_qmt_config()
