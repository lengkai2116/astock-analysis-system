"""
策略沙箱 API 路由（222号 Phase 1）
单策略轻量测试 + 参数变体对比 + 历史记录

v1: /api/v1/verify — 信号记录查询（保留）
v3: /api/v3/sandbox — 沙箱测试（新增）
"""
import logging
from datetime import date, timedelta
from flask import Blueprint, request, jsonify

from app import db
from app.models.verification import SignalRecord
from app.utils.error_handlers import handle_exceptions
from app.services.sandbox_service import (
    SandboxService,
    save_test_record,
    list_test_records,
)

logger = logging.getLogger(__name__)

# ── v1 保留：信号记录查询 ──────────────────────────────────────

sandbox_bp = Blueprint('sandbox_v1', __name__, url_prefix='/api/v1/verify')


@sandbox_bp.route('/signal-records', methods=['GET'])  # DEPRECATED: use /api/v3/sandbox
@handle_exceptions
def list_signal_records():
    """获取策略信号记录 — 策略沙箱的明细数据源"""
    ts_code = request.args.get('ts_code')
    days = int(request.args.get('days', 30))

    query = SignalRecord.query
    if ts_code:
        query = query.filter_by(ts_code=ts_code)
    cutoff = date.today() - timedelta(days=days)
    query = query.filter(SignalRecord.signal_date >= cutoff)
    records = query.order_by(SignalRecord.signal_date.desc()).limit(200).all()

    return jsonify({
        'success': True,
        'data': [r.to_dict() for r in records]
    })


# ── v3 新增：策略沙箱测试 ──────────────────────────────────────

sandbox_v3_bp = Blueprint('sandbox_v3', __name__, url_prefix='/api/v3/sandbox')


@sandbox_v3_bp.route('/run', methods=['POST'])
@handle_exceptions
def run_sandbox():
    """
    运行单策略沙箱测试（S1）

    请求体:
    {
        "ts_code": "000001.SZ",
        "start_date": "20250101",
        "end_date": "20250630",
        "params": {
            "signal_method": "sma_cross",
            "short_window": 5,
            "long_window": 20
        },
        "config": {
            "initial_capital": 100000,
            "commission_rate": 0.0003
        },
        "note": "测试SMA5/20金叉死叉"
    }

    返回5区域: info / metrics / trades / equity_curve / suggestions
    """
    data = request.get_json() or {}
    ts_code = data.get('ts_code')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    params = data.get('params', {})
    config = data.get('config', {})
    note = data.get('note', '')

    if not ts_code:
        return jsonify({'success': False, 'error': 'ts_code 不能为空'}), 400
    if not start_date or not end_date:
        return jsonify({'success': False, 'error': 'start_date 和 end_date 不能为空'}), 400

    service = SandboxService()
    result = service.run_single(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        params=params,
        config=config,
    )

    # 保存到历史记录
    if result.get('success'):
        save_test_record(ts_code, params, result.get('metrics', {}), note)

    return jsonify(result)


@sandbox_v3_bp.route('/compare', methods=['POST'])
@handle_exceptions
def compare_sandbox():
    """
    运行参数变体对比测试（S2）

    请求体:
    {
        "ts_code": "000001.SZ",
        "start_date": "20250101",
        "end_date": "20250630",
        "param_sets": [
            {"label": "快速SMA", "params": {"short_window": 5, "long_window": 20}},
            {"label": "慢速SMA", "params": {"short_window": 10, "long_window": 30}},
            {"label": "RSI", "params": {"signal_method": "rsi", "rsi_period": 14}}
        ],
        "config": {...}
    }
    """
    data = request.get_json() or {}
    ts_code = data.get('ts_code')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    param_sets = data.get('param_sets', [])
    config = data.get('config', {})

    if not ts_code:
        return jsonify({'success': False, 'error': 'ts_code 不能为空'}), 400
    if not param_sets:
        return jsonify({'success': False, 'error': 'param_sets 不能为空'}), 400

    service = SandboxService()
    result = service.run_compare(
        ts_code=ts_code,
        start_date=start_date or '20250101',
        end_date=end_date or '20250630',
        param_sets=param_sets,
        config=config,
    )

    return jsonify(result)


@sandbox_v3_bp.route('/history', methods=['GET'])
@handle_exceptions
def get_sandbox_history():
    """
    获取沙箱测试历史（S3）

    查询参数:
    - limit: 返回条数（默认20）
    """
    limit = request.args.get('limit', 20, type=int)
    records = list_test_records(limit)

    return jsonify({
        'success': True,
        'data': records,
        'total': len(records),
    })


@sandbox_v3_bp.route('/templates', methods=['GET'])
@handle_exceptions
def get_sandbox_templates():
    """
    获取沙箱预置策略模板参数（S4）
    返回可供前端快速选择的策略模板参数配置
    """
    templates = [
        {
            'id': 'sma_fast',
            'name': 'SMA5/20 金叉死叉',
            'description': '快线5日均线上穿20日均线买入，下穿卖出',
            'params': {'signal_method': 'sma_cross', 'short_window': 5, 'long_window': 20},
        },
        {
            'id': 'sma_slow',
            'name': 'SMA10/30 慢速均线',
            'description': '较慢的均线组合，适合中线趋势跟踪',
            'params': {'signal_method': 'sma_cross', 'short_window': 10, 'long_window': 30},
        },
        {
            'id': 'rsi_default',
            'name': 'RSI 14 超买超卖',
            'description': 'RSI低于30超卖买入，高于70超买卖出',
            'params': {'signal_method': 'rsi', 'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70},
        },
        {
            'id': 'bb_default',
            'name': '布林带 20/2',
            'description': '价格触下轨买入，触上轨卖出',
            'params': {'signal_method': 'bb', 'bb_period': 20, 'bb_std': 2.0},
        },
        {
            'id': 'macd_trend',
            'name': 'MACD 趋势跟踪',
            'description': 'MACD金叉买入，死叉卖出',
            'params': {'signal_method': 'trend_follow'},
        },
        {
            'id': 'sma_ultra',
            'name': 'SMA3/10 超短线',
            'description': '超短线均线组合，适合高频测试',
            'params': {'signal_method': 'sma_cross', 'short_window': 3, 'long_window': 10},
        },
    ]

    return jsonify({
        'success': True,
        'data': templates,
        'total': len(templates),
    })
