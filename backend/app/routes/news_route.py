"""
消息面上下文 API 路由 — 153-P1-3
"""
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app.data.news_provider import NewsProvider

logger = logging.getLogger(__name__)
news_bp = Blueprint('news', __name__)
_provider = NewsProvider()

@news_bp.route('/api/news/<ts_code>', methods=['GET'])
@handle_exceptions
def get_stock_news(ts_code):
    days_back = request.args.get('days_back', '7')
    max_count = request.args.get('max_count', '10')
    try:
        news = _provider.get_news(ts_code, days_back=int(days_back), max_count=int(max_count))
        return jsonify({'code': 0, 'data': [n.to_dict() for n in news]})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e), 'data': []})

@news_bp.route('/api/news/market', methods=['GET'])
@handle_exceptions
def get_market_news():
    days_back = request.args.get('days_back', '1')
    max_count = request.args.get('max_count', '5')
    try:
        news = _provider.get_market_news(days_back=int(days_back), max_count=int(max_count))
        return jsonify({'code': 0, 'data': [n.to_dict() for n in news]})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e), 'data': []})

@news_bp.route('/api/news/context/<ts_code>', methods=['GET'])
@handle_exceptions
def get_news_context(ts_code):
    """供 AiContextBuilder 调用的消息面上下文段"""
    days_back = request.args.get('days_back', '3')
    try:
        news = _provider.get_news(ts_code, days_back=int(days_back), max_count=5)
        context = _provider.build_context_section(news)
        return jsonify({'code': 0, 'data': {'context': context, 'news': [n.to_dict() for n in news]}})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})
