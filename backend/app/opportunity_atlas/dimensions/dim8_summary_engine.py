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

import json
import logging
import re

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

# 段键契约（产出键 → 对应 dim_results 数据源键；summary 由 dim8 自行组装）
# 与前端 dimOrder/segOrder 对齐（不含 signal——2026-09-15 裁决：signal 由 JUD 单独
#   路径产出、前端 UI 组合，dim8 现状说明归集不再产出 signal 段；不含 valuation
#   ——436 D5：前端 dimOrder 无此键，不产出）
SEVEN_DIM_SPEC = [
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
    # 479号：dim_names 移除 'valuation'——收益驱动按 dim7 定稿 D2=A 统一并入 summary 尾置
    #   （build_seven_dim_report 的 _valuation_sentence），此处拼接会与尾置重复，且
    #   potential_breakdown 原始 JSON 会泄漏进综合文字
    dim_names = ['signal', 'structure', 'volume_price', 'chip_fund', 'emotion', 'risk']
    dim_cn = {'signal': '信号', 'structure': '结构', 'volume_price': '量价',
              'chip_fund': '资金', 'emotion': '情绪', 'risk': '风险'}
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
        # 479号 P14：数值型指标 dict（piers_leverage {'debt_to_assets','roce'}）渲染中文指标，
        #   避免兜底只取第一个非空子值丢 roce
        if {'debt_to_assets', 'roce'} <= set(v):
            parts = []
            dta = v.get('debt_to_assets')
            if dta is not None:
                parts.append(f'负债率{dta:.1f}%')
            roce = v.get('roce')
            if roce is not None:
                parts.append(f'ROCE {roce:.1f}%')
            if parts:
                return '、'.join(parts)
        # 买卖点 dict：{'type':'buy','point_type':'first_buy','price':2.98,'reason':'...'}
        # 479号 A2：补 reason（判定条件=因）——'一卖(1323.0)：上涨趋势背驰，中枢背驰'
        pt = v.get('point_type') or v.get('type')
        if pt:
            cn = _point_type_cn(pt)
            price = v.get('price')
            base = f'{cn}({price})' if price is not None else cn
            reason = v.get('reason')
            if reason:
                return f'{base}：{reason}'
            return base
        # 482-2：事件 dict（event_details 项，{'event_type','description','direction',
        #   'confidence','event_date'}）——优先 description（与 evidence 同口径），
        #   缺失则用事件类型中文映射兜底；避免兜底 for sub 取到裸 event_type 英文。
        if 'event_type' in v:
            _desc = v.get('description')
            if _desc:
                return str(_desc)
            _et = v.get('event_type')
            return _event_type_cn(str(_et)) if _et else ''
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


def _point_type_cn(pt: str) -> str:
    """买卖点类型 → 中文（含 465-1B 变体：盘整背驰 first_buy_p/first_sell_p、
    类型 a/b 变体 third_buy_a/third_buy_b/second_buy_b 等，统一归基础买卖点中文）"""
    if pt in _POINT_TYPE_CN:
        return _POINT_TYPE_CN[pt]
    base = re.sub(r'_(?:p|a|b)$', '', pt)
    return _POINT_TYPE_CN.get(base, pt)


# 482-2：事件类型枚举 → 中文事件名（源：event_monitor.py 检测器名全集）。
#   仅展示层使用（结构化 event_details/risk_factors 原值保留，439 边界）。
_EVENT_TYPE_CN: dict[str, str] = {
    'longhubang': '龙虎榜', 'holder_concentration': '股东集中', 'holder_reduce': '股东减持',
    'breakout': '突破', 'limit_move': '涨跌停', 'margin_risk': '融资风险',
    'concept_heat': '概念热度', 'regulatory': '监管', 'delist_risk': '退市风险',
    'st_warning': 'ST预警', 'goodwill_risk': '商誉风险', 'fraud_sign': '造假嫌疑',
    'pledge': '质押', 'underwater_ipo': '定增破发', 'buyback': '回购', 'incentive': '股权激励',
}
# 482-3：dim3 量价背离类型枚举 → 中文（展示串层；divergence_type 结构化原值保留）
_DIM3_DIVERGENCE_TYPE_CN: dict[str, str] = {
    'top': '顶背离', 'bottom': '底背离', 'none': '无',
}


def _event_type_cn(et: str) -> str:
    """事件类型 → 中文（未命中 / 已含中文 → 原样返回）"""
    return _EVENT_TYPE_CN.get(et, et)


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


def _compose_dim_subsections(src_key: str, sd: dict) -> list[dict] | None:
    """437-A D1：段内小节（subsections）——按 _DIM8_SUBSECTIONS 分组取字段非空值。

    返回 [{title, items: [「字段名:值」...]}], ...]；无小节配置/全空 → None。
    """
    groups = _DIM8_SUBSECTIONS.get(src_key)
    if not groups:
        return None
    out = []
    for title, fields in groups:
        items = []
        for f in fields:
            v = (sd or {}).get(f)
            if v is None or v == '' or v == 'none' or v == '无':
                continue
            # 479号 P12：risk_factors 剥离事件条目（主源 event_details）
            v = _strip_event_factors(src_key, f, v)
            if not v:
                continue
            # 482-1：套 _DIM8_E_FORMAT 数值模板（与 evidence 同形，防裸小数）。
            #   注意模板已内含字段名（'ATR占比{v:.2f}%'），故命中模板时不再加中文标签前缀。
            fmt = _DIM8_E_FORMAT.get(f)
            if fmt and not isinstance(v, (list, dict)):
                try:
                    val = fmt.format(v=v)
                    if val:
                        items.append(val)
                    continue
                except (TypeError, ValueError):
                    pass
            val = _flatten_value(v)
            if val:
                items.append(f'{_DIM8_FIELD_CN.get(f, f)}：{val}')
        if items:
            out.append({'title': title, 'items': items})
    return out or None


# ═══════════════════════════════════════════════════════════
# dim4 现状描述中文标注网关（464 中文名映射）
#
# 背景：dim4 status_description 部分取值带英文——指标缩写（ASR/CYQKL）、引擎名
#   （PhaseDetector）、拥挤度档位（MODERATE/HIGH_CROWDING）、资金价格背离状态
#   （divergence/aligned）。这些英文分两类：
#     - 结构化键（crowding level、fund_price_divergence_status 等）仍被
#       audit / JUD 消费，原值必须保留（439 SIG-JUD 边界）。
#     - 展示文案（dim8 text / evidence / subsections）是 dim8 唯一叙事出口
#       （436 共识：前端唯一直读 dim8），可中文化。
# 本网关只作用于 dim8 的 fund_chip 段展示输出，不动任何结构化键。
#
# 口径（用户拍板 2026-09-22）：
#   - 指标缩写保留 + 中文释义：ASR（活跃筹码比率）=42。
#   - 拥挤度档位中文：MODERATE→适中 / HIGH_CROWDING→高 / LOW_CROWDING→低。
#   - PhaseDetector 全中文化：阶段引擎分析 / 阶段引擎判定5日净流出。
#   - 背离状态 status：divergence→背离 / aligned→同向 / none→无。
# ═══════════════════════════════════════════════════════════
_INDICATOR_CN = {
    'ASR': '活跃筹码比率',
    'CYQKL': '筹码穿透力',
    'RPS': '相对强弱因子',
}
# 缠论方向等英文值 → 中文（chanlun_direction 等结构化值原样保留，仅展示中文化）
_ZONE_DIRECTION_CN = {
    'up': '上升', 'down': '下降', 'mixed': '中性',
}
_CROWDING_CN = {
    'MODERATE': '适中', 'MODERATE_CROWDING': '适中',
    'HIGH_CROWDING': '高', 'LOW_CROWDING': '低',
}
_DIVERGE_STATUS_CN = {
    'divergence': '背离', 'aligned': '同向', 'none': '无',
}
# 479号 P11：dim6 波动率档位值 → 中文（volatility_level low/medium/high；
#   结构化键原值保留，仅展示层替换）
_VOLATILITY_CN = {
    'low': '低', 'medium': '中', 'high': '高',
}

# ─────────────────────────────────────────────────────────────
# 480号 后续（dim5/dim7 中文网关全量扩展）：甲类+乙类全部 → 中文
#
# 464 网关（_to_display_text）已统一接入 emotion(段)/summary(尾置)，本扩展覆盖
# dim5/dim7 残余英文 token（用户拍板「甲类+乙类全部」）：
#   - 指标缩写：ERP/RSI/PE/PB/ROE/ROCE/PEG/composite；MA5/MA10/MA20（N日均线）
#   - 品牌名：BOCIASI（情绪周期）
#   - 阶段投票维度：chip/fund/stage/trend/ssrp/chan/asr（468-① phase_vote_detail）
#   - 来源标注：dim2/dim4（→ 第N维）
#   - 信号枚举：neutral/risk_warning/right_emerging（对齐 signal_analyzer 名）
# 仅作用于展示层 text/evidence/subsections（网关已统一应用），audit/judgment/
# status_description 结构化键原值不动（439 SIG-JUD 边界）。
# ─────────────────────────────────────────────────────────────

# 指标缩写 → 全中文（数值锚点处保留原语感，无歧义）
_METRIC_CN = {
    'ERP': '股权风险溢价',
    'RSI': '相对强弱指标',
    'ROE': '净资产收益率',
    'ROCE': '资本回报率',
    'PEG': '市盈增长比',
    'composite': '综合评分',
    'PIERS-E': '财务高杠杆',
}
# 均线 N日 → 中文（MA5/MA10/MA20，独立成词）
_MA_CN = {'MA5': '5日均线', 'MA10': '10日均线', 'MA20': '20日均线'}
# PE/PB 近5年分位 → 中文（只替换该固定词组，防 PE/PB 误伤别处）
_PE_PB_CN = {'PE近5年': '市盈率近5年', 'PB近5年': '市净率近5年'}
# BOCIASI 品牌 → 情绪周期（先修复合词组，再裸品牌名）
_BOCIASI_CN = {'BOCIASI四象限': '情绪四象限', 'BOCIASI快': '情绪周期快',
               'BOCIASI慢': '情绪周期慢', 'BOCIASI': '情绪周期'}
# 阶段投票维度（468-① phase_vote_detail：「投票:chip=建仓(0.80)、…」）→ 中文维度名
_VOTE_DIM_CN = {
    'chip': '筹码形态', 'fund': '资金流向', 'stage': '量价阶段', 'asr': '活跃浮筹',
    'trend': '趋势方向', 'ssrp': '主力成本', 'chan': '缠论买点',
}
# 来源标注 dimN → 第N维（potential_breakdown B 方案「（资金→dim4）」）
_DIM_SRC_RE = re.compile(r'(?<![A-Za-z0-9_])dim([234])(?![A-Za-z0-9_])')
# 信号枚举 → 中文（对齐 signal_analyzer.SIGNAL_ATTRIBUTES / STATUS_BAR_STATES 命名）
_SIGNAL_STATE_CN = {
    'neutral': '中性观望', 'risk_warning': '风险警示', 'right_emerging': '右侧初现',
    'right_confirmed': '右侧确认', 'left_probing': '左侧试探',
    'trend_running': '趋势运行中', 'consolidating': '盘整待变',
}
# 背驰 type 枚举 → 中文（dim4 signal reason 直读 active_signal JSON，'xx趋势背驰，trend类型'
#   reason 内 type 为英文；dim2 侧 479-A2 已有 _cn_reason 同语义映射，此处网关兜底覆盖
#   dim4/dim8 展示链，避免英文残留）
_DIVERGENCE_TYPE_CN = {
    'trend': '趋势背驰', 'consolidation': '盘整背驰', 'zhongshu': '中枢背驰',
}


def _to_display_text(s: str) -> str:
    """dim8 展示文案中文化（指标缩写+释义 / 引擎名 / 拥挤档位 / 背离状态 / 缠论方向
    + dim5/dim7 残余指标/BOCIASI/投票维度/来源标注/信号枚举）。

    仅做有确切映射的替换，无匹配子串原样保留，其余内容不受影响。
    结构化键原值（audit/judgment/status_description 的英文枚举）不进本层。
    """
    if not isinstance(s, str) or not s:
        return s
    t = s
    # 0. 480号：dim5/dim7 全量中文化（置于后续通用替换前，防与 ASR 等释义叠加误伤）
    # 0a. 均线 N日 → 中文（独立成词，防 'MA200' 等拼接误中）
    for ma, cn in _MA_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(ma)}(?![A-Za-z0-9_])', cn, t)
    # 0b. PE/PB 近5年分位词组 → 中文
    for en, cn in _PE_PB_CN.items():
        t = t.replace(en, cn)
    # 0c. 指标缩写/评分 → 全中文（独立成词）
    for en, cn in _METRIC_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(en)}(?![A-Za-z0-9_])', cn, t)
    # 0d. BOCIASI → 情绪周期（先复合，后裸名）
    for k, v in _BOCIASI_CN.items():
        t = t.replace(k, v)
    # 0e. 阶段投票维度名 → 中文（仅 '维度名=' 形式，防 'fund_flow' 等拼接键误中）
    t = re.sub(
        r'(?<![A-Za-z0-9_])(chip|fund|stage|asr|trend|ssrp|chan)=',
        lambda m: _VOTE_DIM_CN[m.group(1)] + '=',
        t,
    )
    # 0f. 来源标注 dimN → 第N维（potential_breakdown B 方案）
    t = _DIM_SRC_RE.sub(lambda m: f'第{m.group(1)}维', t)
    # 0g. 信号枚举 → 中文（summary「信号：neutral（…）」）
    for en, cn in _SIGNAL_STATE_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(en)}(?![A-Za-z0-9_])', cn, t)
    # 1. 拥挤度档位 → 中文（'拥挤度=MODERATE' / '拥挤度=HIGH_CROWDING' 等）
    for en, cn in _CROWDING_CN.items():
        t = t.replace(f'拥挤度={en}', f'拥挤度={cn}')
    # 2. 指标缩写补释义：ASR=42 → ASR（活跃筹码比率）=42；RPS=72.4 → RPS（相对强弱因子）=72.4
    #    （缩写在 '=' 或 ':' 后跟数字才替换，避免误伤字段名）
    for abbr, cn in _INDICATOR_CN.items():
        t = re.sub(rf'{re.escape(abbr)}(?==|[:：])', rf'{abbr}（{cn}）', t)
    # 3. 缠论方向值中文化（独立成词才替换，防 'down' 误中 'd_outflow' 等子串）
    for zone, cn in _ZONE_DIRECTION_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(zone)}(?![A-Za-z0-9_])', cn, t)
    # 3a. 背驰 type 枚举中文（'…，trend类型' → '…，趋势背驰'；仅 'xx类型' 形式，
    #     防 'trend' 单词在别处误中；对齐 dim2 479-A2 _cn_reason 语义）
    for en, cn in _DIVERGENCE_TYPE_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(en)}类型(?![A-Za-z0-9_])', cn, t)
    # 4. PhaseDetector 全中文化
    t = t.replace('PhaseDetector分析', '阶段引擎分析')
    t = re.sub(
        r'PhaseDetector资金流向=(5d_inflow|5d_outflow|mixed)',
        lambda m: '阶段引擎判定' + {'5d_inflow': '5日净流入',
                            '5d_outflow': '5日净流出', 'mixed': '中性'}[m.group(1)],
        t,
    )
    t = t.replace('PhaseDetector资金流向', '阶段引擎资金流向')
    # 5. 资金价格背离状态 → 中文（evidence 的 status 值）
    for en, cn in _DIVERGE_STATUS_CN.items():
        t = re.sub(rf'\b{re.escape(en)}\b', cn, t)
    # 6. 479号 P11：波动率档位值 → 中文（'波动率:low' → '波动率:低'；
    #    独立成词防误中 'low_level' 等拼接键）
    for en, cn in _VOLATILITY_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(en)}(?![A-Za-z0-9_])', cn, t)
    # 7. 482-2：事件枚举 → 中文事件名（仅命中事件类型全词；未命中保持原样）
    for en, cn in _EVENT_TYPE_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(en)}(?![A-Za-z0-9_])', cn, t)
    # 8. 482-3：dim3 背离类型（display 'bottom（置信…）' / 裸 'bottom'）→ 顶/底背离
    for en, cn in _DIM3_DIVERGENCE_TYPE_CN.items():
        t = re.sub(rf'(?<![A-Za-z0-9_]){re.escape(en)}(?![A-Za-z0-9_])', cn, t)
    # 9. 482-5：structure evidence 调试性标记清洗（仅展示层，结构化键不动）
    #   9a. 定理键前缀去重：'t1 未通过(0.00) T1 走势必完美…' → '未通过(0.00) T1 走势必完美…'
    #       （行首 tN 冗余前缀，同行稍后出现对应 TN 时移除）
    t = re.sub(r'^t(\d+) (?=[^\n]{0,60}?T\1 )', '', t)
    #   9b. 缠论笔类名 → 中文
    t = t.replace('Stroke(', '笔(')
    #   9c. 变异系数缩写补释义
    t = t.replace('(CV<', '（变异系数<')
    #   9d. 阶段编号残留 'P1-#8'（'关联P1-#8特征序列缺口处理' → '关联特征序列缺口处理'）
    t = t.replace('P1-#8', '')
    #   9e. 中文语境内的 'vs' → '相对'（如 '价格vs中枢'；仅 CJK 两侧命中，防误伤英文键）
    t = re.sub(r'(?<=[\u4e00-\u9fa5])vs(?=[\u4e00-\u9fa5])', '相对', t)
    #   9f. 走势类型标注 '（trend）' → '（趋势）'
    t = t.replace('（trend）', '（趋势）')
    # 10. 482-4 收尾：中文后的半角冒号 → 全角（覆盖引擎自产串，如 dim4 '投票:'、
    #     dim3 pattern 条件 '低点: …'；仅 CJK 紧跟半角冒号时替换，不影响时间/比值）
    t = re.sub(r'(?<=[\u4e00-\u9fa5]):', '：', t)
    return t


def _segment_from_dim(dim_results: dict, src_key: str, title: str) -> dict | None:
    """按前端契约把单个 dim_results 维整形为报告段；缺维返回 None

    437-A 字段级编排（2026-09-20 拍板后实施）：
      - text：按 _DIM8_T_SUBJECTS[src_key] 字段清单，从 status_description 取「字段名:值」子句
        （字段级「分析逻辑实例→话术」，464 §十二 原料定义）；无映射字段时回退 _brief_text。
      - evidence：按 _DIM8_E_FIELDS[src_key] 字段清单收集佐证 + audit.conditions 中
        satisfied 项（437 §一-5：现状=达成状态，由 audit 印证）。
      - subsections（D1）：fund_chip 段内分「筹码成本/资金博弈」两小节（前端可读该键渲染）。
      - 缺维（src_key 无输出）→ None（437-A D7：缺维不产段，仅 summary 恒在）。
    数据驱动：加字段 = 在 _DIM8_T_SUBJECTS/_DIM8_E_FIELDS/_DIM8_SUBSECTIONS 加一行，不动本函数。
    """
    seg = (dim_results or {}).get(src_key)
    if not isinstance(seg, dict) or not seg:
        return None
    jg = seg.get('judgment', {}) or {}
    sd = seg.get('status_description', {}) or {}
    au = seg.get('audit', {}) or {}
    overall = jg.get('overall_light', jg.get('light', 'yellow'))
    # 479号 479-5：段级 text 传入 au，升级「所以→因为→验证」因果链话术（段是 dim8 唯一叙事出口）。
    text = _compose_dim_text(src_key, jg, sd, au)
    evidence = _compose_dim_evidence(src_key, sd)
    # 437 §一-5：audit.conditions 中 satisfied 项作 evidence 底料（现状=达成状态印证）
    for c in (au.get('conditions') or []):
        if isinstance(c, dict) and c.get('satisfied'):
            name = c.get('name')
            if name and name not in evidence:
                evidence.append(name)
    subsections = _compose_dim_subsections(src_key, sd)
    # 464 中文标注网关：对各维展示输出统一中文化（结构化键/audit 原值不动）
    text = _to_display_text(text)
    evidence = [_to_display_text(e) for e in evidence]
    if subsections:
        for grp in subsections:
            grp['items'] = [_to_display_text(it) for it in grp.get('items', [])]
    return {
        'title': title,
        'light': _LIGHT_EMOJI.get(str(overall), '🟡'),
        'text': text,
        # 479号 P10：evidence 硬截断 5→16（dim6 定稿：5 条截断致「因」丢失；479-2 后
        #   11 定理逐条 + 背驰细节 + 基础字段总量 ~20 条，16 保核心"因"优先展示）
        'evidence': evidence[:16],
        'confidence': round(float(jg.get('continuous_value') or au.get('confidence') or 0.5), 2),
        'judgment': {
            'overall_light': jg.get('overall_light', 'yellow'),
            'overall_direction': jg.get('overall_direction', 0),
            'continuous_value': jg.get('continuous_value'),
        },
        # 479号 P9：audit.conditions 透传 actual/threshold（dim6 定稿：现被裁成
        #   name+satisfied，现状本体丢失；结构化键原值保留，不中文化——439 边界）
        'audit': {
            'conditions': [{'name': c.get('name'), 'satisfied': bool(c.get('satisfied')),
                            'actual': c.get('actual'), 'threshold': c.get('threshold')}
                           for c in (au.get('conditions') or []) if isinstance(c, dict)][:8],
            'satisfied_count': au.get('satisfied_count', 0),
            'total_count': au.get('total_count', 0),
            'confidence': au.get('confidence', 0),
        },
        # plain 键保留（前端 seven_dim 契约段结构含该字段），值与 text 同（各维 plain 已删除，
        # dim8 为唯一叙事口径，段内 plain 不再读各维引擎自产文字）
        'plain': text,
        # 437-A D1：fund_chip 段内小节（subsections），前端可读该键渲染小节标题
        **({'subsections': subsections} if subsections else {}),
    }


# ── 437-A 字段级编排映射表（2026-09-20 拍板；数据驱动，加字段=加行）──

# 各维 text 主述字段（T）：按序取 status_description 非空值拼「字段名:值」子句。
# 键名以《437-A字段级归集核对报告》3 处修正为准（dim4 direction→fund_flow、
# dim6 volatility_atr→atr_pct、dim2 优先 buy_sell_points_detail）。
# signal 已按 2026-09-15 裁决移出 dim8（由 JUD 单独产出），不在此表。
_DIM8_T_SUBJECTS: dict[str, list[str]] = {
    # 479号：删 chanlun_strength（dim2 定稿 §七①：结构健康度/评分归 JUD，dim8 不产句；
    #   健康度"因"= 11 定理明细，由补产出 A4（theorem_check.details）经 evidence 承载）
    'structure': ['chanlun_direction', 'stage_name', 'trend_basis',
                  'buy_sell_points_detail', 'multi_level_direction_text'],
    # 479号：删 health_score/pattern_score（dim3 定稿：评分归 JUD）、vol_ratio（去重并入
    #   volume_energy，引擎仍产供 JUD）；rps 由本层转表述（细项6：RPS=61.5（前 38% 分位））
    # 479号 A5：vp_state_label/vp_rule（量价状态机"因"，先因后果——定稿细项1）
    'volume_price': ['vp_state_label', 'vp_rule', 'vp_state', 'volume_energy', 'pattern', 'rps'],
    'chip_fund': ['phase', 'fund_flow', 'fund_price_divergence', 'cost_structure',
                  'crowding', 'signal', 'margin'],
    # D4 去重：emotion.stock 由 dim3 vp_state 派生，主源 dim3（437-A §三-1）→ 不在此表
    'emotion': ['market', 'sector', 'quadrant', 'temperature'],
    'risk': ['risk_level', 'support_price', 'resistance_price', 'rr_value', 'rr_level',
             'volatility_level', 'risk_factors'],
    # 479号：valuation 不产独立段（436 D5），本表仅供 _valuation_sentence（summary 尾置）
    #   消费；按 dim7 定稿：评分（potential_score/strength）仅 JUD、fina_health 去重归 dim6
    'valuation': ['valuation_level', 'pe_percentile', 'pb_percentile', 'fcf_yield',
                  'dividend_yield', 'revenue_growth', 'value_trap', 'growth_trap',
                  'potential_breakdown'],
}

# D1：fund_chip 段内分两小节（437-A D1 拍板 A=合一段内分两小节；段结构加 subsections 键）。
# 小节名 → 该小节字段（取 status_description 非空值）；text 主述字段仍由 _DIM8_T_SUBJECTS 平铺。
_DIM8_SUBSECTIONS: dict[str, list[tuple[str, list[str]]]] = {
    'chip_fund': [
        ('筹码成本', ['phase', 'cost_structure', 'crowding']),
        ('资金博弈', ['fund_flow', 'fund_price_divergence', 'signal', 'margin']),
    ],
    # 479号 P15：risk 段内分「价格位置 / 风险状态」两小节（dim6 定稿 §4.2，
    #   对齐 dim4 subsections 先例；dist_*/signal_days 等 E 字段随小节呈现）
    'risk': [
        ('价格位置', ['support_price', 'resistance_price', 'dist_to_support_pct',
                   'dist_to_resistance_pct', 'dist_to_prev_high_pct', 'signal_days',
                   'rr_value', 'rr_level', 'rr_assessment']),
        ('风险状态', ['risk_level', 'risk_detail', 'risk_factors', 'piers_leverage',
                   'volatility_level', 'atr_pct', 'volatility_percentile',
                   'liquidity_detail', 'event_details', 'invalidation']),
    ],
}

# 各维 evidence 佐证字段（E）：按序取 status_description 非空值入 evidence 列表。
# 对齐 437-A §三 跨维去重主源（dim3 主源个股情绪 → emotion 不再重复 stock 至 evidence 主位；
# dim4 主源资金流 → valuation 不重复 fund_flow；dim2↔dim6 支撑阻力同源 → risk 主源）。
_DIM8_E_FIELDS: dict[str, list[str]] = {
    # 479号：删 vs_chip（筹码主源 dim4，dim2 定稿 §三-1 不产话术）/vs_support_resistance
    #   （支撑阻力主源 dim6，dim2 仅交叉印证不重复产句）/chanlun_phase（保留键不产话术）
    #   /level_cross_score/ts_strength（归 JUD）；trend_structure_signal 条件采用——
    #   值='none' 时 _compose_dim_evidence 自动跳过，仅非 none 产句（dim2 定稿 §四）
    # 479号：structure E 字段序即 evidence 展示序——theorem_check_details（11 定理，健康度
    #   叙事主素材）优先于背驰细节，防 evidence 截断挤掉核心"因"
    'structure': ['vs_zhongshu', 'vs_ma', 'vs_indicator',
                  # 479号 A1/A3/A4：中枢区位比例/背驰检测条件/11定理明细（dim2 补产出透传）
                  'theorem_check_details', 'zhongshu_location_ratio',
                  'divergence', 'divergence_type', 'divergence_details',
                  'divergence_dual_confirmed',
                  'trend_structure_signal'],
    'volume_price': ['divergence', 'granville',
                     # 479号 A8：背离检测条件结构化键（定稿细项5；divergence 已含置信表述）
                     'divergence_type', 'divergence_confidence', 'divergence_macd_confirmed'],
    'chip_fund': ['retail_institution', 'fund_price_divergence_risk',
                  'fund_price_divergence_status'],
    'emotion': ['bociasi_quick', 'bociasi_slow'],
    # 479号 P13/P14：-event_summary（去重，事件佐证主源改 event_details）+event_details
    #   +piers_leverage +dist_to_prev_high_pct +liquidity_detail +signal_days
    #   （dim6 定稿 §4.3；event_details 为 dict-list、piers_leverage 为 dict，均新增渲染）
    'risk': ['atr_pct', 'volatility_percentile', 'dist_to_support_pct',
             'dist_to_resistance_pct', 'dist_to_prev_high_pct', 'rr_assessment',
             'liquidity_detail', 'invalidation', 'event_details', 'piers_leverage'],
    'valuation': ['pe_percentile', 'pb_percentile', 'fcf_yield', 'dividend_yield',
                  'revenue_growth', 'potential_breakdown'],
}

# evidence 数值字段表述模板（437 §七-6：数值转自然语言，不裸放）。{v} 为原值。
_DIM8_E_FORMAT: dict[str, str] = {
    'atr_pct': 'ATR占比{v:.2f}%',
    'volatility_percentile': '波动率历史分位{v:.0%}',
    'dist_to_support_pct': '距防守位{v:.1f}%',
    'dist_to_resistance_pct': '距压力位{v:.1f}%',
    'dist_to_prev_high_pct': '距前高{v:.1f}%',
    'rr_value': '盈亏比{v:.2f}',
    # 479号 A1：中枢区位比例（区间内 0~1、上方>1、下方<0）
    'zhongshu_location_ratio': '中枢区位比{v:.2f}',
}

# 各维 text 主述字段的「字段名」中文标签（供「字段名:值」子句）
_DIM8_FIELD_CN: dict[str, str] = {
    'chanlun_direction': '缠论方向', 'chanlun_strength': '结构强度', 'stage_name': '阶段',
    'trend_basis': '趋势依据', 'buy_sell_points_detail': '买卖点', 'multi_level_direction_text': '多级别',
    'vp_state': '量价状态', 'health_score': '健康度', 'volume_energy': '量能',
    'vol_ratio': '量比', 'pattern': '形态', 'pattern_score': '形态评分', 'rps': 'RPS',
    # 479号 A5：量价状态机"因"标签（先因后果）
    'vp_state_label': '量价状态机', 'vp_rule': '状态规则',
    'phase': '主力阶段', 'fund_flow': '资金流', 'fund_price_divergence': '资金价格背离',
    'cost_structure': '筹码结构', 'crowding': '拥挤度', 'signal': '筹码信号', 'margin': '融资',
    'market': '市场情绪', 'sector': '板块情绪', 'stock': '个股情绪', 'quadrant': '情绪象限',
    'temperature': '情绪温度',
    'risk_level': '风险等级', 'support_price': '防守位', 'resistance_price': '压力位',
    'rr_value': '盈亏比', 'rr_level': '盈亏比评级', 'volatility_level': '波动率',
    'risk_factors': '风险因素',
    # 479号：risk 两小节/P14 新键标签（dim6 定稿 §4.2/§4.3）
    'risk_detail': '风险明细', 'dist_to_support_pct': '距防守位', 'dist_to_resistance_pct': '距压力位',
    'dist_to_prev_high_pct': '距前高', 'signal_days': '站上60日线天数', 'rr_assessment': '盈亏比评估',
    'atr_pct': 'ATR占比', 'volatility_percentile': '波动率分位', 'liquidity_detail': '流动性',
    'event_details': '事件', 'piers_leverage': '杠杆/资本回报', 'invalidation': '失效条件',
    # 479号 A1/A3/A4：dim2 补产出透传字段标签
    'zhongshu_location_ratio': '中枢区位比', 'divergence_details': '背驰检测条件',
    'divergence_dual_confirmed': '背驰双确认', 'theorem_check_details': '11定理明细',
    'valuation_level': '估值水平', 'potential_score': '潜力评分', 'potential_strength': '潜力强度',
    'fina_health': '财务健康', 'value_trap': '估值陷阱', 'growth_trap': '成长陷阱',
    'pe_percentile': 'PE分位', 'pb_percentile': 'PB分位', 'fcf_yield': 'FCF收益率',
    'dividend_yield': '股息率', 'revenue_growth': '营收同比', 'potential_breakdown': '潜力六维',
}


def _compose_dim_text(src_key: str, jg: dict, sd: dict,
                      au: dict | None = None) -> str:
    """437-A 字段级 text 编排：按 _DIM8_T_SUBJECTS 从 status_description 取 T 字段拼子句。

    规则（对齐 437-A §一）：缺字段不占位（子句跳过）；数值字段转表述由各维引擎
    status_description 已自产文字承载（本层只拼装不重算）；无 T 字段产出时回退 _brief_text。

    479号 479-5（实例→话术收官）：段级调用传入 au 时，把纯字段子句升级为因果链话术——
      「所以（现状结论=字段话术）」→「因为（被满足的条件=audit.conditions 中 satisfied 项
       的 name，现状=达成状态由 audit 印证）」→「验证（条件稽核 N/M 动态读）」。
      summary 平铺（_generate_text）与 strategy_analyze 不传 au → 保持纯字段话术（不回归）。
    """
    fields = _DIM8_T_SUBJECTS.get(src_key, [])
    parts = []
    for f in fields:
        v = (sd or {}).get(f)
        if v is None or v == '' or v == 'none' or v == '无':
            continue
        # 479号 P12：risk_factors 呈现时剥离事件条目（dim6 定稿 3A：事件话术主源=event_details；
        #   risk_factors 在 T 表（text 主述），text 不重复展示事件）
        v = _strip_event_factors(src_key, f, v)
        if not v:
            continue
        # 479号：dim3 细项6 rps 转表述——"61.5/100" → "RPS=61.5（近20日涨幅全市场前38%分位）"
        #   （排名事实作现状；RPS>85 强势判定归 JUD，dim8 不产评分句）
        if src_key == 'volume_price' and f == 'rps' and isinstance(v, str):
            if '数据不足' in v or '无' in v:
                continue  # 437 缺则降级：数据缺失不产 rps 子句
            m = re.search(r'([\d.]+)/100', v)
            if m:
                try:
                    rps_num = float(m.group(1))
                    pct = max(1, min(99, int(round(100 - rps_num))))
                    parts.append(f'RPS={rps_num:.1f}（近20日涨幅全市场前{pct}%分位）')
                    continue
                except (TypeError, ValueError):
                    pass
        label = _DIM8_FIELD_CN.get(f, f)
        val = _flatten_value(v)
        if not val:
            continue
        # 引擎自产字段多为完整句子（如 '强流出（5d_outflow）'），直接拼接不加冒号
        # 482-4：字段名后统一全角冒号（与段级「所以：/因为：/验证：」一致）
        parts.append(f'{label}：{val}')
    if not parts:
        return _brief_text(src_key, jg, sd)
    body = '；'.join(parts)
    # 479号 479-5（实例→话术收官，B1）：段级调用传入 au 时升级因果链话术。
    # 纯展示/话术层——不动审计判定逻辑，只把"因"（satisfied 条件名）显性化于 text。
    if au is not None:
        return _narrative_so_so_yz(body, src_key, jg, sd, au)
    return body


def _narrative_so_so_yz(body: str, src_key: str, jg: dict, sd: dict,
                        au: dict) -> str:
    """479号 479-5：把段 text 升级为「所以 → 因为 → 验证」因果链话术。

    各维定稿话术模板统一口径（dim2-dim7 定稿 §话术模板 + dim6 §5.1）：
      【所以】{现状结论 = 字段话术 body}（主结论，客观陈述非判定）
      【因为】{被满足条件 = audit.conditions 中 satisfied 项 name}（现状=达成状态由 audit 印证；
             缺失/无满足项 → 该节省略，防空"因"占位）
      【验证】条件稽核 N/M（audit.satisfied_count/total_count 动态读，436 §5.5 audit 展示）
      —— 评分键（structure_health_score 等）已被 479-1 清理出 T 表，不产句；此处不改任何判定。
    """
    conds = (au.get('conditions') or []) if isinstance(au, dict) else []
    satisfied = [str(c.get('name')) for c in conds if isinstance(c, dict) and c.get('satisfied')
                 and c.get('name')]
    total = au.get('total_count')
    got = au.get('satisfied_count')
    chain = f'所以：{body}'
    if satisfied:
        chain += f'；因为：{"、".join(satisfied)}'
    if isinstance(total, int) and total > 0:
        got = got if isinstance(got, int) else len(satisfied)
        chain += f'；验证：条件稽核 {got}/{total}'
    return chain


def _strip_event_factors(src_key: str, f: str, v):
    """479号 P12：risk_factors 呈现时剥离事件条目（dim6 定稿 3A：事件话术主源=event_details，
    risk_factors 只保留 5 源因子，避免与 event_details 重复展示）。"""
    if src_key == 'risk' and f == 'risk_factors' and isinstance(v, list):
        return [x for x in v if not (isinstance(x, str) and ('事件风险' in x or x.startswith('事件')))]
    return v


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
        # 479号 P12：risk_factors 剥离事件条目（主源 event_details）
        v = _strip_event_factors(src_key, f, v)
        if not v:
            continue
        # 479号 P13/P14：event_details dict-list 渲染（事件话术主源）——
        #   '龙虎榜机构净买 12449 万（2026-06-30，置信 80%）'；非 dict 项走通用展开
        if src_key == 'risk' and f == 'event_details' and isinstance(v, list):
            for item in v:
                if not isinstance(item, dict):
                    s = _flatten_value(item)
                    if s and s not in ev:
                        ev.append(s)
                    continue
                desc = item.get('description') or item.get('event_type') or ''
                _date = item.get('event_date') or ''
                _conf = item.get('confidence')
                _conf_txt = f'，置信{_conf:.0%}' if isinstance(_conf, (int, float)) else ''
                s = f'{desc}（{_date}{_conf_txt}）' if _date else f'{desc}{_conf_txt}'
                if s and s not in ev:
                    ev.append(s)
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


def _market_state_sentence(dim_results: dict) -> str:
    """437-A D3：第一层环境定位——大盘状态句（市场广度/情绪温度）。

    数据源 dim1 data_context['market_stats']（daemon RAW 预计算，全市场共享）。
    无数据/异常返回 ''（437 标准「有数据则显、缺则降级」）。
    """
    try:
        sig = (dim_results or {}).get('signal') or {}
        dc = sig.get('data_context') or {}
        ms = dc.get('market_stats') or {}
        if not ms:
            return ''
        parts = []
        ma20 = ms.get('ma20_ratio')
        if isinstance(ma20, (int, float)):
            pct = ma20 * 100
            tone = '偏强' if pct >= 60 else ('中性' if pct >= 40 else '偏弱')
            parts.append(f'全市场MA20强势占比{pct:.0f}%（{tone}）')
        lim = ms.get('limit_up_count')
        if isinstance(lim, int) and lim > 0:
            parts.append(f'涨停{lim}家')
        sealing = ms.get('sealing_rate')
        if isinstance(sealing, (int, float)) and sealing > 0:
            parts.append(f'封板率{sealing * 100:.0f}%')
        if not parts:
            return ''
        return '大盘状态：' + '；'.join(parts)
    except Exception:
        return ''


def _sector_position_sentence(dim_results: dict, ts_code: str) -> str:
    """437-A D3：第一层环境定位——板块定位句（所属行业热度/排名）。

    数据源 dim1 data_context['sector_heat']（当日 109 行业）+ get_stock_industry。
    无行业映射 / 无热度 → ''（437 缺则降级，不产该段）。
    """
    if not ts_code:
        return ''
    try:
        from app.data import DataManager
        sig = (dim_results or {}).get('signal') or {}
        dc = sig.get('data_context') or {}
        sector_heat = dc.get('sector_heat') or {}
        if not sector_heat:
            return ''
        industry = DataManager().get_stock_industry(ts_code)
        if not industry:
            return ''
        info = sector_heat.get(industry)
        if not info or not isinstance(info, dict):
            return ''
        level = info.get('heat_level', '')
        if level in ('none', '', None):
            return ''
        rank = info.get('rank')
        level_cn = {'top_10': '主线热点', 'top_20': '较活跃', 'top_40': '中等'}.get(level, level)
        rank_txt = f'（行业排名第{rank}）' if isinstance(rank, (int, float)) else ''
        return f'板块定位：{industry}板块{level_cn}{rank_txt}'
    except Exception:
        return ''


def _index_trend_sentence(dim_results: dict) -> str:
    """481号 ①：第一层环境定位——大盘指数趋势句。

    读 BenchmarkService 沪深300/上证近 1/5/20/60 日指数 K 线，给出指数当下点位、
    当日涨跌、近期趋势（60 日涨跌 + 60 日线上下方）。独立查询，不依赖 daemon 内存缓存。
    无数据/异常返回 ''（437 标准「有数据则显、缺则降级」）。
    """
    try:
        from app.services.benchmark_service import BenchmarkService
        bs = BenchmarkService()
        parts = []
        for idx, label in (('000300.SH', '沪深300'), ('000001.SH', '上证')):
            try:
                df = bs.get_index_daily(idx)
            except Exception:
                continue
            if df is None or df.empty or 'close' not in df.columns:
                continue
            closes = df['close'].astype(float)
            last = float(closes.iloc[-1])
            pct_1d = 0.0
            if 'pct_chg' in df.columns:
                v = df.iloc[-1].get('pct_chg')
                if v is not None:
                    try:
                        pct_1d = float(v)
                    except (TypeError, ValueError):
                        pct_1d = 0.0
            piece = f'{label}{last:.0f}(当日{pct_1d:+.1f}%)'
            # 近20/60日涨跌幅 + 60日线上下方
            if len(closes) >= 61:
                ret20 = (last / float(closes.iloc[-21]) - 1) * 100
                ret60 = (last / float(closes.iloc[-61]) - 1) * 100
                ma60 = float(closes.iloc[-60:].mean())
                pos = '60日线上方' if last >= ma60 else '60日线下方'
                tone = '偏强' if ret60 >= 0 and last >= ma60 else ('偏弱' if ret60 <= -5 else '中性')
                piece += f'，近20日{ret20:+.1f}%/近60日{ret60:+.1f}%，{pos}（{tone}）'
            elif len(closes) >= 21:
                ret20 = (last / float(closes.iloc[-21]) - 1) * 100
                piece += f'，近20日{ret20:+.1f}%'
            parts.append(piece)
        if not parts:
            return ''
        return '大盘趋势：' + '；'.join(parts)
    except Exception:
        return ''


def _sector_full_sentence(dim_results: dict, ts_code: str) -> str:
    """481号 ②：第一层环境定位——行业完整情况句。

    复用 SectorAnalysisService.get_sector_context（已具备行业 1/5/20 日收益、排名、
    轮动状态、资金流向，仅 strategy_analyze 消费过）。此处接进 dim8 环境定位段。
    无行业映射 / 服务不可用 → ''（437 缺则降级）。
    """
    if not ts_code:
        return ''
    try:
        from app.services.sector_analysis_service import SectorAnalysisService
        sctx = SectorAnalysisService().get_sector_context(ts_code)
        if not sctx.get('available'):
            return ''
        parts = []
        name = sctx.get('sector_name', '')
        ret20 = sctx.get('sector_20d_return')
        if ret20 is not None:
            parts.append(f'近20日{ret20:+.2f}%')
        ret5 = sctx.get('sector_5d_return')
        if ret5 is not None:
            parts.append(f'近5日{ret5:+.2f}%')
        rotation = sctx.get('rotation_state')
        rot_cn = {'LEADING': '领涨', 'LAGGING': '落后', 'STRENGTHENING': '增强',
                  'WEAKENING': '转弱', 'NEUTRAL': '中性'}.get(rotation, rotation)
        if rot_cn:
            parts.append(f'轮动{rot_cn}')
        mfrank = sctx.get('sector_moneyflow_rank')
        if isinstance(mfrank, (int, float)) and mfrank > 0:
            parts.append(f'资金流向第{mfrank}名')
        mfnet = sctx.get('sector_moneyflow_net')
        # 仅当净流向非 0 才产（SectorAnalysisService 无资金数据时兜底返回 0，
        #   '净流入0.0亿' 属误导，437 缺则降级）
        if isinstance(mfnet, (int, float)) and mfnet != 0:
            verb = '净流入' if mfnet >= 0 else '净流出'
            parts.append(f'{verb}{abs(mfnet) / 1e4:.1f}亿')
        if not parts:
            return ''
        return f'行业：{name}（' + '、'.join(parts) + '）'
    except Exception:
        return ''


def _industry_position_sentence(ts_code: str) -> str:
    """481号 ③：第一层环境定位——个股行业位置句。

    读 industry_position_cache（daemon RAW-2C 预计算）：目标股近20日收益在其
    所属行业全部有效成分股中的排名/总数/百分位/五档。独立查询，不依赖 daemon
    内存缓存。无数据/异常 → ''（437「有数据则显、缺则降级」）。
    """
    if not ts_code:
        return ''
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        p = get_ecm_instance().get_industry_position(ts_code)
        if not p:
            return ''
        ind = p.get('industry')
        rank = p.get('rank_in_industry')
        total = p.get('total_in_industry')
        pct = p.get('percentile')
        if not ind or rank is None or not total or total < 2 or pct is None:
            return ''          # 单成分行业/缺基准 → 不产误导位次句
        pos_cn = {'top25%': '前列', '中上': '中上', '中下': '中下', 'bottom25%': '靠后'}.get(p.get('position'))
        piece = f'{ind}板块内近20日涨幅第{rank}/{total}'
        if pct is not None:
            piece += f'（前{max(1, int(round(pct * 100))):d}%）'
        if pos_cn:
            piece += f'，位置{pos_cn}'
        return f'个股行业位置：{piece}'
    except Exception:
        return ''


def _valuation_sentence(dim_results: dict) -> str:
    """479号：收益驱动（dim7 估值/财务）并入 summary 尾置句（437-A D2，dim7 定稿 §4.2）。

    按 dim7 定稿话术模板（因果链）：
      估值{水平}（主结论）→ PE/PB 近5年分位 + FCF/股息/营收（因）→ 陷阱现状句 →
      潜力六维明细（potential_breakdown 展示层解析 + B 方案标注来源）→ 验证（audit N/8 动态读）。
    评分键（potential_score/potential_strength）仅 JUD、fina_health 去重归 dim6——本句不再拼入
    （dim7 定稿 §二：评分归 JUD/§三：fina_health 去重）。
    无 valuation 维 / 全字段空 → ''（437 缺则降级，不占位）。
    """
    val = (dim_results or {}).get('valuation') or {}
    sd = val.get('status_description', {}) or {}
    if not sd:
        return ''
    parts = []

    def _get(k):
        v = sd.get(k)
        return None if (v is None or v == '' or v == 'none' or v == '无') else v

    # 【所以】估值水平（主结论，中文已自产含 composite）
    lvl = _get('valuation_level')
    if lvl is not None:
        parts.append(_flatten_value(lvl))
    # 【因为】PE/PB 近5年分位 + FCF/股息/营收（因透传）
    seg_factors = [s for s in (_get('pe_percentile'), _get('pb_percentile')) if s]
    if seg_factors:
        parts.append('、'.join(seg_factors))
    cash_factors = [s for s in (_get('fcf_yield'), _get('dividend_yield'), _get('revenue_growth')) if s]
    if cash_factors:
        parts.append('、'.join(cash_factors))
    # 【附加现状句】陷阱（条件输出）
    for t in (_get('value_trap'), _get('growth_trap')):
        if t:
            parts.append(t)
    # 【潜力因明细】potential_breakdown 六维（JSON 展示层解析 + B 方案来源标注）
    bd = _get('potential_breakdown')
    if bd is not None:
        six = _parse_potential_breakdown(bd)
        if six:
            parts.append('潜力六维：' + '；'.join(six))
    # 【验证】估值条件 N/8 满足（dim8 动态读 audit）
    au = val.get('audit', {}) or {}
    _sat, _tot = au.get('satisfied_count'), au.get('total_count')
    if _sat is not None and _tot:
        parts.append(f'估值条件 {_sat}/{_tot} 满足')
    if not parts:
        return ''
    return '；'.join(parts)


_POTENTIAL_DIM_CN = {
    'val': '估值分位', 'earn': 'ROE分位', 'sector': '板块', 'event': '事件',
    'fund': '资金', 'trend': '趋势',
}
# dim7 定稿 4B：潜力六维 B 方案标注来源（板块→第一层、资金→dim4、趋势→dim2/3）
_POTENTIAL_DIM_SRC = {
    'sector': '（板块→第一层）', 'fund': '（资金→dim4）', 'trend': '（趋势→dim2/3）',
}


def _parse_potential_breakdown(v) -> list:
    """dim7 定稿 §4.3：potential_breakdown JSON → 潜力六维明细句（B 方案标注来源）。

    status_description 中为 json.dumps 字符串（dim7_valuation_engine:1020）；
    dict 兜底兼容；解析失败/空 → []（437 缺则降级）。
    """
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return []
    if not isinstance(v, dict) or not v:
        return []
    out = []
    for k in ('val', 'earn', 'sector', 'event', 'fund', 'trend'):
        if k not in v or v[k] is None:
            continue
        val = v[k]
        try:
            val_txt = f'{val:.2f}' if isinstance(val, (int, float)) else str(val)
        except (TypeError, ValueError):
            val_txt = str(val)
        out.append(f"{_POTENTIAL_DIM_CN.get(k, k)} {val_txt}{_POTENTIAL_DIM_SRC.get(k, '')}")
    return out



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

        # 五维（structure→volume_price→fund_chip→emotion→risk；signal 已按 2026-09-15
        # 裁决移出 dim8，由 JUD 单独路径产出）
        for out_key, src_key, title in SEVEN_DIM_SPEC:
            seg = _segment_from_dim(dim_results, src_key, title)
            if seg is not None:
                segments[out_key] = seg

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
            # 464 中文标注网关：summary 走独立拼接通路（_generate_text 读原始 dim_results），
            # 需单独应用中文化，否则各段已中文而 summary 平铺仍残留原始英文
            text = _to_display_text(text)
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

        # 437-A D3：第一层环境定位并入 summary 前置。
        #   顺序：大盘趋势(①) → 大盘广度 → 板块定位 → 行业完整(②) → 个股行业位置(③) → 相对强弱。
        # 481号：新增 ①_index_trend_sentence（指数趋势）、②_sector_full_sentence（行业完整）、
        #   ③_industry_position_sentence（个股行业位置）。
        # 有数据则显、缺则降级（437 §七-2），不改前端契约键。
        if ts_code and 'summary' in segments:
            env_parts = []
            it = _index_trend_sentence(dim_results)
            if it:
                env_parts.append(it)
            ms = _market_state_sentence(dim_results)
            if ms:
                env_parts.append(ms)
            sp = _sector_position_sentence(dim_results, ts_code)
            if sp:
                env_parts.append(sp)
            sf = _sector_full_sentence(dim_results, ts_code)
            if sf:
                env_parts.append(sf)
            ip = _industry_position_sentence(ts_code)
            if ip:
                env_parts.append(ip)
            rs = _relative_strength_sentence(ts_code)
            if rs:
                env_parts.append(rs)
            if env_parts:
                _seg = segments['summary']
                # 482 追加：环境定位句在网关之后拼接，需补过网关（MA20→20日均线 等）
                _env = _to_display_text('；'.join(env_parts))
                _seg['text'] = f'{_env}；{_seg.get("text", "")}'
                _seg['plain'] = f'{_env}；{_seg.get("plain", "")}' if _seg.get('plain') else _env

        # 437-A D2：收益驱动（dim7 估值/财务）并入 summary 尾置（素材不丢、不扩契约键）。
        # 无 valuation 维 / 全字段空 → 跳过（437 缺则降级）。
        # 479号：_generate_text 的 dim_names 已移除 valuation（避免与尾置重复/JSON 泄漏），
        #   收益驱动句统一由 _valuation_sentence 尾置承载（dim7 定稿 D2=A）。
        if 'summary' in segments:
            vs = _valuation_sentence(dim_results)
            if vs:
                # 480号 后续：收益驱动句在尾置拼入前先过中文网关（此前尾置于网关后拼接，
                #   composite/PE/PB/ROE/ROCE/PEG/dim来源标注 的英文 token 残留，绕开 _to_display_text）
                vs = _to_display_text(vs)
                _seg = segments['summary']
                _cur = _seg.get('text', '') or ''
                _seg['text'] = f'{_cur}；估值：{vs}'
                _seg['plain'] = f'{_seg.get("plain", "")}；估值：{vs}' if _seg.get('plain') else f'估值：{vs}'

        return segments

    def get_data_dependencies(self) -> list:
        return [
            'dim1-dim7 引擎输出（通过 lifecycle["dim_results"] 传入）',
            'dims (StatusEngine) — 旧维度数据（兼容回退）',
        ]
