---
type: concept
title: Triple-Barrier标签
created: 2026-06-05
updated: 2026-06-05
tags: [machine-learning, label-construction, overfitting-control, quantitative-trading]
related: [Purged-K-Fold, 机器学习合成因子过拟合控制, 过拟合检测, Meta-Labeling]
sources: ["research--2026-06-05.md"]
---
# Triple-Barrier标签

## 概述

Triple-Barrier标签由Marcos López de Prado提出，是一种先进的标签构造方法。它通过设置止盈、止损和固定时间三条"沿"，动态确定样本标签，使模型学习到与真实交易更一致的信号，相比固定窗口收益标签能显著降低噪声混入。

## 实现要点

- **上沿与下沿**：基于波动率自适应设定（如2倍ATR），避免固定阈值对高波动股票失效。
- **时间沿**：设置最大持仓时间，防止样本无限期持有。
- **标签定义**：首次触达上沿标记为1（盈利），触达下沿标记为-1（亏损），时间沿到期标记为0（平局）。
- **交叉验证**：对标签时间重叠的样本在交叉验证中显式剔除（[[Purged K-Fold]]）。
- **Meta-Labeling**：可与[[Meta-Labeling]]技术结合，将信号方向与置信度分离建模。

## 优势

- 更贴近真实交易场景，考虑了退出条件
- 基于波动率自适应，适用于不同波动特征的股票
- 与严格训练协议结合，有效控制过拟合