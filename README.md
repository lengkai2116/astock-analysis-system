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

## 部署架构

生产环境前端通过 **Nginx + Docker 镜像** 提供服务，不需要 Node.js 运行时：

```
User --> Browser --> Nginx (:9000)
                        |
                        +--> /api/*             --> Flask Backend (:5001)
                        +--> /socket.io/*       --> Socket.IO (WebSocket)
                        +--> /assets/*          --> 静态文件（长期缓存）
                        +--> /*                 --> SPA (index.html)
```

- **Nginx** 负责静态文件服务、SPA 路由回退、API 反向代理、WebSocket 代理
- **API 基地址** 默认使用相对路径（由 Nginx 代理），也可通过 `API_BASE_URL` 环境变量单独指定后端地址
- 构建产物通过多阶段 Dockerfile 压缩到约 50MB

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

# 3. 查看启动状态
make status

# 4. 浏览器打开 http://localhost:9000

# 5. 查看日志
make docker-logs            # 全部服务
make docker-logs-backend    # 仅后端
make docker-logs-frontend   # 仅前端
```

### Docker 部署详解

#### 架构说明

`docker-compose.yml` 编排了 4 个服务：

| 服务 | 镜像 | 端口 | 依赖 |
|------|------|------|------|
| `postgres` | postgres:16 | 5432 | - |
| `redis` | redis:7-alpine | 6379 | - |
| `backend` | 本地构建 | 5001 | postgres, redis |
| `frontend` | 本地构建 | 9000:80 | backend |

#### Nginx 配置关键点

前端容器内的 Nginx（[frontend/vue-project/nginx.conf](./frontend/vue-project/nginx.conf)）：

- **SPA 回退**：所有非静态文件路由都回退到 `index.html`
- **API 代理**：`/api/` 路径转发到后端容器 `http://backend:5001`
- **WebSocket**：`/socket.io/` 路径启用 `Upgrade` 头，支持实时行情推送
- **静态缓存**：`/assets/` 设置 `Cache-Control: public, immutable`，有效期 1 年
- **健康检查**：`/health` 端点用于 Docker 容器健康检测
- **Gzip**：对 JS、CSS、JSON 等启用压缩

#### 运行时环境变量

前端容器启动时，`docker-entrypoint.sh` 会检查 `API_BASE_URL` 环境变量：

- **不设置**（默认）：使用相对路径，通过 Nginx 反向代理访问后端
- **设置**：如 `API_BASE_URL=http://api.example.com`，会注入到前端 `window.__API_BASE__`
- 同一份 Docker 镜像可通过不同环境变量部署到不同后端地址

#### 独立部署前端（后端不在同一 Docker 网络时）

```bash
# 先构建镜像
make docker-build

# 单独启动前端，指定后端地址
docker run -d \
  --name astock-frontend \
  -p 9000:80 \
  -e API_BASE_URL=http://your-backend-host:5001 \
  astock-frontend
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
│       │   ├── components/    # 组件
│       │   ├── services/      # API 服务
│       │   └── store/         # Vuex 状态
│       ├── Dockerfile         # 多阶段构建（Node → Nginx）
│       ├── nginx.conf         # 生产 Nginx 配置
│       ├── docker-entrypoint.sh  # 容器入口脚本（运行时注入环境变量）
│       └── .dockerignore      # Docker 构建上下文过滤
├── docker-compose.yml         # 全量部署编排
├── Makefile                   # 快捷命令
├── 001-沟通记录/              # 项目沟通记录
├── 002-方案存档/              # 方案/报告存档
└── data/                      # 数据缓存目录
```

## 核心功能

- **K 线图表**：日/周/月线 + 多指标叠加（MA/BOLL/MACD/RSI/KDJ）
- **指标 IDE**：可编程研究工作台
- **策略回测**：T+1/涨跌停/手续费等 A 股规则
- **AI 分析**：多角色分析师（需配置 LLM）
- **因子系统**：200+ 内置因子
- **三层策略筛选**：达尔文（风险过滤）→ 筹码（主力识别）→ 策略验证（缠论+因子）
- **筹码分布**：主力阶段识别（建仓/洗盘/拉升/出货）
- **缠论分析**：分型/笔/线段/中枢/背驰/买卖点
- **信号融合**：多策略加权信号输出

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
