---
type: concept
title: 二阶随机占优（SSD）
created: 2026-06-05
updated: 2026-06-05
tags: [asset-pricing, factor-model, stochastic-dominance]
related: [duo-yinzi-xuan-gu, SDF-xishu-xing-zhenglun, gaojie-yinzi-moxing]
sources: ["research--2026-06-05.md"]
---
# 二阶随机占优（SSD）

二阶随机占优（Second-Order Stochastic Dominance, SSD）是一种基于风险厌恶投资者偏好的排序方法，用于比较不同投资组合或因子模型的优劣。

## 在因子筛选中的应用

Kofina等（2025）基于SSD框架提出稀疏因子模型，从24个初始因子中选出10个因子（含市场因子、规模因子、ROE、时间序列动量、HMLm、预期增长、QMJ、资产增长、总毛利率和净运营资产）。当候选因子扩展到177个时，该模型仍保持10个因子的最优水平，并显著优于所有基准模型。

## 优势

- SSD框架不依赖于特定的效用函数假设，具有更强的鲁棒性。
- 与[[GRS统计量]]和[[Lasso回归]]相比，SSD从风险厌恶投资者的角度评估因子模型，更贴近实际投资决策。