---
type: concept
title: Fama-MacBeth回归
created: 2026-06-05
updated: 2026-06-05
tags: [asset-pricing, factor-model, cross-sectional-regression]
related: [duo-yinzi-xuan-gu, gaojie-yinzi-moxing, SDF-xishu-xing-zhenglun]
sources: ["research--2026-06-05.md"]
---
# Fama-MacBeth回归

Fama-MacBeth回归是截面收益检验的经典方法，由Fama & MacBeth（1973）提出。该方法分为两步：第一步，对每个时间截面进行横截面回归，估计因子暴露的收益率；第二步，对时间序列的估计值进行统计推断。

## 在因子筛选中的应用

Borri等（2026）使用前向选择Fama-MacBeth回归，从57个候选高阶因子中选出7个高阶因子，将截面调整R²从31.2%提升至59%。

## 优势与局限

- **优势**：能够处理截面相关性，提供稳健的标准误估计。
- **局限**：假设因子暴露在时间上稳定，可能无法捕捉时变因子暴露。