---
title: Phase 8 - 维度引擎整合
type: 实施方案（子方案）
date: 2026-08-21
version: v1.0
parent: 364-七维现状描述系统实施方案（总纲）
depends: Phase 1-7
---

# 364h - Phase 8：维度引擎整合（20h）

> 目标：将分散在30+文件中的计算逻辑整合为6个集中维度引擎，收敛冗余计算，统一输出格式。
> 详细化358号§十的整合方案。

---

## 一、现状问题与冗余清单

### 1.1 vol_ratio（量比）冗余计算——6处独立计算

| # | 文件 | 计算方式 | 均量基准 | 行号 |
|---|------|---------|---------|------|
| 1 | `data_daemon.py` | `vol / avg_vol_5d` | 5日均量 | L185-249 |
| 2 | `volume_price_strategy.py` | `volumes[-1] / vol_ma20` | 20日均量 | L3769 |
| 3 | `volume_price_strategy.py` | `volumes[-1] / vol_ma5` | 5日均量 | L3907 |
| 4 | `signal_computation_service.py` | `vol_ma5 / vol_ma20` | 5日/20日均量比 | L209 |
| 5 | `chip_indicators.py` | `current_vol / avg_vol_100` | 100日均量 | L511 |
| 6 | `phase_detector.py` | `latest_ma5 / latest_ma20` | 5日/20日均量比 | L451 |

**问题**：同一指标在6个文件中使用不同均量基准计算，导致不同模块对"放量"判定标准不一致。

### 1.2 risk_level（风险等级）冗余计算——10+处独立计算

| # | 文件 | 判定逻辑 |
|---|------|---------|
| 1 | `status_engine.py` | `rl == 'HIGH' or vl_lv == 'high'` → 高 |
| 2 | `advice_builder.py` | L0 gate风险系数推导 |
| 3 | `cross_validate.py` | `_evaluate_gate()` 风险门禁 |
| 4 | `potential_engine.py` | 风险评分影响信号强度 |
| 5 | `event_monitor.py` | 事件风险等级评估 |
| 6 | `condition_auditor.py` | RiskConditionAuditor稽核 |
| 7 | `signal_computation_service.py` | 信号风险过滤 |
| 8 | `chip_strategy_impl.py` | 筹码风险评估 |
| 9 | `phase_detector.py` | 阶段判定中的风险因子 |
| 10 | `volume_price_strategy.py` | 量价背离风险 |

### 1.3 支撑阻力（support_resistance）冗余——4个独立数据源

| # | 文件 | 数据来源 | 输出 |
|---|------|---------|------|
| 1 | `advice_builder.py:_geometric()` | 缠论中枢±调整 | support/resistance |
| 2 | `chanlun_strategy.py` | 中枢上沿/下沿 | zs_high/zs_low |
| 3 | `pre_feat_cache` | 标签库 `support_resistance` | JSON字符串 |
| 4 | `tag_extractor.py` | 多源聚合 | 结构化标签 |

### 1.4 ma_alignment（均线排列）冗余——3处独立计算

| # | 文件 | 计算方式 |
|---|------|---------|
| 1 | `volume_price_strategy.py` | MA5/MA10/MA20交叉判定 |
| 2 | `signal_computation_service.py` | MA5/MA20/MA60交叉判定 |
| 3 | `chanlun_strategy.py` | 趋势方向推导均线排列 |

### 1.5 price_position（价格位置）冗余——3处独立算法

| # | 文件 | 算法 |
|---|------|------|
| 1 | `status_engine.py` | 标签`price_position` + 中枢上沿覆盖 |
| 2 | `tag_extractor.py` | 百分位区间判定 |
| 3 | `advice_builder.py` | 几何化位置计算 |

---

## 二、整合原则

1. **每维度一个集中的维度引擎**：负责该维度的唯一计算入口、统一输出格式
2. **收敛冗余计算**：同一指标只在一处计算，其他模块引用计算结果
3. **消除粗启发式**：data_daemon中的粗启发式计算替换为维度引擎调用
4. **统一输出格式**：每个维度输出统一的双轨结构（status_description + judgment + audit）
5. **保留共用逻辑**：跨维度共用的逻辑（如支撑阻力）定义为共享服务
6. **分阶段实施**：从简单维度开始，按整合难度从低到高推进

---

## 三、目标架构

```
当前架构（散乱）：
  data_daemon.py → 各处分散计算 → tags → status_engine.py → dim_states
  问题：同一指标多处计算、口径不一致、输出格式不统一

目标架构（集中）：
  backend/app/opportunity_atlas/dimensions/
  ├── __init__.py                        → 维度引擎注册表
  ├── dim1_signal_engine.py              → 第1维 信号确认引擎
  ├── dim2_structure_engine.py           → 第2维 结构位置引擎
  ├── dim3_vp_engine.py                  → 第3维 量价健康引擎
  ├── dim4_chip_fund_engine.py           → 第4维 资金筹码引擎
  ├── dim5_emotion_engine.py             → 第5维 情绪环境引擎
  ├── dim6_risk_engine.py                → 第6维 风险边界引擎
  ├── shared_support_resistance.py       → 跨维度共用·支撑阻力服务
  └── shared_vol_ratio.py               → 跨维度共用·量比服务
```

---

## 四、共享服务设计

### 4.1 shared_support_resistance.py —— 支撑阻力统一服务

**设计目标**：将4个独立数据源收敛为1个统一服务，所有维度引擎通过此服务获取支撑/阻力位。

```python
"""
shared_support_resistance.py — 支撑阻力统一服务（364h Phase 8）
"""
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)


class SupportResistanceService:
    """跨维度共用的支撑阻力服务
    
    数据源优先级（从精确到兜底）：
    1. 缠论中枢上下沿（chanlun_strategy.status_recognition.support_resistance）
    2. advice_builder._geometric() 几何化计算
    3. pre_feat_cache 标签库 support_resistance
    4. MA60 作为最后兜底
    """
    
    def get_support_resistance(
        self, 
        ts_code: str, 
        tags: dict, 
        signals: dict,
        dm=None
    ) -> dict:
        """
        获取统一的支撑阻力位
        
        Args:
            ts_code: 股票代码
            tags: pre_feat_cache 扁平化标签
            signals: strategy_signal_detail 信号
            dm: DataManager 实例（可选）
            
        Returns:
            {
                'support': float,           # 支撑位
                'resistance': float,        # 阻力位
                'source': str,              # 数据来源标识
                'confidence': float,        # 置信度 0-1
                'zhongshu_high': float,     # 中枢上沿（可选）
                'zhongshu_low': float,      # 中枢下沿（可选）
            }
        """
        # 数据源1：缠论中枢（最精确）
        chan_sr = self._from_chanlun(signals)
        if chan_sr and chan_sr.get('support') and chan_sr.get('resistance'):
            return {**chan_sr, 'source': 'chanlun', 'confidence': 0.8}
        
        # 数据源2：几何化计算
        geo_sr = self._from_geometric(ts_code, dm)
        if geo_sr and geo_sr.get('support') and geo_sr.get('resistance'):
            return {**geo_sr, 'source': 'geometric', 'confidence': 0.7}
        
        # 数据源3：标签库
        tag_sr = self._from_tags(tags)
        if tag_sr and tag_sr.get('support') and tag_sr.get('resistance'):
            return {**tag_sr, 'source': 'tags', 'confidence': 0.6}
        
        # 数据源4：MA60兜底
        ma_sr = self._from_ma60(ts_code, dm)
        if ma_sr:
            return {**ma_sr, 'source': 'ma60_fallback', 'confidence': 0.4}
        
        return {'support': 0, 'resistance': 0, 'source': 'none', 'confidence': 0}
    
    def _from_chanlun(self, signals: dict) -> Optional[dict]:
        """从缠论信号提取支撑阻力"""
        chan = None
        for name in ('缠论走势分析',):
            if name in signals:
                chan = signals[name]
                break
        if not chan:
            return None
        sr = (chan.get('status_recognition') or {}).get('support_resistance', {})
        return {
            'support': float(sr.get('support', 0) or 0),
            'resistance': float(sr.get('resistance', 0) or 0),
            'zhongshu_high': float(sr.get('zhongshu_high', 0) or 0),
            'zhongshu_low': float(sr.get('zhongshu_low', 0) or 0),
        }
    
    def _from_geometric(self, ts_code: str, dm=None) -> Optional[dict]:
        """从 advice_builder._geometric() 计算"""
        try:
            if dm is None:
                from app.data import DataManager
                dm = DataManager()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty:
                return None
            from app.opportunity_atlas.advice_builder import _geometric
            geo = _geometric(df)
            return {
                'support': float(geo.get('support_price', 0) or 0),
                'resistance': float(geo.get('resistance_price', 0) or 0),
            }
        except Exception as e:
            logger.debug("geometric SR 失败 %s: %s", ts_code, e)
            return None
    
    def _from_tags(self, tags: dict) -> Optional[dict]:
        """从标签库提取"""
        try:
            raw = tags.get('support_resistance', '{}')
            sr = json.loads(raw) if isinstance(raw, str) else (raw or {})
            return {
                'support': float(sr.get('support', 0) or 0),
                'resistance': float(sr.get('resistance', 0) or 0),
            }
        except Exception:
            return None
    
    def _from_ma60(self, ts_code: str, dm=None) -> Optional[dict]:
        """MA60 兜底"""
        try:
            if dm is None:
                from app.data import DataManager
                dm = DataManager()
            df = dm.get_cached_daily_data(ts_code)
            if df is None or len(df) < 60:
                return None
            ma60 = float(df['close'].tail(60).mean())
            return {'support': ma60 * 0.95, 'resistance': ma60 * 1.05}
        except Exception:
            return None


# 全局单例
_support_resistance_service = None

def get_support_resistance_service() -> SupportResistanceService:
    global _support_resistance_service
    if _support_resistance_service is None:
        _support_resistance_service = SupportResistanceService()
    return _support_resistance_service
```

### 4.2 shared_vol_ratio.py —— 量比统一服务

**设计目标**：将6处独立量比计算收敛为1个统一服务，统一使用5日均量基准。

```python
"""
shared_vol_ratio.py — 量比统一服务（364h Phase 8）
"""
from typing import Optional
import logging
import numpy as np

logger = logging.getLogger(__name__)

# 统一均量基准
VOL_RATIO_BASELINE = 5  # 5日均量（标准量比定义）


class VolumeRatioService:
    """跨维度共用的量比服务
    
    统一量比定义：当日成交量 / 过去N日平均成交量
    
    不同用途的量比：
    - vol_ratio_standard: 当日vol / 5日均量（标准量比）
    - vol_ratio_short: 5日均量 / 20日均量（短期量能趋势）
    - vol_ratio_long: 5日均量 / 100日均量（长期量能趋势）
    """
    
    def compute(
        self, 
        ts_code: str, 
        dm=None,
        daily_basic: Optional[dict] = None
    ) -> dict:
        """
        计算统一量比指标
        
        Args:
            ts_code: 股票代码
            dm: DataManager 实例
            daily_basic: daily_basic_cache 数据（可选，避免重复查询）
            
        Returns:
            {
                'vol_ratio': float,          # 标准量比（5日基准）
                'vol_ratio_short': float,    # 短期趋势（5日/20日）
                'vol_ratio_long': float,     # 长期趋势（5日/100日）
                'volume_status': str,        # 量能状态标签
                'volume_energy': str,        # 量能强度描述
                'source': str,               # 数据来源
            }
        """
        try:
            if dm is None:
                from app.data import DataManager
                dm = DataManager()
            
            df = dm.get_cached_daily_data(ts_code)
            if df is None or df.empty or len(df) < 20:
                return self._empty(ts_code)
            
            volumes = df['vol'].astype(float).values
            closes = df['close'].astype(float).values
            
            # 标准量比：当日 / 5日均量
            current_vol = volumes[-1]
            avg_vol_5 = np.mean(volumes[-6:-1]) if len(volumes) >= 6 else np.mean(volumes[:-1])
            vol_ratio = current_vol / max(avg_vol_5, 1e-9)
            
            # 短期趋势：5日均量 / 20日均量
            avg_vol_20 = np.mean(volumes[-21:-1]) if len(volumes) >= 21 else np.mean(volumes[:-1])
            vol_ratio_short = avg_vol_5 / max(avg_vol_20, 1e-9)
            
            # 长期趋势：5日均量 / 100日均量
            avg_vol_100 = np.mean(volumes[-101:-1]) if len(volumes) >= 101 else np.mean(volumes[:-1])
            vol_ratio_long = avg_vol_5 / max(avg_vol_100, 1e-9)
            
            # 量能状态标签
            volume_status = self._classify_status(vol_ratio)
            volume_energy = self._classify_energy(vol_ratio, vol_ratio_short)
            
            return {
                'vol_ratio': round(vol_ratio, 2),
                'vol_ratio_short': round(vol_ratio_short, 2),
                'vol_ratio_long': round(vol_ratio_long, 2),
                'volume_status': volume_status,
                'volume_energy': volume_energy,
                'source': 'computed',
            }
        except Exception as e:
            logger.debug("vol_ratio 计算失败 %s: %s", ts_code, e)
            return self._empty(ts_code)
    
    @staticmethod
    def _classify_status(vol_ratio: float) -> str:
        """量能状态标签"""
        if vol_ratio >= 3.0:
            return '极端放量'
        elif vol_ratio >= 2.0:
            return '明显放量'
        elif vol_ratio >= 1.5:
            return '温和放量'
        elif vol_ratio >= 1.0:
            return '量能正常'
        elif vol_ratio >= 0.7:
            return '量能萎缩'
        else:
            return '极度萎缩'
    
    @staticmethod
    def _classify_energy(vol_ratio: float, short_trend: float) -> str:
        """量能强度描述"""
        if vol_ratio >= 2.0 and short_trend > 1.2:
            return '放量加速（短+长双升）'
        elif vol_ratio >= 1.5:
            return '放量中（单日为主）'
        elif vol_ratio < 0.7 and short_trend < 0.8:
            return '持续缩量（短+长双降）'
        elif vol_ratio < 0.7:
            return '缩量（可能是洗盘）'
        else:
            return '量能平稳'
    
    @staticmethod
    def _empty(ts_code: str) -> dict:
        return {
            'vol_ratio': 0, 'vol_ratio_short': 0, 'vol_ratio_long': 0,
            'volume_status': '未知', 'volume_energy': '未知', 'source': 'insufficient_data'
        }


# 全局单例
_volume_ratio_service = None

def get_volume_ratio_service() -> VolumeRatioService:
    global _volume_ratio_service
    if _volume_ratio_service is None:
        _volume_ratio_service = VolumeRatioService()
    return _volume_ratio_service
```

---

## 五、6个维度引擎接口设计

### 5.1 统一输出结构（所有引擎遵循）

```python
# 每个维度引擎的输出必须包含以下结构
DimensionOutput = {
    # 现状描述轨（面向用户）
    'status_description': {
        'sub_field_1': str,    # 子字段1的描述
        'sub_field_2': str,    # 子字段2的描述
        ...
        'plain': str,          # 动态白话描述
    },
    # 结论判定轨（面向系统）
    'judgment': {
        'sub_field_1': {
            'direction': int,  # +1/0/-1
            'light': str,      # green/yellow/red
        },
        ...
        'overall_light': str,
        'overall_direction': int,
    },
    # 条件稽核（供第7维状态总结使用）
    'audit': {
        'conditions': [
            {
                'name': str,
                'satisfied': bool,
                'actual': str,
                'threshold': str,
                'detail': str,
            }
        ],
        'satisfied_count': int,
        'total_count': int,
        'confidence': float,
    },
    # 连续强度值（0-1 或 -1~+1，替代离散投票）
    'continuous_value': float,
    'confidence': float,
    # 证据链
    'evidence': list[str],
}
```

### 5.2 dim1_signal_engine.py —— 第1维 信号确认引擎

```python
"""
dim1_signal_engine.py — 信号确认维度引擎（364h Phase 8）

职责：
- 信号触发检测（5类注册表信号）
- 信号验证状态跟踪（3日/5日验证）
- 信号生命周期计算（初期/中期/已延伸）
- 共振维度计数
- 衰减检测

输入：
- tags (pre_feat_cache扁平化)
- signals (strategy_signal_detail)
- lifecycle (生命周期数据)

输出：DimensionOutput
"""
from typing import Optional


class Dim1SignalEngine:
    """第1维：信号确认维度引擎"""
    
    def __init__(self, dm=None):
        self.dm = dm
    
    def evaluate(self, tags: dict, signals: dict, 
                 lifecycle: Optional[dict] = None) -> dict:
        """
        信号确认维度评估
        
        Returns: DimensionOutput
        """
        # 1. 信号触发检测
        triggered_signals = self._detect_triggered(signals, tags)
        
        # 2. 信号验证状态
        verification = self._check_verification(tags, lifecycle)
        
        # 3. 共振维度计数
        resonance = self._count_resonance(signals, tags)
        
        # 4. 生命周期阶段
        lifecycle_stage = lifecycle.get('stage', '中期') if lifecycle else '中期'
        
        # 5. 构建status_description
        status_description = self._build_status_desc(
            triggered_signals, verification, resonance, lifecycle_stage)
        
        # 6. 构建judgment
        judgment = self._build_judgment(
            triggered_signals, verification, resonance, lifecycle_stage)
        
        # 7. 构建audit
        audit = self._build_audit(
            triggered_signals, verification, resonance, lifecycle_stage)
        
        # 8. 连续强度值
        continuous = self._compute_continuous(
            triggered_signals, verification, resonance, lifecycle_stage)
        
        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
            'continuous_value': continuous,
            'confidence': judgment.get('confidence', 0.5),
            'evidence': triggered_signals.get('evidence', []),
        }
    
    def _detect_triggered(self, signals: dict, tags: dict) -> dict:
        """检测触发的注册表信号（5类）"""
        hits = []
        # 缠论三买
        bsp = str(tags.get('buy_sell_point', ''))
        if '三买' in bsp or 'third_buy' in bsp:
            hits.append({'type': 'chan_third_buy', 'name': '缠论三买'})
        # 放量突破
        vp = signals.get('量价分析策略') or {}
        if '突破' in str(vp.get('signal_label', '')):
            hits.append({'type': 'volume_breakout', 'name': '放量突破'})
        # 均线多头
        if '多头' in str(tags.get('ma_alignment', '')):
            hits.append({'type': 'ma_bullish', 'name': '均线多头'})
        # 平台突破
        ps = str(tags.get('pattern_signal', ''))
        if '突破' in ps:
            hits.append({'type': 'platform_breakout', 'name': '平台突破'})
        # 量价强势形态
        if ps and ps != 'none':
            hits.append({'type': 'pattern_up', 'name': '量价强势形态'})
        
        return {
            'count': len(hits),
            'signals': hits,
            'evidence': [f"触发{len(hits)}类信号: {', '.join(h['name'] for h in hits)}"] if hits else ['无活跃信号'],
        }
    
    def _check_verification(self, tags: dict, lifecycle: Optional[dict]) -> dict:
        """信号验证状态检查"""
        # TODO: Phase 7 signal_decay_detector 的输出
        return {'status': 'unknown', 'days': 0}
    
    def _count_resonance(self, signals: dict, tags: dict) -> int:
        """共振维度计数"""
        count = 0
        for dim in ('structure', 'vp', 'chip_fund', 'factor'):
            # 简化版：基于各维度confidence > 0.5判断
            pass
        return count
    
    def _build_status_desc(self, triggered, verification, resonance, stage) -> dict:
        """构建现状描述"""
        count = triggered.get('count', 0)
        names = ', '.join(s['name'] for s in triggered.get('signals', []))
        return {
            'attribute': f"右侧确认（{count}信号共振）" if count >= 2 else f"信号{stage}阶段",
            'strength': f"{count}维共振" if resonance >= 2 else "单维信号",
            'maintenance': f"信号{stage}",
            'plain': f"{'有' + str(count) + '个信号确认上涨' if count >= 2 else '信号处于' + stage + '阶段'}",
        }
    
    def _build_judgment(self, triggered, verification, resonance, stage) -> dict:
        """构建结论判定"""
        light = 'green' if triggered['count'] >= 2 else ('yellow' if triggered['count'] == 1 else 'red')
        return {
            'overall_light': light,
            'overall_direction': 1 if light == 'green' else (0 if light == 'yellow' else -1),
            'confidence': 0.7 if triggered['count'] >= 2 else 0.5,
        }
    
    def _build_audit(self, triggered, verification, resonance, stage) -> dict:
        """构建条件稽核"""
        conditions = [
            {'name': '信号触发', 'satisfied': triggered['count'] > 0,
             'actual': f'{triggered["count"]}类', 'threshold': '≥1类', 'detail': triggered['evidence'][0] if triggered['evidence'] else ''},
            {'name': '信号验证', 'satisfied': stage in ('初期', '中期'),
             'actual': stage, 'threshold': '初期或中期', 'detail': f'生命周期：{stage}'},
            {'name': '共振维度', 'satisfied': resonance >= 2,
             'actual': f'{resonance}维', 'threshold': '≥2维', 'detail': f'共振维度数：{resonance}'},
        ]
        sat = sum(1 for c in conditions if c['satisfied'])
        return {
            'conditions': conditions,
            'satisfied_count': sat,
            'total_count': len(conditions),
            'confidence': sat / len(conditions) if conditions else 0,
        }
    
    def _compute_continuous(self, triggered, verification, resonance, stage) -> float:
        """连续强度值 -1~+1"""
        score = 0
        if triggered['count'] >= 2:
            score += 0.4
        elif triggered['count'] == 1:
            score += 0.2
        if stage in ('初期', '中期'):
            score += 0.2
        if resonance >= 2:
            score += 0.2
        return min(1.0, max(-1.0, score))
```

### 5.3 dim2_structure_engine.py —— 第2维 结构位置引擎

```python
"""
dim2_structure_engine.py — 结构位置维度引擎（364h Phase 8）

职责：
- 价格vs中枢位置判定
- 均线排列统一计算（收敛3处）
- 价格位置统一计算（收敛3处）
- 支撑阻力（引用 shared_support_resistance）
- 几何化距离计算

输入：
- tags (pre_feat_cache)
- signals (strategy_signal_detail)
- sr_service (SupportResistanceService)

输出：DimensionOutput
"""


class Dim2StructureEngine:
    """第2维：结构位置维度引擎"""
    
    def __init__(self, dm=None, sr_service=None):
        self.dm = dm
        self.sr_service = sr_service
    
    def evaluate(self, tags: dict, signals: dict) -> dict:
        """
        结构位置维度评估
        
        Returns: DimensionOutput
        """
        from app.opportunity_atlas.dimensions.shared_support_resistance import get_support_resistance_service
        sr_svc = self.sr_service or get_support_resistance_service()
        
        # 1. 缠论趋势方向（统一来源：缠论信号status_recognition）
        chan = signals.get('缠论走势分析', {})
        trend_dir = self._get_trend_direction(chan)
        
        # 2. 价格vs中枢位置
        position_vs_zs = self._get_position_vs_zs(chan, tags)
        
        # 3. 均线排列（统一计算）
        ma_alignment = self._compute_ma_alignment(tags, signals)
        
        # 4. 支撑阻力（引用共享服务）
        sr = sr_svc.get_support_resistance(
            tags.get('ts_code', ''), tags, signals, self.dm)
        
        # 5. 价格位置
        price_position = self._compute_price_position(tags, sr)
        
        # 6. 几何化距离
        current_price = self._get_current_price(tags)
        geo_distances = self._compute_geo_distances(current_price, sr)
        
        # 7. 构建输出
        status_description = self._build_status_desc(
            trend_dir, position_vs_zs, ma_alignment, sr, geo_distances)
        judgment = self._build_judgment(trend_dir, ma_alignment, price_position)
        audit = self._build_audit(trend_dir, position_vs_zs, ma_alignment, sr)
        
        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
            'continuous_value': self._compute_continuous(trend_dir, ma_alignment),
            'confidence': judgment.get('confidence', 0.5),
            'evidence': [f'趋势={trend_dir}', f'均线={ma_alignment}', f'价格={price_position}'],
        }
    
    def _get_trend_direction(self, chan: dict) -> str:
        """从缠论信号提取趋势方向"""
        td = ((chan.get('status_recognition') or {}).get('trend') or {}).get('direction', '')
        return 'up' if td == 'up' else ('down' if td == 'down' else 'flat')
    
    def _get_position_vs_zs(self, chan: dict, tags: dict) -> str:
        """价格vs中枢位置"""
        zs_pos = ((chan.get('status_recognition') or {}).get('trend') or {}).get('direction', '')
        return zs_pos or tags.get('position_vs_zs', '未知')
    
    def _compute_ma_alignment(self, tags: dict, signals: dict) -> str:
        """均线排列统一计算（收敛3处）"""
        # 统一使用标签库中的ma_alignment（data_daemon预计算）
        return str(tags.get('ma_alignment', '未知'))
    
    def _compute_price_position(self, tags: dict, sr: dict) -> str:
        """价格位置统一计算（收敛3处）"""
        pp = str(tags.get('price_position', ''))
        if pp:
            return pp
        # 兜底：从支撑阻力推导
        current = self._get_current_price(tags)
        support = sr.get('support', 0)
        resistance = sr.get('resistance', 0)
        if current and support and resistance:
            if current <= support * 1.02:
                return 'low_zone'
            elif current >= resistance * 0.98:
                return 'high_zone'
        return '中位'
    
    def _get_current_price(self, tags: dict):
        """获取当前价格"""
        try:
            return float(tags.get('close', 0) or 0)
        except (TypeError, ValueError):
            return 0
    
    def _compute_geo_distances(self, price: float, sr: dict) -> dict:
        """几何化距离计算"""
        if not price:
            return {}
        support = sr.get('support', 0)
        resistance = sr.get('resistance', 0)
        return {
            'dist_to_support': round((price - support) / price * 100, 1) if support else None,
            'dist_to_resistance': round((resistance - price) / price * 100, 1) if resistance else None,
        }
    
    def _build_status_desc(self, trend, pos_zs, ma, sr, geo) -> dict:
        """构建现状描述"""
        trend_cn = {'up': '上升趋势', 'down': '下降趋势', 'flat': '盘整'}
        return {
            'vs_zhongshu': f"趋势{trend_cn.get(trend, '未知')}",
            'vs_ma': f"均线排列：{ma}",
            'vs_support_resistance': f"支撑{sr.get('support', 0):.2f} / 阻力{sr.get('resistance', 0):.2f}",
            'geo_distances': geo,
            'plain': f"走势{trend_cn.get(trend, '未知')}，均线{ma}",
        }
    
    def _build_judgment(self, trend, ma, position) -> dict:
        light = 'green' if trend == 'up' else ('red' if trend == 'down' else 'yellow')
        return {
            'overall_light': light,
            'overall_direction': 1 if trend == 'up' else (-1 if trend == 'down' else 0),
            'confidence': 0.7,
        }
    
    def _build_audit(self, trend, pos_zs, ma, sr) -> dict:
        conditions = [
            {'name': '趋势方向', 'satisfied': bool(trend and trend != 'flat'),
             'actual': trend, 'threshold': '有明确方向', 'detail': f'趋势：{trend}'},
            {'name': '均线排列', 'satisfied': bool(ma and ma != '未知'),
             'actual': ma, 'threshold': '有明确排列', 'detail': f'均线：{ma}'},
            {'name': '支撑阻力', 'satisfied': bool(sr.get('support') and sr.get('resistance')),
             'actual': f"支撑{sr.get('support', 0):.2f}/阻力{sr.get('resistance', 0):.2f}",
             'threshold': '有明确支撑阻力', 'detail': f'来源：{sr.get("source", "none")}'},
        ]
        sat = sum(1 for c in conditions if c['satisfied'])
        return {
            'conditions': conditions,
            'satisfied_count': sat,
            'total_count': len(conditions),
            'confidence': sat / len(conditions) if conditions else 0,
        }
    
    def _compute_continuous(self, trend, ma) -> float:
        score = {'up': 0.5, 'down': -0.5, 'flat': 0}.get(trend, 0)
        if '多头' in ma:
            score += 0.2
        elif '空头' in ma:
            score -= 0.2
        return max(-1.0, min(1.0, score))
```

### 5.4 dim3_vp_engine.py —— 第3维 量价健康引擎

```python
"""
dim3_vp_engine.py — 量价健康维度引擎（364h Phase 8）

职责：
- 量比统一计算（引用 shared_vol_ratio）
- 量价关系判定（收敛3处）
- 背离检测（收敛4+处）
- 健康度评分
- 量价形态匹配

输入：
- tags (pre_feat_cache)
- signals (strategy_signal_detail)
- vol_service (VolumeRatioService)

输出：DimensionOutput
"""


class Dim3VPEngine:
    """第3维：量价健康维度引擎"""
    
    def __init__(self, dm=None, vol_service=None):
        self.dm = dm
        self.vol_service = vol_service
    
    def evaluate(self, tags: dict, signals: dict) -> dict:
        from app.opportunity_atlas.dimensions.shared_vol_ratio import get_volume_ratio_service
        vol_svc = self.vol_service or get_volume_ratio_service()
        
        # 1. 统一量比
        vol_data = vol_svc.compute(tags.get('ts_code', ''), self.dm)
        
        # 2. 量价关系判定（统一使用 volume_price_strategy 输出）
        vp = signals.get('量价分析策略', {})
        vp_state = self._derive_vp_state(vp, tags)
        
        # 3. 背离检测
        divergence = self._detect_divergence(vp)
        
        # 4. 健康度评分
        health_score = self._compute_health_score(vp_state, vol_data, divergence)
        
        # 5. 构建输出
        status_description = self._build_status_desc(vp_state, vol_data, divergence, health_score)
        judgment = self._build_judgment(vp_state, health_score)
        audit = self._build_audit(vp_state, vol_data, divergence)
        
        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
            'continuous_value': self._compute_continuous(vp_state, health_score),
            'confidence': judgment.get('confidence', 0.5),
            'evidence': [f'量价={vp_state}', f'量比={vol_data["vol_ratio"]}', f'背离={divergence["has_divergence"]}'],
        }
    
    def _derive_vp_state(self, vp: dict, tags: dict) -> str:
        """量价状态判定（复用 StatusEngine._derive_vp_state 逻辑）"""
        # 统一到 StatusEngine 的三重数据源优先级
        from app.opportunity_atlas.status_engine import StatusEngine
        state, _, _ = StatusEngine._derive_vp_state(vp, tags)
        return state
    
    def _detect_divergence(self, vp: dict) -> dict:
        """背离检测"""
        vpd = vp.get('volume_price_detail') or {}
        rel = (vpd.get('量价关系') or {}) if isinstance(vpd, dict) else {}
        div_type = str(rel.get('divergence', 'none'))
        macd_ok = bool(rel.get('divergence_macd_confirmed'))
        return {
            'type': div_type if div_type != 'none' else '无',
            'macd_confirmed': macd_ok,
            'has_divergence': div_type in ('top', 'bottom'),
        }
    
    def _compute_health_score(self, vp_state: str, vol_data: dict, divergence: dict) -> int:
        """健康度评分 0-100"""
        score_map = {'强健康': 85, '健康': 70, '中性': 50, '背离': 30, '严重背离': 15}
        score = score_map.get(vp_state, 50)
        if divergence['has_divergence'] and divergence['type'] == 'top':
            score = max(score - 20, 0)
        return score
    
    def _build_status_desc(self, vp_state, vol_data, divergence, health) -> dict:
        div_text = f"背离类型：{divergence['type']}" if divergence['has_divergence'] else '无背离'
        return {
            'vp_state': f"量价关系：{vp_state}",
            'health_score': f"健康度：{health}/100",
            'divergence': div_text,
            'volume_energy': vol_data.get('volume_energy', ''),
            'plain': f"量价关系{vp_state}，{vol_data.get('volume_status', '')}",
        }
    
    def _build_judgment(self, vp_state, health) -> dict:
        light_map = {'强健康': 'green', '健康': 'green', '中性': 'yellow', '背离': 'red', '严重背离': 'red'}
        light = light_map.get(vp_state, 'yellow')
        return {'overall_light': light, 'overall_direction': 1 if light == 'green' else (-1 if light == 'red' else 0), 'confidence': 0.7}
    
    def _build_audit(self, vp_state, vol_data, divergence) -> dict:
        conditions = [
            {'name': '量价关系', 'satisfied': vp_state in ('强健康', '健康'),
             'actual': vp_state, 'threshold': '健康或强健康', 'detail': f'量价状态：{vp_state}'},
            {'name': '背离检测', 'satisfied': not divergence['has_divergence'],
             'actual': '有背离' if divergence['has_divergence'] else '无背离', 'threshold': '无背离', 'detail': f'背离类型：{divergence["type"]}'},
            {'name': '量比状态', 'satisfied': 0.8 <= vol_data['vol_ratio'] <= 3.0,
             'actual': f'{vol_data["vol_ratio"]:.1f}', 'threshold': '0.8-3.0', 'detail': f'量比：{vol_data["vol_ratio"]}'},
        ]
        sat = sum(1 for c in conditions if c['satisfied'])
        return {'conditions': conditions, 'satisfied_count': sat, 'total_count': len(conditions), 'confidence': sat / len(conditions)}
    
    def _compute_continuous(self, vp_state, health) -> float:
        score_map = {'强健康': 0.8, '健康': 0.5, '中性': 0, '背离': -0.5, '严重背离': -0.8}
        return score_map.get(vp_state, 0)
```

### 5.5 dim4_chip_fund_engine.py —— 第4维 资金筹码引擎

```python
"""
dim4_chip_fund_engine.py — 资金筹码维度引擎（364h Phase 8）

职责：
- 主力阶段判定（收敛两套并行系统）
- 资金流向评分（收敛两套主力评分）
- 筹码结构分析
- 量比引用（shared_vol_ratio）
- moneyflow_cache查询统一

输入：
- tags (pre_feat_cache)
- signals (strategy_signal_detail)
- vol_service (VolumeRatioService)

输出：DimensionOutput
"""


class Dim4ChipFundEngine:
    """第4维：资金筹码维度引擎"""
    
    def __init__(self, dm=None, vol_service=None):
        self.dm = dm
        self.vol_service = vol_service
    
    def evaluate(self, tags: dict, signals: dict) -> dict:
        # 1. 主力阶段
        main_phase = self._determine_phase(tags, signals)
        
        # 2. 资金流向
        fund_flow = self._determine_fund_flow(tags)
        
        # 3. 筹码结构
        chip_structure = self._determine_chip_structure(tags)
        
        # 4. 信号
        chip_signal = self._determine_signal(tags, signals)
        
        # 5. 构建输出
        status_description = self._build_status_desc(main_phase, fund_flow, chip_structure, chip_signal)
        judgment = self._build_judgment(main_phase, fund_flow)
        audit = self._build_audit(main_phase, fund_flow, chip_structure)
        
        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
            'continuous_value': self._compute_continuous(main_phase, fund_flow),
            'confidence': judgment.get('confidence', 0.5),
            'evidence': [f'阶段={main_phase}', f'资金={fund_flow}', f'筹码={chip_structure}'],
        }
    
    def _determine_phase(self, tags, signals) -> str:
        """主力阶段判定（收敛两套系统为统一判定）"""
        mfp = str(tags.get('main_force_phase', ''))
        phase_map = {'building': '建仓期', 'washing': '洗盘期', 'raising': '拉升期', 'distributing': '出货期'}
        return phase_map.get(mfp, '未知')
    
    def _determine_fund_flow(self, tags) -> str:
        """资金流向判定"""
        ff = str(tags.get('fund_flow', ''))
        return {'5d_inflow': '流入', '5d_outflow': '流出'}.get(ff, '中性')
    
    def _determine_chip_structure(self, tags) -> dict:
        """筹码结构"""
        return {
            'concentration': tags.get('concentration', 0),
            'chip_peak': tags.get('chip_peak', 0),
            'profit_ratio': tags.get('profit_ratio', 0),
        }
    
    def _determine_signal(self, tags, signals) -> str:
        """筹码信号"""
        chip = signals.get('筹码主力分析', {})
        return str((chip.get('status_recognition') or {}).get('state', '未知'))
    
    def _build_status_desc(self, phase, flow, chip, signal) -> dict:
        return {
            'phase': f"主力{phase}",
            'fund_flow': f"资金{flow}",
            'cost_structure': f"筹码峰{chip.get('chip_peak', 0):.2f}",
            'plain': f"主力{phase}，资金{flow}",
        }
    
    def _build_judgment(self, phase, flow) -> dict:
        direction = 1 if flow == '流入' else (-1 if flow == '流出' else 0)
        light = 'green' if direction > 0 else ('red' if direction < 0 else 'yellow')
        return {'overall_light': light, 'overall_direction': direction, 'confidence': 0.6}
    
    def _build_audit(self, phase, flow, chip) -> dict:
        conditions = [
            {'name': '主力阶段', 'satisfied': phase != '未知', 'actual': phase, 'threshold': '有明确阶段', 'detail': f'主力阶段：{phase}'},
            {'name': '资金流向', 'satisfied': flow != '未知', 'actual': flow, 'threshold': '有明确流向', 'detail': f'资金流向：{flow}'},
        ]
        sat = sum(1 for c in conditions if c['satisfied'])
        return {'conditions': conditions, 'satisfied_count': sat, 'total_count': len(conditions), 'confidence': sat / len(conditions)}
    
    def _compute_continuous(self, phase, flow) -> float:
        flow_map = {'流入': 0.6, '中性': 0, '流出': -0.6}
        return flow_map.get(flow, 0)
```

### 5.6 dim5_emotion_engine.py —— 第5维 情绪环境引擎

```python
"""
dim5_emotion_engine.py — 情绪环境维度引擎（364h Phase 8）

职责：
- 市场情绪阶段收敛（sentiment_phase映射统一）
- BOCIASI四象限调用统一
- 板块热度整合
- 涨停生态指标整合
- 事件影响评估

输入：
- tags (pre_feat_cache)
- signals (strategy_signal_detail)

输出：DimensionOutput
"""


class Dim5EmotionEngine:
    """第5维：情绪环境维度引擎"""
    
    def __init__(self, dm=None):
        self.dm = dm
    
    def evaluate(self, tags: dict, signals: dict) -> dict:
        # 1. 市场情绪阶段
        market_emotion = self._determine_market_emotion(tags, signals)
        
        # 2. 板块热度
        sector_heat = self._determine_sector_heat(tags)
        
        # 3. 事件影响
        event_impact = self._determine_event_impact(tags)
        
        # 4. 构建输出
        status_description = self._build_status_desc(market_emotion, sector_heat, event_impact)
        judgment = self._build_judgment(market_emotion, sector_heat, event_impact)
        audit = self._build_audit(market_emotion, sector_heat, event_impact)
        
        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
            'continuous_value': self._compute_continuous(market_emotion),
            'confidence': judgment.get('confidence', 0.5),
            'evidence': [f'市场={market_emotion}', f'板块={sector_heat}', f'事件={event_impact}'],
        }
    
    def _determine_market_emotion(self, tags, signals) -> str:
        """市场情绪阶段（统一映射，收敛2处）"""
        sp = str(tags.get('sentiment_phase', ''))
        # 统一映射（收敛 StatusEngine + BOCIASI 两处）
        emotion_map = {
            'recovery': '复苏', 'climax': '退潮', 'ebb': '退潮',
            'cautious': '正常', 'euphoria': '退潮',
        }
        emo = emotion_map.get(sp, '正常')
        
        # BOCIASI信号覆盖
        bociasi = signals.get('BOCIASI快线') or signals.get('BOCIASI慢线(情绪-跨市场)') or {}
        esig = str(bociasi.get('signal', ''))
        if esig in ('bullish', 'BULLISH'):
            emo = '复苏'
        elif esig in ('bearish', 'BEARISH'):
            emo = '退潮'
        
        return emo
    
    def _determine_sector_heat(self, tags) -> str:
        """板块热度"""
        return str(tags.get('sector_heat', '未知'))
    
    def _determine_event_impact(self, tags) -> str:
        """事件影响"""
        ce = str(tags.get('catalyst_event', ''))
        _neg = {'pledge', 'float', 'reduce', 'fraud_sign', 'regulatory', 'lawsuit', 'decline'}
        _pos = {'earnings', 'lhb', 'concept', 'buyback', 'breakout', 'new_high', 'profit_growth'}
        return '正向' if ce in _pos else ('负面' if ce in _neg else '中性')
    
    def _build_status_desc(self, market, sector, event) -> dict:
        return {
            'market': f"市场情绪{market}",
            'sector': f"板块热度{sector}",
            'event': f"事件影响{event}",
            'plain': f"市场{market}，事件{event}",
        }
    
    def _build_judgment(self, market, sector, event) -> dict:
        light = 'green' if market == '复苏' else ('red' if market == '退潮' else 'yellow')
        return {'overall_light': light, 'overall_direction': 1 if light == 'green' else (-1 if light == 'red' else 0), 'confidence': 0.6}
    
    def _build_audit(self, market, sector, event) -> dict:
        conditions = [
            {'name': '市场情绪', 'satisfied': market in ('复苏', '正常'), 'actual': market, 'threshold': '复苏或正常', 'detail': f'市场情绪：{market}'},
            {'name': '事件影响', 'satisfied': event != '负面', 'actual': event, 'threshold': '非负面', 'detail': f'事件：{event}'},
        ]
        sat = sum(1 for c in conditions if c['satisfied'])
        return {'conditions': conditions, 'satisfied_count': sat, 'total_count': len(conditions), 'confidence': sat / len(conditions)}
    
    def _compute_continuous(self, market) -> float:
        return {'复苏': 0.6, '正常': 0, '退潮': -0.6}.get(market, 0)
```

### 5.7 dim6_risk_engine.py —— 第6维 风险边界引擎

```python
"""
dim6_risk_engine.py — 风险边界维度引擎（364h Phase 8）

职责：
- risk_level统一计算（收敛10+处为1处）
- valuation风险评估
- finance PIERS检查
- 支撑阻力引用（shared_support_resistance）
- 盈亏比计算
- 波动率评估

输入：
- tags (pre_feat_cache)
- signals (strategy_signal_detail)
- sr_service (SupportResistanceService)

输出：DimensionOutput
"""


class Dim6RiskEngine:
    """第6维：风险边界维度引擎"""
    
    def __init__(self, dm=None, sr_service=None):
        self.dm = dm
        self.sr_service = sr_service
    
    def evaluate(self, tags: dict, signals: dict) -> dict:
        from app.opportunity_atlas.dimensions.shared_support_resistance import get_support_resistance_service
        sr_svc = self.sr_service or get_support_resistance_service()
        
        # 1. risk_level统一计算
        risk_level = self._compute_risk_level(tags, signals)
        
        # 2. 估值风险
        valuation = self._compute_valuation(tags)
        
        # 3. 财务风险
        finance = self._compute_finance(tags)
        
        # 4. 支撑阻力
        sr = sr_svc.get_support_resistance(tags.get('ts_code', ''), tags, signals, self.dm)
        
        # 5. 盈亏比
        risk_reward = self._compute_risk_reward(tags, sr)
        
        # 6. 波动率
        volatility = self._compute_volatility(tags)
        
        # 7. 构建输出
        status_description = self._build_status_desc(risk_level, valuation, finance, sr, risk_reward, volatility)
        judgment = self._build_judgment(risk_level, valuation, finance)
        audit = self._build_audit(risk_level, valuation, finance)
        
        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
            'continuous_value': self._compute_continuous(risk_level),
            'confidence': judgment.get('confidence', 0.5),
            'evidence': [f'风险={risk_level}', f'估值={valuation}', f'财务={finance}'],
        }
    
    def _compute_risk_level(self, tags, signals) -> str:
        """risk_level统一计算（收敛10+处）"""
        rl = str(tags.get('risk_level', ''))
        vl = str(tags.get('volatility_level', ''))
        if rl == 'HIGH' or vl == 'high':
            return '高'
        elif rl == 'LOW':
            return '低'
        return '中'
    
    def _compute_valuation(self, tags) -> str:
        """估值风险"""
        vl = str(tags.get('valuation_level', ''))
        return {'extreme_low': '极度低估', 'low': '低估', 'fair': '合理', 'high': '高估', 'extreme_high': '极度高估'}.get(vl, '合理')
    
    def _compute_finance(self, tags) -> str:
        """财务风险"""
        fh = str(tags.get('fina_health', ''))
        return {'pass': '健康', 'suspicious': '关注', 'fail': '风险'}.get(fh, '关注')
    
    def _compute_risk_reward(self, tags, sr) -> float:
        """盈亏比"""
        try:
            price = float(tags.get('close', 0) or 0)
            support = sr.get('support', 0)
            resistance = sr.get('resistance', 0)
            if price and support and resistance and (price - support) > 0:
                return round((resistance - price) / (price - support), 2)
        except (TypeError, ValueError):
            pass
        return 0
    
    def _compute_volatility(self, tags) -> str:
        """波动率"""
        return str(tags.get('volatility_level', '中'))
    
    def _build_status_desc(self, risk, val, fin, sr, rr, vol) -> dict:
        rr_label = f"盈亏比{rr}" if rr else "盈亏比未知"
        return {
            'risk_level': f"风险等级：{risk}",
            'support_resistance': f"支撑{sr.get('support', 0):.2f}/阻力{sr.get('resistance', 0):.2f}",
            'risk_reward': rr_label,
            'volatility': f"波动率{vol}",
            'plain': f"风险{risk}，估值{val}，财务{fin}",
        }
    
    def _build_judgment(self, risk, val, fin) -> dict:
        light = 'green' if risk == '低' else ('red' if risk == '高' else 'yellow')
        return {'overall_light': light, 'overall_direction': 1 if light == 'green' else (-1 if light == 'red' else 0), 'confidence': 0.6}
    
    def _build_audit(self, risk, val, fin) -> dict:
        conditions = [
            {'name': '风险等级', 'satisfied': risk in ('低', '中'), 'actual': risk, 'threshold': '低或中', 'detail': f'风险等级：{risk}'},
            {'name': '估值状态', 'satisfied': val in ('低估', '极度低估', '合理'), 'actual': val, 'threshold': '合理或低估', 'detail': f'估值：{val}'},
            {'name': '财务健康', 'satisfied': fin == '健康', 'actual': fin, 'threshold': '健康', 'detail': f'财务：{fin}'},
        ]
        sat = sum(1 for c in conditions if c['satisfied'])
        return {'conditions': conditions, 'satisfied_count': sat, 'total_count': len(conditions), 'confidence': sat / len(conditions)}
    
    def _compute_continuous(self, risk) -> float:
        return {'低': 0.5, '中': 0, '高': -0.5}.get(risk, 0)
```

---

## 六、data_daemon.py 分散计算逻辑收敛清单

### 6.1 需要收敛到维度引擎的计算

| 当前位置 | 计算内容 | 收敛到 | 操作 |
|---------|---------|--------|------|
| `data_daemon.py:L185-249` | `_compute_volume_ratio()` | `shared_vol_ratio.py` | 改为调用共享服务 |
| `data_daemon.py:L3768-3851` | `_build_status_snapshot()` | 6维度引擎 | 内部调用6个引擎 |
| `data_daemon.py:L2328` | pre_feat_cache 标签提取 | 维度引擎内部 | 移除冗余提取 |

### 6.2 需要保留的data_daemon计算（数据层，非业务逻辑）

| 计算内容 | 保留原因 |
|---------|---------|
| `_batch_daily()` | 数据采集层，非业务逻辑 |
| `_batch_daily_basic()` | 数据采集层 |
| `_batch_moneyflow()` | 数据采集层 |
| `_compute_volume_ratio()` | → 改为调用 shared_vol_ratio（数据层自算仍保留） |
| `run_integrity_check()` | 数据质量保障 |

---

## 七、status_engine.py 中 evaluate() 的重构方案

### 7.1 当前实现（L64-80）

```python
def evaluate(self, ts_code: str) -> Optional[dict]:
    tags = self._load_tags(ts_code)
    signals = self._load_signals(ts_code)
    lifecycle = self._signal_lifecycle(ts_code, tags, signals)
    dims = self._build_dimensions(ts_code, tags, signals, lifecycle)  # ← 11维散装判定
    l0 = self._apply_l0(ts_code, tags, dims, lifecycle)
    l2 = self._aggregate(tags, dims, l0, lifecycle)
    hits = self._detect_registered_signals(tags, signals)
    return self._assemble(ts_code, dims, lifecycle, l0, l2, hits)
```

### 7.2 重构后实现

```python
def evaluate(self, ts_code: str) -> Optional[dict]:
    tags = self._load_tags(ts_code)
    signals = self._load_signals(ts_code)
    
    if not tags and not signals:
        return None
    
    # 1. 加载共享服务
    from app.opportunity_atlas.dimensions.shared_support_resistance import get_support_resistance_service
    from app.opportunity_atlas.dimensions.shared_vol_ratio import get_volume_ratio_service
    sr_svc = get_support_resistance_service()
    vol_svc = get_volume_ratio_service()
    
    # 2. 生命周期计算（保留，供信号引擎使用）
    lifecycle = self._signal_lifecycle(ts_code, tags, signals)
    
    # 3. 6维度引擎评估（替代原_build_dimensions散装逻辑）
    from app.opportunity_atlas.dimensions import (
        Dim1SignalEngine, Dim2StructureEngine, Dim3VPEngine,
        Dim4ChipFundEngine, Dim5EmotionEngine, Dim6RiskEngine
    )
    
    dim_results = {
        'signal': Dim1SignalEngine(self.dm).evaluate(tags, signals, lifecycle),
        'structure': Dim2StructureEngine(self.dm, sr_svc).evaluate(tags, signals),
        'vp': Dim3VPEngine(self.dm, vol_svc).evaluate(tags, signals),
        'chip_fund': Dim4ChipFundEngine(self.dm, vol_svc).evaluate(tags, signals),
        'emotion': Dim5EmotionEngine(self.dm).evaluate(tags, signals),
        'risk': Dim6RiskEngine(self.dm, sr_svc).evaluate(tags, signals),
    }
    
    # 4. 转换为dims格式（兼容下游 _aggregate 和 _assemble）
    dims = self._convert_to_dims_format(dim_results)
    
    # 5. L0/L2 逻辑保持不变（使用转换后的dims）
    l0 = self._apply_l0(ts_code, tags, dims, lifecycle)
    l2 = self._aggregate(tags, dims, l0, lifecycle)
    hits = self._detect_registered_signals(tags, signals)
    
    return self._assemble(ts_code, dims, lifecycle, l0, l2, hits, dim_results)


def _convert_to_dims_format(self, dim_results: dict) -> dict:
    """将维度引擎输出转换为原有的dims格式（兼容 _aggregate 和 _assemble）"""
    dims = {}
    for dim_key, result in dim_results.items():
        jd = result.get('judgment', {})
        light = jd.get('overall_light', 'yellow')
        direction = jd.get('overall_direction', 0)
        # 映射回原有格式
        state_map = {
            'green': list(_DIM_DIRECTION.get(self._dim_key_map(dim_key), {}).keys())[0] if direction > 0 else '中性',
            'yellow': '中性',
            'red': list(_DIM_DIRECTION.get(self._dim_key_map(dim_key), {}).keys())[-1] if direction < 0 else '中性',
        }
        dims[self._dim_key_map(dim_key)] = {
            'state': state_map.get(light, '中性'),
            'light': light,
            'confidence': result.get('confidence', 0.5),
            'evidence': result.get('evidence', []),
        }
    return dims

@staticmethod
def _dim_key_map(dim_key: str) -> str:
    """维度引擎key → 原有dims key映射"""
    return {
        'signal': 'signal_confirm',
        'structure': 'structure',
        'vp': 'vp',
        'chip_fund': 'chip_fund',
        'emotion': 'emotion',
        'risk': 'risk',
    }.get(dim_key, dim_key)
```

---

## 八、各引擎的具体实现步骤

### 8.1 实施顺序（按358号§10.5）

| 步骤 | 维度 | 工作量 | 依赖 | 说明 |
|------|------|:------:|------|------|
| 1 | 共享服务 | 4h | 无 | shared_support_resistance + shared_vol_ratio |
| 2 | dim1_signal_engine | 2h | 步骤1 | 最简单，逻辑最集中 |
| 3 | dim5_emotion_engine | 2h | 步骤1 | 核心引擎已有，只需收敛 |
| 4 | dim6_risk_engine | 3h | 步骤1 | 统一risk_level（10+→1处） |
| 5 | dim2_structure_engine | 3h | 步骤1 | 依赖共享支撑阻力 |
| 6 | dim3_vp_engine | 3h | 步骤1 | 依赖共享量比 |
| 7 | dim4_chip_fund_engine | 3h | 步骤1 | 最复杂，依赖量价维度 |
| 8 | evaluate()重构 + 兼容层 | 2h | 步骤2-7 | 统一入口 |
| **合计** | | **20h** | | |

### 8.2 文件创建清单

| # | 文件路径 | 操作 |
|---|---------|------|
| 1 | `backend/app/opportunity_atlas/dimensions/__init__.py` | 新建 |
| 2 | `backend/app/opportunity_atlas/dimensions/shared_support_resistance.py` | 新建 |
| 3 | `backend/app/opportunity_atlas/dimensions/shared_vol_ratio.py` | 新建 |
| 4 | `backend/app/opportunity_atlas/dimensions/dim1_signal_engine.py` | 新建 |
| 5 | `backend/app/opportunity_atlas/dimensions/dim2_structure_engine.py` | 新建 |
| 6 | `backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py` | 新建 |
| 7 | `backend/app/opportunity_atlas/dimensions/dim4_chip_fund_engine.py` | 新建 |
| 8 | `backend/app/opportunity_atlas/dimensions/dim5_emotion_engine.py` | 新建 |
| 9 | `backend/app/opportunity_atlas/dimensions/dim6_risk_engine.py` | 新建 |

### 8.3 文件修改清单

| # | 文件路径 | 修改内容 |
|---|---------|---------|
| 1 | `status_engine.py` | evaluate()重构为调用6维度引擎 + 兼容层 |
| 2 | `data_daemon.py` | _build_status_snapshot()改为调用维度引擎 |
| 3 | `data_daemon.py` | _compute_volume_ratio()改为调用shared_vol_ratio |
| 4 | `condition_auditor.py` | 改为消费维度引擎的audit输出（不再独立计算） |
| 5 | `advice_builder.py` | 改为调用shared_support_resistance |
| 6 | `cross_validate.py` | 消费维度引擎统一输出 |
| 7 | `arbiter.py` | 消费维度引擎连续强度值 |

---

## 九、测试用例

### 9.1 共享服务测试

```python
# shared_support_resistance 测试
def test_sr_service_priority():
    """数据源优先级：chanlun > geometric > tags > ma60"""
    svc = SupportResistanceService()
    # 场景1：缠论有数据 → 使用缠论
    sr = svc.get_support_resistance('000001.SZ', tags={}, signals={'缠论走势分析': {...}})
    assert sr['source'] == 'chanlun'
    # 场景2：缠论无数据，标签有 → 使用标签
    sr = svc.get_support_resistance('000001.SZ', tags={'support_resistance': '{"support":10}'}, signals={})
    assert sr['source'] == 'tags'

# shared_vol_ratio 测试
def test_vol_ratio_consistency():
    """量比统一性：所有维度看到相同的量比值"""
    svc = VolumeRatioService()
    result = svc.compute('000001.SZ')
    assert result['vol_ratio'] > 0
    assert result['volume_status'] in ('极端放量', '明显放量', '温和放量', '量能正常', '量能萎缩', '极度萎缩')
```

### 9.2 维度引擎测试

```python
def test_dim1_signal_engine():
    """信号引擎：共振信号判定"""
    engine = Dim1SignalEngine()
    tags = {'buy_sell_point': 'third_buy', 'ma_alignment': '多头'}
    signals = {'量价分析策略': {'signal_label': '突破'}}
    result = engine.evaluate(tags, signals)
    assert result['judgment']['overall_light'] == 'green'
    assert result['audit']['satisfied_count'] >= 2

def test_dim6_risk_engine_risk_level():
    """风险引擎：risk_level收敛性"""
    engine = Dim6RiskEngine()
    tags = {'risk_level': 'HIGH', 'valuation_level': 'extreme_high'}
    result = engine.evaluate(tags, {})
    assert result['status_description']['risk_level'] == '风险等级：高'
    assert result['judgment']['overall_light'] == 'red'
```

### 9.3 集成测试

```python
def test_evaluate_uses_dim_engines():
    """evaluate()使用维度引擎"""
    engine = StatusEngine()
    result = engine.evaluate('000001.SZ')
    if result:
        dims = json.loads(result['dim_states'])
        assert 'structure' in dims
        assert 'vp' in dims
        assert dims['structure']['light'] in ('green', 'yellow', 'red')

def test_vol_ratio_convergence():
    """量比收敛性：不再6处独立计算"""
    # 确认 shared_vol_ratio 被所有引擎使用
    from app.opportunity_atlas.dimensions.shared_vol_ratio import get_volume_ratio_service
    svc = get_volume_ratio_service()
    result = svc.compute('000001.SZ')
    assert result['source'] != 'none'
```

### 9.4 回归测试

```python
def test_full_pytest_pass():
    """全量pytest确认无回归"""
    # 执行: pytest tests/ -v
    # 预期: 325+ passed, 0 failed
    pass
```

---

## 十、实施步骤汇总

| 步骤 | 内容 | 工作量 |
|------|------|:------:|
| 1 | 创建dimensions目录 + __init__.py | 0.5h |
| 2 | shared_support_resistance.py | 2h |
| 3 | shared_vol_ratio.py | 1.5h |
| 4 | dim1_signal_engine.py | 2h |
| 5 | dim5_emotion_engine.py | 2h |
| 6 | dim6_risk_engine.py | 3h |
| 7 | dim2_structure_engine.py | 3h |
| 8 | dim3_vp_engine.py | 3h |
| 9 | dim4_chip_fund_engine.py | 3h |
| 10 | evaluate()重构 + 兼容层 | 2h |
| 11 | 测试用例 | 3h |
| 12 | 代码审查 + 冗余代码清理 | 2h |
| **合计** | | **25h**（含缓冲） |

---

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|---------|
| v1.0 | 2026-08-21 | 初版：358号§十整合方案详细化，6引擎接口+共享服务+收敛清单+测试 |
