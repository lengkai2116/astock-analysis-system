"""简易内存速率限制中间件"""
import time
from collections import defaultdict
from flask import request, jsonify

class MemoryRateLimiter:
    def __init__(self):
        self._buckets = defaultdict(list)

    def is_limited(self, key, max_requests, window_seconds=60):
        now = time.time()
        self._buckets[key] = [t for t in self._buckets[key] if now - t < window_seconds]
        if len(self._buckets[key]) >= max_requests:
            return True
        self._buckets[key].append(now)
        return False

_limiter = MemoryRateLimiter()

def rate_limit(max_requests=100, window=60, key_func=None):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = key_func() if key_func else request.remote_addr or "unknown"
            if _limiter.is_limited(key, max_requests, window):
                return jsonify({
                    "success": False,
                    "error": "请求过于频繁，请稍后再试",
                    "error_type": "RateLimited",
                    "retry_after": window
                }), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator

auth_rate_limit = rate_limit(max_requests=10, window=60)
api_rate_limit = rate_limit(max_requests=100, window=60)
