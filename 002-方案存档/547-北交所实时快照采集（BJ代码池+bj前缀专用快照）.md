---
title: 547-北交所实时快照采集（BJ代码池 + bj前缀专用快照）
type: 修复
date: 2026-10-23
status: 已实施并实机验证；纳入 2026-10-23 统一提交
---

# 547｜北交所实时快照采集

## 一、问题

市场地图 5,569 只中北交所 352 只，`as_market_snapshot` 仅 SH 2,320 + SZ 2,909，**BJ 0 行**；352 只 BJ 的价格/涨跌/成交额仍为 10-22 日终，地图呈“93.7% 实时 + 6.3% 日终”混排。

## 二、根因

1. `mootdx_collector._get_a_share_codes()` 只查 `stocks WHERE ts_code LIKE '%.SH' OR '%.SZ'`，BJ 未入池；
2. `_fetch_eastmoney/_fetch_sina/_fetch_tencent` 用 `code.startswith(('6','9')) ? sh : sz` 判定市场，920xxx 被误判为沪市；
3. `ts_code` 后缀只生成 `.SH/.SZ`，无 `.BJ` 分支；
4. 东财 `ulist.np` 的 BJ secid 口径与沪深不同，未纳入东财批次。

## 三、改动

`backend/app/data/mootdx_collector.py`：

- 新增 `_market_prefix()`：`92/4/8` → `bj`，`6/9` → `sh`，其余 `sz`；`92` 优先于沪市 `9`；
- 新增 `_ts_code_from_prefix()`：支持 `.BJ`；
- 新增 `_get_bj_codes()`：从 `data/app.db` 读取 `.BJ` 6 位代码（351 只）；
- `_fetch_sina()`：请求前缀改用 `_market_prefix()`；解析 `hq_str_bj...` 并生成 `.BJ`；
- `_fetch_tencent()`：请求前缀改用 `_market_prefix()`；解析 `v_bj...` 并生成 `.BJ`；
- 新增 `_collect_bj_snapshot()`：新浪主、腾讯备，专采 BJ；
- `_collect_dual_source_fallback()`：沪深结果后合并 BJ；即使沪深主源失败，BJ 也可独立返回；补回 `t_start`。

东财 `ulist.np` 批次不混入 BJ，避免 secid 误映射；BJ 走已验证的 `bj` 前缀接口。

## 四、验证

### 4.1 单测

`backend/tests/test_547_bj_realtime.py` 3 项：

- `920196/430047/830799 → bj`，`600519 → sh`，`000001/300750 → sz`；
- `_ts_code_from_prefix` 生成 `.BJ/.SH/.SZ`；
- `_get_bj_codes()` ≥300 只、全 6 位。

执行：`test_547` 3 + `test_546` 7 = **10 passed**；`py_compile` 通过。

### 4.2 零写入探测

`_collect_bj_snapshot({})`：代码池 **351**，Sina 返回 **350** 条，全部 `.BJ`，耗时 **0.14s**，样本：

```text
920802.BJ 保丽洁 10.31 +0.88% 2,225,513.17 sina
920806.BJ 云星宇 10.16 +2.73% 21,755,009.5 sina
920807.BJ 奔朗新材 8.32 +1.71% 11,889,995.73 sina
```

### 4.3 实机

daemon 看守 43832 / data_daemon 43987（新代码）；`as_market_snapshot`：

```text
BJ 350 / SH 2,320 / SZ 2,909
max(cached_at)=2026-10-23 14:47:59
```

`/treemap?mode=market`：BJ 352 只，`snapshot=true` **350**；`realtime_at=14:48:18`。`/quotes?ts_codes=920000.BJ&detail=1` 返回：

```text
price=13.33 prev_close=13.22 open=13.03 high=13.4 low=12.72
amount=6,191.27 千元 amplitude=5.14 quote_partial=false
```

## 五、剩余缺口

- `920196.BJ`、`920296.BJ` 仍无实时：不在 `stocks`/`pre_feat`，属既有新股元数据缺口，不是采集前缀问题；
- BJ 走新浪/腾讯专源，东财 secid 未纳入；若东财恢复 BJ 批次，可再统一；
- `in_memory_store` 是否完整接收 BJ 未单独验证；市场地图直接读 `as_market_snapshot`，不受影响。

## 六、回滚

还原 `mootdx_collector.py` 的 BJ 前缀/专用快照段即可；不涉及表结构或数据迁移。纳入 2026-10-23 统一提交。

## 七、市场地图 OUT 元信息（同批）

`/treemap` 响应新增：

- `panel_source='out'`（无快照时 `missing`）；
- `panel_date=data_date`；
- `panel_built_at=snapshot_date`；
- `stale = snapshot_date < today`。

不改变原有 payload；用于标记 `treemap_snapshot` 的 OUT 成品仓来源与构建时效。
