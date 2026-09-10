---
title: JUD管线接入与signal消费链补齐方案
type: 架构方案
date: 2026-09-08
version: v1.0
status: 待实施
related:
  - 390号-JUD环节多因子决策引擎架构方案
  - 409号-dim1数据质量门禁层改造方案
  - 411号-维度引擎统一实施计划（407-410整合）
  - 412号-SIG到RAW迁移实施状态审计与消费者接入补充方案
  - 417号-COL采集端深度数据清洗增强方案
---

# 418号 — JUD管线接入与signal消费链补齐方案

---

## 一、问题背景

### 1.1 问题1：`jud_engine_version: "v390"` 配置与代码脱节（HIGH）

**现状**：`backend/config/status_engine.yaml` 声明 `jud_engine_version: "v390"`，但 `backend/app/opportunity_atlas/status_engine.py` 中**没有任何代码读取该配置**：

- 主流程 `evaluate()` L105 直接调用旧管线 `self._aggregate(...)`（`arbiter.arbitrate` 加权投票），无版本分支
- v390 组件（`consensus_engine.compute` / `conflict_matrix.detect` / `factor_arbiter.arbitrate` / `advice_engine.compute_advice`）**全部已实现且签名完整**（390号方案 Phase 1-3 产出），但生产代码中几乎无调用方（仅 `cross_validate.py` 引用 advice_engine）
- `backend/docs/JUD环节代码实审报告.md`（8-28 审计）声称存在 `_aggregate_v390`（L551-L699，L1-L6 调用链），但 `git log -S "_aggregate_v390"` **无任何提交**——该函数从未存在于代码库，实审报告与实际代码状态不符

**影响**：用户/运维期望 v390 多因子管线生效，实际运行的是 legacy 加权投票。390号方案的 final_score / semantic_type / reliability_summary / consensus_detail 等输出字段（§1.4 表）从未产出。

### 1.2 问题2：dim1 门禁结果与 JUD 消费链不匹配（MED）

**现状**：411号 Phase 4 后，`results['signal']` = dim1 门禁结果 `{data_context, status_quality}`（**无 `judgment.attribute`**）。而 JUD 消费链期望旧 dim1 格式：

| 消费方 | 读取路径 | dim1门禁输出下实际拿到 |
|--------|---------|----------------------|
| `dim_adapter.convert_to_factors` L468-478 | `dim_results['signal']['judgment']['attribute']['code']` | 无 → `_sig_attr_code` 恒 `'neutral'` → **direction 恒 0** |
| `reliability_assessor._assess_signal` L57-69 | `dim_results['signal']['judgment']['maintenance']['status']` | 无 → 恒默认 0.5 |
| dim8 `_extract_dim_direction(dim_results, 'signal')` | `dim_results['signal']['judgment']['overall_direction']` | 无 → signal 方向恒 0，dim8 L166/L175 冲突检测失效 |
| status_engine `_convert_to_dims_format` L414-437 | **已改用 `signal_analyzer.classify_attribute` 生成 `dims['signal_confirm']`** | ✅ 正常（唯一正确消费方） |

**根因**：411号 Phase 4 将 signal_analyzer 的完整输出放在 `results['signal_analysis']` 键，但 JUD 层（dim_adapter / reliability_assessor / dim8）读取的是 `results['signal']` 键——**键名错位**。

---

## 二、方案目标

1. **接入 v390 管线**：status_engine 真实消费 `jud_engine_version` 配置，实现 `_aggregate_v390`（L1-L6 调用链），与 legacy `_aggregate` 并存，可配置切换
2. **修复 signal 消费链**：signal_analyzer 输出接入 JUD 消费链，dim_adapter / reliability_assessor / dim8 恢复 signal 维度数据
3. **保持兼容**：legacy 路径完整保留；dim1 门禁职责不变；输出 schema 向后兼容

---

## 三、详细设计

### 3.1 问题2修复：signal 消费链键名对齐（先行，无风险）

**方案**：在 `_build_dim_engine_results` Step 3 中，将 `analyze_signal` 的输出**同时写入 `results['signal']` 的判定子结构**，而不是单独放 `signal_analysis` 键。

```python
# status_engine.py _build_dim_engine_results() Step 3 改造（当前 L279-280）
signal_analysis = analyze_signal(dims_for_signal, tags, lifecycle or {})
results['signal_analysis'] = signal_analysis          # 保留（兼容既有消费者）

# 新增：将signal判定结果并入 results['signal']（dim1门禁结果之上叠加judgment）
if signal_analysis:
    _sig = results.get('signal') or {}
    # signal_analysis 含 status_description / judgment / audit
    results['signal'] = {**_sig, **signal_analysis}
```

**效果**：

| 消费方 | 改造后读取 | 结果 |
|--------|-----------|------|
| dim_adapter L468-478 | `results['signal']['judgment']['attribute']['code']` | ✅ 恢复 7 类属性 → direction 映射 |
| reliability_assessor `_assess_signal` | `results['signal']['judgment']['maintenance']['status']` | ✅ 恢复衰减状态 → reliability |
| dim8 `_extract_dim_direction` | `results['signal']['judgment']['overall_direction']` | ✅ 恢复 signal 方向 |

**降级保护**：dim1 门禁失败（`data_context=None`）时 signal_analysis 仍由 dim2-dim7 的 dims_for_signal 生成，signal 判定不依赖门禁成功 → 端到端降级策略（409号 §5.6）天然满足。

**说明**：`results['signal']` 键名保持不变（仍为 dim1 门禁结果占位），仅叠加 judgment 子结构，不影响 `_assemble` 中 `dim_engine_results` 序列化结构。

### 3.2 问题1修复：v390 管线接入（核心）

#### a) 实现 `_aggregate_v390`（对齐实审报告 L1-L6 调用链 + 390号方案签名）

```python
# status_engine.py 新增方法（放在 _aggregate 之后）
def _aggregate_v390(self, tags: dict, dims: dict, l0: dict, lifecycle: dict,
                    dim_results: dict, ts_code: str) -> dict:
    """390号方案 v390 多因子决策管线（L1-L6）

    配置 jud_engine_version: "v390" 时由 evaluate() 调用。
    """
    from app.opportunity_atlas.dim_adapter import convert_to_factors
    from app.opportunity_atlas.reliability_assessor import assess
    from app.opportunity_atlas.consensus_engine import compute as consensus_compute
    from app.opportunity_atlas.conflict_matrix import detect as conflict_detect
    from app.opportunity_atlas.factor_arbiter import arbitrate as factor_arbitrate
    from app.opportunity_atlas.advice_engine import compute_advice

    # L1: 维度因子提取
    dims_factor = convert_to_factors(dim_results or {}, tags)

    # L2: 可靠性评估
    reliability = assess(dims_factor, dim_results or {})

    # L3: 共识聚合（weights 取 MARKET_REGIME_WEIGHTS[regime]）
    regime = self._detect_market_regime(tags, dims)
    weights = self.MARKET_REGIME_WEIGHTS.get(regime, self.MARKET_REGIME_WEIGHTS['ranging'])
    emotion_phase = str(tags.get('emotion_phase', 'normal'))
    try:
        consensus = consensus_compute(dims_factor, reliability, weights, emotion_phase)
    except Exception:
        consensus = {'consensus_rate': 0.0, 'direction': 'neutral',
                     'bull_score': 0.0, 'bear_score': 0.0, 'group_details': {}}

    # L4: 冲突检测
    try:
        conflict = conflict_detect(dims_factor, tags, dim_results or {}, consensus.get('consensus_rate', 0.0))
    except Exception:
        conflict = {'fatal_to_veto': [], 'warn_for_semantic': [],
                    'semantic_type': '', 'semantic_adjustment': 1.0, 'all_conflicts': []}

    # ⚡ 硬否决检查（对齐 legacy _aggregate 行为）
    if l0.get('hard_veto'):
        return self._v390_result('avoid', [l0.get('hard_reason', 'L0a 硬否决')],
                                 consensus, conflict, 0.0, reliability)

    # ⚡ L4 致命冲突 → wait
    if conflict.get('fatal_to_veto'):
        return self._v390_result('wait', conflict['fatal_to_veto'],
                                 consensus, conflict, 30.0, reliability)

    # L5: 多因子仲裁
    try:
        arb_result = factor_arbitrate(consensus, conflict, tags, dims_factor, reliability)
    except Exception:
        arb_result = {'opportunity_state': 'wait', 'final_score': 50.0,
                      'state_evidence': ['L5仲裁不可用'], 'conflict_evidence': []}

    # L6: 操作建议（对齐 _assemble advice_params 语义）
    advice = {}
    try:
        entry_price = None
        df = (dim_results.get('daily_df') or {})
        if hasattr(df, 'empty') and not df.empty and 'close' in df.columns:
            entry_price = float(df['close'].iloc[-1])
        advice = compute_advice(arb_result.get('final_score', 50.0), dims_factor,
                                l0, dim_results or {}, ts_code, entry_price)
    except Exception:
        pass

    return self._v390_result(arb_result.get('opportunity_state', 'wait'),
                             arb_result.get('state_evidence', []),
                             consensus, conflict,
                             arb_result.get('final_score', 50.0), reliability,
                             advice=advice)
```

#### b) 辅助方法 `_v390_result`

```python
def _v390_result(self, state, evidence, consensus, conflict, final_score,
                 reliability, advice=None) -> dict:
    """v390 输出组装（兼容 _assemble 消费的 l2 结构）"""
    return {
        'opportunity_state': state,
        'state_evidence': evidence,
        'consensus_rate': consensus.get('consensus_rate', 0.0),
        'direction': consensus.get('direction', 'neutral'),
        'bullish_dims': consensus.get('bull_score', 0.0),
        'bearish_dims': consensus.get('bear_score', 0.0),
        'conflict_evidence': conflict.get('all_conflicts', [])[:8],
        # 390号新增字段
        'final_score': final_score,
        'semantic_type': conflict.get('semantic_type', ''),
        'reliability_summary': reliability,
        'consensus_detail': consensus.get('group_details', {}),
        'advice': advice or {},
    }
```

#### c) evaluate() 主流程接入版本分支

```python
# status_engine.py evaluate() 当前 L105：l2 = self._aggregate(tags, dims, l0, lifecycle)
# 改造为：
_jud_ver = str((self.cfg or {}).get('jud_engine_version', 'legacy'))
if _jud_ver == 'v390':
    l2 = self._aggregate_v390(tags, dims, l0, lifecycle, dim_engine_results, ts_code)
else:
    l2 = self._aggregate(tags, dims, l0, lifecycle)
```

**注意**：`dim_engine_results` 已含 dim1 门禁 + signal 判定（3.1 改造后）+ dim2-dim7 + summary。

#### d) `_assemble` 输出扩展（390号 §1.4 字段，条件写入）

```python
# _assemble() 中，v390 路径下追加 390号 新字段：
if 'final_score' in l2:
    result['final_score'] = l2['final_score']
    result['semantic_type'] = l2['semantic_type']
    result['reliability_summary'] = json.dumps(l2['reliability_summary'], ensure_ascii=False, default=str)
    result['consensus_detail'] = json.dumps(l2['consensus_detail'], ensure_ascii=False, default=str)
    # L6 advice 参数并入 advice_params（保持 337号 键名兼容）
    if l2.get('advice'):
        _ap = json.loads(result['advice_params']) if result.get('advice_params') else {}
        _ap.update({k: v for k, v in l2['advice'].items()
                    if k in ('max_position_ratio', 'stop_loss_price', 'target_price',
                             'risk_reward_ratio', 'invalidation_conditions')})
        result['advice_params'] = json.dumps(_ap, ensure_ascii=False, default=str)
```

### 3.3 兼容性与降级

| 场景 | 行为 |
|------|------|
| `jud_engine_version: "legacy"`（或配置缺失） | 走 `_aggregate`，与现状完全一致 |
| `jud_engine_version: "v390"` | 走 `_aggregate_v390`，输出含 390号 新字段 |
| v390 L3/L4/L5/L6 任一异常 | 逐层 try/except 降级（默认值），不中断管道 |
| dim1 门禁失败 | signal 判定由 dim2-dim7 输出独立生成（3.1），不受影响 |
| 回滚 | 改配置 `jud_engine_version: "legacy"` 一键回滚（390号 P5.4 机制） |

### 3.4 实审报告纠偏

- `backend/docs/JUD环节代码实审报告.md` 中 `_aggregate_v390`（L551-L699）描述与代码不符（函数从未存在）
- 本方案实施后该报告描述将成为现实；实施完成后建议在报告中标注"2026-09-08 418号方案实施后已落地"或重新实审

---

## 四、改动清单

| 文件 | 改动 | 风险 |
|------|------|------|
| `backend/app/opportunity_atlas/status_engine.py` | ①`_build_dim_engine_results` Step3 signal 判定并入 `results['signal']`（3.1）②新增 `_aggregate_v390`（3.2a）③新增 `_v390_result`（3.2b）④`evaluate()` 版本分支（3.2c）⑤`_assemble()` 390号字段扩展（3.2d） | 中（单文件，legacy 路径不改） |
| `backend/config/status_engine.yaml` | 无需修改（`jud_engine_version: "v390"` 已声明，本次让代码真正消费它） | 无 |
| `backend/tests/test_418_jud_v390.py` | 新建：v390 管线测试（见 §五） | 无 |
| `backend/tests/test_411_pipeline.py` | 补充：signal 键消费断言（可选） | 无 |

---

## 五、验证方案

### 5.1 单元测试（新建 test_418_jud_v390.py）

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统
backend/.venv/bin/python3 -m pytest backend/tests/test_418_jud_v390.py -v --tb=short
```

测试用例：
1. `test_signal_analysis_merged_into_signal`：`_build_dim_engine_results` 后 `results['signal']` 含 `judgment.attribute.code`（mock tags+dim2-dim7 输出，无真实 DB）
2. `test_dim_adapter_reads_signal`：`convert_to_factors` 从合并后的 dim_results 提取 signal direction（right_confirmed→1 / risk_warning→-1）
3. `test_reliability_assessor_signal`：`_assess_signal` 从合并后 signal 提取 maintenance.status（healthy→0.8）
4. `test_aggregate_v390_basic`：`_aggregate_v390` 返回含 final_score/semantic_type/reliability_summary/consensus_detail
5. `test_aggregate_v390_hard_veto`：l0.hard_veto=True → 返回 avoid
6. `test_aggregate_v390_fatal_conflict`：conflict.fatal_to_veto 非空 → 返回 wait
7. `test_version_branch_legacy`：`jud_engine_version: legacy` → 调用 `_aggregate`（mock 断言）
8. `test_version_branch_v390`：`jud_engine_version: v390` → 调用 `_aggregate_v390`
9. `test_legacy_output_unchanged`：legacy 路径输出结构与改造前一致（回归）

### 5.2 既有回归

```bash
make check   # lint + typecheck + test
# 重点回归：test_411_pipeline.py / test_390_integration.py / test_dim1_gate.py
```

### 5.3 真实数据验证

```bash
# 单只全流程（v390）：
backend/.venv/bin/python3 -c "
from app.opportunity_atlas.status_engine import StatusEngine
se = StatusEngine()
r = se.evaluate('000001.SZ')
print('opportunity_state:', r and r.get('opportunity_state'))
print('final_score:', r and r.get('final_score'))
print('semantic_type:', r and r.get('semantic_type'))
"
```

**验收标准**：
- 单只 evaluate < 500ms（390号 ARCH-8 基准）
- 同一股票 v390 vs legacy 的 opportunity_state 分布差异 ≤ ±10%（390号 P5.2 切换标准，抽样 100 只对比）
- 无硬否决遗漏：l0.hard_veto 场景 100% 触发 avoid

---

## 六、风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| v390 组件与 dim_results 键名不匹配（convert_to_factors 期望键 vs 实际键） | 中 | 中 | 3.1 先修复 signal 键；dim2-dim7 键名（structure/volume_price/chip_fund/emotion/risk/valuation）已与 reliability_assessor._KNOWN_DIMS 对齐，实施时逐组件单测验证 |
| conflict_matrix.detect 期望 dim2/dim3 键（L46-47 兼容双键名） | 低 | 低 | detect 已内置 `or dim_results.get('structure')` 兼容 |
| consensus_engine 对 emotion_phase 校验严格（非法值抛 ValueError） | 低 | 中 | 3.2a 已 try/except + 默认 'normal' |
| v390 输出字段变更影响前端 | 中 | 中 | 仅**新增**字段（final_score 等），legacy 键全部保留；前端按需适配 |
| L6 compute_advice 依赖 dim_results['risk'] 结构 | 低 | 低 | 已 try/except；内部有 DataManager fallback |

---

## 七、实施计划

| 阶段 | 任务 | 优先级 | 工时 | 依赖 |
|------|------|--------|------|------|
| Step 1 | 问题2修复：signal 判定并入 `results['signal']`（3.1） | P0 | 0.3天 | 无 |
| Step 2 | `_aggregate_v390` + `_v390_result` 实现（3.2a/b） | P0 | 0.5天 | Step 1 |
| Step 3 | `evaluate()` 版本分支 + `_assemble` 字段扩展（3.2c/d） | P0 | 0.3天 | Step 2 |
| Step 4 | 单元测试 test_418_jud_v390.py（9 用例） | P1 | 0.5天 | Step 1-3 |
| Step 5 | 回归 + 真实数据验证 + 新旧分布对比 | P1 | 0.5天 | Step 4 |
| **合计** | | | **2.1天** | |

### 阶段依赖图

```
Step 1（signal键合并，P0）── 修复问题2，低风险先行
    ↓
Step 2（_aggregate_v390，P0）
    ↓
Step 3（版本分支+输出扩展，P0）
    ↓
Step 4（测试）──→ Step 5（回归+真实验证）
```

---

## 八、与既有方案的关系

| 方案 | 关系 |
|------|------|
| 390号（JUD多因子引擎） | 本方案是 390号 Phase 1-3 产物的**接入补齐**（组件已建，缺 status_engine 编排） |
| 409号（dim1门禁） | 本方案修复 409号 §5.4a 要求但未实现的"v3.1 格式兼容"——通过键名合并恢复 signal 消费 |
| 411号（统一实施计划） | Phase 4 将 signal_analyzer 输出放 `signal_analysis` 键导致消费断裂，本方案修正 |
| 412号（消费者接入） | dim1 门禁（A1-A4）保持不动，本方案只叠加 signal 判定 |
| 417号（COL清洗） | 无直接依赖（不同环节） |

---

**方案编制日期**：2026-09-08
**编制依据**：409号方案核查报告（问题1/问题2）+ 390号方案 v3.0 + JUD环节代码实审报告 + 用户指示
**编制背景**：核查 409 号方案落地状态时发现两个独立问题：①v390 配置与代码脱节（HIGH）②dim1 门禁结果与 JUD 消费链键名错位（MED）。本方案聚焦修复这两项，不重新设计 v390 组件本身。
