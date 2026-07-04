import os
from datetime import datetime


def _get_default_data_dir():
    """获取默认数据目录（开发环境：项目 data/，生产环境由 .env 覆盖）"""
    # 定位到 backend/ 上一级（项目根目录）
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(backend_dir)
    return os.path.join(project_root, 'data')


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 生产化连接池配置（PostgreSQL 多 worker 共享）
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': int(os.getenv('DB_POOL_SIZE', '10')),
        'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '20')),
        'pool_pre_ping': True,
        'pool_recycle': 3600,
    }
    TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN', '')
    DATA_DIR = os.getenv('DATA_DIR', _get_default_data_dir())
    CACHE_EXPIRE_TIME = 3600

    # Redis（Gunicorn 多 Worker SocketIO 广播）
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

    # LLM配置 - DeepSeek API (预留)
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
    DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')
    DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat-v4')

    # LLM配置 - LM Studio (备用)
    LM_STUDIO_ENDPOINT = os.getenv('LM_STUDIO_ENDPOINT', 'http://localhost:1234/v1')
    LM_STUDIO_MODEL = os.getenv('LM_STUDIO_MODEL', 'local-model')

    # 当前使用的LLM类型: 'deepseek', 'lm_studio', 'mock'
    LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'mock')

    # --- QMT 配置（可选，需要额外安装 miniQMT）---
    QMT_ENABLED = os.getenv('QMT_ENABLED', 'false').lower() == 'true'
    QMT_ACCOUNT_ID = os.getenv('QMT_ACCOUNT_ID', '')

    @classmethod
    def get_llm_config(cls):
        """获取当前LLM配置"""
        provider = cls.LLM_PROVIDER
        if provider == 'deepseek':
            return {
                'type': 'deepseek',
                'endpoint': cls.DEEPSEEK_BASE_URL,
                'model': cls.DEEPSEEK_MODEL,
                'api_key': cls.DEEPSEEK_API_KEY
            }
        elif provider == 'lm_studio':
            return {
                'type': 'lm_studio',
                'endpoint': cls.LM_STUDIO_ENDPOINT,
                'model': cls.LM_STUDIO_MODEL,
                'api_key': ''
            }
        else:
            return {
                'type': 'mock',
                'endpoint': '',
                'model': 'mock',
                'api_key': ''
            }
