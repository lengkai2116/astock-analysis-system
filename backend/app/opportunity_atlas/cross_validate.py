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

import pandas as pd

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)


def _convert_dim_engine_to_legacy(der: dict) -> dict:
    """365号批次C：将维度引擎输出转换为旧5维格式（供 _extract_real_dimensions 回退使用）"""
    dims = {}
    # 结构维
    s = der.get('structure') or {}
    if s:
        judg = s.get('judgment', {})
        dims['chanlun'] = {'direction': 'up' if judg.get('overall_direction', 0) > 0 else 'down'}
    # 量价维
    vp = der.get('volume_price') or {}
    if vp:
        judg = vp.get('judgment', {})
        dims['volume_price'] = {'direction': 'up' if judg.get('overall_direction', 0) > 0 else 'down'}
    # 筹码维
    cf = der.get('fund_chip') or {}
    if cf:
        judg = cf.get('judgment', {})
        phase_dir = judg.get('phase', {}).get('direction', 0)
        dims['chip'] = {'direction': 'up' if phase_dir > 0 else ('down' if phase_dir < 0 else 'neutral')}
    # 情绪维
    em = der.get('emotion') or {}
    if em:
        judg = em.get('judgment', {})
        ol = judg.get('overall_light', 'yellow')
        dims['emotion'] = {'direction': 'up' if ol == 'green' else ('down' if ol == 'red' else 'neutral')}
    # 因子维（从 signal 维度派生）
    sig = der.get('signal') or {}
    if sig:
        judg = sig.get('judgment', {})
        od = judg.get('overall_direction', 0)
        dims['factor'] = {'direction': 'up' if od > 0 else ('down' if od < 0 else 'neutral')}
    return dims if dims else None


def _extract_real_dimensions(dm, ts_code: str) -> dict | None:
    """330号改进3（2026-08-13）：从 strategy_signal_detail（P2 预计算）提取真实五维方向

    与个股页 analyze（strategy_analyze.py）同源——消除弹窗 diagnose 标签轻量推导
    导致的共识虚高（301119=100%/300759=90% vs 个股页真实五维 67%）。

    365号批次C：优先尝试从 status_snapshot.dim_engine_results 读取维度引擎输出，
    不存在时回退到旧5维提取逻辑。

    方向口径与 analyze 各 _build_*_dimension 保持一致：
      - chanlun: status_recognition.trend.direction（up/down）或缠论中文态
      - volume_price: status_recognition.trend.direction（up/down）
      - chip: status_recognition.state 中文阶段 → bull/bear
      - emotion: 信号 signal（bullish/bearish）
      - factor: 最高置信度信号方向（无因子信号时中性）

    Returns:
        dimensions dict 或 None（信号缓存缺失/解析失败）
    """
    # 365号批次C：优先使用维度引擎结果
    try:
        row = dm.cache.get_status_snapshot_row(ts_code)
        if row and row.get('dim_engine_results'):
            import json
            der = json.loads(row['dim_engine_results'])
            if der and any(v is not None for v in der.values()):
                return _convert_dim_engine_to_legacy(der)
    except Exception:
        pass  # 回退到旧逻辑
    try:
        cached = dm.cache.get_latest_signal_detail(ts_code)
        if not cached:
            return None
        signals = cached.get('signals', {})
        if not signals:
            return None

        def _sig(name_keyword: str):
            for name, s in signals.items():
                if name_keyword in name:
                    return s
            return None

        chan = _sig('缠论')
        vp = _sig('量价')
        chip_s = _sig('筹码')
        emo = _sig('BOCIASI')
        factor_s = _sig('因子')

        # chanlun：优先 status_recognition.trend.direction，回退信号中文方向
        chan_dir = '待定'
        if chan:
            trend = (chan.get('status_recognition') or {}).get('trend') or {}
            td = trend.get('direction', '')
            chan_dir = ('上升' if td == 'up' else ('下降' if td == 'down' else '待定'))
            if chan_dir == '待定':
                detail = chan.get('chanlun_analysis_detail') or {}
                chan_dir = (detail.get('走势结构') or {}).get('趋势方向', '待定') or '待定'
        # volume_price：status_recognition.trend.direction
        vp_dir = 'neutral'
        if vp:
            vp_dir = ((vp.get('status_recognition') or {}).get('trend') or {}).get('direction', 'neutral')
            if vp_dir not in ('up', 'down'):
                vp_dir = 'neutral'
        # chip：status_recognition.state 中文阶段（拉升/建仓→bullish，出货→bearish）
        chip_dir = 'neutral'
        if chip_s:
            cstate = str((chip_s.get('status_recognition') or {}).get('state', ''))
            chip_dir = ('bullish' if ('拉升' in cstate or '建仓' in cstate or '洗盘' in cstate)
                        else ('bearish' if '出货' in cstate else 'neutral'))
        # emotion：BOCIASI 信号 direction（up/down）或 signal
        emo_dir = 'neutral'
        if emo:
            et = (emo.get('status_recognition') or {}).get('trend') or {}
            ed = et.get('direction', '') or str(emo.get('signal', ''))
            emo_dir = ('bullish' if ed in ('up', 'bullish', 'BULLISH')
                       else ('bearish' if ed in ('down', 'bearish', 'BEARISH') else 'neutral'))
        # factor：取最高置信度信号的 signal 方向
        f_dir = 'neutral'
        best = None
        for s in signals.values():
            if best is None or (s.get('confidence') or 0) > (best.get('confidence') or 0):
                best = s
        if best:
            bs = str(best.get('signal', ''))
            f_dir = ('bullish' if bs in ('bullish', 'BULLISH', 'up')
                     else ('bearish' if bs in ('bearish', 'BEARISH', 'down') else 'neutral'))

        # 336号 S1.5：emotion 维证据补全（603897 差异#3：弹窗"中性/空" vs 个股页"STRENGTHENING/电气设备"）
        # 板块轮动状态用 SectorAnalysisService（读缓存计算），sector 名优先板块服务、
        # 兜底 Stock.industry（与个股页 analyze 同源）
        _rotation, _sector = '', ''
        try:
            from app.services.sector_analysis_service import SectorAnalysisService
            _sctx = SectorAnalysisService().get_sector_context(ts_code)
            if _sctx.get('available'):
                _rotation = _sctx.get('rotation_state', '')
                _sector = _sctx.get('sector_name', '')
        except Exception:
            pass
        if not _sector:
            try:
                from app.models import Stock
                _stk = Stock.query.get(ts_code)
                if _stk and getattr(_stk, 'industry', None):
                    _sector = _stk.industry
            except Exception:
                pass

        return {
            'factor': {'trend': f_dir},
            'chanlun': {'direction': chan_dir,
                        'buy_point': (str((chan or {}).get('buy_point') or '')
                                      or str((signals.get('缠论走势分析') or {}).get('signal_label') or ''))},
            'volume_price': {'direction': vp_dir},
            'chip': {'direction': chip_dir},
            'emotion': {'direction': emo_dir, 'rotation_state': _rotation, 'sector': _sector},
        }
    except Exception as e:
        logger.debug(f"_extract_real_dimensions 失败 ({ts_code}): {e}")
        return None


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
        # 2026-08-06 修复（316号 P5）：黑马形态映射补齐（原缺失致投票失效）
        '底部放量长阳黑马首板': 1,
        # 看跌（预跌）
        '乌云盖顶': -1, '黄昏星': -1, '看跌吞没': -1, '射击之星': -1,
        '三乌鸦': -1, '上吊线': -1, '放量冲高回落': -1, '天量天价': -1,
        '放量滞涨': -1, '跳空高开低走': -1, '放量长阴': -1, '高台跳水': -1,
        # 2026-08-06 修复（316号 P5）：预跌形态映射补齐（原缺失致投票失效）
        '放量下跌恐慌出逃': -1, '平台破位箱体下沿跌破': -1,
        # P5 补充（看跌）
        'MA5死叉MA10': -1, '均线空头排列': -1, '看跌孕线': -1, '看跌捉腰带': -1,
        '看跌踢开': -1, '三线开花空头': -1,
        '格兰维尔卖点1-跌破卖': -1, '格兰维尔卖点2-反抽卖': -1,
        '格兰维尔卖点3-偏离卖': -1, '格兰维尔卖点4-新高卖': -1,
        '头肩顶': -1, '上升楔形': -1, '扩散三角形': -1, 'M顶': -1, '衰竭缺口': -1,
        '跳空高开低走巨量阴线': -1,
        # 持续/待变盘形态（中性，显式声明防误判；2026-08-06 补齐）
        '上升三法': 0, '下降三法': 0, '光头光脚': 0, '孕线十字': 0,
        '陀螺线': 0, '收敛三角形': 0,
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
        # 2026-08-06 修复（316号 P5）：形态原因补齐
        '放量下跌恐慌出逃': '放量下跌恐慌出逃（预跌）',
        '平台破位箱体下沿跌破': '平台破位箱体下沿跌破（预跌）',
        '底部放量长阳黑马首板': '底部放量长阳黑马首板（黑马）',
        '上升三法': '上升三法（持续整理）',
        '下降三法': '下降三法（持续整理）',
        '光头光脚': '光头光脚（持续）',
        '孕线十字': '孕线十字（持续）',
        '陀螺线': '陀螺线（持续）',
        '收敛三角形': '收敛三角形（待变盘）',
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
    'catalyst_event', 'pattern_signal',
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

        # 336号S2 + 352号G3：_arb 仲裁共识从五维标签投票改为 L1 九维推导（消双口径）
        _l1_for_arb = None
        try:
            _sv_tmp = self._get_status_verdict(ts_code)
            if _sv_tmp:
                _l1_for_arb = {'direction': _sv_tmp.get('direction', 'neutral'),
                                'consensus_rate': _sv_tmp.get('consensus_rate', 0)}
        except Exception:
            pass

        # ── 汇总输出 ──
        # 321号 S2：跨维仲裁（权威 gate + 共识同源传入）
        try:
            from app.opportunity_atlas.arbiter import arbitrate
            _arb = arbitrate(tags, gate=gate, consensus=_l1_for_arb or consensus)
        except Exception:
            _arb = {'opportunity_state': 'wait', 'state_evidence': ['仲裁不可用']}
        # verdict/opportunity_summary 移至 operation_advice 后计算（336号 S1.2：用五维共识）
        signal_strength = self._safe_float(tags.get('signal_strength'), 0)
        signal_strength_adjusted = self._compute_signal_strength_adjusted(tags, signal_strength)

        # ── 并行计算日常变化（299号§5.1 变更检测归属L4） ──
        daily_change = self._compute_daily_change(ts_code, tags)

        # 319号修订版：EPS 同比 + PB 分位传入风险提示（估值矛盾场景数据驱动分叉）
        _eps_yoy = self._eps_yoy(ts_code)
        _pb_pct = self._safe_float(tags.get('pb_percentile_5y'), None)
        risk_warnings = self._build_risk_warnings(tags, gate, eps_yoy=_eps_yoy, pb_pct=_pb_pct)
        user_checklist = self._build_user_checklist(ts_code, tags, valuation_tracking)
        tags_summary = self._build_tags_summary(tags)

        # 323号 S0.7：执行层统一——operation_advice 改由 advice_builder 生成
        # （唯一仓位/止损/入场来源），用标签构造五维输入，保留旧字段兼容
        # 旧 _build_operation_advice 仅作 advice_builder 失败时回退（废弃标记）
        operation_advice = None
        try:
            from app.opportunity_atlas.advice_builder import build_operation_advice
            _dm = self._get_dm()
            _df = _dm.get_cached_daily_data(ts_code)
            # ── 330号改进3（2026-08-13）：双引擎口径统一 ──
            # 弹窗 diagnose 与个股页 analyze 共识双口径（弹窗标签轻量推导 100%/90%
            # vs 个股页真实五维 67%）根因：两处构造 dimensions 的方式不同。
            # 统一方案：diagnose 也从 strategy_signal_detail（P2 预计算，毫秒级读缓存）
            # 提取真实五维方向——与 analyze 同源，消除共识虚高。
            try:
                _real_dims = _extract_real_dimensions(_dm, ts_code)
            except Exception:
                _real_dims = None
            if _real_dims:
                _dims = _real_dims
            else:
                # 回退：标签推导（信号缓存缺失时，保留旧口径保证弹窗可用）
                _ta = str(tags.get('trend_alignment', ''))
                _ff = str(tags.get('fund_flow', ''))
                _bsp = str(tags.get('buy_sell_point', ''))
                _vpf = str(tags.get('volume_price_fit', ''))
                _sp = str(tags.get('sentiment_phase', ''))
                _chan_dir = ('上升' if ('买' in _bsp and '卖' not in _bsp)
                             else ('下降' if '卖' in _bsp else '待定'))
                _vp_dir = ('up' if _vpf in ('healthy', 'strong')
                           else ('down' if _vpf in ('unhealthy', 'weak') else 'neutral'))
                _emo_dir = ('bullish' if _sp in ('recovery', 'boom', 'revival')
                            else ('bearish' if _sp in ('ebb', 'ice', 'climax') else 'neutral'))
                _dims = {
                    'factor': {'trend': ('bullish' if _ta == 'up_aligned'
                                         else ('bearish' if _ta == 'down_aligned'
                                                else 'neutral'))},
                    'chanlun': {'direction': _chan_dir,
                                'buy_point': tags.get('buy_sell_point', '')},
                    'volume_price': {'direction': _vp_dir},
                    'chip': {'direction': ('bullish' if _ff == '5d_inflow'
                                           else ('bearish' if _ff == '5d_outflow'
                                                  else 'neutral'))},
                    'emotion': {'direction': _emo_dir},
                }
            # 336号S2 + 352号G2：传入 L1 九维共识（与 analyze 同源）
            _l1_consensus = None
            _l1_dirs = None
            try:
                _sv = self._get_status_verdict(ts_code)
                if _sv:
                    _l1_consensus = {
                        'consensus_rate': _sv.get('consensus_rate', 0),
                        'bullish_votes': _sv.get('bullish_dims', 0),
                        'bearish_votes': _sv.get('bearish_dims', 0),
                        'direction': _sv.get('direction', 'neutral'),
                        '_source': 'nine_dim',
                    }
                    for _d in _sv.get('dim_states', {}).values():
                        _light = _d.get('light', 'yellow')
                        _l1_dirs = _l1_dirs or []
                        _l1_dirs.append(1 if _light == 'green' else (-1 if _light == 'red' else 0))
            except Exception:
                pass
            unified = build_operation_advice(ts_code, _dims, [], _df, tags=tags,
                                              consensus=_l1_consensus, dirs=_l1_dirs)
            # 保留旧字段兼容（action/label/max_position_ratio/entry_plan/
            # stop_loss/target_price），供机会库等旧消费方过渡
            _ex = unified['executable']
            _pos = _ex['position']
            unified['action'] = _ex.get('action_type', 'hold')
            unified['label'] = unified.get('summary', '')
            unified['max_position_ratio'] = _pos.get('max_pct', 0.0)
            unified['entry_plan'] = [{'trigger': e.get('trigger'),
                                      'pct': e.get('size_pct')}
                                     for e in _ex.get('entry_rules', [])]
            _sl = _ex.get('exit_rules') or []
            unified['stop_loss'] = (_sl[0].get('trigger') if _sl else None)
            unified['target_price'] = None
            operation_advice = unified
        except Exception as _unify_err:
            import traceback
            logger.warning(f"S0.7 执行层统一跳过 ({ts_code}): {_unify_err}\n{traceback.format_exc()}")
            # 回退旧 _build_operation_advice（321 逻辑，废弃过渡）
            try:
                operation_advice = self._build_operation_advice(
                    ts_code, consensus, tags, gate, df)
            except Exception as _old_err:
                logger.debug(f"旧 _build_operation_advice 失败 ({ts_code}): {_old_err}")
                operation_advice = {}
        if not operation_advice:
            operation_advice = {}

        # 336号 S2：弹窗摘要层共识切换到 L1 九维推导（成品仓唯一消费）
        # 原 S1 过渡口径（consensus_5d 五维推导）已不满足 336号 §2.2 要求：
        # "弹窗摘要/个股页/快照全部读同一 L2 输出共识"。
        # 优先读 status_verdict（StatusEngine L1 九维），回退到五维推导。
        try:
            _sv = self._get_status_verdict(ts_code)
            if _sv and _sv.get('dim_states'):
                from app.opportunity_atlas.status_engine import _DIM_DIRECTION
                _dims9 = _sv['dim_states']
                _bull9 = _bear9 = _neu9 = 0
                for _dim, _info in _dims9.items():
                    _st = _info.get('state', '') if isinstance(_info, dict) else _info
                    _v = _DIM_DIRECTION.get(_dim, {}).get(_st, 0)
                    if _v > 0:
                        _bull9 += 1
                    elif _v < 0:
                        _bear9 += 1
                    else:
                        _neu9 += 1
                _dir_active = _bull9 + _bear9
                _rate9 = max(_bull9, _bear9) / max(_dir_active, 1) if _dir_active else 0.0
                consensus_display = {
                    'bullish_votes': _bull9,
                    'bearish_votes': _bear9,
                    'neutral_votes': _neu9,
                    'total_active': len(_dims9),
                    'consensus_rate': round(_rate9, 3),
                    'direction': 'bullish' if _bull9 > _bear9 else ('bearish' if _bear9 > _bull9 else 'neutral'),
                    'tie': _bull9 == _bear9 and _bull9 > 0,
                    '_source': 'nine_dim',
                }
            else:
                raise RuntimeError("status_verdict 不可用，回退五维推导")
        except Exception:
            # 回退：五维推导（S1 过渡口径）
            try:
                _dims5 = locals().get('_dims') or {}
                if _dims5:
                    from app.opportunity_atlas.advice_builder import _dim_directions, _consensus_from_dirs
                    _five_dirs = _dim_directions(_dims5)
                    _five = _consensus_from_dirs(_five_dirs)
                    consensus_display = {
                        'bullish_votes': sum(1 for x in _five_dirs if x > 0),
                        'bearish_votes': sum(1 for x in _five_dirs if x < 0),
                        'neutral_votes': sum(1 for x in _five_dirs if x == 0),
                        'total_active': len(_five_dirs),
                        'consensus_rate': _five['consensus_rate'],
                        'direction': _five['direction'],
                        'tie': False,
                        '_source': 'five_dim',
                    }
                else:
                    consensus_display = consensus
            except Exception:
                consensus_display = consensus
        verdict = self._build_verdict(consensus_display, [], tags,
                                      gate=gate, consensus_authority=consensus_display,
                                      final_state=(operation_advice or {}).get('state'))
        opportunity_summary = self._build_opportunity_summary(tags, consensus_display, risk_warnings)

        # 323号 S8：顶层 opportunity_state 同步为 advice_builder 降级后的 state
        # （实时风控：≥2维反向/停牌等降级须在时机行与建议卡间保持一致）
        _final_state = _arb['opportunity_state']
        _final_evidence = _arb['state_evidence']
        if operation_advice and operation_advice.get('state'):
            if operation_advice['state'] != _arb['opportunity_state']:
                _final_state = operation_advice['state']
                _final_evidence = [operation_advice.get('state_reason')
                                   or '实时风控降级'] + _final_evidence

        return {
            'ts_code': ts_code,
            'name': name,
            'diagnosis_date': datetime.now().strftime('%Y-%m-%d'),
            'opportunity_summary': opportunity_summary,
            'tags_summary': tags_summary,
            'opportunity_state': _final_state,   # 321号：机会状态机（唯一结论，S8 实时风控同步）
            'state_evidence': _final_evidence,   # 321号：仲裁依据
            # 330号改进4：暴露跨维冲突证据（缠论vs趋势/高位获利盘/结构风险vs确认），
            # 前端风险边界展示——不再让 arbiter 硬合成掩盖真实矛盾
            'conflict_evidence': _arb.get('conflict_evidence', []),
            # 337号 S3.1：成品仓维度状态透出（弹窗九维灯；status_snapshot 日终生成前=None）
            'dim_states': self._get_status_dim_states(ts_code),
            # 336号 成品仓切换：status_engine 生产环节权威结论（双模块唯一消费源，
            # 实时 evaluate，不依赖日终快照——盘中可用；前端优先展示）
            'status_verdict': self._get_status_verdict(ts_code),
            'cross_validation': {
                'consensus': consensus_display,   # 336号 S2：L1 九维推导共识（成品仓唯一消费）
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

    def _get_status_verdict(self, ts_code: str) -> dict | None:
        """336号 成品仓切换：status_engine 生产环节权威结论（双模块唯一消费源）

        实时 evaluate（读缓存毫秒级，不依赖日终 status_snapshot）；前端优先展示。
        """
        try:
            from app.opportunity_atlas.status_engine import StatusEngine
            r = StatusEngine().evaluate(ts_code)
            if not r:
                return None
            import json as _json
            return {
                'opportunity_state': r['opportunity_state'],
                'status_bar': r['status_bar'],
                'consensus_rate': r['consensus_rate'],
                'direction': r['direction'],
                'conflict_evidence': _json.loads(r['conflict_evidence'] or '[]'),
                'dim_states': _json.loads(r['dim_states'] or '{}'),
                'advice_params': _json.loads(r['advice_params'] or '{}'),
            }
        except Exception as e:
            logger.debug("status_verdict 生成失败 %s: %s", ts_code, e)
            return None

    def _get_status_dim_states(self, ts_code: str) -> dict | None:
        """337号 S3.1：读 status_snapshot.dim_states（日频现状成品九维状态，弹窗九维灯）"""
        try:
            _dm = self._get_dm()
            _row = _dm.cache._query_df(
                "SELECT dim_states, status_bar, consensus_rate, opportunity_state "
                "FROM status_snapshot WHERE ts_code=? LIMIT 1", [ts_code])
            if _row is None or _row.empty:
                return None
            import json as _json
            return {
                'dim_states': _json.loads(_row.iloc[0].get('dim_states') or '{}'),
                'status_bar': _row.iloc[0].get('status_bar'),
                'consensus_rate': _row.iloc[0].get('consensus_rate'),
                'opportunity_state': _row.iloc[0].get('opportunity_state'),
            }
        except Exception as e:
            logger.debug("status_snapshot 读取失败 %s: %s", ts_code, e)
            return None

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

        # ── 估值分级（319号：valuation_level 主导，PE 分位仅作深度细分） ──
        # 修复前：pe_pct/dev 独立判定（与 valuation_level 冲突根源，447+160 只股票矛盾）
        # 修复后：仅 level ∈ (high, extreme_high) 时进入估值分级；
        #         level=fair/low/extreme_low 不构成估值风险（PE 分位高=盈利下滑信号，归 R2 提示）
        try:
            pe_pct = self._safe_float(tags.get('pe_percentile_5y'), None)
            dev = self._safe_float(tags.get('valuation_deviation'), None)
            level = tags.get('valuation_level', '')
            lv = 'none'
            if level in ('high', 'extreme_high'):
                if (pe_pct is not None and pe_pct > 90) or (dev is not None and dev < -20):
                    lv = 'deep'     # 双信号共振（相对贵 + 历史分位高）→ 深度高估
                elif (pe_pct is not None and pe_pct > 80) or (dev is not None and dev < -12):
                    lv = 'moderate'
                else:
                    lv = 'mild'     # level 高但 PE 分位不高 → 轻度标注，不硬否决
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
        """执行共识投票统计

        316号 P3 修复（2026-08-06）：动态加权参与共识统计——
        情绪加权后的投票（adjusted_votes）计入 bullish/bearish 强度，
        共识率 = 优势方向加权强度 / 方向票加权强度（降权影响结果）。
        """
        bullish = 0
        bearish = 0
        neutral = 0
        w_bullish = 0.0   # 加权看多强度（316号 P3）
        w_bearish = 0.0   # 加权看空强度
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
                w_bullish += adj_vote
            elif raw_vote < 0:
                bearish += 1
                w_bearish += abs(adj_vote)
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
        # 316号 P3：分子分母均用加权强度（情绪加权真实参与共识）
        direction_active = w_bullish + w_bearish
        if direction_active > 0 and w_bullish > w_bearish:
            direction = 'bullish'
            rate = w_bullish / direction_active
        elif w_bearish > w_bullish:
            direction = 'bearish'
            rate = w_bearish / direction_active
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
                return 'reduce', '减仓/回避'
            if rate >= 0.35:
                return 'hold', '仅做T/持有'
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

    def _build_verdict(self, consensus: dict, voting_detail: list, tags: dict = None,
                       gate: dict = None, consensus_authority: dict = None,
                       final_state: str = None) -> str:
        """构建自然语言总结

        321号 S2：跨维仲裁状态前置——右侧否决/硬风险/深度高估时，
        verdict 直接输出"回避"语义，不再输出"优质机会建议关注"（修 T3 矛盾）。
        2026-08-10 审查修复：arbitrate 传入权威 gate/consensus（与 diagnose 同源，
        消除 P2 深度高估/P3 强看空边缘漏判）。
        336号 S1.2：final_state 感知——五维共识看多但实时风控（盈亏比/纪律）已降级为
        wait/avoid 时，verdict 不输出"优质机会建议关注"（消灭 603897 同屏矛盾残余）。
        """
        # ── 321号 S2：仲裁状态前置（仅 avoid 覆盖；其余沿用共识文本） ──
        if tags:
            try:
                from app.opportunity_atlas.arbiter import arbitrate
                _arb = arbitrate(tags, gate=gate, consensus=consensus_authority)
                if _arb['opportunity_state'] == 'avoid':
                    reason = _arb['state_evidence'][0] if _arb['state_evidence'] else '出现风险信号'
                    return f'🚫 回避：{reason}'
            except Exception:
                pass

        b = consensus.get('bullish_votes', 0)
        be = consensus.get('bearish_votes', 0)
        n = consensus.get('neutral_votes', 0)
        total = consensus.get('total_active', 0)
        rate = consensus.get('consensus_rate', 0)
        direction = consensus.get('direction', 'neutral')

        if total < 3:
            return f'维度数据不足（仅{total}个有效维度），无法形成有效共识，暂不推荐。'

        if direction == 'bullish':
            desc = f'{b} 个维度看多，{be} 个看空，{n} 个中性，共识率 {rate*100:.1f}%'
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
                if final_state in ('wait', 'avoid'):
                    desc += ' 但实时风控（盈亏比/纪律约束）已降级，建议观望。'
                else:
                    desc += ' 综合判断为优质机会，建议关注。'
            else:
                desc += ' 多空接近，建议观望。'
            return desc

        if direction == 'bearish':
            desc = f'{be} 个维度看空，{b} 个看多，{n} 个中性，共识率 {rate*100:.1f}%'
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
            verification = f'★ 强共识（{consensus.get("bullish_votes", 0)}/{total} 方向一致）'
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
                                gate: dict = None, df=None) -> dict:
        """⚠️ 废弃（2026-08-10 标记）：323号 S0.7 起 operation_advice 由
        advice_builder 生成（唯一仓位/止损/入场来源），本函数仅作 S0.7 失败回退
        （cross_validate.diagnose except 分支）。迁移完成后删除。

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
            # 335号 S2.3：deep 从硬否决改"高风险机会强提示 + 仓位压缩"
            # （估值非绝对精准，可能突破——用户决策；潜力侧 dev>30×0.3 已降级）
            action, label = 'hold', '深度高估：价格高位风险，注意追涨（估值非绝对精准）'
            max_ratio = round(max_ratio * 0.3, 2)   # 仓位压缩（status_engine.yaml l0.deep_position_cap）
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

        # ── 321号 S2：跨维仲裁状态派生（统一结论源，修 T4：否决→仓位归零） ──
        # 与 diagnose 传入的权威 gate + 情绪加权 consensus 同源，避免预计算/诊断偏差
        try:
            from app.opportunity_atlas.arbiter import arbitrate
            _arb = arbitrate(tags, gate=gate, consensus=consensus)
            _state = _arb['opportunity_state']
            if _state == 'avoid':
                action, label = 'not_recommended', f"回避：{_arb['state_evidence'][0]}"
                max_ratio = 0.0
            elif _state == 'wait':
                if action in ('build_position', 'add_position'):
                    action, label = 'hold', '等待：右侧信号未确认或共识不足'
                max_ratio = min(max_ratio, 0.2)   # 等待态仓位上限 0.2（保守）
            elif _state == 'light':
                max_ratio = round(max_ratio * 0.5, 2)   # 可轻仓 → 仓位减半
            # enter：保持上方闸门2/门禁计算的仓位
        except Exception:
            pass

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
        """⚠️ 废弃（2026-08-10 标记）：323号 S0.7 起交易计划由 advice_builder
        executable 生成（现价入场 + 60日低点止损），本函数仅被已废弃的
        _build_operation_advice 调用。迁移完成后删除。

        316号 P4：结构化交易计划（§5.3 规则）

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

        # 建仓类建议：分批入场 + 止损/目标（首仓随 max_ratio 缩放：40-60%）
        if action in ('build_position', 'add_position') and max_ratio > 0:
            # 2026-08-06 修复：原公式 0.4*max_ratio/max(max_ratio,0.1)*100 恒为 40%
            # （冗余缩放抵消），未体现"首仓 40-60% 按风险等级下调"
            # （方案 §5.3）。改为随 max_ratio 线性缩放：0.6→60%、≤0.1→43%
            first = round((40 + 20 * min(max_ratio / 0.6, 1.0)))
            remaining = 100 - first
            second = third = remaining // 2
            entry_plan = []
            if ma10 and ma20 and price > ma20:
                entry_plan.append({'price': f'回踩 MA10（{ma10:.2f}-{ma20:.2f}）', 'ratio': f'{first}%',
                                   'condition': '首次建仓（分批）'})
            else:
                entry_plan.append({'price': f'当前价 {price:.2f}', 'ratio': f'{first}%', 'condition': '首次建仓'})
            if hi60 and price < hi60:
                entry_plan.append({'price': f'放量突破前高 {hi60:.2f}', 'ratio': f'{second}%',
                                   'condition': '右侧加仓'})
            else:
                entry_plan.append({'price': '回踩 MA10 不破', 'ratio': f'{second}%',
                                   'condition': '回踩加仓'})
            entry_plan.append({'price': f'回踩 MA20（{ma20:.2f}）', 'ratio': f'{third}%',
                               'condition': '深度回踩补仓'})

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

    def _eps_yoy(self, ts_code: str) -> float | None:
        """计算每股收益同比（basic_eps 同月跨年，income_cache）

        319号修订版：盈利方向用于估值矛盾场景的数据驱动分叉。
        Returns: 同比变化率（小数，如 0.25 = +25%），无数据返回 None
        """
        try:
            dm = self._get_dm()
            df = dm.get_cached_income(ts_code)
            if df is None or df.empty or 'basic_eps' not in df.columns:
                return None
            df = df.sort_values('end_date', ascending=False)
            latest = df.iloc[0]
            try:
                latest_end = pd.Timestamp(latest['end_date'])
            except Exception:
                return None
            target = latest_end - pd.DateOffset(years=1)
            # end_date 可能是 date 对象或字符串，统一转 Timestamp 比较
            match = df[df['end_date'].apply(lambda d: pd.Timestamp(d) == target)]
            if match.empty:
                return None
            cur = latest['basic_eps']
            prev = match.iloc[0]['basic_eps']
            if pd.isna(cur) or pd.isna(prev) or prev == 0:
                return None
            return (float(cur) - float(prev)) / abs(float(prev))
        except Exception:
            return None

    def _build_risk_warnings(self, tags: dict, gate: dict = None,
                             eps_yoy: float = None, pb_pct: float = None) -> list[dict]:
        """构建风险提示列表（316号 P1：估值分级提示 + 流动性风险）

        319号修订版：估值矛盾场景数据驱动分叉（EPS 方向 × PB 分位）：
          - EPS 下滑 → 盈利下滑风险
          - EPS 增长 + PB 分位低 → 困境反转（机会类描述，非风险）
          - EPS 增长 + PB 分位高 → 估值收缩风险
          - 无 EPS 数据 → 不输出 PE 相关提示（避免无依据输出）
        """
        warnings: list[dict] = []

        fina = tags.get('fina_health', '')
        FINA_MAP = {'suspicious': '存疑', 'fail': '不通过'}
        fina_label = FINA_MAP.get(fina, fina)
        if fina in ('suspicious', 'fail'):
            warnings.append({'type': 'company', 'content': f'财务健康评级为{fina_label}，存在基本面风险'})

        # 319号：估值风险提示以 valuation_level 为准（消除"定位低估/提示偏高"冲突）
        if gate is None:
            gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}
        val_lv = gate.get('valuation', 'none')
        _level = tags.get('valuation_level', '')
        _pe_pct = tags.get('pe_percentile_5y', '')
        if val_lv == 'deep':
            warnings.append({'type': 'valuation', 'content': '深度高估（估值等级高估 + PE 历史分位 >90%），估值泡沫风险，暂不介入'})
        elif val_lv == 'moderate':
            warnings.append({'type': 'valuation', 'content': '估值偏高（估值等级偏高 + PE 分位 80-90%），安全边际有限，仓位减半'})
        elif val_lv == 'mild':
            warnings.append({'type': 'valuation', 'content': '估值略偏高（估值等级偏高），注意追高风险'})
        # 319号：矛盾场景——估值等级低估/合理但 PE 历史分位偏高
        # 修订版：按 EPS 方向 × PB 分位数据驱动分叉（取消"需核实"推诿文案）
        elif _level in ('low', 'extreme_low', 'fair') and _pe_pct:
            try:
                if float(_pe_pct) > 60:
                    _pb = pb_pct if pb_pct is not None else self._safe_float(
                        tags.get('pb_percentile_5y'), None)
                    if eps_yoy is None:
                        # 无 EPS 数据：不输出 PE 相关提示（避免无依据输出）
                        pass
                    elif eps_yoy < 0:
                        warnings.append({'type': 'valuation',
                                         'content': '盈利下滑，PE 高位源于盈利萎缩，注意基本面风险'})
                    elif _pb is not None and _pb < 40:
                        # 盈利增长 + 资产端便宜 → 困境反转机会特征（非风险）
                        warnings.append({'type': 'valuation',
                                         'content': '盈利改善中且资产端便宜（PB 近5年低分位），属周期底部/困境反转特征——PE 高源于盈利基数低，注意盈利持续性'})
                    else:
                        warnings.append({'type': 'valuation',
                                         'content': '盈利增长，但 PE 处历史高位——已计入较多增长预期，若盈利增速回落，估值有收缩风险'})
            except (ValueError, TypeError):
                pass

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
        """获取上一个交易日（YYYY-MM-DD）——经 DataManager 网关（红线5）"""
        return self._get_dm().get_previous_trade_date()

    def _compute_daily_change(self, ts_code: str, today_tags: dict) -> dict:
        """计算当日 vs 上日标签变化（299号§5.2 八维度监控）

        Returns:
            {has_changes, changes: [{tag, label, old_value, new_value, level, summary}]}
        """
        yesterday = self._get_previous_trade_date()
        if yesterday is None:
            return {'has_changes': False, 'changes': [], 'change_count': 0,
                    'focus_items': []}

        # 加载上日标签（合规整改：经 DataManager 网关，替代直连 cache.conn）
        try:
            yesterday_tags = self._get_dm().get_tags_by_date(ts_code, yesterday)
        except Exception:
            yesterday_tags = {}

        if not yesterday_tags:
            return {'has_changes': False, 'changes': [], 'change_count': 0,
                    'focus_items': []}

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
