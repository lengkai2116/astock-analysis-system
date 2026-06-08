<template>
  <div
    class="sidebar"
    :class="{ collapsed: collapsed }"
  >
    <div class="sidebar-header">
      <div
        class="logo"
        @click="toggleCollapse"
      >
        <span class="logo-icon">📊</span>
        <span
          v-if="!collapsed"
          class="logo-text"
        >A股分析</span>
      </div>
    </div>

    <div class="sidebar-menu">
      <a-menu
        :mode="collapsed ? 'vertical' : 'inline'"
        :selected-keys="selectedKeys"
        :default-open-keys="openKeys"
        theme="dark"
      >
        <a-menu-item
          key="/"
          @click="navigate('/')"
        >
          <DashboardOutlined />
          <span>仪表盘</span>
        </a-menu-item>

        <a-menu-item
          key="/indicator-ide"
          @click="navigate('/indicator-ide')"
        >
          <CodeOutlined />
          <span>个股策略分析</span>
        </a-menu-item>

        <a-menu-item
          key="/screener"
          @click="navigate('/screener')"
        >
          <FilterOutlined />
          <span>选股系统</span>
        </a-menu-item>

        <a-menu-item
          key="/watchlist"
          @click="navigate('/watchlist')"
        >
          <StarOutlined />
          <span>自选监控</span>
        </a-menu-item>

        <a-menu-item
          key="/ai-analysis"
          @click="navigate('/ai-analysis')"
        >
          <RobotOutlined />
          <span>AI分析</span>
        </a-menu-item>

        <a-menu-item
          key="/backtest"
          @click="navigate('/backtest')"
        >
          <BarChartOutlined />
          <span>回测系统</span>
        </a-menu-item>

        <a-menu-item
          key="/factor-manager"
          @click="navigate('/factor-manager')"
        >
          <DatabaseOutlined />
          <span>因子管理</span>
        </a-menu-item>

        <a-menu-item
          key="/strategy-templates"
          @click="navigate('/strategy-templates')"
        >
          <FileTextOutlined />
          <span>策略模板</span>
        </a-menu-item>

        <a-menu-item
          key="/reports-center"
          @click="navigate('/reports-center')"
        >
          <FolderOutlined />
          <span>报告中心</span>
        </a-menu-item>

        <a-menu-item
          key="/account"
          @click="navigate('/account')"
        >
          <WalletOutlined />
          <span>账户管理</span>
        </a-menu-item>
      </a-menu>
    </div>

    <div class="sidebar-footer">
      <!-- 主题切换按钮 (150§2.1) -->
      <div
        class="theme-toggle"
        :title="isDark ? '切换到浅色主题' : '切换到深色主题'"
        @click="toggleTheme"
      >
        <span class="theme-toggle-icon">{{ isDark ? '☀️' : '🌙' }}</span>
        <span
          v-if="!collapsed"
          class="theme-toggle-text"
        >{{ isDark ? '浅色主题' : '深色主题' }}</span>
      </div>

      <div
        class="collapse-btn"
        @click="toggleCollapse"
      >
        <RightOutlined v-if="collapsed" /><LeftOutlined v-else />
      </div>
    </div>
  </div>
</template>

<script>
import {
  BarChartOutlined, CodeOutlined, DashboardOutlined, DatabaseOutlined,
  FileTextOutlined, FilterOutlined, FolderOutlined, LeftOutlined,
  RightOutlined, RobotOutlined, StarOutlined, WalletOutlined,
} from '@ant-design/icons-vue'
import { mapState, mapActions } from 'pinia'
import { useAppStore } from '@/stores'
import { useThemeStore } from '@/stores/theme'

export default {
  name: 'Sidebar',
  components: {
    BarChartOutlined, CodeOutlined, DashboardOutlined, DatabaseOutlined,
    FileTextOutlined, FilterOutlined, FolderOutlined, LeftOutlined,
    RightOutlined, RobotOutlined, StarOutlined, WalletOutlined,
  },
  data() {
    return {
      selectedKeys: [],
      openKeys: [],
    }
  },
  computed: {
    ...mapState(useAppStore, { collapsed: 'sidebarCollapsed' }),
    isDark() {
      return this.$themeStore?.isDark
    },
  },
  created() {
    this.$themeStore = useThemeStore()
  },
  mounted() {
    this.updateSelectedKey()
    this.$router.afterEach(() => {
      this.updateSelectedKey()
    })
  },
  methods: {
    ...mapActions(useAppStore, ['toggleSidebar']),
    toggleCollapse() {
      this.toggleSidebar()
    },
    toggleTheme() {
      this.$themeStore.toggle()
    },
    updateSelectedKey() {
      const path = this.$route.path
      this.selectedKeys = [path === '/' ? '/' : path]
    },
    navigate(path) {
      this.$router.push(path)
    },
  },
}
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  display: flex;
  flex-direction: column;
  position: fixed;
  left: 0;
  top: 0;
  z-index: 1000;
  transition: width 0.3s;
}

.sidebar.collapsed {
  width: var(--sidebar-collapsed-width);
}

.sidebar-header {
  padding: var(--space-16);
  border-bottom: 1px solid var(--sidebar-border);
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
  color: var(--text-primary);
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
  border-radius: var(--radius-md);
}

.sidebar-menu :deep(.ant-menu-item-selected) {
  background: var(--sidebar-menu-selected-bg);
}

.sidebar-menu :deep(.ant-menu-item-selected::after) {
  border-right: 3px solid var(--color-brand-500);
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--sidebar-border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.theme-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: var(--sidebar-collapse-bg);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.theme-toggle:hover {
  background: var(--sidebar-collapse-hover-bg);
  color: var(--text-primary);
}

.theme-toggle-icon {
  font-size: 16px;
}

.theme-toggle-text {
  font-size: 13px;
}

.collapse-btn {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 8px;
  background: var(--sidebar-collapse-bg);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.collapse-btn:hover {
  background: var(--sidebar-collapse-hover-bg);
  color: var(--text-primary);
}
</style>
