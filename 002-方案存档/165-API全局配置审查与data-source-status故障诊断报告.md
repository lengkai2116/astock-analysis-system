# API 全局配置审查与 `/api/v3/data-source/status` 故障诊断报告

## 一、问题现象

前端网页持续弹出错误提示：「请求失败: /api/v3/data-source/status」。该请求由 `App.vue` 在 `mounted()` 时触发，并以 30 秒间隔轮询，所以错误消息反复出现。

## 二、故障链路跟踪

### 2.1 请求从发起到失败的全流程

```
App.vue mounted()
  → _pollDataSourceStatus()
    → dataService.getDataSourceStatus()
      → _get('/api/v3/data-source/status')
        → dedupedRequest('/api/v3/data-source/status', {})
          → axios.get('/api/v3/data-source/status')      ← 使用 原始 axios，不带 Authorization
            ↓
            Flask before_request check_auth()
              → AUTH_TOKEN 已设置 (LryxVG_...)
              → /api/v3/data-source/status 不在白名单中
              → 请求头 Authorization 不存在
              → 返回 401 {"success":false,"error":"缺少认证令牌"}
            ↓
          axios 因 401 拒绝 Promise
          → dedupedRequest 抛出异常
        → _get catch: message.error('请求失败: /api/v3/data-source/status')
        → 异常继续上抛
      → getDataSourceStatus 抛出
    → _pollDataSourceStatus catch: 静默吞异常
```

### 2.2 根本原因

**根因：`dedupedRequest()` 使用原始 axios 发送请求，未携带 Bearer 认证令牌。**

系统存在两套 axios 实例：

| 实例 | 文件 | 特性 |
|---|---|---|
| `E` (带拦截器) | `src/utils/request.js` | 创建时已配置 `Authorization` 请求拦截器 + `401/403` 响应拦截器 |
| `axios` (原始) | `src/utils/requestDedupe.js` | 直接 `import axios from 'axios'`，无任何拦截器 |

- `DataService._get()` → `dedupedRequest()` → 使用 **原始 axios**
- `DataService._post()/_put()/_delete()` → 动态 `import('axios')` → 也使用 **原始 axios**
- 而 `src/utils/request.js` 导出的 `E` 实例配置了 `Authorization: Bearer <token>` 请求拦截器，但 **DataService 从未使用此实例**

## 三、系统 API 配置全面审计

### 3.1 环境变量配置

| 变量 | .env 值 | .env.local 值 | .env.example 默认 | 状态 |
|---|---|---|---|---|
| `AUTH_TOKEN` | `LryxVG_6XoO8x09QDQWU8XP5g7hylY3ATEh6vsu054M` | 未设置 | 空(不启用) | **已启用** |
| `SECRET_KEY` | `GiAEpUkodzr9M63Ao3OBHEzYQcy4u9l1UqEwjeM4e0I` | `stock_analysis_secret_key_2026` | `change-this-to...` | ✅ |
| `CORS_ORIGIN` | `http://localhost:9000` | 未设置 | `http://localhost:9000` | ✅ |
| `TUSHARE_TOKEN` | `0ef90eacb9...` | 同上 | `your-tushare-token-here` | ✅ |
| `DEEPSEEK_API_KEY` | `sk-56efa3f9...` | `sk-your-deepseek-api-key-here` | `sk-your-api-key-here` | ✅ 已设置 |
| `DATABASE_URL` | 未设置 | `sqlite:///test.db` | 未设置 | ⚠️ SQLite (测试) |
| `LLM_PROVIDER` | 未设置 | `mock` (非当前活动 .env) | `mock` | ⚠️ 仅 mock |
| `LLM_WIKI_API_TOKEN` | `8vp3lOahrm...` | 同上 | 未设置 | ✅ |

### 3.2 后端鉴权配置

| 文件 | 行号 | 内容 |
|---|---|---|
| `backend/app/__init__.py` | 74 | `whitelist = ['/api/v1/health', '/api/v3/health', '/api/auth/login']` |
| `backend/app/auth.py` | 27-31 | 同上白名单 |
| `backend/app/auth.py` | 47-73 | `@require_auth` 装饰器（未在 phase3 路由上使用） |

**发现：后端 `before_request` 硬编码白名单，`/api/v3/data-source/status` 不在其中。** 当 `AUTH_TOKEN` 启用时，所有非白名单请求均需鉴权。

### 3.3 前端鉴权链路

| 文件 | 角色 | 问题 |
|---|---|---|
| `src/utils/request.js` | 配置了 Auth 拦截器的 axios 实例 `E` | **未被 DataService 使用** |
| `src/utils/requestDedupe.js` | DataService 实际调用的去重请求工具 | **使用原始 axios，无 Token** |
| `src/services/dataService.js` | 统一数据服务层 | `_get/_post/_put/_delete` 均走原始 axios |
| `src/App.vue` | 页面根组件，轮询 `getDataSourceStatus()` | 该接口时间已启用，请求无 Auth 必然 401 |

### 3.4 其他潜在影响面

除 `/api/v3/data-source/status` 外，DataService 中所有方法均受影响，包括：

- `/api/v3/chart/kline` (K线数据)
- `/api/v3/symbols/search` (股票搜索)
- `/api/v3/watchlist` (自选股 CRUD)
- `/api/v3/sim/order` (模拟交易)
- `/api/v3/market/categories` (市场分类)
- `/api/v3/alerts` (告警)
- `/api/v3/drawings/*` (画图持久化)
- `/api/v3/watchlist/dashboard` (仪表盘自选数据)
- `/api/v3/market/overview` (市场概况)
- `/api/v3/signals/summary` (信号摘要)
- `/api/v3/ai-analysis/signals` (AI分析信号)

这些接口在 `AUTH_TOKEN` 启用时均因缺少 Token 而失败。

### 3.5 前端入口与 baseURL

`frontend/vue-project/index.html:54`: `window.__API_BASE__ = window.__API_BASE__ || '';`

两个 axios 实例均将 baseURL 设为 `''`（同源），端点无配置问题。

## 四、修复建议

### 方案 A：让 DataService 使用已配置的 axios 实例（推荐）

将 `requestDedupe.js` 中的 `import axios from 'axios'` 替换为使用 `request.js` 导出的已配置实例：

```
文件: frontend/vue-project/src/utils/requestDedupe.js
修改: import axios from '../utils/request'    ← 使用带有拦截器的实例
同时: 将各处动态 import('axios') 也统一替换为 import request from '../utils/request'
```

### 方案 B：在 `dedupedRequest` 中手动添加 Token

在 `requestDedupe.js` 的 `dedupedRequest` 函数中，在发起 axios 请求前从 `localStorage` 读取 Token 并注入 `Authorization` 头。

### 方案 C：后端白名单放行（治标不治本）

将路径加入 `backend/app/auth.py` 和 `backend/app/__init__.py` 的白名单：

```python
WHITELIST_PATHS = [
    '/api/v1/health',
    '/api/v3/health',
    '/api/v3/data-source/status',
    '/api/auth/login',
]
```

但此方案仅解决这一个端点，其他 DataService 接口仍会失败。

### 方案 D：开发环境关闭 Auth（紧急绕过）

注释 `.env` 中的 `AUTH_TOKEN` 行：

```
# AUTH_TOKEN=LryxVG_6XoO8x09QDQWU8XP5g7hylY3ATEh6vsu054M
```

后端 `before_request` 检测到 `_AUTH_TOKEN` 为空时跳过鉴权。**仅推荐作为临时措施。**

## 五、推荐修复路径

1. **立即修复：** 方案 A — 将 `requestDedupe.js` 的 axios 引用指向 `request.js` 导出的已配置实例，同时将 `dataService.js` 中 `import axios` 替换为 `import request from '../utils/request'`，消除全线 Auth 缺失问题。
2. **同步检查：** 确认后端白名单是否需要补充 `/api/v3/health` 之外的公共端点。
3. **验证：** 清除前端缓存后重启 dev server，检查 `/api/v3/data-source/status` 响应及所有 DataService 调用是否正常。

---

报告生成时间: 2026-06-09
审计范围: 前端请求链路、后端鉴权白名单、环境变量配置

---

## 六、补充发现：登录页无法正常工作

在排查 `data-source/status` 故障时，发现登录系统本身存在两个连锁问题：

### 6.1 /api/auth/status 不在白名单中

`/api/auth/status` 是登录页用来检测后端是否启用了认证、以及获取令牌预览的第一个请求。但它不在鉴权白名单中。

**后端** `backend/app/auth.py` 的 `WHITELIST_PATHS` 只有：
```python
WHITELIST_PATHS = [
    '/api/v1/health',
    '/api/v3/health',
    '/api/auth/login',
]
```

`/api/auth/status` 未包含。实测返回 401（详见本报告 6.3），导致登录页的 `created()` 在 catch 中静默失败，`authInfo.enabled` 保持默认 `false`，用户看到的提示与实际不符。

### 6.2 路由守卫未重定向到登录页

`前端 router/index.js` 的 `beforeEach` 守卫在发现 localStorage 无 token 时，仅调用 `next()` 放行，而非重定向到 `/login`。结果用户直接进入主页面，面对因缺少认证而不断失败的 API 请求，却无从知道需要先登录。

### 6.3 修复清单

| 修复项 | 文件 | 说明 |
|---|---|---|
| 白名单补充 | `backend/app/__init__.py` line 74 | 在 before_request 的 whitelist 中加入 `'/api/auth/status'` |
| 白名单补充 | `backend/app/auth.py` line 28 | 在 `WHITELIST_PATHS` 中加入 `'/api/auth/status'` |
| 路由守卫修复 | `frontend/vue-project/src/router/index.js` line 98 | 将 `return next()` 改为 `return next('/login')`，无 token 时自动跳转登录页 |
| axios 实例统一 | `frontend/vue-project/src/utils/requestDedupe.js` | `import axios from 'axios'` → `import request from './request'` |
| axios 实例统一 | `frontend/vue-project/src/services/dataService.js` | 移除 3 处动态 `import('axios')`，改用已配置的 `request` 实例 |
| axios 实例统一 | `frontend/vue-project/src/services/strategyService.js` | 同上 |
| axios 实例统一 | `frontend/vue-project/src/services/strategyTemplateService.js` | 同上 |

## 七、当前 Token 信息

- **当前 Token**: `LryxVG_6XoO8x09QDQWU8XP5g7hylY3ATEh6vsu054M`
- **来源**: `.env` 文件中 `AUTH_TOKEN` 变量，由 2026-06-07 的 commit `7380f83`（部署前安全加固）引入
- **修改方式**: 编辑 `.env` 文件中的 `AUTH_TOKEN=新值`
- **生成新 Token**: 运行
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
  将输出复制替换 `.env` 中的值，重启后端即可生效。

## 八、登录/认证操作指引

| 场景 | 操作 |
|---|---|
| 已启用 Auth（当前） | 打开系统 → 自动跳转登录页 → 点击"查看令牌内容" → 复制令牌 → 输入登录 |
| 想关闭 Auth | 删除或注释 `.env` 中的 `AUTH_TOKEN` 行 → 重启后端 → 登录页会自动登录并跳转首页 |
| 想修改 Token | 修改 `.env` 中 `AUTH_TOKEN` 的值 → 重启后端 → 用新 Token 登录 |

> 注意：登录页中"查看令牌内容"仅显示 Token 前 8 位作为预览。如需完整 Token，请在 `.env` 文件中查看 `AUTH_TOKEN` 变量的值。
