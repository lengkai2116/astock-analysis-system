"""
策略输出 AI 解读 API 路由 — 153-P3-1
"""
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app.services.strategy_ai_interpretation_service import (
    StrategyAIInterpretationService
)

logger = logging.getLogger(__name__)
strategy_interpret_bp = Blueprint('strategy_interpret', __name__)

_interpreter = StrategyAIInterpretationService()

@strategy_interpret_bp.route('/api/strategy-interpret/interpret', methods=['POST'])
@handle_exceptions
def interpret_signal():
    body = request.get_json(silent=True) or {}
    strategy = body.get('strategy', '')
    signal_data = body.get('signal', {})
    ts_code = body.get('ts_code', '')
    stock_name = body.get('stock_name', '')
    try:
        result = _interpreter.interpret(strategy, signal_data, ts_code, stock_name)
        return jsonify({'code': 0, 'data': result})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})

@strategy_interpret_bp.route('/api/strategy-interpret/batch', methods=['POST'])
@handle_exceptions
def batch_interpret():
    body = request.get_json(silent=True) or {}
    signals = body.get('signals', [])
    ts_code = body.get('ts_code', '')
    stock_name = body.get('stock_name', '')
    try:
        results = _interpreter.batch_interpret(signals, ts_code, stock_name)
        return jsonify({'code': 0, 'data': results})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})

@strategy_interpret_bp.route('/api/strategy-interpret/resonance', methods=['POST'])
@handle_exceptions
def interpret_resonance():
    body = request.get_json(silent=True) or {}
    resonance_data = body.get('resonance', {})
    combo_cards = body.get('combo_cards', [])
    try:
        text = _interpreter.interpret_resonance(resonance_data, combo_cards)
        return jsonify({'code': 0, 'data': {'interpretation': text}})
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})
