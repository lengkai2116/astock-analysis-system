"""
共振评分 & ComboCard API 路由 — 152-Phase 3
"""
import logging
from app.utils.error_handlers import handle_exceptions
from flask import Blueprint, request, jsonify
from app.services.resonance_service import ResonanceService
from app.services.combo_engine import ComboEngine
from app.engine.patterns import PatternResult, PatternCategory, PatternLevel

logger = logging.getLogger(__name__)
resonance_bp = Blueprint('resonance', __name__)

_resonance = ResonanceService()
_combo_engine = ComboEngine()

@resonance_bp.route('/api/resonance/score', methods=['POST'])
@handle_exceptions
def resonance_score():
    """计算指定股票的共振评分和组合卡片"""
    body = request.get_json(silent=True) or {}
    ts_code = body.get('ts_code', '')
    patterns_dicts = body.get('patterns', [])

    if not ts_code:
        return jsonify({'code': -1, 'msg': '缺少 ts_code'})

    # 将前端传入的dict转为PatternResult
    patterns = []
    for p in patterns_dicts:
        try:
            pr = PatternResult(
                name=p.get('name', ''),
                category=PatternCategory(p.get('category', 'candlestick')),
                direction=p.get('direction', 'neutral'),
                strength=float(p.get('strength', 0.5)),
                source=p.get('source', ''),
                description=p.get('description', ''),
                levels=PatternLevel(**p['levels']) if p.get('levels') else None,
            )
            patterns.append(pr)
        except Exception as e:
            logger.warning(f"Pattern 转换失败: {e}")

    try:
        # 共振评分
        resonance_result = _resonance.score(ts_code, patterns)
        # 组合卡片
        combo_cards = _combo_engine.build_combos(patterns)

        return jsonify({
            'code': 0,
            'data': {
                'resonance': resonance_result.to_dict(),
                'combo_cards': [c.to_dict() for c in combo_cards],
            }
        })
    except Exception as e:
        logger.error(f"共振评分失败: {e}")
        return jsonify({'code': -1, 'msg': str(e)})

@resonance_bp.route('/api/resonance/combo-cards', methods=['POST'])
@handle_exceptions
def combo_cards():
    """仅返回组合卡片"""
    body = request.get_json(silent=True) or {}
    ts_code = body.get('ts_code', '')
    patterns_dicts = body.get('patterns', [])
    resolution = body.get('resolution', '日线')

    patterns = []
    for p in patterns_dicts:
        try:
            patterns.append(PatternResult(
                name=p.get('name', ''),
                category=PatternCategory(p.get('category', 'candlestick')),
                direction=p.get('direction', 'neutral'),
                strength=float(p.get('strength', 0.5)),
                source=p.get('source', ''),
                description=p.get('description', ''),
            ))
        except Exception:
            pass

    try:
        cards = _combo_engine.build_combos(patterns, resolution=resolution)
        return jsonify({
            'code': 0,
            'data': [c.to_dict() for c in cards]
        })
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})

@resonance_bp.route('/api/resonance/registry', methods=['GET'])
@handle_exceptions
def pattern_registry():
    """返回所有注册的模式元数据"""
    try:
        from app.engine.patterns.registry import PatternRegistry
        reg = PatternRegistry()
        from app.engine.patterns import PatternCategory
        return jsonify({
            'code': 0,
            'data': {
                'total': reg.total_count(),
                'by_category': reg.count_by_category(),
                'patterns': [p.to_dict() for p in reg.list_all()],
            }
        })
    except Exception as e:
        return jsonify({'code': -1, 'msg': str(e)})
