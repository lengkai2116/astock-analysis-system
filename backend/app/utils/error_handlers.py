"""
统一的异常处理模块
提供异常处理装饰器和通用错误响应
"""

from functools import wraps
from flask import jsonify
import traceback
import logging

logger = logging.getLogger(__name__)


def handle_exceptions(func):
    """
    统一的异常处理装饰器
    自动捕获异常并返回友好的JSON错误响应
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            logger.error(f"参数错误 in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'error': f'参数错误: {str(e)}',
                'error_type': 'ValueError'
            }), 400
        except KeyError as e:
            logger.error(f"数据键错误 in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'error': f'数据键错误: {str(e)}',
                'error_type': 'KeyError'
            }), 400
        except TypeError as e:
            logger.error(f"类型错误 in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'error': f'类型错误: {str(e)}',
                'error_type': 'TypeError'
            }), 400
        except AttributeError as e:
            logger.error(f"属性错误 in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'error': f'属性错误: {str(e)}',
                'error_type': 'AttributeError'
            }), 400
        except Exception as e:
            logger.error(f"未预期的错误 in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'error': f'服务器内部错误: {str(e)}',
                'error_type': 'InternalError'
            }), 500
    
    return wrapper


def safe_db_operation(func):
    """
    数据库操作安全装饰器
    确保数据库连接正确关闭
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"数据库操作错误 in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                'success': False,
                'error': f'数据库操作失败: {str(e)}',
                'error_type': 'DatabaseError'
            }), 500
    
    return wrapper


class APIException(Exception):
    """自定义API异常"""
    
    def __init__(self, message, status_code=400, error_type='APIException'):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
    
    def to_response(self):
        return jsonify({
            'success': False,
            'error': self.message,
            'error_type': self.error_type
        }), self.status_code


def validate_required_params(data, required_params):
    """
    验证必需参数
    
    Args:
        data: 请求数据字典
        required_params: 必需参数列表
    
    Raises:
        APIException: 当参数缺失时
    """
    missing_params = [p for p in required_params if p not in data or data[p] is None]
    if missing_params:
        raise APIException(
            f"缺少必需参数: {', '.join(missing_params)}",
            status_code=400,
            error_type='MissingParams'
        )
