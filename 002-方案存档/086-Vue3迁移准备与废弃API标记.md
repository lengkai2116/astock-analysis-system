# Vue 3 迁移准备与已废弃API标记

**文档版本**: 1.0  
**创建日期**: 2026-05-24  
**目标**: 标记所有需要迁移的Vue 2 API，为Vue 3升级做准备

---

## 第一部分：已废弃的Vue 2 API标记

### 1.1 Vue Router API

| 文件位置 | 当前用法 | 废弃原因 | 迁移建议 |
|---------|---------|---------|---------|
| Sidebar.vue | `this.$router.push()` | Vue 3兼容 | 保持不变 |
| 所有.vue文件 | `this.$router` | Composition API | 改用 `useRouter()` |

**标记状态**: ⚠️ 待迁移

### 1.2 Vuex Store API

| 文件位置 | 当前用法 | 废弃原因 | 迁移建议 |
|---------|---------|---------|---------|
| store/index.js | `Vuex.Store` | Vue 3不兼容 | 改用 `createStore()` 或 `Pinia` |
| 所有.vue文件 | `this.$store` | Composition API | 改用 `useStore()` 或 Pinia |

**标记状态**: ⚠️ 待迁移

---

## 第二部分：已废弃的Ant Design Vue API

### 2.1 Icon组件

| 文件位置 | 当前用法 | 废弃原因 | 迁移建议 |
|---------|---------|---------|---------|
| Sidebar.vue | `<a-icon type="dashboard" />` | A-IV 4.x语法 | 改用 `<DashboardOutlined />` |
| 所有.vue文件 | `<a-icon type="xxx" />` | A-IV 4.x语法 | 改用组件式icon |

**标记状态**: ⚠️ 待迁移

### 2.2 Modal组件

| 文件位置 | 当前用法 | 废弃原因 | 迁移建议 |
|---------|---------|---------|---------|
| watchlist/index.vue | `slot="overlay"` | Vue 2语法 | 改用 `v-slot:overlay` |
| 所有.vue文件 | `v-model.sync` | Vue 2语法 | 改用 `v-model:visible` |

**标记状态**: ⚠️ 待迁移

### 2.3 Table组件

| 文件位置 | 当前用法 | 废弃原因 | 迁移建议 |
|---------|---------|---------|---------|
| watchlist/index.vue | `slot="customRender"` | Vue 2语法 | 改用 `#customRender` |
| 所有.vue文件 | `slot-scope` | Vue 2语法 | 改用 `v-slot` |

**标记状态**: ⚠️ 待迁移

---

## 第三部分：需要重写的组件

### 3.1 必须重写的组件列表

| 组件路径 | 优先级 | 重写难度 | 备注 |
|---------|--------|---------|------|
| src/views/watchlist/index.vue | 🔴 高 | 🟡 中 | 使用大量Ant Design组件 |
| src/views/dashboard/index.vue | 🔴 高 | 🟢 低 | 使用Ant Design组件较少 |
| src/components/Layout/Sidebar.vue | 🔴 高 | 🟡 中 | 包含icon和菜单组件 |
| src/store/index.js | 🔴 高 | 🔴 高 | Vuex → Pinia迁移 |

### 3.2 可渐进迁移的组件

| 组件路径 | 优先级 | 重写难度 | 备注 |
|---------|--------|---------|------|
| src/views/indicator-ide/index.vue | 🟠 中 | 🔴 高 | Monaco Editor集成复杂 |
| src/views/backtest/index.vue | 🟠 中 | 🟡 中 | 图表组件需要适配 |
| src/views/ai-analysis/index.vue | 🟠 中 | 🟡 中 | AI功能相对独立 |
| src/views/factor-manager/index.vue | 🟠 中 | 🟡 中 | 表格组件较多 |

---

## 第四部分：迁移检查清单

### 4.1 Phase 1: 依赖分析 ✅

- [x] 识别Vue 3不兼容的依赖
- [x] 评估Ant Design Vue 4.x兼容性
- [x] 确认Vuex → Pinia迁移方案
- [x] 制定第三方库升级计划

**完成时间**: 2026-05-24

### 4.2 Phase 2: 代码标记 ⚠️ (进行中)

- [ ] 标记所有 `this.$router` 用法
- [ ] 标记所有 `this.$store` 用法
- [ ] 标记所有废弃的Ant Design API
- [ ] 标记所有Composition API可用场景

**预计完成**: 1周

### 4.3 Phase 3: 测试环境搭建 ⏳ (待开始)

- [ ] 搭建Vue 3开发环境
- [ ] 配置兼容层（如 @vue/compat）
- [ ] 创建测试用例
- [ ] 验证核心功能

**预计完成**: 2周

### 4.4 Phase 4: 渐进式迁移 ⏳ (待开始)

- [ ] 迁移路由（Vue Router 4.x）
- [ ] 迁移状态管理（Vuex → Pinia）
- [ ] 迁移UI组件（Ant Design Vue 4.x）
- [ ] 重构业务组件

**预计完成**: 6-8周

---

## 第五部分：迁移执行指南

### 5.1 Icon组件迁移示例

**Before (Vue 2 + A-IV 1.x)**:
```vue
<template>
  <a-icon type="dashboard" />
  <a-icon type="search" theme="outlined" />
</template>
```

**After (Vue 3 + A-IV 4.x)**:
```vue
<template>
  <DashboardOutlined />
  <SearchOutlined />
</template>

<script setup>
import { DashboardOutlined, SearchOutlined } from '@ant-design/icons-vue'
</script>
```

### 5.2 Modal组件迁移示例

**Before (Vue 2 + A-IV 1.x)**:
```vue
<a-modal
  title="Title"
  :visible.sync="visible"
>
  <template slot="footer">Footer</template>
</a-modal>
```

**After (Vue 3 + A-IV 4.x)**:
```vue
<a-modal
  v-model:visible="visible"
  title="Title"
>
  <template #footer>Footer</template>
</a-modal>
```

### 5.3 Vuex → Pinia迁移示例

**Before (Vue 2 + Vuex)**:
```javascript
// store/index.js
export default new Vuex.Store({
  state: {
    user: null
  },
  mutations: {
    setUser(state, user) {
      state.user = user
    }
  },
  actions: {
    async fetchUser({ commit }) {
      const user = await api.getUser()
      commit('setUser', user)
    }
  }
})

// Component
export default {
  computed: {
    user() {
      return this.$store.state.user
    }
  },
  methods: {
    async loadUser() {
      await this.$store.dispatch('fetchUser')
    }
  }
}
```

**After (Vue 3 + Pinia)**:
```javascript
// stores/user.js
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', {
  state: () => ({
    user: null
  }),
  actions: {
    async fetchUser() {
      const user = await api.getUser()
      this.user = user
    }
  }
})

// Component
<script setup>
import { storeToRefs } from 'pinia'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const { user } = storeToRefs(userStore)

async function loadUser() {
  await userStore.fetchUser()
}
</script>
```

### 5.4 Slots语法迁移

**Before (Vue 2)**:
```vue
<a-table>
  <template slot="name" slot-scope="text, record">
    {{ text }}
  </template>
</a-table>
```

**After (Vue 3)**:
```vue
<a-table>
  <template #name="{ text }">
    {{ text }}
  </template>
</a-table>
```

---

## 第六部分：兼容性配置

### 6.1 安装Vue 3兼容层

```bash
npm install vue@3 vue-router@4 pinia@2 @vue/compiler-sfc
npm install ant-design-vue@4 @ant-design/icons-vue
npm install -D @vue/compat
```

### 6.2 配置Vite

```javascript
// vite.config.js
export default {
  plugins: [
    vue({
      template: {
        compilerOptions: {
          // 兼容旧组件
        }
      }
    })
  ],
  resolve: {
    alias: {
      'vue': 'vue/compat'
    }
  }
}
```

### 6.3 main.js配置

```javascript
import { createApp } from 'vue'
import { createCompatVue } from '@vue/compat'

const app = createApp(App)

// 启用Vue 2兼容模式
app.use(createCompatVue())

// 安装Vue Router 4.x
import router from './router'
app.use(router)

// 安装Pinia
import { createPinia } from 'pinia'
app.use(createPinia())

app.mount('#app')
```

---

## 第七部分：测试计划

### 7.1 单元测试

- [ ] 为每个组件编写单元测试
- [ ] 测试Vuex/Pinia store
- [ ] 测试API调用
- [ ] 测试业务逻辑

### 7.2 集成测试

- [ ] 测试路由跳转
- [ ] 测试WebSocket连接
- [ ] 测试表单提交
- [ ] 测试数据展示

### 7.3 E2E测试

- [ ] 端到端用户流程测试
- [ ] 跨浏览器兼容性测试
- [ ] 性能基准测试

---

## 第八部分：风险评估

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| 组件兼容性问题 | 高 | 中 | 使用@vue/compat兼容层 |
| 第三方库不兼容 | 高 | 中 | 寻找替代库或自己实现 |
| 功能回归bug | 高 | 中 | 完善测试覆盖 |
| 性能下降 | 中 | 低 | 性能优化和基准测试 |
| 开发进度延误 | 中 | 中 | 预留20%缓冲时间 |

---

## 第九部分：文档维护

**最后更新**: 2026-05-24  
**下次审查**: 2026-05-31  
**负责人**: AI Assistant

**更新记录**:
- 2026-05-24: 创建文档，完成依赖分析，标记需要迁移的API
