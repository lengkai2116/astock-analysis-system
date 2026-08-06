"""
L4 交叉验证仲裁层 — 共识投票引擎

12 个标签独立投票 + 情绪加权 + 估值退出跟踪

四步串联：
  Step A: 前置估值门禁
  Step B: 情绪环境全局加权
  Step C: 共识投票（VOTE_MAP）
  Step D: 结果映射
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)

# ── 标签 → 中文名映射 ─────────────────────────────────────
TAG_LABELS: dict[str, str] = {
    'main_force_phase': '主力阶段',
    'valuation_level': '估值水平',
    'trend_alignment': '多周期趋势',
    'fund_flow': '资金流向',
    'fina_health': '财务健康',
    'catalyst_event': '催化剂事件',
    'sentiment_phase': '市场情绪',
    'signal_strength': '信号强度',
    'buy_sell_point': '买卖点信号',
    'ma_alignment': '均线排列',
    'price_position': '价格位置',
    'sector_heat': '板块热度',
    # 316号 P3：扩展票源
    'small_cap': '市值规模',
    'low_vol': '波动水平',
    'liquidity': '流动性',
}

# ── 投票映射表 ────────────────────────────────────────────
VOTE_MAP: dict[str, dict[str | int, int]] = {
    'main_force_phase': {
        'building': 1, 'washing': 0, 'lifting': 1,
        'distributing': -1, 'unknown': 0,
    },
    'valuation_level': {'extreme_low': 1, 'low': 1, 'fair': 0, 'high': -1, 'extreme_high': -1},
    'trend_alignment': {'up_aligned': 1, 'down_aligned': -1, 'mixed': 0, 'no_trend': 0},
    'fund_flow': {'5d_inflow': 1, '5d_outflow': -1, 'mixed': 0, 'none': 0},
    'fina_health': {'pass': 1, 'suspicious': 0, 'fail': -1},  # 316号P2：suspicious→0（存疑≠看空，对齐033标尺）
    'catalyst_event': {
        'earnings': 1, 'lhb': 1, 'concept': 1, 'buyback': 1, 'breakout': 1,
        'pledge': -1, 'float': -1, 'reduce': -1, 'fraud_sign': -1, 'regulatory': -1, 'none': 0,
    },
    # 316号P2：sentiment_phase 移出个股票源（313 §4.1 情绪=环境变量，由 Step B 权重矩阵处理，不投票）
    'signal_strength': {},  # 0-100 数值映射（313号）：>=70→+1, <=40→-1（见 _lookup_vote）
    'buy_sell_point': {
        'first_buy': 1, 'first_buy_p': 1, 'second_buy': 1,
        'third_buy': 1, 'third_buy_a': 1, 'third_buy_b': 1,
        'first_sell': -1, 'first_sell_p': -1, 'second_sell': -1,
        'third_sell': -1, 'none': 0,
    },
    'ma_alignment': {'bullish': 1, 'bearish': -1, 'mixed': 0},
    'price_position': {'low_zone': 1, 'mid_zone': 0, 'high_zone': -1},
    # 316号P2：sector none→0（无热度≠看空）、top_20→+0.5（弱看多）
    'sector_heat': {'top_10': 1, 'top_20': 0.5, 'normal': 0, 'none': 0},
    # ── 309号 决策4 新增票源：量价形态 + 闸门2右侧确认 ──
    # 316号 P5：扩展覆盖 EnhancedPatternDetector 实际输出形态（70+ 中文形态，split('(')[0] 后标签值）
    'pattern_signal': {
        # 看涨（预涨，19 旧 + 检测器实际输出）
        'double_bottom': 1, 'breakout': 1, '红三兵': 1, '三白兵': 1, '双针探底': 1,
        '三阳开泰': 1, '低位横盘突破': 1, '放量站上60日线': 1, '平台放量突破': 1,
        '地量后倍量启动': 1, '阳吞阴反击': 1, '密底放量': 1, '震仓向上': 1,
        '晨星': 1, '看涨吞没': 1, '锤子线': 1, '镊子底': 1, '刺透形态': 1,
        # P5 补充（EnhancedPatternDetector 中文形态）
        'MA5金叉MA10': 1, '均线多头排列': 1, '连续站上60日线': 1, 'MA5上穿MA20': 1,
        '回踩MA60获支撑': 1, 'MA5上穿MA60': 1, '看涨孕线': 1, '十字晨星': 1,
        '看涨捉腰带': 1, '倒锤子': 1, '看涨踢开': 1, '连续小阳盘升': 1, '灼阳形态': 1,
        '低位崛起反击': 1, '双阳缺口': 1, '三连阴缩量': 1, '放量跳空阴阳': 1,
        '振幅收敛趋稳': 1, '低位伏击反击': 1, '连续低位反复': 1, '三线开花多头': 1,
        'MA30>MA60': 1, '站上MA120': 1, '站上MA250': 1,
        '格兰维尔买点1-突破买': 1, '格兰维尔买点2-回踩买': 1,
        '格兰维尔买点3-偏离买': 1, '格兰维尔买点4-新低买': 1,
        '涨停形态': 1, 'W底': 1, '下降楔形': 1, '突破缺口': 1,
        '地量后的倍量启动': 1, '低位连续小阳线黑马前奏': 1,
        # 看跌（预跌）
        '乌云盖顶': -1, '黄昏星': -1, '看跌吞没': -1, '射击之星': -1,
        '三乌鸦': -1, '上吊线': -1, '放量冲高回落': -1, '天量天价': -1,
        '放量滞涨': -1, '跳空高开低走': -1, '放量长阴': -1, '高台跳水': -1,
        # P5 补充（看跌）
        'MA5死叉MA10': -1, '均线空头排列': -1, '看跌孕线': -1, '看跌捉腰带': -1,
        '看跌踢开': -1, '三线开花空头': -1,
        '格兰维尔卖点1-跌破卖': -1, '格兰维尔卖点2-反抽卖': -1,
        '格兰维尔卖点3-偏离卖': -1, '格兰维尔卖点4-新高卖': -1,
        '头肩顶': -1, '上升楔形': -1, '扩散三角形': -1, 'M顶': -1, '衰竭缺口': -1,
        '跳空高开低走巨量阴线': -1,
    },
    'right_side_confirm': {'强确认': 1, '基础确认': 0, '未确认': 0, '否决': -1},
    # ── 316号 P3：扩展票源（规模/低波动/流动性）— 默认关闭（L4_EXTRA_VOTES=1 启用），见 _lookup_vote ──
    'small_cap': {},
    'low_vol': {},
    'liquidity': {},
}

# ── 投票原因模板 ──────────────────────────────────────────
VOTE_REASONS: dict[str, dict[str | int, str]] = {
    'main_force_phase': {
        'building': '建仓期，主力资金持续介入',
        'washing': '洗盘期，方向待确认',
        'lifting': '拉升期，趋势强劲',
        'distributing': '出货期，主力离场风险',
        'unknown': '主力阶段不明',
    },
    'valuation_level': {
        'extreme_low': '处于极度低估区间，安全边际充足',
        'low': '处于低估区间，安全边际充足',
        'fair': '估值合理，无显著偏差',
        'high': '处于高估区间，估值压力较大',
        'extreme_high': '处于极度高估区间，估值泡沫风险',
    },
    'trend_alignment': {
        'up_aligned': '短/中/长周期趋势方向一致向上',
        'down_aligned': '短/中/长周期趋势方向一致向下',
        'mixed': '多周期趋势方向不一致',
        'no_trend': '无明显趋势',
    },
    'fund_flow': {
        '5d_inflow': '近5日大单资金持续净流入',
        '5d_outflow': '近5日大单资金持续净流出',
        'mixed': '资金流向分歧',
        'none': '无明显资金信号',
    },
    'fina_health': {
        'pass': '财务健康，ROCE达标，资产负债率合理',
        'suspicious': '财务指标存疑，需关注',
        'fail': '财务健康评级不通过',
    },
    'catalyst_event': {
        'earnings': '业绩超预期催化剂',
        'lhb': '龙虎榜机构席位大额买入',
        'concept': '概念板块活跃联动',
        'buyback': '公司回购注销，积极信号',
        'breakout': '技术形态突破确认',
        'pledge': '股权质押比例过高风险',
        'float': '限售股解禁抛压风险',
        'reduce': '大股东减持预披露',
        'fraud_sign': '财务异常信号',
        'regulatory': '监管异常/立案调查风险',
        'none': '无明显催化剂',
    },
    'sentiment_phase': {
        'ice': '市场情绪冰点',
        'recovery': '情绪复苏期，利于做多',
        'climax': '情绪高潮期，过热风险',
        'ebb': '情绪退潮期，环境不利',
    },
    'signal_strength': {},
    'buy_sell_point': {
        'first_buy': '缠论第一类买点（趋势转折早期，左侧信号）',
        'first_buy_p': '缠论类一买（盘整背驰）',
        'second_buy': '缠论第二类买点（回抽不破前低，右侧确认）',
        'third_buy': '缠论第三类买点（中枢突破回抽确认，右侧追击）',
        'third_buy_a': '缠论三买a型',
        'third_buy_b': '缠论三买b型',
        'first_sell': '缠论第一类卖点',
        'first_sell_p': '缠论类一卖',
        'second_sell': '缠论第二类卖点',
        'third_sell': '缠论第三类卖点',
        'none': '无明显买卖点信号',
    },
    'ma_alignment': {
        'bullish': '均线多头排列，趋势向上',
        'bearish': '均线空头排列，趋势向下',
        'mixed': '均线交叉，方向分歧',
    },
    'price_position': {
        'low_zone': '处于近期低位区间',
        'mid_zone': '处于近期中位区间',
        'high_zone': '处于近期高位区间',
    },
    'sector_heat': {
        'top_10': '板块热度排名前10',
        'top_20': '板块热度排名前20',
        'normal': '板块热度一般',
        'none': '板块热度不足',
    },
    'pattern_signal': {
        'double_bottom': '双底形态确认',
        'breakout': '突破形态确认',
        '红三兵': '红三兵放量上涨',
        '三白兵': '三白兵持续上涨',
        '双针探底': '双针探底底部确认',
        '三阳开泰': '三阳开泰强势形态',
        '低位横盘突破': '低位横盘后突破',
        '放量站上60日线': '放量站上60日均线',
        '平台放量突破': '平台放量向上突破',
        '地量后倍量启动': '地量后倍量启动',
        '阳吞阴反击': '阳线吞没阴线反击',
        '密底放量': '密集底部放量',
        '震仓向上': '震仓后向上',
        '晨星': '晨星底部反转',
        '看涨吞没': '看涨吞没形态',
        '锤子线': '锤子线底部信号',
        '镊子底': '镊子底双底确认',
        '刺透形态': '刺透形态反转',
        '乌云盖顶': '乌云盖顶顶部反转',
        '黄昏星': '黄昏星顶部反转',
        '看跌吞没': '看跌吞没形态',
        '射击之星': '射击之星顶部信号',
        '三乌鸦': '三乌鸦持续下跌',
        '上吊线': '上吊线顶部信号',
        '放量冲高回落': '放量冲高回落（预跌）',
        '天量天价': '天量天价（预跌）',
        '放量滞涨': '放量滞涨（预跌）',
        '跳空高开低走': '跳空高开低走（预跌）',
        '放量长阴': '放量长阴（预跌）',
        '高台跳水': '高台跳水破位（预跌）',
    },
    'right_side_confirm': {
        '强确认': '右侧强确认（突破+结构+趋势背书）',
        '基础确认': '右侧基础确认（仅基础信号）',
        '未确认': '右侧信号未确认',
        '否决': '右侧否决（卖出/背离/预跌信号）',
    },
}

# ── 短线标签（climax 情绪下被折扣的标签集合）───────────────
SHORT_TERM_TAGS = {
    'fund_flow', 'sector_heat', 'buy_sell_point',
    'catalyst_event', 'sentiment_phase', 'pattern_signal',
}

# ── 316号 P3：动量票源（climax 额外降权——追高风险）与质量票源（ice 升权——均值回归机会） ──
MOMENTUM_TAGS = {'trend_alignment', 'buy_sell_point', 'pattern_signal', 'ma_alignment'}
QUALITY_TAGS = {'valuation_level', 'fina_health', 'price_position', 'small_cap', 'low_vol'}


class L4CrossValidator(DataAwareMixin):
    """L4 共识投票引擎"""

    def __init__(self, data_manager=None):
        self._dm = data_manager  # DataAwareMixin 统一注入点

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    def diagnose(self, ts_code: str, tags: dict = None) -> dict:
        """执行 L4 交叉验证诊断

        Args:
            ts_code: 股票代码
            tags: 预加载的标签字典（如为 None 则从 ECM 读取）

        Returns:
            诊断 JSON（294号§十格式）
        """
        if tags is None:
            tags = self._load_tags(ts_code)

        name = self._get_stock_name(ts_code)

        # ── Step A: 前置门禁评估（316号 P1：分级 + 风险项，不再投票前硬截断） ──
        # 门禁结果在操作建议合成后应用（§3.3 门禁后移）：深度高估/负面事件才否决，
        # 中/轻度与软风险作仓位约束 + 风险标注——强确认+高共识的合理偏贵股不再被吞
        gate = self._evaluate_gate(ts_code, tags)

        # ── 日线数据加载（316号 P4：操作建议的入场/止损/目标点位计算；P3 扩展票源复用） ──
        df = None
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            df = get_ecm_instance().get_cached_daily(ts_code)
        except Exception:
            pass

        # ── 316号 P3：扩展票源（规模/低波动/流动性）— 默认关闭（L4_EXTRA_VOTES=1 启用） ──
        if os.getenv('L4_EXTRA_VOTES') == '1':
            try:
                dm = self._get_dm()
                df_b = dm.get_cached_daily_basic(ts_code)
                if df_b is not None and not df_b.empty:
                    last = df_b.iloc[-1]
                    mv = float(last.get('total_mv') or 0) if 'total_mv' in df_b.columns else 0
                    tr = float(last.get('turnover_rate') or 0) if 'turnover_rate' in df_b.columns else None
                    # 规模：<100亿 小盘(+1) / >500亿 大盘(-1) / 中间 0（total_mv 单位=万元）
                    tags.setdefault('small_cap', 'small' if 0 < mv < 1e6 else ('big' if mv >= 5e6 else 'mid'))
                    if tr is not None:
                        tags.setdefault('liquidity', 'low' if tr < 1.0 else 'ok')
                # 低波动：20 日日收益率标准差（低<2% / 高>3.5%）
                if df is not None and len(df) >= 20 and 'close' in df.columns:
                    rets = df['close'].pct_change().dropna().tail(20)
                    std = float(rets.std() * 100)
                    tags.setdefault('low_vol', 'low' if std < 2.0 else ('high' if std > 3.5 else 'mid'))
            except Exception:
                pass

        # ── 并行计算退出跟踪 ──
        valuation_tracking = self._check_valuation_exit(ts_code, tags)

        # ── Step B: 情绪加权 ──
        sentiment_phase = tags.get('sentiment_phase', '')
        sentiment_weight, adjusted_votes = self._apply_sentiment_weight(sentiment_phase, tags)

        # ── Step C: 共识投票 + Step D: 结果映射 ──
        consensus, voting_detail = self._compute_consensus(tags, adjusted_votes)

        # ── 汇总输出 ──
        verdict = self._build_verdict(consensus, voting_detail)
        signal_strength = self._safe_float(tags.get('signal_strength'), 0)
        signal_strength_adjusted = self._compute_signal_strength_adjusted(tags, signal_strength)

        # ── 并行计算日常变化（299号§5.1 变更检测归属L4） ──
        daily_change = self._compute_daily_change(ts_code, tags)

        operation_advice = self._build_operation_advice(ts_code, consensus, tags, signal_strength, gate, df)
        risk_warnings = self._build_risk_warnings(tags, gate)
        user_checklist = self._build_user_checklist(ts_code, tags, valuation_tracking)
        opportunity_summary = self._build_opportunity_summary(tags, consensus, risk_warnings)
        tags_summary = self._build_tags_summary(tags)

        return {
            'ts_code': ts_code,
            'name': name,
            'diagnosis_date': datetime.now().strftime('%Y-%m-%d'),
            'opportunity_summary': opportunity_summary,
            'tags_summary': tags_summary,
            'cross_validation': {
                'consensus': consensus,
                'sentiment_weight': sentiment_weight,
                'voting_detail': voting_detail,
                'verdict': verdict,
                'user_checklist': user_checklist,
                'daily_change_summary': daily_change,
            },
            'operation_advice': operation_advice,
            'risk_warnings': risk_warnings,
            'gate': gate,  # 316号 P1：门禁评估结果（估值分级 + 风险项）
            'valuation_tracking': valuation_tracking,
            'signal_strength_adjusted': signal_strength_adjusted,
        }

    # ══════════════════════════════════════════════════════════
    # Step A: 前置估值门禁（316号 P1：分级 + 风险项扩展，不再投票前硬截断）
    # ══════════════════════════════════════════════════════════

    def _evaluate_gate(self, ts_code: str, tags: dict) -> dict:
        """估值分级 + 风险项识别（316号 §3.2/§3.4）

        估值分级（连续偏离度，不依赖 5 档 level）：
          deep     PE 历史分位 >90 或 deviation < -20   → 深度高估（泡沫，不推荐）
          moderate PE 分位 >80 或 deviation < -12       → 中度偏高（仓位减半）
          mild     PE 分位 >60 或 deviation < -6        → 轻度偏高（仓位压缩一档）
        风险项：
          hard_risks  event_negative（欺诈/监管事件）→ 直接不推荐
          soft_risks  fina_fail / distributing / low_liquidity（换手率<1%）→ 仓位压缩

        Returns: {'valuation': 'none'|'mild'|'moderate'|'deep',
                  'hard_risks': [], 'soft_risks': []}
        """
        gate: dict[str, Any] = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}

        # ── 估值分级（pe_percentile_5y 历史分位 + deviation，负=高估） ──
        try:
            pe_pct = self._safe_float(tags.get('pe_percentile_5y'), None)
            dev = self._safe_float(tags.get('valuation_deviation'), None)
            lv = 'none'
            if (pe_pct is not None and pe_pct > 90) or (dev is not None and dev < -20):
                lv = 'deep'
            elif (pe_pct is not None and pe_pct > 80) or (dev is not None and dev < -12):
                lv = 'moderate'
            elif (pe_pct is not None and pe_pct > 60) or (dev is not None and dev < -6):
                lv = 'mild'
            gate['valuation'] = lv
        except Exception:
            pass

        # ── 硬风险：监管立案（真硬风险，不可逆） → 直接不推荐 ──
        if tags.get('catalyst_event') == 'regulatory':
            gate['hard_risks'].append('event_negative')

        # ── 软风险：仓位约束 ──
        # 财务异常（fraud_sign 已修正语义=经营恶化非欺诈，2026-08-05）→ 仓位约束而非否决
        if tags.get('catalyst_event') == 'fraud_sign':
            gate['soft_risks'].append('fina_weak')
        if tags.get('fina_health') == 'fail':
            gate['soft_risks'].append('fina_fail')
        if tags.get('main_force_phase') == 'distributing':
            gate['soft_risks'].append('distributing')
        # 流动性：换手率 <1%（daily_basic 最新）
        try:
            df = self._get_dm().get_cached_daily_basic(ts_code)
            if df is not None and not df.empty and 'turnover_rate' in df.columns:
                tr = df['turnover_rate'].dropna()
                if not tr.empty and float(tr.iloc[-1]) < 1.0:
                    gate['soft_risks'].append('low_liquidity')
        except Exception:
            pass

        return gate

    def _build_gate_denied(self, ts_code: str, name: str, tags: dict) -> dict:
        """估值偏高时返回门禁拒绝结果"""
        VAL_MAP = {'extreme_low': '极度低估', 'low': '偏低', 'fair': '合理',
                    'high': '偏高', 'extreme_high': '极度高估'}
        val_label = VAL_MAP.get(tags.get('valuation_level', ''), '未知')
        return {
            'ts_code': ts_code,
            'name': name,
            'diagnosis_date': datetime.now().strftime('%Y-%m-%d'),
            'opportunity_summary': {
                'score': 0,
                'grade': 'D',
                'risk_level': 'high',
                'time_horizon': tags.get('opportunity_label', tags.get('opportunity_type', 'unknown')),
                'verification': '✗ 估值门禁拒绝：估值偏高，不推荐介入',
            },
            'tags_summary': self._build_tags_summary(tags),
            'cross_validation': {
                'consensus': {'bullish_votes': 0, 'bearish_votes': 0, 'neutral_votes': 0,
                              'total_active': 0, 'consensus_rate': 0, 'direction': 'neutral'},
                'sentiment_weight': 1.0,
                'voting_detail': [],
                'verdict': f'当前估值{val_label}，不推荐介入。',
                'user_checklist': [f'ℹ 估值{val_label}，建议等待回调至合理区间'],
            },
            'operation_advice': {
                'action': 'not_recommended', 'label': '不推荐',
                'max_position_ratio': 0, 'entry_plan': [], 'stop_loss': None, 'target_price': None,
            },
            'risk_warnings': [{'type': 'valuation', 'content': '估值偏高，安全边际不足'}],
            'valuation_tracking': self._check_valuation_exit(ts_code, tags),
            'signal_strength_adjusted': 0,
        }

    # ══════════════════════════════════════════════════════════
    # Step B: 情绪加权
    # ══════════════════════════════════════════════════════════

    def _apply_sentiment_weight(
        self, sentiment_phase: str, tags: dict,
    ) -> tuple[float, dict[str, float]]:
        """根据情绪阶段调整投票权重

        Returns:
            (sentiment_weight, adjusted_votes)
            adjusted_votes: {tag: weighted_vote_value}
        """
        weight = 1.0
        adjustments: dict[str, float] = {}

        if sentiment_phase == 'ebb':
            weight = 0.7
        elif sentiment_phase == 'climax':
            weight = 0.7
        elif sentiment_phase == 'ice':
            weight = 0.7
        # recovery → weight stays 1.0

        # 对每个标签调整原始投票
        for tag_name in VOTE_MAP:
            raw_value = tags.get(tag_name)
            if raw_value is None or raw_value == '':
                continue

            vote = self._lookup_vote(tag_name, raw_value)
            adjusted = float(vote)

            if sentiment_phase == 'ebb':
                # 所有看多票折扣
                if vote > 0:
                    adjusted = vote * weight
            elif sentiment_phase == 'climax':
                # 短线标签看多票折扣 + 动量票源额外降权（316号 P3：高潮期动量追高风险）
                if vote > 0:
                    if tag_name in MOMENTUM_TAGS:
                        adjusted = vote * 0.6
                    elif tag_name in SHORT_TERM_TAGS:
                        adjusted = vote * weight
            elif sentiment_phase == 'ice':
                # 看空票折扣；质量/估值票看多升权（316号 P3：冰点期均值回归机会）
                if vote < 0:
                    adjusted = vote * weight
                elif vote > 0 and tag_name in QUALITY_TAGS:
                    adjusted = vote * 1.2

            adjustments[tag_name] = adjusted

        return weight, adjustments

    # ══════════════════════════════════════════════════════════
    # Step C: 共识投票
    # ══════════════════════════════════════════════════════════

    def _compute_consensus(self, tags: dict, adjusted_votes: dict[str, float]) -> tuple[dict, list]:
        """执行共识投票统计"""
        bullish = 0
        bearish = 0
        neutral = 0
        total_active = 0
        detail: list[dict] = []

        for tag_name in VOTE_MAP:
            raw_value = tags.get(tag_name)
            if raw_value is None or raw_value == '':
                continue

            raw_vote = self._lookup_vote(tag_name, raw_value)
            adj_vote = adjusted_votes.get(tag_name, float(raw_vote))
            total_active += 1

            if raw_vote > 0:
                bullish += 1
            elif raw_vote < 0:
                bearish += 1
            else:
                neutral += 1

            # 投票明细
            label = TAG_LABELS.get(tag_name, tag_name)
            if tag_name == 'signal_strength':
                value_str = str(raw_value)
                reason = f'信号强度{value_str}分' + (
                    '（强信号，看多）' if raw_vote > 0
                    else '（弱信号，看空）' if raw_vote < 0
                    else '（中性）'
                )
            else:
                reason_map = VOTE_REASONS.get(tag_name, {})
                reason = reason_map.get(str(raw_value), reason_map.get(raw_value, ''))

            vote_str = (
                '+1 看多' if adj_vote > 0 else
                '-1 看空' if adj_vote < 0 else
                '0 中性'
            )
            detail.append({
                'tag': tag_name,
                'label': label,
                'value': str(raw_value),
                'vote': vote_str,
                'reason': reason,
            })

        # 兜底：标签数据不足
        if total_active < 3:
            return {
                'bullish_votes': 0, 'bearish_votes': 0, 'neutral_votes': 0,
                'total_active': total_active, 'consensus_rate': 0, 'direction': 'neutral',
                'tie': False,
            }, detail

        # 确定方向（316号 P2：共识率用方向票分母——中性票不稀释方向共识；
        # rate = 优势方向票 / (看多+看空)，全中性 → 0）
        direction_active = bullish + bearish
        if direction_active > 0 and bullish > bearish:
            direction = 'bullish'
            rate = bullish / direction_active
        elif bearish > bullish:
            direction = 'bearish'
            rate = bearish / direction_active
        else:
            # L2修复：多空打平 → 标记"多空分歧"（tie=True），供前端显示而非误导为 0%
            direction = 'neutral'
            rate = 0

        return {
            'bullish_votes': bullish,
            'bearish_votes': bearish,
            'neutral_votes': neutral,
            'total_active': total_active,
            'consensus_rate': round(rate, 3),
            'direction': direction,
            'tie': bullish == bearish and bullish > 0,
        }, detail

    @staticmethod
    def _lookup_vote(tag_name: str, value: Any) -> int:
        """查找单个标签的投票值"""
        mapping = VOTE_MAP.get(tag_name)
        if mapping is None:
            return 0
        # 316号 P3：扩展票源（规模/低波动/流动性）— 值由 diagnose 计算
        if tag_name == 'small_cap':
            return 1 if value == 'small' else (-1 if value == 'big' else 0)
        if tag_name == 'low_vol':
            return 1 if value == 'low' else (-1 if value == 'high' else 0)
        if tag_name == 'liquidity':
            return -1 if value == 'low' else 0
        # signal_strength 是数值映射
        if tag_name == 'signal_strength':
            try:
                v = float(value)
                # 313号：signal_strength 改为 0-100 潜力强度（旧 0-10 的 ×10 迁移）
                if v >= 70.0:
                    return 1
                if v <= 40.0:
                    return -1
                return 0
            except (ValueError, TypeError):
                return 0
        return mapping.get(value, mapping.get(str(value), 0))

    # ══════════════════════════════════════════════════════════
    # Step D: 结果映射 & 汇总
    # ══════════════════════════════════════════════════════════

    def _map_consensus_to_action(self, consensus: dict, total_active: int) -> tuple[str, str]:
        """共识率 → 操作建议"""
        if total_active < 3:
            return 'not_recommended', '不推荐'
        rate = consensus.get('consensus_rate', 0)
        direction = consensus.get('direction', 'neutral')

        if direction == 'bearish':
            if rate >= 0.80:
                return 'clear', '清仓'
            if rate >= 0.65:
                return 'reduce', '减仓'
            if rate >= 0.50:
                return 'hold', '仅做T/持有'
            if rate >= 0.35:
                return 'reduce', '减仓/回避'
            return 'hold', '仅做T/持有'

        # bullish or neutral
        if rate >= 0.80:
            return 'build_position', '建仓/加仓'
        if rate >= 0.65:
            return 'build_position', '建议建仓'
        if rate >= 0.50:
            return 'hold', '仅做T/持有'
        if rate >= 0.35:
            return 'reduce', '减仓/回避'
        return 'clear', '清仓/不推荐'

    def _build_verdict(self, consensus: dict, voting_detail: list) -> str:
        """构建自然语言总结"""
        b = consensus.get('bullish_votes', 0)
        be = consensus.get('bearish_votes', 0)
        n = consensus.get('neutral_votes', 0)
        total = consensus.get('total_active', 0)
        rate = consensus.get('consensus_rate', 0)
        direction = consensus.get('direction', 'neutral')

        if total < 3:
            return f'标签数据不足（仅{total}个有效标签），无法形成有效共识，暂不推荐。'

        if direction == 'bullish':
            desc = f'{b} 个标签看多，{be} 个看空，{n} 个中性，共识率 {rate*100:.1f}%'
            if rate >= 0.80:
                desc += '（★ 强共识）。'
            elif rate >= 0.65:
                desc += '（✓ 中等确认）。'
            else:
                desc += '（ℹ 分歧）。'

            # 收集看多原因
            reasons = [d['reason'] for d in voting_detail if d['vote'].startswith('+1')]
            if reasons:
                desc += ' ' + '；'.join(reasons[:4])

            if rate >= 0.65:
                desc += ' 综合判断为优质机会，建议关注。'
            else:
                desc += ' 多空接近，建议观望。'
            return desc

        if direction == 'bearish':
            desc = f'{be} 个标签看空，{b} 个看多，{n} 个中性，共识率 {rate*100:.1f}%'
            if rate >= 0.65:
                desc += '（⚠ 偏空）。'
            else:
                desc += '（ℹ 分歧）。'
            reasons = [d['reason'] for d in voting_detail if d['vote'].startswith('-1')]
            if reasons:
                desc += ' ' + '；'.join(reasons[:3])
            desc += ' 建议控制仓位、注意风险。'
            return desc

        return f'多空均衡（看多{b} 看空{be} 中性{n}），建议持有观察。'

    def _build_opportunity_summary(self, tags: dict, consensus: dict, risk_warnings: list) -> dict:
        """构建机会概览"""
        signal_strength = self._safe_float(tags.get('signal_strength'), 0)
        score = signal_strength

        if score >= 8:
            grade = 'A+'
        elif score >= 6:
            grade = 'A'
        elif score >= 4:
            grade = 'B'
        elif score >= 2:
            grade = 'C'
        else:
            grade = 'D'

        n_risks = len(risk_warnings)
        if n_risks >= 3:
            risk_level = 'high'
        elif n_risks >= 1:
            risk_level = 'medium'
        else:
            risk_level = 'low'

        rate = consensus.get('consensus_rate', 0)
        total = consensus.get('total_active', 0)
        if total >= 3 and rate >= 0.80:
            verification = f'★ 强共识（{consensus.get("bullish_votes", 0)}/{total} 标签方向一致）'
        elif total >= 3 and rate >= 0.65:
            verification = f'✓ 中等确认（共识率 {rate*100:.0f}%）'
        elif total >= 3:
            verification = f'ℹ 分歧（共识率 {rate*100:.0f}%）'
        else:
            verification = 'ℹ 标签数据不足'

        return {
            'score': round(score, 1),
            'grade': grade,
            'risk_level': risk_level,
            'time_horizon': tags.get('opportunity_label', tags.get('opportunity_type', 'unknown')),
            'verification': verification,
        }

    def _build_tags_summary(self, tags: dict) -> dict:
        """四行标签摘要"""
        # 方向
        direction_parts = []
        trend = tags.get('trend_alignment', '')
        if 'up' in trend:
            direction_parts.append('趋势向上')
        elif 'down' in trend:
            direction_parts.append('趋势向下')
        else:
            direction_parts.append('趋势震荡')
        ma = tags.get('ma_alignment', '')
        if ma == 'bullish':
            direction_parts.append('均线多头')
        elif ma == 'bearish':
            direction_parts.append('均线空头')
        elif ma == 'mixed':
            direction_parts.append('均线交叉')

        # 位置
        position_parts = []
        val = tags.get('valuation_level', '')
        val_map = {'extreme_low': '极度低估', 'low': '估值偏低', 'fair': '估值合理',
                    'high': '估值偏高', 'extreme_high': '估值过高'}
        position_parts.append(val_map.get(val, ''))
        pp = tags.get('price_position', '')
        pp_map = {'low_zone': '区间低位', 'mid_zone': '区间中位', 'high_zone': '区间高位'}
        if pp in pp_map:
            position_parts.append(pp_map[pp])

        # 质量
        quality_parts = []
        phase = tags.get('main_force_phase', '')
        phase_map = {'building': '主力建仓', 'washing': '主力洗盘',
                      'lifting': '主力拉升', 'distributing': '主力出货'}
        if phase in phase_map:
            quality_parts.append(phase_map[phase])
        fina = tags.get('fina_health', '')
        if fina == 'pass':
            quality_parts.append('财务健康')
        elif fina in ('suspicious', 'fail'):
            quality_parts.append('财务异常')
        fund = tags.get('fund_flow', '')
        if fund == '5d_inflow':
            quality_parts.append('机构主导')
        elif fund == '5d_outflow':
            quality_parts.append('机构流出')

        # 环境
        env_parts = []
        sent = tags.get('sentiment_phase', '')
        sent_map = {'recovery': '情绪复苏', 'climax': '情绪高潮',
                     'ebb': '情绪退潮', 'ice': '情绪冰点'}
        if sent in sent_map:
            env_parts.append(sent_map[sent])
        heat = tags.get('sector_heat', '')
        if heat == 'top_10':
            env_parts.append('板块前10')
        elif heat == 'top_20':
            env_parts.append('板块前20')

        return {
            'direction': ', '.join(filter(None, direction_parts)),
            'position': ', '.join(filter(None, position_parts)),
            'quality': ', '.join(filter(None, quality_parts)),
            'environment': ', '.join(filter(None, env_parts)),
        }

    def _build_operation_advice(self, ts_code: str, consensus: dict, tags: dict,
                                signal_strength: float, gate: dict = None, df=None) -> dict:
        """构建操作建议

        309号 决策3：操作建议以 L4 共识率为唯一来源，但叠加闸门2右侧确认覆盖：
          - right_side_confirm=否决 → 直接不推荐（无论共识率多高）
          - right_side_confirm=未确认 → 降级为"观察/仅做T"
          - right_side_confirm=强确认 → 仓位上限提升一档
        316号 P1 门禁约束（合成后应用）：
          - 深度高估 / 负面事件 → 强制不推荐（max_ratio=0）
          - 中度偏高 / 财务fail / 出货 / 流动性差 → 仓位压缩
        316号 P4 结构化输出：入场区间/建仓节奏/止损/止盈/时间止损（_build_trade_plan）
        """
        total_active = consensus.get('total_active', 0)
        action, label = self._map_consensus_to_action(consensus, total_active)

        # ── 闸门2右侧确认覆盖（309号§7.1） ──
        rsc = tags.get('right_side_confirm', '')
        if rsc == '否决':
            action, label = 'not_recommended', '右侧否决：出现卖出/背离/预跌信号'
        elif rsc == '未确认':
            if action in ('build_position', 'add_position'):
                action, label = 'hold', '右侧未确认：等待突破信号，仅观察'
        elif rsc == '强确认':
            pass  # 下方 max_position_ratio 提升一档

        # max_position_ratio：优先取 event_composite_score，否则共识率映射
        event_score = self._safe_int(tags.get('event_composite_score'), 0)
        if event_score > 0:
            if event_score >= 3:
                max_ratio = 0.8
            elif event_score >= 1:
                max_ratio = 0.6
            else:
                max_ratio = 0.4
        else:
            rate = consensus.get('consensus_rate', 0)
            if rate >= 0.80:
                max_ratio = 0.8
            elif rate >= 0.65:
                max_ratio = 0.6
            elif rate >= 0.50:
                max_ratio = 0.4
            elif rate >= 0.35:
                max_ratio = 0.2
            else:
                max_ratio = 0.0

        # 右侧强确认 → 仓位上限提升一档（309号§7.1 增强加权）
        if rsc == '强确认' and action in ('build_position', 'add_position'):
            max_ratio = min(max_ratio + 0.1, 0.9)

        # ── 316号 P1 门禁约束（合成后应用，§3.3 门禁后移） ──
        if gate is None:
            gate = self._evaluate_gate(ts_code, tags)
        val_lv = gate.get('valuation', 'none')
        hard = gate.get('hard_risks', [])
        soft = gate.get('soft_risks', [])
        if 'event_negative' in hard:
            # 负面事件（监管/财务欺诈）：直接不推荐
            action, label = 'not_recommended', '负面事件：监管/财务异常信号，规避'
            max_ratio = 0.0
        elif val_lv == 'deep':
            # 深度高估（PE 历史分位>90% 或偏离<-20）：泡沫风险，暂不介入
            action, label = 'not_recommended', '深度高估：估值泡沫风险，暂不介入'
            max_ratio = 0.0
        else:
            # 仓位约束（软风险 + 估值级别）
            if 'fina_weak' in soft:
                max_ratio = round(max_ratio * 0.5, 2)   # 财务异常（经营恶化）→ 减半
            if 'fina_fail' in soft:
                max_ratio = round(max_ratio * 0.5, 2)
            if 'distributing' in soft:
                max_ratio = round(max_ratio * 0.7, 2)
            if 'low_liquidity' in soft:
                max_ratio = round(max_ratio * 0.7, 2)
            if val_lv == 'moderate':
                max_ratio = round(max_ratio * 0.5, 2)
            elif val_lv == 'mild':
                max_ratio = round(max_ratio * 0.8, 2)

        # ── 316号 P4：结构化交易计划（入场/止损/止盈/时间止损/风险注记） ──
        entry_plan, stop_loss, target_price, time_stop, risk_notes = self._build_trade_plan(
            ts_code, tags, df, action, max_ratio, gate)

        return {
            'action': action,
            'label': label,
            'max_position_ratio': max_ratio,
            'entry_plan': entry_plan,
            'stop_loss': stop_loss,
            'target_price': target_price,
            'time_stop': time_stop,
            'risk_notes': risk_notes,
        }

    def _build_trade_plan(self, ts_code: str, tags: dict, df, action: str,
                          max_ratio: float, gate: dict) -> tuple:
        """316号 P4：结构化交易计划（§5.3 规则）

        - 入场区间：MA10-MA20 回踩带 / 突破 60 日前高确认
        - 建仓节奏：首仓 40-60%（按 max_ratio 缩放）→ 回踩加仓 → 突破加仓（分批金字塔）
        - 止损：结构位（MA20 与前低取高）×0.98（跌破离场）
        - 止盈：60 日前高（前高突破目标）
        - 时间止损：持仓 20 交易日未创新高则减半
        - risk_notes：门禁软风险注记

        Returns: (entry_plan, stop_loss, target_price, time_stop, risk_notes)
        """
        entry_plan: list[dict] = []
        stop_loss: dict | None = None
        target_price: dict | None = None
        time_stop: str | None = None
        risk_notes: list[str] = []

        # 风险注记（来自门禁软风险）
        if gate:
            for r in gate.get('soft_risks', []):
                if r == 'fina_weak':
                    risk_notes.append('财务指标异常，仓位已减半')
                elif r == 'fina_fail':
                    risk_notes.append('财务健康不通过，仓位已减半')
                elif r == 'distributing':
                    risk_notes.append('主力出货阶段，仓位已压缩')
                elif r == 'low_liquidity':
                    risk_notes.append('流动性偏低（换手<1%），仓位已压缩')
            if gate.get('valuation') == 'mild':
                risk_notes.append('估值略偏高，仓位已压缩一档')
            elif gate.get('valuation') == 'moderate':
                risk_notes.append('估值偏高，仓位已减半')

        # 数据不足：仅保留风险注记
        if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
            return entry_plan, stop_loss, target_price, time_stop, risk_notes

        closes = df['close'].values
        price = float(closes[-1])
        ma10 = float(df['close'].tail(10).mean()) if len(closes) >= 10 else None
        ma20 = float(df['close'].tail(20).mean()) if len(closes) >= 20 else None
        hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else (
            float(closes[-60:].max()) if len(closes) >= 60 else None)
        lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else (
            float(closes[-60:].min()) if len(closes) >= 60 else None)

        # 建仓类建议：分批入场 + 止损/目标（基于 max_ratio 缩放首仓比例）
        if action in ('build_position', 'add_position') and max_ratio > 0:
            first = round(0.4 * max_ratio / max(max_ratio, 0.1) * 100)  # 首仓约 40%（0.4/上限）
            entry_plan = []
            if ma10 and ma20 and price > ma20:
                entry_plan.append({'price': f'回踩 MA10（{ma10:.2f}-{ma20:.2f}）', 'ratio': f'{first}%',
                                   'condition': '首次建仓（分批）'})
            else:
                entry_plan.append({'price': f'当前价 {price:.2f}', 'ratio': f'{first}%', 'condition': '首次建仓'})
            if hi60 and price < hi60:
                entry_plan.append({'price': f'放量突破前高 {hi60:.2f}', 'ratio': '30%', 'condition': '右侧加仓'})
            else:
                entry_plan.append({'price': '回踩 MA10 不破', 'ratio': '30%', 'condition': '回踩加仓'})
            entry_plan.append({'price': f'回踩 MA20（{ma20:.2f}）', 'ratio': '30%', 'condition': '深度回踩补仓'})

            # 止损：max(MA20, 60日前低) × 0.98
            stop_base = None
            if ma20:
                stop_base = ma20
            if lo60 and (stop_base is None or lo60 > stop_base):
                stop_base = lo60
            if stop_base:
                stop_loss = {'type': 'structure', 'price': round(stop_base * 0.98, 2),
                             'reason': f'跌破 MA20/前低 {stop_base:.2f} 离场'}
            # 止盈：60 日前高（或保守 15% 目标）
            if hi60 and price < hi60:
                target_price = {'price': round(hi60, 2), 'reason': f'前高 {hi60:.2f} 压力位'}
            else:
                target_price = {'price': round(price * 1.15, 2), 'reason': '保守 15% 目标'}
            time_stop = '持仓 20 交易日未创新高则减半'
        elif action == 'hold' and max_ratio > 0:
            # 持有/观察：给出观察位（结构位止损）
            stop_base = ma20 or lo60
            if stop_base:
                stop_loss = {'type': 'structure', 'price': round(stop_base * 0.97, 2),
                             'reason': f'跌破 {stop_base:.2f} 转弱离场'}

        return entry_plan, stop_loss, target_price, time_stop, risk_notes

    def _build_risk_warnings(self, tags: dict, gate: dict = None) -> list[dict]:
        """构建风险提示列表（316号 P1：估值分级提示 + 流动性风险）"""
        warnings: list[dict] = []

        fina = tags.get('fina_health', '')
        FINA_MAP = {'suspicious': '存疑', 'fail': '不通过'}
        fina_label = FINA_MAP.get(fina, fina)
        if fina in ('suspicious', 'fail'):
            warnings.append({'type': 'company', 'content': f'财务健康评级为{fina_label}，存在基本面风险'})

        # 316号 P1：估值分级风险标注（替代原"估值偏高"一刀切）
        if gate is None:
            gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
        val_lv = gate.get('valuation', 'none')
        if val_lv == 'deep':
            warnings.append({'type': 'valuation', 'content': '深度高估（PE 历史分位 >90%），估值泡沫风险，暂不介入'})
        elif val_lv == 'moderate':
            warnings.append({'type': 'valuation', 'content': '估值偏高（PE 分位 80-90%），安全边际有限，仓位减半'})
        elif val_lv == 'mild':
            warnings.append({'type': 'valuation', 'content': '估值略偏高（PE 分位 60-80%），注意追高风险'})
        elif tags.get('valuation_level') in ('high', 'extreme_high'):
            warnings.append({'type': 'valuation', 'content': '估值偏高，安全边际不足'})

        # 316号 P1：流动性风险（新增）
        if 'low_liquidity' in gate.get('soft_risks', []):
            warnings.append({'type': 'liquidity', 'content': '流动性偏低（换手率 <1%），注意买卖冲击成本'})
        if 'fina_weak' in gate.get('soft_risks', []):
            warnings.append({'type': 'company', 'content': '财务指标异常（营收下滑/现金流为负/亏损），经营恶化风险，仓位减半'})
        if 'event_negative' in gate.get('hard_risks', []):
            warnings.append({'type': 'event', 'content': '存在监管立案风险，需高度警惕'})

        catalyst = tags.get('catalyst_event', '')
        if catalyst in ('regulatory', 'fraud_sign'):
            warnings.append({'type': 'event', 'content': '存在监管/财务异常事件，需高度警惕'})

        phase = tags.get('main_force_phase', '')
        if phase == 'distributing':
            warnings.append({'type': 'market', 'content': '主力处于出货阶段，谨慎参与'})

        sector = tags.get('sector_heat', '')
        if sector == 'none':
            warnings.append({'type': 'industry', 'content': '所属板块缺乏热度支撑'})

        return warnings

    def _build_user_checklist(
        self, ts_code: str, tags: dict, valuation_tracking: dict,
    ) -> list[str]:
        """构建用户自判清单"""
        checklist: list[str] = []

        val = tags.get('valuation_level', '')
        if val in ('high', 'extreme_high'):
            checklist.append('⚠ 估值偏高，需判断是否仍有上行空间')

        fina = tags.get('fina_health', '')
        if fina in ('suspicious', 'fail'):
            checklist.append('⚠ 财务健康存疑，建议核查最新财报')

        vt_action = valuation_tracking.get('action', '')
        if vt_action == 'consider_partial_take_profit':
            checklist.append('ℹ 估值已从入场时的低点回升，考虑部分止盈')
        elif vt_action == 'consider_reduce':
            checklist.append('⚠ 估值已升至高位，建议减仓锁定利润')

        event_score = self._safe_int(tags.get('event_composite_score'), 0)
        if event_score >= 3:
            pass  # 事件驱动正向，无额外提示
        elif event_score <= -3:
            checklist.append('⚠ 存在重大负面事件驱动，注意风险')

        if not checklist:
            checklist.append('ℹ 各维度信号一致，系统建议可参考')

        return checklist

    # ══════════════════════════════════════════════════════════
    # signal_strength_adjusted（独立补偿）
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _compute_signal_strength_adjusted(tags: dict, signal_strength: float) -> float:
        """计算事件维度补充后的信号强度（303号§5.7 协议）"""
        catalyst = tags.get('catalyst_event', 'none')
        if catalyst in ('earnings', 'lhb', 'buyback', 'breakout'):
            adjustment = 0.15
        elif catalyst == 'none':
            adjustment = 0
        elif catalyst in ('pledge', 'float', 'reduce', 'fraud_sign', 'regulatory'):
            adjustment = -0.15
        else:
            # concept 等正向信号 → 小幅上调
            adjustment = 0.10

        return round(signal_strength * (1 + adjustment), 2)

    # ══════════════════════════════════════════════════════════
    # 日常变化检测（299号§5.1 变更检测归属L4）
    # ══════════════════════════════════════════════════════════

    # 八维度监控配置：(标签名, 展示名, 比较函数, 推送级别判定函数)
    MONITOR_DIMENSIONS = [
        ('main_force_phase', '主力阶段', None, None),  # 值变化
        ('valuation_level', '估值水平', None, None),     # 5档区间切换
        ('trend_alignment', '趋势方向', 'direction_reversal', None),  # up↔down
        ('fund_flow', '资金流向', 'direction_reversal', None),  # inflow↔outflow
        ('phase_confidence', '主力可信度', 'numeric_0_2', None),  # ±0.2
        ('catalyst_event', '催化剂', 'on_off_switch', None),  # none↔有值
        ('fina_health', '财务健康', 'health_change', None),  # pass→非pass
        ('signal_strength', '综合信号', 'numeric_1_0', None),  # ±1.0
    ]

    def _get_previous_trade_date(self) -> str | None:
        """获取上一个交易日（YYYY-MM-DD）"""
        try:
            cache = self._get_cache()
            row = cache.conn.execute(
                "SELECT DISTINCT trade_date FROM daily_cache "
                "ORDER BY trade_date DESC LIMIT 1 OFFSET 1"
            ).fetchone()
            if row:
                return row[0]
            return None
        except Exception:
            return None

    def _compute_daily_change(self, ts_code: str, today_tags: dict) -> dict:
        """计算当日 vs 上日标签变化（299号§5.2 八维度监控）

        Returns:
            {has_changes, changes: [{tag, label, old_value, new_value, level, summary}]}
        """
        yesterday = self._get_previous_trade_date()
        if yesterday is None:
            return {'has_changes': False, 'changes': [], 'change_count': 0,
                    'focus_items': []}

        # 加载上日标签
        try:
            cache = self._get_cache()
            rows = cache.conn.execute(
                "SELECT tag_name, tag_value FROM opportunity_tags_cache "
                "WHERE ts_code=? AND updated_at=?",
                [ts_code, yesterday]
            ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return {'has_changes': False, 'changes': [], 'change_count': 0,
                    'focus_items': []}

        yesterday_tags: dict[str, str] = {r[0]: r[1] for r in rows}
        changes: list[dict] = []

        # 检查各维度
        tag_change_detected = lambda old, new: old is not None and new is not None and old != new
        direction_reversed = lambda old, new: (
            (old in ('up_aligned', 'down_aligned') and new in ('up_aligned', 'down_aligned')
             and old != new)
        )
        numeric_diff_ge = lambda old, new, threshold: (
            self._safe_float(new, 0) - self._safe_float(old, 0) >= threshold
            or self._safe_float(old, 0) - self._safe_float(new, 0) >= threshold
        )

        # 1. main_force_phase — 任意变化 → important
        old = yesterday_tags.get('main_force_phase')
        new = today_tags.get('main_force_phase')
        if old is not None and new is not None and old != new:
            changes.append({
                'tag': 'main_force_phase', 'label': '主力阶段',
                'old_value': old, 'new_value': new,
                'level': 'important',
                'summary': f'主力阶段 {old} → {new}',
            })

        # 2. valuation_level — 5档区间切换 → urgent 仅当到 extreme_high
        old = yesterday_tags.get('valuation_level')
        new = today_tags.get('valuation_level')
        if old is not None and new is not None and old != new:
            level = 'urgent' if new == 'extreme_high' else 'normal'
            changes.append({
                'tag': 'valuation_level', 'label': '估值水平',
                'old_value': old, 'new_value': new,
                'level': level,
                'summary': f'估值水平 {old} → {new}',
            })

        # 3. trend_alignment — 方向反转 → normal
        old = yesterday_tags.get('trend_alignment')
        new = today_tags.get('trend_alignment')
        if direction_reversed(old, new):
            changes.append({
                'tag': 'trend_alignment', 'label': '趋势方向',
                'old_value': old, 'new_value': new,
                'level': 'normal',
                'summary': f'趋势方向 {old} → {new}',
            })

        # 4. fund_flow — 方向反转 → normal
        old = yesterday_tags.get('fund_flow')
        new = today_tags.get('fund_flow')
        if direction_reversed(old, new):
            changes.append({
                'tag': 'fund_flow', 'label': '资金流向',
                'old_value': old, 'new_value': new,
                'level': 'normal',
                'summary': f'资金流向 {old} → {new}',
            })

        # 5. phase_confidence — ±0.2 → normal
        old = yesterday_tags.get('phase_confidence')
        new = today_tags.get('phase_confidence')
        if old is not None and new is not None:
            delta = self._safe_float(new, 0) - self._safe_float(old, 0)
            if abs(delta) >= 0.2:
                changes.append({
                    'tag': 'phase_confidence', 'label': '主力可信度',
                    'old_value': old, 'new_value': new,
                    'level': 'normal',
                    'summary': f'主力可信度 {old} → {new}',
                })

        # 6. catalyst_event — none↔有值 → important（有值）or normal（消失）
        old = yesterday_tags.get('catalyst_event')
        new = today_tags.get('catalyst_event')
        if old is not None and new is not None and old != new:
            level = 'important' if new not in ('none', '', 'unknown') else 'normal'
            changes.append({
                'tag': 'catalyst_event', 'label': '催化剂',
                'old_value': old, 'new_value': new,
                'level': level,
                'summary': f'催化剂 {old} → {new}',
            })

        # 7. fina_health — pass→非pass → urgent；其他变化 → important
        old = yesterday_tags.get('fina_health')
        new = today_tags.get('fina_health')
        if old is not None and new is not None and old != new:
            level = 'urgent' if new == 'fail' else 'important'
            changes.append({
                'tag': 'fina_health', 'label': '财务健康',
                'old_value': old, 'new_value': new,
                'level': level,
                'summary': f'财务健康 {old} → {new}',
            })

        # 8. signal_strength — ±1.0 → normal
        old = yesterday_tags.get('signal_strength')
        new = today_tags.get('signal_strength')
        if old is not None and new is not None:
            delta = self._safe_float(new, 0) - self._safe_float(old, 0)
            if abs(delta) >= 1.0:
                direction = '上升' if delta > 0 else '下降'
                changes.append({
                    'tag': 'signal_strength', 'label': '综合信号',
                    'old_value': old, 'new_value': new,
                    'level': 'normal',
                    'summary': f'信号强度 {direction} {abs(delta):.1f}',
                })

        return {
            'has_changes': bool(changes),
            'changes': changes,
            'change_count': len(changes),
            'focus_items': [c['summary'] for c in changes[:5]],
        }

    # ══════════════════════════════════════════════════════════
    # 估值退出跟踪（独立并行通道）
    # ══════════════════════════════════════════════════════════

    def _check_valuation_exit(self, ts_code: str, tags: dict) -> dict:
        """独立于共识投票的并行通道 — 估值退出跟踪

        检查开仓后估值变化是否触发退出条件。
        仅对自选库内股票有完整数据。
        """
        result: dict[str, Any] = {
            'entry_level': None,
            'current_level': tags.get('valuation_level'),
            'level_change': None,
            'composite_rating': self._safe_float(tags.get('composite_rating'), None),
            'rating_change': None,
            'days_in_position': None,
            'action': 'none',
        }

        try:
            # 从 DataManager 读取库信息（Red Line 5 合规）
            lib = self._get_dm().get_library_entry(ts_code)

            if lib is None or lib.lib_level in ('done',):
                return result

            # 解析开仓时存入的操作建议 JSON
            advice_str = lib.operation_advice or '{}'
            import json
            try:
                advice = json.loads(advice_str) if isinstance(advice_str, str) else advice_str
            except (json.JSONDecodeError, TypeError):
                advice = {}

            from datetime import date

            result['entry_level'] = advice.get('entry_valuation_level', 'unknown')
            current_level = tags.get('valuation_level', '')

            # 计算持仓天数
            added = lib.added_date
            if added:
                try:
                    added_dt = datetime.strptime(str(added)[:10], '%Y-%m-%d').date()
                    result['days_in_position'] = (date.today() - added_dt).days
                except (ValueError, TypeError):
                    pass

            # 检查退出条件
            entry_level = result['entry_level']
            if entry_level in ('low', 'extreme_low') and current_level in ('high', 'extreme_high'):
                result['level_change'] = f'{entry_level} → {current_level}'
                # 检查情绪是否高潮
                if tags.get('sentiment_phase') == 'climax':
                    result['action'] = 'consider_reduce'
                else:
                    result['action'] = 'consider_partial_take_profit'

            elif entry_level == 'extreme_low' and current_level == 'fair':
                result['level_change'] = f'{entry_level} → {current_level}'
                result['action'] = 'consider_partial_take_profit'

            # composite_rating 变化
            entry_rating = advice.get('entry_composite_rating')
            current_rating = self._safe_float(tags.get('composite_rating'), None)
            if entry_rating is not None and current_rating is not None:
                try:
                    delta = current_rating - float(entry_rating)
                    result['rating_change'] = f'{delta:+.1f} since entry'
                except (ValueError, TypeError):
                    pass

            # fina_health 恶化
            fina = tags.get('fina_health', '')
            if fina in ('suspicious', 'fail') and entry_level != 'unknown':
                adv = advice.get('entry_fina_health', '')
                if adv == 'pass':
                    result['action'] = 'consider_exit'

        except Exception as e:
            logger.debug('_check_valuation_exit(%s): %s', ts_code, e)

        return result

    # ══════════════════════════════════════════════════════════
    # 辅助方法
    # ══════════════════════════════════════════════════════════

    def _load_tags(self, ts_code: str) -> dict:
        """从 ECM 加载标签"""
        try:
            return self._get_cache().get_tags(ts_code)
        except Exception:
            logger.warning('L4CrossValidator: 无法加载标签 %s', ts_code)
            return {}

    def _get_stock_name(self, ts_code: str) -> str:
        """获取股票名称"""
        try:
            info = self._get_dm().get_stock_info(ts_code)
            return info.get('name', '') if info else ''
        except Exception:
            return ''

    @staticmethod
    def _safe_float(v: Any, default: float = 0) -> float:
        try:
            return float(v) if v is not None else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(v: Any, default: int = 0) -> int:
        try:
            return int(v) if v is not None else default
        except (ValueError, TypeError):
            return default
