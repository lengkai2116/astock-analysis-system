---
title: Windows 移植部署方案
type: 方案设计
date: 2026-05-29
---

# Windows 移植部署方案

## 一、背景

本系统目前运行在 macOS 开发机上，需移植到 Windows 生产机。核心目标是：用户只需双击桌面图标即可进入系统，无需记忆命令行操作。

## 二、移植可行性评估

### 2.1 架构分析

当前系统完全基于 Docker 容器化部署，所有服务运行在 Linux 容器中：

| 组件 | 运行方式 | 跨平台性 |
|------|---------|---------|
| 后端 (Python Flask) | Docker 容器 | ✅ 完全跨平台 |
| 前端 (Nginx + 静态文件) | Docker 容器 | ✅ 完全跨平台 |
| PostgreSQL 数据库 | Docker 容器 | ✅ 完全跨平台 |
| Redis 缓存 | Docker 容器 | ✅ 完全跨平台 |
| Shell 脚本 (entrypoint) | 容器内 Alpine Linux 执行 | ✅ 不受宿主机影响 |

**结论**：Docker 架构天然跨平台，Windows 安装 Docker Desktop 后可直接运行。

### 2.2 GitHub 仓库内容核对

| 内容 | 是否在仓库中 | 备注 |
|------|-------------|------|
| 全部代码 | ✅ | `main` 分支 |
| Docker 编排 | ✅ | `docker-compose.yml` |
| 数据库建表脚本 | ✅ | `backend/migrations/init.sql` |
| Nginx 配置 | ✅ | `frontend/vue-project/nginx.conf` |
| Dockerfile | ✅ | 前后端各一份 |
| `.env` 密钥文件 | ❌ | `.gitignore` 排除，需重新创建 |
| PostgreSQL 数据卷 | ❌ | Docker volume，跨机器不携带 |
| DuckDB 缓存文件 | ❌ | `data/duckdb/` 在 `.gitignore` 中 |

### 2.3 无法通过仓库携带的内容

- **`.env` 文件**：需在 Windows 上重新创建（含 `DEEPSEEK_API_KEY`）
- **PostgreSQL 数据库数据**：5524 只股票、611 万条日线记录需重新同步
- **Docker 容器/镜像**：需在 Windows 上重新构建

## 三、Windows 迁移步骤

### 3.1 前置条件

- Windows 10/11 专业版（推荐）
- Docker Desktop for Windows（已安装并启动）
- Git for Windows

### 3.2 部署步骤

```bash
# 1. 克隆代码
git clone https://github.com/lengkai2116/astock-analysis-system.git
cd astock-analysis-system

# 2. 创建环境变量文件
echo DEEPSEEK_API_KEY=sk-你的key > .env

# 3. 构建并启动
docker compose up -d --build

# 4. 同步历史数据（可选，首次部署后执行一次）
curl -X POST http://localhost:5001/api/cache/sync
```

### 3.3 创建桌面快捷方式

项目根目录下的 `start.bat` 文件支持"双击即用"：

- **首次双击**：构建 Docker 容器 + 自动打开浏览器
- **之后双击**：检测到服务已在运行，直接打开浏览器

创建快捷方式方法：
1. 右键 `start.bat` → "发送到" → "桌面快捷方式"
2. 可右键快捷方式 → "属性" → "更改图标" 选择一个 logo

## 四、跨平台注意事项

### 4.1 Git 行尾处理

已通过 `.gitattributes` 解决行尾问题：

```
*.sh     text eol=lf    # Shell 脚本必须 LF（Docker Alpine 要求）
*.bat    text eol=crlf  # Windows 批处理必须 CRLF
```

### 4.2 中文文件名

方案存档文件（`002-方案存档/` 目录）包含中文字符，Windows 系统需确保系统区域设置为中文，否则可能出现乱码。

### 4.3 端口占用

系统使用的端口：
- 9000 — 前端页面
- 5001 — 后端 API
- 5432 — PostgreSQL
- 6379 — Redis

Windows 上如有其他服务占用这些端口，需修改 `docker-compose.yml` 的端口映射。

## 五、数据恢复方案

### 5.1 初始数据同步

首次启动后，调用数据同步端点补全数据库：

```
POST /api/cache/sync
```

该接口会自动：
1. 同步股票列表（~5500 只）
2. 同步全部日线数据（~600 万条）
3. 写入 PostgreSQL

### 5.2 同步耗时

- 股票列表：~30 秒
- 全量日线同步：受数据源限速影响，通常 2-5 小时

建议在系统上线后后台运行，不影响前端使用。

## 六、启动/重启说明

### 启动
双击 `start.bat` 或桌面快捷方式

### 停止（如需）
```bash
docker compose down
```

### 更新代码
```bash
git pull
docker compose up -d --build
```

### 查看运行状态
```bash
docker compose ps
```

---

**文档版本**: v1.0
**编制日期**: 2026-05-29
**关联文档**:
- [128-Vue3迁移规划方案.md](./128-Vue3迁移规划方案.md)
- [126-系统数据管道整体核查与能力评估报告.md](./126-系统数据管道整体核查与能力评估报告.md)
