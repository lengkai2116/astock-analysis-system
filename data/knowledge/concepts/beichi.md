---
type: concept
title: 背驰
created: 2026-05-31
updated: 2026-05-31
tags: [缠论, 动力学, 背驰, 买卖点]
related: [chanlun, zhongshu, xian-duan, bi]
sources: ["research--2026-05-31.md"]
---
# 背驰

背驰是[[chanlun|缠论]]中用于判断趋势转折的核心信号，指价格与指标（如MACD）的背离。在缠论中，背驰通常通过比较前后两段走势的MACD面积、斜率等指标来识别。背驰是缠论买卖点判断的核心依据之一，也是量化实现中重要的特征工程方向。[[chan-py]]等项目在计算自定义动力学买卖点（cbsp）时，会提取数百个与背驰相关的特征。