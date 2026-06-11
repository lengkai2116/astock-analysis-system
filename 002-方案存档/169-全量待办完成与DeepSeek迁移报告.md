# 169 — 全量待办完成与 DeepSeek 模型迁移报告

> 日期: 2026-06-10  
> 关联: 待解决事项全量更新、DeepSeek v4-flash 迁移、前端依赖清理、基建补全

---

## 一、背景

`待解决事项.md`（最后更新 06-07）中列出的大量待办项在 06-08~06-09 的实际 git 提交中已被完成但未更新文档，导致状态失真。本次统一完成剩余可操作项。

## 二、已完成事项清单

### 2.1 DeepSeek API v4-flash 迁移

| 文件 | 变更 |
|------|------|
| `backend/app/config.py:16` | 默认模型 `deepseek-chat-v4` → `deepseek-chat-v4-flash` |
| `backend/app/services/deepseek_analysis_service.py:84` | 回退默认值同步 |
| `backend/app/services/weekly_report_service.py:157` | 回退默认值同步 |
| `.env` | `DEEPSEEK_MODEL=deepseek-chat-v4-flash` |
| `.env.local` | `DEEPSEEK_MODEL=deepseek-chat-v4-flash` |
| `.env.example` | `DEEPSEEK_MODEL=deepseek-chat-v4-flash` |
| `README.md` | 废弃告警 → 迁移完成声明 |

### 2.2 前端依赖清理

| 依赖 | 大小 | 状态 | 原因 |
|------|------|------|------|
| `lodash-es` | 2.6MB (disk) | ✅ 移除 | 零引用，死依赖 |
| `moment` | 58KB (min) | 保留 | Ant Design Vue 4.x 使用 |

### 2.3 基建补全

| 模块 | 新增/修改 | 说明 |
|------|----------|------|
| `backend/app/services/alert_notifier.py` | 新增 | 告警通知服务，JSONL 日志 + 预留 webhook/email |
| `backend/app/monitors/strategy_health_monitor.py` | 修改 | 集成 AlertNotifier，每次 check 分发告警 |
| `scripts/sync_stocks.py` | 新增 | 全量股票同步脚本骨架（节流+断点续传） |
| `docs/策略输出规范.md` | 新增 | 统一格式/报告模板/评分标准三合一 |

### 2.4 确认已完成的（git log 验证）

| 待办项 | 提交 | 日期 |
|--------|------|------|
| 3.1 持仓市价 | da29565 | 06-08 |
| 3.2 复盘引擎 | 361616c | 06-08 |
| 151-P1-1 分钟级数据通道 | 1c99124 | 06-07 |
| 151-P3-1 回放复盘 | 1c99124 | 06-07 |
| 151-P3-3 K线重采样 | 1c99124 | 06-07 |
| 152-Phase 3 ComboCard联调 | 1c99124 | 06-07 |
| 153-P1-2 预测校准 | 1c99124 | 06-07 |
| 153-P1-3 消息面上下文 | 1c99124 | 06-07 |
| 153-P2-2 MultiStepContext | 1c99124 | 06-07 |
| 153-P3-1 策略AI解读 | 1c99124 | 06-07 |
| 154批2-6 形态规则扩展 | 1c99124 | 06-07 |

## 三、无法完成的项及原因

| 事项 | 原因 |
|------|------|
| 6.4 Tushare 5000积分限制 | 外部资源限制，需升级 Tushare 积分 |
| 6.2 Docker 构建 | registry-1.docker.io 不可达（基础镜像拉取超时），非 pypi 问题。Dockerfile 已预置 pypi 镜像 ARG，但需用户自行解决 Docker Hub 连通性（VPN/代理/可用镜像源） |
| 6.3 ~2000只股票同步 | 需 Tushare Token + 运行同步脚本 |
| 12.3~12.4 知识库同步 | 需用户决策同步机制 |
| 136报告9个突破方向 | 需用户决策优先级 |
| 缠论级别递归(30分/60分/日线) | 长远规划，无阻塞 |
| 154批3-6 剩余规则扩展 | 低优先级，无需求驱动 |

## 四、遗留建议

1. **Docker 构建**：registry-1.docker.io 在中国大陆不可达是根因，需用户自行解决 Docker Hub 连通性（VPN / 代理 / 可用镜像源）。Dockerfile 已预置 `PIP_INDEX_URL` 构建参数，当 Docker Hub 能连通时一条命令就能完成构建。
2. **全量股票同步**：`python scripts/sync_stocks.py --resume` 在有 Tushare Token 时可直接运行。
3. **DeepSeek 生产切换**：已切换 `LLM_PROVIDER=deepseek`（`.env` 中），AI 功能将调用真实接口。
4. **告警渠道扩展**：`alert_notifier.py` 中预留的 `_dispatch_webhook` 可对接企业微信/Slack。

---

## 五、文件变更清单

```
M  .env
M  .env.example
M  .env.local
M  README.md
M  backend/app/config.py
M  backend/app/services/deepseek_analysis_service.py
M  backend/app/services/weekly_report_service.py
M  backend/app/monitors/strategy_health_monitor.py
M  frontend/vue-project/package.json
A  backend/app/services/alert_notifier.py
A  scripts/sync_stocks.py
A  docs/策略输出规范.md
A  001-沟通记录/26-06-10沟通纪要.md
A  002-方案存档/169-全量待办完成与DeepSeek迁移报告.md
```
