import os
from datetime import datetime

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN', '')
    DATA_DIR = os.getenv('DATA_DIR', '/data')
    CACHE_EXPIRE_TIME = 3600
    
    # LLM配置 - DeepSeek API (预留)
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
    DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')
    DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
    
    # LLM配置 - LM Studio (备用)
    LM_STUDIO_ENDPOINT = os.getenv('LM_STUDIO_ENDPOINT', 'http://localhost:1234/v1')
    LM_STUDIO_MODEL = os.getenv('LM_STUDIO_MODEL', 'local-model')
    
    # 当前使用的LLM类型: 'deepseek', 'lm_studio', 'mock'
    LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'mock')
    
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
