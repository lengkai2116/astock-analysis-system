# A股股票分析系统 — Agent 指令

> 本文件存储项目级全局指令，任何 AI 编码代理访问本项目时自动遵循。
> 目标：防止反复试错，加速每次会话的启动。

---

## 一、文档存档规范

**每次操作完成后必须执行：**

### 📝 沟通记录

- `001-沟通记录/YYYY-MM-DD.md` 存在则追加，不存在则新建
- 格式：`### 序号 - 主题` → **用户输入** / **AI执行内容**
- 同一日多文件：`YYYY-MM-DD-02.md` 等后缀
- 完成后更新 `001-沟通记录/沟通索引.md`

### 📋 方案存档

- 设计方案、评估报告等 → `002-方案存档/序号-标题.md`
- 编号 = 目录中已有文件最大编号 + 1，跨会话持续递增
- 文件头包含 title、type、date 元信息

### 🔴 全局数据体系文档规则（2026-07-23 起强制执行）

- **唯一权威文件**：`002-方案存档/292-全局数据体系权威架构说明（2026-07-23版）.md`
- **禁止创建新的全局数据体系架构文档**：所有涉及全局数据体系架构的修订，必须直接编辑 292号文件，不得创建新的编号文档
- **17 份历史方案已标注作废**：239/241/242/243/244/245/246/248/249/250/251/254/260/264/266/279/284 号，任何 AI 代理访问本项目时，如需参考全局数据体系架构，必须优先读取 292号文件

---

## 二、Windows 迁移兼容性

所有代码必须考虑未来迁移到 Windows：

| 级别 | 规则 |
|------|------|
| **必须** | 文件路径用 `pathlib.Path`（禁止 `os.path`、硬编码 `/` 或 `\`） |
| **必须** | SocketIO 后端避免 `eventlet`（Windows 兼容性差），新代码用 `gevent-websocket` 或抽象切换层 |
| **必须** | 避免 `os.fork()`、`signal.SIGKILL` 等 Unix-only API |
| **必须** | 文件读写始终指定 `encoding='utf-8'` |
| **必须** | 服务优先 Docker 容器化 |
| **建议** | 环境变量路径分隔符用 `os.sep` / `pathlib`；自动化提供 `.ps1` 替代 `.sh`；避免 `fcntl`、`termios` |

---

## 三、系统架构要点

### 生产环境（桌面应用）

- **单进程 Flask**（eventlet）: `python backend/run.py --port 5001`
- **唯一端口 5001**：托管 SPA + REST API + WebSocket，禁止引入其他端口
- **数据库**：SQLite（OLTP, app.db）+ SQLite WAL（盘后缓存, stock_cache.db），禁用 PostgreSQL/Redis
- **缓存**：`cachetools.TTLCache`（内存），禁用 Redis
- **前端**：Flask `send_from_directory` 托管 Vue 构建产物，无需 Nginx
- **数据目录**：`DATA_DIR` 环境变量，禁止硬编码

### 开发环境（单机直跑，Docker 已废止——170号方案）

```bash
python backend/run.py --port 5001   # 启动后端（业务库=SQLite data/app.db，331号对齐292权威）
cd frontend/vue-project && npm run build  # 构建前端（若存在）
# 注：PostgreSQL/Redis 已废止（251号残留 .env 已清理，见 331号方案）
```

### 双进程架构

| 进程 | 文件 | 职责 |
|------|------|------|
| **数据进程** | `backend/data_daemon.py` | mootdx TCP 采集（5s）、日终同步（15:30）、完整性检查、分钟数据采集与聚合、指标预计算、因子预计算、信号预计算 |
| **API 进程** | `backend/run.py` | Flask REST API + SocketIO 推送 |

数据进程启动时会设置 `DATA_DAEMON_RUNNING=1`，API 进程据此跳过采集器初始化和日终同步注册。

### Data Daemon 全量采集覆盖清单

data_daemon 启动后先后执行：
1. 实时采集器：mootdx TCP（5s 快照）+ AKShare（1800s 板块/分钟线/龙虎榜/舆情）
2. `run_integrity_check(backfill_days=3)`：回溯 3 个交易日批量补采以下 10 类
3. 主循环 30s：消费 sync_requests 队列、15:30 日终同步、整点非交易时段巡检

| 数据表 | 采集函数 | 完整性检查 | 日终同步 | sync_requests |
|--------|----------|:----------:|:--------:|:-------------:|
| daily_cache | `_batch_daily` | ✅ 阈值5000行 | ✅ | ✅ `full_daily` |
| daily_basic_cache | `_batch_daily_basic` | ✅ 阈值5000行 | ✅ | ✅ `full_basic` |
| moneyflow_cache | `_batch_moneyflow` | ✅ 阈值1000行 | ✅ | ✅ `full_moneyflow` |
| stk_limit_cache | `_batch_stk_limit` | ✅ 阈值1000行 | ✅ | — |
| lhb_cache | `_batch_lhb` | ✅ 阈值20行 | ✅ | — |
| lhb_detail_cache | `_batch_lhb_detail` | ✅ 空表检查 | ✅ | — |
| concept_cache | `_batch_concept` | ✅ 有数据即可 | ✅ | — |
| index_member_cache | `_batch_index_member` | — | ✅ | — |
| margin_cache | `_batch_margin` | ✅ 空表检查 | ✅ | — |
| fina_indicator_cache | `_batch_fina_indicator` | ✅ ≥100行 | 财务同步后台 | — |
| income_cache | `_batch_income_recent` | — | 财务同步后台 | — |
| balancesheet_cache | `_batch_balancesheet` | — | 财务同步后台 | — |
| cashflow_cache | `_batch_cashflow` | — | 财务同步后台 | — |
| forecast_cache | `_batch_forecast` | — | 财务同步后台 | — |
| **adj_factor_cache** | `_batch_adj_factor` | ✅ 空表检查 | ✅ 日终补充 | ✅ `adj_factor` |
| **top10_holders_cache** | `_batch_top10_holders` | ✅ 空表检查 | ✅ 日终补充 | ✅ `top10_holders` |
| **stk_holder_cache** | `_batch_stk_holder` | ✅ 空表检查 | ✅ 日终补充 | ✅ `stk_holder` |
| **finance_report_cache** | `_batch_finance_report` | ✅ 空表检查 | ✅ 日终补充 | ✅ `finance_report` |
| minute_kline_cache | `_run_minute_backfill` | ✅ 自选股检查 | ✅ 分钟回填后台 | — |
| strategy_signals | `_run_precompute` | — | ✅ 预计算后台 | — |
| factor_cache | `_precompute_preset_combos` | — | ✅ 预计算后台 | — |
| win_rate_cache | `_batch_win_rate` | — | ✅ | — |

> API 进程的 `scheduler_manager.py` 在检测到 `DATA_DAEMON_RUNNING=1` 时跳过日终同步注册。
> 所有采集操作由 data_daemon 统一管理，API 进程只读存储层。

### 🔴 全局数据体系架构红线（强制性标准）

所有系统编码必须严格遵循以下四层架构：

```
采集层 (Collection Layer) — 独立进程，系统开机自动启动
  数据源连接（mootdx TCP / Tushare HTTP / AKShare）只允许出现在采集进程
  采集频率由 data_daemon 主循环统一管理（禁止在 API 进程中触发）
  ↓ 写入
存储层 (Storage Layer) — DataManager 为唯一网关
  ECM SQLite WAL（盘后持久化）+ InMemoryStateStore（盘中实时）
  DataManager 是所有数据访问的统一入口，禁止绕过
  sync_requests 队列表（新增）：调用层→存储层的"数据缺失"信号
  ↓ 读取（写入 sync_requests）
计算层 (Computation Layer) — 数据到达时后台自动触发，非等待请求
  日终同步后自动触发：指标预计算 → 因子预计算 → 信号预计算
  盘中增量计算：分钟K线聚合
  ↓ 写入
调用层 (Call Layer) — 仅从存储层只读，前端请求时提取
  Flask REST API 只读存储层，不得直接调用外部数据源
  不得在路由中触发实时计算，不得生成 Mock 数据
  数据缺失时：写入 sync_requests 队列表 → 返回空/503 → daemon 异步补采
  ↓
前端
```

**红线规则（违反=必须修复）：**
1. **所有非采集层代码**（包括 `routes/` 和 `services/`）禁止以下操作：
   - `new TushareProvider()`、`new AkshareProvider()`、`mootdx.Quotes.factory()` 等数据源提供者实例化
   - `DataManager.sync_*()` 系列方法调用（`sync_daily_data`、`sync_stock_list`、`sync_all_daily_data` 等）
   - 任何直接调用 `pro.daily()`、`pro.moneyflow()` 等 Tushare API 的行为
2. 禁止 `use_cache=False` 参数——非采集层代码不得显式绕过存储层
3. API 路由中禁止实时计算技术指标等**数据计算**（应当在后台预计算）。**策略核算**（缠论/量价/筹码等策略分析）可按用户操作触发
4. 计算层执行时机：**数据计算**在数据到达时自动触发；**策略核算**在用户触发时执行
5. DataManager 是存储层的**唯一数据网关**，任何数据读取通过 DataManager
6. **禁止使用 Mock/随机数据作为数据降级方案**（§13规则，参见第六节）
7. 分钟K线数据必须持久化到 `minute_kline_cache` 表，禁止直调 Tushare 不落缓存
8. **数据缺失时禁止直调数据源降级**——必须走 sync_requests 异步队列机制（详见下文"数据就绪保障机制"）

**数据就绪保障机制（sync_requests 异步队列）：**

当调用层访问存储层发现数据缺失时，禁止直调采集层。改为：

```
调用层 → DataManager.request_data(task_type, ts_code?)
       → 写入 SQLite sync_requests 表 (status='pending')
       → 返回空结果 / HTTP 503
       → data_daemon 30s 轮询消费
       → 批量同步（_batch_daily 等全量API，非逐只）
       → 写入存储层 + 标记 status='done'
       → 计算层自动触发预计算
       → 调用层下次请求命中缓存
```

sync_requests 表结构（后续实现）：
```sql
CREATE TABLE sync_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,       -- 'full_daily' | 'full_moneyflow' | 'full_basic' | etc.
    ts_code TEXT,                  -- NULL 表示全市场
    status TEXT DEFAULT 'pending', -- pending | running | done | failed
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
```

**注意**：对于轻量缺失（如单日数据），可在 daemon 主循环中快速补采；
对于重量缺失（首次开机/全量建库），daemon 执行批量 API 调用后通知调用层。

**关键概念区分：**
| 维度 | 数据计算（预计算） | 策略核算（按需） |
|------|-------------------|-----------------|
| 定义 | 纯数学变换（MA/MACD/RSI/分钟聚合等） | 策略推理（缠论分析/量价识别/筹码判断等） |
| 触发 | 数据到达时后台自动触发 | 用户点击"运行分析"时触发 |
| 存储 | 写入 indicator_ma/macd/other、factor_cache | 内存缓存 AnalysisCache |
| 消费方 | K线图指标展示、策略核算的输入 | 前端五维卡片

---

## 四、关键命令

所有命令从**项目根目录**执行：

### 代码质量

```bash
make lint       # ruff check backend/app/ tests/
make typecheck  # mypy backend/app/
make test       # pytest backend/tests/ -v（--tb=short）
make check      # lint + typecheck + test
make ci         # lint + typecheck（不含测试）
```

### 开发/部署

```bash
python backend/run.py --port 5001   # 启动开发服务器
python backend/data_daemon.py       # 启动数据采集进程（data_daemon 模式）
open start.command                   # macOS 一键启动
cd frontend/vue-project && npm run build  # 构建前端
make docker-up                      # Docker 部署
```

### 健康检查

```bash
curl http://localhost:5001/api/v3/health         # 综合健康
curl http://localhost:5001/api/v3/health/live    # 存活检查
curl http://localhost:5001/api/v3/health/ready   # 就绪检查
```

---

## 五、配置

`.env` 文件（复制自 `.env.example`）关键变量：

| 变量 | 说明 | 默认 |
|------|------|------|
| `LLM_PROVIDER` | AI 提供者 | `mock`（`deepseek` / `lm_studio`） |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `DEEPSEEK_MODEL` | 模型 | `deepseek-v4-flash` |
| `TUSHARE_TOKEN` | Tushare Pro Token | — |
| `DATABASE_URL` | 数据库连接 | `sqlite:///data/app.db` |
| `DATA_DIR` | 数据目录 | `./data` |
| `AUTH_TOKEN` | API 鉴权令牌（留空=不鉴权） | — |

---

## 六、重要约束

### 数据完整性（§13 规则）

**生产环境禁止使用模拟数据（Mock）作为数据源降级方案。** 允许的降级优先级：
1. **缓存数据**（ECM 最近一次成功数据，返回 `cached_at` 字段）
2. **空结构**（空列表/空对象，前端展示空状态）
3. **明确错误**（HTTP 503 + 错误信息）
4. **异步队列补采**（调用层写入 `sync_requests` → daemon 异步补 → 下次请求命中）

**禁止**：
- 随机数填充、造假走势/信号/板块数据
- **直调 TushareProvider / AkshareProvider / mootdx 作为降级方案**
- **在调用层（routes/）或服务层（services/）中使用 `use_cache=False`**
- **在非采集层代码中实例化任何数据源 Provider**

### 已知技术细节

- **run.py 启动时清除代理变量**：`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 在 `run.py` 第 8 行清除，防止 Claude Code 注入代理导致数据源请求失败。这是数据采集正常工作的前提。
- **DuckDB → SQLite WAL**：`enhanced_cache_manager.py` 已使用 `sqlite3`（WAL 模式）替代 DuckDB。代码中不应出现新的 duckdb 引用。
- **Gunicorn 当前未使用**：`gunicorn_config.py` 注释声明暂不使用（eventlet worker 被 Gunicorn 26.x 移除）。启动始终走 `run.py`（`socketio.run`）。
- **mootdx TCP**：实时行情通过通达信 TCP 协议采集（非 HTTP），不依赖 AKShare HTTP。AKShare 仅作低频补充。
- **DataManager 唯一数据网关**：`data/__init__.py` 中的 `DataManager` 是所有数据访问的唯一入口。`get_kline_data()` 方法统一支持 `D/W/M/1m/5m/15m/30m/60m` 周期。任何代码（路由/服务/策略）不得绕过 DataManager 直调数据源。
- **分钟数据持久化**：`_get_minute_data()` 必须走 ECM `minute_kline_cache` 表的 cache-on-demand 策略——首次从 mootdx 获取并缓存，后续直接命中缓存。禁止直调 Tushare/AKShare 不落缓存。
- **指标预计算**：`indicator_ma`/`indicator_macd`/`indicator_other` 宽表已有数据，`chart.py` 必须优先从宽表读取，禁止回退到实时计算。`factor_cache`(3715万行) 和 `strategy_signals` 同理。
- **前段产物缺失**：`frontend/vue-project/` 目录当前不完整（仅 `.DS_Store`），`npm run build` 前需先恢复项目文件。
- **前端产物缺失**：`frontend/vue-project/` 目录当前不完整（仅 `.DS_Store`），`npm run build` 前需先恢复项目文件。
- **sync_requests 异步队列**：当调用层（routes/）访问存储层数据缺失时，禁止直调数据源降级。必须写 `sync_requests` 表通知 daemon 异步补采。该机制是四层架构红线规则的数据就绪保障。详见 §III 红线规则 8。
- **红线违规历史记录**：全系统曾在 10 个文件（4 个 routes/ + 4 个 services/ + 2 个其他）中存在 20+ 处直调数据源/`use_cache=False`/`sync_*` 违规。详情见 `002-方案存档/284-全局数据体系违规审计与架构整改方案.md`。新代码必须通过以下合规检查：
  - `git diff` 不引入新的 `TushareProvider()`/`AkshareProvider()`/`sync_*`/`use_cache=False`
  - 数据读取必经 DataManager 只读方法（`get_*`），不走 `sync_*`

---

## 七、测试说明

- 框架：**pytest**（配置在 `pyproject.toml`）
- 测试目录：`backend/tests/`
- 测试文件：`test_*.py`（5 个文件：`test_api_health` / `test_api_routes` / `test_backtest_engine` / `test_core` / `test_services`）
- 部分测试可直接 `python backend/tests/test_xxx.py` 运行
- 测试创建 Flask app 实例（`create_app()`），无需外部服务依赖

---

## 八、目录体系

```
001-沟通记录/     # 按日期的 AI 沟通纪要，含 沟通索引.md 和 待解决事项.md
002-方案存档/     # 155+ 份编号技术方案（编号接续递增）
docs/            # 技术文档（CODE_STANDARDS.md 等）
_prototype/      # 前端原型（HTML）
_原型定稿-不可修改/  # UI 规范真理源（只读快照）
_项目运行手册.md    # 详细运维手册（覆盖架构/启动/故障排查/部署）
_工作上下文.md      # AI 会话持久化工作状态
```
