---
title: Windows 软件化迁移完整方案
type: 方案设计
date: 2026-06-10
version: 2.0
tags: [Windows迁移, 安装程序, 无Docker, CI/CD]
supersedes: ~（129 已删除）
---

# Windows 软件化迁移完整方案

> 本方案是 129 号文档的全面升级。129 原方案基于 Docker Desktop 部署，经实际验证 Docker Hub 在中国大陆不可达。本方案采用 **无 Docker 裸跑 + Inno Setup 安装程序** 策略，实现真正的 Windows 软件化交付。

---

## 一、方案概述

### 1.1 目标

用户从 GitHub Releases 下载一个 `.exe` 安装文件，双击安装后，桌面出现图标，双击图标直达系统（`http://localhost:5001`）。整个过程不需要接触命令行、不需要安装 Python/Node.js/Docker。

### 1.2 核心策略

| 层面 | 策略 | 说明 |
|------|------|------|
| **运行模式** | 无 Docker 裸跑 | Flask 直接运行，SQLite + DuckDB 替代 PostgreSQL + Redis |
| **Python 分发** | 嵌入式 Python | 微软官方 nuget 包，~30MB，免安装免管理员 |
| **前端交付** | 预构建 dist | GitHub Actions 上 `npm run build`，不依赖用户环境 |
| **分发渠道** | GitHub Releases | CI 自动构建 → exe 上传 → 用户下载 |
| **安装体验** | Inno Setup | 标准 Windows 安装程序，可选目录、开始菜单、桌面图标 |
| **启动体验** | VBScript 静默启动 | 无黑框框，双击桌面图标直接弹浏览器 |

---

## 二、系统架构（去 Docker 后）

### 2.1 架构对比

```
旧架构（Docker）:
  macOS/Windows
    ├── Docker Desktop
    │   ├── Nginx 容器 (:9000) → 托管前端 + 反向代理到后端
    │   ├── Flask 容器 (:5001) → Gunicorn + eventlet
    │   ├── PostgreSQL 容器 (:5432)
    │   └── Redis 容器 (:6379)
    └── Vite dev server (开发时额外启动)

新架构（无 Docker）:
  Windows 10/11
    ├── Python 3.11 (嵌入式)
    │   └── Flask (:5001) → 托管前端 SPA + API + WebSocket
    ├── SQLite → backend/test.db（代替 PostgreSQL）
    └── DuckDB → data/duckdb/stock_cache.db（代替 Redis）
```

### 2.2 组件职责变化

| 组件 | 原来（Docker） | 现在（裸跑） | 变更 |
|------|--------------|------------|------|
| 前端服务 | Nginx 容器 | **Flask 内置 `send_from_directory`** | ✅ 已实现（`__init__.py`） |
| 后端服务 | Gunicorn + eventlet | **`python run.py` (Werkzeug)** | ✅ 已实现 |
| 数据库 | PostgreSQL 容器 | **SQLite (`test.db`)** | ✅ 已实现（默认配置） |
| 缓存 | Redis 容器 | **DuckDB 文件** | ✅ 已实现（CacheManager） |
| WebSocket | Nginx → Gunicorn → SocketIO | **Flask-SocketIO 直连** | ✅ 原生支持 |
| 日志 | Docker log driver | **TimedRotatingFileHandler** | ✅ 已有 |
| 构建 | Dockerfile 多阶段 | **GitHub Actions runner** | 新加 |

### 2.3 不再需要的文件/配置

| 文件 | 用途 | 处理 |
|------|------|------|
| `backend/Dockerfile` | Docker 镜像构建 | 保留（云部署备选），不删除 |
| `frontend/vue-project/Dockerfile` | 前端 Nginx 镜像 | 保留 |
| `frontend/vue-project/nginx.conf` | Nginx 反向代理配置 | 保留 |
| `frontend/vue-project/docker-entrypoint.sh` | 容器启动注入 | 保留 |
| `.dockerignore` | Docker 构建排除 | 保留 |
| `docker-compose.yml` | 服务编排 | 保留（PostgreSQL/Redis 本地开发可用） |
| `frontend/vue-project/Dockerfile` | 前端构建 | 保留 |
| `scripts/crontab.txt` | Docker 内定时任务 | 保留 |

> Docker 相关文件全部保留不移除。Windows 安装程序不使用它们，但云服务器部署时仍可复用。

---

## 三、GitHub Release 工作流

### 3.1 构建流程

```
GitHub Actions: Windows Server 2022 runner
  
  步骤 1: 检出代码
    git checkout main
  
  步骤 2: 安装 Node.js + 构建前端
    npm ci
    npm run build → frontend/vue-project/dist/
  
  步骤 3: 下载嵌入式 Python
    curl -LO https://www.nuget.org/api/v2/package/python/3.11.9
    → python-3.11.9-embed.zip（~30MB）
    → 解压到 installer/python/
  
  步骤 4: 安装 Python 依赖
    installer/python/python.exe -m pip install -r backend/requirements.txt
    → 目标: installer/python/Lib/site-packages/
  
  步骤 5: 整理安装目录
    installer/staging/
    ├── backend/                    ← 从项目复制
    ├── frontend/vue-project/dist/  ← 步骤 2 产物
    ├── data/                       ← 空目录（首次启动自动初始化）
    ├── python/                     ← 步骤 3+4 产物
    ├── start-backend.vbs           ← 静默启动脚本
    ├── stop-backend.vbs            ← 停止脚本
    └── .env.example                ← 模板（安装时引导填写）
  
  步骤 6: Inno Setup 打包
    ISCC installer/windows.iss
    → Output/astock-analysis-v1.0.0.exe
  
  步骤 7: 上传到 Release
    gh release upload v1.0.0 astock-analysis-v1.0.0.exe
```

### 3.2 GitHub Releases 版本约定

| 版本号 | 说明 |
|--------|------|
| `v1.0.0` | 首次正式发布 |
| `v1.1.0` | 功能更新 |
| `v2.0.0` | 重大架构更新 |
| `nightly` | 每日构建（可选） |

**Release Note 模板：**
```
## A股分析系统 v1.0.0

### 下载
⬇️ astock-analysis-v1.0.0.exe（~80MB）

### 安装
1. 下载 exe
2. 双击安装（可选择安装目录）
3. 安装完成后桌面出现图标
4. 双击图标即可使用

### 更新内容
- ...

### 系统要求
- Windows 10/11（64 位）
- 无需 Python、Node.js、Docker
```

---

## 四、Windows 安装程序方案（Inno Setup）

### 4.1 安装脚本设计

```pascal
; installer/windows.iss — Inno Setup 脚本

[Setup]
AppName=A股股票分析系统
AppVersion=1.0.0
DefaultDirName={autopf}\A股分析系统
DefaultGroupName=A股分析系统
UninstallDisplayIcon={app}\assets\icon.ico
PrivilegesRequired=lowest          ; 无需管理员权限
OutputDir=..\dist
OutputBaseFilename=astock-analysis-v1.0.0
SolidCompression=yes

[Files]
Source: "staging\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{commondesktop}\A股分析系统"; Filename: "{app}\start-backend.vbs"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\A股分析系统"; Filename: "{app}\start-backend.vbs"
Name: "{group}\停止系统"; Filename: "{app}\stop-backend.vbs"
Name: "{group}\卸载"; Filename: "{uninstallexe}"

[Run]
; 安装完成后立即启动
Filename: "{app}\start-backend.vbs"; Description: "启动 A股分析系统"; Flags: postinstall nowait skipifsilent
```

### 4.2 VBScript 静默启动脚本

```vbscript
' start-backend.vbs — 无窗口启动后端
Set WshShell = CreateObject("WScript.Shell")
appPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' 设置环境变量
WshShell.Environment("PROCESS")("DATA_DIR") = appPath & "\data"
WshShell.Environment("PROCESS")("FRONTEND_DIST") = appPath & "\frontend\vue-project\dist"

' 静默启动后端（0 = 隐藏窗口）
WshShell.Run """" & appPath & "\python\python.exe"" """ & appPath & "\backend\run.py"" --port 5001", 0, False

' 等待服务就绪后打开浏览器
WScript.Sleep 5000
For i = 1 To 15
    On Error Resume Next
    Dim http: Set http = CreateObject("MSXML2.ServerXMLHTTP")
    http.open "GET", "http://localhost:5001/api/v3/health", False
    http.send
    If http.Status = 200 Then
        WshShell.Run "http://localhost:5001"
        WScript.Quit
    End If
    WScript.Sleep 2000
Next
```

### 4.3 安装目录结构

```
用户自定义目录（默认为 C:\Program Files\A股分析系统\）
├── backend/
│   ├── app/                  ← 后端代码
│   ├── run.py                ← 入口
│   └── requirements.txt
├── frontend/vue-project/dist/
│   ├── index.html            ← 前端入口
│   └── assets/               ← 静态资源
├── python/
│   ├── python.exe            ← 嵌入式 Python
│   └── Lib/site-packages/    ← 全部依赖
├── data/                     ← 运行时数据（空，首次启动自动创建）
├── assets/
│   └── icon.ico              ← 应用图标
├── .env.example              ← 环境变量模板
├── start-backend.vbs         ← 启动脚本（桌面快捷方式目标）
└── stop-backend.vbs          ← 停止脚本
```

### 4.4 首次启动流程

```
用户双击桌面图标
  → start-backend.vbs 执行
  → 检测 .env 是否存在
    ├── 不存在：复制 .env.example → .env，弹出记事本让用户填写 API Key
    └── 存在：跳过
  → 检测 data/ 目录是否存在，不存在则创建
  → python run.py --port 5001（无窗口模式）
  → 循环检测 localhost:5001/health
  → 就绪后自动打开浏览器 http://localhost:5001
  → 用户直接使用系统

用户想停止时
  → 双击桌面快捷方式组中的"停止系统"
  → 或 开始菜单 → A股分析系统 → 停止系统
  → vbs 脚本发送 Ctrl+C 或 taskkill 结束进程
```

---

## 五、系统代码变更清单

已完成变更：

| 文件 | 变更内容 | 状态 |
|------|---------|------|
| `backend/app/__init__.py` | 新增前端 SPA 静态文件托管（`send_from_directory`） | ✅ 已完成 |
| `backend/app/__init__.py` | SPA 回退路由（非 API 路由 → `index.html`） | ✅ 已完成 |
| `backend/app/config.py` | `DATA_DIR` 默认值 `/data` → `data` | ✅ 已完成 |
| `.env.example` | 补充 `DATABASE_URL`、`DATA_DIR`、`FLASK_APP`、`FLASK_ENV` | ✅ 已完成 |
| `start.bat` | Docker 模式 → 裸跑模式，含虚拟环境/前端构建/服务启动 | ✅ 已完成 |
| `start.command` | Docker 模式 → 裸跑模式 | ✅ 已完成 |
| `start.sh` | Docker 模式 → 裸跑模式 | ✅ 已完成 |
| `stop.sh` | 新增 | ✅ 已完成 |
| `stop.bat` | 新增 | ✅ 已完成 |
| `scripts/backup.sh` | PostgreSQL → SQLite + DuckDB | ✅ 已完成 |
| `scripts/sync_stocks.py` | Tushare 全量同步脚本（断点续传、频率控制） | ✅ 已完成 |
| `backend/app/services/alert_notifier.py` | 告警通知服务 | ✅ 已完成 |

待完成变更（安装程序构建）：

| 文件 | 变更内容 | 状态 |
|------|---------|------|
| `installer/windows.iss` | Inno Setup 安装脚本 | 🔲 待创建 |
| `installer/start-backend.vbs` | 静默启动脚本 | 🔲 待创建 |
| `installer/stop-backend.vbs` | 停止脚本 | 🔲 待创建 |
| `installer/icon.ico` | 应用图标 | 🔲 待创建 |
| `.github/workflows/build-windows.yml` | CI 构建流水线 | 🔲 待创建 |
| `.gitignore` | 可能需要调整 dist/ 策略 | 🔲 待评估 |

---

## 六、Windows 设备迁移完整步骤

### 6.1 一次安装（首次迁移）

```mermaid
flowchart LR
    A[macOS 开发机] -->|git push| B[GitHub main 分支]
    B -->|GitHub Actions| C[自动构建 exe]
    C -->|上传到 Releases| D[astock-v1.0.0.exe]
    D -->|用户下载| E[Windows 机器]
    E -->|双击安装| F[自定义安装目录]
    F -->|安装完成| G[桌面出现图标]
    G -->|双击图标| H[浏览器自动打开]
```

### 6.2 日常更新

```mermaid
flowchart LR
    A[macOS: 开发新功能] -->|git push| B[GitHub main]
    B -->|Actions 自动构建| C[新 exe]
    C -->|GitHub Releases| D[用户下载新版本]
    D -->|覆盖安装| E[Windows 升级完成]
    E -->|数据不丢失| F[data/ 目录保留]
```

### 6.3 数据迁移注意事项

| 数据 | 能否通过 GitHub 携带 | 替代方案 |
|------|---------------------|---------|
| `.env` API Key | ❌ .gitignore 排除 | 安装程序自动弹出模板让用户填写 |
| SQLite 数据库 | ❌ .gitignore 排除 | 首次启动自动创建空库 |
| DuckDB 缓存 | ❌ .gitignore 排除 | 运行 `sync_stocks.py` 从 Tushare 同步 |
| 前端构建产物 | ❌ .gitignore 排除 | GitHub Actions 上预构建，打包进 exe |
| Python 环境 | ❌ 非仓库内容 | 嵌入式 Python 打包进 exe |

---

## 七、剩余工作项与优先级

| # | 工作项 | 优先级 | 预估工时 | 说明 |
|---|--------|--------|---------|------|
| 1 | 创建 `installer/windows.iss` | P0 | 2h | Inno Setup 安装脚本，含目录选择、开始菜单、桌面图标 |
| 2 | 创建 `installer/start-backend.vbs` | P0 | 1h | 无窗口启动脚本，含环境变量设置、服务等待、浏览器打开 |
| 3 | 创建 `installer/stop-backend.vbs` | P0 | 0.5h | 停止脚本 |
| 4 | 准备 `installer/icon.ico` | P1 | 0.5h | 应用图标（可从现有素材生成） |
| 5 | 创建 `.github/workflows/build-windows.yml` | P0 | 3h | CI 流水线：安装依赖 → 构建前端 → 下载 Python → 打包 exe → 上传 Release |
| 6 | 测试：Windows 10/11 真实机器安装验证 | P0 | 2h | 安装、启动、停止、卸载全流程 |
| 7 | 测试：空机首次启动（无 Python/Node） | P0 | 0.5h | 确认嵌入式 Python 正常工作 |
| 8 | 测试：已有数据升级安装 | P1 | 1h | 覆盖安装后 data/ 数据不丢失 |
| 9 | 编写 Release Note 模板 | P1 | 0.5h | GitHub Release 说明 |
| 10 | 更新 README.md 安装说明 | P2 | 0.5h | 添加 Windows 安装方式 |

### 7.1 工作量估算

| 阶段 | 工时 | 说明 |
|------|------|------|
| P0（核心） | 6.5h | 安装脚本 + CI 流水线 + VBS 启动脚本 |
| P1（完善） | 2h | 图标、测试验证、Release Note |
| P2（文档） | 0.5h | README 更新 |
| **合计** | **9h** | 约 1-2 个工作日 |

---

## 八、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 嵌入式 Python 缺少某些 C 扩展 | 低 | 高 | 提前在 CI runner 上测试全部 import |
| Inno Setup 打包文件超过 2GB 限制 | 极低 | 中 | 安装包约 80MB，远低于限制 |
| Windows Defender 误报 vbs 脚本 | 中 | 低 | vbs 仅做进程启动和 HTTP 检测，无网络/文件敏感操作 |
| 用户自定义目录含中文/空格 | 中 | 中 | Inno Setup 默认支持 Unicode 路径，vbs 中 `GetParentFolderName` 处理空格 |
| Python pip 依赖在新版 Python 不兼容 | 低 | 高 | 固定 Python 3.11 版本，在 CI 中锁定 |
| Tushare API 在 Windows 上行为差异 | 极低 | 低 | Tushare 是纯 HTTP API，无平台差异 |

---

## 九、与旧版 129 方案的关系

| 维度 | 129 号方案（原版） | 170 号方案（本版） |
|------|-------------------|-------------------|
| 部署方式 | Docker Desktop | 裸跑 + 嵌入式 Python |
| 安装体验 | clone + 双击 start.bat | 双击 exe 安装程序 |
| Python | 用户自行安装 | 嵌入式 Python 打包 |
| Node.js | 需要 | 不需要（前端预构建） |
| 数据库 | PostgreSQL（需 Docker） | SQLite（零配置） |
| 分发渠道 | git clone | GitHub Releases |
| 桌面体验 | 黑框框窗口 | 静默启动，无窗口 |
| 更新方式 | git pull | 下载新 exe 覆盖安装 |
| 维护成本 | 中（需解决 Docker Hub） | 低（全自动 CI） |

---

## 十、附录

### 10.1 所需工具

| 工具 | 用途 | 获取方式 |
|------|------|---------|
| Inno Setup 6 | 安装程序制作 | `https://jrsoftware.org/isinfo.php`（免费） |
| GitHub Actions | CI 构建 | GitHub 内置 |
| 嵌入式 Python 3.11 | 便携 Python 运行时 | `https://www.nuget.org/api/v2/package/python/3.11.9` |

### 10.2 参考文档

- [129-Windows移植部署方案.md](./129-Windows移植部署方案.md) — 原 Docker 方案（已废弃）
- [169-全量待办完成与DeepSeek迁移报告.md](./169-全量待办完成与DeepSeek迁移报告.md) — 前置工作
- [Inno Setup 文档](https://jrsoftware.org/ishelp/)
- [NuGet Python 嵌入式包](https://www.nuget.org/packages/python/)

---

**文档版本**: v2.0
**编制日期**: 2026-06-10
**关联文档**:
- [129-Windows移植部署方案.md](./129-Windows移植部署方案.md)
- [169-全量待办完成与DeepSeek迁移报告.md](./169-全量待办完成与DeepSeek迁移报告.md)
