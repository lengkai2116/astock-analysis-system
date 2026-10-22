---
title: 541-前端展示类 OUT 成品仓与仪表盘合规改造（规则边界 + out_market_panel + B0/B1）
type: 实施方案
date: 2026-10-22
status: B0/B1/B2/B3 已实施
---

# 541｜前端展示类 OUT 成品仓与仪表盘合规改造

> 承接 2026-10-22 前端取数分层核查（OUT 成品仓口径）。本文只做 B0（规则/分类/表结构）与 B1（`out_market_panel` 构建与校验）；B2~B5 为后续批次。

## 一、规则边界（B0 定稿）

### 1.1 三类数据

| 类别 | 允许读 | 禁止读 | 标注 | 典型对象 |
|---|---|---|---|---|
| **展示类（OUT 成品仓）** | `status_snapshot`、`treemap_snapshot`、`one_liner_detail`、历史/差分、`out_market_panel` | RAW/SIG/JUD 中间表、旧标签表、COL 原始表 | `source=out` + `data_date` | 机会图谱、个股页展示、仪表盘 EOD 模块、状态/预警 |
| **盘中实时例外** | `as_market_snapshot`、`in_memory_store`、盘中 `limit_detail_cache` 的原始实时字段 | 不用实时值替代 EOD 序列、板块热度、资金流聚合、状态/预警 | `source=live` + `data_time` | 指数卡实时价、`/quotes`、盘中家数/涨停/封板率 |
| **交互类（后续独立体系）** | 后续自定（输入来自 OUT） | 本轮不纳入展示规则 | 交互体系自存 | 自选股、策略分析、回测、筛选、AI 投研 |

### 1.2 盘中实时白名单

允许：价格、涨跌幅、开/高/低、成交额、成交量、换手率、振幅、指数报价、涨跌平家数、涨停/跌停家数、封板率、最高连板，以及这些字段的**直接排序/直接聚合**。

禁止：20/30 日序列、日终散点/四象限、板块涨跌幅/热度/资金流、行业排名、市场状态、预警结论、机会图谱 `opportunity_state`/共识/操作建议/估值分位。

### 1.3 缺失处理

OUT 缺失 → 最后一次有效 OUT + `stale=true` + 时间戳，或空/503；**禁止回退** RAW/SIG/旧标签表。

## 二、仪表盘接口分类（B0）

| 模块/接口 | 当前主源（层） | 分类 | 目标 |
|---|---|---|---|
| `/market/index-daily` | `daily_cache`（COL） | EOD | OUT `market_index_daily` |
| `/market/daily-top` | `daily_cache`+`daily_basic_cache`（COL） | EOD（盘中榜例外） | OUT 涨/跌两份；盘中仅实时排序 |
| `/market/eod-snapshot` | `daily_cache`+`daily_basic_cache`（COL） | EOD | OUT `market_eod_snapshot` |
| `/market/overview` | 实时指数 + `daily_cache` | 混合 | EOD 字段 OUT；实时价 overlay |
| `/market/moneyflow-summary` | `moneyflow_cache`（COL） | EOD | OUT `market_moneyflow_summary` |
| `/market/sector-sector` | `daily_cache`+板块排行（COL/RAW） | EOD | OUT `market_sector_changes` |
| `/market/sector-moneyflow` | `moneyflow_cache`+`daily_cache`（COL） | EOD | OUT `market_sector_moneyflow` |
| `/market/overview-panel` | `daily_cache`+`daily_basic_cache`（COL） | EOD | OUT `market_overview_panel` |
| `/market/flows-30d` | `moneyflow`+`fund_share`+`margin`（COL） | EOD | OUT `market_flows_30d` |
| `/market/breadth` | `daily_cache`+`market_stats_cache`（COL/RAW） | 混合 | OUT EOD；盘中家数/比例 live |
| `/market/limit-ecology` | `limit_detail_cache`+`daily_cache`（COL/RAW） | 混合 | OUT EOD；盘中家数/封板率 live |
| `/market/emotion` | `sentiment_pool_cache`+`market_stats_cache`（RAW） | 混合 | OUT EOD 阶段/温度；盘中涨停/封板 live |
| `/market/state` | `market_stats_cache`+指数（RAW/COL） | EOD 判定 | OUT `market_state` |
| `/market/sector-heat` | `sector_heat_cache`（RAW） | EOD | OUT `market_sector_heat` |
| `/market/sector-heat-dim` | `sector_heat_dim_cache`（RAW） | EOD | OUT `market_sector_heat_dim` |
| `/market/alerts` | state/breadth/emotion 派生 | EOD 判定 | OUT `market_alerts`；实时预警后续归通知体系 |
| `/dashboard/full` | 以上聚合 | 混合 | OUT 聚合 + live overlay（B2/B3） |

## 三、OUT 市场成品仓表（B1）

```sql
CREATE TABLE out_market_panel (
    module          TEXT NOT NULL,   -- market_state / market_breadth / ...
    asof_date       TEXT NOT NULL,   -- pipeline_date（YYYYMMDD）
    payload_json    TEXT NOT NULL,   -- 与现有 API data 同构
    data_dates_json TEXT,            -- 模块自带日期口径（trade_date/data_date/...）
    schema_version  INTEGER DEFAULT 1,
    built_at        TEXT,
    PRIMARY KEY (module, asof_date)
);
```

位置：`snapshot_cache.db`（与 `status_snapshot`/`treemap_snapshot` 同库；`sharding_manager` 已登记路由）。

模块清单（17）：`market_index_daily`、`market_daily_top_up/down`、`market_eod_snapshot`、`market_overview_panel`、`market_moneyflow_summary`、`market_sector_changes`、`market_sector_moneyflow`、`market_flows_30d`、`market_breadth`、`market_limit_ecology`、`market_state`、`market_emotion`、`market_sector_heat`、`market_sector_heat_dim`、`market_alerts`、`market_overview`。

## 四、B1 实施内容

1. **纯逻辑模块** `backend/app/data/out_market.py`
   - `OUT_MARKET_MODULES` 契约（模块→必需顶层键）；
   - `validate_payload()` 字段级校验（`alerts/gainers/losers` 允许空列表）；
   - `extract_dates()` 提取模块日期口径；
   - `ensure_table/upsert_panel/get_panel/get_latest_asof_date` 分库读写。
2. **分库接入** `backend/app/data/sharding_manager.py`
   - `out_market_panel → snapshot_cache.db`；
   - 建表 + `(module, asof_date)` 索引（幂等）。
3. **网关** `enhanced_cache_manager.py` / `DataManager`
   - `upsert_out_market_panel`（仅 OUT 构建器写）；
   - `get_out_market_panel` / `get_out_market_panel_date`（调用层只读）。
4. **OUT 构建与校验** `backend/data_daemon.py`
   - `OUT_MARKET_BUILDERS`（17 模块 → DashboardService 方法/参数）；
   - `_collect_out_market_payloads()`：调用服务、契约校验、日期提取、异常隔离；
   - `_build_out_market_panel(pipeline_date)`：OUT 步骤写入；
   - `_verify_out_market_panel(pipeline_date)`：模块齐全 + payload 契约，写 `pipeline_status.OUT-MARKET-CHECK`；
   - `_drive_pipeline()` 的 OUT 步骤已接线（先七维透传/归档，再构建市场成品仓）。

## 五、验证

- 新增 `backend/tests/test_541_out_market_panel.py`：**27 passed**（17 模块契约 + 空列表边界 + 日期提取 + 分库 roundtrip/latest + 收集器全模块/异常隔离）。
- `py_compile` 通过（`out_market.py`、`sharding_manager.py`、`enhanced_cache_manager.py`、`DataManager`、`data_daemon.py`、测试文件）。
- 实机只读核对：15 个仪表盘接口 payload 顶层键与契约一致；`/market/overview` 提供 `indexes/data_date`。
- 未在开发基准库执行 `_build_out_market_panel`（避免额外写入）；首次 daemon OUT 运行会自动建表/落 17 模块。

## 六、后续批次

| 批次 | 内容 |
|---|---|
| **B2** | 仪表盘 EOD 接口改读 `out_market_panel`；加 last-valid/stale；响应结构不变 |
| **B3** | 实时 overlay 白名单；拆分 breadth/limit/emotion/overview；移除 `daily_cache` 盘中午读 |
| **B4** | 机会图谱/个股页：`get_tags` state/rsc/label 切 OUT；移除 `/treemap` 旧回退；`_build_label_baseline` 切 OUT；dim7 估值基准切 pre_feat |
| **B5** | 旧表四字段迁移 → 冻结 → 归档；文档/health 更新 |
| **B6** | 交互体系（自选股等）独立号 |

## 七、B2 实施（2026-10-22 续）

- 新增 `backend/app/services/out_market_reader.py`：
  - `OUT_MARKET_PANEL_MODE`：`off` / `prefer`（默认）/ `strict`；
  - `get_out_or_legacy()`：成品仓优先，缺失按模式回退旧路径并标记 `panel_source=legacy / panel_missing / stale`；
  - `attach_meta()`：附加 `panel_source=out / panel_date / panel_built_at / stale`（不覆盖各模块原有 `source`）；
  - 参数切片：指数/资金 `days`、榜单 `limit`、板块 `top_n`、板块资金 `stocks_per_sector`、热度 `top_n`。
- `routes/dashboard.py`：12 个 EOD 接口改走 reader
  （index-daily / daily-top / eod-snapshot / overview-panel / moneyflow-summary / sector-sector / sector-moneyflow / flows-30d / state / sector-heat / sector-heat-dim / alerts）；
  混合接口（overview / breadth / limit-ecology / emotion）保留旧路径，B3 做实时 overlay。
- `dashboard_service.get_dashboard_full`：上述 EOD 模块改走 reader；overview / breadth / limit_ecology / emotion 仍旧路径（B3）。
- B1 构建窗口扩到 **60 日 / 50 条**（指数、资金；涨跌榜），供 B2 按请求参数切片。
- 验证：`test_541_out_market_panel.py` 27 + `test_541_b2_out_market_reader.py` 13 = **40 passed**；`py_compile`、`ruff` 通过。
- 激活：默认 `OUT_MARKET_PANEL_MODE=prefer`（有成品仓读成品仓；缺失临时回退并标记 legacy/stale）；daemon 首次 OUT 落表后可切 `strict`（缺失直接 503，不再回退）。

## 八、B3 实施（2026-10-22 续）

- 新增 `backend/app/services/live_overlay.py`：
  - 白名单只覆盖原始实时字段：
    - `market_overview`：`indexes.price/change_pct`、`market_status`、`data_is_live`；
    - `market_breadth`：`count/up_count/down_count/flat_count/up_ratio/down_ratio`；
    - `market_limit_ecology`：`up.count/down.count/data_available`；
    - `market_emotion`：`metrics.limit_up_count/limit_down_count/up_down_ratio`。
  - 实时源：`in_memory_store` 快照/涨跌停池优先；`as_market_snapshot` 仅在 `updated_at` 5 分钟内兜底。
  - 新鲜度：store meta 超过 300s 不 overlay；宽度样本 <100 只不 overlay；避免停更实时源冒充 live。
  - EOD 字段不覆盖：`history/ma20_ratio/limit_ratio/turnover_percentile`、涨跌停明细/行业/连板、`phase/phase_label/sealing_rate/max_board_height`。
- `routes/market.py`：`/market/overview` 改走 `out_market_reader` + `live_overlay`。
- `routes/dashboard.py`：`/market/breadth`、`/market/limit-ecology`、`/market/emotion` 改走 reader + overlay。
- `dashboard_service.get_dashboard_full`：`market_overview`、`market_limit_ecology`、`market_breadth`、`market_emotion` 四个混合模块同改。
- 验证：B1 27 + B2 13 + B3 11 = **51 passed**；`py_compile`、`ruff` 通过。

## 九、B4 实施（2026-10-22 续）

- `get_tags`：以 `treemap_snapshot`（OUT）覆盖
  `signal_strength / opportunity_state / right_side_confirm / opportunity_label /
  opportunity_type / opportunity_profile / confirm_evidence / state_evidence /
  entry_signals / exit_conditions / main_force_presence / presence_evidence /
  consensus_rate / conflict`；
  无快照行时显式清空 state/rsc/label/signal，禁止回落 08-19 旧值。
- `/treemap`：快照不可用返回 `snapshot_missing` + 空 `groups`，删除旧 `_fallback_legacy_treemap()` 路径；缺失结果不写 1h 缓存。
- `_build_label_baseline`：经 `get_tags` 自动使用 OUT 覆盖后的 state/rsc/label/profile（字段结构未改）。
- dim7：`build_composite_percentile` 改从 `pre_feat_cache` 最新交易日 `valuation.composite_rating` 构建截面基准；不再读取旧标签表。
- 验证：B1 27 + B2 13 + B3 11 + B4 8 = **59 passed**；`py_compile`、`ruff` 通过。

## 十、B5 实施（2026-10-22 续）

- `pre_feat` 映射扩展：`ma_alignment`、`buy_sell_point`、`pattern_signal`、`state_label`，并补 `support_resistance`、`chip_fund_ext`（asr/concentration/cyqkl/profit_ratio/ssrp）、`risk_ext`、`valuation_ext` 等深度字段。
- `get_tags`：删除 `opportunity_tags_cache` 查询，源＝`pre_feat_cache` + `treemap_snapshot`；无快照行清空 state/rsc/label/signal。
- `get_tags_by_group`：旧 tag_group 读取冻结，返回新鲜标签全集（个股页深度字段按 key 取用）。
- `get_tags_by_date`：改用 `pre_feat_cache`（指定日）+ `treemap_snapshot_history`（指定日）。
- `get_tags_batch`：逐只 `get_tags`；雷达候选改读 `treemap_snapshot` Top500。
- `health.py`：移除 `opportunity_tags_cache` 新鲜度检查。
- 归档脚本 `backend/scripts/_541_archive_opportunity_tags.py`（默认 dry-run；`--apply` 复制到 `opportunity_tags_cache_archive_20261022`，原表保留；本轮未执行）。
- 验证：B1 27 + B2 13 + B3 11 + B4 8 + B5 5 = **64 passed**；`py_compile`、`ruff` 通过。

## 十一、状态

- B0：规则、实时白名单、16 接口分类、表结构 **已完成**。
- B1：`out_market_panel` 建表/读写/构建/校验/测试 **已实施**；未提交。
- B2：reader 三模式 + EOD 路由/`dashboard/full` 接管 + 参数切片 **已实施**；未提交。
- B3：混合模块实时 overlay 白名单 + 新鲜度门槛 + 四模块接线 **已实施**；未提交。
- B4：`get_tags` OUT 覆盖 + `/treemap` 去旧回退 + dim7 基准切 pre_feat **已实施**；未提交。
- B5：四字段迁 pre_feat + 旧表读取冻结 + 雷达改 OUT + health 去旧表 + 归档脚本 **已实施**；未提交。
- OCR 复核问题修复：14 项需修已落地（#4 实证不改），3 项待拍板已定口径（历史日保持 `trade_date`；接受 OUT 滞后；家数覆盖 <80% 不 overlay）；未提交。
- 旧表 `opportunity_tags_cache` 仍物理保留（仅冻结读取）；归档需手动执行脚本。
- 未改前端；运行中 API/daemon 仍旧代码，需重启后生效；未在基准库执行归档。

## 十二、OCR 复核问题修复（2026-10-22 续）

OCR 23 条经实证分档：15 需修 / 3 待拍板 / 5 误报。本轮处置如下。

### 12.1 仪表盘读取与 overlay

- `routes/market.py` `/market/overview`：仅 `panel_source=out` 时 overlay；strict 缺 payload 不再空 overlay，legacy 回退不重复叠加。
- `dashboard_service.get_dashboard_full`：overview 同加 OUT 门控；`live_overlay`/`out_market_reader` 改模块顶部导入。
- `live_overlay._merge_overview`：仅指数全覆盖（merged == len(indexes)）才置 `data_is_live=True`，1/4 覆盖不再强改。
- `live_overlay._merge_breadth`：实时样本 < EOD `count` 的 80% 时整体不覆盖，保留 EOD 家数/比例锚定。
- `live_overlay._market_status_now`：改用 `trading_hours`（北京时间 + 节假日历），周末/节假日返回 `holiday`，不再一律 `closed`。
- `out_market_reader.attach_meta`：`actual` 同步归一化（去掉 `-`）再与 `expected` 比较，历史 `YYYY-MM-DD` 面板不再误判 stale。
- `out_market_reader._expected_date`：查询失败不写缓存（避免瞬时错误导致 60s 全量 `stale=False`），加锁保护缓存读写。

### 12.2 标签读取（pre_feat/treemap）

- `get_tags_batch`：恢复批量 `IN` 查询（每块 1 次 pre_feat 最新行 + 1 次 treemap，块大小 500）；treemap 查询失败的块保留 pre_feat 结果，不用空 overlay 误清判定字段。
- `get_tags_by_group`：按 `_TAG_GROUP_MAP` 将旧组名（structure/chip_deep/fund_risk 等）映射到 pre_feat 分组并取子集；未知组名保持返回全集兼容。
- `_PRE_FEAT_FIELD_MAP`：`structure_ext` 只保留 `indicator_status`，`support_price/resistance_price` 唯一归属 `risk_ext`，消除后者被覆盖。
- `get_tags_by_date`：OUT 覆盖异常改为 warning 日志（与 `get_tags` 一致），不再静默吞。
- 历史快照日期：经实证与调用方语义，保持 `WHERE trade_date=?`（`snapshot_date` 是构建日，改按它取会偏一天）。

### 12.3 归档脚本与管道状态

- 归档脚本：`--apply` 前检查目标表存在则中止，新增 `--overwrite` 显式 DROP 后重建；默认表名按当天日期生成；dry-run 以 `mode=ro` 只读打开。
- `data_daemon._verify_out_market_panel`：`pipeline_status` 写入改取 `stock_cache.db` 写锁，写失败 rollback；锁内复检 `done`，避免并发把 done 翻成 failed。
- `#4 sector-heat-dim KPI`：实证 legacy `get_sector_heat_dim(top_n)` 同样在全量 31 行业上算 KPI 再切片，OUT 切片与其同口径，不改。

### 12.4 验证

- 541 定向：`test_541_b2/b3/b4/b5/out_market_panel/archive_script` = **73 passed**。
- 关联回归：data_gateway / 323 / 509 / 507 / 461×3 / dim1 / 540 = **76 passed**。
- `py_compile` 通过；`app.routes.market` / `app.routes.dashboard` / `dashboard_service` / `enhanced_cache_manager` 导入通过；API health/routes 测试通过。
- 运行中 API/daemon 仍旧代码，需重启生效；未在基准库执行归档；未提交。
