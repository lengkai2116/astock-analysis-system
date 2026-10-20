# 529号｜start.command 起服慢 + 浏览器「先无法打开」修复

**状态**：🟢 全面收官（v1.1：批次1 A + 批次2 B1 全部已实施，2026-10-20）
**HEAD（核查时）**：`13bbf97`（= origin/main 已推送；528 号 ①~④ 全面收官后）
**涉及文件**：`start.command`（脚本）、`backend/app/utils/db_lock.py`

---

## 一、缘起（2026-10-20 用户反馈）

「start.command 起服耗时较长，且浏览器打开也较慢，先提示无法打开，等待很长时间后才回复正常」→ 只读核查（未改代码）已报告根因，用户拍板**开号**并评估 **A、B 是否可以都做**。

## 二、只读核查结论（2026-10-20，未改代码）

### 根因1（主因）：API 冷启动被 daemon 写锁阻塞 ≈25-33s
- `app/__init__.py:189-192`：`create_app` 导入 routes 前调用 `wait_db_unlock`（511 号防锁风暴守卫，`db_lock.py` 默认 `max_wait=300s`、每 5s 重试）。
- **今日实测时间线**（`app.log`）：API 09:58:21 启动 → 09:58:24 `[WARNING] db_lock: 检测到数据库写锁: ['snapshot_cache.db']` → 09:58:57 `数据库写锁已释放（等待 25s）` → 09:58:58 就绪，**进程启动到就绪共 37s**。
- 锁持有方：daemon 早晨补采阶段写 `snapshot_cache.db`（09:58:50 `status_snapshot 构建完成` + JUD 预计算）；此窗口内起服 API 必被拖慢。

### 根因2（「先无法打开」直接原因）：start.command 15s 就绪超时不校验
- `start.command`「等待 API 就绪（最长 15s）」`for` 循环结束后**不检查 API 是否真就绪**即无条件继续 → 启动 WAL 守护 → `open` 浏览器。
- API 实测需 37s 就绪 → 浏览器 ~16s 打开时 5001 未监听 → 报「无法打开此页面」→ 就绪后（首条 200 09:59:14）刷新才正常。

### 观感加重
- daemon 早晨阶段 08:38→09:35 才进主循环（≈57min，早晨补采/RAW 阶段）；此时段内起服时「等待数据进程就绪」（`grep '进入主循环'`）会等满 30s，叠加浏览器前 `sleep 1` + WAL 守护检查。

## 三、A/B 可行性评估（2026-10-20 实证）

| 方向 | 结论 | 依据（代码实证） |
|---|---|---|
| **A**：start.command 就绪校验（未就绪继续等/明确提示，浏览器「就绪后开」） | ✅ **可做**（治本-1，纯脚本低风险） | `start.command` 15s 循环后无条件 `open`；加校验即可避免浏览器提前打开报错 |
| **B1**：`wait_db_unlock` 等待期打进度日志 + `max_wait` 300s→60s | ✅ **可做**（治本-2 子项，改善可观测性；超时继续启动有「后续重试机制兜底」注释） | `db_lock.py` 等待期仅 `_waited==0` 一条 warning + 释放一条 info，中间每 5s 静默重试 |
| **B2**：API 等待清单排除 `snapshot_cache.db`（等 8 库→等 7 库） | ❌ **不可做** | API 初始化 ECM 时 `sharding_manager` 会对 `snapshot_cache.db` **补索引 DDL**（424 P2-1，`sharding_manager.py:193-194`）——排除后 routes 导入仍撞该库锁，511 锁风暴回归风险（2026-10-12 实测 18 分钟） |
| **B3**：daemon 早晨补采写库与 API 启动错峰 | ⏸ 暂缓 | 涉及 daemon 调度/启动时序改动，超本轮范围，另立号评估 |

## 四、批次计划

- **批次1（A，`start.command`）**：「等待 API 就绪（最长 15s）」循环后加**就绪校验**——未就绪则继续等（如再等最长 45s，总最长 60s）并打印提示「API 尚未就绪，请稍候」，就绪后才 `open` 浏览器；避免浏览器提前打开报「无法打开」。
- **批次2（B1，`db_lock.py`）**：等待期每 ~10s 打一条「仍等待锁释放（已等 Xs）」进度日志（不刷屏）；`max_wait` 默认 300s→60s（API 与 daemon 调用点共用默认；超时继续启动的「重试机制兜底」注释保留）。
- （B2 不做、B3 暂缓——见 §三评估。）

## 五、验证

- `bash -n start.command` 语法校验 + 实测起服（用户双击 start.command：确认浏览器不再先报「无法打开」、等待期有进度提示）；
- `db_lock.py` 定向测试（新增：等待期进度日志出现、60s 上限超时仍返回）+ 相邻回归（test_428_gap_fixes 的 wait_db_unlock 用例）；
- py_compile/ruff 通过。

---

## 六、实施记录（2026-10-20，批次1 + 批次2 全部落地）

### 批次1（A：`start.command` 就绪校验）
「等待 API 就绪（最长 15s）」循环后新增：
- `API_READY` 标记 + 15s 未就绪则**继续等待**（`seq 16 60`，最长再 45s、总 60s），打印「⏳ API 尚未就绪，继续等待（最长再 45s，共 60s）...」；
- 60s 仍未就绪打印「⚠️ API 进程 60s 内未就绪——浏览器打开后可能短暂无法访问，请稍候手动刷新」（不再无条件 silent 打开浏览器）；
- 浏览器 `open` 仍在 WAL 守护启动之后执行（时序不变，但此时 API 大概率已就绪）。
- 验证：`bash -n start.command` 通过。

### 批次2（B1：`db_lock.py` 进度日志 + 上限 60s）
- **进度日志**：`wait_db_unlock` 等待循环中 `elif _waited % 10 == 0:` 每 10s 打一条 `仍等待数据库写锁释放（已等 Xs）: [...lock...]`（原等待期仅 `_waited==0` 一条 warning + 释放后一条 info，中间每 5s 静默重试——API 冷启动等锁时用户无反馈）；
- **上限**：默认 `max_wait` **300s→60s**（实测等锁 ≤30s，原 5 分钟上限过长；超时继续启动的「后续重试机制兜底」注释保留）；
- API（`app/__init__.py` create_app）与 daemon（`data_daemon.py` 薄包装）调用点共用默认值。

### 验证结果
新增 `test_529_startup_fixes.py` **5 passed**：
- 默认 max_wait=60.0（inspect 签名校验）；
- 持锁 17s → 等待期出现「仍等待数据库写锁释放（已等 10s）」进度日志（⚠️ 初版持锁 11s 不足——探测 `BEGIN IMMEDIATE` 在锁下阻塞 timeout=2s，到 `_waited=10` 探测点实际已过 ~14s、锁已释放；改持锁 17s）；
- 超时（max_wait=5、持锁 15s）→ 打「等待数据库写锁超时」日志且正常返回不抛异常；
- 无锁立即返回 + 锁释放后返回（对齐 test_428 既有用例，防回归）。
相邻回归 `test_428_gap_fixes.py` **40 passed** + py_compile/ruff（All checks passed）+ `bash -n start.command` 全过。

**浏览器目检/实机起服验证**：待用户双击 start.command 复核（`feedback/ui-verification-manual-by-user`）。
