"""
仪表盘 Dashboard API 路由 — 213号规格书
6 个新端点 + 规格书定义的统一响应格式

⚠️ 数据完整性约束：所有数据不可用场景返回 503，不假造模拟数据。
"""


def _data_response(data):
    """统一处理数据不可用情况——返回 data 或 503 错误"""
    if data is None:
        return jsonify({
            'success': False,
            'message': '数据源不可用，暂无法加载该模块。请检查网络连接或稍后重试。',
            'error_type': 'DataUnavailable',
        }), 503
    return jsonify({'success': True, 'data': data})
import logging
from flask import Blueprint, request, jsonify
from app.services.dashboard_service import DashboardService
from app.utils.error_handlers import handle_exceptions
from app.utils.api_cache import api_cache

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)
_service = DashboardService()

# ══════════════════════════════════════════════════════════════
# ‼️ 重要：market/overview 增强在 market.py 中实现（已有路由）
#        chart/kline?mini=true 增强在 chart.py 中实现（已有路由）
# ══════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────
# 3. 成交额柱状图（index-daily）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/index-daily', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_index_daily():
    """四大交易所合计成交额柱状图（近20日）"""
    days = request.args.get('days', 20, type=int)
    data = _service.get_market_volume(days=days)
    return _data_response(data)


# ──────────────────────────────────────────────
# 4. 涨幅榜/跌幅榜（daily-top）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/daily-top', methods=['GET'])
@handle_exceptions
def get_daily_top():
    """涨幅前十/跌幅前十排行"""
    type_ = request.args.get('type', 'up')
    limit = request.args.get('limit', 10, type=int)
    data = _service.get_daily_top(type=type_, limit=limit)
    return _data_response(data)


# ──────────────────────────────────────────────
# 5. 板块涨跌幅（sector-sector）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/sector-sector', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_sector_sector():
    """行业板块涨跌幅排行"""
    top_n = request.args.get('top_n', 8, type=int)
    data = _service.get_sector_changes(top_n=top_n)
    return _data_response(data)


# ──────────────────────────────────────────────
# 6. AI雷达+策略信号（dashboard/summary）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/dashboard/summary', methods=['GET'])
@handle_exceptions
def get_dashboard_summary():
    """AI交易机会雷达 + 策略信号汇总"""
    data = _service.get_dashboard_summary()
    return _data_response(data)


# ──────────────────────────────────────────────
# 7. 全市场资金流向（moneyflow-summary）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/moneyflow-summary', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_moneyflow_summary():
    """全市场资金流向趋势（近20日）"""
    days = request.args.get('days', 20, type=int)
    data = _service.get_moneyflow_summary(days=days)
    return _data_response(data)


# ──────────────────────────────────────────────
# 8. 板块资金流向（sector-moneyflow）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/sector-moneyflow', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_sector_moneyflow():
    """行业板块净流入排行 + Top5板块×前3个股"""
    top_n = request.args.get('top_n', 8, type=int)
    stocks_per = request.args.get('stocks_per_sector', 3, type=int)
    data = _service.get_sector_moneyflow(top_n=top_n, stocks_per_sector=stocks_per)
    return _data_response(data)


# ──────────────────────────────────────────────
# 9. 仪表盘聚合（聚合全部 7 个数据源）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/dashboard/full', methods=['GET'])
@api_cache(ttl=30)
@handle_exceptions
def get_dashboard_full():
    """聚合仪表盘全部数据 — 一次调用替代 7 次独立请求"""
    data = _service.get_dashboard_full()
    return _data_response(data)
