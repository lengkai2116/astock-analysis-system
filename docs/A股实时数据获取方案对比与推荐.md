# A股实时数据获取方案对比与推荐

评估日期：2026-05-25

## 结论

最优方案：采用 **QMT/miniQMT xtquant 本地行情推送** 作为主实时源，保留 **Tushare 日线/基础/资金流/特色数据** 作为研究数据源，增加 **AkShare 或 efinance** 作为免费降级源。

理由：

- 当前系统是个人/本地化 A 股分析系统，不是面向公众转售行情的数据平台。
- 系统已经有 Flask-SocketIO、Redis、实时推送模块，适合接入一个本地行情桥接进程。
- QMT/miniQMT 提供订阅式实时行情、tick、五档/Level-2 相关能力，工程上比轮询网页源稳定。
- 官方交易所 Level-1/Level-2 合规性最好，但成本、资质、专线/授权复杂度明显高于本项目当前阶段。
- Tushare、AkShare、efinance 的实时接口多属于爬虫或网页数据源包装，适合研究展示，不适合作为生产级实时主源。

## 当前系统状态

本项目已有实时服务框架：

- `backend/app/routes/realtime.py`：Socket.IO 推送、Redis 发布订阅、订阅自选股、订阅 K 线。
- `frontend/vue-project/src/services/socketService.js`：前端 Socket.IO 连接与重连。
- `backend/app/data/akshare_provider.py`：已有 AkShare 实时 provider 雏形。

但当前主流程存在关键问题：

- `RealtimeDataService._get_stock_realtime_data()` 实际优先调用 `TushareProvider.get_daily_data()`，这不是实时行情。
- `AkShareRealtimeProvider` 已导入但没有成为主实时源。
- 自选股订阅参数没有真正驱动 provider 拉取对应列表，服务仍使用固定 `default_watchlist`。
- 实时服务在模块 import 时自动启动，不利于生产部署和多 worker 管理。

## 方案对比

| 方案 | 数据类型 | 延迟/频率 | 稳定性 | 合规性 | 成本 | 适合场景 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 交易所官方 Level-1/Level-2 | 官方实时行情、逐笔、盘口 | 最优 | 最优 | 最优 | 高 | 机构、商业数据服务、严肃实盘 | 长期目标，不适合当前 MVP |
| QMT/miniQMT xtquant | 本地终端行情、tick、五档、订阅推送 | 好 | 好 | 依赖券商/终端授权 | 中低 | 个人本地量化、实盘监控 | 推荐主方案 |
| 同花顺 iFinD / 东方财富 Choice / Wind | 商业终端 API | 好 | 好 | 较好 | 中高 | 研究机构、投研系统 | 预算足够可选 |
| Tushare realtime_quote | 新浪/东财爬虫实时快照 | 一般 | 一般 | 研究学习 | 低 | 辅助展示、低频看盘 | 只做降级 |
| AkShare | 新浪/东财等网页源实时行情 | 一般 | 一般 | 研究学习 | 免费 | 快速原型、辅助看盘 | 只做降级 |
| efinance | 东方财富网页源包装 | 一般 | 一般 | 研究学习 | 免费 | 批量快照、快速开发 | 可作为降级 |
| pytdx/mootdx 通达信 | 通达信行情服务器 | 一般 | 中 | 灰色边界 | 免费 | 个人研究 | 不建议作为主源 |
| BaoStock | 历史行情为主 | 不适合 | 好 | 研究 | 免费 | 历史回测 | 不适合实时 |

## 最优推荐架构

建议把实时行情做成独立 provider 层：

```text
QMT/miniQMT 客户端
    ↓ xtquant.subscribe_quote / get_full_tick
realtime_provider_qmt.py
    ↓ 标准 QuoteEvent
Redis Pub/Sub 或 Stream
    ↓
Flask-SocketIO realtime service
    ↓
前端自选股 / 指标 IDE / 报告中心
```

Provider 优先级：

1. `QMTRealtimeProvider`：主实时源。
2. `TushareRealtimeProvider`：低频快照降级源。
3. `AkShareRealtimeProvider` 或 `EFinanceRealtimeProvider`：免费降级源。
4. `CachedDailyProvider`：非交易时段或全部实时源失败时，回退到本地日线缓存。

## 推荐实现路径

### 第一阶段：修正当前实时服务

- 抽象 `BaseRealtimeProvider`。
- 修改 `RealtimeDataService`，让其使用 provider，而不是直接调用 `tushare.get_daily_data()`。
- 订阅时使用前端传入的 watchlist，而不是固定 `default_watchlist`。
- 增加 provider 状态字段：`source`、`latency_ms`、`quote_time`、`is_realtime`、`fallback_reason`。
- 去掉模块 import 时自动启动，改为由应用启动脚本或 scheduler 控制。

### 第二阶段：接入 QMT/miniQMT

新增 `backend/app/data/qmt_realtime_provider.py`：

- 使用 `xtquant.xtdata.connect()` 连接本地 miniQMT。
- 使用 `xtdata.subscribe_quote()` 订阅自选股 tick。
- 使用 `xtdata.get_full_tick()` 获取当前快照。
- 将 QMT 字段统一转换为系统字段：
  - `ts_code`
  - `name`
  - `price`
  - `pre_close`
  - `open`
  - `high`
  - `low`
  - `volume`
  - `amount`
  - `bid_price_1`
  - `ask_price_1`
  - `bid_vol_1`
  - `ask_vol_1`
  - `quote_time`
  - `source`

### 第三阶段：建立降级策略

建议策略：

```text
交易时段:
  QMT 可用 -> QMT
  QMT 不可用 -> Tushare realtime_quote 或 efinance/AkShare
  全部失败 -> 最近缓存 + 标记 delayed

非交易时段:
  本地日线缓存 + 最新收盘行情
```

### 第四阶段：持久化和监控

- Redis 保存最近快照。
- DuckDB 可选保存 1 分钟聚合行情，不建议保存全量 tick，除非明确有存储和合规需求。
- 增加 `/api/v3/market/realtime/status`，展示当前数据源、延迟、最近更新时间、失败次数。

## 为什么不推荐免费网页源作为主方案

AkShare、efinance、Tushare realtime_quote 的优势是接入快、成本低，但它们共同问题明显：

- 多数依赖新浪/东方财富等网页接口，字段和反爬策略可能变化。
- 高频轮询容易触发限流。
- 批量刷新延迟和稳定性不如本地终端订阅。
- 合规边界不适合商业化或对外分发行情。
- 一旦用于策略信号，行情中断或延迟会直接污染信号。

因此它们适合做“看盘展示降级源”，不适合作为主实时源。

## 为什么推荐 QMT/miniQMT

QMT/miniQMT 的优势正好匹配本项目：

- 本地客户端连接，适合个人电脑长期运行。
- 支持订阅式推送，不需要高频轮询网页。
- 可获取实时 tick、行情快照、五档数据，后续还能扩展交易接口。
- Python 接入成本较低，可直接接入当前 Flask/Redis/Socket.IO 架构。
- 对当前系统来说，改造集中在 provider 层，不需要重构前端。

限制：

- 需要安装并登录 miniQMT/QMT 客户端。
- 依赖券商支持和账号权限。
- 如果要对外展示或商业使用行情，仍需确认授权边界。
- Docker 容器内直接连接本机 GUI 客户端可能麻烦，建议 QMT bridge 先运行在宿主机，后端通过本地 HTTP/WebSocket/Redis 接收。

## 最终建议

短期最优落地：

1. 先修正当前实时服务架构，避免用 Tushare 日线冒充实时行情。
2. 接入 QMT/miniQMT 作为主实时源。
3. 保留 AkShare/efinance/Tushare realtime_quote 作为降级源。
4. 前端明确展示数据源和是否实时。

中长期最优落地：

- 若系统只用于个人研究和本地监控：继续 QMT/miniQMT。
- 若系统要服务多人或商业化：采购交易所授权行情或合规商业数据 API。
- 若只是日线/分钟级策略研究：Tushare + DuckDB 缓存仍是主力数据源，实时行情只作为监控和触发提示。

总体判断：**当前系统最优方案是 QMT/miniQMT 主实时源 + Tushare 研究数据 + AkShare/efinance 降级源**。

## 参考来源

- 迅投知识库 XtQuant.XtData 行情模块：https://dict.thinktrader.net/nativeApi/xtdata.html
- AKShare 股票数据文档：https://akshare.akfamily.xyz/data/stock/stock.html
- efinance GitHub 项目说明：https://github.com/Micro-sheep/efinance
- 上证所信息网络有限公司行情服务：https://www.sseinfo.com/services/assortment/market/
- 上证所 Level-2 行情介绍：https://www.sseinfo.com/services/assortment/level2/
- 深圳证券信息有限公司深市行情授权：https://www.szsi.cn/cpfw/fwsq/hq/hlhqfw.htm
