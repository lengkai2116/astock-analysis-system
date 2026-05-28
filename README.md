# A股股票分析决策支持系统

基于Vue.js + Flask + PostgreSQL的A股股票分析系统。

## 技术栈

- **前端**: Vue 3 + TypeScript + Tailwind CSS
- **后端**: Flask + SQLAlchemy
- **数据库**: PostgreSQL 16 + Redis 7 + DuckDB
- **数据来源**: Tushare Pro API

## 项目进度

- ✅ **阶段一**: 需求分析与架构设计
- ✅ **阶段二**: 数据层开发
- 🔄 **阶段三**: 业务逻辑层开发（进行中）
- ⏳ **阶段四**: 策略分析模块
- ⏳ **阶段五**: 前端集成与测试

## 快速开始

### 环境要求

- Docker & Docker Compose
- Python 3.11+ (可选，用于本地开发)
- Node.js 18+ (可选，用于前端开发)

### 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，设置 Tushare Token：

```env
TUSHARE_TOKEN=your_tushare_token_here
```

### 数据同步

```bash
python sync_data.py
```

### 启动服务

```bash
docker-compose up -d
```

### 访问服务

- API: http://localhost:5000
- 健康检查: http://localhost:5000/api/v1/health
- UI原型: http://localhost:8888/ui-design.html（需单独启动HTTP服务器）

## API接口

### 阶段一/二接口（/api/v1）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/stocks` | GET | 获取股票列表 |
| `/api/v1/stocks/{ts_code}` | GET | 获取股票详情 |
| `/api/v1/stocks/{ts_code}/daily` | GET | 获取日线数据 |
| `/api/v1/stocks/sync` | POST | 同步股票列表 |
| `/api/v1/market/index` | GET | 获取指数列表 |
| `/api/v1/health` | GET | 服务健康检查 |

### 阶段三接口（/api/v3）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v3/indicators/{ts_code}` | GET | 获取技术指标 |
| `/api/v3/indicators/{ts_code}/calculate` | POST | 计算技术指标 |
| `/api/v3/signals` | GET | 获取信号列表 |
| `/api/v3/signals/generate` | POST | 生成信号 |
| `/api/v3/watchlist` | GET | 获取自选股 |
| `/api/v3/watchlist` | POST | 添加自选股 |
| `/api/v3/watchlist/{id}` | DELETE | 删除自选股 |
| `/api/v3/portfolio` | GET | 获取投资组合 |
| `/api/v3/portfolio` | POST | 创建投资组合 |
| `/api/v3/portfolio/{id}/trade` | POST | 模拟交易 |
| `/api/v3/portfolio/{id}/performance` | GET | 组合业绩 |

## 功能特性

### 已实现

- ✅ 股票数据获取与存储
- ✅ Tushare API集成
- ✅ 技术指标计算（MA、MACD、RSI、KDJ、BOLL）
- ✅ 信号生成系统
- ✅ 自选股管理
- ✅ 模拟交易
- ✅ 投资组合管理

### 技术指标支持

- **MA**: 移动平均线（MA5、MA10、MA20）
- **MACD**: 指数平滑异同移动平均线
- **RSI**: 相对强弱指标（14日）
- **KDJ**: 随机指标
- **BOLL**: 布林带（20日）
- **VOL**: 成交量指标

### 信号生成

- 单指标信号（MA、MACD、RSI、KDJ、BOLL）
- 多指标共振信号
- 置信度评估

## 项目结构

```
01-A股股票分析系统/
├── docker-compose.yml      # Docker配置
├── .env                   # 环境变量
├── sync_data.py           # 数据同步脚本
├── backend/               # 后端服务
│   ├── app/
│   │   ├── models/        # 数据模型
│   │   ├── data/          # 数据管理
│   │   ├── indicators/    # 指标计算
│   │   ├── signals/       # 信号生成
│   │   └── routes/        # API路由
│   ├── migrations/        # 数据库迁移
│   └── requirements.txt   # Python依赖
├── frontend/              # 前端项目
│   └── ui-design.html     # UI原型
├── 001-沟通记录/          # 沟通记录
└── docs/                  # 文档
```

## 开发指南

### 后端开发

```bash
cd backend
pip install -r requirements.txt
flask run
```

### 前端开发

```bash
cd frontend
npm install
npm run dev
```

## 文档

- [阶段一需求分析](../002-方案存档/056-A股股票分析系统-阶段一需求分析与架构设计.md)
- [阶段二数据层开发](../002-方案存档/057-A股股票分析系统-阶段二数据层开发计划.md)
- [阶段三开发计划](../002-方案存档/060-阶段三开发计划.md)
- [优化建议报告](../002-方案存档/059-项目优化建议报告.md)

## License

MIT License
