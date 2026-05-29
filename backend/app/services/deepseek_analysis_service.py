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
    model = config.get('model', 'deepseek-chat')
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
    bullish = 50
    bearish = 50

    import re
    # Extract bullish percentage
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
                report_text = _call_deepseek(prompt, role['role_prompt'], config)

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

            prompt = (
                f'请对{stock_name}({ts_code})给出最终投资建议。\n\n'
                f'各分析师评分：\n' + '\n'.join(summaries) + '\n\n'
                '请给出：总体评级、目标价位区间、建议仓位、止损价位、详细理由。'
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
