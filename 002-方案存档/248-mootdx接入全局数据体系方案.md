---
title: mootdx 接入全局数据体系方案
type: 技术方案
date: 2026-07-06
status: ⏹️ 已过时（已被292号方案替代。mootdx TCP 因通达信协议更新于2026-07-20断裂，`quotes()`/`bars()`返回空，主数据源已变更为东财HTTP API）
superseded_by: 292
---

# mootdx 接入全局数据体系方案

> 基于 mootdx(TCP) 替代 AKShare(HTTP) 实时行情采集的架构重构方案
>
> 前置验证：[[mootdx-feasibility-confirmed]] — 45字段L1行情 TCP 连通性已验证

---

## 1. 现状问题

### 1.1 当前盘中数据架构

```
AkshareCollector (5线程 · ~850行 · akshare_collector.py)
┌──────────┐ ┌────────┐ ┌──────┐ ┌────┐ ┌──────┐
│快照(15s) │ │涨跌(30s)│ │板块(5m)│ │分钟│ │龙虎(30m)│
└──────────┘ └────────┘ └──────┘ └────┘ └──────┘
  全局令牌桶 · monkey-patch requests · 三层HTTP兜底
  WAF反爬对抗 · push2子域名重写 · curl/urllib/requests
  三重写入 PG + DuckDB + InMemoryStateStore
```

### 1.2 7 个痛点

| # | 问题 | 代码位置 | 根源 |
|:--|------|---------|------|
| 1 | **全局令牌桶** | `_throttle()` / `_throttle_bump_success/failure` | 东方财富限流常态化，5线程共享一个令牌桶 |
| 2 | **monkey-patch requests** | `_collect_patched_get` / `_collect_patched_session_request` | 重写 `requests.get` + `Session.request`，侵入式 |
| 3 | **三层 HTTP 兜底** | `_em_get()` 的 urllib→requests→curl 三层回退 | 85行代码处理 WAF 断连，每次失败走三层 |
| 4 | **PG 三重写入** | 每线程均写 PG (snapshot/top_stocks/sectors/等 8 类) | PG 盘中数据**无下游消费方**，Flask 路由全走 InMemoryStateStore |
| 5 | **WAF 反爬对抗** | push2 子域名重写 / UA 伪装 / 保温期超时 / 子域名限流检测 | HTTP REST 在东方财富 CDN 面前是被动方 |
| 6 | **可靠性归零** | 5 线程在当前 Claude 代理环境下全部 RemoteDisconnected | HTTP 协议被代理拦截，TCP 直连无此问题 |
| 7 | **数据字段有限** | 快照仅 20 字段(push2 API 返回) | mootdx get_security_quotes 返回 45 字段 + 五档盘口 |

---

## 2. 目标架构

### 2.1 总体设计

```
mootdx Collector (1-2线程)
┌──────────────────────────────────────┐
│ L1快照线程 (1-3s TCP直连)            │
│ · get_security_quotes(全市场)        │ ← TCP 二进制协议，无 WAF
│ · 45字段 + 五档盘口                  │
│ · 从快照自算涨跌榜/涨跌停池           │
└──────────────┬───────────────────────┘
               │
AKShare (低频补充, 隔4线程复用)
┌──────────────┴───────────────────────┐
│ 板块排行(30min) · 概念排行(30min)     │ ← 保留，降频
│ 龙虎榜(30min) · 新闻(30min)          │
│ 分钟K线(5min, 全市场+多频段)         │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│ InMemoryStateStore                   │ ← 完全不变
│ + WsBridge → SocketIO → 前端         │
└──────────────────────────────────────┘
```

### 2.2 关键设计原则

1. **TCP 为主，HTTP 为辅**：mootdx 走通达信 TCP 二进制协议(L1行情/分钟线)，AKShare HTTP 仅为低频补充(板块/龙虎榜/新闻)
2. **去 monkey-patch**：不再重写 `requests.get` / `Session.request`
3. **去令牌桶**：TCP 无 HTTP 限流概念，1线程单发无需令牌桶
4. **去 PG 盘中写入**：移除 8 类盘中数据到 PostgreSQL 的三重写入（无下游消费方）
5. **计算替代采集**：涨跌幅榜/涨跌停池从全市场快照自算，不再单独 HTTP 采集
6. **降频稳定**：AKShare 保留调用降为 30min+ 间隔，低频不受限
7. **存储不受影响**：InMemoryStateStore → WsBridge 链路完全不变，盘后 DuckDB 日线不变

### 2.3 mootdx vs AKShare 对比

| 维度 | AKShare(东方财富 HTTP) | mootdx(通达信 TCP) |
|------|----------------------|-------------------|
| 协议 | HTTP REST，WAF 反爬重灾区 | TCP 二进制，无 WAF |
| 网络依赖 | 需 HTTP_PROXY 清除，CDN 限流 | 直连，仅需 TCP 可达 |
| 稳定性 | 东方财富频繁断连(RemoteDisconnected) | 券商基础设施，15年稳定 |
| 延迟 | 15-30s 轮询 + 限流等待 | 1-3s TCP 直连 |
| 数据字段 | ~20 字段(push2 子集) | 45 字段 + 五档盘口(bid/ask x5) |
| 反爬风险 | ❌ 持续对抗 | ✅ 基础设施协议 |
| IP 池 | 需保温期 / 子域名重写 | 无需，TCP 直连 |

---

## 3. 具体变更

### 3.1 Thread 1: 全市场 L1 快照（mootdx 替代）

| 项目 | 当前 | mootdx 后 |
|------|------|-----------|
| 数据源 | `push2.eastmoney.com/api/qt/clist/get` | `client.client.get_security_quotes()` |
| 协议 | HTTP REST | TCP 二进制 |
| 间隔 | 15s（含全局限速等待） | 3-5s（TCP 直连） |
| 字段 | ~20 (f2/f3/f4/.../f12/f14/...) | 45 字段 + 五档盘口 |
| 全市场覆盖 | 5000只（需分页 pz=5000） | 全市场 5000+ 只 |
| 稳定性 | 需 WAF 对抗 | 通达信协议，无对抗 |

**输出字段映射（45字段关键子集）：**

| 字段 | 含义 | mootdx 列名 | 当前字段 |
|------|------|-----------|---------|
| 代码 | 股票代码 | `code` | `f12` |
| 名称 | 股票名称 | `code_name` | `f14` |
| 最新价 | 当前价格 | `price` | `f2` |
| 昨收 | 昨日收盘 | `last_close` | `f18` |
| 开盘 | 今日开盘 | `open` | `f17` |
| 最高 | 今日最高 | `high` | `f15` |
| 最低 | 今日最低 | `low` | `f16` |
| 成交量 | 成交手数 | `volume` | `f21/f5` |
| 成交额 | 成交金额 | `amount` | `f20/f6` |
| 涨跌额 | 涨跌额 | `price - last_close` | `f4` |
| 涨跌幅 | 涨跌百分比 | →自算 | `f3` |
| 买一~五价 | 五档买盘 | `bid1~bid5` | 无 |
| 卖一~五价 | 五档卖盘 | `ask1~ask5` | 无 |
| 买一~五量 | 五档买量 | `bid1_vol~bid5_vol` | 无 |

### 3.2 Thread 2: 涨跌榜 + 涨跌停池（从快照自算，不再独立采集）

| 项目 | 当前 | mootdx 后 |
|------|------|-----------|
| 数据源 | `push2 HTTP` 独立请求 | 从 Thread 1 快照排序 |
| 间隔 | 30s 独立线程 | 跟随快照刷新(3-5s) |
| 涨跌榜 | po=1(涨幅)/po=0(跌幅) top20 | 按 change_pct 排序取 top20 |
| 涨停池 | AKShare stock_zt_pool_em | 按涨跌幅 ≥9.8% + 价格≥昨收识别 |
| 跌停池 | AKShare stock_zt_pool_dtgc_em | 按涨跌幅 ≤-9.8% + 价格≤昨收识别 |
| 额外 | 无 | 近涨停(≥7%)/近跌停(≤-7%) 标记 |

**优势**：无需独立 HTTP 采集、涨跌停条件可自定义（不依赖东方财富接口定义）、刷新频率从 30s→3-5s

### 3.3 Thread 3: 板块排行 + 概念排行（AKShare 保留，降频）

| 项目 | 当前 | mootdx 后 |
|------|------|-----------|
| 数据源 | AKShare | AKShare（不变） |
| 间隔 | 5min | **30min**（低频不受限） |
| 修改 | — | 移除 PG 写入 |

### 3.4 Thread 4: 分钟 K 线（评估是否切换）

| 项目 | 当前 | mootdx minutes API |
|------|------|-------------------|
| 数据源 | AKShare stock_zh_a_hist_min_em | mootdx `client.minutes()` |
| 协议 | HTTP REST | TCP 二进制 |
| 范围 | 仅自选股（watchlist） | **全市场任意股票** |
| 频段 | 仅 5min | 1min / 5min / 15min / 30min / 60min |
| 间隔 | 5min | 5min |
| 可处理当日完整数据 | ❌ 仅今日 | ✅ 含历史 |
| 稳定性 | AKShare 可能受限 | TCP 直连 |

**建议**：切换到 mootdx。核心优势是从"仅自选"扩展到"全市场任意股票"，且为 TCP 直连更可靠。如切换，Thread 4 的 watchlist 依赖可移除。

### 3.5 Thread 5: 龙虎榜 + 新闻（AKShare 保留，不变）

| 项目 | 当前 | mootdx 后 |
|------|------|-----------|
| 数据源 | AKShare | AKShare（不变） |
| 间隔 | 30min | 30min（不变） |
| 修改 | — | 移除 PG 写入 |

### 3.6 可移除的代码清单

| 文件/模块 | 代码段 | 行数 | 原因 |
|-----------|--------|------|------|
| `akshare_collector.py` 全局令牌桶 | `_throttle()` / `_throttle_bump_success/failure()` / `_collect_interval` / `_consecutive_success`/`_collect_lock` | ~40行 | mootdx TCP 无需限速 |
| `akshare_collector.py` monkey-patch | `_collect_patched_get` / `_collect_patched_session_request` + 拦截注册 | ~30行 | 不再 requests 做 HTTP |
| `akshare_collector.py` 三层兜底 | `_em_get()` 的 urllib→requests→curl 三层回退逻辑 | ~55行 | 仅 HTTP 需要 |
| `akshare_collector.py` PG 写入 | `_get_pg()` + 每线程的 pg 调用 (8 处 upsert) | ~50行 | PG 盘中数据无消费方 |
| `akshare_collector.py` 连接测试 | `test_eastmoney_connectivity()` | ~20行 | 不再依赖东方财富 push2 |
| `akshare_collector.py` Thread 2 涨跌榜 | `_collect_top_stocks()` 完整线程 | ~40行 | 从快照自算 |
| `akshare_collector.py` _collect_sector_and_limit | `ak.stock_zt_pool_em` / `stock_zt_pool_dtgc_em` 涨跌停部分 | ~60行 | 从快照自算 |
| `akshare_collector.py` watchlist 机制 | `_watchlist` / `update_watchlist()` / 关联 Thread 4 | ~30行 | 如切换分钟线到 mootdx 则移除 |
| `realtime_pg.py` | 整个文件（8 个 upsert 函数 + 连接配置） | ~200行 | 如移除 PG 盘中写入 |
| **合计** | | **~525行** | |

### 3.7 新增代码估算

| 文件 | 新增量 | 说明 |
|------|--------|------|
| `mootdx_collector.py` | ~400行 | mootdx 采集器管理器 |
| `akshare_collector.py` 瘦身 | 从~850行→~400行 | 保留 Thread 3/5 的 AKShare 低频采集 |
| **净减少** | **~450行** | |

---

## 4. 不受影响的模块

| 模块 | 说明 |
|------|------|
| `InMemoryStateStore` | 所有采集仍写入 store，接口完全不变 |
| `WsBridge → SocketIO → 前端` | WebSocket 推送链路不变 |
| `realtime.py` Flask 路由 | 继续从 store 读取，代码零修改 |
| `TushareProvider` / `DataManager` | 盘后日线同步不变 |
| `DuckDB daily_cache` | 盘后归档不变 |
| `enhanced_cache_manager.py` | DuckDB 缓存层不变 |
| 策略引擎(Chanlun/VP/多因子等) | 全部基于日线，不变 |
| `_项目运行手册.md` | 无需修改 |

---

## 5. 实施步骤

### Phase A: 创建 mootdx_collector.py（~1天）

1. 新建 `backend/app/data/mootdx_collector.py`
   - mootdx Quotes 客户端工厂（惰性初始化，支持重连）
   - L1 快照采集函数（`collect_market_snapshot()`）→ 写入 `InMemoryStateStore`
   - 从快照自算涨跌榜 + 涨跌停池 → 写入 `InMemoryStateStore`
   - 单线程运行时管理（`_CollectThread` 复用现有基类，或新建更轻量的 `MootdxThread`）
   - 采集完成后调用 `ws_bridge.on_collect_complete()`
2. 分钟 K 线采集（如切换到 mootdx）：`collect_minute_kline()` → 全市场/指定股票
3. AKShare 低频线程保留（`CollectThread` 复用）：板块/概念/龙虎榜/新闻

### Phase B: 瘦身 akshare_collector.py（~0.5天）

1. 移除全局令牌桶相关代码
2. 移除 monkey-patch (requests.get / Session.request 重写)
3. 移除 `_em_get()` 三层 HTTP 兜底
4. 移除 PG 写入代理 `_get_pg()` 及相关调用
5. 移除独立涨跌榜采集 `_collect_top_stocks()`
6. 移除涨跌停池 AKShare 采集部分
7. 移除 `test_eastmoney_connectivity()` 和 watchlist 机制
8. Thread 3/5 降频为 30min 并清理写入

### Phase C: 移除 realtime_pg.py（~0.5天）

1. 删除 `backend/app/data/realtime_pg.py`
2. 检查是否有其他模块导入 py（`grep -rn 'realtime_pg'`）
3. 清理 `__init__.py` 注册

### Phase D: 移除 PG 盘中写入配置（~0.5天）

1. 清理 244 号方案遗留的 PG 盘中实时表定义（如有）
2. 确认 `backend/app/__init__.py` 无相关注册
3. 确认 `_项目运行手册.md` 无相关配置引用

### Phase E: 验证（~0.5天）

1. `InMemoryStateStore` 读写验证：快照 / 涨跌榜 / 涨跌停池 / 分钟线
2. WsBridge 推送验证：`on_collect_complete` 触发 WebSocket 推送
3. `realtime.py` 路由验证：REST API `/api/v3/realtime/...` 返回正确数据
4. AKShare 低频数据验证：板块 / 概念 / 龙虎榜 / 新闻
5. 盘后 Tushare 日线同步不受影响验证

### 总工时

| Phase | 工时 | 依赖 |
|-------|------|------|
| A. mootdx_collector.py 新建 | ~1天 | mootdx 在正式机器已验证连通 |
| B. akshare_collector.py 瘦身 | ~0.5天 | Phase A 完成 |
| C. realtime_pg.py 移除 | ~0.5天 | Phase B 完成 |
| D. PG 配置清理 | ~0.5天 | Phase C 完成 |
| E. 验证 | ~0.5天 | Phase D 完成 |
| **合计** | **~3天** | |

---

## 6. 风险与注意事项

1. **mootdx 在正式机器上必须验证连通**：当前开发环境 TCP 被 Claude 代理拦截无法用，需在正式运行 Mac 上实测 `Quotes.factory()` + `quotes()` 返回非空 DataFrame
2. **mootdx 版本兼容**：当前 0.11.7，内部使用 tdxpy 库。需确认 `get_security_quotes` 参数签名（`all_stock` 为 `(market, code)` 列表）
3. **高可用设计**：mootdx 断连后自动重试 + 退避 + AKShare 兜底（如 mootdx 不可用则降级到 AKShare 全量采集）
4. **与 244 号方案的衔接**：Phase D 须确认无其他模块引用 `realtime_pg`，否则单独移除会导致 ImportError
5. **mootdx 不支持北交所**：`get_security_quotes` 检测到北交所代码会返回 None，需跳过或单独用 AKShare 补充
6. **涨跌停自算精度**：从快照按涨跌幅阈值判断（≥9.8%），与东方财富官方涨跌停池可能存在边缘差异（如新股首日 44% 等特殊规则），可在后续迭代中补充

---

## 7. 遗留问题

| # | 问题 | 类型 | 建议 |
|:--|------|------|------|
| 1 | mootdx 正式环境中 TCP 7709 端口是否可达？ | 前置条件 | 需用户确认 |
| 2 | 分钟 K 线是否切换到 mootdx？ | 待决策 | 建议切换，理由见 §3.4 |
| 3 | PG 盘中写入是否彻底移除？ | 待决策 | 建议移除，理由见 §1.2#4 |
