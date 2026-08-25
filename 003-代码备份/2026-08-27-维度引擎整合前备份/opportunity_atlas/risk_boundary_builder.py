"""risk_boundary_builder.py — 第6维风险边界输出结构化构建器

364b Phase 2：将风险边界维度拆解为6个子维度的结构化输出。
"""
from __future__ import annotations
import json
import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_risk_boundary(
    dims: dict,
    tags: dict,
    geo: dict,
    l0: dict,
    df=None,
    snapshot_row: dict = None,
) -> dict:
    """构建第6维风险边界结构化输出

    Returns:
        {
            'status_description': {risk_level, risk_factors, support_resistance,
                                    rr_assessment, volatility, invalidation, plain},
            'judgment': {level, light},
            'audit': {conditions, satisfied_count, total_count, confidence}
        }
    """
    risk_level_info = _assess_risk_level(dims, l0, tags)
    risk_factors = _list_risk_factors(tags, dims, l0)
    rr_info = _assess_rr(geo, risk_level_info['level'])
    vol_info = _calc_volatility(df, tags)
    invalidation = _build_invalidation_list(geo.get('support_price'), tags, dims, snapshot_row)

    plain = _risk_boundary_plain(
        risk_level_info['level'], risk_factors, geo, rr_info, vol_info, invalidation
    )

    status_description = {
        'risk_level': f"{risk_level_info['level']}（{risk_level_info['detail']}）",
        'risk_factors': [f"{f['category']}：{f['factor']}（{f['severity']}）" for f in risk_factors if f['satisfied']],
        'support_resistance': f"防守位{geo.get('support_price', '无')}元（距现价{geo.get('dist_to_support_pct', '无')}），压力位{geo.get('resistance_price', '无')}元（距现价{geo.get('dist_to_resistance_pct', '无')}）",
        'rr_assessment': rr_info['rr_assessment'],
        'volatility': f"波动率{vol_info['level']}（ATR={vol_info['atr_14d']:.2f}，历史分位{vol_info['percentile']:.0%}）" if vol_info['atr_14d'] else f"波动率{vol_info['level']}",
        'invalidation': [item['condition'] for item in invalidation],
        'plain': plain,
    }

    judgment = {'level': risk_level_info['level'], 'light': risk_level_info['light']}

    # 条件稽核
    audit_conditions = [
        {'name': '风险等级', 'satisfied': risk_level_info['level'] in ('低', '中'),
         'actual': risk_level_info['level'], 'threshold': '低或中（非高/极高）',
         'detail': risk_level_info['detail']},
        {'name': '盈亏比', 'satisfied': rr_info.get('rr_value', 0) >= 2.0 if rr_info.get('rr_value') else False,
         'actual': f"{rr_info.get('rr_value', '无')}" if rr_info.get('rr_value') else '数据不足',
         'threshold': '≥2R', 'detail': rr_info['rr_assessment']},
        {'name': '波动率', 'satisfied': vol_info['level'] != 'high' if vol_info['level'] else True,
         'actual': vol_info['level'] or '未知', 'threshold': '非high',
         'detail': f"波动率{vol_info['level']}"},
    ]
    satisfied_count = sum(1 for c in audit_conditions if c['satisfied'])

    return {
        'status_description': status_description,
        'judgment': judgment,
        'audit': {
            'conditions': audit_conditions,
            'satisfied_count': satisfied_count,
            'total_count': len(audit_conditions),
            'confidence': satisfied_count / len(audit_conditions) if audit_conditions else 0,
        },
    }


def _assess_risk_level(dims: dict, l0: dict, tags: dict) -> dict:
    """风险等级识别 — 以dim_states为主，tags为辅"""
    risk_sources = []
    high_count = 0

    # 以dim_states中的risk判定为主（status_engine的L1计算）
    dim_risk = str(dims.get('risk', {}).get('state', ''))
    dim_risk_light = str(dims.get('risk', {}).get('light', ''))
    if dim_risk == '高' or dim_risk_light == 'red':
        return {'level': '高', 'light': 'red', 'sources': [{'name': 'L1风险判定', 'level': '高',
                'detail': f'dim_states risk={dim_risk}'}], 'detail': f'L1判定风险=高'}

    # tags作为辅助验证
    rl = str(tags.get('risk_level', ''))
    if rl == 'HIGH':
        risk_sources.append({'name': '缠论风险', 'level': '高', 'detail': 'risk_level=HIGH'})
        high_count += 1
    else:
        risk_sources.append({'name': '缠论风险', 'level': '低', 'detail': f'risk_level={rl or "LOW"}'})

    vl = str(tags.get('volatility_level', ''))
    if vl == 'high':
        risk_sources.append({'name': '波动率风险', 'level': '高', 'detail': 'volatility_level=high'})
        high_count += 1
    else:
        risk_sources.append({'name': '波动率风险', 'level': '低', 'detail': f'volatility_level={vl or "medium"}'})

    # 3. 财务风险
    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        risk_sources.append({'name': '财务风险', 'level': '高', 'detail': 'fina_health=fail'})
        high_count += 1
    else:
        risk_sources.append({'name': '财务风险', 'level': '低', 'detail': f'fina_health={fh or "pass"}'})

    # 4. 事件风险
    ce = str(tags.get('catalyst_event', ''))
    event_risk = {'fraud_sign', 'regulatory', 'delist_risk'}
    if ce in event_risk:
        risk_sources.append({'name': '事件风险', 'level': '高', 'detail': f'catalyst_event={ce}'})
        high_count += 1
    else:
        risk_sources.append({'name': '事件风险', 'level': '低', 'detail': f'catalyst_event={ce or "none"}'})

    # 5. 主力风险
    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        risk_sources.append({'name': '主力风险', 'level': '高', 'detail': 'main_force_phase=distributing'})
        high_count += 1
    else:
        risk_sources.append({'name': '主力风险', 'level': '低', 'detail': f'main_force_phase={mfp or "unknown"}'})

    # 6. 流动性风险
    try:
        tr = float(tags.get('turnover_rate', 999))
        if tr < 1.0:
            risk_sources.append({'name': '流动性风险', 'level': '高', 'detail': f'turnover_rate={tr:.1f}%'})
            high_count += 1
        else:
            risk_sources.append({'name': '流动性风险', 'level': '低', 'detail': '流动性充足'})
    except (TypeError, ValueError):
        risk_sources.append({'name': '流动性风险', 'level': '低', 'detail': '数据不足'})

    # L0硬否决 → 极高
    if l0.get('hard_veto'):
        return {'level': '极高', 'light': 'red', 'sources': risk_sources,
                'detail': f"硬否决：{l0.get('hard_reason', '')}"}

    # 综合判定
    if high_count >= 2:
        level, light = '高', 'red'
    elif high_count == 1:
        level, light = '中', 'yellow'
    else:
        level, light = '低', 'green'

    return {'level': level, 'light': light, 'sources': risk_sources,
            'detail': f'{high_count}个高风险源叠加' if high_count else '无高风险源'}


def _list_risk_factors(tags: dict, dims: dict, l0: dict) -> list[dict]:
    """风险因素列举"""
    factors = []

    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        factors.append({'category': '财务风险', 'factor': '财务异常', 'severity': '高', 'satisfied': True,
                        'description': '存在财务异常风险'})
    elif fh == 'suspicious':
        factors.append({'category': '财务风险', 'factor': '财务关注', 'severity': '中', 'satisfied': True,
                        'description': '财务数据存在关注点'})

    ce = str(tags.get('catalyst_event', ''))
    event_map = {
        'regulatory': ('监管问题', '高', '存在监管立案/调查风险'),
        'delist_risk': ('退市风险', '极高', '存在退市风险'),
        'fraud_sign': ('造假信号', '极高', '存在财务造假信号'),
    }
    if ce in event_map:
        name, sev, desc = event_map[ce]
        factors.append({'category': '事件风险', 'factor': name, 'severity': sev, 'satisfied': True, 'description': desc})

    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        factors.append({'category': '主力风险', 'factor': '主力出货', 'severity': '中', 'satisfied': True,
                        'description': '主力处于出货阶段，抛压风险'})

    vl = str(tags.get('valuation_level', ''))
    if vl in ('high', 'extreme_high'):
        factors.append({'category': '估值风险', 'factor': '估值过高', 'severity': '中', 'satisfied': True,
                        'description': '估值偏高，安全边际不足'})

    try:
        tr = float(tags.get('turnover_rate', 999))
        if tr < 1.0:
            factors.append({'category': '流动性风险', 'factor': '流动性不足', 'severity': '高', 'satisfied': True,
                            'description': f'流动性不足（换手率{tr:.1f}%）'})
    except (TypeError, ValueError):
        pass

    try:
        pr = float(tags.get('profit_ratio', 0))
        if pr >= 0.8:
            factors.append({'category': '获利盘风险', 'factor': '获利盘过高', 'severity': '中', 'satisfied': True,
                            'description': f'获利盘比例过高（{pr:.0%}），获利回吐压力大'})
    except (TypeError, ValueError):
        pass

    for sr in l0.get('soft_risks', []):
        if sr == 'low_liquidity' and not any(f['factor'] == '流动性不足' for f in factors):
            factors.append({'category': '流动性风险', 'factor': '流动性不足', 'severity': '中', 'satisfied': True,
                            'description': '流动性不足（L0标记）'})

    if not factors:
        factors.append({'category': '综合', 'factor': '无显著风险', 'severity': '无', 'satisfied': True,
                        'description': '未检测到显著风险因素'})

    return factors


def _assess_rr(r_geo: dict, r_level: str) -> dict:
    """盈亏比分析 + R乘数分级"""
    rr = r_geo.get('risk_reward')
    if rr is None:
        return {'rr_value': None, 'rr_level': '未知', 'rr_assessment': '盈亏比数据不足', 'light': 'yellow'}

    if rr < 1.0:
        return {'rr_value': round(rr, 2), 'rr_level': '不值得交易',
                'rr_assessment': f'盈亏比{rr:.2f}<1R，止损过宽，不值得交易', 'light': 'red'}
    elif rr < 2.0:
        return {'rr_value': round(rr, 2), 'rr_level': '可考虑',
                'rr_assessment': f'盈亏比{rr:.2f}（1R-2R），需高胜率配合', 'light': 'yellow'}
    elif rr < 3.0:
        return {'rr_value': round(rr, 2), 'rr_level': '较好',
                'rr_assessment': f'盈亏比{rr:.2f}（2R-3R），较好交易机会', 'light': 'green'}
    else:
        return {'rr_value': round(rr, 2), 'rr_level': '优质',
                'rr_assessment': f'盈亏比{rr:.2f}（>3R），优质交易机会', 'light': 'green'}


def _build_invalidation_list(support, tags, dims, snapshot_row=None) -> list[dict]:
    """失效条件结构化"""
    conditions = []

    if support is not None:
        conditions.append({'source': '防守位', 'condition': f'收盘跌破止损位{support}', 'priority': 1})

    sp = str(tags.get('sentiment_phase', ''))
    if sp in ('ebb', 'climax'):
        conditions.append({'source': '情绪退潮', 'condition': '大盘进入退潮/高潮期，追涨风险大', 'priority': 2})

    rsc = str(tags.get('right_side_confirm', ''))
    if rsc == '否决':
        conditions.append({'source': '右侧否决', 'condition': '右侧确认已转为否决', 'priority': 3})

    try:
        ec_raw = tags.get('exit_conditions')
        if ec_raw:
            ec = json.loads(ec_raw) if isinstance(ec_raw, str) else ec_raw
            if isinstance(ec, list):
                for item in ec:
                    desc = str(item.get('desc', '')).strip()
                    if desc and desc not in [c['condition'] for c in conditions]:
                        conditions.append({'source': '标签退出条件', 'condition': desc, 'priority': 4})
    except Exception:
        pass

    return conditions


def _calc_volatility(df=None, tags: dict = None) -> dict:
    """波动率状态计算"""
    tags = tags or {}
    level = str(tags.get('volatility_level', 'medium'))
    atr_14d = 0.0
    atr_pct = 0.0
    percentile = 0.5

    if df is not None and not df.empty and len(df) >= 20:
        try:
            import pandas as pd
            close = df['close'].astype(float)
            high = df['high'].astype(float)
            low = df['low'].astype(float)
            tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr_14d = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else tr.mean()
            current_price = close.iloc[-1]
            atr_pct = (atr_14d / current_price * 100) if current_price > 0 else 0
            percentile = _calc_volatility_percentile(df)
        except Exception as e:
            logger.debug(f"波动率计算异常: {e}")

    detail_parts = [f"波动率等级={level}"]
    if atr_14d > 0:
        detail_parts.append(f"ATR(14)={atr_14d:.2f}")
    if atr_pct > 0:
        detail_parts.append(f"ATR%={atr_pct:.1f}%")
    detail_parts.append(f"历史分位={percentile:.0%}")

    return {'level': level, 'atr_14d': atr_14d, 'atr_pct': atr_pct,
            'percentile': percentile, 'detail': '，'.join(detail_parts)}


def _calc_volatility_percentile(df) -> float:
    """波动率历史分位计算"""
    try:
        import pandas as pd
        close = df['close'].astype(float)
        if len(close) < 20:
            return 0.5
        returns = close.pct_change().dropna()
        if len(returns) < 20:
            return 0.5
        vol_20d = returns.rolling(20).std() * math.sqrt(252)
        vol_20d = vol_20d.dropna()
        if len(vol_20d) < 2:
            return 0.5
        current_vol = vol_20d.iloc[-1]
        below = (vol_20d < current_vol).sum()
        percentile = below / len(vol_20d)
        return float(percentile)
    except Exception:
        return 0.5


def _risk_boundary_plain(risk_level, factors, geo, rr, vol, invalidation) -> str:
    """第6维plain白话文本生成（365号修订）

    358号要求：描述"错了在哪认错"的具体防守位和盈亏比。
    """
    parts = []

    # 风险等级概述
    level_cn = {'低': '低风险', '中': '中等风险', '高': '高风险'}.get(risk_level, f'{risk_level}风险')
    parts.append(f'{level_cn}')

    # 支撑位 + 距现价百分比（关键信息）
    support = geo.get('support_price')
    dist_sup = geo.get('dist_to_support_pct')
    if support:
        if dist_sup is not None:
            parts.append(f'防守位{support}元（距现价{dist_sup:+.1f}%）')
        else:
            parts.append(f'防守位{support}元')

    # 压力位 + 距现价百分比
    resistance = geo.get('resistance_price')
    dist_res = geo.get('dist_to_resistance_pct')
    if resistance:
        if dist_res is not None:
            parts.append(f'压力位{resistance}元（距现价{dist_res:+.1f}%）')
        else:
            parts.append(f'压力位{resistance}元')

    # 盈亏比 → 直接给出数字和评价
    rr_val = rr.get('rr_value')
    rr_level = rr.get('rr_level', '')
    if rr_val:
        if rr_val >= 3:
            parts.append(f'盈亏比{rr_val}（优质交易机会）')
        elif rr_val >= 2:
            parts.append(f'盈亏比{rr_val}（较好）')
        elif rr_val >= 1:
            parts.append(f'盈亏比{rr_val}（一般）')
        else:
            parts.append(f'盈亏比{rr_val}（不划算）')

    # 波动率中文
    vol_level = vol.get('level', '')
    vol_cn = {'low': '低波动', 'medium': '中等波动', 'high': '高波动'}.get(vol_level, vol_level)
    if vol_cn and vol_cn not in ('', '数据不足'):
        parts.append(f'{vol_cn}')

    # 高风险因子
    key_factors = [f['factor'] for f in factors if f.get('satisfied') and f.get('severity') in ('高', '极高')]
    if key_factors:
        parts.append(f'需关注：{"、".join(key_factors)}')

    # 失效条件
    if invalidation:
        parts.append(f'止损条件：{invalidation[0].get("condition", "")}')

    return '，'.join(parts) if parts else '风险数据不足'
