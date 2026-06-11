"""
认证模块 — 简单 Token 鉴权
============================
部署前安全加固：基于 Bearer Token 的请求鉴权。

工作方式:
- 读取环境变量 AUTH_TOKEN，如未设置则跳过鉴权（兼容开发模式）
- 前端在请求头中携带 Authorization: Bearer <token>
- 对 /api/auth/login 和 /api/v1/health 等端点放行
"""

import os
import secrets
import hashlib
import logging
from functools import wraps
from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)

# 从环境变量获取 token，未设置时自动生成一个
_AUTH_TOKEN = os.environ.get('AUTH_TOKEN', '').strip()

# 跳过认证的白名单路径
WHITELIST_PATHS = [
    '/api/v1/health',
    '/api/v3/health',
    '/api/auth/login', '/api/auth/status',
]


def is_auth_enabled() -> bool:
    """是否启用了认证"""
    return bool(_AUTH_TOKEN)


def get_auth_token() -> str:
    """获取当前认证 Token"""
    return _AUTH_TOKEN


def generate_token() -> str:
    """生成随机 Token"""
    return secrets.token_urlsafe(32)


def require_auth(f):
    """请求鉴权装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_auth_enabled():
            return f(*args, **kwargs)

        # 白名单放行
        path = request.path
        for whitelist in WHITELIST_PATHS:
            if path.startswith(whitelist):
                return f(*args, **kwargs)

        # 提取 Token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'error': '缺少认证令牌',
                'error_type': 'AuthRequired'
            }), 401

        token = auth_header[7:]
        if not _constant_time_compare(token, _AUTH_TOKEN):
            return jsonify({
                'success': False,
                'error': '认证令牌无效',
                'error_type': 'AuthInvalid'
            }), 403

        return f(*args, **kwargs)
    return decorated


def _constant_time_compare(a: str, b: str) -> bool:
    """常量时间比较，防止时序攻击"""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


# ── 登录路由 ──
from flask import Blueprint
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """登录接口（简化版：提供 token 即登录成功）"""
    data = request.get_json(silent=True) or {}
    provided = data.get('token', '').strip()

    if is_auth_enabled():
        if not provided:
            return jsonify({'success': False, 'error': '请输入 Token'}), 401
        if not _constant_time_compare(provided, _AUTH_TOKEN):
            return jsonify({'success': False, 'error': 'Token 无效'}), 403

    return jsonify({
        'success': True,
        'data': {
            'token': _AUTH_TOKEN,
            'message': '登录成功',
        }
    })


@auth_bp.route('/api/auth/status', methods=['GET'])
def auth_status():
    """查询认证状态"""
    return jsonify({
        'success': True,
        'data': {
            'enabled': is_auth_enabled(),
            'has_token': bool(_AUTH_TOKEN),
            'token_preview': _AUTH_TOKEN[:8] + '...' if _AUTH_TOKEN else '',
        }
    })
