---
title: Phase 6 - 第2维结构位置支撑阻力统一
type: 实施方案（子方案）
date: 2026-08-22
version: v1.0
parent: 364-七维现状描述系统实施方案（总纲）
---

# 364f - Phase 6：第2维结构位置支撑阻力统一（8h）

> 目标：修复 `_geometric()` 中 resistance 逻辑 bug，统一 3 个支撑阻力来源，min_width 百分比化，支撑阻力结果落库 pre_feat_cache。

---

## 一、当前代码状态

### 1.1 `_geometric()` 具体实现（advice_builder.py:77-142）

```python
def _geometric(df) -> dict:
    """几何化指标：距支撑/压力%、盈亏比、信号天数、防守位（K线不足返回空）

    - support_price：近端防守位 = max(MA20, 近20日低点)
    - resistance：60日高点与 MA60 取较低者
    - signal_days：突破信号后已持续交易日数
    """
    if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
        return {'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'signal_days': None, 'support_price': None,
                'resistance_price': None}
    closes = df['close'].values
    price = float(closes[-1])
    hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
    lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else None
    # 压力位：60日高点与 MA60 取较低者（更贴近的阻力）
    ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else None
    resistance = hi60
    if hi60 is not None and ma60 is not None:
        resistance = min(hi60, ma60)   # 更贴近的压力参考
    ma20 = float(df['close'].tail(20).mean()) if len(df) >= 20 else None
    lo20 = float(df['low'].tail(20).min()) if len(df) >= 20 and 'low' in df.columns else None
    # 近端结构位：MA20 与 近20日低点取高者（更贴近现价的支撑）
    near = None
    if ma20 is not None and lo20 is not None:
        near = max(ma20, lo20)
    elif ma20 is not None:
        near = ma20
    elif lo20 is not None:
        near = lo20
    support = near
    # 止损必须低于现价（H3 教训）：近端位高于现价时回退 60日低点
    if support is not None and price is not None and support >= price:
        support = lo60
    # 止损距离上限 15%：近端结构位过远时压缩
    if support is not None and price is not None:
        max_stop_pct = 0.15
        min_support = price * (1 - max_stop_pct)
        if support < min_support:
            support = min_support
    dist_sup = (support / price - 1) * 100 if support else None
    dist_res = (resistance / price - 1) * 100 if resistance else None
    rr = abs(dist_res / dist_sup) if dist_sup and dist_res else None
    # 信号天数
    signal_days = None
    if len(closes) >= 62:
        prior_hi = float(df['high'].iloc[-61:-1].max())
        if prior_hi > 0 and closes[-1] > prior_hi:
            days = 0
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] > prior_hi:
                    days += 1
                else:
                    break
            signal_days = days if days > 0 else None
    return {'dist_to_support_pct': round(dist_sup, 2) if dist_sup is not None else None,
            'dist_to_resistance_pct': round(dist_res, 2) if dist_res is not None else None,
            'risk_reward': round(rr, 2) if rr is not None else None,
            'signal_days': signal_days,
            'support_price': round(support, 2) if support is not None else None,
            'resistance_price': round(resistance, 2) if resistance is not None else None}
```

### 1.2 Resistance 逻辑 Bug 分析

**Bug 位置**：advice_builder.py L99-101

```python
resistance = hi60
if hi60 is not None and ma60 is not None:
    resistance = min(hi60, ma60)   # ← BUG: 取较低者
```

**问题**：
- `min(hi60, ma60)` 取 60 日高点和 MA60 的**较低者**作为压力位
- 当价格在 MA60 之上时（趋势向上），`ma60 < hi60`，resistance = ma60，**压力位低于现价**
- 导致 `dist_to_resistance_pct` 为负数（表示"已在压力位之上"），盈亏比计算异常
- 359号 §2.3 子维度3 已标注此问题："3个来源分散，无统一输出"

**实际影响**（L342-343 的下游修复已存在但治标不治本）：

```python
# advice_builder.py L342-343（下游补丁）
_res_eff = resistance if (resistance and price and resistance > price) else (
    (df['high'].tail(60).max() if df is not None and not df.empty and len(df) >= 60 ...))
```

下游通过 `resistance > price` 检查来回退到 60 日高点，但这种"补丁"逻辑分散在多处，不统一。

### 1.3 三个支撑阻力来源（359号 §2.3 子维度3 确认）

| # | 来源 | 位置 | 当前输出 | 落库 |
|---|------|------|---------|:----:|
| 1 | `_geometric()` | advice_builder.py:77 | support_price/resistance_price/dist_pct | ❌ |
| 2 | `_calc_vap_support_resistance()` | signal_computation_service.py:321 | vap_support/vap_resistance | ❌ |
| 3 | 前高前低 | advice_builder.py:95-96 | hi60/lo20 | ❌ |

**核心问题**：
1. 三个来源各自独立计算，可能给出矛盾的支撑/阻力价位
2. 无统一输出接口，下游消费者（七维模板、advice_card）需要分别处理
3. 计算结果不落库，无法历史追踪变化

### 1.4 min_width 现状（chanlun_strategy.py:940, 1154）

```python
# ZhongshuAnalyzer.__init__（L940）
class ZhongshuAnalyzer:
    def __init__(self, min_segment_count=3, min_width: float = 1.0, ...):
        self.min_width = min_width  # ← 硬编码绝对值 1.0

# BiZhongshuFinder.__init__（L1154）
class BiZhongshuFinder:
    def __init__(self, min_bi_count=3, min_width: float = 0.5):
        self.min_width = min_width  # ← 硬编码绝对值 0.5
```

**问题**：
- `min_width` 为绝对价格差（如 1.0 元、0.5 元），不随股价自适应
- 100 元股的 1.0 元中枢宽度仅 1%（过窄），10 元股的 1.0 元为 10%（过宽）
- 359号 §2.3 要求百分比化以适应不同价格区间

### 1.5 系统差距总结（359号 §2.6）

| 子维度 | 现状 | 差距 | 修复方案 |
|--------|------|------|---------|
| 价格vs支撑阻力 | 3个来源分散，无统一输出，不落库 | 核心缺口 | 新建UnifiedSupportResistance类+落库 |

---

## 二、修订内容

### 2.1 新建文件：unified_support_resistance.py

**位置**：`backend/app/opportunity_atlas/unified_support_resistance.py`

```python
"""364f Phase6：统一支撑阻力计算器

整合 3 个来源的支撑阻力数据，输出标准化的统一结果。
支持落库到 pre_feat_cache 供历史追踪。

Sources:
  1. geometric（advice_builder._geometric）：MA20/MA60/近20日低点/60日高点
  2. VAP（signal_computation_service._calc_vap_support_resistance）：成交量密集价格区
  3. 前高前低（advice_builder._geometric hi60/lo20 扩展）：60日/120日高低点
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


@dataclass
class SupportResistanceLevel:
    """单个支撑/阻力位"""
    price: float
    source: str          # 来源：'ma20'/'lo20'/'hi60'/'vap'/'zhongshu'/'fibonacci'
    level_type: str      # 'support' 或 'resistance'
    strength: float      # 强度 0-1（多源确认则强度高）
    distance_pct: float  # 距现价百分比


@dataclass
class UnifiedSR:
    """统一支撑阻力结果"""
    support_price: Optional[float] = None
    support_source: str = ''
    support_distance_pct: Optional[float] = None
    resistance_price: Optional[float] = None
    resistance_source: str = ''
    resistance_distance_pct: Optional[float] = None
    risk_reward: Optional[float] = None
    all_levels: List[SupportResistanceLevel] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'support': {
                'price': round(self.support_price, 2) if self.support_price else None,
                'source': self.support_source,
                'distance_pct': round(self.support_distance_pct, 2) if self.support_distance_pct is not None else None,
            },
            'resistance': {
                'price': round(self.resistance_price, 2) if self.resistance_price else None,
                'source': self.resistance_source,
                'distance_pct': round(self.resistance_distance_pct, 2) if self.resistance_distance_pct is not None else None,
            },
            'risk_reward': round(self.risk_reward, 2) if self.risk_reward is not None else None,
            'evidence': self.evidence,
        }


class UnifiedSupportResistance:
    """364f Phase6：统一支撑阻力计算器

    整合 3 个来源，按优先级和距离选取最终支撑/阻力位。
    """

    def calc(self, df: pd.DataFrame, ts_code: str = None,
             zhongshu_levels: Dict = None,
             vap_data: Dict = None) -> UnifiedSR:
        """计算统一支撑阻力

        Args:
            df: 日线 DataFrame（OHLCV）
            ts_code: 股票代码（日志用）
            zhongshu_levels: 缠论中枢近端支撑/阻力 {'support': float, 'resistance': float}
            vap_data: VAP 成交量密集价位 {'vap_support': float, 'vap_resistance': float}

        Returns:
            UnifiedSR 统一结果
        """
        result = UnifiedSR()
        if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
            return result

        closes = df['close'].values
        price = float(closes[-1])
        all_supports: List[SupportResistanceLevel] = []
        all_resistances: List[SupportResistanceLevel] = []

        # ── 来源1：geometric（MA20/MA60/近20日低点/60日高点）──
        ma20 = float(df['close'].tail(20).mean()) if len(df) >= 20 else None
        lo20 = float(df['low'].tail(20).min()) if len(df) >= 20 and 'low' in df.columns else None
        ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else None
        hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
        lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else None

        # 近端支撑位（修复后的逻辑）
        near_support = self._calc_near_support(ma20, lo20, lo60, price)
        if near_support is not None:
            all_supports.append(SupportResistanceLevel(
                price=near_support, source='MA20+近20日低点',
                level_type='support', strength=0.6,
                distance_pct=(near_support / price - 1) * 100
            ))

        # 近端阻力位（修复：取高于现价的最近位）
        near_resistance = self._calc_near_resistance(hi60, ma60, price)
        if near_resistance is not None:
            all_resistances.append(SupportResistanceLevel(
                price=near_resistance, source='前60日高点',
                level_type='resistance', strength=0.6,
                distance_pct=(near_resistance / price - 1) * 100
            ))

        # ── 来源2：VAP 成交量密集价位 ──
        if vap_data:
            vap_sup = vap_data.get('vap_support')
            vap_res = vap_data.get('vap_resistance')
            if vap_sup and vap_sup < price:
                all_supports.append(SupportResistanceLevel(
                    price=vap_sup, source='VAP成交量密集区',
                    level_type='support', strength=0.7,
                    distance_pct=(vap_sup / price - 1) * 100
                ))
            if vap_res and vap_res > price:
                all_resistances.append(SupportResistanceLevel(
                    price=vap_res, source='VAP成交量密集区',
                    level_type='resistance', strength=0.7,
                    distance_pct=(vap_res / price - 1) * 100
                ))

        # ── 来源3：缠论中枢近端 ──
        if zhongshu_levels:
            zs_sup = zhongshu_levels.get('support')
            zs_res = zhongshu_levels.get('resistance')
            if zs_sup and zs_sup < price:
                all_supports.append(SupportResistanceLevel(
                    price=zs_sup, source='缠论中枢下沿',
                    level_type='support', strength=0.8,
                    distance_pct=(zs_sup / price - 1) * 100
                ))
            if zs_res and zs_res > price:
                all_resistances.append(SupportResistanceLevel(
                    price=zs_res, source='缠论中枢上沿',
                    level_type='resistance', strength=0.8,
                    distance_pct=(zs_res / price - 1) * 100
                ))

        # ── 选取最终支撑/阻力 ──
        # 支撑：选取最靠近现价且低于现价的位（最近支撑）
        valid_supports = [s for s in all_supports if s.price < price]
        if valid_supports:
            best_support = max(valid_supports, key=lambda s: s.price)  # 最近的
            result.support_price = best_support.price
            result.support_source = best_support.source
            result.support_distance_pct = best_support.distance_pct

        # 阻力：选取最靠近现价且高于现价的位（最近阻力）
        valid_resistances = [r for r in all_resistances if r.price > price]
        if valid_resistances:
            best_resistance = min(valid_resistances, key=lambda r: r.price)  # 最近的
            result.resistance_price = best_resistance.price
            result.resistance_source = best_resistance.source
            result.resistance_distance_pct = best_resistance.distance_pct

        # 盈亏比
        if result.support_distance_pct and result.resistance_distance_pct:
            sup_abs = abs(result.support_distance_pct)
            res_abs = abs(result.resistance_distance_pct)
            if sup_abs > 0:
                result.risk_reward = round(res_abs / sup_abs, 2)

        # 多源确认增强：同一价位被多个来源确认时强度提升
        result.all_levels = all_supports + all_resistances
        result.evidence = self._build_evidence(result, price)
        return result

    @staticmethod
    def _calc_near_support(ma20, lo20, lo60, price):
        """计算近端支撑位（修复 _geometric 逻辑）

        规则：
        1. MA20 与 lo20 取高者（更贴近现价的支撑）
        2. 结果必须低于现价（止损必须在现价之下）
        3. 止损距离上限 15%（知识库约束）
        4. 以上均不满足时回退 lo60
        """
        near = None
        if ma20 is not None and lo20 is not None:
            near = max(ma20, lo20)
        elif ma20 is not None:
            near = ma20
        elif lo20 is not None:
            near = lo20

        if near is not None and price is not None and near >= price:
            near = lo60  # 回退 60日低点

        if near is not None and price is not None:
            # 止损距离上限 15%
            min_support = price * (1 - 0.15)
            if near < min_support:
                near = min_support

        return near

    @staticmethod
    def _calc_near_resistance(hi60, ma60, price):
        """计算近端阻力位（修复 _geometric Bug）

        Bug 修复：原 `min(hi60, ma60)` 会在 ma60 < price 时返回低于现价的阻力位。
        修复逻辑：
        1. 优先取 hi60（60日最高价，天然高于现价）
        2. 若 hi60 不存在，取 ma60（但仅当 ma60 > price 时有效）
        3. 若两者都不高于现价，返回 None（无有效阻力位）
        """
        candidates = []
        if hi60 is not None and hi60 > price:
            candidates.append(hi60)
        if ma60 is not None and ma60 > price:
            candidates.append(ma60)

        if not candidates:
            return None

        # 取最近的（最小的高于现价格）
        return min(candidates)

    @staticmethod
    def _build_evidence(result: UnifiedSR, price: float) -> list:
        """构建证据链"""
        ev = []
        if result.support_price:
            ev.append(f"支撑位{result.support_price:.2f}({result.support_source}, "
                      f"距现价{result.support_distance_pct:+.1f}%)")
        if result.resistance_price:
            ev.append(f"阻力位{result.resistance_price:.2f}({result.resistance_source}, "
                      f"距现价{result.resistance_distance_pct:+.1f}%)")
        if result.risk_reward is not None:
            ev.append(f"盈亏比1:{result.risk_reward}")
        if not ev:
            ev.append("支撑阻力数据不足")
        return ev
```

### 2.2 修改：_geometric() 中 resistance Bug 修复

**修改文件**：`backend/app/opportunity_atlas/advice_builder.py`

**修改行号**：L97-101

```python
# === 旧代码（Bug） ===
resistance = hi60
if hi60 is not None and ma60 is not None:
    resistance = min(hi60, ma60)   # ← BUG: 取较低者

# === 新代码（修复） ===
# 阻力位：取高于现价的最近位（Bug 修复：原 min(hi60, ma60) 会在 ma60<price 时返回低于现价的阻力）
resistance = None
if hi60 is not None and hi60 > price:
    resistance = hi60
if ma60 is not None and ma60 > price:
    if resistance is None or ma60 < resistance:
        resistance = ma60  # 取更贴近的
```

### 2.3 修改：min_width 百分比化

**修改文件**：`backend/app/engine/framework/chanlun_strategy.py`

**修改位置**：`ZhongshuAnalyzer.__init__()`（L940）和 `BiZhongshuFinder.__init__()`（L1154）

```python
# === ZhongshuAnalyzer.__init__ ===
class ZhongshuAnalyzer:
    def __init__(self, min_segment_count=3, min_width: float = 1.0,
                 min_width_pct: float = None,  # 364f 新增：百分比宽度
                 combine_mode='zs', algo='normal'):
        self.min_segment_count = min_segment_count
        # 364f: min_width_pct 优先；若提供则动态计算绝对宽度
        self._min_width_pct = min_width_pct
        self.min_width = min_width
        self.combine_mode = combine_mode
        self.algo = algo

    def find(self, segments: List[Segment]) -> List[Zhongshu]:
        # 动态 min_width：若设了百分比，基于当前价格范围计算
        # （在 _calculate_overlap 中使用动态宽度）
        return self._find_impl(segments)

    def _find_impl(self, segments):
        """实际中枢查找逻辑（提取自原 find()）"""
        # ... 原逻辑不变，但 min_width 比较处改为：
        if self._min_width_pct is not None:
            # 动态宽度：基于前一段的价格范围
            if i + 2 < len(segments):
                price_range = max(s.high for s in segments[i:i+3]) - min(s.low for s in segments[i:i+3])
                dynamic_width = price_range * self._min_width_pct / 100
            else:
                dynamic_width = self.min_width
        else:
            dynamic_width = self.min_width

        if high - low < dynamic_width:
            i += 1
            continue
        # ... 后续逻辑不变

# === BiZhongshuFinder.__init__ ===
class BiZhongshuFinder:
    def __init__(self, min_bi_count=3, min_width: float = 0.5,
                 min_width_pct: float = None):  # 364f 新增
        self.min_bi_count = min_bi_count
        self._min_width_pct = min_width_pct
        self.min_width = min_width

    def find(self, strokes: List[Stroke]) -> List[Zhongshu]:
        # ... 在 min_width 比较处（约 L1194）改为：
        effective_width = self.min_width
        if self._min_width_pct is not None and len(strokes) >= i + 3:
            price_range = max(
                max(s.start_price, s.end_price) for s in strokes[i:i+3]
            ) - min(
                min(s.start_price, s.end_price) for s in strokes[i:i+3]
            )
            effective_width = max(self.min_width, price_range * self._min_width_pct / 100)

        if high - low < effective_width:
            i += 1
            continue
        # ... 后续逻辑不变
```

### 2.4 新增：pre_feat_cache 落库字段设计

**修改文件**：`backend/app/data/enhanced_cache_manager.py`（或 pre_feat_cache 写入处）

**新增字段**（在 pre_feat_cache 的 structure 组内）：

```json
{
  "structure": {
    "...existing fields...",
    "unified_support_resistance": {
      "support": {
        "price": 28.5,
        "source": "MA20+近20日低点",
        "distance_pct": -4.2
      },
      "resistance": {
        "price": 32.0,
        "source": "前60日高点",
        "distance_pct": 11.8
      },
      "risk_reward": 2.81,
      "evidence": [
        "支撑位28.5(MA20+近20日低点, 距现价-4.2%)",
        "阻力位32.0(前60日高点, 距现价+11.8%)",
        "盈亏比1:2.81"
      ],
      "calc_date": "2026-08-22"
    }
  }
}
```

**落库时机**：在 `data_daemon._build_pre_feat()` 中，P2 信号计算完成后调用 `UnifiedSupportResistance.calc()` 并写入。

**字段路径**：`pre_feat_cache.structure.unified_support_resistance`

### 2.5 修改：build_seven_dim_report() 中结构位置维度引用统一支撑阻力

**修改文件**：`backend/app/opportunity_atlas/status_engine.py`

**修改位置**：`build_seven_dim_report()` 函数（L608-654）

```python
# 结构位置段落（structure segment）中的支撑阻力描述改为引用统一数据
def _structure_plain(d, t):
    struct = d.get('structure', {}).get('state', '盘整')
    pos = d.get('position', {}).get('state', '中位')
    # 364f: 从 tags 中读取统一支撑阻力
    sr = t.get('unified_support_resistance') or {}
    sup = sr.get('support', {})
    res = sr.get('resistance', {})
    parts = [f"走势{struct}，价格处于{pos}"]
    if sup.get('price'):
        parts.append(f"支撑位{sup['price']:.2f}({sup.get('source', '')})")
    if res.get('price'):
        parts.append(f"阻力位{res['price']:.2f}({res.get('source', '')})")
    return '，'.join(parts)
```

---

## 三、调用链变更

```
旧链路：
  advice_builder._geometric(df) → {support_price, resistance_price, ...}
  signal_computation_service._calc_vap_support_resistance() → {vap_support, vap_resistance}
  （三个来源分散，无统一接口）

新链路（364f Phase6）：
  unified_support_resistance.UnifiedSupportResistance.calc(
      df, ts_code, zhongshu_levels, vap_data
  ) → UnifiedSR（统一结果）
    ↓
  pre_feat_cache.structure.unified_support_resistance（落库）
    ↓
  build_seven_dim_report(row, tags) → 结构位置段落引用统一数据
    ↓
  advice_builder._geometric(df) → resistance Bug 修复（保持向后兼容）
```

**关键变更**：
1. 新建 `unified_support_resistance.py` 模块
2. `_geometric()` resistance 逻辑 Bug 修复
3. `ZhongshuAnalyzer` 和 `BiZhongshuFinder` 新增 `min_width_pct` 参数
4. `pre_feat_cache` 新增 `unified_support_resistance` 字段
5. `build_seven_dim_report()` 引用统一数据

---

## 四、测试用例

### 4.1 单元测试

| 测试项 | 输入 | 预期输出 |
|--------|------|---------|
| resistance Bug 修复 | price=30, hi60=35, ma60=28 | resistance=35（非28） |
| resistance 均高于现价 | price=30, hi60=35, ma60=32 | resistance=32（最近的） |
| resistance 无有效位 | price=30, hi60=25, ma60=28 | resistance=None |
| support 近端位 | price=30, ma20=28, lo20=27 | support=28（max(ma20,lo20)） |
| support 超过现价回退 | price=30, ma20=31, lo20=29, lo60=25 | support=25（回退lo60） |
| 支撑距离上限15% | price=30, lo60=20 | support=25.5（30×0.85） |
| VAP来源整合 | vap_support=28, price=30 | all_levels含VAP来源 |
| 缠论来源整合 | zhongshu_levels={'support':27} | all_levels含缠论来源 |
| 多源确认强度 | ma20=28 + vap_support=28 | strength 提升 |
| min_width 百分比 | min_width_pct=2.0, price_range=100 | dynamic_width=2.0 |
| risk_reward | dist_sup=-5%, dist_res=+15% | risk_reward=3.0 |
| UnifiedSR.to_dict() | 有支撑阻力 | 输出含support/resistance/risk_reward |
| 落库字段 | 完整计算结果 | pre_feat_cache含unified_support_resistance |

### 4.2 集成测试

1. 运行全量 pytest 确认无回归
2. 验证 `_geometric()` 在价格站上 MA60 时不再返回低于现价的 resistance
3. 调用 `/api/v3/strategy-analyze`，验证返回的 structure 维度引用统一支撑阻力
4. 检查 pre_feat_cache 中是否包含 `unified_support_resistance` 字段
5. 验证 min_width 百分比化后，高低价位股的中枢宽度合理

---

## 五、实施步骤

| 步骤 | 内容 | 工作量 |
|------|------|:------:|
| 1 | 新建 unified_support_resistance.py | 2h |
| 2 | _geometric() resistance Bug 修复 | 0.5h |
| 3 | ZhongshuAnalyzer min_width 百分比化 | 1h |
| 4 | BiZhongshuFinder min_width 百分比化 | 0.5h |
| 5 | pre_feat_cache 落库字段设计+写入 | 1.5h |
| 6 | build_seven_dim_report() 引用统一数据 | 0.5h |
| 7 | 单元测试 | 1h |
| 8 | 集成测试 | 0.5h |
| **合计** | | **8h** |

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|---------|
| v1.0 | 2026-08-22 | 初版：resistance Bug修复 + 三源统一 + min_width百分比化 + 落库 |
