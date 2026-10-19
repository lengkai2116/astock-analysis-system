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

from flask import Blueprint, jsonify, request

from app.services.dashboard_service import DashboardService
from app.utils.api_cache import api_cache
from app.utils.error_handlers import handle_exceptions

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
    # 526 B8：days clamp 1~60（防负数/超大值）
    days = request.args.get('days', 20, type=int)
    days = max(1, min(days if days else 20, 60))
    data = _service.get_market_volume(days=days)
    return _data_response(data)


# ──────────────────────────────────────────────
# 4. 涨幅榜/跌幅榜（daily-top）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/daily-top', methods=['GET'])
@api_cache(ttl=120)  # 526 B10：补 api_cache（其余 sibling 端点均有，防热点路径每请求重算）
@handle_exceptions
def get_daily_top():
    """涨幅前十/跌幅前十排行"""
    # 526 B8：type 白名单 up/down；limit clamp 1~50
    type_ = request.args.get('type', 'up')
    if type_ not in ('up', 'down'):
        type_ = 'up'
    limit = request.args.get('limit', 10, type=int)
    limit = max(1, min(limit if limit else 10, 50))
    data = _service.get_daily_top(type=type_, limit=limit)
    return _data_response(data)


# ──────────────────────────────────────────────
# 523：全市场日终散点（eod-snapshot）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/eod-snapshot', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_eod_snapshot():
    """全市场前一交易日日终散点数据（体量×涨跌 + 开高低收四象限）"""
    data = _service.get_eod_snapshot()
    return _data_response(data)


# ──────────────────────────────────────────────
# 524 批次1'：大盘监控只读接口（breadth / state / emotion）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/breadth', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_market_breadth():
    """市场宽度（524 号 L2）：涨跌家数 + MA20占比/涨停比例"""
    data = _service.get_market_breadth()
    return _data_response(data)


@dashboard_bp.route('/api/v3/market/state', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_market_state():
    """大盘状态（524 号 L1）：4 状态·状态机（趋势/震荡/高波动/盘整）"""
    data = _service.get_market_state()
    return _data_response(data)


@dashboard_bp.route('/api/v3/market/emotion', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_market_emotion():
    """市场情绪（524 号 L3）：六段论阶段 + 涨停生态指标"""
    data = _service.get_market_emotion()
    return _data_response(data)


@dashboard_bp.route('/api/v3/market/sector-heat', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_sector_heat():
    """板块热度/排名（524 号 L4）：sector_heat_cache 最新日全行业"""
    top_n = request.args.get('top_n', 8, type=int)
    # 525 A4：clamp 防负数/超大值（负数/None 归默认，上限 100）
    top_n = min(top_n if top_n and top_n > 0 else 8, 100)
    data = _service.get_sector_heat(top_n=top_n)
    return _data_response(data)


@dashboard_bp.route('/api/v3/market/alerts', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_market_alerts():
    """市场预警（524 号 L5）：四条规则 + 建议输出（建议型、非强制）"""
    data = _service.get_market_alerts()
    return _data_response(data)


# ──────────────────────────────────────────────
# 5. 板块涨跌幅（sector-sector）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/sector-sector', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_sector_sector():
    """行业板块涨跌幅排行"""
    # 526 B8：top_n clamp 1~50
    top_n = request.args.get('top_n', 8, type=int)
    top_n = max(1, min(top_n if top_n else 8, 50))
    data = _service.get_sector_changes(top_n=top_n)
    return _data_response(data)


# 516 批次2（Q2）：/api/v3/dashboard/summary（AI 交易机会雷达）已下线（前后端一并移除）

# ──────────────────────────────────────────────
# 7. 全市场资金流向（moneyflow-summary）
# ──────────────────────────────────────────────
@dashboard_bp.route('/api/v3/market/moneyflow-summary', methods=['GET'])
@api_cache(ttl=120)
@handle_exceptions
def get_moneyflow_summary():
    """全市场资金流向趋势（近20日）"""
    # 526 B8：days clamp 1~60
    days = request.args.get('days', 20, type=int)
    days = max(1, min(days if days else 20, 60))
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
    # 526 B8：top_n clamp 1~50；stocks_per_sector clamp 1~10
    top_n = request.args.get('top_n', 8, type=int)
    top_n = max(1, min(top_n if top_n else 8, 50))
    stocks_per = request.args.get('stocks_per_sector', 3, type=int)
    stocks_per = max(1, min(stocks_per if stocks_per else 3, 10))
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
