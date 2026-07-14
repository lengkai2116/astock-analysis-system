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
    model = config.get('model', 'deepseek-v4-flash')
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

    # 要求AI输出方向标签
    parts.append(
        "\n\n请在分析报告末尾单独一行输出方向标签，格式如下：\n"
        "方向标签：看多（或：偏多/中性偏多/中性/中性偏空/偏空/看空）"
    )

    return '\n\n'.join(parts)


def _extract_direction(report_text: str, role_id: str) -> str:
    """从AI分析报告中提取方向标签"""
    # 1) 尝试从末尾的"方向标签"中提取
    import re
    patterns = [
        r'方向标签[：:]\s*(\S+)',
        r'【核心判断】[^\n]*(\S+)[^\n]*',
    ]
    for pat in patterns:
        m = re.search(pat, report_text)
        if m:
            tag = m.group(1)
            for known in ('看多', '偏多', '中性偏多', '中性', '中性偏空', '偏空', '看空', '可参与', '观望'):
                if known in tag:
                    return known

    # 2) 关键词兜底
    bullish_words = ['看多', '偏多', '积极', '买入', '上涨', '突破']
    bearish_words = ['看空', '偏空', '谨慎', '卖出', '下跌', '回避', '风险']
    bullish_score = sum(1 for w in bullish_words if w in report_text)
    bearish_score = sum(1 for w in bearish_words if w in report_text)

    if bullish_score > bearish_score + 2:
        return '偏多'
    elif bearish_score > bullish_score + 2:
        return '偏空'
    return '中性'


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
    if not has_api:
        return {
            'status': 'failed', 'role_id': role_id,
            'error': 'DeepSeek API 不可用，无法生成分析',
        }

    prompt = _build_structured_input(ts_code, role_id)
    context = ai_context_builder.build_context(ts_code)
    context_section = ai_context_builder.to_prompt_section(context)
    enriched = prompt + '\n\n' + (context_section or '')
    report_text = _call_deepseek(enriched, role['role_prompt'], config)
    if not report_text:
        return {
            'status': 'failed', 'role_id': role_id,
            'error': 'DeepSeek API 返回为空',
        }

    # 从AI输出中提取方向标签（而非用角色默认值）
    direction = _extract_direction(report_text, role_id)
    logger.info(f"{role_id} AI方向提取: {direction}")

    return {
        'status': 'completed',
        'role_id': role_id,
        'analysis_report': report_text,
        'direction': direction,
        'structured_data': {},
        'sources': [{'type': 'api', 'source': 'deepseek', 'data_item': 'LLM生成'}],
    }


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

    # 不再补全失败角色（移除Mock数据回退）
    completed = [rid for rid, r in results.items() if r.get('status') == 'completed']
    failed = [rid for rid, r in results.items() if r.get('status') != 'completed']
    if failed:
        logger.warning(f"角色分析失败: {failed}，已完成: {completed}")

    return {'roles': results, 'synthesis': {}}


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
        'model': 'deepseek-v4-flash',
        'active_analyses': active,
    }


# ════════════════════════════════════════════════════════
# 以下为原有功能保留（供 indicator-ide 页面使用）
# ════════════════════════════════════════════════════════

def interpret_status(ts_code: str, stock_name: str, aggregated_status: Dict) -> Dict:
    """根据现状识别结果生成 AI 解读建议（供 indicator-ide 使用）

    使用 NLG 渲染器将结构化状态转为中文描述，配合验证链和知识库
    构建三段式 prompt 发送给 DeepSeek，提升解读质量。
    """
    from app.config import Config

    config = Config.get_llm_config()
    provider = config.get('type', 'mock')
    has_api = provider in ('deepseek', 'lm_studio') and config.get('api_key', '')

    state_consensus = aggregated_status.get('state_consensus', {})
    risk_aggregation = aggregated_status.get('risk_aggregation', {})
    momentum_consensus = aggregated_status.get('momentum_consensus', {})
    key_levels = aggregated_status.get('key_levels', {})
    dimensions = aggregated_status.get('dimensions', [])
    verification_chains = aggregated_status.get('verification_chains', [])
    dimension_relations = aggregated_status.get('dimension_relations', [])

    state_label = state_consensus.get('state', 'UNKNOWN')
    risk_level = risk_aggregation.get('risk_level', 'MEDIUM')
    momentum_label = momentum_consensus.get('momentum', 'NEUTRAL')

    latest_close = None
    for dim in dimensions:
        signals = dim.get('signals', dim.get('signal', []))
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
        # ── 1. 五维现状详述（通过 NLG 渲染器） ──
        nlg_descriptions = _build_nlg_descriptions(dimensions)

        # ── 2. 验证链状态 ──
        chain_lines = []
        for vc in verification_chains:
            name = vc.get('chain_name', '验证链')
            passed = vc.get('passed', False)
            conflict = vc.get('conflict_detail', '')
            evidence = vc.get('evidence', [])
            status = '✅ 通过' if passed else '❌ 未通过'
            if conflict:
                chain_lines.append(f"  {name}: {status} — {conflict}")
            elif evidence:
                chain_lines.append(f"  {name}: {status}（{'；'.join(evidence[:2])}）")
            else:
                chain_lines.append(f"  {name}: {status}")
        verification_text = '\n'.join(chain_lines) if chain_lines else '  无可用的验证链数据'

        # ── 3. 维度间关系 ──
        if dimension_relations:
            dr_lines = []
            for dr in dimension_relations:
                status_cn = '一致' if dr['status'] == 'consistent' else ('矛盾' if dr['status'] == 'conflict' else '偏差')
                dr_lines.append(f"  {dr['from']} ↔ {dr['to']}: {status_cn}（{dr['detail']}）")
            dimension_text = '\n'.join(dr_lines)
        else:
            dimension_text = '  无可用的维度关系数据'

        # ── 4. 知识库参考 ──
        knowledge_text = _build_knowledge_context(dimensions, state_label)

        prompt = (
            f"以下是股票 {stock_name}({ts_code}) 的多维现状分析数据。\n"
            f"最新价: {latest_close}\n\n"
            f"【五维现状详述】\n{nlg_descriptions}\n\n"
            f"【验证链状态】\n{verification_text}\n\n"
            f"【维度间关系】\n{dimension_text}\n\n"
            f"【知识库参考】\n{knowledge_text}\n\n"
            f"请基于以上完整信息，生成一份通俗易懂的中文操作建议。\n"
            f'请严格按照以下 JSON 格式返回（不要包含其他内容）：\n'
            f'{{"operation_plan": "操作计划（含具体操作方向逻辑和持仓建议）", '
            f'"entry_zone": "入场区间", '
            f'"stop_loss": "止损价", "target": "目标价", '
            f'"risk_notes": ["提示1","提示2"], '
            f'"status_summary": "一句话总结（含核心判断依据）"}}'
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


def _build_nlg_descriptions(dimensions: list) -> str:
    """用 NLG 渲染器为每个维度生成中文描述。"""
    try:
        from app.services.nlg import render_five_dimensions
        dim_texts = render_five_dimensions(dimensions)
        if dim_texts:
            lines = []
            for dim_name, desc in dim_texts.items():
                lines.append(f"{dim_name}：{desc}")
            return '\n'.join(lines)
    except Exception:
        pass

    # 降级：取 state 字段
    lines = []
    for dim in dimensions[:5]:
        name = dim.get('strategy_name', dim.get('name', '未知'))
        status = dim.get('status_recognition', {})
        s = status.get('state', 'N/A') if isinstance(status, dict) else 'N/A'
        lines.append(f"  {name}: {s}")
    return '\n'.join(lines)


def _build_knowledge_context(dimensions: list, state_label: str) -> str:
    """从 KnowledgeReader 查询与当前状态相关的知识概念。"""
    try:
        from app.services.knowledge_reader import get_knowledge_reader
        reader = get_knowledge_reader()
        reader.initialize()

        # 从各维度提取中文关键词（忽略英文状态码，只保留有语义的中文词）
        keywords = []
        eng_state_set = {'ACCUMULATING', 'DISTRIBUTING', 'RANGING', 'BEARISH', 'BULLISH',
                         'NEUTRAL', 'UNKNOWN', 'WATCH', 'BUY', 'SELL', 'HOLD',
                         'LOW', 'MEDIUM', 'HIGH', 'UP', 'DOWN', ''}
        for dim in dimensions[:3]:
            status = dim.get('status_recognition', {})
            if not isinstance(status, dict):
                continue
            # 用中文 state_label 而非英文 state
            label = status.get('state_label', '')
            if label and label not in eng_state_set:
                keywords.append(label)
            # 趋势方向（已在模板转为中文）
            trend = status.get('trend', {})
            td = trend.get('direction', '')
            if td and td not in eng_state_set:
                keywords.append(td)
            trend_stage = trend.get('stage', '')
            if trend_stage:
                # 提取中文部分，如 '日线up_延续' → '日线'
                cn_parts = re.findall(r'[\u4e00-\u9fff]+', trend_stage)
                keywords.extend(cn_parts)
            # 量价形态（结构字段有中文形态名）
            vol_struct = status.get('volume', {}).get('structure', '')
            if vol_struct:
                cn_parts = re.findall(r'[\u4e00-\u9fff]+', vol_struct)
                keywords.extend(cn_parts[:2])
            # 买卖点
            bp = status.get('buy_sell_point', {})
            if bp.get('buy'):
                keywords.extend(bp['buy'][:2])
            if bp.get('sell'):
                keywords.extend(bp['sell'][:2])

        # 去重 + 过滤空/单字母/纯英文
        unique_keywords = []
        seen = set()
        for kw in keywords:
            kw_stripped = kw.strip()
            if not kw_stripped or kw_stripped in seen or kw_stripped.upper() in eng_state_set:
                continue
            if len(kw_stripped) < 2 and kw_stripped.isascii():
                continue
            seen.add(kw_stripped)
            unique_keywords.append(kw_stripped)

        query = ' '.join(unique_keywords[:6]) if unique_keywords else f'{state_label} 股票分析'
        results = reader.match(query, top_k=3, min_tier='T2')
        if results:
            lines = []
            for r in results:
                lines.append(f"- {r['title']}（相关度 {r['relevance']:.2f}）")
                snippet = r['content'][:100].replace('\n', ' ')
                lines.append(f"  {snippet}")
            return '\n'.join(lines)
    except Exception as e:
        logger.debug(f"知识库查询跳过: {e}")
    return "暂无相关知识库匹配结果"


def explain_signal(ts_code: str, stock_name: str, signals: List[Dict],
                   wiki_context: str = "") -> Dict:
    """根据信号维度数据生成 AI 解读文本（供 indicator-ide 使用）

    Args:
        ts_code: 股票代码
        stock_name: 股票名称
        signals: 信号数据列表
        wiki_context: LLM Wiki 知识库上下文（可选），将注入到 prompt 中
    """
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
        if wiki_context:
            prompt = f"【知识库参考信息】\n{wiki_context}\n\n{prompt}"
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
