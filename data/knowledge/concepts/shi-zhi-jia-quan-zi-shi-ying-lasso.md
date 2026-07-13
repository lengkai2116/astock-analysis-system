---
type: concept
title: 市值加权自适应LASSO
created: 2026-06-05
updated: 2026-06-05
tags: [algorithm, factor-selection, regularization]
related: [a-gu-wu-da-you-xiao-yin-zi, wang-xi-deng-2022, zi-shi-ying-lasso]
sources: ["research--2026-06-05.md"]
---
# 市值加权自适应LASSO

市值加权自适应LASSO是王熙等（2022）在《A股市场的时变多因子模型》中采用的一种改进的LASSO算法，用于从47个候选因子中识别出A股五大有效因子。

## 核心优势

1. **自适应权重**：通过引入自适应权重，防止模型对重要因子进行“过度压缩”（Over-Shrinkage）。
2. **市值加权**：通过市值加权，减轻了极端小市值股票对结果的影响，保证了因子收益估计的稳健性。

## 应用案例

该算法在2008-2020年的A股数据上，从47个候选因子中成功识别出[[市场因子]]、[[税收因子]]、[[市盈率因子]]、[[规模因子]]和[[速动因子]]五个最有效的定价因子。

## 与ElasticNet的对比

市值加权自适应LASSO与[[ElasticNet]]在A股多因子模型中的对比研究表明，市值加权自适应LASSO的短期预测优势显著，但长期预测中不同方法收敛。选择取决于投资期限、因子相关性、信噪比等具体条件。