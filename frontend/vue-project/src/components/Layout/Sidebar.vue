<template>
  <div class="sidebar" :class="{ collapsed: collapsed }">
    <div class="sidebar-header">
      <div class="logo" @click="toggleCollapse">
        <span class="logo-icon">📊</span>
        <span v-if="!collapsed" class="logo-text">A股分析</span>
      </div>
    </div>

    <div class="sidebar-menu">
      <a-menu
        :mode="collapsed ? 'vertical' : 'inline'"
        :selectedKeys="selectedKeys"
        :defaultOpenKeys="openKeys"
        theme="dark"
      >
        <a-menu-item key="/" @click="navigate('/')">
          <a-icon type="dashboard" />
          <span>仪表盘</span>
        </a-menu-item>

        <a-menu-item key="/watchlist" @click="navigate('/watchlist')">
          <a-icon type="star" />
          <span>自选监控</span>
        </a-menu-item>

        <a-menu-item key="/indicator-ide" @click="navigate('/indicator-ide')">
          <a-icon type="code" />
          <span>指标IDE</span>
        </a-menu-item>

        <a-menu-item key="/ai-analysis" @click="navigate('/ai-analysis')">
          <a-icon type="robot" />
          <span>AI分析</span>
        </a-menu-item>

        <a-menu-item key="/backtest" @click="navigate('/backtest')">
          <a-icon type="bar-chart" />
          <span>回测系统</span>
        </a-menu-item>

        <a-menu-item key="/factor-manager" @click="navigate('/factor-manager')">
          <a-icon type="database" />
          <span>因子管理</span>
        </a-menu-item>
      </a-menu>
    </div>

    <div class="sidebar-footer">
      <div class="collapse-btn" @click="toggleCollapse">
        <a-icon :type="collapsed ? 'right' : 'left'" />
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Sidebar',
  data() {
    return {
      collapsed: false,
      selectedKeys: [],
      openKeys: []
    }
  },
  mounted() {
    this.updateSelectedKey()
    this.$router.afterEach(() => {
      this.updateSelectedKey()
    })
  },
  methods: {
    updateSelectedKey() {
      const path = this.$route.path
      this.selectedKeys = [path === '/' ? '/' : path]
    },
    navigate(path) {
      this.$router.push(path)
    },
    toggleCollapse() {
      this.collapsed = !this.collapsed
    }
  }
}
</script>

<style scoped>
.sidebar {
  width: 200px;
  height: 100vh;
  background: #0f172a;
  border-right: 1px solid #2a2a2a;
  display: flex;
  flex-direction: column;
  position: fixed;
  left: 0;
  top: 0;
  z-index: 1000;
  transition: width 0.3s;
}

.sidebar.collapsed {
  width: 64px;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #2a2a2a;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.logo-icon {
  font-size: 24px;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  color: #f1f5f9;
}

.sidebar-menu {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
}

.sidebar-menu :deep(.ant-menu) {
  background: transparent;
  border: none;
}

.sidebar-menu :deep(.ant-menu-item) {
  margin: 4px 0;
  border-radius: 8px;
}

.sidebar-menu :deep(.ant-menu-item-selected) {
  background: rgba(59, 130, 246, 0.2);
}

.sidebar-menu :deep(.ant-menu-item-selected::after) {
  border-right: 3px solid #3b82f6;
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid #2a2a2a;
}

.collapse-btn {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 8px;
  background: #1e293b;
  border-radius: 8px;
  cursor: pointer;
  color: #94a3b8;
  transition: all 0.2s;
}

.collapse-btn:hover {
  background: #334155;
  color: #f1f5f9;
}
</style>
