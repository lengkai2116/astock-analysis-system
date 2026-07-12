"""
AiConsensusEngine — 多角色AI研判共识与辩论引擎
============================================
在6角色独立研判完成后，对各方观点进行：
  1. 共识聚合：按置信度加权计算综合方向
  2. 辩论分析：识别分歧角色并提取正反论点，生成反驳
  3. 共识报告：输出结构化的共识等级/一致性/分歧焦点
"""

import logging
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 方向→分数映射 ──
# 注意：方向标签仅做粗粒度分类，有效评分 = direction_score × confidence
# 即"偏多(0.75) × 高置信度(0.9)=0.675" vs "偏多(0.75) × 低置信度(0.3)=0.225"
# 置信度差异通过乘法自然体现
DIRECTION_SCORE_MAP = {
    '看多': 1.0, '偏多': 0.75, '中性偏多': 0.6,
    '中性': 0.5, '中性偏空': 0.4, '偏空': 0.25, '看空': 0.0,
    '可参与': 0.6, '观望': 0.3,
}

# ── 共识等级阈值 ──
# ⚠️ 这些阈值为经验值，未经回测验证。不同市场状态下最优阈值可能不同。
# 当 completed_count 较少时，引擎自动提高阈值要求（见 _classify_consensus）
CONSENSUS_LEVELS = [
    ('strong_consensus', '高度一致', 0.8),
    ('consensus', '基本一致', 0.6),
    ('leaning', '倾向明显', 0.45),
    ('divided', '分歧明显', 0.35),
    ('conflicting', '强烈分歧', 0.0),
]

# ── 反驳论点生成规则库 ──
# 用于规则降级（当 DeepSeek 不可用时）。
# 每个规则由关键词匹配触发，比固定维度映射更灵活。
# 生产环境中应优先使用 DeepSeek 动态生成反驳。
_COUNTER_RULES = [
    # 技术面
    (['金叉', '突破', '放量'], '技术指标存在滞后性，突破需连续3日站稳确认'),
    (['底背离', '超卖', '超跌'], '超卖后可能继续超卖，需等待明确的企稳信号'),
    (['死叉', '破位', '放量下跌'], '技术面已破位，但短期跌幅过大可能触发反弹'),
    # 基本面
    (['PE', '估值', '市盈率'], '低估值不等于立即上涨，需结合盈利趋势判断'),
    (['ROE', '盈利', '利润'], '历史ROE不代表未来，需关注盈利趋势的可持续性'),
    (['增速放缓', '下滑', '下降'], '增速放缓但绝对水平仍高，需区分周期性与趋势性'),
    # 筹码
    (['主力', '大单', '机构'], '主力资金动向需持续观察3-5日确认方向'),
    (['北向', '外资'], '北向资金单日波动大，需看5日累计趋势'),
    (['融资', '杠杆'], '融资余额增长放缓时可能触发被动平仓'),
    # 情绪
    (['过热', '高潮'], '情绪过热时回调风险加大，但趋势可能延续'),
    (['冰点', '低迷'], '情绪冰点可能是布局时机，但需等待确认信号'),
    (['换手率'], '换手率异常需结合价格位置判断是吸筹还是出货'),
    # 消息面
    (['减持', '解禁'], '减持短期承压，但大股东减持不等于基本面变差'),
    (['利空', '监管', '政策收紧'], '利空已被部分定价，实际影响需看执行细节'),
    (['利好', '政策支持'], '利好可能已被市场提前消化，谨防高开低走'),
    # 风控
    (['波动率', '风险'], '波动率回归均值的概率较大，极端行情不可持续'),
    (['止损', '仓位'], '严格风控是长期生存的基础，不应因错过机会而放松'),
]


def _generate_counter(pro_point: str, con_point: str, pro_dimension: str) -> str:
    """
    根据实际观点内容动态生成反驳论点

    1. 优先从 pro_point 中匹配关键词生成针对性反驳
    2. 无匹配时从 con_point 提取关键词补充
    3. 完全无匹配时返回通用反驳
    """
    for keywords, counter in _COUNTER_RULES:
        for kw in keywords:
            if kw in pro_point:
                return counter
    # 尝试从空方观点匹配
    for keywords, counter in _COUNTER_RULES:
        for kw in keywords:
            if kw in con_point:
                return counter
    return '多空双方论据均存在不确定性，需结合实际走势进一步验证'

# ── 维度关键词映射（从角色名称推断分析维度）──
_ROLE_TO_DIMENSION = {
    'technical': '技术面', '技术研判': '技术面',
    'fundamental': '基本面', '基本面研判': '基本面',
    'chip': '筹码资金', '筹码资金研判': '筹码资金',
    'sentiment': '情绪面', '情绪研判': '情绪面',
    'news': '消息面', '消息面研判': '消息面',
    'risk': '风控', '风控研判': '风控',
}


@dataclass
class ConsensusResult:
    """共识计算结果"""
    overall_score: float = 0.5
    consensus_level: str = 'conflicting'
    consensus_label: str = '数据不足'
    direction: str = '中性'
    role_count: int = 0
    completed_count: int = 0
    agreement_rate: float = 0.0
    weighted_scores: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'overall_score': round(self.overall_score, 3),
            'consensus_level': self.consensus_level,
            'consensus_label': self.consensus_label,
            'direction': self.direction,
            'role_count': self.role_count,
            'completed_count': self.completed_count,
            'agreement_rate': round(self.agreement_rate, 3),
            'weighted_scores': self.weighted_scores,
        }


@dataclass
class DebatePoint:
    """辩论观点"""
    role_id: str
    role_name: str
    dimension: str           # 分析维度（技术面/基本面/筹码资金/情绪面/消息面/风控）
    direction: str
    score: float
    key_points: List[str]

    def to_dict(self) -> Dict:
        return {
            'role_id': self.role_id,
            'role_name': self.role_name,
            'dimension': self.dimension,
            'direction': self.direction,
            'score': round(self.score, 3),
            'key_points': self.key_points[:3],
        }


@dataclass
class DebatePair:
    """辩论配对 — 正反双方就同一维度的观点交锋"""
    dimension: str                              # 辩论维度
    pro_role: str                               # 看多方角色名
    con_role: str                               # 看空方角色名
    pro_point: str                              # 看多观点
    con_point: str                              # 看空观点
    counter_from_con: str = ''                  # 空方对多方观点的反驳
    counter_from_pro: str = ''                  # 多方对空方观点的反驳

    def to_dict(self) -> Dict:
        return {
            'dimension': self.dimension,
            'pro_role': self.pro_role,
            'con_role': self.con_role,
            'pro_point': self.pro_point,
            'con_point': self.con_point,
            'counter_from_con': self.counter_from_con,
            'counter_from_pro': self.counter_from_pro,
        }


@dataclass
class DebateResult:
    """辩论分析结果（增强版）"""
    has_disagreement: bool = False
    pro_arguments: List[DebatePoint] = field(default_factory=list)
    con_arguments: List[DebatePoint] = field(default_factory=list)
    neutral_arguments: List[DebatePoint] = field(default_factory=list)
    debate_pairs: List[DebatePair] = field(default_factory=list)   # 正反对阵配对
    debate_summary: str = ''
    debate_detail: str = ''                      # 详细辩论分析文本

    def to_dict(self) -> Dict:
        return {
            'has_disagreement': self.has_disagreement,
            'pro_count': len(self.pro_arguments),
            'con_count': len(self.con_arguments),
            'neutral_count': len(self.neutral_arguments),
            'debate_pair_count': len(self.debate_pairs),
            'pro_arguments': [p.to_dict() for p in self.pro_arguments],
            'con_arguments': [p.to_dict() for p in self.con_arguments],
            'neutral_arguments': [p.to_dict() for p in self.neutral_arguments],
            'debate_pairs': [p.to_dict() for p in self.debate_pairs],
            'debate_summary': self.debate_summary,
            'debate_detail': self.debate_detail,
        }


class AiConsensusEngine:
    """多角色AI研判共识与辩论引擎"""

    @staticmethod
    def _score_from_direction(direction: str) -> float:
        return DIRECTION_SCORE_MAP.get(direction, 0.5)

    @staticmethod
    def _direction_from_score(score: float) -> str:
        if score >= 0.7:
            return '看多'
        elif score >= 0.55:
            return '偏多'
        elif score >= 0.45:
            return '中性'
        elif score >= 0.3:
            return '偏空'
        return '看空'

    @staticmethod
    def _classify_consensus(avg_score: float, agreement_rate: float,
                            completed_count: int = 6, total_roles: int = 6) -> Tuple[str, str]:
        """综合评分+一致性比率+完成度 → 共识等级"""
        completion_ratio = completed_count / max(total_roles, 1)
        if completion_ratio < 0.5 or completed_count < 3:
            return 'conflicting', '数据不足'
        effective = avg_score * (0.5 + 0.5 * agreement_rate * completion_ratio)
        for level_id, level_label, threshold in CONSENSUS_LEVELS:
            if effective >= threshold:
                return level_id, level_label
        return 'conflicting', '强烈分歧'

    @staticmethod
    def _get_dimension(role_name: str) -> str:
        """从角色名推断分析维度"""
        for key, dim in _ROLE_TO_DIMENSION.items():
            if key in role_name or role_name in key:
                return dim
        return role_name

    @staticmethod
    def _extract_key_points(rdata: Dict) -> List[str]:
        """从角色数据中提取关键观点列表"""
        if isinstance(rdata.get('key_points'), list) and len(rdata['key_points']) > 0:
            return rdata['key_points']
        if isinstance(rdata.get('evidence'), list) and len(rdata['evidence']) > 0:
            return rdata['evidence']
        report = rdata.get('report') or rdata.get('analysis_report', '')
        if report:
            import re
            sentences = re.split(r'[。\n]+', report)
            points = [s.strip() for s in sentences if len(s.strip()) > 10]
            return points[:3] if points else [report[:120]]
        return []

    @staticmethod
    def _get_counter(pro_point: str, con_point: str) -> str:
        """根据实际观点内容动态生成反驳论点"""
        return _generate_counter(pro_point, con_point, '')

    # ── 共识计算 ──

    def compute_consensus(self, role_results: Dict[str, Dict]) -> ConsensusResult:
        if not role_results:
            return ConsensusResult()

        scores = []
        weighted_scores = []

        for rid, rdata in role_results.items():
            if rdata.get('status') != 'completed':
                continue
            direction = rdata.get('direction', '')
            if not direction or direction == '中性':
                # 方向为空或中性时使用默认权重
                direction_score = 0.5
                weight = 0.3
            else:
                direction_score = self._score_from_direction(direction)
                confidence = float(rdata.get('score', rdata.get('confidence', 0.5)))
                weight = max(0.3, min(1.0, confidence))
            scores.append((direction_score, weight))

            weighted_scores.append({
                'role_id': rid,
                'role_name': rdata.get('role_name', rid),
                'role_icon': rdata.get('role_icon', ''),
                'direction': direction,
                'direction_score': round(direction_score, 3),
                'confidence': round(weight, 3),
                'weighted_score': round(direction_score * weight, 3),
            })

        if not scores:
            return ConsensusResult()
        total_weight = sum(w for _, w in scores)
        if total_weight == 0:
            return ConsensusResult()

        overall = sum(s * w for s, w in scores) / total_weight
        values = [s for s, _ in scores]
        if len(values) >= 2:
            import statistics
            std = statistics.stdev(values)
            agreement_rate = max(0.0, 1.0 - std * 2.0)
        else:
            agreement_rate = 1.0

        level_id, level_label = self._classify_consensus(overall, agreement_rate, len(scores), len(role_results))
        direction = self._direction_from_score(overall)

        return ConsensusResult(
            overall_score=overall, consensus_level=level_id,
            consensus_label=level_label, direction=direction,
            role_count=len(role_results), completed_count=len(scores),
            agreement_rate=agreement_rate, weighted_scores=weighted_scores,
        )

    # ── 辩论分析（增强版）──

    def detect_debate(self, role_results: Dict[str, Dict]) -> DebateResult:
        """
        检测6角色之间的观点分歧，提取正反论点并生成反驳

        Args:
            role_results: {role_id: {status, direction, score, evidence, key_points, ...}}

        Returns:
            DebateResult 辩论分析结果（含辩论配对和反驳论点）
        """
        pro = []
        con = []
        neutral = []

        for rid, rdata in role_results.items():
            if rdata.get('status') != 'completed':
                continue
            direction = rdata.get('direction', '')
            if not direction:
                # API不可用导致角色失败，跳过
                continue
            score = self._score_from_direction(direction)
            confidence = float(rdata.get('score', rdata.get('confidence', 0.5)))
            role_name = rdata.get('role_name', rid)
            dimension = self._get_dimension(role_name)
            key_points = self._extract_key_points(rdata)

            dp = DebatePoint(
                role_id=rid, role_name=role_name, dimension=dimension,
                direction=direction, score=score * confidence,
                key_points=key_points,
            )

            if score >= 0.6:
                pro.append(dp)
            elif score <= 0.4:
                con.append(dp)
            else:
                neutral.append(dp)

        has_disagreement = len(pro) > 0 and len(con) > 0

        # 生成辩论配对（pro vs con 按维度匹配）
        debate_pairs = self._build_debate_pairs(pro, con)

        # 生成分歧摘要
        debate_summary = ''
        if has_disagreement:
            pro_roles = '、'.join(p.role_name for p in pro[:3])
            con_roles = '、'.join(c.role_name for c in con[:3])
            debate_summary = (
                f"{pro_roles}偏多，而{con_roles}偏空。"
            )

        # 生成详细辩论分析文本
        debate_detail = self._generate_debate_detail(debate_pairs, pro, con, neutral)

        # 尝试LLM增强辩论分析
        llm_detail = self._llm_debate_analysis(role_results, debate_pairs)
        if llm_detail:
            debate_detail = llm_detail

        return DebateResult(
            has_disagreement=has_disagreement,
            pro_arguments=sorted(pro, key=lambda x: x.score, reverse=True),
            con_arguments=sorted(con, key=lambda x: x.score),
            neutral_arguments=neutral,
            debate_pairs=debate_pairs,
            debate_summary=debate_summary,
            debate_detail=debate_detail,
        )

    def _build_debate_pairs(self, pro: List[DebatePoint], con: List[DebatePoint]) -> List[DebatePair]:
        """构建正反对阵配对：按维度匹配pro和con，生成反驳论点"""
        if not pro or not con:
            return []

        pairs = []
        used_pro = set()
        used_con = set()

        # 优先按相同维度配对
        for p in sorted(pro, key=lambda x: x.score, reverse=True):
            if p.role_id in used_pro:
                continue
            for c in sorted(con, key=lambda x: x.score):
                if c.role_id in used_con:
                    continue
                if p.dimension == c.dimension:
                    # 同维度正反配对
                    pro_point = p.key_points[0] if p.key_points else f'{p.role_name}看多'
                    con_point = c.key_points[0] if c.key_points else f'{c.role_name}看空'
                    pairs.append(DebatePair(
                        dimension=p.dimension,
                        pro_role=p.role_name,
                        con_role=c.role_name,
                        pro_point=pro_point,
                        con_point=con_point,
                        counter_from_con=self._get_counter(pro_point, con_point),
                        counter_from_pro=self._get_counter(con_point, pro_point),
                    ))
                    used_pro.add(p.role_id)
                    used_con.add(c.role_id)
                    break

        # 剩余未配对的pro和con做交叉配对
        remaining_pro = [p for p in pro if p.role_id not in used_pro]
        remaining_con = [c for c in con if c.role_id not in used_con]

        for p in remaining_pro:
            if not remaining_con:
                break
            c = remaining_con.pop(0)
            pp = p.key_points[0] if p.key_points else f'{p.role_name}看多'
            cp = c.key_points[0] if c.key_points else f'{c.role_name}看空'
            pairs.append(DebatePair(
                dimension='综合分析',
                pro_role=p.role_name,
                con_role=c.role_name,
                pro_point=pp,
                con_point=cp,
                counter_from_con=self._get_counter(pp, cp),
                counter_from_pro=self._get_counter(cp, pp),
            ))

        return pairs

    def _generate_debate_detail(self, debate_pairs: List[DebatePair],
                                 pro: List[DebatePoint],
                                 con: List[DebatePoint],
                                 neutral: List[DebatePoint]) -> str:
        """生成结构化辩论分析文本（基于规则的详细分析）"""
        parts = []

        if not debate_pairs:
            if pro and not con:
                parts.append('各角色方向一致看多，无明显分歧。')
            elif con and not pro:
                parts.append('各角色方向一致看空，无明显分歧。')
            else:
                parts.append('各角色无明显方向性分歧。')
            return '\n'.join(parts)

        # 辩论维度分析
        dimensions = set(p.dimension for p in debate_pairs)
        parts.append(f'【分歧维度】共{len(debate_pairs)}组观点交锋，涉及{len(dimensions)}个维度。')
        for pair in debate_pairs:
            parts.append(
                f'■ {pair.dimension}：{pair.pro_role}(看多) vs {pair.con_role}(看空)\n'
                f'  多方：{pair.pro_point}\n'
                f'  空方：{pair.con_point}\n'
                f'  反驳：{pair.counter_from_con}'
            )

        # 强度对比
        if pro and con:
            avg_pro = sum(p.score for p in pro) / len(pro)
            avg_con = sum(c.score for c in con) / len(con)
            stronger = '多方' if avg_pro > avg_con else '空方'
            parts.append(f'【强度对比】多方均分{avg_pro:.2f} vs 空方均分{avg_con:.2f}，{stronger}论据强度略占优。')

        return '\n'.join(parts)

    def _llm_debate_analysis(self, role_results: Dict[str, Dict],
                              debate_pairs: List[DebatePair]) -> Optional[str]:
        """
        使用 DeepSeek 进行深度辩论分析
        当 DeepSeek API 可用时调用，不可用时返回 None 降级到规则分析
        """
        if not debate_pairs:
            return None

        try:
            from app.core import config
            provider = config.get('llm_provider', 'mock')
            if provider == 'mock':
                return None

            api_key = config.get('deepseek_api_key', '')
            if not api_key:
                return None

            # 构造辩论Prompt
            role_summaries = []
            for rid, rdata in role_results.items():
                if rdata.get('status') == 'completed':
                    report = (rdata.get('report') or rdata.get('analysis_report', ''))[:200]
                    role_summaries.append(
                        f"[{rdata.get('role_name', rid)}] 方向={rdata.get('direction','中性')} "
                        f"信心={rdata.get('score', 0.5)} 要点={report}"
                    )

            prompt = (
                '你是一名专业的A股辩论分析师。请对以下多角色AI研判结果进行辩论分析。\n\n'
                '各角色研判摘要：\n' + '\n'.join(role_summaries) + '\n\n'
                '请按以下结构输出：\n'
                '1. 核心分歧：哪些维度存在显著分歧，分歧的本质是什么\n'
                '2. 多方逻辑链：看多角色的核心逻辑和关键论据\n'
                '3. 空方逻辑链：看空角色的核心逻辑和关键论据\n'
                '4. 辩论焦点：多空双方最关键的3个争议点\n'
                '5. 综合评估：你认为哪方逻辑更强，以及当前不确定性最大的因素\n\n'
                '请用中文、专业、客观的语气分析。'
            )

            import requests
            endpoint = config.get('deepseek_endpoint', 'https://api.deepseek.com/v1')
            model = config.get('deepseek_model', 'deepseek-v4-flash')

            resp = requests.post(
                f'{endpoint}/chat/completions',
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                json={
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': '你是一名专业的A股辩论分析师，擅长从多角色研判结果中提取分歧焦点并进行客观分析。'},
                        {'role': 'user', 'content': prompt},
                    ],
                    'temperature': 0.5,
                    'max_tokens': 2048,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.debug(f'DeepSeek辩论分析不可用，使用规则降级: {e}')

        return None

    # ── 一站式分析 ──

    def full_analysis(self, role_results: Dict[str, Dict]) -> Dict:
        """
        一站式：共识 + 辩论 + 综合报告
        Returns: 完整共识分析结果字典
        """
        consensus = self.compute_consensus(role_results)
        debate = self.detect_debate(role_results)

        # ── 基于实际分析内容生成建议（非模板）──
        completed_roles = []
        for rid, rdata in role_results.items():
            if rdata.get('status') == 'completed' and rdata.get('direction'):
                completed_roles.append({
                    'name': rdata.get('role_name', rid),
                    'direction': rdata.get('direction', ''),
                    'key_point': rdata.get('key_points', [None])[0] if rdata.get('key_points') else '',
                })

        # 统计看多/看空角色数量
        bullish = sum(1 for r in completed_roles if r['direction'] in ('看多', '偏多', '中性偏多'))
        bearish = sum(1 for r in completed_roles if r['direction'] in ('看空', '偏空', '中性偏空'))
        neutral = len(completed_roles) - bullish - bearish

        total = len(completed_roles)
        advice_parts = []

        if total == 0:
            advice_parts.append('AI分析不可用，无法生成综合建议')
        elif consensus.consensus_level in ('strong_consensus', 'consensus'):
            # 高度一致：列出一致看多/看空的角色和核心理由
            majority_dir = '看多' if bullish > bearish else '看空'
            majority_roles = [r for r in completed_roles if r['direction'] in (
                ('看多', '偏多', '中性偏多') if majority_dir == '看多'
                else ('看空', '偏空', '中性偏空')
            )]
            role_names = '、'.join(r['name'] for r in majority_roles[:3])
            key_pts = [r['key_point'] for r in majority_roles[:2] if r['key_point']]
            reason = '（' + '；'.join(key_pts) + '）' if key_pts else ''
            advice_parts.append(f'多角色一致{majority_dir}：{role_names}{reason}')
        elif consensus.consensus_level == 'leaning':
            # 倾向明显：指出多数和少数
            majority = '看多' if bullish > bearish else '看空'
            majority_names = '、'.join(r['name'] for r in completed_roles[:3] if (
                r['direction'] in ('看多', '偏多') if majority == '看多'
                else r['direction'] in ('看空', '偏空')
            ))
            minority_roles = [r for r in completed_roles if (
                r['direction'] in ('看空', '偏空') if majority == '看多'
                else r['direction'] in ('看多', '偏多')
            )]
            minority_names = '、'.join(r['name'] for r in minority_roles[:2])
            advice_parts.append(f'多数角色倾向{majority}：{majority_names}')
            if minority_names:
                advice_parts.append(f'存在分歧：{minority_names}持相反观点，需注意风险')
        else:
            # 分歧明显：指出冲突维度
            if debate.debate_pairs:
                dims = set(p.dimension for p in debate.debate_pairs)
                advice_parts.append(f'角色间存在明显分歧，涉及{len(dims)}个维度（{"、".join(dims)}）')
            else:
                advice_parts.append('各角色方向分散，暂未形成明确共识')

        # 补充置信度信息
        if consensus.agreement_rate < 0.3 and total >= 3:
            advice_parts.append('一致性较低，建议等待更多确认信号')

        advice = '；'.join(advice_parts) if advice_parts else '无法生成综合建议'

        return {
            'consensus': consensus.to_dict(),
            'debate': debate.to_dict(),
            'advice': advice,
            'has_consensus': consensus.consensus_level in ('strong_consensus', 'consensus'),
            'has_conflict': debate.has_disagreement,
        }
