# 535号｜仪表盘 P1 数据锚定修复（breadth + daily-top + emotion 统一口径）

**状态**：🟢 P1 已实施并实机验证（2026-10-21）；P2/P3 待续
**HEAD（开工前）**：`0f681f6`（533/534 改动未提交，工作树含 533/534）
**缘起**：OCR 第三轮核查发现 534 只修了散点/四象限，`/market/breadth`、`/market/daily-top` 仍取 10-21 的 95 只残行；`/market/emotion` 涨停 102 与 `/market/limit-ecology` 54 口径冲突。用户拍板「开 535 号，先修 P1」。

---

## 一、P1 实证（修复前）

| 接口 | 修复前 | 说明 |
|---|---|---|
| `/market/breadth` | `trade_date=2026-10-21`、`count=95`、`up=14/down=80/flat=1`、`up_ratio=14.7%` | 底部市场宽度错误；`/market/alerts` 误报「下跌宽度极端」 |
| `/market/daily-top` | `date=2026-10-21`、`source=DuckDB 盘后数据`、95 只池 | 涨幅/跌幅榜非全市场 |
| `/market/emotion` | `data_date=20261020`、`limit_up_count=102` | 与 `/market/limit-ecology` 的 54 冲突 |

## 二、修复（Serena replace_symbol_body）

1. `DashboardService.get_market_breadth()`：
   - 改 `_get_best_trade_date(before=today)` 锚定前一完整交易日；
   - 候选日含再前一交易日；join `count<1000` 自动回退样本更大者；
   - 返回 `data_quality`；`stats = ... or {}` 防 None。
2. `DashboardService.get_daily_top()`：
   - DB 降级分支改 `_get_best_trade_date(before=today)`；
   - 保留 AKShare 实时分支不变；
   - `source='DuckDB 盘后数据（前一完整交易日）'`。
3. `MarketSentimentService`：
   - `get_sentiment_phase(trade_date=None, metrics_override=None)` 支持外部权威指标覆盖；
   - 提取 `_classify_phase(metrics)` 复用六段论阈值。
4. `DashboardService.get_market_emotion()`：
   - 优先调用 `get_limit_ecology()`，用 `limit_detail_cache` 的涨停/跌停/连板/封板率覆盖 sentiment_pool；
   - 仅在 limit_detail 不可用或日期不匹配时回退 sentiment_pool。

## 三、实机验证（API 重启后）

```text
health=200
/market/breadth    trade_date=2026-10-20  count=5568  quality=ok  up=3778/down=1668  up_ratio=67.9%
/market/daily-top  date=2026-10-20  source=DuckDB 盘后数据（前一完整交易日）  n=10
/market/emotion    data_date=20261020  phase=ferment  limit_up=54/limit_down=7  max_board=4  sealing=65.1%
/market/alerts     count=0
```

- `daily-top` 首条 `920096.BJ +29.98%`，`name` 仍为空（新股/北交所名称映射未覆盖，P2 遗留）。
- API 已重启（PID `49100`，`DATA_DAEMON_RUNNING=1`），daemon 未动。

## 四、测试

- 新增 `test_535_p1_dashboard_anchor.py` **4 passed**（breadth 锚定、daily-top 锚定、emotion 54/7 覆盖、`_classify_phase`）。
- 相关回归：`test_524_market_breadth_state_emotion.py` 9、`test_526_baseline_fixes.py` 9、`test_527_batch3_multiday_aggregations.py` 4、`test_524_batch4_market_alerts.py` 10，合计 **36 passed**。
- `ruff` 通过。

## 五、变更文件

- `backend/app/services/dashboard_service.py`（Serena 替换 3 方法）
- `backend/app/services/market_sentiment_service.py`（Serena 替换 + 新增 `_classify_phase`）
- `backend/tests/test_535_p1_dashboard_anchor.py`（新）
- `backend/tests/test_524_market_breadth_state_emotion.py`、`test_526_baseline_fixes.py`、`test_527_batch3_multiday_aggregations.py`（测试桩适配）
- 535 档/索引/沟通记录

## 六、遗留

- P2（OCR 命中）：`get_index_summary` 60 日边界、`applyEodStateNotes` 空值、`_cachedFetch`、`bindEodPanZoom`、`dashboard/full` 30s/120s 缓存、成交量 live/DB 混用、XSS 转义、`_mktFlowChip` 空值等。
- `daily-top` 名称为空（920096.BJ 等）另登记。
- 533/534/535 均未提交。
