# JUD环节代码实审报告

> 审计日期：2026-08-28
> 审计范围：`backend/app/opportunity_atlas/` + `backend/data_daemon.py` + `backend/config/status_engine.yaml`
> 引擎版本：v390（新管线）

---

## 1. 主流程

### 1.1 StatusEngine.__init__

**文件**: `backend/app/opportunity_atlas/status_engine.py` L84-L90

```python
def __init__(self, dm=None):
    if dm is None:
        from app.data import DataManager
        dm = DataManager()
    self.dm = dm
    self.cfg = get_status_engine_config()   # → status_config.py → load_yaml('status_engine.yaml')
    self.registry = get_signal_registry().get('signals', {})
```

- **依赖注入**: DataManager可外部传入，data_daemon中通过`_get_se()`单例复用
- **配置源**: `status_engine.yaml`，每次实例化时加载（非缓存）

### 1.2 evaluate() 主流程

**文件**: `backend/app/opportunity_atlas/status_engine.py` L96-L148

```
evaluate(ts_code, dim_results=None) → Optional[dict]

流程：
1. _load_tags(ts_code)           → 加载标签
2. _load_signals(ts_code)        → 加载信号
3. 无tags且无signals → return None
4. _signal_lifecycle()           → 信号生命周期
5. _build_dim_engine_results() 或复用外部传入的dim_results
6. Dim8SummaryEngine.evaluate()  → 摘要（失败降级None）
7. _convert_to_dims_format()     → 转旧格式dims
8. _apply_l0()                   → L0风险分级
9. 判断jud_engine_version:
   - v390 → _aggregate_v390()   → 新管线L1-L6
   - legacy → _aggregate()      → 旧管线
10. _detect_registered_signals() → 注册信号命中
11. _assemble()                  → 组装最终输出
```

**性能监控**: evaluate耗时>500ms时记录日志（387号§七-H2）

### 1.3 _aggregate_v390() L1-L6调用链

**文件**: `backend/app/opportunity_atlas/status_engine.py` L551-L699

```
_aggregate_v390(tags, dims, l0, lifecycle, dim_results, ts_code) → dict

调用链：
  L1: dim_adapter.convert_to_factors(dim_results, tags)
       → dims_factor: {dim_name: {direction, strength, evidence, ...}}

  L2: reliability_assessor.assess(dims_factor, dim_results)
       → reliability: {dim_name: float(0-1)}

  L3: consensus_engine.compute(dims_factor, reliability, family_weights, emotion_phase)
       → consensus: {consensus_rate, direction, bull_score, bear_score, group_details}

  L4: conflict_matrix.detect(dims_factor, tags, dim_results, consensus_rate)
       → conflict: {fatal_to_veto, warn_for_semantic, semantic_type, semantic_adjustment}

  ⚡ 硬否决检查: l0.hard_veto → 直接返回avoid
  ⚡ L4致命冲突: conflict.fatal_to_veto → 直接返回wait

  L5: factor_arbiter.arbitrate(consensus, conflict, tags, dims_factor, reliability)
       → arb_result: {opportunity_state, final_score, state_evidence}

  L6: advice_engine.compute_advice(final_score, dims_factor, l0, dim_results, ts_code, entry_price)
       → advice: {max_position_ratio, stop_loss_price, target_price, ...}

  后处理：
  - 背景周期过滤（周线down + 日线看多共识<80% → 降级wait）
  - hold_only覆盖（信号已延伸 → 不新开仓）
  - 返回合并结构
```

### 1.4 _assemble() 输出结构

**文件**: `backend/app/opportunity_atlas/status_engine.py` L786-L876

**输入**: ts_code, dims, lifecycle, l0, l2, hits, dim_engine_results

**输出字段**:
| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | TEXT | 股票代码 |
| dim_states | JSON TEXT | 维度状态(九维) |
| status_bar | TEXT | 状态条文本 |
| opportunity_state | TEXT | enter/light/wait/avoid |
| state_evidence | JSON TEXT | 状态依据列表 |
| conflict_evidence | JSON TEXT | 冲突证据列表 |
| consensus_rate | REAL | 共识率 |
| direction | TEXT | bull/bear/neutral |
| l0 | JSON TEXT | L0风险分级结果 |
| lifecycle | JSON TEXT | 信号生命周期 |
| advice_params | JSON TEXT | 操作建议参数(扩展) |
| signals | JSON TEXT | 命中的注册信号 |
| dim_engine_results | JSON TEXT | 维度引擎原始结果 |
| final_score | REAL | 390号新字段：最终评分 |
| semantic_type | TEXT | 390号：语义类型 |
| reliability_summary | JSON TEXT | 390号：可靠性汇总 |
| consensus_detail | JSON TEXT | 390号：族级共识详情 |

**仓位计算逻辑**:
```
base = 0.6(enter/light) | 0.2(wait) | 0.0(avoid)
position_ratio = base × l0.position_coeff
position_ratio = min(position_ratio, l0.emotion_position_cap)  # 情绪上限

# 2%风险规则
risk_position = max_loss / risk_per_share × entry / account
risk_position = min(risk_position, 0.30)
position_ratio = min(position_ratio, risk_position)
```

**advice_params JSON结构**:
```json
{
  "max_position_ratio": 0.36,
  "hold_only": false,
  "soft_risks": ["distributing"],
  "hard_veto": false,
  "stop_loss_price": 15.20,
  "target_price": 22.50,
  "risk_reward_ratio": 2.1,
  "invalidation_conditions": "跌破14.80元",
  "atr_pct": 0.45,
  "temperature": 62.5,
  "entry_zone": "15.20-15.80",
  "target_zone": "20.00-22.50",
  "risk_budget_position": 0.28,
  "risk_budget_account": 1000000.0,
  "risk_budget_pct": 0.02,
  "final_score": 65.3,
  "semantic_type": "确认型",
  "consensus_detail": {...},
  "conflict_summary": {"fatal": [], "warn": [...]},
  "reliability_summary": {...}
}
```

### 1.5 apply_advice_params()

**文件**: `backend/app/opportunity_atlas/status_engine.py` L879-L909

**用途**: 实时操作建议轻量套算（日频advice_params + 现价）

```python
apply_advice_params(params, price, df=None, rr_gate=1.0) → dict
```

**逻辑**:
1. 无参数 → wait
2. hard_veto → avoid
3. hold_only → wait（不可新开仓）
4. 盈亏比门禁：rr = (resistance - price) / (price - support)，rr < 1 → position × 0.5
5. 返回 `{state, max_position_ratio, reason}`

---

## 2. L1-L6各层组件详细分析

### 2.1 L1: dim_adapter.py → convert_to_factors()

**文件**: `backend/app/opportunity_atlas/dim_adapter.py` L443-L855 (855行)

**函数签名**:
```python
def convert_to_factors(dim_results: dict, tags: dict) -> dict
```

**输入**:
- `dim_results`: 维度引擎预计算结果 `{dim_name: engine_output}`
- `tags`: pre_feat_cache扁平化标签

**输出**:
```python
dims_factor: dict[str, dict] = {
    dim_name: {
        'direction': int,    # -1看空 / 0中性 / 1看多
        'strength': float,   # 信号强度 [0.0, 1.0]
        'evidence': list,    # 支撑证据字符串列表
        # 各维度特有extra字段...
    }
}
```

**12个维度转换逻辑**:

| 维度 | 方向来源 | 强度算法 | 特殊修正 |
|------|----------|----------|----------|
| signal | signal.attribute.code → _SIGNAL_CODE_DIRECTION | 固定0.5 | — |
| structure | judgment.overall_direction | 0.4×chanlun_str + 0.4×cross_score + 0.2×cont_val | 123_buy_breakout增强; 欲病×0.7 |
| vp | state_machine_direction(BUY/SELL/HOLD) | 0.7×sm_confidence + 0.3×resonance_norm | multi_timeframe冲突→归零 |
| chip_fund | phase → ENGINE_STATE_TO_CN → DIM_DIRECTION | phase_confidence | pde_conflict×0.7 |
| emotion | market_phase → _EMOTION_DIRECTION | abs(temperature-50)/50 | bociasi共振±0.15; slow修正×0.6 |
| risk | risk_level + rr_value | rr/3.0 | atr_pct>0.8×0.6 |
| valuation | composite_rating | 0.6×cr_strength + 0.4×deviation_norm | dividend>4%+0.1; rev>20%+0.1 |
| time | emotion.time_rhythm | 固定0.5 | 变盘→+1; 延伸→-1 |
| finance | dim7.judgment.fina_health | 固定0.5 | pass→+1; fail→-1 |
| event | tags.catalyst_event | 固定0.5 | breakout→+1; regulatory/lhb→-1 |
| factor | dim7.potential_score | ps/100 | ≥70→+1; ≤30→-1 |
| position | tags.price_position → DIM_DIRECTION | 固定0.5 | — |
| signal_confirm | tags.right_side_confirm | 固定0.5 | 强确认→+1; 否决→-1 |

### 2.2 L2: reliability_assessor.py → assess()

**文件**: `backend/app/opportunity_atlas/reliability_assessor.py` L294-L344 (345行)

**函数签名**:
```python
def assess(dims_factor: dict, dim_results: dict) -> dict
```

**输出**: `{dim_name: float}` — 每个维度的可靠性分数 (0-1)

**常量**:
- `_DEFAULT_RELIABILITY = 0.5`
- `_KNOWN_DIMS = {signal, structure, volume_price, chip_fund, emotion, risk, valuation}`
- `_DEFAULT_DIMS = {finance, event, time, factor, signal_confirm, position}`

**评估器注册表** `_DIM_ASSESSORS`:
| 维度 | 评估器 | 算法概要 |
|------|--------|----------|
| signal | _assess_signal | 基于signal状态映射 |
| structure | _assess_structure | consistency/stage_confidence + 周线方向修正 |
| volume_price | _assess_volume_price | 票差修正(pde_vote_ratio) |
| chip_fund | _assess_chip_fund | — |
| emotion | _assess_emotion | bociasi_slow_confidence + sector_heat |
| risk | _assess_risk | atr区间映射(<0.3→0.9, >0.7→低) |
| valuation | _assess_valuation | — |

**降级**: _DEFAULT_DIMS → 固定0.5; 未知维度 → 0.5; 单维异常 → 0.5不影响其他维度

### 2.3 L3: consensus_engine.py → compute() + merge_family()

**文件**: `backend/app/opportunity_atlas/consensus_engine.py` (358行)

#### merge_family()

**签名**:
```python
def merge_family(dim_scores, dim_reliabilities, family_dims, dim_strengths=None) → (direction, strength, has_conflict)
```

**算法**:
1. 收集有效(direction, strength, reliability)三元组
2. 分离bull/bear/neutral
3. 各方向内：reliability加权平均strength
4. 多数方向投票（count多者胜；平票取strength高者）
5. 冲突惩罚：has_conflict → majority_strength × 0.6
6. 无冲突：取多数方向的strength

#### compute()

**签名**:
```python
def compute(dims_factor, reliability, weights, emotion_phase='normal') → dict
```

**6族映射** `GROUP_MAPPING`:
```python
{
    'main_behavior':    ['chip_fund'],                    # 主力行为族
    'structure_trend':  ['structure', 'signal', 'time', 'position', 'signal_confirm'],  # 结构趋势族
    'volume_price':     ['vp'],                           # 量价状态族
    'valuation_quality':['valuation', 'finance'],         # 估值质量族
    'environment':      ['emotion', 'event', 'factor'],   # 环境族
    'risk':             ['risk'],                          # 风险族
}
```

**6阶段权重** `STATE_WEIGHTS`（按emotion_phase切换）:

| 族 | ice | ebb | normal | recovery | positive | climax |
|---|---|---|---|---|---|---|
| main_behavior | 0.15 | 0.20 | 0.25 | 0.25 | 0.20 | 0.15 |
| structure_trend | 0.15 | 0.20 | 0.20 | 0.20 | 0.20 | 0.15 |
| volume_price | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |
| valuation_quality | 0.30 | 0.20 | 0.15 | 0.15 | 0.15 | 0.10 |
| environment | 0.10 | 0.10 | 0.10 | 0.10 | 0.15 | 0.20 |
| risk | 0.10 | 0.10 | 0.10 | 0.10 | 0.10 | 0.20 |

**输出**:
```python
{
    'consensus_rate': float,      # [-1, 1] 最终共识率
    'raw_consensus_rate': float,  # neutral cap前
    'reliability_factor': float,  # [0, 1] 有效权重占比
    'direction': str,             # 'bull'/'bear'/'neutral'
    'bull_score': float,
    'bear_score': float,
    'group_details': dict,        # 族级详情
}
```

**关键规则**:
- neutral维度占比>60% → consensus_rate绝对值cap到0.5
- direction阈值: >0.01→bull, <-0.01→bear, else neutral

### 2.4 L4: conflict_matrix.py → detect()

**文件**: `backend/app/opportunity_atlas/conflict_matrix.py` L51-L330 (330行)

**函数签名**:
```python
def detect(dims_factor, tags, dim_results, consensus_rate=0.5, vol_ratio=1.0) → dict
```

**输出**:
```python
{
    'fatal_to_veto':       List[str],   # 致命冲突 → 强制wait/avoid
    'warn_for_semantic':   List[str],   # 警告冲突 → 语义降级
    'semantic_type':       str,         # 矛盾型/追高警示型/确认型/初现型
    'semantic_adjustment': float,       # 评分乘数
    'all_conflicts':       List[str],   # 所有冲突
}
```

**14条冲突规则**:

| 编号 | 类型 | 触发条件 | 级别 | 语义 |
|------|------|----------|------|------|
| C1 | 欲病+强确认 | chanlun_phase含'欲病' + right_side_confirm='强确认' | warn | 方向未定，过度追入风险 |
| C2 | 活跃下跌+结构看多 | stage_name=DOWNTREND_ACTIVE + structure_direction=1 | warn | 趋势矛盾 |
| C2b | 多时间框架分歧 | 日线up+周线down 或 日线down+周线up | warn | 多时间框架趋势分歧 |
| C3 | 冰点+低估值+顶部背离 | emotion=-1 + valuation=1 + vp_divergence='top' | warn | ice+low_valuation+top_divergence |
| C4 | 筹码吸筹+拥挤度高 | phase∈(building,lifting) + crowding∈(HIGH) | warn | 跟风过热风险 |
| C4+ | 主力出货+吸筹 | retail含'主力出货' + phase∈(building,lifting) | **fatal** | 严重矛盾，资金出逃 |
| C4++ | 单峰密集+高拥挤+高获利 | cost_concentration='单峰密集' + HIGH + cost_profit_ratio>0.7 | **fatal** | 集中兑现风险极高 |
| C5 | 高波动低收益 | ATR>0.7 + rr<1.0 + consensus<0.5 | warn | 高波动低收益+市场分歧 |
| C6 | 趋势背驰+123突破 | divergence_type='趋势背驰' + trend_structure_signal='123_buy_breakout' | fatal(warn) | strength>0.7→fatal, ≤0.7→warn |
| C7 | 高风险+确认 | risk_level∈(高,极高) + right_side_confirm∈(强确认,基础确认) | **fatal** | 风险-收益严重失衡 |
| C8 | 高获利+无主力+确认 | cost_profit_ratio>0.8 + main_force='none' + confirm | **fatal** | 高位接盘风险极高 |
| C9 | 监管事件 | catalyst_event='regulatory' | **fatal** | 强制回避（冗余安全检查） |
| C10 | 趋势背驰+高共识 | divergence_type='趋势背驰' + consensus>0.7 | warn | 背驰信号价值更高 |
| C11 | 量价顶部背离+结构看多 | dim3_divergence='top' + structure_direction=1 | fatal(warn) | vol_ratio<0.5→fatal |
| C12 | 结构风险+结构看多 | risk_notes非空 + structure_direction=1 | warn | 风险因素未消除 |
| C13 | 隐含盈亏比偏差 | implied_rr与计算值偏差>0.5 | warn | 支撑/压力度量不一致 |
| C14 | 估值锚定背离 | asset_anchor≤-1 + earnings_anchor≥1 | warn | 估值锚定逻辑矛盾 |

**语义类型识别** (优先级从高到低):
```
1. fatal≥1 或 warn≥3 → 矛盾型 (adjustment=0.5)
2. consensus≥0.8 且 接近前高(>-3%) → 追高警示型 (0.7)
3. aligned≥4 且 consensus≥0.7 → 确认型 (1.15)
4. aligned=2 且 divergence≤0.7 → 初现型 (1.0)
5. 默认 → 初现型 (1.0)
```

### 2.5 L5: factor_arbiter.py → arbitrate()

**文件**: `backend/app/opportunity_atlas/factor_arbiter.py` L65-L218 (219行)

**函数签名**:
```python
def arbitrate(consensus, conflict, tags, dims_factor, reliability) → dict
```

**输出**:
```python
{
    'opportunity_state': str,    # enter/light/wait/avoid
    'final_score': float,        # 0-100
    'state_evidence': list[str],
    'conflict_evidence': list[str],
}
```

**6步评分流水线**:

| Step | 操作 | 公式 |
|------|------|------|
| 1a | right_side_confirm=否决 → avoid | 直接返回 |
| 1b | catalyst=regulatory → avoid | 直接返回 |
| 1c | fatal_to_veto非空 → wait | 直接返回 |
| 2 | 基础分 | `base = consensus_rate × 100` (clamped [0,1]) |
| 3 | 语义调整 | `adjusted = base × semantic_adjustment` (clamped [0.1,3.0]) |
| 4 | RSC门控 | `final = adjusted × rsc_multiplier` |
| 5 | 情绪极端修正 | strength>0.6 → `final × 0.85` |
| 6 | 状态映射 | `_THRESHOLDS` |

**常量**:
```python
_RSC_MULTIPLIER = {'强确认': 1.0, '基础确认': 0.8, '未确认': 0.5}
_RSC_DEFAULT = 0.5
_EMOTION_EXTREME_THRESHOLD = 0.6
_EMOTION_PENALTY = 0.85
_THRESHOLDS = [(70, 'enter'), (55, 'light'), (30, 'wait')]  # <30 → avoid
```

### 2.6 L6: advice_engine.py → compute_advice()

**文件**: `backend/app/opportunity_atlas/advice_engine.py` L23-L153 (153行)

**函数签名**:
```python
def compute_advice(final_score, dims_factor, l0, dim_results, ts_code, entry_price=None) → dict
```

**8步仓位模型**:

| Step | 操作 | 规则 |
|------|------|------|
| 1 | 基础仓位 | score≥70→0.6, ≥55→0.4, ≥30→0.1, <30→0.0 |
| 2 | L0软风险连乘 | position × l0.position_coeff |
| 3 | 情绪阶段上限 | min(position, emotion_cap) |
| 4 | 风险预算约束 | 2%规则: max_loss / risk_per_share × entry / account → min(0.30) |
| 5 | 波动率调整 | atr_pct>0.8 → position×0.6 |
| 6 | 盈亏比调整 | position × min(rr/2.0, 1.0) |
| 7 | 距防守位调整 | dist_to_support>-2% → position×0.6 |
| 8 | 单票上限 | min(position, 0.30) |

**输出字段** (合并到advice_params):
- max_position_ratio, hold_only, soft_risks, hard_veto
- stop_loss_price, target_price, risk_reward_ratio
- entry_zone, target_zone
- invalidation_conditions, temperature, atr_pct
- risk_budget_position, final_score

---

## 3. 配置系统

### 3.1 status_engine.yaml 完整内容

**文件**: `backend/config/status_engine.yaml` (56行)

```yaml
version: 1
jud_engine_version: "v390"    # v390=new_pipeline, legacy=old

consensus:
  enter_threshold: 0.67       # 入场门槛(≥2/3)
  bearish_strong: 0.67        # 强看空→avoid
  color_high: 0.70            # 深蓝
  color_low: 0.67             # 浅蓝下限
  neutral_is_zero: true       # 中性不稀释共识

dimension_weights:             # 维度权重(默认等权1.0)
  valuation/structure/position/chip_fund/emotion/finance/event/time/risk/factor: 1.0

conflict_rules:
  enabled: true
  rules: [trend_vs_multi, high_profit_no_flow, distributing_vs_confirm,
          risk_high_vs_confirm, high_profit_no_presence, deep_valuation_confirm]

l0:
  hard_risks: [regulatory, st, delist]
  soft_risk_coeff:
    fina_weak: 0.5, fina_fail: 0.5, distributing: 0.7,
    low_liquidity: 0.7, valuation_moderate: 0.5, valuation_mild: 0.8,
    deep_position_cap: 0.3
  emotion_position_cap:
    ice: 0.10, ebb: 0.30, normal: 0.60, recovery: 0.60, positive: 0.80
  hold_only_stages: ["已延伸"]
```

### 3.2 配置读取逻辑

**文件**: `backend/app/services/status_config.py`

```python
def get_status_engine_config() -> dict:
    return load_yaml('status_engine.yaml')
```

- `load_yaml()` 带缓存机制（`invalidate_config_cache()`可清缓存）
- StatusEngine.__init__中每次调用 `get_status_engine_config()` 加载
- `dimension_weights` 在390新管线中**未直接消费**（权重由weight_engine动态生成后经`_map_dim_weights_to_family`映射）

---

## 4. 管道集成

### 4.1 JUD步骤执行入口

**文件**: `backend/data_daemon.py` L4581-L4589

```python
# 前置条件：SIG步骤完成
if not _all_steps_done(status, ['SIG']):
    return

# JUD管道
if status.get('JUD', {}).get('status') != 'done':
    def _jud_build(_codes):
        _build_status_snapshot(_codes)       # 1. 状态快照
        _jud_enrich_with_meta(_codes)         # 2. 元数据增强
        _build_treemap_snapshot(_codes)       # 3. treemap快照
    _run_pipeline_step(today, 'JUD', _jud_build, codes)
    return
```

### 4.2 _build_status_snapshot()

**文件**: `backend/data_daemon.py` L4044-L4164

```
流程：
1. 获取StatusEngine单例（_get_se()）
2. 读取trade_date（MAX(trade_date) FROM daily_cache）
3. 预取dim_results_json（strategy_signal_detail → 避免JUD重复计算）
4. 并行评估（ThreadPoolExecutor max_workers=8）
   - 每只股票调用 engine.evaluate(code, dim_results=dim_cache.get(code))
5. 按序写入status_snapshot_new表
6. 生成summary_text（greens/reds/direction）
7. 原子表替换：DROP status_snapshot → ALTER RENAME
```

**status_snapshot表结构**:
```sql
CREATE TABLE status_snapshot_new (
    ts_code TEXT PRIMARY KEY,
    snapshot_date TEXT,
    trade_date TEXT,
    dim_states TEXT,            -- JSON: 九维状态
    status_bar TEXT,            -- 状态条文本
    opportunity_state TEXT,     -- enter/light/wait/avoid
    state_evidence TEXT,        -- JSON: 状态依据
    conflict_evidence TEXT,     -- JSON: 冲突证据
    consensus_rate REAL,        -- 共识率
    direction TEXT,             -- bull/bear/neutral
    l0 TEXT,                    -- JSON: L0风险
    lifecycle TEXT,             -- JSON: 生命周期
    advice_params TEXT,         -- JSON: 操作建议参数
    summary_text TEXT,          -- 摘要文本
    one_liner_detail TEXT,      -- 七维透传(OUT步骤填充)
    dim_engine_results TEXT,    -- JSON: 引擎原始结果
    created_at TEXT
)
```

### 4.3 _jud_enrich_with_meta()

**文件**: `backend/data_daemon.py` L3458-L3553

```
在_build_status_snapshot之后、_build_treemap_snapshot之前调用。

流程：
1. _compute_opportunity_meta → opportunity_type/label/profile/evidence_count/entry/exit
2. PotentialEngine.compute_potential → signal_strength/potential_breakdown
3. _check_right_side_confirm → right_side_confirm/confirm_evidence
4. 写入模块级 _jud_meta_cache 供 treemap_snapshot 读取
```

### 4.4 _build_treemap_snapshot()

**文件**: `backend/data_daemon.py` L3555-L3812

```
流程：
1. 从 daily_cache/daily_basic_cache/opportunity_tags_cache 提取最新数据
2. 叠加 _jud_meta_cache（_jud_enrich_with_meta预计算）
3. 读取 seven_dim_json（strategy_signal_detail）
4. 读取 status_snapshot 的 consensus_rate/conflict/opportunity_state/state_evidence
5. 原子表替换写入 treemap_snapshot
```

**treemap_snapshot表结构** (47列):
```sql
CREATE TABLE treemap_snapshot_new (
    ts_code TEXT PRIMARY KEY,
    name TEXT, industry TEXT,
    close REAL, pct_chg REAL, total_mv REAL, trade_date TEXT,
    open REAL, high REAL, low REAL, amplitude REAL,
    pe REAL, pb REAL,
    amount REAL, turnover_rate REAL, circ_mv REAL,
    signal_strength REAL, valuation_level TEXT, valuation_deviation REAL,
    main_force_phase TEXT, phase_confidence REAL,
    sentiment_phase TEXT, sector_heat TEXT, fina_health TEXT,
    opportunity_type TEXT, trend_alignment TEXT, price_position TEXT,
    fund_flow TEXT, capital_nature TEXT, chip_concentration TEXT,
    volatility_level TEXT, dividend_yield REAL, composite_rating REAL,
    opportunity_label TEXT, evidence_count INTEGER,
    right_side_confirm TEXT, confirm_evidence TEXT, opportunity_profile TEXT,
    entry_signals TEXT, exit_conditions TEXT,
    consensus_rate REAL,           -- 来自status_snapshot
    conflict TEXT,                 -- 来自status_snapshot
    main_force_presence TEXT,
    presence_evidence TEXT,
    opportunity_state TEXT,        -- 来自status_snapshot
    state_evidence TEXT,           -- 来自status_snapshot
    seven_dim_report TEXT,         -- 来自strategy_signal_detail.seven_dim_json
    snapshot_date TEXT DEFAULT (date('now'))
)
```

### 4.5 错误处理和重试机制

**文件**: `backend/data_daemon.py` L4590-L4596

```python
if _has_failed(status, ['JUD']):
    for sid in ['JUD']:
        if status.get(sid, {}).get('status') == 'failed':
            rc = status[sid].get('retry_count', 0)
            if rc < 3:
                _ecm.conn.execute(
                    "UPDATE pipeline_status SET status='pending', retry_count=? ...")
```

- **最大重试次数**: 3次
- **重试策略**: failed → pending (retry_count+1) → 重新执行
- **evaluate()内部**: 每只股票独立try/except，单只失败不影响其他
- **dim8降级**: Dim8SummaryEngine失败 → summary=None，继续执行

---

## 5. 输出数据结构

### 5.1 status_snapshot 完整列定义

见 4.2节，共17列。

### 5.2 treemap_snapshot SIG相关字段

见 4.4节，共47列。与JUD直接相关的字段：
- `consensus_rate` / `conflict` / `opportunity_state` / `state_evidence`：来自status_snapshot
- `seven_dim_report`：来自strategy_signal_detail.seven_dim_json

### 5.3 advice_params JSON结构

见 1.4节末尾的JSON示例。

### 5.4 前端字段映射

**treemap_snapshot → 前端**:
- 基础行情: name, industry, close, pct_chg, total_mv, pe, pb
- JUD核心: opportunity_state, consensus_rate, conflict, state_evidence, opportunity_type, signal_strength
- 操作建议: entry_signals, exit_conditions, right_side_confirm

**status_snapshot → 前端**:
- 状态: opportunity_state, status_bar, direction, consensus_rate
- 详情: state_evidence, conflict_evidence, l0, lifecycle, advice_params
- 分析: dim_states, dim_engine_results, final_score, semantic_type

---

## 6. 降级策略

### 6.1 引擎缺失时的降级路径

| 场景 | 降级行为 |
|------|----------|
| dim_results为空 | _build_dim_engine_results()从tags构建 |
| Dim8SummaryEngine失败 | summary=None，不阻塞主流程 |
| weight_engine失败 | weights_7dim={}，_map_dim_weights_to_family返回默认等权 |
| 单维度评估失败(L2) | 该维度reliability=0.5，其他维度不受影响 |
| dim_adapter单维度转换失败 | direction=0, strength=0.3(保守默认) |
| conflict_matrix无数据 | 所有输入做or:{}空化处理，不触发任何冲突规则 |
| consensus_engine无效emotion_phase | 抛ValueError（调用方需确保合法性） |
| apply_advice_params无参数 | 返回{state:'wait', max_position_ratio:0.0} |
| evaluate()整体异常 | 返回None，_build_status_snapshot跳过该股票 |

### 6.2 配置缺失时的默认值

| 配置项 | 默认值 | 来源 |
|--------|--------|------|
| jud_engine_version | 'legacy' | status_engine.py L132 |
| l0.soft_risk_coeff.* | 各值硬编码默认(0.5/0.7等) | status_engine.py L365-380 |
| l0.emotion_position_cap.* | ice=0.10, ebb=0.30, normal=0.60, recovery=0.60, positive=0.80 | status_engine.py L389-394 |
| l0.hold_only_stages | ['已延伸'] | status_engine.py L382 |
| consensus.enter_threshold | 0.67 | status_engine.yaml L11 |
| dimension_weights.* | 1.0(等权) | status_engine.yaml L17-27 |

### 6.3 fatal/warn冲突的处理方式

| 级别 | 处理 |
|------|------|
| L0硬否决(hard_veto=True) | _aggregate_v390直接返回avoid，跳过L3-L6 |
| L4致命冲突(fatal_to_veto非空) | _aggregate_v390直接返回wait，跳过L5-L6 |
| L5硬否决(1a/1b) | arbitrate直接返回avoid(final_score=0) |
| L5致命冲突(1c) | arbitrate直接返回wait(final_score=0) |
| 语义类型=矛盾型(adjustment=0.5) | final_score×0.5，大幅降级 |
| 语义类型=追高警示型(adjustment=0.7) | final_score×0.7 |
| 语义类型=确认型(adjustment=1.15) | final_score×1.15，加分 |
| hold_only=True | 最终position=0.0(不可新开仓) |
| 背景周期过滤 | 周线down + 日线看多共识<80% → 强制wait |

---

## 附录：文件清单

| 文件 | 行数 | 核心符号 |
|------|------|----------|
| `app/opportunity_atlas/status_engine.py` | ~1100 | StatusEngine, apply_advice_params, build_status_engine |
| `app/opportunity_atlas/dim_adapter.py` | 855 | convert_to_factors, convert_to_dims_format, DIM_DIRECTION |
| `app/opportunity_atlas/reliability_assessor.py` | 345 | assess, _DIM_ASSESSORS |
| `app/opportunity_atlas/consensus_engine.py` | 358 | compute, merge_family, GROUP_MAPPING, STATE_WEIGHTS |
| `app/opportunity_atlas/conflict_matrix.py` | 330 | detect (14条冲突规则) |
| `app/opportunity_atlas/factor_arbiter.py` | 219 | arbitrate, _THRESHOLDS |
| `app/opportunity_atlas/advice_engine.py` | ~600 | compute_advice, _geometric, build_operation_advice |
| `app/opportunity_atlas/arbiter.py` | ~200 | arbitrate (旧版规则优先级，321号) |
| `app/services/status_config.py` | ~50 | get_status_engine_config, load_yaml |
| `config/status_engine.yaml` | 56 | 全量配置 |
| `data_daemon.py` | 5349 | _build_status_snapshot, _jud_enrich_with_meta, _build_treemap_snapshot |
