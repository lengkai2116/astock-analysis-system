---
type: concept
title: "Cypher 查询语言"
created: 2026-06-06
updated: 2026-06-06
tags: [query-language, knowledge-graph]
related: [neo4j-ge-ren-wei-ji-ying-yong, zhi-shi-tu-pu]
sources: ["research--2026-06-06.md"]
---
# Cypher 查询语言

**Cypher** 是 Neo4j 图数据库的声明式查询语言，用于执行复杂关联查询。在投资知识图谱中，Cypher 用于检索跨策略的隐性关联，支持 [[桥接发现]] 和 [[社区检测]] 的结果展示。

## 语法特点

- **模式匹配**：使用 ASCII 艺术风格语法描述图模式，直观易读。
- **路径查询**：支持可变长度路径查询，适合发现间接关联。
- **聚合函数**：支持对图结构进行统计聚合，计算中心性、聚类系数等指标。

## 投资 Wiki 应用示例

```cypher
// 查找连接缠论中枢和多因子因子的桥接概念
MATCH (c:Concept {name: "zhongshu"})-[*2..3]-(f:Concept {name: "yinzi"})
RETURN c, f, relationships(*)
```

## 与动态 Schema 配合

Cypher 查询需适应 [[动态 Schema]] 的变化，通过参数化查询和元数据管理，确保在图谱结构演化时查询脚本的鲁棒性。