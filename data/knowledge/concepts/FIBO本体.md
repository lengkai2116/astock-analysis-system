---
type: concept
title: FIBO本体
created: 2026-06-05
updated: 2026-06-05
tags: [ontology, financial-data, knowledge-graph]
related: [知识图谱, 动态Schema, 概念网络构建主题建模与知识图谱的融合]
sources: ["research-wiki469-2026-06-05.md"]
---
# FIBO本体

FIBO（Financial Industry Business Ontology）是一个高度结构化但更新慢的金融本体，由顶级财富基金构建。在知识图谱Schema设计中，FIBO代表了"高度结构化但更新慢"的极端，与LLM动态生成的灵活Schema形成对比。

## 特点

- **高度结构化**：定义了详细的实体类型和关系
- **权威性强**：由顶级财富基金构建
- **更新速度慢**：难以适应快速变化的金融领域

## Schema设计困境

在知识图谱构建中，Schema设计面临核心权衡：是采用高度结构化但更新慢的FIBO本体，还是采用由LLM动态生成、灵活但可能不稳定的Schema。实践上可能需要采用"核心Schema稳定 + 边缘Schema动态更新"的混合模式。