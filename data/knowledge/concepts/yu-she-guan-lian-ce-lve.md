---
type: concept
title: 预关联策略
created: 2026-06-07
updated: 2026-06-07
tags: [knowledge-graph, link-recommendation, wiki, auto-complete]
related: [log-sparse-community, san-jie-duan-jian-jin-shi-zeng-qiang-fang-an, yu-yi-qian-ru]
sources: ["research-log503001-2026-06-07.md"]
---
# 预关联策略

**预关联策略**（Pre-association Strategy）是 [[san-jie-duan-jian-jin-shi-zeng-qiang-fang-an]] 阶段三的核心技术，指在用户编辑维基页面时，基于实时语义匹配和共引网络，自动推荐可能相关的页面链接。

## 实施方法

- 当用户编辑页面时，系统实时分析页面内容。
- 基于语义嵌入的向量相似度计算，匹配知识库中其他页面。
- 结合共引网络分析，推荐与当前页面共同被引用的页面。
- 在编辑界面以侧边栏或下拉菜单形式展示推荐链接。

## 示例

当用户编辑 [[zhangtingban-zhangfa]] 时，系统自动推荐链接到 [[qingxu-zhouqi]]、[[yanzi-jinqianliu]]、[[zhongshu-type]] 等。

## 优势

- 降低用户手动创建链接的认知负担
- 利用算法发现用户可能忽略的关联关系
- 持续增强知识图谱的凝聚度