---
type: concept
title: Bethe-Hessian矩阵谱聚类
created: 2026-06-07
updated: 2026-06-07
tags: [algorithm, community-detection, spectral-clustering, sparse-graph]
related: [log-sparse-community, san-jie-duan-jian-jin-shi-zeng-qiang-fang-an]
sources: ["research-log503001-2026-06-07.md"]
---
# Bethe-Hessian矩阵谱聚类

**Bethe-Hessian矩阵谱聚类**是一种图社区检测算法，特别适用于稀疏网络。该算法在异质度稀疏网络中具有明显优势，可有效避免传统谱聚类对稀疏图的「低信噪比」问题。

## 在Log稀疏社区中的应用

在 [[san-jie-duan-jian-jin-shi-zeng-qiang-fang-an]] 的阶段一中，采用Bethe-Hessian矩阵谱聚类算法对503个节点构建初始连通图，运行社区检测，输出初步子社区划分。

## 优势

- 对稀疏图具有鲁棒性
- 能有效处理异质度网络
- 避免传统谱聚类的低信噪比问题