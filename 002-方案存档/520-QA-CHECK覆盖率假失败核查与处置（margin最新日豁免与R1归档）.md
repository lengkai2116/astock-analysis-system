# 520号｜QA-CHECK 覆盖率假失败核查与处置（margin T+1 发布窗口最新日豁免 + #R1 归档登记）

> **版本**：v1.1（2026-10-14 只读核查 + **拍板 A（margin 最新日豁免）/ A（#R1 归档登记）并实施 + 定向验证通过**）
> **性质**：QA-CHECK 假失败（margin 覆盖率必失败 + 重试超限告警）+ #R1 归档
> **触发**：10-13 QA-CHECK `margin_cache 覆盖率不足: 0/4232（0% < 95%）` → 重试超限 `[ALERT] qa_check`
> **关联**：483（margin 自基准口径）；#R1（10-12 QA-CHECK 9 项覆盖率失败）；511（同为告警/管道议题）
> **核查时刻**：2026-10-14（只读）

---

## 一、现象（实证）

- **10-13 QA-CHECK 连续 4 次失败**（01:36/01:38/01:40/01:42，`data_daemon.log`）→ `重试超限`：
  `margin_cache 覆盖率不足: 0/4232（0% < 95%）`，`无对应补算步骤: margin_cache`，`已调度补算 0 项`；
  `pipeline_status.20261013.Q-A-CHECK` = done（`QA重试超限已告警`，retry_count=3），并触发 `[ALERT] qa_check` 告警链（monitor + AlertNotifier）。
- **10-09 同型复发**：`10-10 14:47-14:58` 四次失败，`margin_cache 2001/4231（45% < 95%）`，同样重试超限告警。
- **margin 数据现状**：`margin_cache` 最新 = **2026-10-12（4455 只）**，10-13 = 0 行；
  daemon 日志多次 `[Tushare空返回] margin_detail trade_date=20261013`（10-14 02:00/03:00/07:06/07:26 均空）——**源侧 T+1（甚至跨周末）才发布**，数据本身最终会由 daemon 独立回补，非永久缺失。
- **#R1（10-12 QA-CHECK 9 项）**：`10-13 09:40:52 QA-CHECK → failed (9项失败, 已调度补算 8 项)`——
  `indicator_ma/macd/other 4826/5505（87%）`、`pre_feat_cache 0/5282`、`factor_cache 467/5282（8%）` 等；
  触发补算（→ RAW-1/2/3）后 **13:34 重跑 done（OK 64.3s, retry_count=1）**——**已自愈，属 RAW 未就绪时序问题**。

## 二、代码机制（实证）

- **QA 规则**：`stg_quality.py` QUALITY_RULES `margin_cache: {'rows_ratio': 0.95, 'date_col': 'trade_date', 'baseline': 'self'}`——
  `baseline='self'`（483号 ③b 自基准），对**当日**（最新交易日）即时校验覆盖率，无发布窗口豁免。
- **daemon 自检口径（对齐参照）**：`data_daemon.py ~2180` 融资融券检查**主动排除最新日历交易日**（`_latest = cal_days[-1]`；注释：`最新交易日的深/北交所数据处于发布窗口内（次一交易日发布），核对无意义`）——QA-CHECK 未对齐此口径。
- **补算映射缺失**：`RECOMPUTE_KEYS`（stg_quality.py:640-650）无 `margin_cache` → `无对应补算步骤` → `已调度补算 0 项` → 3 次重试超限告警。
- **消息截断**：`data_daemon.py:7173` `_issues[:5]`——9 项失败仅展示前 5 项（#R1 归档时注意）。

## 三、根因定性

1. **margin 属「次一交易日发布」表**（源侧 T+1，跨周末更晚）；QA-CHECK 在最新交易日（刚完成 EOD 的日期）即时校验 margin 当日覆盖率 → **结构性假失败**（10-09 45%、10-13 0% 实证）。
2. **无补算映射 + 重试超限告警**：失败不可自愈 → 3 次重试 → `[ALERT] qa_check` 噪音（10-09/10-13 两次触发）。
3. **#R1 定性**：10-12 QA-CHECK 9 项覆盖率失败系**当日 RAW 产物未就绪时序问题**（SIG/JUD/OUT 完成后 QA-CHECK 早于 RAW-1/2/3 完成），补算调度正常自愈——**非缺陷**，归档登记。

## 四、处置方案与拍板

| 方案 | 内容 |
|---|---|
| **A（margin 最新日豁免）** | `QUALITY_RULES['margin_cache']` 加 `skip_latest_day=True`：pipeline_date 为最新交易日（= daily_cache 最新日期，即刚完成 EOD 的日期）时**跳过覆盖判定**（对齐 daemon 自检口径）；**历史日期照常校验**；完整性由 daemon `run_integrity_check` 融资融券检查独立回补。 |
| **A（#R1 归档登记）** | 9 项覆盖率失败已自愈（补算 8 项后通过），根因=RAW 未就绪时序问题，非缺陷；**在本文档登记根因与结果，不改代码**。 |

**拍板（2026-10-14）＝margin 采 A（最新日豁免）；#R1 采 A（归档登记）。**

## 五、实施记录（v1.1，2026-10-14）

- **`app/data/stg_quality.py`**：
  - QUALITY_RULES `margin_cache` 加 `'skip_latest_day': True`（附 520 号注释）。
  - `check_table` 新增分支：`if rule.get('skip_latest_day') and self._latest_daily_date() == pipeline_date:` → logger.info + 返回 `CheckResult(True, ...)`（跳过覆盖判定）；插在 `check_mode='nonempty'` 分支之后、覆盖率计算之前。
  - 新增 `_latest_daily_date()` helper：读 `daily_cache` 的 `MAX(trade_date)`（'YYYY-MM-DD'；异常/空返回 ''）。
- **测试**：新增 `backend/tests/test_520_margin_latest_day_exempt.py`（6 用例：规则标志 / 最新日豁免通过 / 历史日期照常失败 / 非豁免表不受影响 / helper 读 daily_cache / helper 空返回）。

## 六、验证（定向）

- `py_compile` `stg_quality.py` **OK**。
- `tests/test_520_margin_latest_day_exempt.py` **6 passed**（0.59s）。
- `ruff check` `stg_quality.py` + 测试文件 **All checks passed**（零新增）。

## 七、遗留

1. **margin 数据时效**：10-13 margin 待源侧发布后由 daemon `run_integrity_check` 融资融券检查回补（预计 10-14 晚间/10-15），QA 不再因发布窗口假失败。
2. **RECOMPUTE_KEYS 无 margin 映射**：本次未补（拍板 A 不含 C）；因 margin 无管道步骤、由独立回补覆盖，维持现状。
3. **告警口径**：`_issues[:5]` 截断使 9 项失败仅示前 5——本次未改（#R1 归档注明），如需完整展示另开号。

## 附：取证 / 复现命令

```bash
# QA-CHECK margin 失败（10-09/10-13）
grep -hE "margin_cache 覆盖率不足" backend/logs/data_daemon.log.2026-10-13 backend/logs/data_daemon.log | tail -4
# margin 数据现状
sqlite3 data/duckdb/market_cache.db "SELECT trade_date, COUNT(DISTINCT ts_code) FROM margin_cache WHERE trade_date>='2026-10-10' GROUP BY trade_date"
# 最新交易日（豁免判定依据）
sqlite3 data/duckdb/market_cache.db "SELECT MAX(trade_date) FROM daily_cache"
# 520 定向测试
cd backend && PYTHONPATH=$PWD ./.venv/bin/python -m pytest tests/test_520_margin_latest_day_exempt.py -q
```
