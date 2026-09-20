"""第8维 状态总结引擎

358号方案 v4.1：第8维状态总结（纯整理输出）。

职责：读取 dim1-dim7 的 plain 字段和 judgment 输出，
     组装为综合状态条 + 八维红绿灯映射 + 共识率 + 冲突检测。

设计原则（358号§6.1）：
  - 第7维（状态总结）是纯整理输出，不变更内容、不判定
  - 读取前7维的 plain 字段并组装
  - 输出 status_bar + eight_dim_summary + consensus_rate + conflict + text

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 状态条8态定义（358号 + 现有系统兼容）
# ═══════════════════════════════════════════════════════════

STATUS_BAR_STATES = {
    'strong_confirm': '强势确认',
    'trend_confirm': '趋势确认',
    'light_confirm': '轻仓确认',
    'neutral': '中性观望',
    'cautious': '谨慎观望',
    'risk_warning': '风险警示',
    'bearish': '看空回避',
    'exit': '退出观望',
}


# ═══════════════════════════════════════════════════════════
# 前端文字类契约常量（436号 B1，dim8 整体归集器使用）
# ═══════════════════════════════════════════════════════════

# 顶层 light：颜色名 → emoji（前端展示约定，见 436 §3.2 D1）
_LIGHT_EMOJI = {'green': '🟢', 'red': '🔴', 'yellow': '🟡'}

# 七段键契约（产出键 → 对应 dim_results 数据源键；summary 由 dim8 自行组装）
# 与两前端 dimOrder/segOrder 逐一对齐：treemap/indicator-ide 均读
#   signal/structure/volume_price/fund_chip/emotion/risk/summary
# 不含 valuation（436 D5：前端 dimOrder 无此键，不产出）
SEVEN_DIM_SPEC = [
    ('signal',       'signal',       '信号确认状态'),
    ('structure',    'structure',    '结构位置状态'),
    ('volume_price', 'volume_price', '量价健康度'),
    ('fund_chip',    'chip_fund',    '资金与筹码状态'),
    ('emotion',      'emotion',      '情绪环境状态'),
    ('risk',         'risk',         '风险边界状态'),
]

# 段标题映射（summary 段标题）
SUMMARY_TITLE = '状态总结'


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _extract_dim_judgment(dim_results: dict, dim_name: str) -> dict:
    """从维度引擎结果中提取 judgment"""
    result = dim_results.get(dim_name, {})
    if result and isinstance(result, dict):
        return result.get('judgment', {})
    return {}


def _extract_dim_light(dim_results: dict, dim_name: str) -> str:
    """从维度引擎结果中提取 overall_light"""
    jg = _extract_dim_judgment(dim_results, dim_name)
    return jg.get('overall_light', jg.get('light', 'yellow'))


def _extract_dim_direction(dim_results: dict, dim_name: str) -> int:
    """从维度引擎结果中提取 overall_direction"""
    jg = _extract_dim_judgment(dim_results, dim_name)
    return jg.get('overall_direction', 0)


def _extract_dim_audit_confidence(dim_results: dict, dim_name: str) -> float:
    """从维度引擎结果中提取 audit.confidence"""
    result = dim_results.get(dim_name, {})
    if result and isinstance(result, dict):
        au = result.get('audit', {})
        return au.get('confidence', 0)
    return 0


def _extract_dim_confidence(dim_results: dict, dim_name: str) -> float:
    """提取维度连续置信度（judgment.continuous_value），缺失回退 0.5（420号方案）"""
    jg = _extract_dim_judgment(dim_results, dim_name)
    try:
        return float(jg.get('continuous_value', 0.5))
    except (TypeError, ValueError):
        return 0.5


def _extract_dim_rr(dim_results: dict) -> float | None:
    """提取盈亏比（risk.status_description.rr_value），缺失返回 None（420号方案）"""
    result = dim_results.get('risk', {})
    if result and isinstance(result, dict):
        sd = result.get('status_description', {})
        if sd and isinstance(sd, dict):
            rr = sd.get('rr_value')
            if rr is None:
                return None
            try:
                return float(rr)
            except (TypeError, ValueError):
                return None
    return None


def _is_signal_decaying(dim_results: dict) -> bool:
    """信号是否老化：生命周期末期/衰竭 或 维护状态非 healthy（420号方案，对齐因子衰减概念）"""
    sig = dim_results.get('signal', {})
    if not isinstance(sig, dict):
        return False
    sd = sig.get('status_description', {})
    if isinstance(sd, dict):
        stage = str(sd.get('lifecycle_stage', ''))
        if '末' in stage or '衰竭' in stage:
            return True
    jg = sig.get('judgment', {})
    if isinstance(jg, dict):
        maint = jg.get('maintenance', {})
        if isinstance(maint, dict) and maint.get('status') not in (None, 'healthy'):
            return True
    return False


# ═══════════════════════════════════════════════════════════
# 八维红绿灯映射
# ═══════════════════════════════════════════════════════════

def _build_eight_dim_summary(dim_results: dict) -> dict:
    """构建八维红绿灯映射"""
    dim_map = {
        'signal': '信号确认',
        'structure': '结构位置',
        'volume_price': '量价健康',
        'chip_fund': '资金筹码',
        'emotion': '情绪环境',
        'risk': '风险边界',
        'valuation': '价值估算',
        'summary': '状态总结',
    }
    summary = {}
    for key, name in dim_map.items():
        if key == 'summary':
            summary[key] = {'name': name, 'light': 'yellow'}
            continue
        light = _extract_dim_light(dim_results, key)
        summary[key] = {'name': name, 'light': light}
    return summary


# ═══════════════════════════════════════════════════════════
# 共识率计算
# ═══════════════════════════════════════════════════════════

# 维度权重（基于358号方案的动态权重简化版）
DIM_WEIGHTS = {
    'signal': 0.15,
    'structure': 0.20,
    'volume_price': 0.15,
    'chip_fund': 0.20,
    'emotion': 0.10,
    'risk': 0.15,
    'valuation': 0.05,
}


def _calc_consensus_rate(dim_results: dict) -> float:
    """加权共识率：灯色方向 × 连续置信度（420号方案增强）

    对齐知识库"多指标共识机制"——置信度高的维度对共识贡献更大。
    方向取灯色（green=+1/yellow=0/red=-1），权重 = DIM_WEIGHTS × 置信度修正。
    兼容性：continuous_value 缺失时置信度=0.5 → 权重同比例缩，结果与等权一致。
    """
    light_to_value = {'green': 1.0, 'yellow': 0.0, 'red': -1.0}
    total = 0.0
    weight_sum = 0.0
    for dim_key, base_w in DIM_WEIGHTS.items():
        light = _extract_dim_light(dim_results, dim_key)
        direction = light_to_value.get(light, 0.0)
        # 置信度修正：continuous_value 越高，该维对共识的贡献权重越大
        confidence = _extract_dim_confidence(dim_results, dim_key)
        eff_w = base_w * (0.3 + 0.7 * confidence)  # 保底 30% 权重，避免置信度 0 时维度失效
        total += direction * eff_w
        weight_sum += eff_w

    if weight_sum > 0:
        avg = total / weight_sum
        # 映射到0-1: -1→0, 0→0.5, +1→1.0
        return round(max(0, min(1, (avg + 1) / 2)), 2)
    return 0.5


# ═══════════════════════════════════════════════════════════
# 冲突检测
# ═══════════════════════════════════════════════════════════

def _detect_conflicts(dim_results: dict) -> list[dict]:
    """检测维度间矛盾"""
    conflicts = []

    # 1. 结构上升 + 资金派发
    struct_dir = _extract_dim_direction(dim_results, 'structure')
    chip_phase = _extract_dim_judgment(dim_results, 'chip_fund').get('phase', '')
    if struct_dir == 1 and chip_phase == 'distributing':
        conflicts.append({
            'dim1': '结构位置', 'dim2': '资金筹码',
            'description': '结构上升但主力在出货——上涨可能是诱多',
            'severity': 'high',
        })

    # 2. 量价背离 + 信号确认
    vp_light = _extract_dim_light(dim_results, 'volume_price')
    signal_dir = _extract_dim_direction(dim_results, 'signal')
    if vp_light == 'red' and signal_dir == 1:
        conflicts.append({
            'dim1': '量价健康', 'dim2': '信号确认',
            'description': '量价背离但信号确认上涨——信号可靠性存疑',
            'severity': 'medium',
        })

    # 3. 情绪退潮 + 信号确认
    emotion_light = _extract_dim_light(dim_results, 'emotion')
    if emotion_light == 'red' and signal_dir == 1:
        conflicts.append({
            'dim1': '情绪环境', 'dim2': '信号确认',
            'description': '情绪退潮但信号确认上涨——追涨风险大',
            'severity': 'medium',
        })

    # 4. 风险高 + 估值低估
    risk_light = _extract_dim_light(dim_results, 'risk')
    val_light = _extract_dim_light(dim_results, 'valuation')
    if risk_light == 'red' and val_light == 'green':
        conflicts.append({
            'dim1': '风险边界', 'dim2': '价值估算',
            'description': '高风险但估值低估——可能是价值陷阱',
            'severity': 'low',
        })

    # 5. 结构下降 + 量价健康
    if struct_dir == -1 and vp_light == 'green':
        conflicts.append({
            'dim1': '结构位置', 'dim2': '量价健康',
            'description': '趋势下行但量价健康——可能是反弹',
            'severity': 'low',
        })

    # ── 420号方案增强4：基于未消费富字段的新冲突规则 ──

    # 6. 散户过热/减仓 + 结构上升（筹码主力视角：散户反向指标）
    chip_sd = dim_results.get('chip_fund', {})
    chip_retail = ''
    if isinstance(chip_sd, dict):
        chip_retail = str(((chip_sd.get('status_description', {}) or {}).get('retail_institution', ''))
                          or _extract_dim_judgment(dim_results, 'chip_fund').get('retail_institution', ''))
    if struct_dir == 1 and '散户' in chip_retail and '减' in chip_retail:
        conflicts.append({
            'dim1': '结构位置', 'dim2': '资金筹码',
            'description': '结构上升但散户资金在减——上涨动力存疑',
            'severity': 'medium',
        })

    # 7. 量价形态空头 + 信号确认（多形态共振：形态与信号背离）
    vp_sd = dim_results.get('volume_price', {})
    vp_pattern = ''
    if isinstance(vp_sd, dict):
        vp_pattern = str((vp_sd.get('status_description', {}) or {}).get('pattern', ''))
    if signal_dir == 1 and any(k in vp_pattern for k in ('空头', '下跌', 'breakdown', 'bear')):
        conflicts.append({
            'dim1': '量价健康', 'dim2': '信号确认',
            'description': f'量价形态{vp_pattern}但信号确认上涨——形态与信号背离',
            'severity': 'medium',
        })

    # 8. 波动率放大 + 结构下降（Barra风险：高波动下行加速）
    risk_sd = dim_results.get('risk', {})
    vol_level = ''
    if isinstance(risk_sd, dict):
        vol_level = str((risk_sd.get('status_description', {}) or {}).get('volatility_level', ''))
    if struct_dir == -1 and vol_level == 'high':
        conflicts.append({
            'dim1': '结构位置', 'dim2': '风险边界',
            'description': '趋势下行且波动率偏高——下跌可能加速',
            'severity': 'low',
        })

    return conflicts


# ═══════════════════════════════════════════════════════════
# 状态条推导
# ═══════════════════════════════════════════════════════════

def _derive_status_bar(dim_results: dict, consensus_rate: float,
                       conflicts: list) -> str:
    """从共识率+方向+冲突→8态状态条"""
    # 综合方向
    directions = []
    for dim in ['signal', 'structure', 'volume_price', 'chip_fund']:
        directions.append(_extract_dim_direction(dim_results, dim))

    pos_count = sum(1 for d in directions if d > 0)
    neg_count = sum(1 for d in directions if d < 0)

    risk_light = _extract_dim_light(dim_results, 'risk')
    _extract_dim_light(dim_results, 'emotion')

    # 高风险 → 风险警示/看空
    if risk_light == 'red':
        return 'risk_warning'

    # 有高严重度冲突 → 谨慎
    high_conflicts = [c for c in conflicts if c.get('severity') == 'high']
    if high_conflicts:
        return 'cautious'

    # 420号增强3：信号老化 → 强确认降级（对齐因子衰减概念）
    if _is_signal_decaying(dim_results) and consensus_rate >= 0.8 and pos_count >= 3:
        return 'light_confirm'

    # 420号增强2：盈亏比修正（对齐"回报风险比"概念）
    rr_value = _extract_dim_rr(dim_results)
    if rr_value is not None:
        if rr_value >= 2.0:
            # 高盈亏比 → 上修一档（仅当看多且非退出）
            if consensus_rate >= 0.7 and pos_count >= 2:
                return 'strong_confirm' if pos_count >= 3 else 'trend_confirm'
        elif rr_value < 1.0:
            # 低盈亏比 → 下修（抑制盲目确认）
            if consensus_rate >= 0.7 and pos_count >= 2:
                return 'light_confirm'
            elif consensus_rate >= 0.5 and pos_count >= 1:
                return 'neutral'

    # 共识率 + 方向
    if consensus_rate >= 0.8 and pos_count >= 3:
        return 'strong_confirm'
    elif consensus_rate >= 0.7 and pos_count >= 2:
        return 'trend_confirm'
    elif consensus_rate >= 0.5 and pos_count >= 1:
        return 'light_confirm'
    elif neg_count >= 3:
        return 'bearish'
    elif consensus_rate < 0.3:
        return 'exit'
    else:
        return 'neutral'


# ═══════════════════════════════════════════════════════════
# 综合文字生成
# ═══════════════════════════════════════════════════════════

def _generate_text(dim_results: dict, status_bar: str,
                   consensus_rate: float, conflicts: list) -> str:
    """综合文字摘要"""
    bar_cn = STATUS_BAR_STATES.get(status_bar, status_bar)

    # 收集各维现状短句（437-A 字段级编排替代各维 plain——plain 已删除，dim8 不再依赖引擎自产文字）
    dim_names = ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']
    dim_cn = {'signal': '信号', 'structure': '结构', 'volume_price': '量价',
              'chip_fund': '资金', 'emotion': '情绪', 'risk': '风险', 'valuation': '估值'}
    parts = []
    for dim in dim_names:
        seg = (dim_results or {}).get(dim) or {}
        seg_jg = seg.get('judgment', {}) or {}
        seg_sd = seg.get('status_description', {}) or {}
        # 字段级编排短句（T 字段拼「字段名:值」；全空回退 _brief_text 的 judgment state）
        sentence = _compose_dim_text(dim, seg_jg, seg_sd)
        if sentence:
            parts.append(f'{dim_cn.get(dim, dim)}：{sentence}')

    # 420号增强3：信号老化提示（对齐因子衰减概念）
    if _is_signal_decaying(dim_results):
        parts.append('信号：信号老化（进入末期/维护不佳），追涨需谨慎')

    dims_text = '；'.join(parts) if parts else '各维数据不足'

    # 420号增强5：关键量化锚点富化（盈亏比/支撑压力/情绪温度/生命周期天数）
    anchors = []
    rr = _extract_dim_rr(dim_results)
    if rr is not None:
        anchors.append(f'盈亏比{rr:.2f}')
    risk_sd = dim_results.get('risk', {})
    if isinstance(risk_sd, dict):
        risk_sd = risk_sd.get('status_description', {}) or {}
        sp = risk_sd.get('support_price')
        rp = risk_sd.get('resistance_price')
        if sp is not None and rp is not None:
            anchors.append(f'支撑{sp}/压力{rp}')
    emo_sd = dim_results.get('emotion', {})
    if isinstance(emo_sd, dict):
        temp = (emo_sd.get('status_description', {}) or {}).get('temperature', '')
        if temp:
            anchors.append(f'情绪温度{temp}')
    sig_sd = dim_results.get('signal', {})
    if isinstance(sig_sd, dict):
        ld = (sig_sd.get('status_description', {}) or {}).get('lifecycle_days')
        if ld is not None:
            anchors.append(f'信号{ld}天')
    if anchors:
        dims_text = f'{dims_text}｜关键位：{"，".join(anchors)}'

    # 冲突摘要
    conflict_text = ''
    if conflicts:
        conflict_items = [f"{c['description']}" for c in conflicts[:2]]
        conflict_text = f'（注意：{"；".join(conflict_items)}）'

    return f'{bar_cn}（共识{consensus_rate:.0%}）{conflict_text}——{dims_text}'


# ═══════════════════════════════════════════════════════════
# 单段整形（436号 B1 整体归集器使用）
# ═══════════════════════════════════════════════════════════

def _flatten_value(v) -> str:
    """把 judgment 内嵌套 value/label 统一成字符串（避免输出 dict/None 进前端文本）"""
    if isinstance(v, list):
        # 列表字段：dict 项取中文表述（买卖点/风险因素），否则原样转字符串
        items = [_flatten_value(item) for item in v]
        items = [s for s in items if s]
        return '、'.join(items) if items else ''
    if isinstance(v, dict):
        # 形如 {'value': '上升'} / {'label': '集中'} / {'type','point_type','price'}（买卖点）
        for k in ('value', 'label', 'state'):
            if k in v and v[k] is not None:
                return str(v[k])
        # 买卖点 dict：{'type':'buy','point_type':'first_buy','price':2.98}
        pt = v.get('point_type') or v.get('type')
        if pt:
            cn = _POINT_TYPE_CN.get(pt, pt)
            price = v.get('price')
            return f'{cn}({price})' if price is not None else cn
        for sub in v.values():
            if sub is not None and sub != '':
                return str(sub)
        return ''
    return '' if v is None else str(v)


# 买卖点/阶段枚举 → 中文（供 _flatten_value 转述 list[dict] 字段）
_POINT_TYPE_CN: dict[str, str] = {
    'first_buy': '一买', 'second_buy': '二买', 'third_buy': '三买',
    'first_sell': '一卖', 'second_sell': '二卖', 'third_sell': '三卖',
    'buy': '买入', 'sell': '卖出',
}


def _brief_text(key_in: str, jg: dict, sd: dict) -> str:
    """生成该维短结论文本（「标题: 状态 (置信度)」语感，沿用现 generator）"""
    # 取非 meta 的 judgment 值作为状态
    meta = {'overall_light', 'overall_direction', 'continuous_value', 'status_bar',
            'consensus_rate', 'direction', 'status_bar_cn'}
    state = ''
    for jk, jv in jg.items():
        if jk in meta:
            continue
        s = _flatten_value(jv)
        if s:
            state = s
            break
    try:
        conf = float(jg.get('continuous_value') or 0.5)
    except (TypeError, ValueError):
        conf = 0.5
    # 防御边界：continuous_value 契约 0-1，clamp 到 [0,1]，防偶发超值渲染"结构健康120/100"畸形文案。
    conf = max(0.0, min(1.0, conf))
    # 466号 ⑤：structure 维 continuous_value 语义为"结构健康度"，文案改为"结构健康xx/100"，
    #   不再冒充信号"置信xx%"。其余维保持原置信文案。
    if key_in == 'structure':
        return f'{state}（结构健康{conf * 100:.0f}/100）' if state else ''
    return f'{state}（置信{conf:.0%}）' if state else ''


def _segment_from_dim(dim_results: dict, src_key: str, title: str) -> dict | None:
    """按前端契约把单个 dim_results 维整形为报告段；缺维返回 None

    437-A 字段级编排（2026-09-20 拍板后实施）：
      - text：按 _DIM8_T_SUBJECTS[src_key] 字段清单，从 status_description 取「字段名:值」子句
        （字段级「分析逻辑实例→话术」，464 §十二 原料定义）；无映射字段时回退 _brief_text。
      - evidence：按 _DIM8_E_FIELDS[src_key] 字段清单收集佐证（原 _yield_evidence 只取
        plain/text/conclusion 字符串，改为字段级编排）。
      - 缺维（src_key 无输出）→ None（437-A D7：缺维不产段，仅 summary 恒在）。
    数据驱动：加字段 = 在 _DIM8_T_SUBJECTS/_DIM8_E_FIELDS 加一行，不动本函数。
    """
    seg = (dim_results or {}).get(src_key)
    if not isinstance(seg, dict) or not seg:
        return None
    jg = seg.get('judgment', {}) or {}
    sd = seg.get('status_description', {}) or {}
    au = seg.get('audit', {}) or {}
    overall = jg.get('overall_light', jg.get('light', 'yellow'))
    text = _compose_dim_text(src_key, jg, sd)
    evidence = _compose_dim_evidence(src_key, sd)
    return {
        'title': title,
        'light': _LIGHT_EMOJI.get(str(overall), '🟡'),
        'text': text,
        'evidence': evidence[:5],
        'confidence': round(float(jg.get('continuous_value') or au.get('confidence') or 0.5), 2),
        'judgment': {
            'overall_light': jg.get('overall_light', 'yellow'),
            'overall_direction': jg.get('overall_direction', 0),
            'continuous_value': jg.get('continuous_value'),
        },
        'audit': {
            'conditions': [{'name': c.get('name'), 'satisfied': bool(c.get('satisfied'))}
                           for c in (au.get('conditions') or []) if isinstance(c, dict)][:8],
            'satisfied_count': au.get('satisfied_count', 0),
            'total_count': au.get('total_count', 0),
            'confidence': au.get('confidence', 0),
        },
        # plain 键保留（前端 seven_dim 契约段结构含该字段），值与 text 同（各维 plain 已删除，
        # dim8 为唯一叙事口径，段内 plain 不再读各维引擎自产文字）
        'plain': text,
    }


# ── 437-A 字段级编排映射表（2026-09-20 拍板；数据驱动，加字段=加行）──

# 各维 text 主述字段（T）：按序取 status_description 非空值拼「字段名:值」子句。
# 键名以《437-A字段级归集核对报告》3 处修正为准（dim4 direction→fund_flow、
# dim6 volatility_atr→atr_pct、dim2 优先 buy_sell_points_detail）。
_DIM8_T_SUBJECTS: dict[str, list[str]] = {
    'structure': ['chanlun_direction', 'chanlun_strength', 'stage_name', 'trend_basis',
                  'buy_sell_points_detail', 'multi_level_direction_text'],
    'volume_price': ['vp_state', 'health_score', 'volume_energy', 'vol_ratio',
                     'pattern', 'pattern_score', 'rps'],
    'chip_fund': ['phase', 'fund_flow', 'fund_price_divergence', 'cost_structure',
                  'crowding', 'signal', 'margin'],
    'emotion': ['market', 'sector', 'stock', 'quadrant', 'temperature'],
    'risk': ['risk_level', 'support_price', 'resistance_price', 'rr_value', 'rr_level',
             'volatility_level', 'risk_factors'],
    'valuation': ['valuation_level', 'potential_score', 'potential_strength',
                  'fina_health', 'value_trap', 'growth_trap'],
    'signal': ['attribute', 'strength', 'lifecycle_stage', 'verified', 'maintenance'],
}

# 各维 evidence 佐证字段（E）：按序取 status_description 非空值入 evidence 列表。
# 对齐 437-A §三 跨维去重主源（dim3 主源个股情绪 → emotion 不再重复 stock 至 evidence 主位；
# dim4 主源资金流 → valuation 不重复 fund_flow；dim2↔dim6 支撑阻力同源 → risk 主源）。
_DIM8_E_FIELDS: dict[str, list[str]] = {
    'structure': ['vs_zhongshu', 'vs_ma', 'vs_chip', 'vs_support_resistance', 'vs_indicator',
                  'divergence', 'divergence_type', 'level_cross_score', 'ts_strength',
                  'trend_structure_signal', 'chanlun_phase'],
    'volume_price': ['divergence', 'granville'],
    'chip_fund': ['retail_institution', 'fund_price_divergence_risk',
                  'fund_price_divergence_status'],
    'emotion': ['bociasi_quick', 'bociasi_slow'],
    'risk': ['atr_pct', 'volatility_percentile', 'dist_to_support_pct',
             'dist_to_resistance_pct', 'dist_to_prev_high_pct', 'rr_assessment',
             'event_summary', 'liquidity_detail', 'invalidation'],
    'valuation': ['pe_percentile', 'pb_percentile', 'fcf_yield', 'dividend_yield',
                  'revenue_growth', 'potential_breakdown'],
    'signal': ['decay_detail', 'risk_interaction'],
}

# evidence 数值字段表述模板（437 §七-6：数值转自然语言，不裸放）。{v} 为原值。
_DIM8_E_FORMAT: dict[str, str] = {
    'atr_pct': 'ATR占比{v:.2f}%',
    'volatility_percentile': '波动率历史分位{v:.0%}',
    'dist_to_support_pct': '距防守位{v:.1f}%',
    'dist_to_resistance_pct': '距压力位{v:.1f}%',
    'dist_to_prev_high_pct': '距前高{v:.1f}%',
    'rr_value': '盈亏比{v:.2f}',
}

# 各维 text 主述字段的「字段名」中文标签（供「字段名:值」子句）
_DIM8_FIELD_CN: dict[str, str] = {
    'chanlun_direction': '缠论方向', 'chanlun_strength': '结构强度', 'stage_name': '阶段',
    'trend_basis': '趋势依据', 'buy_sell_points_detail': '买卖点', 'multi_level_direction_text': '多级别',
    'vp_state': '量价状态', 'health_score': '健康度', 'volume_energy': '量能',
    'vol_ratio': '量比', 'pattern': '形态', 'pattern_score': '形态评分', 'rps': 'RPS',
    'phase': '主力阶段', 'fund_flow': '资金流', 'fund_price_divergence': '资金价格背离',
    'cost_structure': '筹码结构', 'crowding': '拥挤度', 'signal': '筹码信号', 'margin': '融资',
    'market': '市场情绪', 'sector': '板块情绪', 'stock': '个股情绪', 'quadrant': '情绪象限',
    'temperature': '情绪温度',
    'risk_level': '风险等级', 'support_price': '防守位', 'resistance_price': '压力位',
    'rr_value': '盈亏比', 'rr_level': '盈亏比评级', 'volatility_level': '波动率',
    'risk_factors': '风险因素',
    'valuation_level': '估值水平', 'potential_score': '潜力评分', 'potential_strength': '潜力强度',
    'fina_health': '财务健康', 'value_trap': '估值陷阱', 'growth_trap': '成长陷阱',
    'attribute': '信号属性', 'strength': '信号强度', 'lifecycle_stage': '生命周期',
    'verified': '验证状态', 'maintenance': '维护状态',
}


def _compose_dim_text(src_key: str, jg: dict, sd: dict) -> str:
    """437-A 字段级 text 编排：按 _DIM8_T_SUBJECTS 从 status_description 取 T 字段拼子句。

    规则（对齐 437-A §一）：缺字段不占位（子句跳过）；数值字段转表述由各维引擎
    status_description 已自产文字承载（本层只拼装不重算）；无 T 字段产出时回退 _brief_text。
    """
    fields = _DIM8_T_SUBJECTS.get(src_key, [])
    parts = []
    for f in fields:
        v = (sd or {}).get(f)
        if v is None or v == '' or v == 'none' or v == '无':
            continue
        label = _DIM8_FIELD_CN.get(f, f)
        val = _flatten_value(v)
        if not val:
            continue
        # 引擎自产字段多为完整句子（如 '强流出（5d_outflow）'），直接拼接不加冒号
        parts.append(f'{label}:{val}')
    if parts:
        return '；'.join(parts)
    return _brief_text(src_key, jg, sd)


def _compose_dim_evidence(src_key: str, sd: dict) -> list:
    """437-A 字段级 evidence 编排：按 _DIM8_E_FIELDS 收集 E 字段佐证。

    缺失/空值/占位（'无'/'none'）字段跳过（437 §七-2 有数据则显）；列表字段
    （risk_factors/event_summary/buy_sell_points_detail）展开为多条；数值字段
    按 _DIM8_E_FORMAT 转表述（437 §七-6 不裸放数值）。
    """
    fields = _DIM8_E_FIELDS.get(src_key, [])
    ev = []
    for f in fields:
        v = (sd or {}).get(f)
        if v is None or v == '' or v == 'none' or v == '无':
            continue
        fmt = _DIM8_E_FORMAT.get(f)
        if isinstance(v, list):
            for item in v:
                if item is None or item == '' or item == 'none':
                    continue
                s = fmt.format(v=item) if fmt else _flatten_value(item)
                if s and s not in ev:
                    ev.append(s)
        else:
            if fmt:
                try:
                    s = fmt.format(v=v)
                except (TypeError, ValueError):
                    s = _flatten_value(v)
            else:
                s = _flatten_value(v)
            if s and s not in ev:
                ev.append(s)
    return ev


def _dim1_fallback_segment(tags: dict) -> dict | None:
    """dim1 特例：dim_results 无 signal 维时从 tags.right_side_confirm 造最小段；空则 None"""
    if not tags or isinstance(tags, dict) is False:
        return None
    rsc = tags.get('right_side_confirm')
    if not rsc:
        return None
    light = ('green' if rsc in ('强确认', '基础确认') else ('red' if rsc == '否决' else 'yellow'))
    return {
        'title': '信号确认状态',
        'light': _LIGHT_EMOJI.get(light, '🟡'),
        'text': f'信号确认: {rsc}',
        'evidence': [],
        'confidence': 0.8 if rsc == '强确认' else 0.5,
        'judgment': {'overall_light': light, 'overall_direction': 1 if light == 'green' else 0,
                     'continuous_value': None},
        'audit': {'conditions': [], 'satisfied_count': 0, 'total_count': 0, 'confidence': 0},
        'plain': rsc,
    }


def _relative_strength_sentence(ts_code: str) -> str:
    """462-3：环境定位——近20/60日相对沪深300/上证强弱句（437-A D3「第一层并入 summary 前置」）。

    数据源 relative_strength_cache（438 已闭环，双基准 asof 最新交易日）。
    无数据/异常返回 ''（437 标准「有数据则显、缺则降级」，绝不输出 NULL/空句）。
    """
    if not ts_code:
        return ''
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        rows = get_ecm_instance().get_relative_strength(ts_code=ts_code)
        if not rows:
            return ''
        asof = max((r.get('asof_date') or '') for r in rows if r.get('asof_date'))
        by_bench = {}
        for r in rows:
            if r.get('asof_date') == asof:
                by_bench.setdefault(r.get('benchmark'), r)

        def _phrase(benchmark, label):
            r = by_bench.get(benchmark)
            if not r:
                return ''
            parts = []
            for key, win in (('ex_ret_20d', '近20日'), ('ex_ret_60d', '近60日')):
                v = r.get(key)
                if v is None:
                    continue
                v = float(v) * 100
                verb = '跑赢' if v >= 0 else '跑输'
                parts.append(f'{win}{verb}{label}{abs(v):.1f}%')
            return '、'.join(parts)

        core = [p for p in (_phrase('000300.SH', '沪深300'), _phrase('000001.SH', '上证')) if p]
        if not core:
            return ''
        return '相对强弱：' + '；'.join(core)
    except Exception:
        return ''


def _valuation_sentence(dim_results: dict) -> str:
    """437-A D2：收益驱动（dim7 估值/财务）并入 summary 素材句。

    从 valuation 维 status_description 取估值水平/潜力/陷阱等 T 字段拼句；
    无 valuation 维 / 全字段空 → 返回 ''（437 缺则降级，不占位）。
    """
    val = (dim_results or {}).get('valuation') or {}
    sd = val.get('status_description', {}) or {}
    if not sd:
        return ''
    parts = []
    for f in ('valuation_level', 'potential_score', 'potential_strength', 'fina_health',
              'value_trap', 'growth_trap'):
        v = sd.get(f)
        if v is None or v == '' or v == 'none' or v == '无':
            continue
        s = _flatten_value(v)
        if s:
            parts.append(f'{_DIM8_FIELD_CN.get(f, f)}:{s}')
    if not parts:
        return ''
    return '；'.join(parts)



# ═══════════════════════════════════════════════════════════
# 第8维 引擎
# ═══════════════════════════════════════════════════════════

class Dim8SummaryEngine:
    """第8维 状态总结引擎 — 纯整理输出，读取 dim1-dim7 组装综合报告"""

    def evaluate(self, dims: dict, tags: dict, signals: dict | None = None,
                 lifecycle: dict | None = None) -> dict:
        """统一评估入口

        注意：dim_results 通过 lifecycle['dim_results'] 传入（StatusEngine 调用时注入）
        """
        dim_results = {}
        if lifecycle and isinstance(lifecycle, dict):
            dim_results = lifecycle.get('dim_results', {})
        elif signals and isinstance(signals, dict):
            dim_results = signals.get('dim_results', {})

        # 1. 八维红绿灯映射
        eight_dim_summary = _build_eight_dim_summary(dim_results)

        # 2. 共识率
        consensus_rate = _calc_consensus_rate(dim_results)

        # 3. 冲突检测
        conflicts = _detect_conflicts(dim_results)

        # 4. 状态条推导
        status_bar = _derive_status_bar(dim_results, consensus_rate, conflicts)
        status_bar_cn = STATUS_BAR_STATES.get(status_bar, status_bar)

        # 5. 综合文字
        text = _generate_text(dim_results, status_bar, consensus_rate, conflicts)

        # 6. status_description
        status_description = {
            'status_bar': status_bar_cn,
            'eight_dim_summary': eight_dim_summary,
            'consensus_rate': f"{consensus_rate:.0%}",
            'conflict_count': len(conflicts),
            'conflicts': [c['description'] for c in conflicts],
            'text': text,
            'plain': text,
        }

        # 420号增强6：数据完整度提示（audit.confidence 均值 <0.7 时警示）
        dim_names7 = ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']
        confidences = [_extract_dim_audit_confidence(dim_results, d) for d in dim_names7]
        data_confidence = sum(confidences) / len(confidences) if confidences else 0
        if 0 < data_confidence < 0.7:
            status_description['data_warning'] = f'数据完整度偏低（{data_confidence:.0%}），部分维度判断受限'

        # 7. judgment
        direction = 1 if consensus_rate >= 0.5 else (-1 if consensus_rate < 0.3 else 0)
        judgment = {
            'status_bar': status_bar,
            'status_bar_cn': status_bar_cn,
            'consensus_rate': consensus_rate,
            'direction': direction,
            'overall_light': 'green' if consensus_rate >= 0.6 else ('red' if consensus_rate < 0.3 else 'yellow'),
            'overall_direction': direction,
        }

        # 8. audit（纯整理的稽核：各维输出完整性）
        dim_names = ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']
        conditions = []
        for dim in dim_names:
            has_output = bool(dim_results.get(dim))
            conditions.append({
                'name': f'{dim}引擎输出',
                'satisfied': has_output,
                'actual': '有输出' if has_output else '无输出',
                'threshold': '维度引擎有输出',
            })
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        audit = {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0,
        }

        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
        }

    def build_seven_dim_report(self, dim_results: dict | None,
                                tags: dict | None = None,
                                ts_code: str | None = None) -> dict | None:
        """SIG 文字类输出整体归集器（436号 B1，dim8 按新共识承担）

        读取 dim_results（dim2-dim7 富数据）组装前端契约的七维现状描述 seven_dim_json：
          - 7 键：signal/structure/volume_price/fund_chip/emotion/risk/summary
          - 每段 {title, light(emoji), text, evidence, confidence, judgment, audit, plain}
          - 顶层无 light（各段自带）；summary 段含 dim8 综合状态条/共识/冲突
        ts_code：可选，供 462-3 相对强弱环境定位句（summary 前置，437-A D3）；
                 不传/无数据则跳过（437 缺则降级）。
        dim_results 为空/非 dict → 返回 None（由门禁/NULL 语义承接）。
        """
        if not dim_results or not isinstance(dim_results, dict):
            return None

        segments: dict = {}

        # 六维（signal→structure→volume_price→fund_chip→emotion→risk）
        for out_key, src_key, title in SEVEN_DIM_SPEC:
            seg = _segment_from_dim(dim_results, src_key, title)
            if seg is not None:
                segments[out_key] = seg

        # dim1 特例：dim_results 无 signal 维时回退 tags.right_side_confirm
        if 'signal' not in segments:
            fb = _dim1_fallback_segment(tags)
            if fb is not None:
                segments['signal'] = fb

        # summary 段：复用本引擎 evaluate 的综合组装（状态条+共识率+冲突+文字）
        # 兼容 dim_results 可能缺失 summary 维（dim8 产物本就在 JUD 路径才落），自行组装。
        try:
            self_ = self.__class__()
            summary_d8 = self_.evaluate(dims={}, tags=tags or {},
                                        lifecycle={'dim_results': dim_results})
            sd = summary_d8.get('status_description', {}) or {}
            jg = summary_d8.get('judgment', {}) or {}
            au = summary_d8.get('audit', {}) or {}
            text = sd.get('plain', '') or sd.get('text', '')
            segments['summary'] = {
                'title': SUMMARY_TITLE,
                'light': _LIGHT_EMOJI.get(jg.get('overall_light', 'yellow'), '🟡'),
                'text': text,
                # conflicts 已是字符串列表（evaluate 已转 description）；兼容 dict 兜底
                'evidence': [c['description'] if isinstance(c, dict) else str(c)
                             for c in sd.get('conflicts', [])][:3],
                'confidence': round(float(jg.get('consensus_rate', 0.5)), 2),
                'judgment': {'overall_light': jg.get('overall_light', 'yellow'),
                             'overall_direction': jg.get('overall_direction', 0),
                             'consensus_rate': jg.get('consensus_rate', 0.0)},
                'audit': {'conditions': au.get('conditions', [])[:8],
                          'satisfied_count': au.get('satisfied_count', 0),
                          'total_count': au.get('total_count', 0),
                          'confidence': au.get('confidence', 0)},
                'plain': text,
            }
        except Exception:
            # summary 组装失败：退化为最小段，保证门禁「必含 summary」不误拦
            segments['summary'] = {
                'title': SUMMARY_TITLE,
                'light': '🟡',
                'text': '状态总结：数据不足',
                'evidence': [],
                'confidence': 0.5,
                'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                             'consensus_rate': 0.5},
                'audit': {'conditions': [], 'satisfied_count': 0, 'total_count': 0,
                          'confidence': 0},
                'plain': '状态总结：数据不足',
            }

        # 462-3：环境定位——相对强弱句并入 summary 前置（437-A D3「第一层并入 summary」）。
        # 不传 ts_code / 无数据 → 跳过（437 缺则降级，不改前端契约键）。
        if ts_code and 'summary' in segments:
            rs = _relative_strength_sentence(ts_code)
            if rs:
                _seg = segments['summary']
                _seg['text'] = f'{rs}；{_seg.get("text", "")}'
                _seg['plain'] = f'{rs}；{_seg.get("plain", "")}' if _seg.get('plain') else rs

        # 437-A D2：收益驱动（dim7 估值/财务）并入 summary 尾置（素材不丢、不扩契约键）。
        # 无 valuation 维 / 全字段空 → 跳过（437 缺则降级）。
        # 注：_generate_text 的 dim_names 已含 valuation（plain 拼装会带"估值：…"），
        # 若已含则本句去重跳过，避免估值双段。
        if 'summary' in segments:
            vs = _valuation_sentence(dim_results)
            if vs:
                _seg = segments['summary']
                _cur = _seg.get('text', '') or ''
                if '估值：' not in _cur:
                    _seg['text'] = f'{_cur}；估值：{vs}'
                    _seg['plain'] = f'{_seg.get("plain", "")}；估值：{vs}' if _seg.get('plain') else f'估值：{vs}'

        return segments

    def get_data_dependencies(self) -> list:
        return [
            'dim1-dim7 引擎输出（通过 lifecycle["dim_results"] 传入）',
            'dims (StatusEngine) — 旧维度数据（兼容回退）',
        ]
