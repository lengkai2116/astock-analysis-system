"""
DeepSeek 多角色投研分析服务
5个角色平行分析，最终合成报告
"""

import os
import json
import time
import threading
import logging
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)
# [153] AI上下文注入 + 结构化解析
from app.services.ai_context_builder import ai_context_builder, ai_structured_parser, ai_signal_bus


# 内存存储：analysis_id -> 分析状态
_analysis_store: Dict[str, Dict] = {}
_lock = threading.Lock()

ANALYST_ROLES = [
    {
        'id': 'technical',
        'name': '技术分析师',
        'icon': '📈',
        'role_prompt': (
            '你是一名经验丰富的A股技术分析师。请基于以下股票数据，从技术面角度进行分析。\n'
            '分析要点：趋势判断（均线、通道）、支撑压力位、成交量分析、技术指标（MACD/RSI/KDJ）、K线形态。\n'
            '请给出明确的看多/看空倾向（百分比）和关键价位判断。'
        )
    },
    {
        'id': 'fundamental',
        'name': '基本面分析师',
        'icon': '📊',
        'role_prompt': (
            '你是一名A股基本面分析师。请基于以下股票信息进行基本面分析。\n'
            '分析要点：财务健康度、估值水平（PE/PB/PS）、成长性、行业地位、竞争优势、ROE、现金流。\n'
            '请给出明确的看多/看空倾向（百分比）。'
        )
    },
    {
        'id': 'macro',
        'name': '宏观策略师',
        'icon': '🌐',
        'role_prompt': (
            '你是一名A股宏观策略师。请基于以下股票和当前市场环境进行分析。\n'
            '分析要点：宏观经济周期、行业政策、市场情绪、资金流向、北向资金流向、板块轮动。\n'
            '请给出明确的看多/看空倾向（百分比）。'
        )
    },
    {
        'id': 'risk',
        'name': '风险控制官',
        'icon': '⚠️',
        'role_prompt': (
            '你是一名A股风控官。请从风控角度评估该股票的投资风险。\n'
            '评估要点：市场风险、流动性风险、个股风险（质押/减持/监管）、波动率风险、回撤风险。\n'
            '请给出明确的风险等级判断和止损建议。'
        )
    },
    {
        'id': 'fund_manager',
        'name': '资深基金经理',
        'icon': '👨‍💼',
        'role_prompt': (
            '你是一名拥有20年经验的A股基金经理。请综合所有分析师的判断，给出最终投资建议。\n'
            '请综合评定：总体评级（STRONGLY_BUY/BUY/HOLD/SELL/STRONGLY_SELL）、\n'
            '目标价位区间、建议仓位（百分比）、止损价位。\n'
            '要求观点明确、可执行，不要让用户感到模棱两可。'
        )
    }
]


def _call_deepseek(prompt: str, system_prompt: str, config: Dict) -> Optional[str]:
    """调用 DeepSeek API"""
    import requests

    api_key = config.get('api_key', '')
    endpoint = config.get('endpoint', 'https://api.deepseek.com/v1')
    model = config.get('model', 'deepseek-chat-v4')
    provider = config.get('type', 'mock')

    if provider == 'mock' or not api_key:
        return None  # caller will handle mock fallback

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.7,
        'max_tokens': 2048
    }

    try:
        resp = requests.post(
            f'{endpoint}/chat/completions',
            headers=headers,
            json=payload,
            timeout=120
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        else:
            logger.error(f'DeepSeek API error: {resp.status_code} {resp.text}')
            return None
    except Exception as e:
        logger.error(f'DeepSeek call failed: {e}')
        return None


def _parse_analyst_report(text: str, role_id: str) -> Dict:
    """解析分析师返回的文本为结构化数据"""
    # [153-P0-2] 优先尝试JSON结构化解析
    parsed = ai_structured_parser.parse_json(text)
    if parsed and ai_structured_parser.validate_schema(parsed, role_id):
        direction = parsed.get('direction', 'neutral')
        confidence = parsed.get('confidence', 50)
        bullish = confidence if direction == 'bullish' else (100 - confidence if direction == 'bearish' else 50)
        bearish = 100 - bullish
        return {
            'role_id': role_id,
            'structured': parsed,
            'raw': text[:2000],
            'bullishScore': bullish,
            'bearishScore': bearish,
            'evidence': parsed.get('evidence', []),
            'risk_notes': parsed.get('risk_notes', []),
            'conclusion': parsed.get('conclusion', ''),
        }

    # 回退到正则解析
    bullish = 50
    bearish = 50

    import re
    m = re.search(r'(?:看多|Bullish|bullish)\s*[:：]?\s*(\d+)%?', text, re.IGNORECASE)
    if m:
        bullish = min(100, max(0, int(m.group(1))))

    m = re.search(r'(?:看空|Bearish|bearish)\s*[:：]?\s*(\d+)%?', text, re.IGNORECASE)
    if m:
        bearish = min(100, max(0, int(m.group(1))))

    if bearish + bullish == 0:
        bullish = bearish = 50

    return {
        'role_id': role_id,
        'raw': text[:2000],
        'bullishScore': bullish,
        'bearishScore': bearish
    }


def _parse_final_report(text: str) -> Dict:
    """解析最终基金经理报告"""
    import re

    report = {
        'overallRating': 'HOLD',
        'targetPriceRange': {'min': 0, 'max': 0},
        'stopLoss': 0,
        'suggestedPosition': 0.2,
        'summary': text[:1000],
        'sections': []
    }

    # Rating
    rating_map = {
        'STRONGLY_BUY': 'STRONGLY_BUY', '强烈看多': 'STRONGLY_BUY',
        'BUY': 'BUY', '看多': 'BUY',
        'HOLD': 'HOLD', '中性': 'HOLD', '持有': 'HOLD',
        'SELL': 'SELL', '看空': 'SELL',
        'STRONGLY_SELL': 'STRONGLY_SELL', '强烈看空': 'STRONGLY_SELL'
    }
    for k, v in rating_map.items():
        if k in text:
            report['overallRating'] = v
            break

    # Target price range
    m = re.search(r'(?:目标价[位格]?|target)\s*[:：]?\s*(\d+\.?\d*)\s*[-~]\s*(\d+\.?\d*)', text)
    if m:
        report['targetPriceRange'] = {'min': float(m.group(1)), 'max': float(m.group(2))}

    # Stop loss
    m = re.search(r'(?:止损|stop\s*loss)\s*[:：]?\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if m:
        report['stopLoss'] = float(m.group(1))

    # Position
    m = re.search(r'(?:仓位|position)\s*[:：]?\s*(\d+)%', text)
    if m:
        report['suggestedPosition'] = min(1.0, max(0, int(m.group(1)) / 100))

    return report


def _mock_analyst_report(role_id: str, ts_code: str) -> Dict:
    """Mock 分析结果（当 DeepSeek 不可用时）"""
    mock_data = {
        'technical': {
            'bullishScore': 65,
            'bearishScore': 35,
            'raw': (
                f'【技术分析】{ts_code} 当前处于上升通道中。'
                'MACD指标出现金叉信号，RSI处于51中性区间，KDJ三线向上发散。'
                '成交量温和放大，20日均线支撑有效。短线看好反弹延续，中线趋势偏多。'
            )
        },
        'fundamental': {
            'bullishScore': 55,
            'bearishScore': 45,
            'raw': (
                f'【基本面分析】{ts_code} 业绩稳健增长，ROE保持在15%以上。'
                '当前PE处于行业中等水平，估值合理。资产负债率适中，现金流充裕。'
                '行业龙头地位稳固，但需关注行业增速放缓风险。'
            )
        },
        'macro': {
            'bullishScore': 60,
            'bearishScore': 40,
            'raw': (
                f'【宏观分析】{ts_code} 所属行业受益于政策支持。'
                '北向资金近期持续流入该板块，市场情绪偏乐观。'
                '宏观经济处于复苏期，流动性合理充裕，利于权益资产表现。'
            )
        },
        'risk': {
            'bullishScore': 40,
            'bearishScore': 60,
            'raw': (
                f'【风控分析】{ts_code} 主要风险包括：市场波动加剧、'
                '行业竞争加剧导致利润率下滑、大股东减持风险。'
                '建议设置8%止损线，仓位控制在20%以内。'
            )
        },
        'fund_manager': None  # 由分析服务合成
    }
    return mock_data.get(role_id, {
        'bullishScore': 50,
        'bearishScore': 50,
        'raw': f'【{role_id}分析】正在分析{ts_code}...'
    })


def _run_analysis_job(analysis_id: str, ts_code: str, stock_name: str, config: Dict):
    """后台运行完整的分析流程"""
    provider = config.get('type', 'mock')
    has_api = provider == 'deepseek' and config.get('api_key', '')

    try:
        # 获取股票数据（简化为基本信息）
        stock_info = f"股票代码: {ts_code}, 名称: {stock_name}"

        # 逐步分析5个角色
        analyst_results = {}
        for idx, role in enumerate(ANALYST_ROLES):
            role_id = role['id']
            with _lock:
                if analysis_id in _analysis_store:
                    _analysis_store[analysis_id]['current_role'] = role_id
                    _analysis_store[analysis_id]['progress'] = 15 + idx * 17
                    _analysis_store[analysis_id]['progress_text'] = f'{role["name"]}分析中...'

            # 调用 DeepSeek 或 fallback 到 Mock
            report_text = None
            if has_api:
                prompt = (
                    f'请对{stock_name}({ts_code})进行股票分析。\n\n'
                    f'当前时间：{datetime.now().strftime("%Y-%m-%d")}\n\n'
                    f'请从{role["name"]}的角度进行分析，给出看多/看空百分比。'
                )
                # [153-P0-1] 多层上下文注入
            context = ai_context_builder.build_context(ts_code)
            context_section = ai_context_builder.to_prompt_section(context)
            enriched_prompt = prompt + '\n\n' + context_section
            report_text = _call_deepseek(enriched_prompt, role['role_prompt'], config)

            if report_text:
                report = _parse_analyst_report(report_text, role_id)
            else:
                report = _mock_analyst_report(role_id, ts_code)
                report['role_id'] = role_id

            analyst_results[role_id] = report

            # 更新进度
            with _lock:
                if analysis_id in _analysis_store:
                    _analysis_store[analysis_id]['analysts'][role_id] = report
                    _analysis_store[analysis_id]['progress'] = 15 + (idx + 1) * 17
                    _analysis_store[analysis_id]['logs'].append({
                        'role': role_id,
                        'icon': role['icon'],
                        'content': f'{role["name"]}分析完成',
                        'timestamp': datetime.now().isoformat()
                    })

        # 第5步：基金经理合成报告
        with _lock:
            if analysis_id in _analysis_store:
                _analysis_store[analysis_id]['progress'] = 95
                _analysis_store[analysis_id]['progress_text'] = '生成最终报告...'

        # 生成最终报告
        fund_manager_role = ANALYST_ROLES[4]
        final_report_text = None
        if has_api:
            # 把前面4个分析结果给基金经理做综合
            summaries = []
            for rid in ['technical', 'fundamental', 'macro', 'risk']:
                r = analyst_results.get(rid, {})
                summaries.append(f'{rid}: 看多{r.get("bullishScore", 50)}%/看空{r.get("bearishScore", 50)}%')

            # [153-P0-1] 基金经理也接收上下文
            context = ai_context_builder.build_context(ts_code)
            context_section = ai_context_builder.to_prompt_section(context)
            prompt = (
                f'请对{stock_name}({ts_code})给出最终投资建议。\n\n'
                f'各分析师评分：\n' + '\n'.join(summaries) + '\n\n'
                '请给出：总体评级、目标价位区间、建议仓位、止损价位、详细理由。\n\n'
                + context_section
            )
            final_report_text = _call_deepseek(prompt, fund_manager_role['role_prompt'], config)

        if final_report_text:
            final_report = _parse_final_report(final_report_text)
        else:
            # Mock 最终报告
            final_report = {
                'overallRating': 'BUY',
                'targetPriceRange': {'min': 0, 'max': 0},
                'stopLoss': 0,
                'suggestedPosition': 0.2,
                'summary': (
                    f'综合来看，{stock_name}({ts_code})当前具有一定投资价值。'
                    '技术面信号向好，基本面稳健，宏观环境偏利好。'
                    '建议轻仓配置，注意控制风险，设置合理止损位。'
                ),
                'sections': [
                    {'title': '📈 技术面', 'content': analyst_results.get('technical', {}).get('raw', '')[:300]},
                    {'title': '📊 基本面', 'content': analyst_results.get('fundamental', {}).get('raw', '')[:300]},
                    {'title': '🌐 宏观面', 'content': analyst_results.get('macro', {}).get('raw', '')[:300]},
                    {'title': '⚠️ 风险提示', 'content': analyst_results.get('risk', {}).get('raw', '')[:300]}
                ]
            }

        with _lock:
            if analysis_id in _analysis_store:
                store = _analysis_store[analysis_id]
                store['final_report'] = final_report
                store['status'] = 'completed'
                store['progress'] = 100
                store['progress_text'] = '分析完成！'
                store['analysts']['fund_manager'] = {
                    'role_id': 'fund_manager',
                    'bullishScore': 60,
                    'bearishScore': 40,
                    'raw': final_report.get('summary', '')
                }
                store['analysts_report'] = store['analysts']
                store['logs'].append({
                    'role': '',
                    'icon': '✅',
                    'content': '分析完成！',
                    'timestamp': datetime.now().isoformat()
                })

    except Exception as e:
        logger.error(f'Analysis job failed: {e}', exc_info=True)
        with _lock:
            if analysis_id in _analysis_store:
                _analysis_store[analysis_id]['status'] = 'failed'
                _analysis_store[analysis_id]['error'] = str(e)


def start_analysis(ts_code: str, stock_name: str) -> str:
    """启动异步分析，返回 analysis_id"""
    from app.config import Config

    analysis_id = f'ana_{int(time.time())}'
    config = Config.get_llm_config()

    store = {
        'analysis_id': analysis_id,
        'ts_code': ts_code,
        'stock_name': stock_name,
        'status': 'running',
        'progress': 5,
        'progress_text': '准备中...',
        'current_role': '',
        'analysts': {},
        'final_report': None,
        'logs': [
            {'role': '', 'icon': '🚀', 'content': f'开始分析 {ts_code}...', 'timestamp': datetime.now().isoformat()}
        ],
        'created_at': datetime.now().isoformat()
    }

    with _lock:
        _analysis_store[analysis_id] = store

    # 启动后台线程
    thread = threading.Thread(
        target=_run_analysis_job,
        args=(analysis_id, ts_code, stock_name, config),
        daemon=True
    )
    thread.start()

    return analysis_id


def get_progress(analysis_id: str) -> Optional[Dict]:
    """获取分析进度"""
    with _lock:
        store = _analysis_store.get(analysis_id)
        if not store:
            return None
        return {
            'status': store['status'],
            'progress': store['progress'],
            'progress_text': store['progress_text'],
            'current_role': store.get('current_role', ''),
            'logs': store.get('logs', []),
            'analysts': store.get('analysts', {}),
            'has_report': store.get('final_report') is not None
        }


def get_final_report(analysis_id: str) -> Optional[Dict]:
    """获取最终报告"""
    with _lock:
        store = _analysis_store.get(analysis_id)
        if not store or not store.get('final_report'):
            return None
        return {
            'analysis_id': analysis_id,
            'ts_code': store['ts_code'],
            'stock_name': store['stock_name'],
            'report': store['final_report'],
            'analysts': store.get('analysts', {}),
            'logs': store.get('logs', []),
            'created_at': store['created_at']
        }


def get_health() -> Dict:
    """获取服务健康状态"""
    from app.config import Config
    config = Config.get_llm_config()
    provider = config.get('type', 'mock')
    has_key = bool(config.get('api_key', ''))
    return {
        'provider': provider,
        'configured': provider != 'mock' and has_key,
        'model': config.get('model', 'mock'),
        'active_analyses': len(_analysis_store)
    }


def interpret_status(ts_code: str, stock_name: str, aggregated_status: Dict) -> Dict:
    """
    根据 StatusOutputService 聚合的现状数据生成 AI 解读建议

    Args:
        ts_code: 股票代码
        stock_name: 股票名称
        aggregated_status: StatusOutputService.aggregate() 的输出，包含:
            state_consensus, risk_aggregation, momentum_consensus, key_levels,
            strategy_count, strategies_detail

    Returns:
        {
            "operation_plan": "...",
            "entry_zone": "...",
            "stop_loss": "...",
            "target": "...",
            "risk_notes": [...],
            "status_summary": "..."
        }
    """
    from app.config import Config

    config = Config.get_llm_config()
    provider = config.get('type', 'mock')
    has_api = provider in ('deepseek', 'lm_studio') and config.get('api_key', '')

    # 从 aggregated_status 中提取关键信息
    state_consensus = aggregated_status.get('state_consensus', {})
    risk_aggregation = aggregated_status.get('risk_aggregation', {})
    momentum_consensus = aggregated_status.get('momentum_consensus', {})
    key_levels = aggregated_status.get('key_levels', {})
    strategies_detail = aggregated_status.get('strategies_detail', [])

    state_label = state_consensus.get('state', 'UNKNOWN')
    state_pct = state_consensus.get('consensus_pct', 0.0)
    risk_level = risk_aggregation.get('risk_level', 'MEDIUM')
    momentum_label = momentum_consensus.get('momentum', 'NEUTRAL')

    # 尝试从 strategies_detail 或其他字段获取最新收盘价
    latest_close = None
    for sd in strategies_detail:
        signals = sd.get('signals', sd.get('signal', []))
        if isinstance(signals, list):
            for sig in signals:
                if isinstance(sig, dict) and sig.get('close'):
                    latest_close = float(sig['close'])
                    break
        if latest_close:
            break

    # 尝试从 key_levels 提取价格信息
    if latest_close is None and key_levels:
        support = key_levels.get('support_levels', [])
        if support and isinstance(support, list) and len(support) > 0:
            if isinstance(support[0], dict) and 'level' in support[0]:
                latest_close = float(support[0]['level'])
            else:
                latest_close = float(support[0])
        resistance = key_levels.get('resistance_levels', [])
        if latest_close is None and resistance and isinstance(resistance, list) and len(resistance) > 0:
            if isinstance(resistance[0], dict) and 'level' in resistance[0]:
                latest_close = float(resistance[0]['level'])
            else:
                latest_close = float(resistance[0])

    # Mock 降级时使用默认的价格假设
    if latest_close is None:
        latest_close = 100.0  # 兜底值

    if has_api:
        # 构建状态描述文本
        state_desc = (
            f"股票: {stock_name}({ts_code})\n"
            f"状态共识: {state_label} (共识度: {state_pct*100:.1f}%)\n"
            f"风险等级: {risk_level}\n"
            f"动量共识: {momentum_label}\n"
        )

        if key_levels:
            supports = key_levels.get('support_levels', [])
            resistances = key_levels.get('resistance_levels', [])
            if supports:
                state_desc += f"支撑位: {supports}\n"
            if resistances:
                state_desc += f"压力位: {resistances}\n"

        # 策略详细信息摘要
        detail_lines = []
        for sd in strategies_detail[:5]:
            name = sd.get('strategy_name', sd.get('name', '未知策略'))
            status = sd.get('status_recognition', {})
            s = status.get('state', 'N/A') if isinstance(status, dict) else 'N/A'
            detail_lines.append(f"  - {name}: {s}")
        if detail_lines:
            state_desc += "各策略状态:\n" + '\n'.join(detail_lines)

        prompt = (
            f"以下是股票 {stock_name}({ts_code}) 的多维现状聚合数据。\n"
            f"请根据这些数据，生成一份通俗易懂的中文操作建议。\n\n"
            f"{state_desc}\n\n"
            f"请严格按照以下 JSON 格式返回（不要包含其他内容）：\n"
            f'{{"operation_plan": "操作计划（一段话描述当前应该做什么）", '
            f'"entry_zone": "建议入场区间（如 98.50-102.00）", '
            f'"stop_loss": "建议止损价位", '
            f'"target": "建议目标价位", '
            f'"risk_notes": ["风险提示1", "风险提示2"], '
            f'"status_summary": "一句话总结当前股票状态"}}'
        )
        system_prompt = (
            "你是一名专业的A股投资分析师，擅长将多维量化信号转化为清晰可执行的操作建议。"
            "请基于提供的现状数据给出客观分析，不夸大风险也不遗漏机会。"
            "输出严格按要求的 JSON 格式。"
        )
        result_text = _call_deepseek(prompt, system_prompt, config)
        if result_text:
            try:
                import re
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"状态解读 JSON 解析失败: {e}")

    # Mock 降级响应
    return {
        "operation_plan": "建议观望，等待趋势明朗",
        "entry_zone": f"{latest_close*0.97:.2f}-{latest_close*1.03:.2f}",
        "stop_loss": f"{latest_close*0.92:.2f}",
        "target": f"{latest_close*1.12:.2f}",
        "risk_notes": ["市场存在不确定性"],
        "status_summary": f"{stock_name}({ts_code})当前{state_label}"
    }


def explain_signal(ts_code: str, stock_name: str, signals: List[Dict]) -> Dict:
    """
    根据信号维度数据生成 AI 解读文本
    接收前端传来的信号列表，返回每个策略的 AI 解读 + 综合建议
    """
    from app.config import Config

    config = Config.get_llm_config()
    provider = config.get('type', 'mock')
    has_api = provider in ('deepseek', 'lm_studio') and config.get('api_key', '')

    # 构建策略维度摘要
    strategy_lines = []
    for sig in signals:
        name = sig.get('strategy_name', '未知策略')
        conf_pct = round((sig.get('confidence', 0) or 0) * 100)
        direction = sig.get('signal_label', sig.get('signal', '中性'))
        lines = [f"策略: {name}", f"评分: {conf_pct}%", f"方向: {direction}"]

        # 提取证据
        evidence = sig.get('evidence', [])
        if evidence:
            lines.append("依据: " + '; '.join(evidence[:3]))

        # 提取价格信息
        entry = sig.get('entry_zone')
        if entry and isinstance(entry, (list, tuple)) and len(entry) == 2:
            lines.append(f"入场: {entry[0]} - {entry[1]}")
        risk = sig.get('risk_line')
        if risk:
            lines.append(f"止损: {risk}")
        target = sig.get('target_zone')
        if target and isinstance(target, (list, tuple)) and len(target) == 2:
            lines.append(f"目标: {target[0]} - {target[1]}")

        # 风险提示
        risks = sig.get('risk_notes', [])
        if risks:
            lines.append("风险: " + '; '.join(risks))

        strategy_lines.append('\n'.join(lines))

    strategy_text = '\n---\n'.join(strategy_lines)

    if has_api:
        prompt = (
            f"以下是股票 {stock_name}({ts_code}) 的多维策略信号数据。"
            f"请为每个策略生成一段通俗易懂的中文AI解读（约100-150字），"
            f"解释信号背后的逻辑和操作建议，并最后给出综合投资建议。\n\n"
            f"{strategy_text}\n\n"
            f"请严格按照以下 JSON 格式返回（不要包含其他内容）：\n"
            f'{{"explanations": [{{"strategy": "策略名称", "ai_summary": "解读文本", "ai_advice": "操作建议", "risk_tip": "风险提示"}}], "composite_advice": "综合投资建议"}}'
        )
        system_prompt = (
            "你是一名专业的 A 股投资分析师，擅长将量化信号转化为通俗易懂的解读。"
            "请基于信号数据给出客观分析，不夸大风险也不遗漏机会。"
            "输出严格按要求的 JSON 格式，确保每个策略的解读清晰且可执行。"
        )
        result_text = _call_deepseek(prompt, system_prompt, config)
        if result_text:
            try:
                import re
                # 尝试提取 JSON
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"信号解读 JSON 解析失败: {e}")

    # Mock 降级
    return _mock_signal_explain(ts_code, stock_name, signals)


def _mock_signal_explain(ts_code: str, stock_name: str, signals: List[Dict]) -> Dict:
    """当 DeepSeek 不可用时，基于规则生成解读文本"""
    explanations = []
    total_conf = 0

    for sig in signals:
        name = sig.get('strategy_name', '未知策略')
        conf = sig.get('confidence', 0) or 0
        conf_pct = round(conf * 100)
        direction = sig.get('signal_label', sig.get('signal', '中性'))
        evidence = sig.get('evidence', [])

        total_conf += conf

        if name == '筹码主力分析':
            summary = (
                f"筹码集中度评估为 {conf_pct}%。"
                f"{'主力资金控盘迹象明显，' if conf_pct >= 60 else '主力资金介入程度一般，'}"
                f"{'近期成交量温和放大，建仓阶段特征明显。' if any('放量' in (e or '') for e in evidence) else '成交量变化不大，需持续观察。'}"
            )
            advice = "建议关注筹码集中度变化，配合成交量确认后介入。"
            risk_tip = "筹码分析滞后于实际交易，需结合量价关系综合判断。"
        elif name == '缠论策略验证':
            summary = (
                f"缠论信号强度为 {conf_pct}%。"
                f"{'日线级别形成标准底分型结构，' if '底分型' in str(evidence) else '顶分型结构出现，'}"
                f"{'MACD底背离确认，属于一类买点信号。' if 'MACD' in str(evidence) else 'MACD指标需进一步确认。'}"
            )
            advice = f"按{conf_pct}%仓位介入，严格设置止损位。"
            risk_tip = "缠论信号存在滞后性，需成交量配合确认有效性。"
        elif name == '因子评分系统':
            summary = (
                f"多因子综合评分为 {conf_pct}%。"
                f"动量因子表现{'突出' if conf_pct >= 60 else '一般'}，"
                f"量价配合情况{'良好' if conf_pct >= 50 else '有待改善。'}"
            )
            advice = f"建议以{conf_pct}%仓位配置，持有周期2-4周。"
            risk_tip = "因子模型存在假设偏差，市场风格切换可能导致信号失效。"
        else:
            summary = f"策略信号评分为 {conf_pct}%，方向为 {direction}。"
            advice = "建议结合其他策略综合判断。"
            risk_tip = "独立策略信号存在局限性。"

        explanations.append({
            'strategy': name,
            'ai_summary': summary,
            'ai_advice': advice,
            'risk_tip': risk_tip
        })

    avg_conf = round(total_conf / max(len(signals), 1) * 100)
    if avg_conf >= 65:
        composite = "三维信号共振，整体偏多。建议按方案轻仓介入，严格止损。"
    elif avg_conf >= 45:
        composite = "信号存在分歧，需进一步确认。建议观望或轻仓试探。"
    else:
        composite = "整体信号偏弱，建议暂时观望，等待更明确的入场时机。"

    return {
        'explanations': explanations,
        'composite_advice': composite
    }
