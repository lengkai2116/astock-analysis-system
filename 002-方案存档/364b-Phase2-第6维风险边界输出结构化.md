---
title: Phase 2 - 第6维风险边界输出结构化
type: 实施方案（子方案）
date: 2026-08-21
version: v1.0
parent: 364-七维现状描述系统实施方案（总纲）
status: 已废弃——369号维度引擎整合后，dim6_risk_engine已替代本方案Phase2功能
---

# 364b - Phase 2：第6维风险边界输出结构化（8h）

> 目标：将风险边界维度从简单的state/light二元输出升级为结构化的六维度输出（风险等级识别、风险因素列举、支撑阻力位、盈亏比R乘数分级、失效条件、波动率状态），含几何化指标和条件稽核。

---

## 一、当前代码状态

### 1.1 advice_builder._geometric() 当前实现（advice_builder.py:77-142）

```python
# 当前逻辑（逐行）：
# L77: def _geometric(df) -> dict:
# L89-92: K线不足时返回空结构
# L93-96: 取最近收盘价、60日高点、60日低点
# L98-101: 压力位 = min(hi60, ma60)（更贴近的阻力）
# L102-111: 支撑位 = max(ma20, lo20)（近端结构位）
# L113-115: 止损必须低于现价（H3教训）：近端位高于现价时回退60日低点
# L117-121: 止损距离上限15%：过远时压缩
# L122-124: 计算dist_sup/dist_res/rr
# L126-136: 信号天数：突破前60日高点后持续天数
# L137-142: 返回dict
```

**当前输出结构**：
```python
{
    'dist_to_support_pct': float | None,     # 距支撑位百分比
    'dist_to_resistance_pct': float | None,  # 距压力位百分比
    'risk_reward': float | None,             # 盈亏比
    'signal_days': int | None,              # 信号天数
    'support_price': float | None,          # 支撑位价格
    'resistance_price': float | None,       # 压力位价格
}
```

**问题**：
- 缺少R乘数分级判定（<1R/1-2R/2-3R/>3R）
- 缺少波动率状态（volatility_level + ATR + 历史分位）
- 缺少风险因素列表（从L0 soft_risks派生）
- 缺少失效条件结构化输出
- 缺少几何化描述文本（plain字段）

### 1.2 status_engine中risk维度的当前输出逻辑（status_engine.py:294-298）

```python
# L294-298: risk维度判定
rl = str(tags.get('risk_level', ''))
vl_lv = str(tags.get('volatility_level', ''))
risk_state = '高' if (rl == 'HIGH' or vl_lv == 'high') else ('低' if rl == 'LOW' else '中')
put('risk', risk_state, 0.6, [f'risk_level={rl}', f'volatility_level={vl_lv}'])
```

**问题**：
- risk维度仅输出state（低/中/高），无子维度拆解
- 无支撑阻力位、盈亏比、失效条件等结构化数据
- evidence仅有risk_level和volatility_level标签值

### 1.3 build_seven_dim_report()中risk段落（status_engine.py:645-649）

```python
# L645-649: risk段落
'seg': _seg('风险边界状态', dims.get('risk', {}).get('light', 'yellow'),
            f"风险等级：{dims.get('risk', {}).get('state', '中')}；"
            f"估值：{dims.get('valuation', {}).get('state', '合理')}；"
            f"财务：{dims.get('finance', {}).get('state', '关注')}",
            '错了在哪认错'),
```

**问题**：
- text仅为三行拼接，缺少支撑阻力位/盈亏比/失效条件
- plain为硬编码

### 1.4 _build_invalidation() 当前实现（advice_builder.py:433-461）

```python
# L433-461: 失效条件派生
# L441-442: 防守位跌破
# L443-444: 情绪退潮/高潮
# L445-446: 右侧否决
# L448-460: 标签库exit_conditions（330号改进1）
```

**输出**：`list[str]` 纯文本列表，无结构化分类

### 1.5 当前缺失的波动率数据

- `volatility_level`：pre_feat_cache标签，仅3态（high/medium/low）
- `atr_14d`：VolumePriceStrategy有ATR计算但未暴露到dim_states
- `atr_pct`：未计算
- `volatility_percentile`：完全缺失

---

## 二、修订内容

### 2.1 新建文件：risk_boundary_builder.py

位置：`backend/app/opportunity_atlas/risk_boundary_builder.py`

```python
"""risk_boundary_builder.py — 第6维风险边界输出结构化构建器

364b Phase 2：将风险边界维度拆解为6个子维度的结构化输出。
"""
from __future__ import annotations
import json
import logging
import numpy as np
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

    Args:
        dims: status_engine的dim_states（含risk/valuation/finance等）
        tags: pre_feat_cache扁平化标签
        geo: _geometric()输出（support/resistance/rr等）
        l0: L0风险分级输出（hard_veto/soft_risks等）
        df: 日线DataFrame（波动率计算用）
        snapshot_row: status_snapshot行（lifecycle等）

    Returns:
        {
            'status_description': {risk_level, risk_factors, support_resistance,
                                    rr_assessment, volatility, invalidation, plain},
            'judgment': {level, light},
            'audit': {conditions, satisfied_count, total_count, confidence}
        }
    """
    ...


def _assess_risk_level(dims: dict, l0: dict, tags: dict) -> dict:
    """风险等级识别（6维度加权）

    Returns:
        {'level': '低'|'中'|'高'|'极高', 'light': 'green'|'yellow'|'red',
         'sources': [...], 'detail': str}
    """
    ...


def _list_risk_factors(tags: dict, dims: dict, l0: dict) -> list[dict]:
    """风险因素列举（结构化）

    Returns:
        [{'category': '财务风险', 'factor': '财务异常', 'severity': '中',
          'satisfied': True, 'description': '...'}, ...]
    """
    ...


def _assess_rr(r_geo: dict, r_level: str) -> dict:
    """盈亏比分析 + R乘数分级

    R乘数分级标准（LLM Wiki《R乘数》）：
      <1R: 不值得交易
      1R-2R: 可考虑（需高胜率配合）
      2R-3R: 较好交易机会
      >3R: 优质交易机会

    Returns:
        {'rr_value': float, 'rr_level': str, 'rr_assessment': str, 'light': str}
    """
    ...


def _build_invalidation_list(
    support: float, tags: dict, dims: dict, snapshot_row: dict = None
) -> list[dict]:
    """失效条件结构化（替代原_build_invalidation的纯文本列表）

    Returns:
        [{'source': '防守位', 'condition': '收盘跌破28.2元', 'priority': 1},
         {'source': '情绪退潮', 'condition': '大盘进入退潮/高潮期', 'priority': 2},
         ...]
    """
    ...


def _calc_volatility(df=None, tags: dict = None) -> dict:
    """波动率状态计算

    1. volatility_level：从pre_feat_cache标签读取
    2. atr_14d：从df计算14日ATR
    3. atr_pct：ATR/现价
    4. volatility_percentile：20日波动率在120日历史中的分位（新建）

    Returns:
        {'level': str, 'atr_14d': float, 'atr_pct': float,
         'percentile': float, 'detail': str}
    """
    ...


def _calc_volatility_percentile(df) -> float:
    """波动率历史分位计算

    计算方法：
      1. 取最近120日收盘价
      2. 计算20日滚动波动率序列（std/close × √252）
      3. 取最新一个波动率值在120日序列中的分位排名
      4. 返回0-1分位值

    阈值映射：
      >0.7 → high（波动率处于历史高位）
      0.3-0.7 → medium
      <0.3 → low

    Returns: 0.0-1.0
    """
    ...


def _risk_boundary_plain(risk_level: str, factors: list, geo: dict,
                         rr: dict, vol: dict, invalidation: list) -> str:
    """第6维plain白话文本生成

    模板：风险等级{X}，{关键风险因素}；防守位{Y}元（距现价{Z}%），
          压力位{W}元（距现价{V}%），盈亏比{U}（{R评级}）；
          {失效条件摘要}
    """
    ...
```

### 2.2 _assess_risk_level() 具体逻辑

**修改文件**：`backend/app/opportunity_atlas/risk_boundary_builder.py`（新建）

**风险等级6维度加权判定**：

```python
def _assess_risk_level(dims: dict, l0: dict, tags: dict) -> dict:
    """风险等级识别 — 6风险源加权判定

    判定规则（来自360号§6.3 §1）：
      任一硬否决触发 → "极高"
      多个高风险源叠加 → "高"
      单个高风险源 → "中"
      无高风险源 → "低"
    """
    risk_sources = []
    high_count = 0

    # 1. 缠论风险
    rl = str(tags.get('risk_level', ''))
    if rl == 'HIGH':
        risk_sources.append({'name': '缠论风险', 'level': '高', 'detail': 'risk_level=HIGH'})
        high_count += 1
    else:
        risk_sources.append({'name': '缠论风险', 'level': '低', 'detail': f'risk_level={rl or "LOW"}'})

    # 2. 波动率风险
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
    lr = str(tags.get('low_liquidity', ''))
    if lr == 'true' or (tags.get('turnover_rate') and float(tags.get('turnover_rate', 999)) < 1.0):
        risk_sources.append({'name': '流动性风险', 'level': '高', 'detail': 'turnover_rate<1%'})
        high_count += 1
    else:
        risk_sources.append({'name': '流动性风险', 'level': '低', 'detail': '流动性充足'})

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
```

### 2.3 _list_risk_factors() 具体逻辑

**新增函数**：`risk_boundary_builder.py`

```python
def _list_risk_factors(tags: dict, dims: dict, l0: dict) -> list[dict]:
    """风险因素列举 — 基于PIERS五维度+系统标签

    来源：360号§6.3 §2 风险因素分类表
    """
    factors = []

    # 财务风险
    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        factors.append({'category': '财务风险', 'factor': '财务异常',
                        'severity': '高', 'satisfied': True,
                        'description': '存在财务异常风险（营收/现金流/ROE异常）'})
    elif fh == 'suspicious':
        factors.append({'category': '财务风险', 'factor': '财务关注',
                        'severity': '中', 'satisfied': True,
                        'description': '财务数据存在关注点'})

    # 事件风险
    ce = str(tags.get('catalyst_event', ''))
    event_map = {
        'regulatory': ('监管问题', '高', '存在监管立案/调查风险'),
        'delist_risk': ('退市风险', '极高', '存在退市风险（股价<1元或市值<3亿）'),
        'fraud_sign': ('造假信号', '极高', '存在财务造假信号'),
    }
    if ce in event_map:
        name, sev, desc = event_map[ce]
        factors.append({'category': '事件风险', 'factor': name,
                        'severity': sev, 'satisfied': True, 'description': desc})

    # 主力风险
    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        factors.append({'category': '主力风险', 'factor': '主力出货',
                        'severity': '中', 'satisfied': True,
                        'description': '主力处于出货阶段，抛压风险'})

    # 估值风险
    vl = str(tags.get('valuation_level', ''))
    if vl in ('high', 'extreme_high'):
        factors.append({'category': '估值风险', 'factor': '估值过高',
                        'severity': '中', 'satisfied': True,
                        'description': '估值偏高，安全边际不足'})

    # 流动性风险
    try:
        tr = float(tags.get('turnover_rate', 999))
        if tr < 1.0:
            factors.append({'category': '流动性风险', 'factor': '流动性不足',
                            'severity': '高', 'satisfied': True,
                            'description': f'流动性不足（换手率{tr:.1f}%），卖出困难'})
    except (TypeError, ValueError):
        pass

    # 获利盘风险
    try:
        pr = float(tags.get('profit_ratio', 0))
        if pr >= 0.8:
            factors.append({'category': '获利盘风险', 'factor': '获利盘过高',
                            'severity': '中', 'satisfied': True,
                            'description': f'获利盘比例过高（{pr:.0%}），获利回吐压力大'})
    except (TypeError, ValueError):
        pass

    # L0软风险补充
    for sr in l0.get('soft_risks', []):
        if sr == 'low_liquidity' and not any(f['factor'] == '流动性不足' for f in factors):
            factors.append({'category': '流动性风险', 'factor': '流动性不足',
                            'severity': '中', 'satisfied': True,
                            'description': '流动性不足（L0标记）'})

    # 无风险时标注
    if not factors:
        factors.append({'category': '综合', 'factor': '无显著风险',
                        'severity': '无', 'satisfied': True,
                        'description': '未检测到显著风险因素'})

    return factors
```

### 2.4 _assess_rr() R乘数分级

**新增函数**：`risk_boundary_builder.py`

```python
def _assess_rr(r_geo: dict, r_level: str) -> dict:
    """盈亏比分析 + R乘数分级

    R乘数 = 盈亏比（risk_reward）
    分级标准（LLM Wiki《R乘数》+《短线高手的交易语言》）：
      <1R  → "不值得交易"（止损>目标收益）
      1-2R → "可考虑"（需高胜率配合）
      2-3R → "较好交易机会"
      >3R  → "优质交易机会"

    止损铁律：任何止损大于1/2止盈的交易不可取 → R<2不值得做
    """
    rr = r_geo.get('risk_reward')
    if rr is None:
        return {'rr_value': None, 'rr_level': '未知', 'rr_assessment': '盈亏比数据不足', 'light': 'yellow'}

    if rr < 1.0:
        level = '不值得交易'
        assessment = f'盈亏比{rr:.2f}<1R，止损过宽，不值得交易'
        light = 'red'
    elif rr < 2.0:
        level = '可考虑'
        assessment = f'盈亏比{rr:.2f}（1R-2R），需高胜率配合'
        light = 'yellow'
    elif rr < 3.0:
        level = '较好'
        assessment = f'盈亏比{rr:.2f}（2R-3R），较好交易机会'
        light = 'green'
    else:
        level = '优质'
        assessment = f'盈亏比{rr:.2f}（>3R），优质交易机会'
        light = 'green'

    return {'rr_value': round(rr, 2), 'rr_level': level,
            'rr_assessment': assessment, 'light': light}
```

### 2.5 _build_invalidation_list() 结构化失效条件

**新增函数**：`risk_boundary_builder.py`

```python
def _build_invalidation_list(support, tags, dims, snapshot_row=None) -> list[dict]:
    """失效条件结构化 — 替代原advice_builder._build_invalidation的纯文本列表"""
    conditions = []

    # 优先级1：防守位跌破（最高优先）
    if support is not None:
        conditions.append({
            'source': '防守位',
            'condition': f'收盘跌破止损位{support}',
            'priority': 1,
            'check': f'close < {support}',
        })

    # 优先级2：情绪退潮
    sp = str(tags.get('sentiment_phase', ''))
    if sp in ('ebb', 'climax'):
        conditions.append({
            'source': '情绪退潮',
            'condition': '大盘进入退潮/高潮期，追涨风险大',
            'priority': 2,
            'check': f'sentiment_phase={sp}',
        })

    # 优先级3：右侧否决
    rsc = str(tags.get('right_side_confirm', ''))
    if rsc == '否决':
        conditions.append({
            'source': '右侧否决',
            'condition': '右侧确认已转为否决（卖出/背离/预跌信号）',
            'priority': 3,
            'check': 'right_side_confirm=否决',
        })

    # 优先级4：标签库退出条件（330号改进1）
    try:
        ec_raw = tags.get('exit_conditions')
        if ec_raw:
            ec = json.loads(ec_raw) if isinstance(ec_raw, str) else ec_raw
            if isinstance(ec, list):
                for item in ec:
                    desc = str(item.get('desc', '')).strip()
                    if desc and desc not in [c['condition'] for c in conditions]:
                        conditions.append({
                            'source': '标签退出条件',
                            'condition': desc,
                            'priority': 4,
                            'check': str(item.get('check', '')),
                        })
    except Exception:
        pass

    return conditions
```

### 2.6 _calc_volatility() 波动率状态 + 历史分位

**新增函数**：`risk_boundary_builder.py`

```python
def _calc_volatility(df=None, tags: dict = None) -> dict:
    """波动率状态计算（含历史分位）

    数据来源：
      1. volatility_level：pre_feat_cache标签（已有）
      2. atr_14d + atr_pct：从df计算（需新增）
      3. volatility_percentile：20日滚动波动率在120日中的分位（需新增）
    """
    tags = tags or {}
    vol_level = str(tags.get('volatility_level', ''))

    atr_14d = None
    atr_pct = None
    percentile = None

    if df is not None and not df.empty and len(df) >= 20:
        closes = df['close'].values
        highs = df['high'].values if 'high' in df.columns else closes
        lows = df['low'].values if 'low' in df.columns else closes

        # ATR(14)计算
        tr_list = []
        for i in range(1, min(15, len(closes))):
            tr = max(highs[-i] - lows[-i],
                     abs(highs[-i] - closes[-i-1]),
                     abs(lows[-i] - closes[-i-1]))
            tr_list.append(tr)
        atr_14d = round(np.mean(tr_list), 4) if tr_list else None

        price = float(closes[-1])
        if atr_14d and price > 0:
            atr_pct = round(atr_14d / price * 100, 2)

        # 波动率历史分位
        percentile = _calc_volatility_percentile(df)

    # 波动率等级回退：如果标签缺失，从percentile推导
    if not vol_level and percentile is not None:
        if percentile > 0.7:
            vol_level = 'high'
        elif percentile < 0.3:
            vol_level = 'low'
        else:
            vol_level = 'medium'

    level_cn = {'high': '高', 'medium': '中', 'low': '低'}.get(vol_level, '中')

    detail_parts = [f'波动率{level_cn}级别']
    if atr_14d:
        detail_parts.append(f'14日ATR {atr_14d:.4f}')
    if atr_pct:
        detail_parts.append(f'占现价{atr_pct:.1f}%')
    if percentile is not None:
        detail_parts.append(f'历史分位{percentile:.0%}')

    return {
        'level': vol_level or 'medium',
        'level_cn': level_cn,
        'atr_14d': atr_14d,
        'atr_pct': atr_pct,
        'percentile': percentile,
        'detail': '（' + '，'.join(detail_parts) + '）',
    }


def _calc_volatility_percentile(df) -> float:
    """波动率历史分位计算

    方法：
      1. 取最近120日收盘价序列
      2. 计算20日滚动年化波动率：rolling_std(close, 20) / rolling_mean(close, 20) × √252
      3. 取最后一个波动率值在序列中的分位排名

    Returns: 0.0-1.0分位值
    """
    if df is None or df.empty or len(df) < 40:
        return 0.5

    closes = df['close'].values
    if len(closes) < 40:
        return 0.5

    # 20日滚动波动率
    window = 20
    rolling_vol = []
    for i in range(window, len(closes)):
        w = closes[i-window:i]
        mean_w = np.mean(w)
        if mean_w > 0:
            vol = np.std(w) / mean_w * np.sqrt(252)
            rolling_vol.append(vol)

    if len(rolling_vol) < 2:
        return 0.5

    current_vol = rolling_vol[-1]
    count_below = sum(1 for v in rolling_vol if v < current_vol)
    percentile = count_below / len(rolling_vol)

    return round(percentile, 4)
```

### 2.7 risk_boundary_plain() 白话文本

**新增函数**：`risk_boundary_builder.py`

```python
def _risk_boundary_plain(risk_level, factors, geo, rr, vol, invalidation) -> str:
    """第6维plain白话文本生成"""
    parts = [f'风险等级{risk_level}']

    # 关键风险因素（仅列出非"无显著"的）
    significant = [f for f in factors if f['factor'] != '无显著风险']
    if significant:
        factor_names = '、'.join(f['factor'] for f in significant[:3])
        parts.append(f'存在{factor_names}')

    # 支撑阻力
    sup = geo.get('support_price')
    res = geo.get('resistance_price')
    dist_sup = geo.get('dist_to_support_pct')
    dist_res = geo.get('dist_to_resistance_pct')
    if sup and dist_sup:
        parts.append(f'防守位{sup}元（距现价{dist_sup:+.1f}%）')
    if res and dist_res:
        parts.append(f'压力位{res}元（距现价{dist_res:+.1f}%）')

    # 盈亏比
    if rr.get('rr_value'):
        parts.append(f'盈亏比{rr["rr_value"]:.2f}（{rr["rr_level"]}）')

    # 失效条件摘要
    if invalidation:
        parts.append(f'失效条件{len(invalidation)}条')

    return '，'.join(parts)
```

### 2.8 修改：build_seven_dim_report()中risk段落

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改行号**：645-649（替换risk段落构建）

```python
# 旧代码（L645-649）:
'seg': _seg('风险边界状态', dims.get('risk', {}).get('light', 'yellow'),
            f"风险等级：{dims.get('risk', {}).get('state', '中')}；"
            f"估值：{dims.get('valuation', {}).get('state', '合理')}；"
            f"财务：{dims.get('finance', {}).get('state', '关注')}",
            '错了在哪认错'),

# 新代码（364b Phase 2）:
'risk_boundary': _build_risk_segment(dims, tags, geo, l0, df, snapshot_row),
```

**新增辅助函数**（status_engine.py内部或risk_boundary_builder.py）：

```python
def _build_risk_segment(dims, tags, geo, l0, df, snapshot_row) -> dict:
    """第6维风险边界结构化段落"""
    from app.opportunity_atlas.risk_boundary_builder import (
        build_risk_boundary, _assess_risk_level, _list_risk_factors,
        _assess_rr, _build_invalidation_list, _calc_volatility, _risk_boundary_plain
    )

    risk_level_info = _assess_risk_level(dims, l0, tags)
    risk_factors = _list_risk_factors(tags, dims, l0)
    rr_info = _assess_rr(geo, risk_level_info['level'])
    invalidation = _build_invalidation_list(geo.get('support_price'), tags, dims, snapshot_row)
    volatility = _calc_volatility(df, tags)

    plain = _risk_boundary_plain(
        risk_level_info['level'], risk_factors, geo, rr_info, volatility, invalidation)

    # 条件稽核
    conditions = []
    for src in risk_level_info['sources']:
        conditions.append({
            'name': src['name'],
            'satisfied': src['level'] == '高',
            'actual': src['detail'],
            'threshold': '非高风险',
            'detail': f"{src['name']}={src['level']}"
        })
    if rr_info['rr_value'] is not None:
        conditions.append({
            'name': '盈亏比',
            'satisfied': rr_info['rr_value'] >= 2.0,
            'actual': f"{rr_info['rr_value']:.2f}",
            'threshold': '≥2.0',
            'detail': rr_info['rr_assessment']
        })
    satisfied = sum(1 for c in conditions if c['satisfied'])

    return {
        'title': '风险边界状态',
        'light': _l.get(risk_level_info['light'], '⚠️'),
        'judgment': risk_level_info['level'],
        'audit': {
            'conditions': conditions,
            'satisfied_count': satisfied,
            'total_count': len(conditions),
            'confidence': round(satisfied / max(len(conditions), 1), 2),
        },
        'text': (f"风险等级：{risk_level_info['level']}; "
                 f"防守位：{geo.get('support_price', 'N/A')}; "
                 f"盈亏比：{rr_info.get('rr_value', 'N/A')}({rr_info.get('rr_level', '')})"),
        'plain': plain,
        # 新增结构化数据（供前端渲染）
        'data': {
            'risk_level': risk_level_info,
            'risk_factors': risk_factors,
            'support_resistance': {
                'support_price': geo.get('support_price'),
                'resistance_price': geo.get('resistance_price'),
                'dist_to_support_pct': geo.get('dist_to_support_pct'),
                'dist_to_resistance_pct': geo.get('dist_to_resistance_pct'),
            },
            'rr': rr_info,
            'volatility': volatility,
            'invalidation': invalidation,
        },
    }
```

---

## 三、调用链变更

```
旧链路：
  status_engine._build_dimensions() → dims['risk'] = {state, light, confidence, evidence}
  status_engine.build_seven_dim_report() → risk段落（简单三行拼接）
  advice_builder._geometric() → geo dict（无R乘数分级/无波动率）

新链路：
  status_engine._build_dimensions() → dims['risk'] = {state, light, confidence, evidence}（保持不变）
  status_engine.build_seven_dim_report() → risk段落（调用risk_boundary_builder.build_risk_boundary()）
  risk_boundary_builder.build_risk_boundary() →
    _assess_risk_level(dims, l0, tags) → 6源风险等级
    _list_risk_factors(tags, dims, l0) → 风险因素列表
    _assess_rr(geo, r_level) → R乘数分级
    _build_invalidation_list(support, tags, dims) → 结构化失效条件
    _calc_volatility(df, tags) → 波动率状态+历史分位
    _risk_boundary_plain(...) → 动态白话
  advice_builder._geometric() → 保持不变（已被risk_boundary_builder引用）
```

**关键变更**：
- 新增 `risk_boundary_builder.py` 模块
- `build_seven_dim_report()` 中 risk 段落从简单拼接升级为结构化构建
- `_calc_volatility_percentile()` 为全新计算（之前完全缺失）

---

## 四、测试用例

### 4.1 单元测试

| 测试项 | 输入 | 预期输出 |
|--------|------|---------|
| R乘数分级 <1R | geo={risk_reward: 0.8} | rr_level='不值得交易', light='red' |
| R乘数分级 1-2R | geo={risk_reward: 1.5} | rr_level='可考虑', light='yellow' |
| R乘数分级 2-3R | geo={risk_reward: 2.5} | rr_level='较好', light='green' |
| R乘数分级 >3R | geo={risk_reward: 3.5} | rr_level='优质', light='green' |
| 风险等级-极高 | l0={hard_veto: True} | level='极高', light='red' |
| 风险等级-高 | tags含risk_level=HIGH+volatility_level=high | level='高', light='red' |
| 风险等级-低 | tags无高风险源 | level='低', light='green' |
| 风险因素-fina_fail | tags={fina_health: 'fail'} | factors含财务异常 |
| 波动率分位 | df含120日收盘价 | percentile为0-1浮点数 |
| 失效条件-多源 | tags含sentiment_phase='ebb'+right_side_confirm='否决' | invalidation含3条 |
| plain文本 | 正常输入 | 包含风险等级+防守位+盈亏比 |

### 4.2 集成测试

1. 运行全量pytest确认无回归
2. 调用`/api/v3/strategy-analyze`接口，验证返回的seven_dim_report.risk段落包含：
   - `audit`字段（conditions + satisfied_count）
   - `data.risk_level`（6源详细）
   - `data.rr`（R乘数分级）
   - `data.volatility`（含percentile）
   - `data.invalidation`（结构化失效条件列表）
3. 浏览器验证indicator-ide.html正确渲染风险6子维度

---

## 五、实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|:------:|
| 1 | 新建risk_boundary_builder.py骨架 | 0.5h |
| 2 | 实现_assess_risk_level()（6源风险等级） | 1h |
| 3 | 实现_list_risk_factors()（风险因素列举） | 1h |
| 4 | 实现_assess_rr()（R乘数分级） | 0.5h |
| 5 | 实现_build_invalidation_list()（结构化失效条件） | 1h |
| 6 | 实现_calc_volatility() + _calc_volatility_percentile() | 1.5h |
| 7 | 实现_risk_boundary_plain()（动态白话） | 0.5h |
| 8 | 修改build_seven_dim_report() risk段落 | 1h |
| 9 | 单元测试+集成测试 | 1h |
| **合计** | | **8h** |

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|---------|
| v1.0 | 2026-08-21 | 初版：6维度风险等级+R乘数分级+波动率历史分位+结构化失效条件+条件稽核 |
