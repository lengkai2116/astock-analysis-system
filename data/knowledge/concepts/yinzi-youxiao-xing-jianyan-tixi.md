---
type: concept
title: 因子有效性检验体系
created: 2026-06-05
updated: 2026-06-05
tags: [factor-model, validation, IC, IR]
related: [duo-yinzi-xuan-gu, SDF-xishu-xing-zhenglun, GRS-tongjiliang, er-jie-sui-ji-zhan-you, Fama-MacBeth-huigui]
sources: ["research--2026-06-05.md"]
---
# 因子有效性检验体系

因子有效性检验体系是评判量化因子预测能力的系统性方法。最新研究引入了更高级的筛选工具。

## 传统方法

- **IC（信息系数）**：因子值与未来收益的截面相关性。
- **Rank IC**：因子值与未来收益的秩相关性。
- **ICIR**：IC的均值与标准差之比，衡量因子预测的稳定性。
- **分层收益**：按因子值分组后的收益差异。

## 高级筛选方法

- **[[GRS统计量]]**：检验因子模型能否解释所有Alpha。
- **[[二阶随机占优]]（SSD）框架**：从风险厌恶投资者角度评估因子模型。
- **[[Fama-MacBeth回归]]**：截面收益检验的经典方法。
- **[[组合对称交叉验证]]（CSCV）**：量化回测过拟合概率。

## 因子筛选应匹配模型类型

- 对于线性因子模型，应使用IC、Rank IC等线性相关性指标。
- 对于非线性模型（如[[随机森林]]、[[XGBoost]]），应使用卡方检验、Cramer's V或互信息等能捕捉非线性关系的指标。