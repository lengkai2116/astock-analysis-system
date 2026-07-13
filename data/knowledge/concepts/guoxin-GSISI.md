---
type: concept
title: 国信投资者情绪指数（GSISI）
created: 2026-06-01
updated: 2026-06-01
tags: [情绪周期, 量化择时, 国信证券]
related: [qingxu-zhouqi-lianghua-yanzheng, qingxu-zhouqi, BigQuant-qingxu-zhishu]
sources: ["research--2026-06-01.md"]
---
# 国信投资者情绪指数（GSISI）

**国信投资者情绪指数（GSISI）**是国信证券基于行业贝塔轮动构建的投资者情绪指数。

## 核心方法

采用Spearman秩相关系数度量申万一级行业的Beta系数与收益率之间的等级相关性：
- $\rho_s \geq 0$：投资乐观情绪上扬
- $\rho_s \leq 0$：投资悲观情绪蔓延

使用37.1作为多空阈值，连续两次信号确认后判断反转。

## 复现

BigQuant平台提供了该模型的复现实现。