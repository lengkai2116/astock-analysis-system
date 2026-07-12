"""
API 响应缓存装饰器
===================
基于 cachetools.TTLCache，按 (endpoint, query_string) 缓存 JSON 响应。
用于高频读取的低变化端点（仪表盘、市场总览等）。

用法：
    @api_cache(ttl=30)
    def my_route():
        return jsonify(data)
"""
from functools import wraps
from flask import request
from cachetools import TTLCache
import logging

logger = logging.getLogger(__name__)

# 全局缓存实例，用于批量失效
_response_cache = TTLCache(maxsize=500, ttl=60)


def api_cache(ttl: int = 30, maxsize: int = 200):
    """API 响应缓存装饰器

    Args:
        ttl: 缓存生存时间（秒）
        maxsize: 最大缓存条目数
    """
    cache = TTLCache(maxsize=maxsize, ttl=ttl)

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # 构建缓存键：路由 + 排序后的 query params
            params = tuple(sorted(request.args.items())) if request.args else ()
            key = (request.path, params)

            # 检查缓存
            cached = cache.get(key)
            if cached is not None:
                return cached

            # 执行原函数
            response = f(*args, **kwargs)

            # 仅缓存成功响应
            if isinstance(response, tuple):
                body, status = response
                if status == 200:
                    cache[key] = response
            else:
                cache[key] = response

            return response
        return wrapper
    return decorator


def invalidate_api_cache(pattern: str = None):
    """按路径前缀失效缓存（适配数据更新后清除旧缓存）

    Args:
        pattern: 路径前缀，如 '/api/v3/market'。None 时清空全部
    """
    if pattern is None:
        _response_cache.clear()
        return
    keys_to_del = [k for k in _response_cache if k[0].startswith(pattern)]
    for k in keys_to_del:
        del _response_cache[k]
