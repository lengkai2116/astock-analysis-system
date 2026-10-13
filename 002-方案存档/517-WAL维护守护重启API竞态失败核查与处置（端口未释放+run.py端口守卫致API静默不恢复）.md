# 517号｜WAL 维护守护「停后即时重启 API」竞态失败核查与处置（端口未释放 + run.py 端口守卫致 API 静默不恢复）

> **版本**：v1.0（2026-10-13 只读核查；**未改代码**）
> **性质**：运营/运维缺陷（WAL 守护自恢复链断裂）——`backend/wal_maintenance.py` + `backend/run.py`
> **前置**：2026-10-13 用户会话后台任务通知（旧 `start.command` 退出 143）触发核查；用户拍板「**开号处置（先落核查档）**」
> **关联**：511（总库写锁，无关）；513/516（仪表盘，下游受影响者）
> **HEAD（核查时）**：`daa0f45`（= origin/main）
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

## 附：核对命令（只读）

- 守护日志：`tail data/logs/wal_maintenance.log`
- API stdout（run.py 提示语在此，非 `backend/logs/app.log`）：`tail data/logs/api.log`
- 代码定位：`wal_maintenance.py:180-206`（`start_processes`）/ `:257-266`（`maintenance_once`）/ `:155-157`（`stop_processes`）；`run.py:16-25`（`_port_in_use`）/ `:40-41`（守卫）
- 复现：`grep -c "本次启动取消" data/logs/api.log`
