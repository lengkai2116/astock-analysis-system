"""
"策略系统 API 路由
提供策略输出、模板管理、信号计算等功能"
"""
from flask import Blueprint, request, jsonify
from app import db
from app.services.strategy_output_service import StrategyOutputService
from app.services.strategy_template_service import StrategyTemplateService
from app.services.signal_computation_service import SignalComputationService
from app.utils.error_handlers import handle_exceptions
from datetime import datetime

strategy_bp = Blueprint('strategy', __name__, url_prefix='/api/v2/strategy')

# 信号计算服务（实时计算 fallback）
_signal_computer = None

def get_signal_computer():
    global _signal_computer
    if _signal_computer is None:
        _signal_computer = SignalComputationService()
    return _signal_computer


@strategy_bp.route('/outputs', methods=['GET'])
@handle_exceptions
def get_strategy_outputs():
    ts_code = request.args.get('ts_code')
    strategy_name = request.args.get('strategy_name')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    limit = int(request.args.get('limit', 10))

    if start_date:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if end_date:
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

    # 1️⃣ 先查数据库缓存
    outputs = StrategyOutputService.get_strategy_outputs(
        ts_code=ts_code,
        strategy_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )

    # 2️⃣ 如果数据库有缓存数据，直接返回
    if outputs:
        return jsonify({
            'success': True,
            'data': [o.to_dict() for o in outputs]
        })

    # 3️⃣ 数据库无缓存 → 实时计算
    if ts_code:
        computer = get_signal_computer()
        computed = computer.compute_for_stock(ts_code, limit=limit)
        if computed:
            return jsonify({
                'success': True,
                'data': computed,
                'computed': True  # 标记为实时计算
            })

    # 4️⃣ 兜底
    return jsonify({
        'success': True,
        'data': []
    })


@strategy_bp.route('/outputs', methods=['POST'])
@handle_exceptions
def create_strategy_output():
    data = request.json

    output = StrategyOutputService.create_strategy_output(
        ts_code=data.get('ts_code'),
        strategy_name=data.get('strategy_name'),
        signal=data.get('signal'),
        signal_date=datetime.strptime(data.get('signal_date'), '%Y-%m-%d').date(),
        confidence=data.get('confidence'),
        entry_zone=data.get('entry_zone'),
        risk_line=data.get('risk_line'),
        target_zone=data.get('target_zone'),
        position_suggestion=data.get('position_suggestion'),
        holding_period=data.get('holding_period'),
        evidence=data.get('evidence'),
        risk_notes=data.get('risk_notes')
    )

    return jsonify({
        'success': True,
        'data': output.to_dict()
    })


@strategy_bp.route('/outputs/<int:output_id>', methods=['DELETE'])
@handle_exceptions
def delete_strategy_output(output_id):
    success = StrategyOutputService.delete_strategy_output(output_id)
    return jsonify({
        'success': success,
        'message': '删除成功' if success else '删除失败'
    })


@strategy_bp.route('/outputs/latest', methods=['GET'])
@handle_exceptions
def get_latest_signal():
    ts_code = request.args.get('ts_code')
    if not ts_code:
        return jsonify({
            'success': False,
            'message': '缺少ts_code参数'
        }), 400

    # 先查 DB 缓存
    signal = StrategyOutputService.get_latest_signal(ts_code)
    if signal:
        return jsonify({
            'success': True,
            'data': signal.to_dict()
        })

    # 无缓存 → 实时计算
    computer = get_signal_computer()
    computed = computer.compute_for_stock(ts_code, limit=3)
    return jsonify({
        'success': True,
        'data': computed[0] if computed else None,
        'computed': True
    })




@strategy_bp.route('/match-check', methods=['POST'])
@handle_exceptions
def signal_match_check():
    """
    信号匹配度检查 — 账户管理系统复盘专用

    输入：用户交易记录列表
    POST body:
    {
        "trades": [
            {"ts_code": "600519.SH", "trade_date": "2026-05-20", "action": "BUY"},
            {"ts_code": "000001.SZ", "trade_date": "2026-05-22", "action": "SELL"}
        ]
    }

    输出：每笔交易的信号匹配度
    {
        "summary": {"total_trades": 2, "matched": 1, "match_rate": 0.5},
        "details": [
            {"ts_code": "600519.SH", "trade_date": "2026-05-20", "action": "BUY",
             "strategy_signal": "BULLISH", "confidence": 0.72, "matched": true,
             "reason": "买入操作与策略信号一致"},
            ...
        ]
    }
    """
    data = request.get_json()
    if not data or 'trades' not in data:
        return jsonify({'success': False, 'message': '缺少trades参数'}), 400

    trades = data['trades']
    if not isinstance(trades, list) or len(trades) == 0:
        return jsonify({'success': False, 'message': 'trades必须为非空列表'}), 400

    details = []
    matched_count = 0

    for trade in trades:
        ts_code = trade.get('ts_code', '')
        trade_date_str = trade.get('trade_date', '')
        action = trade.get('action', '').upper()

        if not ts_code or not trade_date_str or action not in ('BUY', 'SELL'):
            details.append({
                'ts_code': ts_code,
                'trade_date': trade_date_str,
                'action': action,
                'strategy_signal': None,
                'matched': False,
                'reason': '参数不完整或无效'
            })
            continue

        try:
            trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
        except ValueError:
            details.append({
                'ts_code': ts_code,
                'trade_date': trade_date_str,
                'action': action,
                'strategy_signal': None,
                'matched': False,
                'reason': '日期格式错误(需YYYY-MM-DD)'
            })
            continue

        # 查询当日策略信号（精确匹配 trade_date）
        # 先查数据库
        outputs = StrategyOutputService.get_strategy_outputs(
            ts_code=ts_code,
            start_date=trade_date,
            end_date=trade_date,
            limit=5
        )

        # 如果数据库无缓存，尝试实时计算
        if not outputs:
            computer = get_signal_computer()
            computed = computer.compute_for_stock(ts_code, limit=3)
            if computed:
                # 实时计算结果按日期匹配
                signals_for_date = []
                for s in computed:
                    sd = s.get('signal_date', '')
                    if sd == trade_date_str:
                        signals_for_date.append(s)

                # 判断信号是否匹配
                match_result = _process_trade_with_signals(
                    ts_code, trade_date_str, action,
                    signals_for_date, details
                )
                if match_result:
                    matched_count += 1
                continue
            else:
                details.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date_str,
                    'action': action,
                    'strategy_signal': None,
                    'matched': False,
                    'reason': '无可用策略信号（数据库与实时计算均为空）'
                })
                continue

        # 数据库有结果
        signals_for_date = [o.to_dict() for o in outputs]
        match_result = _process_trade_with_signals(
            ts_code, trade_date_str, action,
            signals_for_date, details
        )
        if match_result:
            matched_count += 1

    total = len(trades)
    return jsonify({
        'success': True,
        'data': {
            'summary': {
                'total_trades': total,
                'matched': matched_count,
                'match_rate': round(matched_count / total, 4) if total > 0 else 0,
            },
            'details': details
        }
    })


def _process_trade_with_signals(ts_code, trade_date_str, action,
                                  signals, details) -> bool:
    """处理单笔交易的信号匹配判断，返回是否匹配"""
    if not signals:
        details.append({
            'ts_code': ts_code,
            'trade_date': trade_date_str,
            'action': action,
            'strategy_signal': None,
            'matched': False,
            'reason': '当日无策略信号'
        })
        return False

    # 取最高置信度的信号
    best_signal = max(signals, key=lambda x: x.get('confidence', 0) or 0)
    sig_val = best_signal.get('signal', 'NEUTRAL')
    confidence = best_signal.get('confidence', 0)
    sig_name = best_signal.get('strategy_name', '未知策略')

    # 匹配规则：
    # 买入(BUY) 应与 BULLISH/WATCH 匹配
    # 卖出(SELL) 应与 BEARISH 匹配
    buy_signals = ('BULLISH', 'WATCH')
    sell_signals = ('BEARISH',)

    # 取最高置信度的信号
    best_signal = max(signals, key=lambda x: x.get('confidence', 0) or 0)
    sig_val = best_signal.get('signal', 'NEUTRAL')
    confidence = best_signal.get('confidence', 0)
    sig_name = best_signal.get('strategy_name', '未知策略')

    buy_signals = ('BULLISH', 'WATCH')
    sell_signals = ('BEARISH',)

    if action == 'BUY' and sig_val in buy_signals:
        matched = True
        reason = f"买入操作与{sig_name}信号一致({sig_val}, conf={confidence})"
    elif action == 'SELL' and sig_val in sell_signals:
        matched = True
        reason = f"卖出操作与{sig_name}信号一致({sig_val}, conf={confidence})"
    else:
        matched = False
        reason = f"操作{action}与策略信号{sig_val}不一致({sig_name})"

    details.append({
        'ts_code': ts_code,
        'trade_date': trade_date_str,
        'action': action,
        'strategy_signal': sig_val,
        'confidence': confidence,
        'strategy_name': sig_name,
        'matched': matched,
        'reason': reason,
    })
    return matched
# ── 策略模板 API（保持不变）──

@strategy_bp.route('/templates', methods=['GET'])
@handle_exceptions
def get_templates():
    template_type = request.args.get('template_type')
    is_system = request.args.get('is_system')

    if is_system is not None:
        is_system = is_system.lower() == 'true'

    templates = StrategyTemplateService.get_templates(
        template_type=template_type,
        is_system=is_system
    )

    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in templates]
    })


@strategy_bp.route('/templates', methods=['POST'])
@handle_exceptions
def create_template():
    data = request.json
    template = StrategyTemplateService.create_template(
        name=data.get('name'),
        description=data.get('description'),
        template_type=data.get('template_type', 'indicator'),
        code_template=data.get('code_template'),
        author=data.get('author')
    )
    return jsonify({
        'success': True,
        'data': template.to_dict()
    })


@strategy_bp.route('/templates/<int:template_id>', methods=['GET'])
@handle_exceptions
def get_template(template_id):
    template = StrategyTemplateService.get_template_by_id(template_id)
    if not template:
        return jsonify({
            'success': False,
            'message': '模板不存在'
        }), 404

    return jsonify({
        'success': True,
        'data': template.to_dict()
    })


@strategy_bp.route('/templates/<int:template_id>', methods=['PUT'])
@handle_exceptions
def update_template(template_id):
    data = request.json
    template = StrategyTemplateService.update_template(
        template_id=template_id,
        name=data.get('name'),
        description=data.get('description'),
        code_template=data.get('code_template'),
        is_active=data.get('is_active')
    )

    if not template:
        return jsonify({
            'success': False,
            'message': '模板不存在'
        }), 404

    return jsonify({
        'success': True,
        'data': template.to_dict()
    })


@strategy_bp.route('/templates/<int:template_id>', methods=['DELETE'])
@handle_exceptions
def delete_template(template_id):
    success = StrategyTemplateService.delete_template(template_id)
    return jsonify({
        'success': success,
        'message': '删除成功' if success else '删除失败'
    })


@strategy_bp.route('/templates/<int:template_id>/use', methods=['POST'])
@handle_exceptions
def use_template(template_id):
    StrategyTemplateService.increment_usage(template_id)
    return jsonify({
        'success': True,
        'message': '使用次数已更新'
    })
