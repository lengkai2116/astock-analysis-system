---
type: concept
title: 市值加权自适应LASSO
created: 2026-06-04
updated: 2026-06-04
tags: [machine-learning, overfitting, multi-factor, quant, lasso]
related: [机器学习合成因子过拟合控制, 多因子选股, 群体特异性建模, ElasticNet, 正则化]
sources: ["research--2026-06-04.md"]
---
# 市值加权自适应LASSO

市值加权自适应LASSO（Market Cap Weighted Adaptive LASSO）是王熙等（2022）提出的针对A股市场的因子筛选模型。该模型在样本外表现上显著优于ElasticNet等固定惩罚模型。

## 核心机制

- **自适应权重**：使用WLS（加权最小二乘）系数的倒数作为自适应惩罚权重。
- **市值加权**：对不同因子施加不同的惩罚权重，防止模型被小市值股过度影响。
- **时变因子筛选**：能够实时识别A股市场的有效因子。

## 实证表现

- 样本外月收益：1.19%
- 样本外夏普比率：0.92
- 显著优于PCA、普通LASSO、ElasticNet

## 与ElasticNet的对比

| 维度 | ElasticNet | 市值加权自适应LASSO |
|------|------------|-------------------|
| 惩罚方式 | 固定L1+L2惩罚 | 自适应权重惩罚 |
| 市值处理 | 无特殊处理 | 市值加权防止小市值过度影响 |
| 时变性 | 静态 | 动态识别有效因子 |
| A股样本外表现 | 较好 | 更优 |

## 实践意义

该模型提示：在A股市场中，简单的固定惩罚模型（如ElasticNet）是一个好的起点，但并非最优解。通过引入市值权重和自适应惩罚机制，可以显著提升模型的样本外表现。