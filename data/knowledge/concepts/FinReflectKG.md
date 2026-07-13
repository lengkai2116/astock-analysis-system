---
type: concept
title: FinReflectKG
created: 2026-06-05
updated: 2026-06-05
tags: [knowledge-graph, llm, financial-ai, framework]
related: [LLM在知识图谱构建中的应用, 知识图谱, 三元组, 概念网络构建主题建模与知识图谱的融合]
sources: ["research-wiki469-2026-06-05.md"]
---
# FinReflectKG

FinReflectKG是一个LLM驱动的金融知识图谱构建框架，其核心创新是"反射代理"（Reflection-Agent）模式。该模式通过迭代的"提取-反馈-修正"循环，可显著提高三元组提取的质量（精度与覆盖面），优于单次或多次COT提示。

## 核心特点

- **反射式提取**：通过迭代反馈修正提高三元组提取质量
- **高质量输出**：在精度和覆盖面方面优于传统方法
- **金融领域适配**：专门针对金融知识图谱构建设计

## 在概念网络构建中的应用

FinReflectKG的反射式提取模式可作为概念网络构建阶段二中知识图谱构建的核心方法，用于从概念页面内容中自动提取高质量的三元组。