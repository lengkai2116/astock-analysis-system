---
title: 546-机会图谱市场地图数据修复（成交额单位 + P2/P3 口径）
type: 修复
date: 2026-10-23
status: P1 + P2/P3 可确定项已实施并实机验证；数据源依赖项待拍板；未提交
---

# 546｜机会图谱市场地图数据修复（P1 成交额 + P2/P3 口径）

## 一、背景与范围

承接 2026-10-23 对「机会图谱 → 市场地图」（`_ui-prototype/opportunity-treemap.html`，`mode=market`）的只读核查。

核查结论：市场地图主体读 OUT 成品仓表 `treemap_snapshot`，盘中由 `as_market_snapshot` 覆盖 `price / pct_change / open / high / low / amount` 六个字段。本次只修其中唯一的 P1：

> **成交额单位混用**：`as_market_snapshot.amount` 为元，`treemap_snapshot.amount` 为千元；overlay 直接搬运后，前端统一按千元 ÷1e5，导致 5,217 只实时覆盖股票的成交额被放大 1000 倍。

不在本号范围：北交所实时覆盖、2 只北交所新股元数据、`/quotes` 全量轮询等依赖外部数据源/性能口径的项，仍在 §六 登记待拍板。P2/P3 中可确定的口径项（前收盘价、振幅、状态日、PE/行业PE 空值、fallback 文案）已在本轮实施，见 §八。

## 二、根因

`backend/app/routes/opportunity_atlas.py:66` 的 `_merge_snapshot_with_realtime()`：

```python
for _f in ('open', 'high', 'low', 'amount'):
    _v = float(rt.get(_f))
    ...
    item[_f] = _v
```

- `rt` 来自 `as_market_snapshot`，其 `amount` 单位为元；
- `item` 来自 `treemap_snapshot`，其 `amount` 单位为千元（`daily_cache` 口径）；
- 前端 `opportunity-treemap.html:1126 / 1474 / 1505` 均按千元 ÷1e5 显示“亿”。

实证（修复前）：

| 股票 | 实时 `amount`（元） | API 返回 | 前端显示 | 实际 |
|---|---:|---:|---:|---:|
| 000001.SZ 平安银行 | 1,161,789,918.21 | 1,161,789,918.21 | 11,589.2 亿 | 11.59 亿 |
| 600519.SH 贵州茅台 | 5,776,569,493.00 | 5,776,569,493.00 | 57,562.4 亿 | 57.56 亿 |

## 三、口径决策

**统一到快照既有口径（千元），不改前端、不改 API 字段契约。**

理由：

1. `treemap_snapshot.amount`、`daily_cache.amount` 均为千元，前端换算系数已按千元固定；
2. 只改 overlay 一处，`/treemap` 与 `/stock` 两个消费方同时修复；
3. 不引入新字段/新单位标记，避免前端分支与历史兼容成本。

## 四、改动

`backend/app/routes/opportunity_atlas.py:86-95`：

```python
if _v > 0:
    # 546号 P1：as_market_snapshot.amount 为元，treemap_snapshot.amount
    # 为千元；统一到快照口径，避免前端 ÷1e5 后放大 1000 倍。
    item[_f] = _v / 1000.0 if _f == 'amount' else _v
```

仅 `amount` 除以 1000；`open/high/low/price` 仍为元，不做换算。

## 五、验证

### 5.1 定向测试

新增 `backend/tests/test_546_amount_unit.py`：

1. 实时 `amount` 元→千元换算；
2. `open/high/low` 不被误除；
3. 无实时覆盖的北交所行保持日终千元值；
4. 实时 `prev_close` 覆盖并按实时高低/昨收重算振幅；
5. 无 `prev_close` 时保留快照振幅。

执行：

```text
backend/.venv/bin/python -m pytest \
  backend/tests/test_546_amount_unit.py \
  backend/tests/test_t25_f1_change_pct.py -q
→ 8 passed
```

`ruff check`（route/test）、`py_compile`、`node --check`（前端内联脚本）均通过。

### 5.2 实机验证

重启 API（旧 PID 36565 → 新 PID 38336，`health/live=200`），重新请求：

```text
GET /api/v3/opportunity-atlas/treemap?mode=market
```

| 股票 | 修复后 API `amount`（千元） | 前端显示 | 结论 |
|---|---:|---:|---|
| 000001.SZ | 1,299,288.48801 | 12.99 亿 | 与盘中实际量级一致 |
| 600519.SH | 6,073,995.134 | 60.74 亿 | 与盘中实际量级一致 |

修复前同口径为 11,589 亿 / 57,562 亿，确认 1000 倍放大已消除。P2/P3 实机复核见 §8.3。

## 六、遗留登记（本轮已修 / 待拍板）

| 项 | 现状 | 处置 |
|---|---|---|
| 前收盘价 | 快照无 `prev_close`，前端曾用现价冒充 | ✅ 已修（§八）：快照按 `close/(1+pct/100)` 还原；实时用 `as_market_snapshot.prev_close` 覆盖 |
| 振幅 | 实时覆盖 `high/low` 后未重算 | ✅ 已修（§八）：按实时高低/昨收重算 |
| `status_date` | 取 `MAX(snapshot_date)`=构建日 | ✅ 已修（§八）：状态截至改用 `MAX(trade_date)`=数据日 |
| PE/PB null | 1,457 只 PE null 被前端置 0 | ✅ 已修（§八）：保留 null，前端显示 `--` |
| 行业PE | 曾用个股 PE 冒充 | ✅ 已修（§八）：无 `industry_pe` 显示 `--` |
| fallback 文案 | 称“fallback 估算数据” | ✅ 已修（§八）：改“信号缺失（JUD 未产出）” |
| 2 只北交所新股 | 920196/920296.BJ 空名称/空行业/无 signal | 名称已回退代码、行业归“其他”；signal 仍待补 pre_feat |
| 北交所实时 | `as_market_snapshot` 仅 SH/SZ，352 只 BJ 仍 10-22 日终 | 待数据源；浮窗已加“日终 10-22”标识 |
| 3 只无行业 | 301139/920196/920296 | ✅ 已修（§八）：API 空行业统一归“其他” |
| 5 只实时行 OHLC=0 | 覆盖跳过零值，保留日终 OHLC | ✅ 已修（§八）：标记 `quote_partial`，浮窗显示“盘中（OHLC 日终）” |
| `/quotes` 全量 | 30s 5,225 条 / 563 KB | ✅ 已修（§八）：行业下钻/小筛选集（≤500只）传 `ts_codes`；全市场仍全量 |
| `/quotes` 只更 price/pct | amount/OHLC 停留首屏 | ✅ 已修（§八）：`detail=1` 返回 OHLC/昨收/振幅/成交额；裁剪集每次、全市场每 10 次（5min） |

## 七、影响面与回滚

- 影响接口：`/api/v3/opportunity-atlas/treemap?mode=market`、`/api/v3/opportunity-atlas/stock`（共用 overlay）；
- 影响文件：`backend/app/routes/opportunity_atlas.py`、`backend/app/data/enhanced_cache_manager.py`、`_ui-prototype/opportunity-treemap.html`；
- 不影响：`treemap_snapshot` 落库数据、`/quotes`、其他 mode；
- 回滚：还原 `_merge_snapshot_with_realtime()` 的 `amount` 换算/`prev_close`/`amplitude` 段，以及前端字段映射即可；无表结构变更。

## 八、P2/P3 实施明细（2026-10-23）

### 8.1 后端

1. `enhanced_cache_manager.py::get_treemap_snapshot_items()`
   - 新增 `prev_close`：`close/(1+pct_chg/100)`，避免前端拿现价当前收；
   - 名称空值回退 `ts_code`（920196/920296.BJ）。
2. `opportunity_atlas.py::_merge_snapshot_with_realtime()`
   - 用 `as_market_snapshot.prev_close` 覆盖昨收；
   - 用实时 `high/low` 与 `prev_close` 重算 `amplitude`。
3. `enhanced_cache_manager.py::get_status_snapshot_trade_date()`
   - 新增数据交易日读取；`opportunity_atlas.py` 的 `status_date` 改用它（10-22），不再用构建日（10-23）。

### 8.2 前端

1. `prevClose` 改读 `s.prev_close`，不再用 `s.price`；
2. `pe/pb/dividendYield/industryPe` 保留 null，浮窗显示 `--`；
3. 市场地图浮窗新增“前收”“盘中/日终”标识；换手率在日终行标注数据日；
4. fallback 徽标改为“⚠ 信号缺失”，title 改为“JUD 未产出，不是估算值”。

### 8.3 验证

```text
pytest test_546_amount_unit.py test_t25_f1_change_pct.py -q
→ 8 passed
ruff check（route/test）→ All checks passed
py_compile → OK
node --check（内联脚本）→ OK
```

实机（API PID 38336，`health/live=200`）：

| 字段/股票 | 结果 |
|---|---|
| `status_date` | **2026-10-22**（修复前误为构建日 10-23） |
| 000001.SZ | `prev_close=11.30`，`amplitude=1.59`（实时高低/昨收） |
| 600519.SH | `prev_close=1318.49`，`amplitude=2.57` |
| `prev_close` null | **0** |
| `pe` null | 1,457（保持 null，前端显示 `--`） |
| 920196/920296.BJ | 名称回退为代码，行业仍空 |
