---
name: font-specification-complete
description: 字体规范体系已制定完成（212号方案），含7级+1Badge标准、12页面关键信息映射、对比度核查
metadata:
  type: reference
---

字体标准体系（212号）已制定完成：P0-l 24px Bold → Badge 10px Bold 共8级。调研覆盖 OakView/Fintech Dashboard/B端规范/WCAG 2.1。base.css需新增8个`--fs-*`字体token变量。`--text-muted` #64748B 对比度4.36:1略低，建议调至#6B7280（4.81:1）。**Phase A**可快速修复4个低位超小字体页（indicator-ide/backtest/playback/badge-new），**Phase B**批量标准化10px→12px/11px和表格数据统一13px。不改变结构，仅通过base.css token和font-size调整实现。
