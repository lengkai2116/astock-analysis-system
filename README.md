# A 股股票分析决策支持系统

基于 Flask + Vue 的全栈量化分析平台，专注 A 股策略研究与回测验证。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Flask 3.0 + SQLAlchemy 2.0 + SocketIO |
| 数据库 | PostgreSQL 16 + Redis 7 + DuckDB |
| 数据源 | Tushare Pro |
| 前端 | Vue 2.7 + Vite 5 + Ant Design Vue 1.x |
| 图表 | klinecharts + echarts |
| AI 推理 | DeepSeek / LM Studio（可选） |

## 快速开始

### 开发环境

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN

# 2. 启动数据库
make dev-db

# 3. 启动后端（新终端）
make dev-backend

# 4. 启动前端（新终端）
make dev-frontend

# 5. 浏览器打开 http://localhost:9000
```

### Docker 部署（生产）

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN

# 2. 构建并启动
make docker-build
make docker-up

# 3. 浏览器打开 http://localhost:9000
```

## 项目结构

```
├── backend/                    # Python Flask 后端
│   ├── app/
│   │   ├── routes/            # API 路由（12 个模块）
│   │   ├── data/              # 数据层（Tushare + DuckDB + Redis）
│   │   ├── engine/            # 回测引擎 + 策略管线
│   │   ├── services/          # 业务服务
│   │   ├── factors/           # 因子系统（200+ 因子）
│   │   ├── indicators/        # 技术指标计算
│   │   └── signals/           # 信号生成
│   ├── config/                # 策略配置（YAML）
│   └── migrations/            # 数据库迁移
├── frontend/
│   └── vue-project/           # Vue 前端
│       ├── src/
│       │   ├── views/         # 8 个视图页面
│       │   ├── components/    # 组件（含 KLineChart）
│       │   ├── services/      # API 服务
│       │   └── store/         # Vuex 状态
│       ├── Dockerfile         # 前端 Docker 构建
│       └── nginx.conf         # Nginx 配置（生产）
├── docker-compose.yml         # 全量部署编排
├── Makefile                   # 快捷命令
└── data/                      # 数据缓存目录
```

## 核心功能

- **K 线图表**：日/周/月线 + 多指标叠加（MA/BOLL/MACD/RSI/KDJ）
- **指标 IDE**：可编程研究工作台
- **策略回测**：T+1/涨跌停/手续费等 A 股规则
- **AI 分析**：多角色分析师（需配置 LLM）
- **因子系统**：200+ 内置因子
- **筹码分布**：主力阶段识别（建仓/洗盘/拉升/出货）

## API 版本

所有 API 统一使用 `/api/v3/` 前缀。

```
/api/v3/health          — 健康检查
/api/v3/stocks          — 股票列表
/api/v3/chart/kline     — K 线数据
/api/v3/ai/analyze      — AI 分析
/api/v3/backtest/run    — 回测
...
```

## License

MIT
