---
type: concept
title: 高阶因子模型
created: 2026-06-05
updated: 2026-06-05
tags: [factor-model, higher-order, non-linear, asset-pricing]
related: [duo-yinzi-xuan-gu, SDF-xishu-xing-zhenglun, Fama-French-wu-yinzi, yinzi-shixiao-yu-guodu-youhua]
sources: ["research--2026-06-05.md"]
---
# 高阶因子模型

高阶因子模型是指在基础因子（如[[Fama-French五因子模型]]、动量因子）之上，加入平方项、三次项及交互项等非线性变换，以捕捉因子间的非线性关系和协同效应。

## Borri等（2026）研究

- 在Fama-French五因子加动量因子的基础上，构建57个候选高阶因子。
- 通过前向选择[[Fama-MacBeth回归]]选出7个高阶因子（如SMB²、SMB²×Mom等）。
- 将截面调整R²从31.2%提升至59%。
- 可解释148个[[因子动物园]]中95%的因子。

## 经济含义

高阶因子的显著性暗示可能存在[[金融中介资产定价]]等经济机制，但具体经济含义仍需进一步验证。非线性暴露在极端状态下的显著性值得关注。

## 实践建议

- 若基础因子集解释力不足，可考虑加入平方项和交互项（选3-7个）。
- 需注意高阶项带来的[[过拟合]]风险，使用[[组合对称交叉验证]]（CSCV）进行检验。
- 高阶因子模型更适合学术定价模型和Beta对冲组合，而非主动选股策略。