---
type: concept
title: 波动率微笑因子
created: 2026-06-05
updated: 2026-06-05
tags: [options, volatility, quantitative-trading]
related: [svi-model, nasdaq-barometer-algorithm, duo-yin-zi-dong-tai-rong-he-mo-xing, qing-xu-zhou-qi-liang-hua-yan-zheng]
sources: ["research--2026-06-05.md"]
---
# 波动率微笑因子

**波动率微笑因子**（Volatility Smile Factor）是[[纳斯达克晴雨表算法]]中的核心因子之一。该因子基于CBOE期权隐含波动率数据，使用[[SVI模型]]构建完整的隐含波动率曲面，计算微笑偏度指数作为市场恐慌或乐观的信号。

## 核心指标

微笑偏度指数的计算公式为：

$$
\text{Skewness Index} = \frac{\text{IV}_{25\Delta Put} - \text{IV}_{25\Delta Call}}{\text{IV}_{ATM}} \times 100\%
$$

## 决策阈值

决策阈值根据VIX水平动态调整：
- 当偏度超过动态上限时发出强看空信号（-2.0）
- 当偏度低于动态下限时发出看多信号（+1.0）

## 技术实现

- 使用SVI参数化模型拟合隐含波动率曲面
- 加入时间衰减因子（`time_decay`）以提高跨期拟合精度
- 引入高斯平滑减少噪声

## 意义

波动率微笑因子是期权市场情绪的核心指标，反映了市场对尾部风险的定价。该因子与[[情绪周期量化验证]]中的情绪指标有互补关系，但更侧重于期权市场的专业投资者预期。
