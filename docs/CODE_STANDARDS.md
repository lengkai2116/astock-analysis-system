# 代码规范与质量保障体系

## 文档版本
- 版本: 1.0
- 创建日期: 2026-05-24
- 维护者: 开发团队

## 目录

1. [前端代码规范](#前端代码规范)
2. [后端代码规范](#后端代码规范)
3. [Git 工作流程](#git-工作流程)
4. [代码审查流程](#代码审查流程)
5. [测试指南](#测试指南)
6. [性能优化指南](#性能优化指南)

---

## 前端代码规范

### JavaScript / TypeScript

#### 1.1 命名约定
```javascript
// 类名 - PascalCase
class UserService { }

// 函数名 - camelCase
function getUserData() { }

// 常量 - UPPER_SNAKE_CASE
const MAX_RETRY_COUNT = 3

// 私有变量 - 下划线前缀 (Vue 2)
const _internalState = {}

// 布尔值 - is/has/can 前缀
const isLoading = true
const hasPermission = true
const canEdit = true
```

#### 1.2 注释规范
```javascript
/**
 * 获取用户数据
 * @param {number} userId - 用户ID
 * @param {Object} options - 配置选项
 * @returns {Promise<Object>} 用户数据
 */
async function getUserData(userId, options = {}) {
  // 实现
}
```

#### 1.3 函数长度
- 单个函数不超过 50 行
- 复杂逻辑拆分为多个小函数
- 每个函数只做一件事

### Vue 组件规范

#### 2.1 组件命名
```vue
<!-- 组件文件 - PascalCase -->
<!-- UserProfile.vue -->

<!-- 组件使用 - PascalCase -->
<template>
  <UserProfile />
</template>

<script>
export default {
  name: 'UserProfile'
}
</script>
```

#### 2.2 组件结构
```vue
<template>
  <!-- 模板 -->
</template>

<script>
export default {
  name: 'ComponentName',
  
  // 1. 继承
  extends: BaseComponent,
  
  // 2. 注入
  inject: ['store'],
  
  // 3. 组件属性
  props: {
    title: {
      type: String,
      required: true
    }
  },
  
  // 4. 数据
  data() {
    return {}
  },
  
  // 5. 计算属性
  computed: {},
  
  // 6. 方法
  methods: {},
  
  // 7. 生命周期钩子
  created() {},
  mounted() {},
  
  // 8. 侦听器
  watch: {}
}
</script>

<style scoped>
/* 样式 */
</style>
```

#### 2.3 Props 定义
```javascript
// 好
props: {
  status: {
    type: String,
    required: true,
    validator: (value) => ['pending', 'active', 'completed'].includes(value)
  },
  count: {
    type: Number,
    default: 0
  }
}

// 避免
props: ['status', 'count']
```

### CSS 规范

#### 3.1 命名约定
```css
/* 类名 - BEM 风格 */
.block {}
.block__element {}
.block--modifier {}

/* 组件内样式 - 前缀 */
.user-profile__header {}
.user-profile__content {}
```

#### 3.2 颜色变量
```css
:root {
  --color-primary: #3b82f6;
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-error: #ef4444;
  --text-primary: #f1f5f9;
  --text-secondary: #cbd5e1;
  --bg-primary: #0a1628;
  --bg-secondary: #1e293b;
}
```

### ESLint 配置
```json
{
  "rules": {
    "semi": ["error", "never"],
    "quotes": ["error", "single"],
    "indent": ["error", 2],
    "vue/no-unused-vars": "error",
    "vue/attributes-order": "error"
  }
}
```

---

## 后端代码规范

### Python 代码规范

#### 1.1 命名约定
```python
# 类名 - CapWords
class UserService:
    pass

# 函数名 - snake_case
def get_user_data(user_id):
    pass

# 常量 - UPPER_SNAKE_CASE
MAX_RETRY_COUNT = 3

# 私有变量 - 下划线前缀
_internal_data = {}
```

#### 1.2 类型注解
```python
from typing import List, Dict, Optional

def get_users(
    page: int = 1,
    page_size: int = 20
) -> Dict[str, any]:
    """
    获取用户列表
    
    Args:
        page: 页码
        page_size: 每页数量
        
    Returns:
        用户数据字典
    """
    pass
```

#### 1.3 函数长度
- 单个函数不超过 40 行
- 复杂逻辑拆分为多个小函数
- 每个函数只做一件事

### Flask 路由规范

#### 2.1 路由装饰器顺序
```python
from flask import Blueprint, request
from app.utils.error_handlers import handle_exceptions

bp = Blueprint('example', __name__)

@bp.route('/example', methods=['GET'])
@handle_exceptions  # 异常处理装饰器应该在最外层
def get_example():
    """获取示例数据"""
    pass
```

#### 2.2 统一响应格式
```python
# 成功响应
return jsonify({
    'success': True,
    'data': data,
    'message': '操作成功'
})

# 错误响应
return jsonify({
    'success': False,
    'error': '错误信息',
    'error_type': 'ERROR_TYPE'
}), 400
```

### 数据库操作规范

#### 3.1 参数化查询
```python
# 好
cursor.execute(
    "SELECT * FROM users WHERE id = ? AND status = ?",
    (user_id, status)
)

# 避免 - SQL 注入风险
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

#### 3.2 连接管理
```python
from contextlib import contextmanager

@contextmanager
def db_connection():
    conn = None
    try:
        conn = get_db_connection()
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
```

### 日志规范

#### 4.1 日志级别
```python
import logging

logger = logging.getLogger(__name__)

logger.debug('调试信息')
logger.info('一般信息')
logger.warning('警告信息')
logger.error('错误信息')
logger.critical('严重错误')
```

#### 4.2 日志格式
```python
# 好
logger.info('User login: user_id=%s ip=%s', user_id, ip)

# 避免
logger.info('User login: user_id=' + str(user_id) + ' ip=' + ip)
```

---

## Git 工作流程

### 分支管理策略

```
main (生产环境)
  └── develop (开发环境)
        ├── feature/user-auth (功能分支)
        ├── feature/strategy-templates (功能分支)
        ├── hotfix/login-bug (热修复分支)
        └── release/v1.0.0 (发布分支)
```

### 分支命名规范

- `feature/xxx` - 功能分支
- `bugfix/xxx` - Bug 修复分支
- `hotfix/xxx` - 紧急修复分支
- `release/xxx` - 发布分支
- `refactor/xxx` - 重构分支

### 提交信息规范

#### Commit 消息格式
```
<type>(<scope>): <subject>

<body>

<footer>
```

#### Type 类型
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档变更
- `style`: 代码格式变更
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具相关

#### 示例
```
feat(auth): 添加用户登录功能

- 实现登录页面
- 添加 API 接口
- 完善错误处理

Closes #123
```

### 代码审查清单

- [ ] 代码符合项目规范
- [ ] 无明显的 Bug
- [ ] 测试覆盖充分
- [ ] 文档更新完善
- [ ] 性能影响评估
- [ ] 安全风险评估

---

## 代码审查流程

### 审查流程

1. **发起审查**
   - 创建 Pull Request
   - 填写审查模板
   - 添加审查者

2. **自动检查**
   - CI/CD 自动运行
   - 代码规范检查
   - 测试覆盖检查

3. **人工审查**
   - 至少 1 人审查
   - 提出修改意见
   - 讨论解决问题

4. **修改与重新审查**
   - 根据意见修改
   - 重新提交审查
   - 确认问题解决

5. **合并代码**
   - 审查通过
   - 合并到目标分支
   - 关闭相关 Issues

### 审查要点清单

#### 功能性检查
- [ ] 功能实现符合需求
- [ ] 边界条件处理正确
- [ ] 异常情况处理完善
- [ ] 用户反馈友好

#### 代码质量检查
- [ ] 代码可读性良好
- [ ] 无重复代码
- [ ] 函数/类设计合理
- [ ] 命名清晰规范

#### 安全检查
- [ ] 无 SQL 注入风险
- [ ] 输入验证充分
- [ ] 敏感数据处理安全
- [ ] 权限控制正确

#### 性能检查
- [ ] 无性能瓶颈
- [ ] 数据库查询优化
- [ ] 资源使用合理
- [ ] 缓存策略合适

#### 测试检查
- [ ] 单元测试覆盖充分
- [ ] 关键功能有集成测试
- [ ] 测试用例设计合理
- [ ] 测试通过率 100%

---

## 测试指南

### 前端测试

#### 1.1 单元测试
```javascript
import { shallowMount } from '@vue/test-utils'
import MyComponent from '@/components/MyComponent.vue'

describe('MyComponent', () => {
  it('renders correctly', () => {
    const wrapper = shallowMount(MyComponent, {
      propsData: { title: 'Test' }
    })
    expect(wrapper.text()).toContain('Test')
  })
})
```

#### 1.2 测试覆盖率目标
- 语句覆盖率: >= 80%
- 分支覆盖率: >= 75%
- 函数覆盖率: >= 80%

### 后端测试

#### 2.1 单元测试
```python
import pytest
from app.services.user_service import UserService

def test_get_user():
    service = UserService()
    user = service.get_user(1)
    assert user is not None
    assert user.id == 1
```

#### 2.2 API 测试
```python
import pytest
from app import create_app

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_get_users(client):
    response = client.get('/api/users')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
```

---

## 性能优化指南

### 前端性能优化

#### 1.1 加载优化
- 路由懒加载
- 组件按需引入
- 图片懒加载
- 资源压缩
- CDN 加速

#### 1.2 渲染优化
- 使用 v-show 替代 v-if
- 合理使用 key
- 避免不必要的计算
- 使用虚拟列表

#### 1.3 网络优化
- API 请求合并
- 请求缓存
- WebSocket 使用
- 离线支持

### 后端性能优化

#### 2.1 数据库优化
- 添加适当索引
- 避免 N+1 查询
- 使用连接池
- 查询分页
- 缓存热点数据

#### 2.2 API 优化
- 响应压缩
- 添加缓存控制头
- 使用异步处理
- 避免不必要的计算

#### 2.3 缓存策略
- Redis 缓存
- 数据库查询缓存
- 静态资源缓存

---

## 附录

### A. 工具推荐

| 类别 | 工具 | 说明 |
|------|------|------|
| 代码格式化 | Prettier, Black | 自动格式化代码 |
| 代码检查 | ESLint, flake8 | 代码规范检查 |
| 版本控制 | Git | 版本管理 |
| 项目管理 | GitHub, GitLab | 代码托管 |
| CI/CD | GitHub Actions, Jenkins | 自动化流程 |

### B. 参考资源

- [Vue 官方风格指南](https://vuejs.org/style-guide/)
- [PEP 8 - Python 代码风格指南](https://peps.python.org/pep-0008/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Google Style Guides](https://google.github.io/styleguide/)
