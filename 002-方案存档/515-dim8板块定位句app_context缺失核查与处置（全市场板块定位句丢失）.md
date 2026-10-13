# 515号｜dim8 板块定位句 app_context 缺失核查与处置（全市场板块定位句丢失）

> **版本**：v1.2（2026-10-13 拍板 **C 双管** + 实施 + 单测定向 + **「无-context 旧失败条件」定向实机验证**通过）
> **性质**：展示层（dim8 第一层环境定位）取数依赖 Flask app context 导致**全市场静默丢失**
> **范围**：`dim8_summary_engine._sector_position_sentence` + `DataManager.get_stock_industry` + daemon dim8 归集调用点
> **前置**：源自 **514 号**实施过程（#R2 实机复核）的附带发现——daemon 日志 `dim8 板块定位句构建失败 [xxxxxx.BJ]: Working outside of application context`
> **关联**：512/514（app_context 修复先例，均为「调用点无 context」同型）；481 号 B1（`get_cached_sector_heat` 数据侧已修）
> **HEAD（核查时）**：`758eeb3`（= origin/main）

---

## 一、缘起（2026-10-13）

514 号 #R2 实机复核时，在 `backend/logs/data_daemon.log` 发现**另一条与 #R2 不同源**的 app_context 报错：

```
2026-10-13 08:50:03,173 [WARNING] data_daemon: dim8 板块定位句构建失败 [000006.SZ]: Working outside of application context.
...
2026-10-13 09:19:22,641 [WARNING] data_daemon: dim8 板块定位句构建失败 [920982.BJ]: Working outside of application context.
```

用户指示「开 515 号处置 dim8 板块定位句」。本档为**只读核查**（未改代码/方案），拍板后再实施。

## 二、现象与影响面（实证）

| 项 | 实测 |
|---|---|
| 报错条数 | `grep -c "板块定位句构建失败" backend/logs/data_daemon.log` = **5557** |
| 涉及股票 | **5557** 只（正则 `\[[0-9]{6}\.[A-Z]{2}\]` 去重后 5557）→ **恰好全市场（每票一条）** |
| 时间窗 | 2026-10-13 08:50:03 → 09:19:22（旧 daemon；本轮全市场重算期间） |
| 级别 | WARNING（被 except 吞，**不阻断管道**） |

**结论**：daemon 归集 seven_dim 时，**全市场每只票的「板块定位句」均构建失败并被丢弃** —— 即前端「个股现状体检报告」**第一层环境定位**缺失「板块定位：X板块…（行业排名第N）」句（全市场性缺陷，非边缘个例）。

## 三、根因（代码实证链）

1. **报错点**：`app/opportunity_atlas/dimensions/dim8_summary_engine.py:1331`
   ```python
   except Exception as _e:
       # 507批次2：环境定位 helper 静默降级改 warning
       logger.warning("dim8 板块定位句构建失败 [%s]: %s", ts_code, _e)
       return ''
   ```
   位于 `_sector_position_sentence(dim_results, ts_code)`（def `:1301`）。
2. **抛错调用**：同函数 `:1316` → `industry = DataManager().get_stock_industry(ts_code)`；
   其实现 `app/data/__init__.py:353-356`：
   ```python
   def get_stock_industry(self, ts_code: str) -> str | None:
       stock = db.session.query(Stock).filter(Stock.ts_code == ts_code).first()
       return stock.industry if stock else None
   ```
   → **Flask-SQLAlchemy（`db.session.query(Stock)`），需 Flask app context**；无 context 线程调用即抛 `RuntimeError: Working outside of application context`。
3. **外层归集**：`Dim8SummaryEngine.build_seven_dim_report`（`:1676`）第一层环境定位段（`:1752-1786`）于 `:1763` 调 `_sector_position_sentence(dim_results, ts_code)`。
4. **daemon 无-context 调用点**（`build_seven_dim_from_dim_results` → 委派 `build_seven_dim_report`，`status_engine.py:1408/1418-1419`，其自身**不加** app_context）：
   - **`_precompute_strategy_signals`（`data_daemon.py:7287`）→ `:7343-7344`** `build_seven_dim_from_dim_results(dim_results, tags=_tags, ts_code=ts_code)` —— **该函数体内无 `app_context`**（`sed -n '7287,7330p'` 未见 `with`/`app_context`）⇒ **本 5557 条 warning 的产生路径**（SIG 步骤）。
   - `_backfill_seven_dim_jud`（`:6160`）→ `:6185` 同调用，经 `:6322` 于 `_build_status_snapshot`（JUD 步骤）调用；该函数体含 `with _flask_app.app_context():`（`:6215`）——**是否覆盖 `:6322` 待确认**（JUD 侧如已在 context 内则不报错）。
5. **唯一性**：`dim8_summary_engine.py` 全文 `db.session|Stock.query|get_stock_industry|from app import db` 检索**只命中 `:1304`（docstring）与 `:1316`** ⇒ **`_sector_position_sentence` 是 dim8 内唯一依赖 Flask-SQLAlchemy 者**；其余环境定位句（`_index_trend_sentence`/`_market_state_sentence`/`_sector_full_sentence`/`_industry_position_sentence`/`_relative_strength_sentence`）与其它 dim8 键**均不依赖 ORM**（context-free）。

**一行根因**：`_sector_position_sentence` 用 **ORM 版** `DataManager.get_stock_industry()`（需 app context），而 daemon 的 SIG 预计算路径 `_precompute_strategy_signals` 调 dim8 归集**未包 app_context** → ORM 抛 `Working outside of application context` → 被 except 吞成 WARNING → **全市场板块定位句被丢弃**。

## 四、修复方案（待拍板）

| 方案 | 内容 | 评价 |
|---|---|---|
| **A. 调用点补 context**（512/514 同型） | 在 daemon `_precompute_strategy_signals` 的 dim8 构建段（`:7341-7346`）包 `with _flask_app.app_context():`；并确认 `_build_status_snapshot`/`_backfill_seven_dim_jud` 路径 | 改动小、与既有先例一致；但治标——任何**新增**无-context 调用点仍会静默丢句；且 dim8 builder 被多处调用，逐点包裹易漏 |
| **B. 取数去 ORM 化**（治本） | `_sector_position_sentence` 改从不依赖 app context 的行业源取 `industry`（候选：① raw `sqlite3` 读 `data/app.db` 的 `Stock.industry`；② 复用 dim1 `dim_results['signal']['data_context']` 内已有行业；③ `industry_position_cache`（481③ 分库表）） | 治本——彻底消除该句对 context 的依赖；需选行业源口径 |
| **C. 双管** | B 为主 + A 为辅（对 dim8 其它潜在调用点做 context 防护） | 最稳，改动略大 |

> **附带核查项**：`DataManager.get_stock_industry_batch`（`app/data/__init__.py:358`）同为 ORM 版；若其亦被无-context 路径调用，属同型隐患，可一并核对调用方。

## 五、待业务拍板（Q1~Q3）

| Q | 议题 | 选项（首项为建议） |
|---|------|-------------------|
| **Q1** | 修复取向 | **A. 双管（B 治本 + A 防护）** / B. 仅 B 去 ORM 化 / C. 仅 A 调用点补 context / D. 维持现状仅登记 |
| **Q2** | 若含 B，行业源口径 | **A. raw sqlite 读 `app.db`（`Stock.industry`）** / B. 复用 dim1 `data_context` 既有行业 / C. `industry_position_cache` 分库表 |
| **Q3** | 附带核查 | **A. 一并核对 `get_stock_industry_batch` 调用方与 dim8 其它潜在 ORM 依赖** / B. 本次只修本处 |

### 拍板结果（2026-10-13）

- **Q1 → A（双管）**：B 治本（取数去 ORM 化）+ A 防护（daemon 调用点补 app context）。
- **Q2 → A**：行业源＝**raw sqlite 读 `app.db`（`stocks.industry`）**。
- **Q3 → A**：一并核对——`get_stock_industry_batch` 同型兜底（已一并处理）；dim8 全文仅此处依赖 ORM（无其它）。

## 六、批次建议与验证口径

- **批次1（单批）**：按 Q1 落地（一处 helper 取数 + 必要时调用点 context）+ Q3 附带核对。
- **验证**：
  - **定向**：daemon SIG 步骤重跑后 `data_daemon.log` **不再出现** `板块定位句构建失败`（现 5557 条 → 0）。
  - **内容**：随机抽票（含 `.BJ` 与主板）dim8 summary 含「板块定位：X板块{主线热点/较活跃/中等}（行业排名第N）」句；对照 `sector_heat` 值。
  - **回归**：涉及 `dashboard`/dim8 定向用例；涉 daemon 改动按 `full-regression-daemon-must-stop.md` 择机全量。

## 七、实施记录（2026-10-13，Q1=A 双管）

- **B 治本（取数去 ORM 化）** — `backend/app/data/__init__.py`：
  - `DataManager.get_stock_industry`：ORM 查询包 `try/except RuntimeError` → 无 context 时兜底
    `_get_stock_industry_ctxfree`（raw sqlite 读 `os.path.join(Config.DATA_DIR,'app.db')` 的 `stocks.industry`，
    进程内懒缓存 `_industry_ctxfree_map`）。
  - `get_stock_industry_batch`：**同型兜底**（Q3 一并）。
  - 补 `import os`。
- **A 防护（daemon 调用点补 context）** — `backend/data_daemon.py`：
  - 新增模块级 `_dim8_app = None`（`_account_risk_app` 同型缓存）；
  - `_precompute_strategy_signals` 的 dim8 归集调用（`:7343-7344`）改包 `with _dim8_app.app_context():`（首次懒建 app）。
- **验证**：
  - 定向测试 `backend/tests/test_515_sector_position_ctxfree.py` **2 passed**（独立线程无 context → 兜底 raw sqlite 命中 `000001.SZ=银行` / `600519.SH=白酒` / 未知=None；batch 同）。
  - **真实 app.db 无 context 读取命中**：`600519.SH=白酒`、`000001.SZ=银行`、`999999.SZ=None`，映射 **5571 条**。
  - `py_compile` 通过；`ruff`：`app/data/__init__.py` + 测试文件 **All checks passed**；`data_daemon.py` 保持既有 **40 基线（零新增）**。
  - **待观察（实机）**：daemon SIG 步骤下一次重跑后 `data_daemon.log` 该 warning **5557 → 0**；抽票 dim8 summary 含「板块定位：…（行业排名第N）」句。
- **待办**：全量回归（须先停 daemon + 看守，按 `full-regression-daemon-must-stop.md` 择机）。

## 八、定向实机验证（2026-10-13，无 app context 旧失败条件）

**背景**：管道 `pipeline_status` 对 `pipeline_date=20261012` 的 **`SIG` 已 `done`**（`09:19:26 [管道] SIG → done (OK (2097.0s) 5561/5561 stocks)`，即那批 5557 条 warning 的来源）；管道对 SIG 判据为「非 done 才跑」⇒ **重启 daemon 不会重跑 SIG**，故「daemon 日志 5557→0」需等**下一次全市场 SIG**（今日 10-13 日终，收盘后自动）。为即时取证，按「无 context」复刻 daemon 旧失败条件做定向验证。

**探针**：`backend/scripts/_515_ctxfree_verify_probe.py`（只读，不入库、不改管道）。复刻原理＝daemon 中 `_load_tags`/`_build_dim_engine_results` 本就无 context，仅 dim8 归集被 515 包了 context ⇒ **「无 context 调 dim8 归集」即旧失败条件**。

**结果（全程无 app context）**：

| # | 检项 | 结果 |
|---|------|------|
| 0 | `db.session.query(Stock)` | 抛 `RuntimeError: Working outside of application context.` ⇒ **旧失败条件实证存在** |
| 1 | `DataManager.get_stock_industry`（6 票） | 全返回真实行业（白酒/银行/电气设备/全国地产/保险/银行），**无异常** |
| 2 | 直调 `_sector_position_sentence`（构造真实行业 + sector_heat） | **6/6 产句**「板块定位：X板块较活跃（行业排名第15）」 |
| 3 | 复刻 daemon 真实链路（`StatusEngine` → `build_seven_dim_from_dim_results`，4 票） | 4 票 `sector_heat_n=109` 且含本行业；`000001.SZ`→银行（top_20，第19）、`000002.SZ`→全国地产（top_10，第3）**产句**；`600519.SH`/`300750.SZ` 因 `heat_level='none'`（rank 95/47）按 437「无热度则降级」返回空（设计行为，非缺陷） |
| — | 捕获「dim8 板块定位句构建失败」warning 数 | **0** |

**判定**：在旧失败条件下修复**已生效**（取数不再抛错、句恢复、warning=0）；A 侧（daemon 包 `_dim8_app.app_context()`）使 daemon 实际走 ORM 路径，更为稳妥。
**遗留**：真·daemon 日志口径（`data_daemon.log` 中 `板块定位句构建失败` **5557→0**）待下次全市场 SIG（今日日终）自动取得。

## 附：核查命令（只读）

- 报错点：`grep -rn "板块定位句构建失败" --include=*.py backend/app`
- 规模：`grep -c "板块定位句构建失败" backend/logs/data_daemon.log`（5557）；`grep -oE "\[[0-9]{6}\.[A-Z]{2}\]" ... | sort -u | wc -l`（5557）
- ORM 依赖面：`grep -nE "db\.session|Stock\.query|get_stock_industry|from app import db" app/opportunity_atlas/dimensions/dim8_summary_engine.py`（仅 :1304/:1316）
- daemon 调用点：`grep -n "build_seven_dim_from_dim_results" data_daemon.py`（:6185 / :7344）；`sed -n '7287,7330p' data_daemon.py | grep -nE "app_context|with _"`
