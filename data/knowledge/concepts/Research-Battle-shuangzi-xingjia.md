---
type: concept
title: Research–Battle双子星架构
created: 2026-05-31
updated: 2026-05-31
tags: [ai, multi-agent, finance, architecture]
related: [FinGenius, ai-gongju-juxianxing-jinrong-touzi, huanjue-wenti-jinrong-AI, bianlunshi-jizhi]
sources: ["research-ai-2026-05-31.md"]
---
# Research–Battle双子星架构

## 概述

Research–Battle双子星架构是[[FinGenius]]（首个A股博弈多智能体应用）采用的多智能体架构。该架构通过多轮辩论博弈克服AI幻觉，核心创新在于引入博弈论思想来优化决策过程，解决信息不对称环境下的最优决策问题。

## 架构组成

- **Research模块**：负责信息收集、数据分析和基本面研究，提供决策所需的事实基础
- **Battle模块**：负责多轮辩论博弈，通过多智能体之间的对抗性讨论，识别和纠正信息偏差

## 工作流程

1. Research模块收集和分析金融数据
2. Battle模块启动多轮辩论，多个智能体从不同角度对同一标的进行分析
3. 通过博弈过程逐步收敛到更准确的结论
4. 最终输出经过辩论验证的决策建议

## 意义

该架构通过引入博弈论思想，利用多智能体之间的对抗性讨论来克服单一模型的幻觉问题，是金融AI应用中应对不确定性的创新方案。