# Research Brief: A 股盘中实时行情免费数据源评估

## Question
有哪些免费的数据资源能够满足 A 股盘中实时行情获取？针对当前使用的 mootdx（通达信 TCP 协议）quotes() 返回空的问题，如何通过配置、升级或替代方案解决？同类开源项目如何解决实时行情问题？

## Scope
**In scope:**
- 所有支持 A 股（沪深北）盘中实时行情的免费数据源
- mootdx / tdxpy 库的合理使用方式、服务器配置、协议兼容性
- 同类开源量化项目中实时行情的解决方案（如 vnpy, futuquant, xtquant 等）
- HTTP 降级方案：Sina / EastMoney / Tencent / Xueqiu API 的能力与可靠性

**Out of scope:**
- 付费数据源（Wind、iFind、Tushare Pro 高级版等）
- 历史数据采集方案（仅关注盘中实时）
- Level 2 行情（仅关注 Level 1）
- 交易执行相关

## Depth
standard（5 个子代理，1 轮补充）

## Assumptions
- 环境为 macOS，无 Windows-only 方案（如通达信本地客户端插件）
- 仅需要 Level 1 实时行情（开高低收、成交量、成交额、盘口五档）
- 不需要实时 Tick 级数据

## Angles

### F1: mootdx/tdxpy 库协议兼容性分析与修复方案
深入分析 mootdx v0.11.7 + tdxpy v0.2.7 的 quotes() 返回空的根因。查阅 mootdx GitHub Issues、源码提交记录和社区讨论，寻找已知的协议兼容问题和修复方案。评估升级、降级、指定服务器等配置手段的效果。

### F2: 免费 HTTP 实时行情 API 对比（Sina/EastMoney/Tencent/Xueqiu）
系统对比多个免费 HTTP API 的可用性、延迟、数据完整性、每日请求限制。Sina hq.sinajs.cn、EastMoney push2.eastmoney.com、Tencent qt.gtimg.cn、Xueqiu xueqiu.com 等。评估哪个最适合作为 5s 轮询的降级方案。

### F3: 同类开源项目盘中实时行情方案（vnpy/QUANTAXIS 等）
研究 vnpy、QUANTAXIS、ricequant、pywencai 等知名开源量化项目中 A 股实时行情的采集架构。他们使用什么数据源？mootdx TCP 还是 HTTP 降级？如何解决断连和协议兼容问题？

### F4: GitHub 上 A 股数据采集创新方案
搜索 GitHub 上活跃的 A 股实时行情采集项目，特别是 2025-2026 年的新项目。关注新的数据源挖掘、创新封装方式和协议适配。

### F5: 通达信协议替代实现（非 mootdx 的其他方案）
研究除 mootdx 外其他可用的通达信行情协议实现：Go/Java/C# 等语言的客户端，WebSocket 代理，或直接通达信协议注入方案。评估这些方案在 macOS 环境下的可行性。

## Today
2026-07-21
