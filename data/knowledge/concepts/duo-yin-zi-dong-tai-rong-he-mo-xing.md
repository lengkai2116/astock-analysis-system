---
type: concept
title: 多因子动态融合模型
created: 2026-06-05
updated: 2026-06-05
tags: [quantitative-trading, factor-model, machine-learning]
related: [nasdaq-barometer-algorithm, bo-dong-lu-wei-xiao-yin-zi, huang-jin-dong-liang-yin-zi, duo-ceng-rong-duan-ji-zhi, yin-zi-shi-xiao-yu-guo-du-you-hua, gui-ze-yin-qing-ml-shuang-yin-qing-qu-dong]
sources: ["research--2026-06-05.md"]
---
# 多因子动态融合模型

**多因子动态融合模型**是[[纳斯达克晴雨表算法]]的核心方法论。该模型根据当前市场波动率水平（由VIX指数衡量）自适应调整各因子的贡献权重，实现动态择时。

## 核心机制

模型采用动态权重矩阵，根据VIX指数将市场分为三个波动率区间，每个区间对应不同的因子权重配置：

| 市场波动率水平 | 黄金因子权重 | 波动率因子权重 | ML修正权重 | 市场情绪权重 |
| --- | --- | --- | --- | --- |
| VIX < 15 | 50% | 25% | 15% | 10% |
| 15 ≤ VIX < 25 | 35% | 40% | 15% | 10% |
| VIX ≥ 25 | 20% | 45% | 25% | 10% |

## 核心因子

- **[[黄金动量因子]]**：利用黄金价格高频数据计算动量，结合MACD、ADX、CCI等指标生成多级量化信号。
- **[[波动率微笑因子]]**：基于CBOE期权数据，使用[[SVI模型]]构建隐含波动率曲面，计算偏度指数。
- **市场情绪因子**：整合FinBERT新闻情感分析、社交媒体热度、资金流向等。
- **机器学习增强模块**：[[LSTM]]时序预测网络与[[PPO]]强化学习动态权重调整。

## 信号合成

各因子信号通过动态权重矩阵加权合成，形成最终的晴雨表分数（取值范围[-100, 100]）。

## 与现有维基的连接

该模型是[[AI量化策略]]、[[强化学习]]、[[LSTM]]等概念在美股市场的一个具体、前沿的应用实例。其动态权重思想与[[规则引擎+ML双引擎驱动]]、[[市场状态识别（10种）]]等概念有共通之处。
