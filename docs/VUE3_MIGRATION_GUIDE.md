# Vue 3 迁移指南

## 项目迁移状态

- 当前版本: Vue 2.7 + Ant Design Vue 1.7.8
- 目标版本: Vue 3 + Ant Design Vue 4.x
- 迁移策略: 渐进式迁移

## 迁移步骤

### 阶段 1: 准备阶段 (已完成)
- ✅ 依赖分析
- ✅ 废弃API标记
- ✅ 迁移计划制定

### 阶段 2: Vue 3 安装与配置
- ⏳ 安装 Vue 3 及相关依赖
- ⏳ 配置 Vue 3 兼容模式
- ⏳ 配置 TypeScript（可选）

### 阶段 3: 核心依赖升级
- ⏳ 升级 Vue Router 到 4.x
- ⏳ 升级 Vuex 到 4.x 或迁移到 Pinia
- ⏳ 升级 Ant Design Vue 到 4.x

### 阶段 4: 组件迁移
- ⏳ 基础组件迁移
- ⏳ 业务组件迁移
- ⏳ 自定义组件重构

### 阶段 5: 测试与优化
- ⏳ 单元测试
- ⏳ 集成测试
- ⏳ 性能优化

## 依赖升级清单

### 核心依赖
```json
{
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.2.0",
    "pinia": "^2.1.0",
    "ant-design-vue": "^4.1.0",
    "@ant-design/icons-vue": "^7.0.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "@vue/compat": "^3.4.0"
  }
}
```

## 配置变更

### vite.config.js 变更
```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue({
      template: {
        compilerOptions: {
          // Vue 2 兼容配置
        }
      }
    })
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      // Vue 2 到 Vue 3 的兼容层
      'vue': '@vue/compat'
    }
  }
})
```

## API 迁移对照表

### 1. v-model 变化
```vue
<!-- Vue 2 -->
<ChildComponent v-model="value" />
<ChildComponent :value.sync="value" />

<!-- Vue 3 -->
<ChildComponent v-model="value" />
<ChildComponent v-model:title="title" />
```

### 2. Slots 变化
```vue
<!-- Vue 2 -->
<template slot="header" slot-scope="{ data }">
  {{ data }}
</template>

<!-- Vue 3 -->
<template #header="{ data }">
  {{ data }}
</template>
```

### 3. 事件总线
```javascript
// Vue 2
import Vue from 'vue'
export const EventBus = new Vue()

// Vue 3
import mitt from 'mitt'
export const EventBus = mitt()
```

### 4. 生命周期
```javascript
// Vue 2
beforeDestroy()
destroyed()

// Vue 3
beforeUnmount()
unmounted()
```

### 5. 响应式 API
```javascript
// Vue 2 (Options API)
export default {
  data() {
    return {
      count: 0
    }
  }
}

// Vue 3 (Composition API)
import { ref } from 'vue'
export default {
  setup() {
    const count = ref(0)
    return { count }
  }
}
```

## Ant Design Vue 迁移

### 图标组件
```vue
<!-- Vue 2 + ADesign Vue 1.x -->
<template>
  <a-icon type="dashboard" />
  <a-icon type="setting" theme="filled" />
</template>

<!-- Vue 3 + ADesign Vue 4.x -->
<template>
  <DashboardOutlined />
  <SettingFilled />
</template>

<script setup>
import { DashboardOutlined, SettingFilled } from '@ant-design/icons-vue'
</script>
```

### Modal 组件
```vue
<!-- Vue 2 -->
<a-modal :visible.sync="visible" />

<!-- Vue 3 -->
<a-modal v-model:visible="visible" />
```

### Table 组件
```vue
<!-- Vue 2 -->
<a-table :columns="columns" :dataSource="data">
  <template slot="name" slot-scope="text">
    {{ text }}
  </template>
</a-table>

<!-- Vue 3 -->
<a-table :columns="columns" :dataSource="data">
  <template #name="{ text }">
    {{ text }}
  </template>
</a-table>
```

## Vuex 到 Pinia 迁移

### Store 对比
```javascript
// Vuex (Vue 2)
export default new Vuex.Store({
  state: { count: 0 },
  mutations: {
    increment(state) {
      state.count++
    }
  },
  actions: {
    async incrementAsync({ commit }) {
      await new Promise(r => setTimeout(r, 1000))
      commit('increment')
    }
  }
})

// Pinia (Vue 3)
export const useCounterStore = defineStore('counter', {
  state: () => ({ count: 0 }),
  actions: {
    increment() {
      this.count++
    },
    async incrementAsync() {
      await new Promise(r => setTimeout(r, 1000))
      this.increment()
    }
  }
})
```

### 组件使用对比
```javascript
// Vuex
export default {
  computed: {
    count() { return this.$store.state.count }
  },
  methods: {
    increment() { this.$store.commit('increment') }
  }
}

// Pinia
import { storeToRefs } from 'pinia'
import { useCounterStore } from '@/stores/counter'

export default {
  setup() {
    const store = useCounterStore()
    const { count } = storeToRefs(store)
    return { count, increment: store.increment }
  }
}
```

## 回滚方案

如果迁移过程中遇到严重问题，可以：
1. 回滚到 Vue 2.7 分支
2. 使用 @vue/compat 兼容模式
3. 逐步分批迁移组件

## 注意事项

1. **数据响应式**: Vue 3 使用 Proxy，与 Vue 2 的 Object.defineProperty 有差异
2. **移除的 API**: $on, $off, $once, $listeners 已移除
3. **过滤器**: 过滤器已移除，使用计算属性替代
4. **transition-group**: 需要显式指定 tag 属性

## 参考资源

- [Vue 3 迁移指南](https://v3-migration.vuejs.org/)
- [Vue Router 4 迁移](https://router.vuejs.org/guide/migration/)
- [Pinia 官方文档](https://pinia.vuejs.org/)
- [Ant Design Vue 4.x 迁移](https://antdv.com/docs/vue/migration-v4-cn)
