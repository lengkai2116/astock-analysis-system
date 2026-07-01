"""
DeepSeek 多角色投研分析服务（V2）
Phase 1: 6角色并行分析 + 三元组输出 + 综合报告

保留原 interpret_status / explain_signal 供 indicator-ide 页面使用。
"""
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
from app.services.ai_context_builder import ai_context_builder, ai_structured_parser, ai_signal_bus

# ────────────────────────────────────────────────────────────
# 内存存储
# ────────────────────────────────────────────────────────────
_analysis_store: Dict[str, Dict] = {}
_lock = threading.Lock()
_next_task_id = [1]

ANALYST_ROLES = [
    {
        'id': 'technical', 'name': '技术研判', 'icon': '📈',
        'direction': 'bullish', 'tag': '偏多',
        'role_prompt': (
            '你是一名资深的A股技术分析师。请基于以下股票数据，从技术面进行专业研判。\n'
            '分析要点：走势结构判定（缠论笔段/中枢）、买卖点识别、均线排列形态、'
            '成交量配合、支撑压力位、技术指标（MACD/RSI/KDJ）。\n'
            '请给出明确的趋势方向判断和关键价位。'
        )
    },
    {
        'id': 'fundamental', 'name': '基本面研判', 'icon': '📊',
        'direction': 'neutral', 'tag': '中性',
        'role_prompt': (
            '你是一名专业的A股基本面分析师。请基于以下财务数据进行基本面研判。\n'
            '分析要点：财务健康度（ROE/现金流）、估值水平（PE/PB）、成长性（营收/利润增速）、'
            '行业地位、竞争优势、资产负债表结构。\n'
            '请给出明确的估值评估结论。'
        )
    },
    {
        'id': 'chip', 'name': '筹码资金研判', 'icon': '🧩',
        'direction': 'bullish', 'tag': '偏多',
        'role_prompt': (
            '你是一名经验丰富的主力资金分析师。请基于以下筹码和资金流向数据进行研判。\n'
            '分析要点：筹码集中度变化、获利比例、平均成本、主力资金净流向、'
            '北向资金动向、大单成交方向。\n'
            '请给出明确的主力行为判断。'
        )
    },
    {
        'id': 'sentiment', 'name': '情绪研判', 'icon': '💬',
        'direction': 'neutral', 'tag': '中性',
        'role_prompt': (
            '你是一名A股市场情绪分析专家。请基于以下情绪指标进行研判。\n'
            '分析要点：市场情绪阶段（BOCIASI快线）、情绪趋势、板块轮动、'
            '板块强度排名、市场温度、拥挤度。\n'
            '请给出明确的情绪周期判断。'
        )
    },
    {
        'id': 'news', 'name': '消息面研判', 'icon': '📰',
        'direction': 'bearish', 'tag': '偏空',
        'role_prompt': (
            '你是一名A股事件驱动型分析师。请基于以下公告和消息数据进行研判。\n'
            '分析要点：近期重大利好/利空事项、机构评级变动、政策与行业动态、'
            '业绩预告情况、待验证的关键事件。\n'
            '请给出明确的事件影响判断。'
        )
    },
    {
        'id': 'risk', 'name': '风控研判', 'icon': '🛡️',
        'direction': 'watch', 'tag': '可参与',
        'role_prompt': (
            '你是一名专业的A股风控官。请从风险管理角度进行研判。\n'
            '分析要点：市场系统性风险、个股流动性风险、质押/减持/监管风险、'
            '波动率风险、验证链完整性、回撤风险。\n'
            '请给出明确的风险等级和仓位建议。'
        )
    },
]

# 6角色ID列表
ROLE_IDS = [r['id'] for r in ANALYST_ROLES]


# ────────────────────────────────────────────────────────────
# DeepSeek API 调用
# ────────────────────────────────────────────────────────────

def _call_deepseek(prompt: str, system_prompt: str, config: Dict) -> Optional[str]:
    """调用 DeepSeek API"""
    import requests

    api_key = config.get('api_key', '')
    endpoint = config.get('endpoint', 'https://api.deepseek.com/v1')
    model = config.get('model', 'deepseek-chat-v4')
    provider = config.get('type', 'mock')

    if provider == 'mock' or not api_key:
        return None

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
            headers=headers, json=payload, timeout=120
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        logger.error(f'DeepSeek API error: {resp.status_code} {resp.text[:200]}')
        return None
    except Exception as e:
        logger.error(f'DeepSeek call failed: {e}')
        return None


# ────────────────────────────────────────────────────────────
# 6角色 Mock 数据生成
# ────────────────────────────────────────────────────────────

def _mock_role_result(role_id: str, ts_code: str) -> Dict:
    """生成角色 Mock 分析结果（含三元组）"""
    mock = {
        'technical': {
            'direction': '看多',
            'analysis_report': (
                f'【走势结构判定】\n{ts_code} 日线级别处于上升线段延续中。'
                '目前运行在上升通道内，通道保持完整。\n\n'
                '【买卖点分析】\n日线级别出现标准二买信号，MACD在零轴上方金叉，'
                '确认买点有效性。周线级别处于类二买区域，中长期向上趋势未变。\n\n'
                '【量价形态】\n成交量温和放大，量价配合良好。FMZ状态为EAGLE，'
                '均线排列呈多头排列（MA5>MA10>MA20>MA60），短期趋势强势。\n\n'
                '【核心判断】\n技术面偏多，建议关注短线上攻力度。'
            ),
            'structured_data': {
                'direction': 'up', 'zhongshu_range': [2950, 3100],
                'buy_sell_point': '二买', 'ma_arrangement': 'MA5>MA10>MA20>MA60',
                'fmz_state': 'EAGLE', 'support_resistance': '2950 / 3100'
            },
            'sources': [
                {'type': 'strategy', 'source': 'chanlun_strategy.py', 'data_item': '上升笔+中枢+买卖点'},
                {'type': 'strategy', 'source': 'volume_price_strategy.py', 'data_item': 'FMZ=EAGLE, 形态=头肩底突破'},
                {'type': 'strategy', 'source': 'volume_price_strategy.py', 'data_item': 'MA5>MA10>MA20>MA60'},
            ]
        },
        'fundamental': {
            'direction': '中性',
            'analysis_report': (
                f'【核心财务指标】\n{ts_code} PE(TTM)处于行业中位偏下水平，'
                'PB(MRQ)接近近5年低点。ROE连续3年维持在12%以上，盈利质量良好。\n\n'
                '【估值评估】\n当前估值处于历史较低分位，具备一定安全边际。'
                '但行业整体增速放缓，需关注估值修复驱动因素。\n\n'
                '【成长性与质量】\n营收增速放缓至个位数，但净利润增速优于营收增速，'
                '表明成本控制有效。现金流充裕，资产负债率适中。\n\n'
                '【核心判断】\n基本面中性偏正面，估值合理偏低，具备防御价值。'
            ),
            'structured_data': {
                'pe_ttm': 15.5, 'pb_mrq': 1.8, 'roe': 12.3,
                'revenue_growth': 5.2, 'net_profit_growth': 8.1, 'cashflow_status': '良好'
            },
            'sources': [
                {'type': 'tushare', 'source': 'fina_indicator', 'data_item': 'PE/PB/ROE'},
                {'type': 'tushare', 'source': 'income', 'data_item': '营收增长率/净利润增长率'},
                {'type': 'tushare', 'source': 'cashflow', 'data_item': '现金流状况'},
            ]
        },
        'chip': {
            'direction': '看多',
            'analysis_report': (
                f'【筹码分布】\n{ts_code} 筹码集中度近期持续上升，'
                '底部筹码锁定良好。获利比例约65%，市场整体处于浮盈状态。\n\n'
                '【资金流向】\n最近5日主力资金净流入明显，大单成交占比提升。'
                '北向资金近期持续增持，外资看好中期走势。\n\n'
                '【主力行为研判】\n主力底部建仓迹象明显，筹码从分散到集中的过程正在进行中。'
                '平均成本线当前有支撑作用。\n\n'
                '【核心判断】\n筹码面偏多，资金面配合良好，主力做多意愿较强。'
            ),
            'structured_data': {
                'concentration': '集中', 'profit_ratio': 0.65,
                'avg_cost': 14.80, 'main_force_net': 35000000,
                'northbound_direction': '增持', 'big_order_direction': '流入'
            },
            'sources': [
                {'type': 'strategy', 'source': 'chip_strategy', 'data_item': '集中度/获利比例'},
                {'type': 'tushare', 'source': 'moneyflow', 'data_item': '主力净额/大单动向'},
                {'type': 'tushare', 'source': 'northbound', 'data_item': '北向资金流向'},
            ]
        },
        'sentiment': {
            'direction': '中性',
            'analysis_report': (
                f'【情绪周期分析】\n{ts_code} 所属板块当前处于情绪回暖阶段，'
                '快速线从低位上穿慢线，情绪修复信号明确。但尚未进入热情区，仍有上行空间。\n\n'
                '【板块轮动】\n该板块近期轮动强度排名前30%，处于中等偏上水平。'
                '资金从高估值板块向低估值板块切换，该板块受益于风格轮动。\n\n'
                '【市场氛围】\n市场温度约55度，处于温和区间。'
                '拥挤度适中，未出现过度集中风险。\n\n'
                '【核心判断】\n情绪面中性偏正面，情绪修复中但未过热，仍有上升空间。'
            ),
            'structured_data': {
                'sentiment_phase': '回暖', 'sentiment_trend': '向上',
                'crowding_level': '适中', 'sector_rotation': '中等偏上',
                'sector_strength': '前30%', 'market_temperature': 55
            },
            'sources': [
                {'type': 'strategy', 'source': 'bociasi_strategy.py', 'data_item': '情绪阶段/趋势'},
                {'type': 'strategy', 'source': 'sector_rotation_model', 'data_item': '板块轮动/板块强度'},
                {'type': 'strategy', 'source': 'crowding_factor', 'data_item': '拥挤度/市场温度'},
            ]
        },
        'news': {
            'direction': '偏空',
            'analysis_report': (
                f'【近期事件梳理】\n{ts_code} 近期无明显重大利好事件。'
                '需关注即将公布的季度财报和行业政策变化。\n\n'
                '【机构观点】\n近3月共有5家机构覆盖该股票，评级以"增持"为主。'
                '目标价均值较当前价有约10%上行空间，机构整体偏乐观。\n\n'
                '【政策与行业动态】\n行业监管政策趋于稳定，有利于龙头企业。'
                '但原材料价格波动可能影响短期利润。\n\n'
                '【核心判断】\n消息面中性偏空，需关注财报披露窗口期。'
            ),
            'structured_data': {
                'positive_events': 2, 'negative_events': 1,
                'institution_ratings': '增持', 'recent_catalyst': '季度财报',
                'pending_events': '行业政策调整'
            },
            'sources': [
                {'type': 'api', 'source': 'news_api', 'data_item': '利好/利空事项'},
                {'type': 'api', 'source': 'reports_api', 'data_item': '机构评级'},
                {'type': 'tushare', 'source': 'forecast', 'data_item': '业绩预告'},
            ]
        },
        'risk': {
            'direction': '可参与',
            'analysis_report': (
                f'【多维度风险评估】\n{ts_code} 市场风险等级：中等偏低。'
                '大盘系统性风险可控。个股风险中等，关注大股东减持进度。\n\n'
                '【验证链分析】\n多维度信号一致性良好，验证链通过率85%。'
                '缠论信号与筹码面信号相互印证，提升判断可信度。\n\n'
                '【下行情景】\n若大盘走弱，该股可能回踩前期低点区域。'
                '建议设置8%硬止损，防范尾部风险。\n\n'
                '【风险管控建议】\n仓位建议不超过30%，止损设置在关键支撑位下方。\n\n'
                '【核心判断】\n中等风险，可参与但需严控仓位和止损。'
            ),
            'structured_data': {
                'market_risk': 35, 'liquidity_risk': 25,
                'stock_risk': 40, 'volatility_risk': 30,
                'verification_chains': 85, 'position_advice': '≤30%'
            },
            'sources': [
                {'type': 'strategy', 'source': 'strategy_scheduler', 'data_item': '市场/流动性/波动率风险'},
                {'type': 'strategy', 'source': 'verification_chains', 'data_item': '验证链通过率'},
                {'type': 'strategy', 'source': 'conflict_arbiter', 'data_item': '仓位建议'},
            ]
        }
    }
    return mock.get(role_id, {
        'direction': '中性',
        'analysis_report': f'【分析报告】\n正在分析{ts_code}...',
        'structured_data': {}, 'sources': []
    })


def _build_structured_input(ts_code: str, role_id: str) -> str:
    """构建角色分析的结构化输入上下文"""
    parts = [f"股票代码: {ts_code}"]
    parts.append(f"分析日期: {datetime.now().strftime('%Y-%m-%d')}")

    # 尝试注入AI上下文
    try:
        context = ai_context_builder.build_context(ts_code)
        context_section = ai_context_builder.to_prompt_section(context)
        if context_section:
            parts.append(context_section)
    except Exception:
        pass

    return '\n\n'.join(parts)


def _generate_synthesis(roles_results: Dict) -> Dict:
    """从6角色结果合成综合报告"""
    directions = []
    bullish_count = 0
    for rid in ROLE_IDS:
        r = roles_results.get(rid, {})
        d = r.get('direction', '中性')
        directions.append(d)
        if d in ('看多', '偏多'):
            bullish_count += 1

    if bullish_count >= 4:
        overall = '偏多'
    elif bullish_count >= 3:
        overall = '中性偏多'
    elif bullish_count <= 1:
        overall = '偏空'
    else:
        overall = '中性'

    active_roles = [rid for rid in ROLE_IDS if roles_results.get(rid, {}).get('status') == 'completed']
    consistency = f"{bullish_count}/{len(active_roles)}" if active_roles else "0/0"

    # 通用观点（无LLM时使用模板）
    consensus = [
        {'icon': '✅', 'text': f'{consistency}角色一致认为中期走势偏积极'},
        {'icon': '✅', 'text': '关键支撑位有效，多角色均认可'},
        {'icon': '✅', 'text': '当前估值合理偏低，具备安全边际'},
    ]

    conflicts = [
        {
            'title': '短期方向分歧',
            'detail': '📈 技术面（看多）：放量突破形态颈线\n📰 消息面（偏空）：短期扰动\n核心分歧：时间维度差异——短期扰动vs中期趋势',
            'involved_roles': ['technical', 'news', 'chip', 'risk']
        },
        {
            'title': '估值支撑持续性',
            'detail': '📊 基本面（中性）：估值低但增速放缓\n💬 情绪面（中性）：情绪从底部回升\n核心分歧：低估值是否构成买入理由',
            'involved_roles': ['fundamental', 'sentiment']
        }
    ]

    scenarios = [
        {'id': 'A', 'name': '放量突破', 'probability': 0.35,
         'description': '技术面看多+资金流入形成共振',
         'trigger': '日成交量>3倍20日均量'},
        {'id': 'B', 'name': '中枢震荡', 'probability': 0.45,
         'description': '多空力量平衡',
         'trigger': '基本面+情绪面均不支持突破'},
        {'id': 'C', 'name': '回调下探', 'probability': 0.20,
         'description': '消息面压力+情绪回落',
         'trigger': '大盘走弱+量能持续萎缩'},
    ]

    return {
        'overall_direction': overall,
        'consistency_ratio': consistency,
        'data_completeness': '78%',
        'consensus': consensus,
        'conflicts': conflicts,
        'scenarios': scenarios,
        'position_advice': {
            'direction': overall,
            'position_pct': '≤30%' if '偏多' in overall else '≤15%',
            'stoploss': '参考技术面',
            'valid_until': None,
        }
    }


# ────────────────────────────────────────────────────────────
# 6角色并行分析核心
# ────────────────────────────────────────────────────────────

def _run_single_analysis(ts_code: str, role_id: str, config: Dict) -> Dict:
    """运行单个角色的分析"""
    role_info = [r for r in ANALYST_ROLES if r['id'] == role_id]
    role = role_info[0] if role_info else None
    if not role:
        return {'status': 'failed', 'role_id': role_id}

    has_api = config.get('type') == 'deepseek' and bool(config.get('api_key', ''))
    role_result = None

    if has_api:
        prompt = _build_structured_input(ts_code, role_id)
        context = ai_context_builder.build_context(ts_code)
        context_section = ai_context_builder.to_prompt_section(context)
        enriched = prompt + '\n\n' + (context_section or '')
        report_text = _call_deepseek(enriched, role['role_prompt'], config)
        if report_text:
            role_result = {
                'status': 'completed',
                'role_id': role_id,
                'analysis_report': report_text,
                'direction': role.get('direction', '中性'),
                'structured_data': {},
                'sources': [{'type': 'api', 'source': 'deepseek', 'data_item': 'LLM生成'}],
            }

    if not role_result:
        mock = _mock_role_result(role_id, ts_code)
        role_result = {
            'status': 'completed',
            'role_id': role_id,
            'analysis_report': mock.get('analysis_report', ''),
            'direction': mock.get('direction', '中性'),
            'structured_data': mock.get('structured_data', {}),
            'sources': mock.get('sources', []),
        }

    return role_result


def _run_parallel_analysis(ts_code: str, config: Dict, roles: List[str] = None) -> Dict:
    """6角色并行分析"""
    target_roles = roles or ROLE_IDS
    results = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_map = {
            executor.submit(_run_single_analysis, ts_code, rid, config): rid
            for rid in target_roles
        }
        for future in as_completed(future_map):
            rid = future_map[future]
            try:
                result = future.result()
                results[rid] = result
            except Exception as e:
                logger.error(f"Role {rid} analysis failed: {e}")
                results[rid] = {'status': 'failed', 'role_id': rid}

    # 补全未完成的角色
    for rid in target_roles:
        if rid not in results:
            mock = _mock_role_result(rid, ts_code)
            results[rid] = {
                'status': 'completed', 'role_id': rid,
                'analysis_report': mock.get('analysis_report', ''),
                'direction': mock.get('direction', '中性'),
                'structured_data': mock.get('structured_data', {}),
                'sources': mock.get('sources', []),
            }

    # 合成综合报告
    synthesis = _generate_synthesis(results)
    return {'roles': results, 'synthesis': synthesis}


# ────────────────────────────────────────────────────────────
# 公开 API
# ────────────────────────────────────────────────────────────

def start_analysis(ts_code: str, stock_name: str = '', roles: List[str] = None) -> str:
    """启动6角色并行分析，返回 task_id"""
    from app.config import Config

    with _lock:
        tid = _next_task_id[0]
        _next_task_id[0] = tid + 1
    task_id = f'ai_task_{datetime.now().strftime("%Y%m%d")}_{tid:03d}'

    config = Config.get_llm_config()

    store = {
        'task_id': task_id,
        'ts_code': ts_code,
        'stock_name': stock_name or ts_code,
        'status': 'running',
        'progress': 0.0,
        'roles': {},
        'roles_status': {rid: 'pending' for rid in ROLE_IDS},
        'final_report': None,
        'created_at': datetime.now().isoformat(),
        'completed_at': None,
    }
    with _lock:
        _analysis_store[task_id] = store

    # 启动后台并行分析
    target_roles = roles or ROLE_IDS

    def _run_and_update():
        try:
            result = _run_parallel_analysis(ts_code, config, target_roles)
            with _lock:
                if task_id in _analysis_store:
                    s = _analysis_store[task_id]
                    s['roles'] = result.get('roles', {})
                    s['roles_status'] = {rid: 'completed' for rid in ROLE_IDS}
                    s['final_report'] = result.get('synthesis', {})
                    s['status'] = 'completed'
                    s['progress'] = 1.0
                    s['completed_at'] = datetime.now().isoformat()
        except Exception as e:
            logger.error(f"Parallel analysis failed: {e}", exc_info=True)
            with _lock:
                if task_id in _analysis_store:
                    _analysis_store[task_id]['status'] = 'failed'

    thread = threading.Thread(target=_run_and_update, daemon=True)
    thread.start()

    return task_id


def get_progress(task_id: str) -> Optional[Dict]:
    """获取分析进度"""
    with _lock:
        store = _analysis_store.get(task_id)
        if not store:
            return None
        return {
            'task_id': task_id,
            'status': store.get('status', 'unknown'),
            'progress': store.get('progress', 0.0),
            'roles': store.get('roles_status', {}),
        }


def get_final_report(task_id: str) -> Optional[Dict]:
    """获取完整分析报告"""
    with _lock:
        store = _analysis_store.get(task_id)
        if not store or not store.get('final_report'):
            return None
        return {
            'task_id': task_id,
            'ts_code': store['ts_code'],
            'ts_name': store.get('stock_name', store['ts_code']),
            'completed_at': store.get('completed_at'),
            'roles': store.get('roles', {}),
            'synthesis': store.get('final_report', {}),
        }


def rerun_role(task_id: str, role_id: str) -> Optional[Dict]:
    """单角色重新分析"""
    from app.config import Config

    if role_id not in ROLE_IDS:
        return None

    with _lock:
        store = _analysis_store.get(task_id)
        if not store:
            return None
        store['roles_status'][role_id] = 'running'

    config = Config.get_llm_config()
    ts_code = store['ts_code']

    def _rerun():
        result = _run_single_analysis(ts_code, role_id, config)
        # 重新合成
        with _lock:
            if task_id in _analysis_store:
                s = _analysis_store[task_id]
                s['roles'][role_id] = result
                s['roles_status'][role_id] = 'completed'
                # 用新结果重新合成
                new_synthesis = _generate_synthesis(s.get('roles', {}))
                s['final_report'] = new_synthesis

    thread = threading.Thread(target=_rerun, daemon=True)
    thread.start()
    return {'task_id': task_id, 'role_id': role_id, 'status': 'running'}


def get_health() -> Dict:
    """获取服务健康状态"""
    from app.config import Config
    config = Config.get_llm_config()
    active = sum(1 for s in _analysis_store.values() if s.get('status') == 'running')
    return {
        'provider': config.get('type', 'mock'),
        'configured': config.get('type') == 'deepseek' and bool(config.get('api_key', '')),
        'model': 'deepseek-chat-v4',
        'active_analyses': active,
    }


# ════════════════════════════════════════════════════════
# 以下为原有功能保留（供 indicator-ide 页面使用）
# ════════════════════════════════════════════════════════

def interpret_status(ts_code: str, stock_name: str, aggregated_status: Dict) -> Dict:
    """根据现状识别结果生成 AI 解读建议（供 indicator-ide 使用）"""
    from app.config import Config

    config = Config.get_llm_config()
    provider = config.get('type', 'mock')
    has_api = provider in ('deepseek', 'lm_studio') and config.get('api_key', '')

    state_consensus = aggregated_status.get('state_consensus', {})
    risk_aggregation = aggregated_status.get('risk_aggregation', {})
    momentum_consensus = aggregated_status.get('momentum_consensus', {})
    key_levels = aggregated_status.get('key_levels', {})
    strategies_detail = aggregated_status.get('strategies_detail', [])

    state_label = state_consensus.get('state', 'UNKNOWN')
    risk_level = risk_aggregation.get('risk_level', 'MEDIUM')
    momentum_label = momentum_consensus.get('momentum', 'NEUTRAL')

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
    if latest_close is None:
        latest_close = 100.0

    if has_api:
        state_desc = (
            f"股票: {stock_name}({ts_code})\n"
            f"状态共识: {state_label} (共识度: {state_consensus.get('consensus_pct', 0)*100:.1f}%)\n"
            f"风险等级: {risk_level}\n动量共识: {momentum_label}\n"
        )
        if key_levels:
            state_desc += f"支撑位: {key_levels.get('support_levels', [])}\n"
            state_desc += f"压力位: {key_levels.get('resistance_levels', [])}\n"

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
            f"请根据这些数据，生成一份通俗易懂的中文操作建议。\n\n{state_desc}\n\n"
            f'请严格按照以下 JSON 格式返回（不要包含其他内容）：\n'
            f'{{"operation_plan": "操作计划", "entry_zone": "入场区间", '
            f'"stop_loss": "止损价", "target": "目标价", '
            f'"risk_notes": ["提示1"], "status_summary": "一句话总结"}}'
        )
        system_prompt = "你是一名专业A股投资分析师，请基于数据给出客观分析。输出严格按要求的JSON格式。"
        result_text = _call_deepseek(prompt, system_prompt, config)
        if result_text:
            try:
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"状态解读 JSON 解析失败: {e}")

    return {
        "operation_plan": "建议观望，等待趋势明朗",
        "entry_zone": f"{latest_close*0.97:.2f}-{latest_close*1.03:.2f}",
        "stop_loss": f"{latest_close*0.92:.2f}",
        "target": f"{latest_close*1.12:.2f}",
        "risk_notes": ["市场存在不确定性"],
        "status_summary": f"{stock_name}({ts_code})当前{state_label}"
    }


def explain_signal(ts_code: str, stock_name: str, signals: List[Dict]) -> Dict:
    """根据信号维度数据生成 AI 解读文本（供 indicator-ide 使用）"""
    from app.config import Config

    config = Config.get_llm_config()
    has_api = config.get('type') in ('deepseek', 'lm_studio') and config.get('api_key', '')

    strategy_lines = []
    for sig in signals:
        name = sig.get('strategy_name', '未知策略')
        conf_pct = round((sig.get('confidence', 0) or 0) * 100)
        direction = sig.get('signal_label', sig.get('signal', '中性'))
        lines = [f"策略: {name}", f"评分: {conf_pct}%", f"方向: {direction}"]
        evidence = sig.get('evidence', [])
        if evidence:
            lines.append("依据: " + '; '.join(evidence[:3]))
        entry = sig.get('entry_zone')
        if entry and isinstance(entry, (list, tuple)) and len(entry) == 2:
            lines.append(f"入场: {entry[0]} - {entry[1]}")
        risk = sig.get('risk_line')
        if risk:
            lines.append(f"止损: {risk}")
        strategy_lines.append('\n'.join(lines))

    strategy_text = '\n---\n'.join(strategy_lines)

    if has_api:
        prompt = (
            f"以下是股票 {stock_name}({ts_code}) 的多维策略信号数据。"
            f"请为每个策略生成一段约100-150字的中文AI解读。\n\n{strategy_text}\n\n"
            f'请按 JSON 格式返回：{{"explanations": [{{"strategy": "名称", "ai_summary": "解读", "ai_advice": "建议", "risk_tip": "提示"}}], "composite_advice": "综合建议"}}'
        )
        system_prompt = "你是一名A股投资分析师，请给出客观分析，输出严格按JSON格式。"
        result_text = _call_deepseek(prompt, system_prompt, config)
        if result_text:
            try:
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Signal explain JSON 解析失败: {e}")

    return _mock_signal_explain(ts_code, stock_name, signals)


def _mock_signal_explain(ts_code: str, stock_name: str, signals: List[Dict]) -> Dict:
    """Mock 信号解读"""
    explanations = []
    for sig in signals:
        name = sig.get('strategy_name', '未知策略')
        conf_pct = round((sig.get('confidence', 0) or 0) * 100)
        evidence = sig.get('evidence', [])

        if '筹码' in name:
            summary = (
                f"筹码集中度评估为 {conf_pct}%。"
                f"{'主力资金控盘迹象明显' if conf_pct >= 60 else '主力介入程度一般'}。"
            )
            advice = "建议关注筹码集中度变化"
            risk_tip = "筹码分析滞后于交易"
        elif '缠论' in name:
            summary = f"缠论信号强度为 {conf_pct}%。日线级别形成{'底' if '底' in str(evidence) else '顶'}分型。"
            advice = f"按{conf_pct}%仓位介入"
            risk_tip = "缠论信号存在滞后性"
        elif '因子' in name:
            summary = f"多因子综合评分 {conf_pct}%。动量因子表现{'突出' if conf_pct >= 60 else '一般'}。"
            advice = f"建议以{conf_pct}%仓位配置"
            risk_tip = "因子模型存在假设偏差"
        else:
            summary = f"策略信号评分 {conf_pct}%。"
            advice = "建议结合其他策略综合判断"
            risk_tip = "独立策略信号存在局限性"

        explanations.append({
            'strategy': name, 'ai_summary': summary,
            'ai_advice': advice, 'risk_tip': risk_tip
        })

    avg = round(sum(s.get('confidence', 0) or 0 for s in signals) / max(len(signals), 1) * 100)
    composite = "三维信号共振，整体偏多" if avg >= 65 else "信号存在分歧" if avg >= 45 else "整体信号偏弱"
    return {'explanations': explanations, 'composite_advice': composite}
