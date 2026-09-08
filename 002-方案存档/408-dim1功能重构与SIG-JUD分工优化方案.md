# 408号 — dim1功能重构与SIG-JUD分工优化方案

> **编制日期**：2026-09-03
> **编制依据**：dim1代码核查 + 389号/390号/392号方案审计结论 + 用户指示
> **状态**：待实施
> **关联方案**：358号（策略分析总纲）、389号（SIG输出与JUD消费审计）、390号（JUD多因子决策引擎）、392号（SIG系统架构说明）、407号（维度引擎数据访问路径冲突）

---

## 一、问题背景

### 1.1 dim1当前定位

dim1（Dim1SignalEngine）是第1维**信号确认引擎**，位于SIG环节，做三件事：

1. **7类信号属性分类**：right_confirmed / right_emerging / trend_running / left_probing / risk_warning / consolidating / neutral
2. **5维度共振评分**：structure/vp/chip_fund/factor 四维置信度加权
3. **衰减检测 + 生命周期**：信号持续天数、衰减分数、初期/中期/已延伸阶段

### 1.2 核心问题

dim1当前做的事情本质上是**判定逻辑**（属性分类、评分、衰减判断），而非**分析计算**（从原始数据提取指标）。这导致：

1. **SIG/JUD职责混淆**：dim1在SIG环节做了JUD应该做的事情
2. **数据多流转**：dim1需要读取其他dim的输出（dims参数），然后JUD又读取dim1的判定结果，同一数据被判定两次
3. **输出利用率极低**：389号审计显示dim1的18个输出字段**0%被JUD消费**。390号v3.0虽新增signal因子接入，但仅使用了attribute.code一个字段
4. **循环依赖隐患**：dim1的classify_attribute()读取dims.get('risk')、dims.get('structure')等，但dim1是_build_dim_engine_results()中第一个被调用的引擎，此时其他维度尚未计算，dims传入空字典{}

### 1.3 与JUD的关系

| 维度 | JUD当前做法 | dim1做法 | 关系 |
|------|------------|---------|------|
| 信号确认状态 | 直接读tags.right_side_confirm（纯标签） | 7类属性分类（基于多维交叉判定） | dim1更精细 |
| 方向判定 | dim_adapter读judgment.attribute.code → direction | judgment.overall_direction | dim1已接入JUD（390号v3.0） |
| 衰减/生命周期 | 不处理 | 5维度衰减+生命周期阶段 | dim1独有能力 |

---

## 二、重构方案

### 2.1 设计原则

- **SIG = 分析**：从原始数据计算分析指标，不做判定决策
- **JUD = 判定**：基于分析结果做判定决策
- **dim1 = 数据调度**：为dim2-dim7准备数据上下文，不做分析也不做判定

### 2.2 dim1重构为数据调度层

将dim1从"信号确认引擎"重构为"SIG数据调度器"，职责：

| 当前职责 | 重构后职责 |
|---------|-----------|
| 7类属性分类 | 数据完整性检查 |
| 共振评分 | 预加载共享数据（减少重复IO） |
| 衰减检测 | 缺失数据标记+补采请求 |
| 生命周期阶段 | 为各dim构建data_context |

### 2.3 判定逻辑迁移到JUD

dim1的判定逻辑迁移到JUD的对应组件：

| dim1功能 | 迁移到JUD后的实现位置 |
|---------|---------------------|
| 7类属性分类 | dim_adapter.convert_to_factors()扩展signal因子提取 |
| 共振评分 | L2聚合层（consensus_engine）维度共识计算 |
| 衰减检测 | reliability_assessor信号可靠性因子 |
| 生命周期 | dim_adapter或advice_engine信号成熟度因子 |

### 2.4 两阶段实施路径

#### Phase 1（P0）：修复消费链路 + 调用顺序

**目标**：解决"dim1判定逻辑不被消费"和"循环依赖"两个核心问题

**操作**：
1. 修复调用顺序：status_engine.py的engine_map中将`'signal'`从第一位移到最后一位（`valuation`之后），使dim1在dim2-dim7之后调用，确保dims参数有实际数据
2. 在dim_adapter中完整接入dim1的判定逻辑（共振评分/衰减/生命周期），扩展signal因子为v3.1
3. dim1的status_description直通OUT（389号已建议）
4. 保留dim1的evaluate()接口和Dim1SignalEngine类名不变，仅调整调用顺序

**改动范围**：
- status_engine.py：engine_map中`'signal'`条目从第1位移到第7位（行223→行229之后）
- dim_adapter.py：扩展signal因子提取逻辑（v3.0→v3.1）
- dim8_summary_engine.py：小改dim1输出读取

**工时**：0.3天

#### Phase 2（P1）：dim1重构为数据调度层

**目标**：解决"数据多流转"和"分散读取"的架构问题

**操作**：
1. dim1_signal_engine.py重写：Dim1SignalEngine类保留（接口签名`evaluate(dims, tags, signals, lifecycle)`不变），但内部实现从判定逻辑改为数据调度逻辑（完整性检查+预加载+缺失标记）
2. dim1的判定逻辑完全迁移到JUD（dim_adapter + reliability_assessor）
3. dim1变为纯数据准备+完整性检查，evaluate()返回data_context而非status_description/judgment/audit
4. dim2-dim7引擎渐进式改造：优先dim4/dim5（资源浪费最严重），从data_context读取预加载数据，减少各自读数据库

**改动范围**：
- dim1_signal_engine.py：重写evaluate()内部实现，保留类名和接口签名
- status_engine.py：调整调用链（dim1的输出作为dim2-dim7的输入）
- dim2-dim7引擎：渐进式改造，优先dim4/dim5
- dim_adapter.py：完全接管dim1的判定逻辑

**注意**：Phase 2完成后，dim1的evaluate()返回格式从`{status_description, judgment, audit}`变为`{data_context}`，需要status_engine适配新的返回格式。

**工时**：1.0天

---

## 三、数据调度层设计

### 3.1 核心职责

```python
class Dim1DataDispatcher:
    """SIG数据调度器 — 原料检查+调拨"""

    def prepare(self, ts_code, tags, lifecycle) -> dict:
        """为dim2-dim7准备数据上下文"""
        context = {}

        # 1. 数据完整性检查
        context['completeness'] = self._check_completeness(tags)

        # 2. 预加载共享数据（减少重复IO）
        context['daily_cache'] = self._preload_daily(ts_code)
        context['daily_basic'] = self._preload_daily_basic(ts_code)

        # 3. 缺失数据标记
        context['missing'] = self._identify_missing(tags)
        if context['missing']:
            self._request_sync(ts_code, context['missing'])

        # 4. 各dim的数据切片
        context['dim2_data'] = {'df': context['daily_cache'], ...}
        context['dim3_data'] = {'df': context['daily_cache'], ...}
        context['dim4_data'] = {'df': ..., 'moneyflow': ..., ...}

        return context
```

### 3.2 设计优势

| 问题 | 当前状态 | 重构后 |
|------|---------|--------|
| 数据完整性 | 6个dim各自try-except降级，无法统一感知 | dim1集中检查，统一标记缺失 |
| 重复IO | dim4和dim5都读daily_cache | dim1预加载一次共享 |
| 缺失数据补采 | 各dim各自静默失败 | dim1统一写sync_requests |
| 数据依赖追踪 | 隐式（每个dim内部） | 显式（context字典） |

### 3.3 与407号方案的协同

407号方案（dim1-dim6双重调用）的Phase 1（剔除旧路径调用）与此方案的Phase 1（修复调用顺序）可并行实施，互不冲突。Phase 2的数据调度层设计可作为407号方案Phase 2（dim4/dim5部分计算移到RAW层）的前置优化。

### 3.4 循环依赖修复说明

当前dim1在engine_map中排第一位（行223），是_build_dim_engine_results()中第一个被调用的引擎。此时dims传入空字典{}，导致dim1的classify_attribute()中依赖dims的分支（risk_warning需要dims.risk=='高'、left_probing需要dims.structure=='下降'等）**永远不会触发**。

Phase 1通过将`'signal'`移到engine_map最后一位修复此问题。Phase 2通过数据调度层架构从根本上消除循环依赖——dim1不再需要dims参数。

---

## 四、JUD侧改动

### 4.1 dim_adapter扩展

```python
# v3.1：完整接入dim1判定逻辑
def convert_to_factors(dim_results, tags, lifecycle):
    # ... 现有dim2-dim7逻辑 ...

    # dim1 signal因子（v3.1：完整接入）
    _sig = dim_results.get('signal')
    if _sig and isinstance(_sig, dict):
        _sig_judg = _sig.get('judgment', {})
        _sig_attr = _sig_judg.get('attribute', {})
        _sig_attr_code = str(_sig_attr.get('code', 'neutral'))

        # 属性分类 → direction（已有v3.0映射）
        _dim1_dir = _SIGNAL_CODE_DIRECTION.get(_sig_attr_code, 0)

        # 共振评分 → strength（v3.1新增）
        _sig_sd = _sig.get('status_description', {})
        _strength_text = _sig_sd.get('strength', '')
        _strength_score = 0.5
        if '/' in str(_strength_text):
            try:
                _strength_score = float(str(_strength_text).split('/')[0]) / 100
            except (ValueError, IndexError):
                pass

        # 衰减状态 → reliability（v3.1新增）
        _maintenance = _sig_judg.get('maintenance', {})
        _decay_status = _maintenance.get('status', 'unknown')
        _decay_reliability = {'healthy': 0.8, 'fading': 0.5, 'broken': 0.2}.get(_decay_status, 0.5)

        factors['signal'] = {
            'direction': _dim1_dir,
            'strength': _strength_score,
            'reliability': _decay_reliability,
            'evidence': [f'信号类型={_sig_attr_code}', f'衰减={_decay_status}'],
        }
```

### 4.2 reliability_assessor扩展

```python
# v3.1：接入dim1衰减检测结果
def assess_signal_reliability(dim1_result):
    """dim1信号可靠性 — 基于maintenance.decay_status"""
    if not dim1_result:
        return {'level': 'unknown', 'confidence': 0.5, 'evidence': ['dim1结果缺失']}

    judgment = dim1_result.get('judgment', {})
    maintenance = judgment.get('maintenance', {})
    decay_status = maintenance.get('status', 'unknown')

    level_map = {'healthy': '高', 'fading': '中', 'broken': '低'}
    confidence_map = {'healthy': 0.8, 'fading': 0.5, 'broken': 0.2}

    return {
        'level': level_map.get(decay_status, '中'),
        'confidence': confidence_map.get(decay_status, 0.5),
        'evidence': [f'衰减状态={decay_status}'],
    }
```

---

## 五、实施计划

| 阶段 | 任务 | 优先级 | 工时 | 依赖 |
|------|------|--------|------|------|
| Phase 1 | 修复调用顺序 + dim_adapter接入 + OUT直通 | P0 | 0.3天 | 无 |
| Phase 2 | dim1重构为数据调度层 + 判定逻辑迁移到JUD | P1 | 1.0天 | Phase 1 |
| **合计** | | | **1.3天** | |

---

## 六、风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Phase 1 dim_adapter接入不完整 | 中 | 低 | 逐字段对照390号方案v3.0映射表 |
| Phase 2 dim1重构影响现有调用方 | 中 | 中 | 保持evaluate()接口签名不变 |
| Phase 2 dim2-dim7读取context的改动量 | 低 | 低 | 渐进式改造，优先dim4/dim5 |
| 判定逻辑迁移后JUD判定不一致 | 低 | 低 | 对比dim1旧判定与JUD新判定结果 |

---

## 七、验证方案

```bash
# Phase 1验证
cd /Users/kalence/Desktop/01-A股股票分析系统
backend/.venv/bin/python3 -c "
from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dim_adapter import convert_to_factors
# 验证dim1在dim2-dim7之后调用
# 验证dim_adapter完整接入dim1判定逻辑
print('Phase 1验证通过')
"

# Phase 2验证
make check  # lint + typecheck + test
```

---

**文档编制日期**：2026-09-03
**编制依据**：dim1代码核查 + 389号/390号/392号方案审计结论 + 用户指示
**核查覆盖**：dim1_signal_engine.py(745行) + status_engine.py(831行) + dim_adapter.py(855行)
