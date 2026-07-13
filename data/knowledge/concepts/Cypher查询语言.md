---
type: concept
title: Cypher查询语言
created: 2026-06-05
updated: 2026-06-05
tags: [database, graph-database, query-language]
related: [Neo4j, 知识图谱构建方法论, 本体建模]
sources: ["research-193-2026-06-05.md"]
---
# Cypher查询语言

Cypher查询语言是Neo4j图数据库的声明式查询语言，用于执行复杂关联查询。在个人维基知识图谱中，Cypher用于验证概念间的关联关系。

## 示例查询

```cypher
// 查询所有与"量价策略"直接关联的概念
MATCH (c:Concept{name:'量价策略构建框架'})-[r]-() RETURN c, r

// 查询"量化策略"分支下的所有子概念和引用
MATCH (c:Concept{name:'量化策略'})-[:has_sub|references*1..3]-(child) RETURN child
```

## 核心语法

- **MATCH**：匹配图模式
- **RETURN**：返回查询结果
- **WHERE**：过滤条件
- **CREATE**：创建节点和关系
- **MERGE**：确保模式存在（创建或匹配）