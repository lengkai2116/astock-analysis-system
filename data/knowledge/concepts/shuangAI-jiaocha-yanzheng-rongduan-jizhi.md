---
type: concept
title: 双AI交叉验证与熔断机制
created: 2026-05-31
updated: 2026-05-31
tags: [ai, trading, risk, validation, mechanism]
related: [InvestmentClaw, OpenClaw, ai-gongju-juxianxing-jinrong-touzi, huanjue-wenti-jinrong-AI]
sources: ["research-ai-2026-05-31.md"]
---
# 双AI交叉验证与熔断机制

## 概述

双AI交叉验证与熔断机制是[[InvestmentClaw]]系统（专注美股全自动交易）采用的应对大模型局限性的核心策略。针对每只候选标的，系统由两个推理模型独立评分后进行交叉验证融合，有效降低单一模型误判风险。

## 工作原理

1. **独立评分**：两个推理模型（如MiniMax-M2.7与GLM-5.1）分别对候选标的进行独立分析和评分
2. **交叉验证**：将两个模型的评分结果进行交叉验证，识别分歧点
3. **融合决策**：基于交叉验证结果生成最终决策，降低单一模型误判风险
4. **熔断机制**：当两个模型评分差异过大或系统检测到异常时，自动触发熔断，暂停交易

## 意义

该机制直接针对大模型的概率主义本质，通过多模型交叉验证提高决策的稳健性，是金融AI应用中应对幻觉问题的具体技术方案。