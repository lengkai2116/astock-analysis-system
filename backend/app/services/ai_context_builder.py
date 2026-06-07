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

import numpy as np

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


# ── MultiStepContext ──

class MultiStepContextBuilder:
    """
    多步骤上下文构建器
    =====================
    实现 153-P2-2: 分步构建分析上下文

    流程:
    Step 1: 技术面上下文 — K线数据 + 技术指标 + 形态识别
    Step 2: 基本面上下文 — 财务指标 + 估值水平
    Step 3: 消息面上下文 — 新闻 + 公告 + 舆情
    Step 4: 历史信号上下文 — 前次AI结论 + 偏差
    Step 5: 综合上下文 — 上述全部 + 策略信号 + 市场环境

    每步可独立调用，支持增量式上下文构建。
    """

    STEPS = ['technical', 'fundamental', 'news', 'history', 'synthesis']
    STEP_LABELS = {
        'technical': '技术面分析',
        'fundamental': '基本面分析',
        'news': '消息面分析',
        'history': '历史信号回溯',
        'synthesis': '综合研判',
    }

    def __init__(self, data_manager=None):
        if data_manager is None:
            try:
                from app.data import DataManager
                data_manager = DataManager()
            except Exception:
                data_manager = None
        self.data_manager = data_manager
        self._partial_contexts: Dict[str, Dict] = {}

    def build_step(self, step: str, ts_code: str, **kwargs) -> Dict:
        """
        构建指定步骤的上下文

        Args:
            step: 步骤名 ('technical', 'fundamental', 'news', 'history', 'synthesis')
            ts_code: 股票代码
            kwargs: 额外参数（如 market_env, signals 等）

        Returns:
            该步骤的上下文 Dict
        """
        if step not in self.STEPS:
            raise ValueError(f"未知步骤: {step}，可用: {self.STEPS}")

        ctx = getattr(self, f'_build_{step}_context')(ts_code, **kwargs)
        self._partial_contexts[step] = ctx
        return ctx

    def get_partial_context(self, step: str) -> Dict:
        """获取已构建的某步骤上下文"""
        return self._partial_contexts.get(step, {})

    def get_all_contexts(self) -> Dict[str, Dict]:
        """获取所有已构建的上下文"""
        return dict(self._partial_contexts)

    def build_all(self, ts_code: str, **kwargs) -> Dict:
        """
        一次性构建所有步骤

        Args:
            ts_code: 股票代码
            kwargs: 可传入 market_env, signals, news_list 等
        """
        for step in self.STEPS:
            self.build_step(step, ts_code, **kwargs)
        return self._partial_contexts

    def to_prompt_section(self, steps: List[str] = None) -> str:
        """
        将指定步骤渲染为 AI 提示文本

        Args:
            steps: 步骤列表，默认全部

        Returns:
            str
        """
        if steps is None:
            steps = [s for s in self.STEPS if s in self._partial_contexts]

        lines = ['【多步骤分析上下文】']
        for step in steps:
            ctx = self._partial_contexts.get(step, {})
            label = self.STEP_LABELS.get(step, step)
            lines.append(f'\n--- {label} ---')
            lines.append(self._format_context(ctx))

        return '\n'.join(lines)

    def _build_technical_context(self, ts_code: str, **kwargs) -> Dict:
        """Step 1: 技术面上下文"""
        from datetime import datetime, timedelta
        ctx = {
            'ts_code': ts_code,
            'last_price': 0,
            'ma5': 0, 'ma10': 0, 'ma20': 0, 'ma60': 0,
            'volume_ratio': 1.0,
            'amplitude': 0,
            'patterns_detected': [],
        }
        try:
            from app.data.tushare_provider import TushareProvider
            provider = TushareProvider()
            end = datetime.now().strftime('%Y%m%d')
            start = (datetime.now() - timedelta(days=120)).strftime('%Y%m%d')
            data = provider.get_daily_data(ts_code, start, end)
            if data and len(data) >= 60:
                closes = [float(d['close']) for d in data]
                volumes = [float(d['vol']) for d in data]
                ctx['last_price'] = closes[-1]
                ctx['ma5'] = float(np.mean(closes[-5:])) if len(closes) >= 5 else 0
                ctx['ma10'] = float(np.mean(closes[-10:])) if len(closes) >= 10 else 0
                ctx['ma20'] = float(np.mean(closes[-20:])) if len(closes) >= 20 else 0
                ctx['ma60'] = float(np.mean(closes[-60:])) if len(closes) >= 60 else 0
                avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) > 21 else 0
                ctx['volume_ratio'] = round(volumes[-1] / max(avg_vol, 1), 2) if avg_vol > 0 else 1.0
                if len(closes) >= 2:
                    ctx['amplitude'] = round(abs(closes[-1] - closes[-2]) / closes[-2] * 100, 2)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f'技术面上下文构建失败: {e}')
        return ctx

    def _build_fundamental_context(self, ts_code: str, **kwargs) -> Dict:
        """Step 2: 基本面上下文"""
        ctx = {
            'ts_code': ts_code,
            'name': '',
            'industry': '',
            'pe': None,
            'pb': None,
            'market_cap': None,
            'profit_yoy': None,
        }
        try:
            from app.models import Stock
            stock = Stock.query.get(ts_code)
            if stock:
                ctx['name'] = getattr(stock, 'name', '') or ''
                ctx['industry'] = getattr(stock, 'industry', '') or ''
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f'基本面上下文构建失败: {e}')
        return ctx

    def _build_news_context(self, ts_code: str, **kwargs) -> Dict:
        """Step 3: 消息面上下文"""
        ctx = {'recent_news': [], 'sentiment': 'neutral', 'hot_topics': []}
        try:
            from app.data.news_provider import NewsProvider as NP
            provider = kwargs.get('news_provider', NP())
            news_list = kwargs.get('news_list', None) or provider.get_news(ts_code, days_back=3, max_count=5)
            ctx['recent_news'] = [n.to_dict() for n in news_list]
            if news_list:
                avg_sent = sum(n.sentiment for n in news_list) / len(news_list)
                ctx['sentiment'] = 'positive' if avg_sent > 0.1 else ('negative' if avg_sent < -0.1 else 'neutral')
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f'消息面上下文构建失败: {e}')
        return ctx

    def _build_history_context(self, ts_code: str, **kwargs) -> Dict:
        """Step 4: 历史信号上下文"""
        ctx = {
            'ts_code': ts_code,
            'previous_signals': [],
            'signal_count': 0,
            'last_analysis': None,
        }
        signals = kwargs.get('signals', [])
        if signals:
            ctx['previous_signals'] = signals[:5]
            ctx['signal_count'] = len(signals)
        return ctx

    def _build_synthesis_context(self, ts_code: str, **kwargs) -> Dict:
        """Step 5: 综合上下文 — 汇总前面的所有步骤"""
        summary = {
            'ts_code': ts_code,
            'steps_completed': list(self._partial_contexts.keys()),
            'overall_assessment': '',
        }
        tech = self._partial_contexts.get('technical', {})
        price = tech.get('last_price', 0)
        ma5 = tech.get('ma5', 0)
        ma60 = tech.get('ma60', 0)
        pe = self._partial_contexts.get('fundamental', {}).get('pe')
        news_sent = self._partial_contexts.get('news', {}).get('sentiment', 'neutral')

        assessments = []
        if price > 0 and ma5 > 0:
            assessments.append(f"当前价{price:.2f}" + ("站上MA5" if price > ma5 else "跌破MA5"))
        if price > 0 and ma60 > 0:
            assessments.append(f"{'站上' if price > ma60 else '处于'}MA60下方")
        if pe:
            assessments.append(f"PE={pe}" + ("(偏低)" if pe < 20 else "(合理)" if pe < 50 else "(偏高)"))
        assessments.append(f"消息面{news_sent}")
        summary['overall_assessment'] = ' | '.join(assessments)
        return summary

    def _format_context(self, ctx: Dict) -> str:
        """将 Dict 格式化为文本"""
        lines = []
        for k, v in ctx.items():
            if isinstance(v, list):
                if len(v) > 0:
                    lines.append(f"  {k}: {len(v)} 条")
            elif isinstance(v, dict):
                lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)[:100]}")
            else:
                lines.append(f"  {k}: {v}")
        return '\n'.join(lines)


# 快捷函数
def build_multistep_context(ts_code: str, steps: List[str] = None) -> Dict:
    builder = MultiStepContextBuilder()
    if steps:
        for step in steps:
            builder.build_step(step, ts_code)
    else:
        builder.build_all(ts_code)
    return builder.get_all_contexts()
