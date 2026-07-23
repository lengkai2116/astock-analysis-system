---
title: mootdx 全面能力调研与数据获取提升方案
type: 技术调研报告
date: 2026-07-06
status: ⏹️ 已过时（已被292号方案替代。mootdx TCP 因通达信协议更新于2026-07-20断裂，`quotes()`/`bars()`返回空）
superseded_by: 292
---

# mootdx 全面能力调研与数据获取提升方案

> **背景：** 248号方案（mootdx 接入全局数据体系）Phase 0~E 全量实施后，系统盘中主数据源已从 AKShare HTTP 变更为 mootdx TCP。Phase E 端到端验证发现 4 项遗留问题，本报告对 mootdx 全部 API 能力进行系统性调研，评估解决各遗留问题的可行方案。

---

## 一、mootdx StdQuotes 全部 API 清单

通过 `dir(client)` 遍历，StdQuotes 共有 29 个公开方法：

### 1.1 已使用的方法（248号方案现有）

| 方法 | 用途 | 当前状态 |
|------|------|---------|
| `Quotes.factory()` | 创建通达信 TCP 连接 | ✅ Phase 0 已验证 |
| `stocks()` | 获取全市场股票列表（27530 只） | ✅ 名称映射用 |
| `quotes()` | 获取 L1 实时行情（46 字段 + 五档盘口） | ✅ 主采集方法 |

### 1.2 新发现的关键方法

| 方法 | 返回值 | 发现用途 | 解决遗留问题 |
|------|--------|---------|-------------|
| **`index(code)`** | OHLC + up_count/down_count 日线 DataFrame（800 行） | 指数历史日线，含上涨/下跌家数 | ✅ 问题①指数代码 |
| **`block()`** | 384K 行板块隶属数据（blockname/block_type/code_index/code） | 股票↔板块映射关系 | ✅ 问题③板块排行 |
| **`transactions(code, start, count)`** | 今日逐笔成交（time/price/vol/buyorsell） | 分笔成交 Tick 数据（buyorsell: 0=卖,1=买） | ✅ 新增能力 |
| **`bars(symbol, frequency, start, count)`** | OHLC K 线（freq=9 日线, freq=5 周线） | 日线/周线历史数据 | ⚠️ 备选 |
| **`get_k_data(code, start, end)`** | OHLC 日线 DataFrame | 日线查询 | ⚠️ 备选 |
| **`index_bars(code)`** | 指数 K 线（类似 index()） | 指数日线备选 | ⚠️ 备选 |
| **`minute(code)`** | 当日分时线（price/vol/volume, 240 点） | 分时图（无 OHLC） | ℹ️ 仅 3 列 |
| **`minutes(code, freq)`** | 多日分时线（price/vol/volume） | 同上 | ℹ️ 仅 3 列 |

### 1.3 其他方法（暂未深入调研）

`finance()`, `F10()`, `F10C()`, `k()`, `ohlc()`, `transaction()`, `pool()`, `xdxr()`, `stock_all()`, `stock_count()`, `bestip()`, `reconnect()`, `server`, `traffic`, `verbose`

---

## 二、四项遗留问题的解决方案评估

### 问题①：指数代码格式不兼容 — ✅ 有解

**根因：** `get_stock_market('000001')` 因前缀规则返回 market=0（SZ），但上证指数实际是上海市场（SH）。所有 `000XXX` 代码均被误分到深圳。

**解决方案：** 改用 `client.index(code)` 单独获取指数数据。

```
client.index('000001')   # 上证指数  → OHLC + 涨跌家数 ✅
client.index('399001')   # 深证成指  ✅
client.index('399006')   # 创业板指  ✅
client.index('000016')   # 上证50    ✅
client.index('000300')   # 沪深300   ✅
```

`index()` 返回完整 OHLC 数据（open/close/high/low/vol/amount）加上 `up_count`（上涨家数）/ `down_count`（下跌家数），800 条历史数据。数据已验证为今日实时（2026-07-06 15:00 收盘数据）。

**实施建议：** 在 mootdx_collector.py 中增加 `_collect_indices()` 函数，在 `collect_market_snapshot()` 之后调用，将指数数据写入 InMemoryStateStore 的独立存储区域，供 WsBridge `_broadcast_market_indices()` 读取。无需 monkey-patch。

### 问题②：DuckDB 持久损坏 — ⚠️ 需人工操作

**根因：** DuckDB 文件锁被旧 PID 持有 + Flask 热重载 → 序列化损坏。目前 `stock_cache.db` 已彻底不可恢复。

**修复：**
```bash
rm data/duckdb/stock_cache.db*
rm data/duckdb/stock_cache.db.corrupted.*
```
DuckDB 会自动重建空库，Tushare 日终同步会重新填充。

**mootdx 替代潜力：** `bars(freq=9)` 可返回 800 行日线 OHLC 数据，覆盖 2023-03 至今。可作为 DuckDB 损坏期间的临时降级方案。但 Tushare 的数据维度更广（复权因子、资金流、财务指标），不建议完全替换。

### 问题③：AKShare HTTP 板块排行不可用 — ✅ 有解

**核心发现：** `client.block()` 返回 384,239 行板块隶属数据，包含每只股票所属的全部板块/概念/地域分类。

**block() 数据结构：**

| 列名 | 说明 | 样例 |
|------|------|------|
| `blockname` | 板块名称 | '半导体', '白酒概念', '上海板块' |
| `block_type` | TDX 内部类型编码 | 2, 49, 51, 54, 55, 57, 12336~14648 |
| `code_index` | 板块内序号 | 0, 1, 2, ... |
| `code` | 股票代码 | '600519' |

**替代方案（block() + quotes() 内存聚合）：**

```
block() → 全量板块隶属关系
    +
quotes() → 全量 L1 行情（含涨跌幅）
    ↓
内存中按 blockname 分组 → 聚合计算板块涨跌幅 → 排序输出板块排行
```

**优势：**
- 完全替代 AKShare `stock_board_industry_name_em()` / `stock_board_concept_name_em()`
- 不再依赖 HTTP，无 RemoteDisconnected 问题
- 刷新频率可提升至 ~5s（随 L1 快照一起刷新，但板块计算无需每轮都做）
- 数据更细粒度（可计算板块内涨跌比、平均换手等额外指标）

**待确认：** block_type 编码含义（哪些是行业板块、哪些是概念板块）需进一步映射。block() 仅返回板块内股票代码，不包含板块实时涨跌幅。

### 问题④：北交所数据缺失 — 🔴 待解决

**现状：** mootdx 不支持北交所。`stocks()` 列表中无真正北交所股票代码（833819 等缺失），`quotes()` 对北交所代码返回空。通达信 TCP 协议本身不传输北交所行情数据。

**可能的替代来源（待评估）：**

| 来源 | 可行性 | 实现成本 | 可靠性 |
|------|--------|---------|--------|
| AKShare `stock_zh_a_spot_em()` | 需解决 HTTP RemoteDisconnected | 低 | 依赖 EastMoney |
| Tushare `realtime_quote` | 需要高级积分（5000分以上） | 低 | 高 |
| `efinance` 库 | 轻量级 HTTP 方案 | 低 | 中 |
| 其他通达信库（`pytdx` 专业版） | 可能支持 | 中 | 需验证 |

**建议：** 暂标记为待解决。北交所占全市场成交量约 5-8%，对系统核心策略影响有限。如用户有北交所策略需求，可后续优先尝试 AKShare 或 efinance 方案。

---

## 三、新增能力机会

### 3.1 逐笔成交 Tick 数据（`transactions()`）

```python
client.transactions('000001', start=0, count=800)
# 返回: time, price, vol, buyorsell, volume
# buyorsell: 0=卖盘, 1=买盘
```

今日实时逐笔成交数据（已验证返回 800 行，覆盖 13:53~14:59 今日交易）。可用于：
- 盘中主力资金流向监控
- 大单追踪（筛选 vol 超过阈值的交易）
- Tick 级 K 线重构

### 3.2 日线 OHLC 备选（`bars(freq=9)`）

```python
client.bars('600519', frequency=9, start=0, count=800)
# 返回: open/close/high/low/vol/amount + datetime, 800行
```

800 个交易日历史，从 2023-03 至今。DuckDB 损坏期间可作为 Tushare 降级备选。

### 3.3 block_type 编码待解码

block() 的 block_type 字段含义未知，但数值规律明显：

| block_type | 数量 | 推测 |
|-----------|------|------|
| 2 | 3,172 | 精选指数 |
| 49 | ~27K | 主板行业分类 |
| 51 | ~13K | 行业细分 |
| 54 | ~14K | 概念板块 |
| 55 | ~12K | 地域板块 |
| 57 | ~13K | 风格/指数成分 |
| 12336~14648 | ~12-54K | TDX 自定义分类 |

需通过 blockname 内容推断类型，或在后续使用中验证。

---

## 四、总结

| 遗留问题 | 方案 | 优先度 |
|---------|------|--------|
| ① 指数代码不兼容 | 使用 `index()` 替代 `quotes()` 获取指数数据 | **高** — 影响前端指数展示 |
| ② DuckDB 损坏 | 删除损坏文件后重建 | **中** — 不影响盘中功能 |
| ③ 板块排行不可用 | `block()` + `quotes()` 内存聚合替代 AKShare | **高** — 可完全脱离 HTTP |
| ④ 北交所缺失 | 暂标记待解决 | **低** — 影响小 |

### 建议实施顺序

1. **指数修复**（`index()` 补丁，~0.5天）— 最小改动，解决前端四大指数空白问题
2. **板块聚合**（`block()` + `quotes()` 聚合，~1天）— 彻底摆脱 AKShare HTTP 依赖
3. **DuckDB 清理**（删除损坏文件，~0.1天）— 恢复盘后缓存功能
4. **北交所**（后续评估）— 按需启动
