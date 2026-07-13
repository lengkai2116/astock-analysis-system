---
type: concept
title: 基于消费者信心指数的情绪择时
created: 2026-06-01
updated: 2026-06-01
tags: [情绪周期, 量化择时, 消费者信心指数]
related: [qingxu-zhouqi-lianghua-yanzheng]
sources: ["research--2026-06-01.md"]
---
# 基于消费者信心指数的情绪择时

**基于消费者信心指数的情绪择时**是基于Anchada Charoenrook论文《Does Sentiment Matter?》的方法，使用密歇根大学消费者信心指数（CSI）的同比变化率（CCSI）作为情绪代理变量。

## 核心公式

$$CCSI_t = \frac{CSI_t - CSI_{t-12}}{CSI_{t-12}}$$

策略逻辑：当预测超额收益 $r̂_t = 0.009 - 0.049 × CCSI_{t-1} > 0$ 时持有风险资产，否则空仓。

## 回测结果

2023-2025年回测：年化20.42%，最大回撤11.36%，夏普比率1.6。