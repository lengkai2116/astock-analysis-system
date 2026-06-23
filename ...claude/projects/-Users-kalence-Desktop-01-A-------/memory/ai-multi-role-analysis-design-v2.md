---
name: ai-multi-role-analysis-design-v2
description: 194号方案v2修订完成，三点修正：专业研判范式、RTK评估与结构化token优化、全LLM参与确认
metadata:
  type: project
---

194号方案v2已完成修订，整合三点用户修正：

① **专业性优先**：各角色输出为专业研判报告（非叙事文本）——技术→缠论术语、基本面→投行研报、筹码→主力行为、情绪→情绪周期、消息面→事件驱动、风控→风险矩阵。每个角色有自己的分析框架，由System Prompt定义。

② **RTK评估**：RTK（Rust Token Killer）是CLI代理，不直接适用（后端是Python HTTP API调用）。但其结构化压缩思想可应用：`_build_structured_input()`按角色过滤只传相关数据，预期节约~58% token。双模型分层（fast模型分析/expensive模型合成）。

③ **全LLM确认**：所有分析、辩论、报告输出由DeepSeek实时生成。Mock仅降级使用，且模拟LLM输出风格。全链路：6角色独立LLM调用（并行）→ 辩论LLM调用（Phase 2）→ 综合LLM。

**状态：** ⏳ 待用户评估后启动Phase 0原型制作

**Why:** 用户对v1的三处核心批评已全部解决，方案已可交付评估。

**How to apply:** 用户评估通过后，立即启动Phase 0——重写`_ui-prototype/ai-analysis.html`（6角色Tab+专业研判Mock+进度模拟）。
