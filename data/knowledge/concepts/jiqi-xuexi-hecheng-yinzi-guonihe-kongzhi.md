---
type: concept
title: 机器学习合成因子过拟合控制
created: 2026-06-05
updated: 2026-06-05
tags: [machine-learning, factor-model, overfitting, risk-control]
related: [duo-yinzi-xuan-gu, yinzi-shixiao-yu-guodu-youhua, CSCV, XGBoost, SVM, LSTM, fengge-shibian-xing]
sources: ["research--2026-06-05.md"]
---
# 机器学习合成因子过拟合控制

机器学习合成因子过程中，过拟合控制是一个系统工程。最新研究提供了量化过拟合风险的工具和实证证据。

## CSCV框架

[[组合对称交叉验证]]（CSCV）可量化回测过拟合概率（PBO）。PBO越低（<20%），策略的统计稳健性越高；PBO > 60%时应放弃实盘部署。

## A股实证：不同算法的PBO差异

- **[[XGBoost]]**：约8.6%–14.7%，过拟合风险最低
- **[[SVM]]**：约35.8%–37.1%，过拟合风险中等
- **[[LSTM]]**：约48.4%–57.2%，过拟合风险最高

扣除过拟合效应后，XGBoost的回测超额收益率仍最高。

## 核心控制方法

1. **正则化**：优先采用带L1+L2正则化的模型（如ElasticNet）。
2. **滚动交叉验证**：针对金融时序数据设计，避免使用未来信息。
3. **群体特异性建模**：按市值分组分别训练模型，减少对小市值股的过度关注。
4. **时变因子筛选**：使用[[市值加权自适应LASSO]]实时识别有效因子。