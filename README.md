# A股股票分析决策支持系统

全栈量化分析平台，专注 A 股策略研究、AI 驱动分析与回测验证。

---

## 目录

1. [项目概览](#项目概览)
2. [技术栈](#技术栈)
3. [项目结构](#项目结构)
4. [核心功能](#核心功能)
5. [快速开始](#快速开始)
6. [Docker 部署](#docker-部署)
7. [文档体系](#文档体系)
8. [Git 工作流](#git-工作流)
9. [待推进事项](#待推进事项)

---

## 项目概览

本系统是一个面向 A 股的个人量化投研平台，覆盖从数据采集、策略研究、信号生成到回测验证的完整闭环。

- **数据层**：Tushare Pro（主源）+ AKShare（备用）+ 招商证券 QMT（实时行情），通过 DuckDB 本地缓存加速
- **策略引擎**：基于 QuantConnect LEAN 架构理念，构建了多层抽象的策略框架（Universe → Alpha → Portfolio → Risk → Execution）
- **核心策略**：量价形态策略（17+ 规则）、筹码分布主力追踪、缠论体系（笔-段-中枢-买卖点）、达尔文进化筛选
- **AI 分析**：DeepSeek 驱动，支持结构化 JSON 输出、策略评分、信号总线广播
- **前端**：Vue 3 + Ant Design Vue 4，包含 Dashboard、选股器、K线图表、指标IDE、账户管理、研究报告等模块

---

## 技术栈

| 层级 | 技术 | 备注 |
|------|------|------|
| **后端** | Flask 3.0 + SQLAlchemy 2.0 + Flask-SocketIO | RESTful API + WebSocket |
| **数据库** | PostgreSQL 16 / Redis 7 / DuckDB | 主库 / 缓存 / OLAP 本地缓存 |
| **数据源** | Tushare Pro / AKShare / QMT | 日线/分钟线/实时行情 |
| **AI** | DeepSeek API / LM Studio | 策略分析、结构化解码 |
| **前端** | Vue 3 + Vite 5 + Ant Design Vue 4.x | SPA |
| **图表** | klinecharts + echarts | K线图、指标可视化 |
| **部署** | Docker Compose / Nginx / Gunicorn | 多阶段构建约 50MB |

---

## 项目结构

```
A股股票分析系统/
├── backend/                    # Flask 后端
│   ├── app/
│   │   ├── __init__.py         # Flask 应用工厂
│   │   ├── config.py           # 策略配置
│   │   ├── data/               # 数据层
│   │   │   ├── data_source_manager.py  # 多源数据路由管理器
│   │   │   ├── cache_manager.py       # DuckDB 缓存
│   │   │   ├── enhanced_cache_manager.py
│   │   │   ├── chip_distribution_service.py  # 筹码分布
│   │   │   ├── chip_indicators.py
│   │   │   ├── factor_precompute.py
│   │   │   ├── tushare_provider.py
│   │   │   ├── akshare_provider.py
│   │   │   ├── qmt_provider.py
│   │   │   └── redis_cache_manager.py
│   │   ├── engine/             # 策略引擎（LEAN 架构）
│   │   │   ├── pipeline.py     # 策略流水线基类
│   │   │   ├── backtest.py     # 回测引擎 v1
│   │   │   ├── backtest_v2.py  # 回测引擎 v2（AShareBacktestEngine）
│   │   │   ├── chip_strategy_impl.py
│   │   │   ├── framework/      # 框架核心
│   │   │   │   ├── __init__.py     # ABC 抽象层
│   │   │   │   ├── volume_price_strategy.py  # 量价策略（1488行，17种形态）
│   │   │   │   ├── chanlun_strategy.py       # 缠论策略（1765行）
│   │   │   │   ├── chip_strategy.py          # 筹码策略
│   │   │   │   ├── chip_pre_filter.py        # 预筛选过滤层
│   │   │   │   ├── chip_position_manager.py
│   │   │   │   ├── chip_risk_executor.py
│   │   │   │   ├── screener.py               # 选股器
│   │   │   │   ├── confirm_layer.py
│   │   │   │   ├── optimizer.py
│   │   │   │   ├── kline_pattern.py
│   │   │   │   └── backtest_evidence.py
│   │   │   └── patterns/       # 形态适配器
│   │   │       ├── registry.py
│   │   │       ├── tracker.py
│   │   │       └── adapters/
│   │   ├── services/           # 服务层
│   │   │   ├── deepseek_analysis_service.py   # DeepSeek AI 分析
│   │   │   ├── ai_context_builder.py          # 上下文注入 + 结构化解码
│   │   │   ├── combo_engine.py                # 策略组合评分
│   │   │   ├── resonance_service.py           # 多策略共振检测
│   │   │   ├── signal_computation_service.py
│   │   │   ├── signal_match_service.py
│   │   │   ├── market_service.py
│   │   │   ├── account_service.py
│   │   │   ├── stock_search_service.py
│   │   │   ├── strategy_output_service.py
│   │   │   ├── strategy_template_service.py
│   │   │   ├── benchmark_service.py
│   │   │   ├── backtest_evidence_service.py
│   │   │   ├── review_engine.py
│   │   │   ├── research_pipeline.py
│   │   │   ├── report_generator.py
│   │   │   ├── weekly_report_service.py
│   │   │   ├── indicator_contract.py
│   │   │   ├── indicator_quality.py
│   │   │   ├── indicator_sandbox.py
│   │   │   └── init_system_templates.py
│   │   ├── routes/             # API 路由（15+ 蓝图）
│   │   ├── models/             # ORM 模型
│   │   ├── signals/            # 信号系统
│   │   ├── factors/            # 因子系统
│   │   ├── evaluation/         # 评估模块
│   │   ├── monitors/           # 健康监控
│   │   ├── scheduler.py        # 定时任务调度器
│   │   └── utils/              # 工具函数
│   ├── config/                 # 配置文件
│   ├── sql/                    # SQL 初始化脚本
│   ├── migrations/             # 数据库迁移
│   └── tests/                  # 测试
├── frontend/                   # Vue 3 前端
│   ├── vue-project/
│   │   ├── src/
│   │   │   ├── views/          # 页面
│   │   │   │   ├── dashboard/          # 仪表盘
│   │   │   │   ├── watchlist/          # 自选股
│   │   │   │   ├── screener/           # 选股器
│   │   │   │   ├── ai-analysis/        # AI 智能分析
│   │   │   │   ├── backtest/           # 回测
│   │   │   │   ├── factor-manager/     # 因子管理
│   │   │   │   ├── indicator-ide/      # 指标 IDE
│   │   │   │   ├── account/            # 账户管理
│   │   │   │   ├── reports-center/     # 报告中心
│   │   │   │   └── strategy-templates/ # 策略模板
│   │   │   ├── components/     # 组件
│   │   │   ├── services/       # 前端服务层
│   │   │   ├── stores/         # Pinia 状态管理
│   │   │   ├── utils/          # 工具函数
│   │   │   └── workers/        # Web Workers
│   │   ├── package.json
│   │   └── vite.config.js
│   └── nginx/                  # Nginx 配置
├── 001-沟通记录/               # 开发沟通纪要（35+ 文件）
├── 002-方案存档/               # 方案设计文档（155 份，编号 026~155）
├── docs/                       # 技术文档
├── data/                       # 本地数据缓存
├── database/                   # 数据库相关
├── config/                     # 环境配置
├── docker-compose.yml          # Docker 编排
├── Makefile                    # 开发/部署快捷命令
├── start.command               # macOS 一键启动
└── start.bat                   # Windows 一键启动
```

---

## 核心功能

### 1. 策略引擎

- **量价形态策略**（`volume_price_strategy.py`）：17 种 OHLCV 形态规则（放量突破、天量天价、跳空高开低走、恐慌出逃、平台破位、底部放量长阳等），支持组合评分
- **缠论策略**（`chanlun_strategy.py`）：完整笔-段-中枢-买卖点体系，含特征序列、中枢演化、决策树评分
- **筹码分布策略**（`chip_strategy.py`）：基于筹码分布的主力追踪选股
- **达尔文进化筛选**（`screener.py`）：多代筛选进化优化
- **共振评分**（`resonance_service.py`）：多策略信号交叉验证评分
- **组合引擎**（`combo_engine.py`）：56 种策略模式组合

### 2. AI 分析系统

- DeepSeek API 接入，支持策略分析、股票评估、结构化 JSON 输出
- `AiContextBuilder`：多层上下文注入（市场概况 + 技术指标 + 资金流 + 新闻情绪）
- `AiStructuredParser`：JSON Schema 解码层
- `AiSignalBus`：后端 WebSocket 信号广播

### 3. 数据管道

- 多源数据路由（DataSourceManager）：Tushare Pro 主源 → AKShare 备用 → DuckDB 本地缓存
- QMT 实时行情接入
- 定时同步调度（`scheduler.py`，323 行）
- DuckDB 缓存预热、因子预计算

### 4. 回测系统

- `AShareBacktestEngine`：A 股交易规则感知（T+1、涨跌停、手续费、印花税）
- 支持多股票并行回测、盈亏概率分布分析
- 回测证据服务（`backtest_evidence_service.py`）

### 5. 前端功能

- **Dashboard**：大盘概览、热力图、市场情绪
- **选股器**：Pipeline 流程 + 筛选结果 + 信号详情 + 融合配置
- **K 线图表**：klinecharts 渲染、多指标叠加
- **指标 IDE**：基于 CodeMirror 的在线指标编写和沙箱运行
- **AI 分析**：智能问答、策略评分
- **报告中心**：研究报告生成与浏览
- **账户管理**：持仓、交易记录、复盘审查
- **因子管理**：因子配置与计算
- **数据源监控**：实时状态指示

### 6. 工程体系

- Docker Compose 一键部署（PostgreSQL + Redis + Backend + Frontend/Nginx）
- Makefile 开发快捷命令
- 代码规范文档（`docs/CODE_STANDARDS.md`）
- 方案存档追踪体系（155 份编号文档）
- 待解决事项管理（`001-沟通记录/待解决事项.md`）

---

## 快速开始

### 前置条件

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose（可选，用于数据库和部署）

### 开发环境

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN 和 DEEPSEEK_API_KEY

# 2. 启动数据库（PostgreSQL + Redis）
make dev-db

# 3. 启动后端（端口 5001）
make dev-backend

# 4. 启动前端（端口 9000，自动代理 API 到 5001）
make dev-frontend

# 5. 浏览器打开 http://localhost:9000
```

### 环境变量参考

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | AI 提供者（mock/deepseek/lm_studio） | mock |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | - |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 | https://api.deepseek.com/v1 |
| `DEEPSEEK_MODEL` | DeepSeek 模型 | deepseek-chat |
| `TUSHARE_TOKEN` | Tushare Pro Token | - |
| `DATABASE_URL` | PostgreSQL 连接串 | - |
| `SECRET_KEY` | Flask 密钥 | dev |

---

## Docker 部署

### 架构

```
User → Browser → Nginx (:9000)
                    ├── /api/* → Flask Backend (:5001)
                    ├── /socket.io/* → Socket.IO
                    ├── /assets/* → 静态文件（长期缓存）
                    └── /* → SPA (index.html)
```

### 部署命令

```bash
# 构建并启动全部服务
make docker-build
make docker-up

# 查看状态
make status

# 查看日志
make docker-logs            # 全部
make docker-logs-backend    # 仅后端
make docker-logs-frontend   # 仅前端

# 重启单个服务
make docker-restart-backend
make docker-restart-frontend

# 停止
make docker-down
```

### 服务端口

| 服务 | 端口 |
|------|------|
| Nginx (前端) | 9000 |
| Flask 后端 | 5001 |
| PostgreSQL | 5432 |
| Redis | 6379 |

---

## 文档体系

### 开发沟通记录（001-沟通记录/）

35+ 份沟通纪要，按日期编号，含待解决事项追踪和跨文件索引。

- `沟通索引.md` — 主索引文件
- `待解决事项.md` — 全量待办追踪（按优先级：🔴 🟡 🔵）
- `26-06-07沟通纪要.md` — 最新会议记录

### 方案存档（002-方案存档/）

155 份编号研究报告（026~155），涵盖：

- **架构设计**：056-阶段一需求分析、072-修订方案、094-详细设计
- **策略研究**：142-量价策略、152-观潮对标策略架构、154-50种形态规则库
- **AI 系统**：048-AI策略提取、120-AI分析板块、153-观潮对标AI能力
- **数据与缓存**：032-DuckDB、034-DuckDB缓存机制、065-缓存实施
- **前端与 UI**：054-前端UI设计、146-前端评估、147-前端优化、150-观潮对标UI
- **缠论体系**：061-缠论作图规范、115~119-缠论优化与实施
- **审计报告**：131-全项目审计、155-145~154方案实施状态审计

### 技术文档（docs/）

- `CODE_STANDARDS.md` — 代码规范与质量保障体系
- `VUE3_MIGRATION_GUIDE.md` — Vue 3 迁移指南
- `部署与启动方案优化评估.md`
- `Level2数据权限必要性评估.md`
- `筹码分布主力策略模型可行性评估.md`

---

## Git 工作流

- 主分支：`main`
- 功能分支前缀：`codex/`（如 `codex/migrate-vue3`）
- 远程仓库：`origin` → `https://github.com/lengkai2116/astock-analysis-system.git`

---

## 待推进事项

详见 `001-沟通记录/待解决事项.md`，当前各方案剩余工作：

| 编号 | 事项 | 优先级 | 说明 |
|------|------|--------|------|
| 152-Phase 3 | 前端 ComboCard / ResonanceLamp 联调 | ✅ 已实现 | ResonanceService/ComboEngine API 路由 + 前端组件联调 (indicator-ide) |
| 153-P1-2 | 预测校准系统（AiPrediction + CalibrationService） | ✅ 已实现 | CalibrationService(置信度校准/偏差检测/分组统计) + API 路由 + 定时回填 |
| 153-P1-3 | 消息面上下文（NewsProvider + Tushare news API） | ✅ 已实现 | NewsProvider(多源路由+Mock降级) + API 路由 + AiContextBuilder 集成 |
| 153-P2-2 | MultiStepContext 多步骤上下文构建 | ✅ 已实现 | MultiStepContextBuilder(5步增量构建: 技术/基本面/消息/历史/综合) |
| 153-P3-1 | 策略输出 AI 解读层 | ✅ 已实现 | StrategyAIInterpretationService(信号解读/共振解读/批量解读) + API 路由 |
| 151-P1-1 | 分钟级数据通道 | ✅ 已实现 | MinuteDataManager(Tushare/AKShare降级+DuckDB缓存) + API 路由 |
| 151-P3-1 | 回放复盘系统 | ✅ 已实现 | PlaybackService(时间轴/速度控制/事件检测/跳转) + API 路由 |
| 151-P3-3 | K 线重采样管道 | ✅ 已实现 | KlineResampler(分钟到日到周到月) + API 路由 |
| 154 批 2-6 | 形态规则扩展 | ✅ 已实现 | EnhancedPatternDetector 新增 8 条均线辅助规则(20条总计) |

> 注意：DeepSeek `deepseek-chat` 模型将于 2026/07/24 废弃，需在截止前迁移至 v4-flash 或 v4-pro。
> 
> ✅ 已完成：153-P2-1（5 角色结构化融合引擎）—— 5 个角色并行分析 + fund_manager 综合合成的全流程已在 `deepseek_analysis_service.py`（608 行）中实现。

---

*最后更新: 2026-06-07*
