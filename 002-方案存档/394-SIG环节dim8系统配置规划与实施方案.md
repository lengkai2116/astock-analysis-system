---
title: SIG环节dim8系统配置规划与实施方案
type: 实施方案
date: 2026-09-17
version: v1.0
status: 已实施（2026-09-18，Phase 1-6 遗漏修复完成）
related:
  - 392-SIG环节系统架构与能力说明
  - 393-JUD环节系统架构与能力说明
  - 378-SIG环节8维度引擎能力梳理
  - 383-SIG环节股票现状描述输出确认
---

# 394 — SIG环节dim8系统配置规划与实施方案

> **背景**：经392号系统审查发现dim8的判定输出（共识率/冲突/状态条）在代码中无任何下游消费者，属于"写了但没人读"的冗余计算。同时dim2-dim7引擎生成的plain现状描述文本在透传链路中被丢弃，前端看到的只是简陋的方向摘要。本方案将dim8从"独立判定引擎"重新定位为"SIG输出质量守门员+现状描述生成器"。

---

## 一、dim8新定位

### 1.1 职责变更

| 项目 | 旧定位 | 新定位 |
|------|--------|--------|
| **判定功能** | 自行计算共识率/冲突/状态条 | **删除**。判定完全由JUD L3-L5承接 |
| **输出质量检查** | 仅检查7引擎有无输出 | **新增**。检查完整性/有效性/plain非空/数值合理性 |
| **预计算管理** | 无 | **新增**。发现异常dim时触发单只重算 |
| **现状描述生成** | 无（generate_seven_dim_from_signals忽略plain） | **新增**。读取dim2-dim7的plain，统一加工后输出seven_dim_json |
| **红绿灯汇总** | 提取dim1-dim7灯色 | **保留**。前端九维灯仍从此处读取 |

### 1.2 数据流变更

```
旧流程:
  dim1-dim7 → generate_seven_dim_from_signals() → seven_dim_json（忽略plain，自行拼接方向摘要）
  dim8 → consensus_rate/conflict/status_bar（无人消费）

新流程:
  dim1-dim7 → dim8质量检查 → 异常dim触发重算
           → dim8读取dim2-dim7的plain → 统一加工 → seven_dim_json（真实现状描述）
           → dim8红绿灯汇总（保留）
  dim8不产出consensus_rate/conflict/status_bar（删除判定功能）
```

---

## 二、现状分析

### 2.1 dim8当前代码结构（370行）

| 函数 | 行数 | 用途 | 新方案处置 |
|------|------|------|-----------|
| `_extract_dim_judgment()` | 44-49 | 提取judgment | 保留（质量检查用） |
| `_extract_dim_light()` | 52-55 | 提取灯色 | 保留（红绿灯用） |
| `_extract_dim_direction()` | 58-61 | 提取方向 | 保留（质量检查用） |
| `_extract_dim_plain()` | 64-70 | 提取plain | 保留+增强（现状描述核心） |
| `_extract_dim_audit_confidence()` | 73-79 | 提取audit confidence | **修复bug**（L75参数错误） |
| `_build_eight_dim_summary()` | 86-105 | 红绿灯映射 | 保留 |
| `_calc_consensus_rate()` | 124-143 | 共识率计算 | **删除**（JUD L3替代） |
| `_detect_conflicts()` | 150-201 | 冲突检测 | **删除**（JUD L4替代） |
| `_derive_status_bar()` | 208-243 | 状态条推导 | **删除**（JUD L5替代） |
| `_generate_text()` | 250-273 | 综合文字 | **重构**为plain统一加工 |
| `Dim8SummaryEngine.evaluate()` | 283-364 | 主入口 | **重构**为质量检查+描述生成 |

### 2.2 已知bug

| bug | 位置 | 影响 | 修复方式 |
|-----|------|------|---------|
| `_extract_dim_audit_confidence` L75 | `dim_results.get(dim_results, {})` | dict作key传入自身，始终返回0 | 改为`dim_results.get(dim_name, {})` |

### 2.3 generate_seven_dim_from_signals的问题

当前`status_engine.py:913`的`generate_seven_dim_from_signals()`从signal_json提取方向+置信度拼接为text，**完全忽略各dim引擎的status_description.plain**。dim2的"价格在中枢上方偏离4.7%，均线多头排列"和dim6的"风险中等，支撑位10.62，盈亏比1.8"——这些丰富信息从未到达前端。

---

## 三、技术可行性确认

### 3.1 管道时序保证

```
SIG步骤（原子完成）
  ├─ dim1-dim7预计算（并行）
  ├─ dim8质量检查 → 发现异常 → 触发单只重算 → 更新dim_results_json
  ├─ dim8现状描述生成 → 更新seven_dim_json
  ├─ 写入strategy_signal_detail
  └─ SIG标记done
      ↓（SIG完成后JUD才开始）
JUD步骤 → 读取dim_results_json（已是dim8检查+重算后的数据）
```

**关键**：dim8的所有操作在SIG步骤内部完成，JUD还没开始读数据，不存在不一致问题。

### 3.2 单只重算能力

- `StatusEngine.evaluate(ts_code)` 支持单只计算 ✅
- `_build_dim_engine_results()` 支持单引擎try/except ✅
- `_batch_write_signal_detail()` 支持UPDATE ✅
- API层已有fallback实计算（strategy_analyze.py:977-991） ✅

### 3.3 plain文本现状

| 维度 | plain风格 | 383号规范差距 |
|------|-----------|-------------|
| dim2 | 组合子维度detail，30-60字 | 无 |
| dim3 | 方向+置信度+阶段，30-50字 | 缺pattern和divergence |
| dim4 | 阶段+资金+筹码+拥挤度，30-50字 | 无 |
| dim5 | 市场/板块/个股三层，50-100字 | 无 |
| dim6 | 风险+价位+止损+波动，60-120字 | 无 |
| dim7 | 一行f-string，~25字 | 缺FCF收益率和股息率 |

---

## 四、实施方案

### Phase 1：Bug修复 + 基础准备（1天）

**目标**：修复已知bug，为后续功能做准备。

| 任务 | 内容 | 验证方式 |
|------|------|---------|
| T1.1 | 修复`_extract_dim_audit_confidence` L75 bug：`dim_results.get(dim_results, {})` → `dim_results.get(dim_name, {})` | 单元测试：传入dim_results={structure:{audit:{confidence:0.8}}}，验证返回0.8 |
| T1.2 | dim3 plain补全：在dim3引擎的plain生成处添加pattern和divergence信息 | 手动验证：检查dim3的status_description.plain是否包含形态和背离描述 |
| T1.3 | dim7 plain补全：在dim7引擎的plain生成处添加FCF收益率和股息率 | 手动验证：检查dim7的status_description.plain是否包含fcf_yield和dividend_yield |
| T1.4 | 创建`test_394_dim8_quality.py`测试文件，包含质量检查的基础测试用例 | pytest运行通过 |

**交付物**：
- dim8_summary_engine.py L75 bug修复
- dim3/dim7 plain增强
- test_394_dim8_quality.py

### Phase 2：dim8输出质量检查（2天）

**目标**：dim8实现完整的输出质量检查能力。

| 任务 | 内容 | 验证方式 |
|------|------|---------|
| T2.1 | 在dim8中新增`_check_dim_quality()`函数，实现6项检查：完整性（dim是否存在）、有效性（judgment非空）、plain非空、confidence下限（≥0.3）、方向一致性（不全为0）、数值合理性 | 单元测试：构造正常/异常dim_results，验证检查结果 |
| T2.2 | 在dim8中新增`_calc_quality_score()`函数，将6项检查结果聚合为0-1的质量评分 | 单元测试：验证评分范围[0,1]，全通过=1.0，全失败=0.0 |
| T2.3 | 在dim8.evaluate()中集成质量检查，输出quality_report到status_description | 集成测试：调用dim8.evaluate()，验证输出包含quality_report字段 |
| T2.4 | 在dim8的audit conditions中扩展质量检查项（替代当前仅检查有无输出） | 验证：audit.conditions从7项扩展为13+项 |

**交付物**：
- `_check_dim_quality()` 函数
- `_calc_quality_score()` 函数
- dim8.evaluate()集成质量检查
- 扩展后的audit conditions
- 测试用例

### Phase 3：dim8预计算管理+单只重算（2天）

**目标**：dim8发现异常dim时触发单只重算。

| 任务 | 内容 | 验证方式 |
|------|------|---------|
| T3.1 | 在dim8中新增`_trigger_recalc()`函数：接收ts_code和异常dim列表，调用`StatusEngine._build_dim_engine_results()`重算该股票的异常dim | 单元测试：构造dim_results中某dim为None，验证重算后该dim有输出 |
| T3.2 | 在dim8中新增`_update_dim_results()`函数：将重算结果写回strategy_signal_detail.dim_results_json | 集成测试：验证UPDATE后dim_results_json包含重算结果 |
| T3.3 | 在dim8.evaluate()中集成重算逻辑：质量检查发现异常→触发重算→更新dim_results_json | 端到端测试：构造异常dim_results→调用dim8.evaluate()→验证dim_results_json已更新 |
| T3.4 | 添加重算上限保护：最多重算100只股票/次，超出记录告警日志 | 验证：构造150只异常股票，验证只重算100只 |

**交付物**：
- `_trigger_recalc()` 函数
- `_update_dim_results()` 函数
- 重算集成逻辑
- 重算上限保护
- 测试用例

### Phase 4：dim8现状描述生成器（3天）

**目标**：dim8读取dim2-dim7的plain，统一加工后输出seven_dim_json，替代generate_seven_dim_from_signals。

| 任务 | 内容 | 验证方式 |
|------|------|---------|
| T4.1 | 在dim8中新增`_collect_dim_plain()`函数：从dim2-dim7的status_description.plain采集6段文本 | 单元测试：验证采集到6段非空plain |
| T4.2 | 在dim8中新增`_unify_dim_plain()`函数：对plain进行补全/去重/排序/格式统一 | 单元测试：验证输出格式为"【维度名】描述"，6维按固定顺序排列 |
| T4.3 | 在dim8中新增`_build_seven_dim_report()`函数：将统一后的plain组装为seven_dim_json格式（{dim: {title, light, text, evidence, confidence}}） | 单元测试：验证输出格式与现有seven_dim_json兼容 |
| T4.4 | 在dim8.evaluate()中集成现状描述生成，输出seven_dim_report到status_description | 集成测试：验证dim8输出包含seven_dim_report字段 |
| T4.5 | 修改data_daemon.py SIG步骤：将dim8的seven_dim_report写入strategy_signal_detail.seven_dim_json（替代generate_seven_dim_from_signals） | 端到端测试：运行SIG步骤，验证seven_dim_json包含dim引擎的plain文本 |
| T4.6 | 保留generate_seven_dim_from_signals()作为fallback（dim8失败时使用） | 验证：dim8异常时fallback到旧函数 |

**交付物**：
- `_collect_dim_plain()` 函数
- `_unify_dim_plain()` 函数
- `_build_seven_dim_report()` 函数
- data_daemon.py集成修改
- 测试用例

### Phase 5：删除dim8判定功能（1天）

**目标**：删除dim8中与JUD重叠的判定功能。

| 任务 | 内容 | 验证方式 |
|------|------|---------|
| T5.1 | 删除`_calc_consensus_rate()`函数及其调用 | 验证：dim8.evaluate()不再输出consensus_rate到judgment |
| T5.2 | 删除`_detect_conflicts()`函数及其调用 | 验证：dim8.evaluate()不再输出conflicts到status_description |
| T5.3 | 删除`_derive_status_bar()`函数及其调用 | 验证：dim8.evaluate()不再输出status_bar到judgment |
| T5.4 | 删除DIM_WEIGHTS常量 | 验证：文件中不再有DIM_WEIGHTS定义 |
| T5.5 | 简化dim8.evaluate()：仅保留红绿灯汇总+质量检查+现状描述生成 | 验证：evaluate()代码量从~80行降至~40行 |
| T5.6 | 更新dim8的docstring：反映新定位 | 验证：docstring描述与实际功能一致 |

**交付物**：
- 精简后的dim8_summary_engine.py
- 删除的函数确认无残留引用

### Phase 6：端到端验证（1天）

**目标**：全链路验证dim8新功能。

| 任务 | 内容 | 验证方式 |
|------|------|---------|
| T6.1 | 运行现有14项测试全部通过 | `pytest tests/test_390_*.py -v` |
| T6.2 | 运行新增的dim8质量检查测试 | `pytest tests/test_394_dim8_quality.py -v` |
| T6.3 | 运行dim8现状描述生成测试 | `pytest tests/test_394_dim8_description.py -v` |
| T6.4 | 手动验证：用真实股票数据运行SIG步骤，检查seven_dim_json是否包含dim引擎plain | 日志检查+数据库查询 |
| T6.5 | 手动验证：dim8质量检查发现异常dim时是否触发重算 | 构造异常数据→运行→检查重算日志 |
| T6.6 | 更新392号系统说明文档中dim8章节 | 文档审查 |

**交付物**：
- 全部测试通过
- 验证报告

---

## 五、依赖关系

```
Phase 1 (Bug修复+基础准备)
  ↓
Phase 2 (质量检查) ←── 可与Phase 1并行（T1.2/T1.3不影响）
  ↓
Phase 3 (预计算管理+重算) ←── 依赖Phase 2
  ↓
Phase 4 (现状描述生成) ←── 依赖Phase 1（T1.2/T1.3补全plain）
  ↓
Phase 5 (删除判定功能) ←── 依赖Phase 2+3+4（新功能稳定后才删除旧功能）
  ↓
Phase 6 (端到端验证) ←── 依赖Phase 5
```

**预计总工时**：10天（Phase 1: 1天, Phase 2: 2天, Phase 3: 2天, Phase 4: 3天, Phase 5: 1天, Phase 6: 1天）

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| dim8重算耗时延长SIG步骤 | 全市场5000只中若有大量异常，重算增加~5min | 设置重算上限100只/次，超出记录告警 |
| dim8自身bug导致误判 | 把正常值标记为异常 | 审查检查阈值，添加日志，保留fallback |
| plain加工引入信息丢失 | 统一格式时丢失原始细节 | 保留原始plain作为fallback，加工失败时使用原文 |
| generate_seven_dim_from_signals删除后兼容性 | 某些旧路径可能仍引用 | Phase 5最后执行，保留函数作为deprecated |
| dim8 L75 bug修复影响其他逻辑 | 该函数当前未被调用 | 修复后添加单元测试确认 |

---

## 七、验收标准

| 验收项 | 标准 |
|--------|------|
| dim8质量检查 | 能检测出dim为None/judgment缺失/plain为空/confidence过低等异常 |
| dim8重算触发 | 异常dim被自动重算，重算后dim_results_json更新 |
| dim8现状描述 | seven_dim_json包含dim2-dim7的plain文本（非方向摘要） |
| dim8判定功能删除 | dim8不再输出consensus_rate/conflict/status_bar |
| 现有测试 | 14项390测试全部通过 |
| 新增测试 | dim8质量检查+现状描述生成测试全部通过 |
| 前端兼容 | seven_dim_json格式与现有前端消费格式兼容 |
| 性能 | dim8新增功能使SIG步骤耗时增加不超过30% |

---

**文档编制日期**：2026-09-17
**编制依据**：392/393号系统说明 + 391号核查报告 + dim8代码实审 + 管道时序分析
