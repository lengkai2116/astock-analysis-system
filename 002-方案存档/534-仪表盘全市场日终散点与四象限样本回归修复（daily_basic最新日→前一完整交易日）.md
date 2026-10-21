# 534号｜仪表盘全市场日终散点与四象限样本回归修复

**状态**：🟢 已实施并实机验证（2026-10-21）
**HEAD（开工前）**：`0f681f6`（533 批次1~3 未提交，工作树含 533 改动）
**缘起**：2026-10-21 用户目检反馈——新增「大盘状态」模块正常，但原有「全市场日终散点」与「开盘收盘对比四象限」两张图的股票整体数据不对，不是全市场数据。

---

## 一、实证（只读）

- 运行中接口 `GET /api/v3/market/eod-snapshot`：
  - `trade_date=2026-10-21`、`count=95`。
- 库内同日对比：

| 表 | 2026-10-20 | 2026-10-21 |
|---|---:|---:|
| `daily_cache` | 5604 | **95** |
| `daily_basic_cache` | 5568 | 5568 |
| inner join | **5568** | **95** |

- `summary_5d` 也被污染：10-15~10-20 每日 5565~5568 只，**10-21 仅 95 只**。
- 前端 `loadEodScatter()` 只请求一次 `/market/eod-snapshot`，`renderEodScatter1/2` 共用 `dd.stocks`，所以两图同时缩水。

## 二、根因

`DashboardService.get_eod_snapshot()`（`dashboard_service.py:453`）先取 `daily_basic_cache` 的**最新日期**（`:471`），再用同一日期取 `daily_cache`。

- 531 为避免 `daily_cache` 盘中残行导致 503，改成“以 daily_basic 最新日为准”；
- 现在 `daily_basic` 10-21 已全量 5568，`daily_cache` 10-21 仅 95 只盘中/残行；
- inner join 后只剩 95 只。

`_get_eod_summary_5d()`（`:554`）取 `daily_cache` 最新 5 日同样包含 10-21，导致状态说明也按 95 只计算。

## 三、修复（Serena 编辑）

使用 Serena `replace_symbol_body` 替换两个方法：

1. `get_eod_snapshot()`：
   - `as_of = self._get_best_trade_date(before=today)` 固定前一完整交易日；
   - 候选日优先 `as_of`，再回退 `as_of` 的再前一交易日；
   - inner join 后 `count < 1000` 时自动回退到样本更大的候选日；
   - 返回新增 `data_quality`（`ok` / `low_sample`）；
   - `summary_5d` 调用传入 `as_of=last_date`。
2. `_get_eod_summary_5d(ecm, as_of=None)`：
   - 指定 `as_of` 时，日期查询加 `trade_date <= ?`，排除盘中残行；
   - 不传时保持原行为（向后兼容）。

## 四、验证

- 新增 `test_534_eod_snapshot_anchor.py` **2 passed**：
  - `daily_basic 10-21` 全量、`daily_cache 10-21` 仅 1 只 → 返回 10-20、1001 只、`quality=ok`；
  - 候选日 10-21 仅 1 只时自动回退 10-20。
- `test_523_eod_snapshot.py` **4 passed**、`test_530_batch1_eod_summary_5d.py` **3 passed**。
- `ruff` 通过。
- API 重启后实机：
  - `health=200`
  - `trade_date=2026-10-20`、`count=5568`、`quality=ok`
  - `summary_5d=2026-10-14..2026-10-20`（末日 5568）

## 五、变更文件

- `backend/app/services/dashboard_service.py`（Serena 替换两方法）
- `backend/tests/test_523_eod_snapshot.py`（测试桩锚定 10-16）
- `backend/tests/test_534_eod_snapshot_anchor.py`（新增）
- 534 档、沟通记录 §021、沟通索引 §021、方案索引 534 行

## 六、遗留

- 无功能遗留；前端无需改动。
- 533 批次1~3 仍为未提交工作树，与本号分离。
