"""
报告API路由 v3
迁移说明：v2→v3 路由前缀变更 + 报告类型枚举扩展(3→5种) + 新增POST写入端点
变更日期：2026-07-01
"""

from flask import Blueprint, request, jsonify, current_app
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
import logging

from app.services.ai_strategy_generator import AIStrategyGenerator
from app.services.report_generator import ReportGenerator
from app.services.research_pipeline import ResearchPipeline, create_research_pipeline
from app.utils.error_handlers import handle_exceptions

reports_bp = Blueprint('reports', __name__, url_prefix='/api/v3/reports')

logger = logging.getLogger(__name__)

# ── v3 报告类型枚举 ──
REPORT_TYPES_V3 = {
    'strategy': '策略存档',     # 原 single_stock
    'analysis': '分析报告',     # 原 research
    'backtest': '回测报告',     # 保留
    'diagnosis': '诊断报告',    # 新增
    'sandbox': '测试报告',      # 新增
}

REPORT_SOURCE_LABELS = {
    'indicator-ide': '个股策略分析',
    'ai-analysis': 'AI分析',
    'backtest': '回测系统',
    'playback': '复盘中心',
    'strategy-sandbox': '策略沙箱',
}

# v2→v3 类型映射（向后兼容）
_TYPE_MAP_V2_TO_V3 = {
    'single_stock': 'strategy',
    'research': 'analysis',
    'backtest': 'backtest',
}

TYPE_MAP_V3_TO_V2 = {v: k for k, v in _TYPE_MAP_V2_TO_V3.items()}


def _map_type_v3(type_v2_or_v3: str) -> str:
    """将 v2 类型名映射到 v3；如已是 v3 则原样返回"""
    if type_v2_or_v3 in REPORT_TYPES_V3:
        return type_v2_or_v3
    return _TYPE_MAP_V2_TO_V3.get(type_v2_or_v3, 'strategy')


def _map_type_v2(type_v3: str) -> str:
    """将 v3 类型名映射回 v2（用于 generate 端点兼容）"""
    return TYPE_MAP_V3_TO_V2.get(type_v3, type_v3)


# ── P8: 新增写入端点 ──
@reports_bp.route('', methods=['POST'])
@handle_exceptions
def create_report():
    """上游模块推送报告到报告中心的入口（P8）

    请求体同 proto review_report_data_{id} 结构。
    支持5种类型：strategy / analysis / backtest / diagnosis / sandbox
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '请求体为空'}), 400

    report_type = data.get('type', 'strategy')
    if report_type not in REPORT_TYPES_V3:
        return jsonify({
            'success': False,
            'error': f'不支持的报告类型: {report_type}'
        }), 400

    # 生成报告ID
    date_str = datetime.now().strftime('%Y%m%d')
    # 简单自增（每日期+1的文件扫描）
    metadata_dir = _get_metadata_dir()
    existing = [f for f in os.listdir(metadata_dir) if f.startswith(f'RP-{date_str}')]
    seq = len(existing) + 1
    report_id = f"RP-{date_str}-{seq:03d}"

    report = {
        'id': report_id,
        'type': report_type,
        'source': data.get('source', ''),
        'ts_code': data.get('ts_code', ''),
        'name': data.get('name', f'{REPORT_TYPES_V3.get(report_type, "报告")}'),
        'date': data.get('date', date_str),
        'generated_at': datetime.now().isoformat(),
        'strategy_label': data.get('strategy_label', ''),
        'total_score': data.get('total_score'),
        'pnl_pct': data.get('pnl_pct'),
        'summary': data.get('summary', ''),
        'downloaded': data.get('downloaded', False),
        'file_size': data.get('file_size'),
        'content': data.get('content', ''),
        'format': data.get('format', 'markdown'),
        # 类型特有数据（可选）
        'strategy': data.get('strategy'),
        'interpretation': data.get('interpretation'),
        'analysis_roles': data.get('analysis_roles'),
        'backtest': data.get('backtest'),
        'diagnosis': data.get('diagnosis'),
        'sandbox': data.get('sandbox'),
    }

    _save_report_metadata(report_id, report)

    return jsonify({
        'success': True,
        'data': {
            'id': report_id,
            'created_at': report['generated_at']
        }
    }), 201


def _get_metadata_dir() -> str:
    """获取报告元数据存储目录"""
    data_dir = os.getenv('DATA_DIR', os.getcwd())
    metadata_dir = os.path.join(data_dir, 'reports', 'metadata')
    os.makedirs(metadata_dir, exist_ok=True)
    return metadata_dir


def _save_report_metadata(report_id: str, result: Dict):
    """保存报告元数据"""
    try:
        metadata_dir = _get_metadata_dir()
        metadata_file = os.path.join(metadata_dir, f'{report_id}.json')
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"报告元数据已保存: {metadata_file}")
    except Exception as e:
        logger.warning(f"保存报告元数据失败: {str(e)}")


def _load_reports_list() -> List[Dict]:
    """加载报告列表（v3格式）"""
    reports = []
    metadata_dir = _get_metadata_dir()

    if not os.path.exists(metadata_dir):
        return reports

    for filename in sorted(os.listdir(metadata_dir), reverse=True):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(metadata_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                report_data = json.load(f)

            report_type = report_data.get('type', report_data.get('report_type', 'strategy'))
            report_type = _map_type_v3(report_type)

            reports.append({
                'id': report_data.get('id', report_data.get('report_id', filename[:-5])),
                'type': report_type,
                'source': report_data.get('source', ''),
                'ts_code': report_data.get('ts_code', ''),
                'name': report_data.get('name', report_data.get('title', '未命名报告')),
                'date': report_data.get('date', report_data.get('generated_at', '')[:10]),
                'generated_at': report_data.get('generated_at', ''),
                'strategy_label': report_data.get('strategy_label', ''),
                'total_score': report_data.get('total_score'),
                'pnl_pct': report_data.get('pnl_pct'),
                'summary': report_data.get('summary', ''),
                'downloaded': report_data.get('downloaded', False),
                'file_size': report_data.get('file_size'),
            })
        except Exception as e:
            logger.warning(f"读取报告文件失败 {filename}: {str(e)}")
            continue

    reports.sort(key=lambda x: x.get('generated_at', ''), reverse=True)
    return reports


# ── P1: GET /api/v3/reports — 报告列表 ──
@reports_bp.route('', methods=['GET'])
def get_reports_list():
    """
    获取报告列表（v3，支持5种类型 + 搜索）

    查询参数：
    - type: 类型筛选（strategy / analysis / backtest / diagnosis / sandbox）
    - ts_code: 股票代码筛选
    - search: 搜索关键词（匹配 name / ts_code / summary）
    - limit: 返回数量限制（默认20）
    - offset: 偏移量（默认0）
    """
    try:
        report_type = request.args.get('type')
        ts_code = request.args.get('ts_code')
        search = request.args.get('search')
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))

        reports = _load_reports_list()

        if report_type:
            reports = [r for r in reports if r.get('type') == report_type]

        if ts_code:
            reports = [r for r in reports if r.get('ts_code') == ts_code]

        if search:
            search_lower = search.lower()
            reports = [
                r for r in reports
                if search_lower in (r.get('name', '') + r.get('ts_code', '') + r.get('summary', '')).lower()
            ]

        total = len(reports)
        reports = reports[offset:offset + limit]

        return jsonify({
            'success': True,
            'data': {
                'reports': reports,
                'total': total,
                'limit': limit,
                'offset': offset
            }
        }), 200

    except Exception as e:
        logger.error(f"获取报告列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── P2: GET /api/v3/reports/{id} — 报告详情 ──
@reports_bp.route('/<report_id>', methods=['GET'])
def get_report_detail(report_id: str):
    """获取报告详情"""
    try:
        metadata_dir = _get_metadata_dir()
        metadata_file = os.path.join(metadata_dir, f'{report_id}.json')

        if not os.path.exists(metadata_file):
            return jsonify({'success': False, 'error': f'报告 {report_id} 不存在'}), 404

        with open(metadata_file, 'r', encoding='utf-8') as f:
            report_data = json.load(f)

        return jsonify({'success': True, 'data': report_data}), 200

    except Exception as e:
        logger.error(f"获取报告详情失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── P3: DELETE /api/v3/reports/{id} — 删除报告 ──
@reports_bp.route('/<report_id>', methods=['DELETE'])
def delete_report(report_id: str):
    """删除报告"""
    try:
        metadata_dir = _get_metadata_dir()
        metadata_file = os.path.join(metadata_dir, f'{report_id}.json')

        if not os.path.exists(metadata_file):
            return jsonify({'success': False, 'error': f'报告 {report_id} 不存在'}), 404

        os.remove(metadata_file)
        logger.info(f"报告已删除: {report_id}")

        return jsonify({'success': True, 'message': f'报告 {report_id} 已删除'}), 200

    except Exception as e:
        logger.error(f"删除报告失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── P4: POST /api/v3/reports/generate — 报告生成（上游模块使用） ──
@reports_bp.route('/generate', methods=['POST'])
async def generate_report():
    """
    生成报告接口（上游模块使用）

    支持 v3 类型映射：
    - strategy: 策略报告（原 single_stock）
    - backtest: 回测报告
    - analysis: 分析报告（原 research）
    """
    try:
        data = request.get_json()
        report_type_v2 = data.get('report_type', 'single_stock')
        report_type = _map_type_v3(report_type_v2)

        ts_code = data.get('ts_code', '600519.SH')
        description = data.get('description', '')
        start_date = data.get('start_date', '20250101')
        end_date = data.get('end_date', '20250501')
        output_format = data.get('format', 'markdown')

        logger.info(f"生成报告: type={report_type}, ts_code={ts_code}")

        if report_type == 'analysis':
            result = await _generate_research_report(data)
        elif report_type == 'backtest':
            result = await _generate_backtest_report(data)
        else:
            result = await _generate_single_stock_report(data)

        report_id = f"RP-{datetime.now().strftime('%Y%m%d')}-gen-{int(datetime.now().timestamp())}"
        result['id'] = report_id
        result['type'] = report_type
        result['generated_at'] = datetime.now().isoformat()

        _save_report_metadata(report_id, result)

        return jsonify({'success': True, 'data': result}), 200

    except Exception as e:
        logger.error(f"报告生成失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── P5: GET /api/v3/reports/formats — 格式列表 ──
@reports_bp.route('/formats', methods=['GET'])
def get_supported_formats():
    """获取支持的报告格式和类型"""
    return jsonify({
        'success': True,
        'data': {
            'formats': [
                {'value': 'markdown', 'label': 'Markdown', 'description': '纯文本格式，适合文档和笔记', 'file_extension': '.md'},
                {'value': 'html', 'label': 'HTML', 'description': '网页格式，适合在线查看', 'file_extension': '.html'},
                {'value': 'json', 'label': 'JSON', 'description': 'JSON格式，适合程序处理', 'file_extension': '.json'},
            ],
            'report_types': [
                {'value': k, 'label': v, 'description': f'{v}报告'} for k, v in REPORT_TYPES_V3.items()
            ],
            'sources': [
                {'value': k, 'label': v} for k, v in REPORT_SOURCE_LABELS.items()
            ]
        }
    }), 200


# ── P6: GET /api/v3/reports/health — 健康检查 ──
@reports_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'components': {
            'ai_generator': 'available',
            'report_generator': 'available',
            'research_pipeline': 'available'
        }
    }), 200


# ── P7: GET /api/v3/reports/weekly — 周度报告 ──
@reports_bp.route('/weekly', methods=['GET'])
@handle_exceptions
def get_weekly_report():
    """获取最新周度策略验证报告"""
    from app.services.weekly_report_service import WeeklyReportService
    service = WeeklyReportService()
    reports = service.list_recent_reports(limit=1)
    fmt = request.args.get('format', 'markdown')

    if not reports:
        return jsonify({
            'success': True, 'data': None,
            'message': '暂无周度报告，系统将在周末首次生成'
        }), 200

    latest = reports[0]
    content = service.read_report(latest)
    if content is None:
        return jsonify({'success': False, 'error': '报告文件读取失败'}), 500

    if fmt == 'json':
        import re
        match = re.search(r'报告周期: (.+?) ~ (.+)', content)
        period = {'start': match.group(1), 'end': match.group(2)} if match else {}
        return jsonify({
            'success': True, 'data': {
                'filepath': latest, 'filename': os.path.basename(latest),
                'content': content, 'period': period,
            }
        }), 200

    from flask import Response
    return Response(
        content,
        mimetype='text/markdown; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{os.path.basename(latest)}"'}
    )


# ── 以下为各类型报告生成辅助方法（保持不变） ──

async def _generate_single_stock_report(data: Dict) -> Dict:
    """生成单股票策略报告"""
    generator = AIStrategyGenerator()
    stock_data = {
        'ts_code': data.get('ts_code', '600519.SH'),
        'name': data.get('stock_name', '未知股票'),
        'start_date': data.get('start_date', '20250101'),
        'end_date': data.get('end_date', '20250501')
    }
    description = data.get('description', '基于移动平均线的策略')
    strategy_result = generator.generate_indicator_from_description(
        description=description,
        context={
            'ts_code': stock_data['ts_code'],
            'start_date': stock_data['start_date'],
            'end_date': stock_data['end_date']
        }
    )
    report_generator = ReportGenerator()
    output_format = data.get('format', 'markdown')
    if output_format == 'json':
        report_content = json.dumps({
            'stock_data': stock_data, 'strategy_data': strategy_result
        }, ensure_ascii=False, indent=2)
    else:
        report_content = report_generator.generate_single_stock_report(
            stock_data=stock_data, strategy_data=strategy_result, format=output_format)
    return {
        'title': f"{stock_data['name']} ({stock_data['ts_code']}) 策略分析报告",
        'ts_code': stock_data['ts_code'], 'stock_name': stock_data['name'],
        'strategy': strategy_result, 'content': report_content,
        'format': output_format, 'summary': strategy_result.get('description', '')
    }


async def _generate_backtest_report(data: Dict) -> Dict:
    """生成回测报告"""
    generator = AIStrategyGenerator()
    description = data.get('description', '基于移动平均线的策略')
    strategy_result = generator.generate_indicator_from_description(description=description)
    backtest_result = _mock_backtest_result(data)
    interpretation = generator.interpret_backtest_result(
        backtest_result=backtest_result, strategy_description=description)
    report_generator = ReportGenerator()
    output_format = data.get('format', 'markdown')
    report_content = report_generator.generate_backtest_report(
        backtest_result=backtest_result, interpretation=interpretation, format=output_format)
    return {
        'title': '量化策略回测报告', 'ts_code': data.get('ts_code', '600519.SH'),
        'strategy': strategy_result, 'backtest': backtest_result,
        'interpretation': interpretation, 'content': report_content,
        'format': output_format, 'summary': interpretation.get('summary', ''),
        'overall_score': interpretation.get('overall_score', 0),
        'risk_level': interpretation.get('risk_level', '未知')
    }


async def _generate_research_report(data: Dict) -> Dict:
    """生成完整研究报告"""
    logger.info("启动研究流水线...")
    pipeline = create_research_pipeline({'llm': {}, 'continue_on_error': False})
    request_data = {
        'description': data.get('description', '基于移动平均线的策略'),
        'ts_code': data.get('ts_code', '600519.SH'),
        'start_date': data.get('start_date', '20250101'),
        'end_date': data.get('end_date', '20250501'),
        'initial_capital': data.get('initial_capital', 100000),
        'parameters': data.get('parameters', {})
    }
    pipeline_result = await pipeline.execute(request_data)
    if not pipeline_result.success:
        raise RuntimeError(f"流水线执行失败: {pipeline_result.error}")
    context = {
        'pipeline_id': pipeline_result.pipeline_id,
        'validated_input': pipeline_result.get_step('user_input').result if pipeline_result.get_step('user_input') else {},
        'generated_strategy': pipeline_result.get_step('ai_generation').result if pipeline_result.get_step('ai_generation') else {},
        'quality_check': pipeline_result.get_step('quality_check').result if pipeline_result.get_step('quality_check') else {},
        'backtest_result': pipeline_result.get_step('backtest_validation').result if pipeline_result.get_step('backtest_validation') else {},
        'interpretation': pipeline_result.get_step('ai_interpretation').result if pipeline_result.get_step('ai_interpretation') else {}
    }
    report_generator = ReportGenerator()
    output_format = data.get('format', 'markdown')
    report_data = report_generator.generate_research_report(context, format=output_format)
    return {
        'title': report_data.get('title', '量化研究分析报告'),
        'ts_code': data.get('ts_code', '600519.SH'),
        'sections': report_data.get('sections', []),
        'content': report_data.get('content', ''),
        'format': output_format,
        'pipeline_id': pipeline_result.pipeline_id,
        'pipeline_status': pipeline_result.status.value,
        'execution_time': pipeline_result.duration,
        'steps': [step.to_dict() for step in pipeline_result.steps],
        'interpretation': context['interpretation'],
        'summary': context['interpretation'].get('summary', ''),
        'overall_score': context['interpretation'].get('overall_score', 0),
        'risk_level': context['interpretation'].get('risk_level', '未知')
    }


def _mock_backtest_result(data: Dict) -> Dict:
    """生成模拟回测结果（仅供开发/原型测试使用 — 生产环境不得调用）"""
    import random
    total_return = random.uniform(-0.1, 0.3)
    sharpe_ratio = random.uniform(0.5, 2.0)
    max_drawdown = random.uniform(-0.05, -0.2)
    win_rate = random.uniform(0.4, 0.7)
    return {
        'ts_code': data.get('ts_code', '600519.SH'),
        'start_date': data.get('start_date', '20250101'),
        'end_date': data.get('end_date', '20250501'),
        'config': {'initial_capital': data.get('initial_capital', 100000),
                   'commission_rate': 0.0003, 'stamp_duty_rate': 0.001, 'slippage_rate': 0.0001},
        'metrics': {
            'initial_capital': data.get('initial_capital', 100000),
            'final_value': data.get('initial_capital', 100000) * (1 + total_return),
            'total_return': total_return, 'annual_return': total_return * 1.5,
            'sharpe_ratio': sharpe_ratio, 'sortino_ratio': sharpe_ratio * 1.2,
            'max_drawdown': max_drawdown, 'volatility': abs(max_drawdown) * 2,
            'win_rate': win_rate, 'profit_loss_ratio': 1.5,
            'total_trades': random.randint(10, 50)
        },
        'trades': [], 'daily_equity': []
    }


# ── 旧端点策略生成/解读保持可用（报告中心前端不使用） ──
@reports_bp.route('/strategy/generate', methods=['POST'])
def generate_strategy_from_description():
    """从描述生成策略接口"""
    try:
        data = request.get_json()
        description = data.get('description', '')
        if not description:
            return jsonify({'success': False, 'error': '策略描述不能为空'}), 400
        generator = AIStrategyGenerator()
        result = generator.generate_indicator_from_description(
            description=description, context=data.get('context', {}))
        return jsonify({'success': True, 'data': result}), 200
    except Exception as e:
        logger.error(f"策略生成失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@reports_bp.route('/backtest/interpret', methods=['POST'])
def interpret_backtest_result():
    """AI解读回测结果接口"""
    try:
        data = request.get_json()
        backtest_result = data.get('backtest_result', {})
        strategy_description = data.get('strategy_description', '')
        if not backtest_result:
            return jsonify({'success': False, 'error': '回测结果不能为空'}), 400
        generator = AIStrategyGenerator()
        result = generator.interpret_backtest_result(
            backtest_result=backtest_result, strategy_description=strategy_description)
        return jsonify({'success': True, 'data': result}), 200
    except Exception as e:
        logger.error(f"回测结果解读失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
