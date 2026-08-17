---
title: 业务数据库对齐实施方案（PostgreSQL → SQLite app.db，方向1）
type: 实施方案
date: 2026-08-13
status: ✅ 已实施（2026-08-13 全部完成：.env改SQLite、数据迁移、兼容验证、文档同步、防静默）
---

# 331 — 业务数据库对齐实施方案（PostgreSQL → SQLite app.db）

> 背景：核查发现 `.env` 配置 `DATABASE_URL=postgresql:///stock_analysis`（251号方案残留）与 292 号权威方案（业务数据存 SQLite `data/app.db`）冲突，导致运行中 API 经 `load_dotenv()` 静默连 PostgreSQL、业务数据双库漂移。本方案按方向 1 对齐 292 权威，将业务库改回 SQLite。

## 一、核查结论（前置依据）

### 1.1 当前状态（实测）

| 项 | 现状 | 证据 |
|----|------|------|
| 运行库 | **PostgreSQL**（`postgresql:///stock_analysis`） | `.env` L20 + `load_dotenv()` + 实测 signal_records 08-13 18:35 写入 PG |
| SQLite app.db | **已停更**（signal_records 最后写入 07-12） | data/app.db 实测 |
| PG 业务数据 | 仅 2 表有数据：strategy_templates_v2(20) + signal_records(11)，其余 37 表全空 | pg_stat_user_tables 实测 |
| Docker | **已废止**（docker daemon 未运行），本机 PG 为 Homebrew 裸装 | 170号方案 + docker ps 失败 |

### 1.2 表结构兼容性（实测）

- SQLite app.db 29 张表 = PG 39 张的**子集**
- 缺 10 张：`daily_data`、`opportunity_library`、`realtime_concepts/lhb/limit_pool/minute_kline/news/sectors/snapshot/top_stocks`
- **opportunity_library 有 ORM 模型**（models/opportunity_library.py，被 radar/advice_generator 使用）→ `db.create_all()` 会自动建
- **realtime_*/daily_data 无 ORM 模型**（仅注释提及）→ 无模型引用，改 SQLite 不影响运行（盘中实时已由 InMemoryStateStore 承载）
- `db.create_all()` 在 app/__init__.py L157 启动时自动执行

## 二、实施方案

### Step 1：修改 `.env`（核心）

```ini
# 业务数据库：对齐 292 权威方案，SQLite app.db（原 PostgreSQL 残留）
DATABASE_URL=sqlite:///data/app.db
```

- 与 `.env.example` L35（已是 `sqlite:///data/app.db`）保持一致
- 注释标明变更依据（292 权威 + Docker 废止）

### Step 2：业务数据迁移（PG → SQLite）

PG 仅 2 表有数据，迁移量极小：

| 表 | PG 行数 | SQLite 现状 | 迁移方式 |
|----|:---:|:---:|---------|
| strategy_templates_v2 | 20 | 已有 11（旧） | **取并集**（按 id 去重合并，PG 的 12/6/4 等新 id 插入） |
| signal_records | 11（08-13 改进2 落库） | 已有 30（至 07-12） | **追加合并**（PG 的 11 条新记录插入，含改进2 的 operation_advice 记录） |

迁移脚本（一次性，`scripts/migrate_pg_to_sqlite.py`）：
```python
# 伪代码：psycopg2 读 PG 两表 → sqlite3 写 data/app.db，按主键去重
# strategy_templates_v2: INSERT OR IGNORE（id 主键）
# signal_records: 按 (ts_code, signal_date, strategy_name, created_at) 去重后 INSERT
```

**风险控制**：迁移前备份 `data/app.db`（cp 副本）；迁移后校验行数（PG 行数 + SQLite 原行数 - 重复 = SQLite 最终行数）。

### Step 3：启动兼容性验证

1. 停止 API → 改 `.env` → 启动 API
2. 验证 `db.create_all()` 自动创建 opportunity_library（SQLite 缺表）
3. 验证健康检查：`/api/v3/health/ready` 的 dependencies 正常
4. 验证业务写入：触发一次 analyze → signal_records 写入 SQLite app.db（非 PG）
5. 确认无模型缺失报错（realtime_* 无模型，不报错）

### Step 4：文档同步（3 处）

| 文件 | 修改 |
|------|------|
| AGENTS.md | L62 `make dev-db # 启动 PostgreSQL+Redis` → 更新为"历史残留，当前 SQLite 单机"；L54 禁用 PG 表述保留（与 292 一致） |
| 292号方案 | L744 `5432 PostgreSQL 开发环境 Docker 使用` → 更新为"历史残留（251号），当前业务库=SQLite app.db" |
| 331号方案 | 实施完成后标记 ✅ 已实施 |

### Step 5：防御性改进（防静默）

- `backend/app/config.py` 或 `__init__.py`：`load_dotenv()` 后打印启动日志，明确"业务库 = {DATABASE_URL}"
- 可选：启动时校验 DATABASE_URL 是否含 `sqlite`（生产模式），非 sqlite 时 warning（防再次误配 PG）

## 三、影响评估

| 项 | 影响 | 说明 |
|----|:---:|------|
| 机会图谱板块 | ➖ 无影响 | treemap/diagnose 读 ECM 缓存（stock_cache.db），不依赖业务库 |
| 个股分析板块 | ➖ 无影响 | analyze 读 ECM 缓存 + 实时组装，业务库仅落库 SignalRecord |
| 改进2 验证环 | 🟢 改善 | operation_advice 落库从 PG 改为 SQLite（本地无 PG 环境也可靠），回退逻辑可简化 |
| 复盘/账户/策略 | 🟢 对齐 | 业务数据统一在 SQLite app.db（与 AGENTS.md/292 一致） |
| 风险 | 🟡 | ①PG 中 signal_records 11 条需迁移（含改进2 成果）②strategy_templates_v2 20 条需合并去重 |

## 四、验收标准

1. `.env` DATABASE_URL = `sqlite:///data/app.db`
2. 启动后 opportunity_library 表自动创建（`sqlite3 data/app.db ".tables"` 可见）
3. 触发 analyze 后 signal_records 写入 SQLite（`sqlite3 data/app.db "SELECT ... WHERE strategy_name='operation_advice'"` 有新记录）
4. 健康检查 `/api/v3/health/ready` 通过
5. PG 中两表数据已迁移至 SQLite（行数校验通过）
6. 业务功能（复盘/账户/策略模板）读写正常
7. 无 create_all 报错、无模型缺失报错

## 五、回滚方案

- 保留 `.env` 备份（cp .env .env.bak）
- 若 SQLite 模式异常：恢复 .env.bak + 重启 API 即回 PG
- 数据安全：迁移前备份 data/app.db；PG 数据保留不删（可随时反向迁移）

---

**关联文档**：292（权威）、251（PG 引入）、170（Docker 废止）、330（改进2 验证环）、AGENTS.md

**文档版本**: v1.0
**编制日期**: 2026-08-13
