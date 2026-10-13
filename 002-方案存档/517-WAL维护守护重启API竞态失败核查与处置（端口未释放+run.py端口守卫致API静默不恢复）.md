# 517号｜WAL 维护守护「停后即时重启 API」竞态失败核查与处置（端口未释放 + run.py 端口守卫致 API 静默不恢复）

> **版本**：v1.3（2026-10-13 只读核查 + **批次1（Q1-A + Q3-A）** + **批次2（Q2）** 均实施并实机验证 + **批次3（Q4）决策记录＝A 维持**）
> **性质**：运营/运维缺陷（WAL 守护自恢复链断裂）——`backend/wal_maintenance.py` + `backend/run.py`
> **前置**：2026-10-13 用户会话后台任务通知（旧 `start.command` 退出 143）触发核查；用户拍板「**开号处置（先落核查档）**」→「**提交推送，然后开工批次1**」
> **关联**：511（总库写锁，无关）；513/516（仪表盘，下游受影响者）
> **HEAD（核查时）**：`daa0f45`；**批次1 实施时 HEAD**：`3a041e8`（= origin/main）
> **核查时刻**：2026-10-13 18:4x（触发）/ 18:5x（核查）

---

## 一、缘起

2026-10-13 18:4x，会话收到后台任务通知：`start.command`（承载 API）退出 code 143（SIGTERM）。核查发现 **API 已宕（`curl health` = 000、无 `run.py` 进程）**，而 **daemon 被 WAL 维护守护重启为新 PID**。→ 定位到 WAL 守护的「停 daemon+API → 收缩 → 重启」链存在**竞态失败**。用户拍板**开 517 号，先落核查档**。

## 二、现象与实证

**（1）WAL 守护日志** `data/logs/wal_maintenance.log`（2026-10-13 18:43:45–46）：
```
18:43:45,445 [INFO] 收缩 stock_cache.db: 前 1.0MB
18:43:45,446 [INFO]   stock_cache.db PASSIVE: busy=0 frames=2 checkpointed=2
18:43:46,458 [INFO]   stock_cache.db 后 0.0MB
18:43:46,458 [INFO] ✅ 全部分库 WAL 收缩成功
18:43:46,477 [INFO] daemon 已重启（无看守）
18:43:46,478 [INFO] API 已重启          ← 假象
```

**（2）API 进程 stdout** `data/logs/api.log` 末尾（即 run.py 输出，2026-10-13 18:43:46）：
```
❌ 端口 5001 已被占用——API 可能已在运行，本次启动取消（单实例保护）
```

**（3）实测**：该时刻 `pgrep run.py` 无、`curl http://127.0.0.1:5001/api/v3/health/live` = **000** ⇒ **API 实际未起**；守护「API 已重启」为**无校验的假日志**。（本次已由助手以 `start_new_session=True` 分离方式恢复 API，`health=200`。）

**（4）同源复现**：当日助手**手动** `start.command` 重启时亦被同一「端口 5001 已被占用——本次启动取消」拦截一次（旧 API 套接字未及时释放）——**同根因**。

## 三、根因链

1. **`wal_maintenance.maintenance_once()`（`wal_maintenance.py:257-266`）**：`stop_processes(['data_daemon.py','run.py'])` → `time.sleep(2)` → `shrink_wal()` → `start_processes()`——**无「等待端口释放」环节**（仅 2s 固定 sleep，且位于 shrink 之前）。
2. **`start_processes()`（`:180-206`）**：`subprocess.Popen([VENV_PYTHON,'run.py','--port','5001'], start_new_session=True, stdout/stderr→data/logs/api.log)`，随后**无条件** `logger.info("API 已重启")`——**无端口就绪校验、无 health 回环、无重试、无退出码检查**。
3. **`run.py` 单实例守卫（`run.py:16-25` `_port_in_use`；`:40-41` 守卫）**：`_port_in_use(port)` 用 **裸 `socket.bind(('127.0.0.1', port))`** 探测占用；刚被 SIGTERM 的 API，其 5001 连接可能仍在 **TIME_WAIT** ⇒ 裸 bind **EADDRINUSE** ⇒ **误判「已被占用」** ⇒ `run.py` 打印提示并 **`sys.exit`** ⇒ **API 静默不恢复**。
   - `_port_in_use` **未设 `SO_REUSEADDR`**，无法区分「真实 LISTEN」与「TIME_WAIT 残留」。

**结论**：`stop → 立即 start` 的竞态 ⇒ run.py 端口守卫误拒 ⇒ 守护**无校验**记成功 ⇒ **API 静默宕且不自恢复**。

## 四、影响面

- **每次 WAL 收缩**（条件：非交易时段 + 管道空闲 + WAL 超阈值）**都可能静默停掉 API 且不自恢复** ⇒ 仪表盘与全部 API 端点在守护收缩后不可用，直至人工/下一次成功启动。
- 与 `stop_processes` 的「10s 未退则 SIGKILL」无关（问题在 **start 侧**端口竞态与无校验）。
- 与 511（总库写锁恒持）**无关**、非同一根因；与 516（仪表盘模块）为**下游受影响**关系。

## 五、处置候选（待拍板）

| Q | 议题 | 候选 |
|---|---|---|
| **Q1** | `start_processes` 健壮化 | **A. 停后轮询等待端口释放（≤30s）再起 + 起后回环 health 校验、失败重试** / B. 仅加起后校验+重试 / C. 维持现状 |
| **Q2** | `run.py._port_in_use` 探测语义 | **A. 探测前 `setsockopt(SOL_SOCKET, SO_REUSEADDR)`（只识别真实 LISTEN，不受 TIME_WAIT 干扰）** / B. 维持（依赖 Q1-A 的等待/重试） |
| **Q3** | 守护日志真实性 | **A. 「API 已重启」仅在健康校验通过后记录，否则 WARNING + 重试** / B. 维持 |
| **Q4** | 无看守时自恢复 | A. 维持（守护自身即恢复通道） / B. 引入轻量看守 |

## 六、批次建议

- **批次1（低风险，建议）**：**Q1-A + Q3-A**（停后等端口释放 + 起后 health 校验/重试 + 日志据实）→ 根治「静默不恢复」。
- **批次2**：**Q2**（`_port_in_use` 加 `SO_REUSEADDR`）——须评估只改「探测语义」、不掩盖真实占用（真实 LISTEN 仍应探测为占用）。
- **批次3（可选）**：Q4。

**验证口径**：构造 `maintenance_once()`（或等价 stop→立即 start）场景 → **API 必须自动恢复（health 200）**、无「已重启」假日志；连续多次稳定。

## 七、实施记录（批次1，2026-10-13）

**范围**＝**Q1-A + Q3-A**（§五 / §六 建议项）。**性质**＝运维健壮化（`wal_maintenance.py`，不改业务判定）。

- **Q1-A（起 API 前等端口释放）**：新增 `_port_bindable(port)`——与 `run.py._port_in_use` **同语义**的**裸 `bind` 探测**（**不加 `SO_REUSEADDR`**，确保「此处可绑 ⇒ run.py 守卫必放行」）；`start_processes` 起 API 前**轮询等 `_port_bindable(5001)`**（≤40s）。
- **Q3-A（起后回环 health 校验 + 日志据实）**：新增 `_api_healthy(port)`（回环 `GET /api/v3/health/live`，≤2s 超时）；`start_processes` 起 API 后**轮询 `_api_healthy(5001)`**（≤15s）；**仅在通过后**记 `API 已重启（health 校验通过）`，否则 `WARNING` 并**重试一次**，两次均失败记 `ERROR`（需人工介入）。
- **测试**：新增 `backend/tests/test_517_wal_guardian_restart.py`（2 用例：①`_port_bindable` LISTEN 占用/释放语义；②`start_processes` 含「等端口 + health 校验 + 成功日志仅在确认后」）。

**验证**：`py_compile` OK；`ruff` **All checks passed**；定向 `test_517_wal_guardian_restart` **2 passed**。
**实机验证（等价 stop→start，2026-10-13 19:06）**：停 API（PID 34043）→ 调**新** `start_processes()` → **自动恢复**：输出 `API 已重启（health 校验通过）`、`curl health` **200**（新 API PID 35214）、`data/logs/api.log` 记录**正常启动**（`Running on ...` + werkzeug 200），**不再出现**旧「端口 5001 已被占用」。⇒ 原「静默不恢复」场景**已闭环**；WAL 守护已重启加载（新 PID 35146）。

**生效前置**：WAL 守护（`wal_maintenance.py --daemon`，核查时 PID 4134）为**长驻进程**，**需重启守护**方加载本修复。

**遗留**：~~批次2＝Q2~~（已于批次2 实施，见 **§八**）；**批次3（可选）＝Q4**。

## 八、实施记录（批次2，2026-10-13）

**范围**＝**Q2**（`run.py._port_in_use` 探测语义；连带对齐 `wal_maintenance._port_bindable`）。**性质**＝运维健壮化（不改业务判定）。

> **⚠️ 口径纠正（实施前实测发现）**：§五 Q2-A 的**字面写法**「仅加 `SO_REUSEADDR`、仍探 `127.0.0.1`」在本机（macOS）**会让单实例守卫失效**——`run.py` 服务器实际绑 `0.0.0.0`，而守卫探 `127.0.0.1`；加 `SO_REUSEADDR` 后二者不再冲突，守卫会把「正在运行的 API」**误判为未占用**。实测矩阵：
>
> | 场景 | 探 `127.0.0.1` 裸bind | 探 `127.0.0.1`+REUSEADDR | 探 `0.0.0.0` 裸bind | 探 `0.0.0.0`+REUSEADDR |
> |---|---|---|---|---|
> | 真实 LISTEN 于 `0.0.0.0` | 判占用 ✅ | **判未占用 ❌ 漏判** | 判占用 ✅ | 判占用 ✅ |
> | TIME_WAIT 残留 | 误判占用 ❌ | 放过 ✅ | 误判占用 ❌ | 放过 ✅ |
>
> ⇒ **正确改法＝`SO_REUSEADDR` + 探服务端实际绑定地址 `0.0.0.0`**（与 `socketio.run(host="0.0.0.0")` 一致）。
> 补：`http.server.HTTPServer.allow_reuse_address=1`、`werkzeug BaseWSGIServer.allow_reuse_address=True` ⇒ 服务端自身亦设 `SO_REUSEADDR`，故「守卫放行 ⇒ werkzeug 亦能绑定」在 TIME_WAIT 下成立，端到端自洽。

- **`run.py._port_in_use`**：裸 `bind(('127.0.0.1', port))` → `setsockopt(SOL_SOCKET, SO_REUSEADDR)` + `bind(('0.0.0.0', port))`。
- **`wal_maintenance._port_bindable`（批次2 连带对齐）**：同步改为 `SO_REUSEADDR` + `0.0.0.0`，与守卫**完全同语义**——不变量「此处可绑 ⇒ 守卫放行」保持；且看守不再等 TIME_WAIT，**缩短 API 停机窗口**（达成批次2 目标）。
- **测试**：`test_517_wal_guardian_restart.py` 监听地址改 `0.0.0.0` + **新增 3 用例**（真实 LISTEN 仍判占用 / TIME_WAIT 放过 / `_port_bindable` 语义）；`test_fix_startup.py` 占用探测监听地址订正为 `0.0.0.0`（与守卫语义一致）。

**验证**：`py_compile` OK；`ruff` `wal_maintenance.py`/`test_517`/`test_fix_startup` **All checks passed**（`run.py` 两处 `I001` 为**改动前既有**，未触碰——`--fix` 会打乱「先清代理再导第三方」语义）；定向 `test_517`+`test_fix_startup` **10 passed**。
**实机验证（2026-10-13 19:44，复刻 517 失败条件）**：停 API 制造端口 5001 **TIME_WAIT 残留**（裸 bind FAIL=误判占用）→ 新 `_port_in_use(5001)`=**False**、`_port_bindable(5001)`=**True** → 调**新** `start_processes()` 输出 `API 已重启（health 校验通过）`、**`curl health`=200**（新 API PID 37686）、`data/logs/api.log` 正常启动（**无**「端口 5001 已被占用」）。**已重启 WAL 守护**加载（PID 35146→37881）。daemon 33819（日终管道）**未触碰**。

**遗留**：批次3（Q4）见 **§九**。

## 九、决策记录（批次3 / Q4：「无看守时自恢复」，2026-10-13）

**拍板：Q4 = A（维持，不实施）**——不新增独立看守/自恢复进程；仅记录决策与依据（无代码改动）。

**依据（只读核查 2026-10-13）**——现有恢复通道矩阵：

| 通道 | 覆盖对象 | 触发条件 | 当前态 |
|---|---|---|---|
| `start_daemon.sh`（看守） | 仅 `data_daemon.py` | daemon 退出 → 10s 重启 | 登录项（Terminal.app）拉起；**核查时未运行**（即「无看守」态） |
| `start.command` | daemon+API 启动 | 前台 `wait $API_PID`；**API 退出即脚本退出，不重启** | — |
| `wal_maintenance.py --daemon`（WAL 守护） | daemon+API | **仅「维护触发」时**（WAL>500MB + 非交易 + 管道空闲）→ `start_processes()`（批次1/2 已健壮化） | 运行中 |
| launchd | — | `com.stock.analyzer.datadaemon.plist` 已 `.disabled`；`com.stock.analyzer.backend`（gunicorn 旧架构）已加载但未运行（PID `-`） | 无效通道 |

**理由**：
1. 本号真正根因（**WAL 维护触发的 API 静默宕机**）已由**批次1（起后 health 校验 + 日志据实）+ 批次2（TIME_WAIT 不再误拒）**闭环；**WAL 守护自身即该路径的恢复通道**。
2. 系统定位为**建议输出型**（`project/system-positioning-advice-only.md`）；研发阶段 **daemon 可随时停**（`project/daemon-stop-policy.md`）——新增常驻看守会与「可随时停」规则冲突，并引入**双实例 / SQLite 写锁竞争**风险（本号 Q1/Q3 已为同类竞态付过代价）。
3. 正常使用由**登录项看守**（daemon）+ **双击 `start.command`**（API）覆盖；异常时的短暂不可用可接受。
4. 长期 7×24 由**云端数据大脑**规划承担（`project/deployment-plan.md`），非 macOS 本地看守。

**影响（已知取舍，非缺陷）**：无看守时，API/daemon 因**其它原因（崩溃）**退出**无人自动拉起**；恢复方式＝重新双击 `start.command`（API）/ 走登录项看守（daemon）。

**结论**：517 号**全面收官**（核查档 + 批次1 + 批次2 + 批次3/Q4 决策）。

## 附：核对命令（只读）

- 守护日志：`tail data/logs/wal_maintenance.log`
- API stdout（run.py 提示语在此，非 `backend/logs/app.log`）：`tail data/logs/api.log`
- 代码定位：`wal_maintenance.py:180-206`（`start_processes`）/ `:257-266`（`maintenance_once`）/ `:155-157`（`stop_processes`）；`run.py:16-25`（`_port_in_use`）/ `:40-41`（守卫）
- 复现：`grep -c "本次启动取消" data/logs/api.log`
