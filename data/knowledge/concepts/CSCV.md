---
type: concept
title: 组合对称交叉验证（CSCV）
created: 2026-06-05
updated: 2026-06-05
tags: [backtesting, overfitting, cross-validation, risk-assessment]
related: [yinzi-shixiao-yu-guodu-youhua, jiqi-xuexi-hecheng-yinzi-guonihe-kongzhi, duo-yinzi-xuan-gu, XGBoost, SVM, LSTM]
sources: ["research--2026-06-05.md"]
---
# 组合对称交叉验证（CSCV）

组合对称交叉验证（Combination Symmetric Cross Validation, CSCV）是量化回测过拟合概率（PBO）的评估框架，由Bailey等提出，用于量化策略在历史回测中的过拟合风险。

## 核心原理

CSCV通过将历史数据划分为多个子样本，生成大量"别样景象"（alternative histories），评估策略在不同数据划分下的表现一致性。若策略在特定数据划分下表现显著优于其他划分，则表明存在过拟合。

## 关键指标

- **PBO（Probability of Backtest Overfitting）**：回测过拟合概率。PBO越低（<20%），策略的统计稳健性越高；PBO > 60%时应放弃实盘部署。

## A股实证结果

不同机器学习算法在A股的PBO差异显著：

- **[[XGBoost]]**：约8.6%–14.7%，过拟合风险最低
- **[[SVM]]**：约35.8%–37.1%，过拟合风险中等
- **[[LSTM]]**：约48.4%–57.2%，过拟合风险最高

扣除过拟合效应后，XGBoost的回测超额收益率仍最高。

## 应用建议

- 在策略开发完成后，使用CSCV计算PBO作为最终风险评估。
- 优先选择PBO < 20%的策略进行实盘部署。
- 将CSCV纳入量化策略开发的标准流程。