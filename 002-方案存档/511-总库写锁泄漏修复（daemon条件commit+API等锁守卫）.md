# 511号｜总库写锁永久泄漏修复（daemon 条件 commit + API 等锁守卫）

> **版本**：v1.1（2026-10-12 开号拍板 + ①②全实施 + 定向回归通过 + 重启实测写锁不再恒持）
> **v1.1 补充**：① `_recover_stale_running` 无条件 commit + ② `wait_db_unlock` 提取公共模块（`app/utils/db_lock.py`）并在 API `create_app` 接入均已实施；`py_compile` 通过、ruff 零新增（data_daemon 基线 40 errors 保持不变）、定向 52 passed；daemon 重启实测写锁探测 0.0s 空闲（修复前恒持 2.1s locked）、API 重启 ~30s 绑定 5001（修复前 ~18 分钟）。
> **前置**：`project/eod-write-lock-leak-20261012.md`（根因 100% 定位，诊断补丁已回滚，待开号）
> **性质**：daemon 写事务收尾修复（非「果」层判定语义）——根因已实证，直接实施

---

## 一、缘起与拍板记录（2026-10-12）

用户「按 2026-10-12 记忆开号修总库写锁泄漏」→ 只读核查现状（行号与记忆一致）→ 范围/验证两问拍板：

| 拍板 | 决策 | 实质 |
|------|------|------|
| 修复范围 | **核心修复 + API 等锁守卫** | ① `_recover_stale_running` 无条件 commit（根治泄漏）；② 将 `_wait_db_unlock` 提取为公共函数，API `create_app` 在 routes 导入前调用（防御未来其它进程持锁） |
| 验证方式 | **定向回归 + 重启实测** | py_compile + ruff + 相关单测；重启 daemon 用 F_GETLK 确认写锁不再恒持、重启 API 确认启动不再锁风暴（不在盘中长时间中断采集） |

## 二、根因与现状核查（2026-10-12 代码实证，行号与记忆一致）

### 根因：`_recover_stale_running` 条件 commit（data_daemon.py:6619）

```python
def _recover_stale_running(timeout_hours: float = 4.0) -> int:
    try:
        rc = _ecm.conn.execute(
            "UPDATE pipeline_status SET status='pending', detail='stale running 重置' "
            "WHERE status='running' AND started_at < datetime('now','localtime', ?)",
            [f'-{int(timeout_hours)} hours']
        ).rowcount
        if rc > 0:                 # 无 stale running（正常态）→ rc==0
            _ecm.conn.commit()     # → commit 被跳过，但隐式 BEGIN 已开写事务
        return rc
```

- Python sqlite3 在执行 UPDATE 前**已隐式 BEGIN**（0 行也开写事务）→ commit 被跳过时，ECM 总库写连接 `self.conn` 永久挂未提交写事务 → `stock_cache.db` WAL 写锁长期持锁。
- `_drive_pipeline()` 第一句调用（:6752）→ daemon 每次启动/每 tick 重现。
- **同型缺陷先例**：482号 §9.4 `mark_step_running` 缺 commit（2026-09-25 已修，现无条件 commit，与 mark_step_done/failed 对称）。
- **影响链**：daemon 恒持写锁 → API 启动 ECM `_init_tables`（EnhancedCacheManager.__init__ → busy_timeout=30s）每次写撞锁等满 → 26+ 次 ≈ 18 分钟锁风暴（2026-10-12 实测 5001 才绑定）。

### 全项目同类模式排查（只读）

| 位置 | 模式 | 结论 |
|------|------|------|
| `data_daemon.py:6634` | `if rc > 0: commit()` | 🔴 本号修复对象 |
| `stg_quality.py:675` | `rc=...rowcount; commit()` 无条件；`if rc>0` 仅日志分支 | ✅ 正确，无需改 |

### API 端 ECM 初始化链（等锁守卫落点依据）

`run.py` → `create_app()`（app/__init__.py）→ `from app.routes.factors import ...`（:188 附近）→ `factors.py:31 cache_manager = get_ecm_instance()` → `EnhancedCacheManager.__init__` → `_init_tables()`（数百条 DDL/迁移写）。→ **守卫须在 create_app 内 routes 导入之前调用**。

## 三、修复设计

### ① 核心修复（data_daemon.py `_recover_stale_running`，1 行）

```python
        rc = _ecm.conn.execute(
            "UPDATE pipeline_status SET status='pending', detail='stale running 重置' "
            "WHERE status='running' AND started_at < datetime('now','localtime', ?)",
            [f'-{int(timeout_hours)} hours']
        ).rowcount
        # 511号：无条件 commit——0 行 UPDATE 时 sqlite3 已隐式 BEGIN 开写事务，
        # 原 if rc>0 跳过 commit → 总库写连接永久挂未提交事务 → stock_cache.db
        # 写锁恒持（2026-10-12 实证 API 启动 18 分钟锁风暴）。对齐 482号 §9.4 先例。
        _ecm.conn.commit()
        if rc > 0:
            logger.info(f"  [管道自愈] 清理 {rc} 个超时 running 环节（>{timeout_hours}h）")
        return rc
```

### ② API 等锁守卫（提取公共函数 + create_app 接入）

- **新增** `backend/app/utils/db_lock.py`：把 `_wait_db_unlock`（data_daemon.py:7927 现定义）迁移为公共函数 `wait_db_unlock(data_dir, max_wait=300.0)`（仅依赖 os/time/sqlite3/logger，无包副作用——`app/utils/__init__.py` 为空）。
- **data_daemon.py**：删除本地定义，改 `from app.utils.db_lock import wait_db_unlock as _wait_db_unlock`（main() 内 :7978 调用点不变，测试 `dd._wait_db_unlock` 兼容——测试 import data_daemon 模块属性）。
- **app/__init__.py create_app()**：在 routes 批量导入之前插入：
  ```python
  # 511号：启动前等待核心 SQLite 分库写锁释放（daemon 持锁时避免 ECM 建表
  # 迁移在 30s busy_timeout 下空转——2026-10-12 实测 18 分钟锁风暴）
  try:
      from app.utils.db_lock import wait_db_unlock
      _boot_data_dir = os.environ.get('DATA_DIR') or os.path.join(
          os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
      wait_db_unlock(_boot_data_dir)
  except Exception as e:
      logger.warning(f'数据库锁等待异常: {e}')
  ```

## 四、验证口径

- **静态**：`py_compile data_daemon.py app/utils/db_lock.py app/__init__.py` 通过；ruff data_daemon 基线 40 errors **零新增**（stash 对比确认），app/__init__.py、app/utils/db_lock.py 零错误。
- **单测**：`test_426_phase3_schedule.py` + `test_428_gap_fixes.py` **52 passed**（3.08s）——含 `_wait_db_unlock` 行为测试（薄包装兼容，`dd._wait_db_unlock` 仍可用）。
- **重启实测**（2026-10-12 盘中，结果已记录于 v1.1）：
  1. ✅ 重启 daemon+看守：新代码进入主循环；
  2. ✅ 写锁探测（`BEGIN IMMEDIATE` 短超时，`_wait_db_unlock` 同款）：**修复前恒持（2.1s 后 locked）→ 修复后连续 3 次 + 主循环期再测均 0.0s 空闲**——写锁泄漏根治；
  3. ✅ 重启 API：**~30s 绑定 5001**（修复前 ~18 分钟锁风暴），health 200，启动日志无 `database is locked`；
  4. ✅ daemon 日志无异常（仅既有 `income_cache no such column: trade_date` 完整性检查噪声，与本修复无关）。
- **全量回归**：本次未做（盘中不中断采集）；后续按 `project/full-regression-daemon-must-stop.md` 约定择机停 daemon 补跑。

## 五、附带发现（登记不修）

- **API 后台线程日终同步缺 app context**（`scheduler_manager.py:425` "日终同步失败: Working outside of application context"）：`catch_up_if_needed` 启动补采的后台线程缺 `app_context`。**既有缺陷**，修复前被写锁风暴掩盖（catch_up 根本跑不动），锁释放后暴露。超本次范围，登记待后续处理。
- **F_GETLK 探测在本机 WAL shm 受限**（macOS `struct flock` 布局差异/APFS 锁语义），本次改用 `BEGIN IMMEDIATE` 短超时探测（即 `_wait_db_unlock` 实际实现，测试已验证），更直接反映写锁占用。
