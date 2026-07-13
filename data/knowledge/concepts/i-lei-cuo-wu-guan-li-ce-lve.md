---
type: concept
title: I类错误管理策略
created: 2026-06-07
updated: 2026-06-07
tags: [type-error, risk-management, signal-quality, verification]
related: [i-lei-cuo-wu, yu-yi-ge-li-jiao-yi, liang-jia-xing-tai-da-fen-xi-tong, shi-chang-zhuang-tai-guo-lv, qing-xu-zhou-qi-si-jie-duan-mo-xing, shuang-ai-jiao-cha-yan-zheng-yu-rong-duan-ji-zhi, duo-ceng-shou-suo-yu-zheng-ze-hua-kuang-jia, bing-xiang-li-mei-you-tang-guo-yuan-ze, zu-he-dui-cheng-jiao-cha-yan-zheng-cscv]
sources: ["research-i-2026-06-07.md"]
---
# I类错误管理策略

本页面系统阐述I类错误（假阳性）在交易决策中的三段式管理框架：事前防范、事中控制、事后评估。

## 事前防范：信号质量设计

- **严格定义"进入信号"**：从模糊形态（如"底部放量"）转化为可量化的、多条件同时满足的规则。使用[[量价形态打分系统]]，要求总分超过阈值（如70分）才触发买入，降低单因子假阳性。
- **引入[[市场状态过滤]]**：只在确定性较强的市场状态下（如[[情绪周期四阶段模型]]中的冰点末期或复苏初期）执行开仓，在其他时段暂时隔离交易冲动。

## 事中控制：多重验证

- **[[双AI交叉验证与熔断机制]]**：两个独立AI系统必须都给出买入信号才执行；若信号冲突，启动熔断暂停交易。
- **逐层确认**：遵循[[多层收缩与正则化框架]]，从大类资产选择→行业选择→个股选择→入场时机，每一层通过后才进入下一层，逐层筛除假信号。

## 事后评估：回收视野

- 将I类错误的损失视为**必要的研究成本**。遵循[[冰箱里没有糖果原则]]：剔除后的股票即使后续上涨，也不应追回，避免用事后视角合理化原本的决策误差。
- 使用[[组合对称交叉验证（CSCV）]]定期评估策略整体的过拟合概率，如果PBO过高，说明当前策略中存在大量I类错误的隐患，应重构信号体系。

## 参见

- [[I类错误]]
- [[II类错误]]
- [[I类错误与II类错误-投资]]
- [[语义隔离（交易）]]