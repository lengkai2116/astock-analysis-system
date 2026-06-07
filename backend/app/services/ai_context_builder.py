"""
[153-P0-1] 多重上下文注入 — 增强AI分析的数据维度
[153-P0-2] AI诊断结构化输出 — JSON schema驱动

对照 153-观潮对标-AI能力深度分析与升级方案.md §5.1

为DeepSeek分析服务注入多层市场上下文（指数/行业/成交量/资金流向），
使用JSON schema约束输出格式以替代纯文本解析。
"""

import json
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 结构化输出 JSON Schema ──
ANALYSIS_OUTPUT_SCHEMA = {
    "type": "json",
    "schema": {
        "period": "当前分析周期",
        "market_context": {
            "index_trend": "大盘趋势判断(bullish/bearish/sideways)",
            "sector_strength": "所属板块强度评估(strong/neutral/weak)"
        },
        "analysis": {
            "direction": "方向判断(bullish/bearish/neutral)",
            "confidence": "置信度(0-100)",
            "key_levels": {
                "support": "支撑位(float or null)",
                "resistance": "阻力位(float or null)"
            },
            "evidence": [
                {
                    "type": "指标类型(如trend/volume/pattern/momentum)",
                    "description": "证据描述",
                    "weight": "权重(1-5)"
                }
            ],
            "risk_notes": ["风险点列表"],
            "conclusion": "结论摘要(不超过200字)"
        }
    }
}

# ── 角色输出约束 ──
ROLE_OUTPUT_SCHEMA = {
    "technical": """
请严格按照以下JSON格式输出技术分析结果：
{
    "direction": "bullish/bearish/neutral",
    "confidence": 0-100,
    "key_levels": {"support": 价格或null, "resistance": 价格或null},
    "trend": "上升/下降/震荡",
    "indicators": {"ma_trend": "bullish/bearish", "volume": "放量/缩量/正常", "macd": "金叉/死叉/粘合"},
    "patterns": ["识别的K线形态列表"],
    "evidence": [{"type": "趋势/成交量/形态/动量", "description": "具体分析", "weight": 1-5}],
    "risk_notes": ["风险点"],
    "conclusion": "不超过200字的技术面结论"
}
""",
    "fundamental": """
请严格按照以下JSON格式输出基本面分析结果：
{
    "direction": "bullish/bearish/neutral",
    "confidence": 0-100,
    "valuation": "高估/合理/低估",
    "health": "健康/关注/风险",
    "growth": "成长/稳定/衰退",
    "evidence": [{"type": "估值/财务/成长", "description": "具体分析", "weight": 1-5}],
    "risk_notes": ["风险点"],
    "conclusion": "不超过200字的基本面结论"
}
""",
    "macro": """
请严格按照以下JSON格式输出宏观分析结果：
{
    "direction": "bullish/bearish/neutral",
    "confidence": 0-100,
    "market_environment": "有利/中性/不利",
    "sector_outlook": "看好/中性/看淡",
    "capital_flow": "流入/流出/平衡",
    "evidence": [{"type": "宏观/板块/资金", "description": "具体分析", "weight": 1-5}],
    "risk_notes": ["风险点"],
    "conclusion": "不超过200字的宏观结论"
}
""",
    "risk": """
请严格按照以下JSON格式输出风险评估结果：
{
    "risk_level": "低/中/高/极高",
    "risk_score": 0-100,
    "stop_loss_suggested": 止损价位或null,
    "max_position_pct": 建议仓位百分比(0-30),
    "evidence": [{"type": "市场/流动性/个股", "description": "具体评估", "weight": 1-5}],
    "risk_notes": ["风险点"],
    "conclusion": "不超过200字的风控结论"
}
""",
    "fund_manager": """
请严格按照以下JSON格式输出最终综合投资建议：
{
    "overall_rating": "STRONGLY_BUY/BUY/HOLD/SELL/STRONGLY_SELL",
    "confidence": 0-100,
    "target_price_range": {"min": 下限, "max": 上限},
    "stop_loss": 止损价,
    "suggested_position_pct": 建议仓位百分比,
    "key_reasons": ["3-5条关键理由"],
    "evidence": [{"type": "技术/基本面/宏观/风控", "description": "综合理由", "weight": 1-5}],
    "risk_notes": ["风险提示"],
    "conclusion": "不超过200字的最终建议"
}
"""
}


class AiContextBuilder:
    """
    多层上下文构建器

    从多维度获取数据并组装为AI提示上下文：
    Layer 1: 股票基础上下文（代码/名称/行业/市值）
    Layer 2: 市场环境上下文（指数趋势/板块强度）
    Layer 3: 历史信号上下文（前次AI结论与当前偏差）
    Layer 4: 消息面上下文（新闻/题材/事件驱动）
    """

    def __init__(self, data_manager=None):
        if data_manager is None:
            from app.data import DataManager
            data_manager = DataManager()
        self.data_manager = data_manager

    def build_context(self, ts_code: str, market_env: Optional[Dict] = None) -> Dict:
        """
        构建完整分析上下文

        Returns:
            {
                'stock_context': {...},
                'market_context': {...},
                'history_context': {...},
                'news_context': {...},
            }
        """
        return {
            'stock_context': self._build_stock_context(ts_code),
            'market_context': self._build_market_context(market_env),
            'news_context': self._build_news_context(ts_code),
        }

    def _build_stock_context(self, ts_code: str) -> Dict:
        """构建股票基础上下文"""
        ctx = {
            'ts_code': ts_code,
            'name': '',
            'industry': '',
            'market_cap': '',
            'pe': '',
        }
        try:
            from app.models import Stock
            stock = Stock.query.get(ts_code)
            if stock:
                ctx['name'] = getattr(stock, 'name', '') or ''
                ctx['industry'] = getattr(stock, 'industry', '') or ''
                ctx['market_cap'] = str(getattr(stock, 'market_cap', ''))
        except Exception as e:
            logger.debug(f'股票上下文获取失败: {e}')
        return ctx

    def _build_market_context(self, market_env: Optional[Dict] = None) -> Dict:
        """构建市场环境上下文"""
        ctx = {
            'market_condition': 'UNKNOWN',
            'trend': '',
            'sector_strength': '',
        }
        if market_env:
            ctx['market_condition'] = market_env.get('condition', 'UNKNOWN')
            ctx['trend'] = '弱势' if market_env.get('condition') == 'POOR' else (
                '强势' if market_env.get('condition') == 'GOOD' else '中性'
            )
        return ctx

    def _build_news_context(self, ts_code: str) -> Dict:
        """构建消息面上下文（占位，待接入外部新闻API）"""
        return {
            'recent_news': [],
            'hot_topics': [],
            'source': '未接入新闻API',
        }

    def to_prompt_section(self, context: Dict) -> str:
        """将上下文渲染为AI提示文本"""
        stock = context.get('stock_context', {})
        market = context.get('market_context', {})

        lines = []
        lines.append('【分析上下文】')
        lines.append(f'股票: {stock.get("name", "")}({stock.get("ts_code", "")})')
        if stock.get('industry'):
            lines.append(f'行业: {stock["industry"]}')
        if market.get('market_condition', 'UNKNOWN') != 'UNKNOWN':
            lines.append(f'大盘环境: {market.get("trend", "中性")}')
        return '\n'.join(lines)


class AiStructuredParser:
    """
    [153-P0-2] AI诊断结构化输出解析器
    从AI返回文本中提取JSON格式的结构化数据
    """

    @staticmethod
    def parse_json(text: str) -> Optional[Dict]:
        """从AI输出中提取并解析JSON"""
        import re
        # 尝试查找```json ... ``` 代码块
        m = re.search(r'```(?:json)?\s*\n?({.*?})\s*\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试查找独立的 {...} 块
        brace_match = re.search(r'({[^{}]*"direction"[^{}]*})', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(1))
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def validate_schema(data: Dict, role_id: str) -> bool:
        """验证结构化输出是否包含必要字段"""
        required_fields = {
            'technical': ['direction', 'confidence'],
            'fundamental': ['direction', 'confidence'],
            'macro': ['direction', 'confidence'],
            'risk': ['risk_level', 'risk_score'],
            'fund_manager': ['overall_rating', 'confidence'],
        }
        fields = required_fields.get(role_id, ['direction'])
        return all(f in data for f in fields)


class AiSignalBusService:
    """
    [153-P1-1] AiSignalBus 轻量版 — 后端信号广播服务
    将AI分析结果封装为标准信号事件，通过WebSocket推送到前端
    """

    def __init__(self):
        self._signals: List[Dict] = []
        self._listeners: List[Any] = []

    def emit(self, event_type: str, data: Dict):
        """广播AI信号事件"""
        signal = {
            'type': event_type,
            'timestamp': datetime.now().isoformat(),
            'data': data,
        }
        self._signals.append(signal)
        # 触发WebSocket推送（由socketService负责）
        try:
            from flask_socketio import emit as socket_emit
            socket_emit('ai_signal', signal, broadcast=True)
        except Exception:
            pass
        logger.debug(f'AiSignalBus emit: {event_type}')

    def get_recent(self, limit: int = 20) -> List[Dict]:
        """获取最近N条信号"""
        return self._signals[-limit:]


# 单例
ai_context_builder = AiContextBuilder()
ai_signal_bus = AiSignalBusService()
ai_structured_parser = AiStructuredParser()
