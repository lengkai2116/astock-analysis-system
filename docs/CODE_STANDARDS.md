# 代码规范与质量保障体系

## 1. 开发语言与环境

- Python 3.11+（后端）
- Node.js 18+（前端）
- Vue 3 + Vite 5（前端框架）

## 2. Python 代码规范（后端）

### 格式标准
- 缩进：4 空格
- 行宽：100 字符
- 引号：单引号优先

### 工具链
```bash
# Lint 检查
ruff check app/ tests/

# 类型检查
mypy app/

# 格式化
ruff format app/ tests/
```

### 命名约定
- 类名：`PascalCase`
- 函数/方法：`snake_case`
- 常量：`UPPER_SNAKE_CASE`
- 模块：`snake_case.py`

## 3. JavaScript/Vue 规范（前端）

- 使用 ESLint 进行代码检查
- 组件名：PascalCase
- 文件名：kebab-case（组件目录）或 PascalCase（单个文件）
- Props：camelCase 定义，kebab-case 在模板中使用

## 4. API 规范

- RESTful 风格，统一前缀 `/api/v3/`
- 响应格式：
  ```json
  { "success": true, "data": { ... } }
  { "success": false, "error": "错误信息" }
  ```
- WebSocket 路径：`/socket.io/`

## 5. Git 规范

- 主分支：`main`
- 功能分支：`codex/<feature-name>`
- 提交信息：简短描述修改内容（中文）

## 6. 测试要求

- 后端核心模块（技术指标、信号生成）必须有单元测试覆盖
- API 路由新增时同步添加集成测试
- 回测引擎变更需验证历史结果一致性

## 7. 文档要求

- API 接口需在对应路由文件中注明参数和返回值
- 功能模块需在模块头部注明用途和依赖
- 方案文档编号归档至 `002-方案存档/`
