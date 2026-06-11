<template>
  <div
    id="app"
    tabindex="0"
    @keydown="onKeyDown"
    @keyup="onKeyUp"
  >
    <ErrorBoundary component-name="AppRoot">
      <Sidebar />
      <div
        class="main-content"
        :class="{ 'sidebar-collapsed': sidebarCollapsed }"
      >
        <router-view />
      </div>

      <!-- 数据源状态指示 (150§4.1) -->
      <DataSourceStatusBar :status="dataSourceStatus" />

      <!-- 快捷键帮助浮层 (150§4.2) -->
      <ShortcutsHelp
        v-if="showShortcutHelp"
        @close="closeShortcutHelp"
      />
    </ErrorBoundary>
  </div>
</template>

<script>
import { mapState, mapActions } from 'pinia'
import { useAppStore } from '@/stores'
import { useThemeStore } from '@/stores/theme'
import { useShortcutStore } from '@/stores/shortcuts'
import Sidebar from '@/components/Layout/Sidebar'
import ErrorBoundary from '@/components/ErrorBoundary'
import DataSourceStatusBar from '@/components/DataSourceStatus/DataSourceStatusBar'
import ShortcutsHelp from '@/components/ShortcutsHelp'

export default {
  name: 'App',
  components: {
    Sidebar,
    ErrorBoundary,
    DataSourceStatusBar,
    ShortcutsHelp,
  },
  data() {
    return {
      dataSourceStatus: null,
      statusTimer: null,
    }
  },
  computed: {
    ...mapState(useAppStore, ['sidebarCollapsed']),
    showShortcutHelp() {
      return this.$shortcutStore?.showHelp || false
    }
  },
  created() {
    // 初始化主题
    this.$themeStore = useThemeStore()

    // 初始化快捷键
    this.$shortcutStore = useShortcutStore()
    this.$shortcutStore.registerActions({
      openGlobalSearch: this.openGlobalSearch,
      refreshData: this.refreshAllData,
      closeModal: this.closeActiveModal,
      toggleShortcutHelp: this.$shortcutStore.toggleHelp,
      router: this.$router,
    })
    this.$shortcutStore.$subscribe(() => {
      // reactive update for showShortcutHelp
    })
  },
  mounted() {
    // 数据源状态轮询
    this._pollDataSourceStatus()
  },
  beforeUnmount() {
    if (this.statusTimer) {
      clearInterval(this.statusTimer)
    }
  },
  methods: {
    ...mapActions(useAppStore, ['toggleSidebar']),

    onKeyDown(e) {
      this.$shortcutStore.handleKeyDown(e)
    },
    onKeyUp(e) {
      this.$shortcutStore.handleKeyUp(e)
    },

    openGlobalSearch() {
      // 触发全局搜索——通过自定义事件
      window.dispatchEvent(new CustomEvent('app:global-search'))
    },

    refreshAllData() {
      window.dispatchEvent(new CustomEvent('app:refresh-data'))
    },

    closeActiveModal() {
      // 尝试关闭 ant-design-vue 的 modal
      const modals = document.querySelectorAll('.ant-modal-wrap')
      if (modals.length > 0) {
        // 点击各 modal 的关闭按钮
        const closeBtns = document.querySelectorAll('.ant-modal-close')
        if (closeBtns.length > 0) {
          closeBtns[closeBtns.length - 1].click()
        }
      }
      // 触发自定义关闭事件
      window.dispatchEvent(new CustomEvent('app:close-modal'))
    },

    closeShortcutHelp() {
      this.$shortcutStore.closeHelp()
    },

    async _pollDataSourceStatus() {
      try {
        const { default: dataService } = await import('@/services/dataService')
        const res = await dataService.getDataSourceStatus()
        if (res && res.sources) {
          const sources = Object.entries(res.sources).map(([name, info]) => ({
            name,
            status: info.status,
            latency: info.avg_latency_ms,
            failures: info.consecutive_failures,
          }))
          const worst = sources.reduce(
            (prev, curr) => {
              const rank = { normal: 0, degraded: 1, fallback: 2, unavailable: 3 }
              return rank[curr.status] > rank[prev.status] ? curr : prev
            },
            { status: 'normal', name: 'all' }
          )
          this.dataSourceStatus = {
            sources,
            active_source: res.active || 'unknown',
            active_status: worst.status,
            status: worst.status,
          }
        }
      } catch {
        // 静默
      }

      this.statusTimer = setInterval(() => {
        this._pollDataSourceStatus()
      }, 30000)
    },
  },
}
</script>

<style>
#app {
  min-height: 100vh;
  background: var(--bg-canvas);
  display: flex;
  outline: none;
  transition: background-color 0.3s ease;
}

.main-content {
  flex: 1;
  margin-left: var(--sidebar-width);
  min-height: 100vh;
  transition: margin-left 0.3s;
}

.main-content.sidebar-collapsed {
  margin-left: var(--sidebar-collapsed-width);
}

a {
  color: var(--color-brand-500);
}
</style>
