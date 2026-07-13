---
type: concept
title: 多因子选股
created: 2026-06-05
updated: 2026-06-05
tags: [quantitative-investing, factor-model, portfolio-construction]
related: [SDF-xishu-xing-zhenglun, yinzi-youxiao-xing-jianyan-tixi, jiqi-xuexi-hecheng-yinzi-guonihe-kongzhi, fengge-shibian-xing, yinzi-shixiao-yu-guodu-youhua, CSCV, gaojie-yinzi-moxing, Fama-French-wu-yinzi, Carhart-si-yinzi, Lasso-huigui, GRS-tongjiliang, er-jie-sui-ji-zhan-you, Fama-MacBeth-huigui]
sources: ["research--2026-06-05.md"]
---
# 多因子选股

多因子选股是通过综合多个有效因子信号构建投资组合以获取超额收益的量化策略框架。本文档基于最新学术研究，更新了关于最优因子数量的核心结论。

## 最优因子数量：动态而非固定

最新研究表明，最优因子数量取决于研究目标、方法和市场环境，不存在一个固定的"魔法数字"。

### 不同场景下的参考数量

- **学术定价模型**：8–15个因子（如M8、10-factor SSD模型）
- **Beta对冲组合**：5–6个基准因子加2–3个高阶项
- **主动选股策略**：10–20个有效因子（经IC/IR筛选和正交化后）
- **机器学习合成因子**：可通过降维将上百个因子压缩至5–10个主成分

### 综合框架

建议采用以下流程确定最优因子数量：

1. **理论驱动**：从[[Fama-French五因子模型]]、Barilla-Shanken因子等已被广泛验证的模型中选取基础因子集（约6–10个）。
2. **实证筛选**：利用[[GRS统计量]]、HDA检验或[[二阶随机占优]]（SSD）框架进行前向/后向选择，控制模型大小在8–15个。
3. **高阶项补充**：若基础因子集解释力不足，考虑加入平方项和交互项（选3–7个），但需注意[[过拟合]]风险。
4. **过拟合检验**：使用[[组合对称交叉验证]]（CSCV）计算PBO，并采用滚动窗口验证样本外稳健性。
5. **市场适应**：考虑[[风格时变性]]，当市场结构发生变化时，需动态调整因子集。

## A股市场特殊性

Mai等（2025）的A股实证显示，特征选择后仅需5个关键因子即可解释85%以上样本外收益，暗示A股的最优因子数量可能少于美股。这可能与A股散户主导、政策驱动、T+1机制等市场特质有关。