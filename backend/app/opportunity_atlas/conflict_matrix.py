"""L4 冲突矩阵 — 390号方案 v3.0 §6.3/§6.4

跨维度交叉冲突检测 + 语义模式识别。
从 dims_factor（因子聚合层）、tags（标签层）、dim_results（维度引擎原始输出）
三路输入中检测15条冲突规则（C1-C14），并根据冲突分布识别4种语义类型。

返回结构:
{
    'fatal_to_veto':        List[str],   # 致命冲突列表（含C4+/C4++/C7/C8/C9/C11+）
    'warn_for_semantic':    List[str],   # 警告冲突列表
    'semantic_type':        str,         # 矛盾型/追高警示型/确认型/初现型
    'semantic_adjustment':  float,       # 语义调整系数
    'all_conflicts':        List[str],   # 全部冲突（fatal+warn）
}
"""
from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)


# ── 安全取值辅助 ──

def _safe_get(d: dict, *keys: str, default: Any = None) -> Any:
    """多级安全取值，任意层级缺失返回default"""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _safe_float(val: Any, default: float = 0.0) -> float:
    """安全转浮点"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_str(val: Any, default: str = '') -> str:
    """安全转字符串"""
    if val is None:
        return default
    return str(val)


def detect(
    dims_factor: dict,
    tags: dict,
    dim_results: dict,
    consensus_rate: float = 0.5,
    vol_ratio: float = 1.0,
) -> dict:
    """检测维度间交叉冲突并识别语义模式（390号方案v3.0 §6.3/§6.4）

    Args:
        dims_factor:  因子聚合层输出，含 emotion/valuation/structure 等子结构
        tags:         预计算标签集（right_side_confirm, main_force_presence 等）
        dim_results:  维度引擎原始输出（dim2~dim7），键名为引擎标识
        consensus_rate: 市场共识度 [0, 1]
        vol_ratio:    成交量比率（当前量 / 均量）

    Returns:
        {
            'fatal_to_veto':       List[str],
            'warn_for_semantic':   List[str],
            'semantic_type':       str,
            'semantic_adjustment': float,
            'all_conflicts':       List[str],
        }
    """
    dims_factor = dims_factor or {}
    tags = tags or {}
    dim_results = dim_results or {}

    fatal: List[str] = []
    warn: List[str] = []

    # ── 从各维度引擎结果中安全提取字段 ──
    # 490号（C 类修正：跨维取错）：dim_results 的真实键为
    #   structure / volume_price / chip_fund / emotion / risk / valuation，
    #   此前按 'dim2'~'dim7' 查询（无生产者）后回退到 signal/structure → 取到错误的维
    #   （chanlun_phase/divergence_type/level_trends 落到 dim1 signal、stage_name 落到 dim2
    #    结构），致 C1/C2/C2b/C3/C6/C10/C11 判定输入恒空。
    # 结构维（dim2 引擎）
    structure = dim_results.get('structure') or {}
    structure_sd = structure.get('status_description') or {}
    chanlun_phase = _safe_str(_safe_get(structure_sd, 'chanlun_phase'))
    divergence_type = _safe_str(_safe_get(structure_sd, 'divergence_type'))
    divergence_strength = _safe_float(_safe_get(structure_sd, 'divergence_strength'))
    trend_structure_signal = _safe_str(_safe_get(structure_sd, 'trend_structure_signal'))
    _multi_level = structure_sd.get('multi_level') or {}

    # 量价维（dim3 引擎）
    volume_price = dim_results.get('volume_price') or {}
    volume_price_sd = volume_price.get('status_description') or {}
    # 量价背离：取结构化 divergence_type（'top'/'bottom'/''），非展示文本 divergence
    vp_divergence = _safe_str(_safe_get(volume_price_sd, 'divergence_type'))
    # 量比：取数值键 vol_ratio_value（490号补产出）；缺则回退入参
    vp_vol_ratio = _safe_float(_safe_get(volume_price_sd, 'vol_ratio_value'), vol_ratio)
    risk_notes = volume_price_sd.get('risk_notes') or []

    # 筹码维（dim4 引擎）
    chip_fund = dim_results.get('chip_fund') or {}
    chip_fund_sd = chip_fund.get('status_description') or {}
    # 阶段取 judgment.phase（英文枚举 building/washing/lifting/distributing）；
    # sd['phase'] 为展示文本（"建仓（…）"）不可直接比对
    dim4_phase = _safe_str(_safe_get(chip_fund.get('judgment') or {}, 'phase'))
    chip_fund_phase = dim4_phase
    crowding_level = _safe_str(_safe_get(chip_fund_sd, 'crowding_level'))
    # 散户/机构倾向在 sd 内（此前读容器顶层 → 恒空）
    retail_institution = _safe_str(_safe_get(chip_fund_sd, 'retail_institution'))
    cost_concentration = _safe_str(_safe_get(chip_fund_sd, 'cost_concentration'))
    cost_profit_ratio = _safe_float(_safe_get(chip_fund_sd, 'cost_profit_ratio'))

    # dim5: 情绪维度 — 从 dims_factor 读取
    emotion_factor = dims_factor.get('emotion') or {}
    emotion_direction = int(_safe_float(emotion_factor.get('direction')))

    # dim6: 风险维度
    risk = dim_results.get('risk') or {}
    risk_sd = risk.get('status_description') or {}
    atr_pct = _safe_float(_safe_get(risk_sd, 'atr_pct'))
    rr_value = _safe_float(_safe_get(risk_sd, 'rr_value'))
    risk_level = _safe_str(_safe_get(risk_sd, 'risk_level', default=risk.get('risk_level', '')))
    dist_to_support_pct = _safe_float(_safe_get(risk_sd, 'dist_to_support_pct'))
    dist_to_resistance_pct = _safe_float(_safe_get(risk_sd, 'dist_to_resistance_pct'))

    # dim7: 估值维度 — 从 dims_factor 读取
    valuation_factor = dims_factor.get('valuation') or {}
    valuation_direction = int(_safe_float(valuation_factor.get('direction')))
    # dim7 anchor ratings（490号补产出：此前未落 sd → C14 恒不触发）
    valuation = dim_results.get('valuation') or {}
    valuation_sd = valuation.get('status_description') or {}
    asset_anchor_rating = _safe_float(_safe_get(valuation_sd, 'asset_anchor_rating', default=0))
    earnings_anchor_rating = _safe_float(_safe_get(valuation_sd, 'earnings_anchor_rating', default=0))

    # dims_factor 结构方向
    structure_factor = dims_factor.get('structure') or {}
    structure_direction = int(_safe_float(structure_factor.get('direction')))

    # ── C1: 欲病阶段 + 强确认 → warn ──
    right_side_confirm = _safe_str(tags.get('right_side_confirm'))
    if '欲病' in chanlun_phase and right_side_confirm == '强确认':
        warn.append('C1: 缠论欲病阶段+强确认（方向未定，过度追入风险）')

    # ── C2（490号删除）：原比对 dim3 的 stage_name == 'DOWNTREND_ACTIVE' ──
    #   dim3 量价引擎无趋势阶段产出（其真实状态词表为 vp_state_label，如"放量突破(筹码转换)"），
    #   'DOWNTREND_ACTIVE' 无任何产出源 → 规则恒不触发且与 C11（背离+结构看多）语义重叠。
    #   如需恢复，须先由引擎定义量价趋势阶段枚举（登记 490 §登记项）。

    # ── C2b: 多时间框架趋势分歧 → warn ──
    # 490号：源改为 dim2 多级别联立（457号 MultiLevelChanlunAnalyzer）的 direction_map，
    #   取代原 phantom 键 level_trends（无生产者）
    _dm = _multi_level.get('direction_map') if isinstance(_multi_level, dict) else {}
    if isinstance(_dm, dict):
        _daily_dir = _safe_str(_dm.get('daily'))
        _weekly_dir = _safe_str(_dm.get('weekly'))
        _bull = ('up', '上升', '多')
        _bear = ('down', '下降', '空')
        if ((_daily_dir in _bull and _weekly_dir in _bear)
                or (_daily_dir in _bear and _weekly_dir in _bull)):
            warn.append(f'C2b: 日线{_daily_dir}+周线{_weekly_dir}（多时间框架趋势分歧）')

    # ── C3: 冰点+低估值+顶部背离 → warn ──
    if (emotion_direction == -1
            and valuation_direction == 1
            and vp_divergence == 'top'):
        warn.append('C3: 情绪冰点+估值低估+量价顶部背离（ice+low_valuation+top_divergence）')

    # ── C4: 筹码吸筹/拉升 + 拥挤度高 → warn ──
    if (chip_fund_phase in ('building', 'lifting')
            and crowding_level in ('HIGH', 'HIGH_CROWDING')):
        warn.append('C4: 筹码吸筹/拉升阶段+拥挤度高（跟风过热风险）')

    # ── C4+: 主力出货 + 吸筹/拉升 → fatal ──
    if ('主力出货' in retail_institution
            and dim4_phase in ('building', 'lifting')):
        fatal.append('C4+: 主力出货+筹码吸筹/拉升阶段（严重矛盾，资金出逃）')

    # ── C4++: 单峰密集+高拥挤+高获利 → fatal ──
    # 490号：值域对齐引擎真实枚举（cost_concentration 为 concentrating/dispersing/stable；
    #   crowding_level 为 CrowdingFactor 分档 HIGH_CROWDING/MEDIUM_CROWDING/LOW_CROWDING）
    if (cost_concentration in ('单峰密集', 'concentrating', 'tight')
            and crowding_level in ('HIGH', 'HIGH_CROWDING')
            and cost_profit_ratio > 0.7):
        fatal.append(
            f'C4++: 单峰密集+高拥挤+获利盘{cost_profit_ratio:.0%}（集中兑现风险极高）'
        )

    # ── C5: ATR高+盈亏比差+低共识 → warn ──
    if atr_pct > 0.7 and rr_value < 1.0 and consensus_rate < 0.5:
        warn.append(
            f'C5: ATR{atr_pct:.2f}>0.7+盈亏比{rr_value:.2f}<1.0+共识{consensus_rate:.2f}<0.5'
            '（高波动低收益+市场分歧）'
        )

    # ── C6: 趋势背驰 + 123突破 → fatal/warn ──
    if (divergence_type == '趋势背驰'
            and trend_structure_signal == '123_buy_breakout'):
        if divergence_strength > 0.7:
            fatal.append(
                f'C6: 趋势背驰(强度{divergence_strength:.2f}>0.7)+123买突破'
                '（强背驰+突破=反转确认）'
            )
        else:
            warn.append(
                f'C6: 趋势背驰(强度{divergence_strength:.2f})+123买突破'
                '（弱背驰+突破，信号待确认）'
            )

    # ── C7: 高风险+确认信号 → fatal ──
    if risk_level in ('高', '极高') and right_side_confirm in ('强确认', '基础确认'):
        fatal.append(
            f'C7: 风险等级{risk_level}+右侧{right_side_confirm}'
            '（风险-收益严重失衡）'
        )

    # ── C8: 高获利+无主力+确认 → fatal ──
    main_force_presence = _safe_str(tags.get('main_force_presence'))
    if (cost_profit_ratio > 0.8
            and main_force_presence == 'none'
            and right_side_confirm in ('强确认', '基础确认')):
        fatal.append(
            f'C8: 获利盘{cost_profit_ratio:.0%}>0.8+无主力+右侧{right_side_confirm}'
            '（高位接盘风险极高）'
        )

    # ── C9: 监管事件 → fatal（冗余安全检查：L0已处理regulatory，此处防御性保留）──
    catalyst_event = _safe_str(tags.get('catalyst_event'))
    if catalyst_event == 'regulatory':
        fatal.append('C9: 监管事件催化（强制回避）')

    # ── C10: 趋势背驰 + 高共识 → warn ──
    if divergence_type == '趋势背驰' and consensus_rate > 0.7:
        warn.append(
            f'C10: 趋势背驰+共识{consensus_rate:.2f}>0.7'
            '（共识过度一致时背驰信号价值更高）'
        )

    # ── C11: 量价顶部背离 + 结构看多 → warn/fatal ──
    # 490号：背离取结构化 divergence_type（'top'）；量比取 dim3 vol_ratio_value（真实数值）
    if vp_divergence == 'top' and structure_direction == 1:
        if vp_vol_ratio < 0.5:
            fatal.append(
                f'C11+: 量价顶部背离+结构看多+量比{vp_vol_ratio:.2f}<0.5'
                '（缩量顶部背离，反转概率极高）'
            )
        else:
            warn.append('C11: 量价顶部背离+结构看多（量价背离风险）')

    # ── C12: 结构风险提示 + 结构看多 → warn ──
    if isinstance(risk_notes, list) and len(risk_notes) > 0 and structure_direction == 1:
        warn.append(
            f'C12: 结构维度含{len(risk_notes)}条风险提示+结构看多（风险因素未消除）'
        )

    # ── C13: 隐含盈亏比偏差 → warn ──
    if rr_value > 0 and dist_to_support_pct < 0 and dist_to_resistance_pct > 0:
        implied_rr = dist_to_resistance_pct / abs(dist_to_support_pct)
        if abs(implied_rr - rr_value) > 0.5:
            warn.append(
                f'C13: 隐含盈亏比{implied_rr:.2f}与计算值{rr_value:.2f}'
                f'偏差{abs(implied_rr - rr_value):.2f}>0.5'
                '（支撑/压力度量不一致）'
            )

    # ── C14: 资产锚定 vs 盈利锚定背离 → warn ──
    if asset_anchor_rating <= -1 and earnings_anchor_rating >= 1:
        warn.append(
            f'C14: 资产锚定{asset_anchor_rating}<=-1+盈利锚定{earnings_anchor_rating}>=1'
            '（估值锚定逻辑矛盾）'
        )

    # ── 语义类型识别（390号方案§6.4，优先级从高到低） ──
    fatal_count = len(fatal)
    warn_count = len(warn)

    # 计算 aligned_count：dims_factor 中看多方向的一致数（6个维度）
    _directions = []
    for key in ('structure', 'emotion', 'valuation'):
        _d = dims_factor.get(key) or {}
        _directions.append(int(_safe_float(_d.get('direction'))))
    # 从 dim_results 补充其他维度方向
    for dr_key in ('signal', 'chip_fund', 'risk'):
        _dr = dim_results.get(dr_key) or {}
        _dr_j = _dr.get('judgment') or {}
        _directions.append(int(_safe_float(_dr_j.get('overall_direction', 0))))

    aligned_count = sum(1 for d in _directions if d == 1)
    max(len(_directions), 1)

    dist_to_prev_high_pct = _safe_float(
        _safe_get(risk_sd, 'dist_to_prev_high_pct'), default=-10.0
    )

    semantic_type = '初现型'
    semantic_adjustment = 1.0

    if fatal_count >= 1 or warn_count >= 3:
        # 矛盾型：致命冲突存在 或 警告>=3 → 最保守
        semantic_type = '矛盾型'
        semantic_adjustment = 0.5
    elif consensus_rate >= 0.8 and dist_to_prev_high_pct > -3:
        # 追高警示型：高共识+接近前高
        semantic_type = '追高警示型'
        semantic_adjustment = 0.7
    elif aligned_count >= 4 and consensus_rate >= 0.7:
        # 确认型：多数维度看多+高共识
        semantic_type = '确认型'
        semantic_adjustment = 1.15
    elif aligned_count == 2 and divergence_strength <= 0.7:
        # 初现型：少数维度看多+无强背驰
        semantic_type = '初现型'
        semantic_adjustment = 1.0
    # 其他情况保持默认初现型

    all_conflicts = fatal + warn

    result = {
        'fatal_to_veto': fatal,
        'warn_for_semantic': warn,
        'semantic_type': semantic_type,
        'semantic_adjustment': semantic_adjustment,
        'all_conflicts': all_conflicts,
    }

    if fatal or warn:
        logger.info(
            'conflict_matrix: %d fatal, %d warn → %s (adj=%.2f)',
            fatal_count, warn_count, semantic_type, semantic_adjustment,
        )

    return result
