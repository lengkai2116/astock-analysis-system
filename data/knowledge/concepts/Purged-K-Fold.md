---
type: concept
title: Purged K-Fold
created: 2026-06-05
updated: 2026-06-05
tags: [machine-learning, cross-validation, overfitting-control, time-series]
related: [Triple-Barrier标签, 机器学习合成因子过拟合控制, 过拟合检测, 滚动交叉验证, Combinatorial-Purged-CV]
sources: ["research--2026-06-05.md"]
---
# Purged K-Fold

## 概述

Purged K-Fold是一种针对金融时序数据设计的交叉验证方法。它通过在训练折中剔除标签时间与测试折重叠的样本，防止未来信息泄露，是[[机器学习合成因子过拟合控制]]的核心工程技术之一。

## 实现要点

- **剔除重叠样本**：每一折训练集剔除所有标签区间与测试集时间窗口相交的样本。
- **Embargo机制**：在测试折后设置隔离带（Embargo），防止滞后特征污染。
- **Embargo长度**：设为最大持仓窗口的1-2倍。
- **CPCV扩展**：可进一步采用[[Combinatorial Purged CV]]（CPCV）增加独立评估次数，缓解多重检验问题。

## 与标准K-Fold的区别

标准K-Fold假设样本独立同分布，在金融时序数据中会导致严重的未来信息泄露。Purged K-Fold显式处理了时序依赖问题，是金融机器学习中交叉验证的标准方法。