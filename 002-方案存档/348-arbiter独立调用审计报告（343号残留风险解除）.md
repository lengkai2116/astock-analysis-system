---
title: arbiter 独立调用审计报告（343号残留风险解除）
type: 审计报告
date: 2026-08-17
status: ✅ 已存档（T21 审计完成：routes/services 无绕过快照的独立 arbitrate 调用；343 号残留风险解除，无需改码）
---

# 348 — arbiter 独立调用审计报告

## 一、背景

343 号（第②层判定核查-000008 口径差异记录）§五 残留风险：若某消费端直接调用 `arbitrate(tags)` 而不传 L2 consensus，会得到与快照不同的结论（如 000008.SZ 的 wait vs avoid）。建议后续审计 `arbitrate()` 调用方，确认均从快照取数。

## 二、审计范围

全库搜索 `app/opportunity_atlas/arbiter.py` 的 `arbitrate()` 函数调用方（排除自身定义）。

## 三、审计结果

### 3.1 arbitrate() 调用方（3 处，均为内部消费）

| 文件 | 行号 | 调用方式 | 是否绕过快照 |
|---|---|---|---|
| `status_engine.py` | 411/417 | `arbitrate(tags, gate=gate, ...)` | ❌ 否（引擎内部评估，消费已构建的 tags） |
| `cross_validate.py` | 443-444/934-935/1187-1188 | `arbitrate(tags, gate=gate, consensus=...)` | ❌ 否（内部 diagnose 流程，消费真实标签） |
| `advice_builder.py` | 175 | `arbitrate(arb_tags, consensus=_consensus_from_dirs(dirs))` | ⚠️ 部分（见 §3.2） |

### 3.2 advice_builder:175 兜底路径分析

```python
# advice_builder.py:168-176
arb_tags = {'right_side_confirm': rsc, 'main_force_phase': ...}
consensus = _consensus_from_dirs(dirs)  # 五维近似共识
arb = arbitrate(arb_tags, consensus=consensus)
state = real_state or arb['opportunity_state']  # 真实标签优先
```

**关键**：`real_state = tags.get('opportunity_state')`（160行）——**真实标签优先**，arbiter 仅在 `real_state=None`（数据缺失/无标签）时兜底。

**调用链验证**：
- 个股页 analyze（strategy_analyze.py:755）：传 `_tags = _dm.cache.get_tags(ts_code)`（真实标签）→ `real_state` 有值 → 结论与机会图谱同源 ✅
- 机会图谱 diagnose（cross_validate）：传 tags → 同源 ✅
- ECM `get_tags()`：返回 `{}`（非 None）时 `real_state = {}.get('opportunity_state') = None` → 走兜底 → **仅数据缺失时触发**

**结论**：兜底路径符合设计（数据缺失降级，292 红线"数据缺失返回空/降级"），非绕过快照的独立调用。

### 3.3 排除项（非 P0-P7 状态机）

| 文件 | 函数 | 说明 |
|---|---|---|
| `strategy_analyze.py:535/1017` | `ConflictArbiter.arbitrate(signals, zhongshu, ...)` | 四级信号冲突仲裁（卡5 展示），非 P0-P7 状态机 |
| `ai_analysis.py:317` | `/api/v3/ai/arbitrate` 路由 | LLM Wiki 概念匹配（indicator-ide 卡5B），非 P0-P7 |

## 四、结论

**343 号残留风险解除**——routes/services 无绕过快照的独立 arbitrate 调用：

1. status_engine / cross_validate / advice_builder 三处调用均为**内部消费**（引擎内部评估/diagnose/建议生成）
2. 个股页 analyze + 机会图谱 diagnose 均传**真实标签**（结论同源）
3. advice_builder 兜底仅在**数据缺失**时触发（符合 292 设计）
4. ConflictArbiter 与 ai_analysis/arbitrate 均非 P0-P7，排除

**无需代码修改**。

## 五、遗留

- 若未来新增 arbitrate() 调用方，需审计是否传 L2 consensus / 真实标签
- 建议在 arbiter.py 添加文档注释：`arbitrate()` 应通过 status_snapshot 或传入 L2 consensus 调用，禁止独立调用

---

**关联文档**：343（口径差异记录）、344（第②层报告 §十 遗留 1）、321（arbiter 轻量投票）
**文档版本**: v1.0（2026-08-17 T21 审计完成）
