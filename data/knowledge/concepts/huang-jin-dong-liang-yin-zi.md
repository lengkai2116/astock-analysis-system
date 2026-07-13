---
type: concept
title: 黄金动量因子
created: 2026-06-05
updated: 2026-06-05
tags: [gold, momentum, quantitative-trading]
related: [nasdaq-barometer-algorithm, duo-yin-zi-dong-tai-rong-he-mo-xing]
sources: ["research--2026-06-05.md"]
---
# 黄金动量因子

**黄金动量因子**（Gold Momentum Factor）是[[纳斯达克晴雨表算法]]中的核心因子之一。该因子利用黄金价格的高频数据（20分钟窗口）计算动量，并结合MACD、ADX、CCI等指标生成多级量化信号。

## 信号生成规则

- 当收益率均值 > 0.5且ADX > 25且MACD趋势强度 > 0 → **强看空信号** (-1.5)
- 当收益率均值 < -0.5且CCI < -100且MACD趋势强度 < 0 → **强看多信号** (+1.5)
- 其他情况返回基础方向信号

## 量价背离检测

引入自适应窗口（根据VIX动态调整股票量标准差阈值）识别顶背离和底背离信号。

## 逻辑基础

黄金作为避险资产，其价格走势与美股风险偏好通常呈负相关。当黄金价格快速上涨时，可能反映市场避险情绪升温，预示美股可能下跌；反之亦然。
