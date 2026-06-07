import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'

/**
 * 快捷键系统 Store (150§4.2)
 * 支持 10 个基础快捷键 + 用户自定义绑定
 */
export const useShortcutStore = defineStore('shortcuts', () => {
  const router = useRouter()

  // 快捷键定义
  const shortcuts = ref([
    { id: 'global-search', keys: ['/'], label: '全局搜索', action: 'openGlobalSearch' },
    { id: 'goto-dashboard', keys: ['g', 'i'], label: '跳转仪表盘', action: 'router.push("/")' },
    { id: 'goto-indicator-ide', keys: ['g', 's'], label: '跳转策略分析', action: 'router.push("/indicator-ide")' },
    { id: 'goto-screener', keys: ['g', 'f'], label: '跳转选股', action: 'router.push("/screener")' },
    { id: 'goto-watchlist', keys: ['g', 'w'], label: '跳转自选', action: 'router.push("/watchlist")' },
    { id: 'goto-ai', keys: ['g', 'a'], label: '跳转AI分析', action: 'router.push("/ai-analysis")' },
    { id: 'goto-backtest', keys: ['g', 'b'], label: '跳转回测', action: 'router.push("/backtest")' },
    { id: 'refresh', keys: ['r'], label: '刷新数据', action: 'refreshData' },
    { id: 'close-modal', keys: ['Escape'], label: '关闭弹窗', action: 'closeModal' },
    { id: 'help', keys: ['?'], label: '快捷键帮助', action: 'toggleShortcutHelp' },
  ])

  // 用户自定义绑定覆盖
  const customBindings = ref(JSON.parse(localStorage.getItem('shortcut-bindings') || '{}'))

  // 当前按下的键 (用于组合键)
  const pressedKeys = ref(new Set())
  const showHelp = ref(false)

  // 获取实际绑定 (用户自定义优先)
  function getBinding(id) {
    const custom = customBindings.value[id]
    return custom || shortcuts.value.find(s => s.id === id)?.keys
  }

  function setBinding(id, keys) {
    customBindings.value[id] = keys
    localStorage.setItem('shortcut-bindings', JSON.stringify(customBindings.value))
  }

  function resetBinding(id) {
    delete customBindings.value[id]
    localStorage.setItem('shortcut-bindings', JSON.stringify(customBindings.value))
  }

  // 注册快捷键 (由 App.vue 调用)
  function registerActions(actions) {
    // actions: { openGlobalSearch, refreshData, closeModal, toggleShortcutHelp }
    window.__shortcutActions = actions
  }

  function handleKeyDown(e) {
    // 忽略输入框内的快捷键
    const tag = e.target.tagName
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) {
      if (e.key === 'Escape') {
        e.target.blur()
        return
      }
      return
    }

    const key = e.key
    pressedKeys.value.add(key)

    // 检查匹配
    const actions = window.__shortcutActions
    if (!actions) return

    // 遍历快捷键
    for (const shortcut of shortcuts.value) {
      const binding = getBinding(shortcut.id)
      if (!binding) continue

      // 单键
      if (binding.length === 1) {
        if (key === binding[0] && !e.ctrlKey && !e.metaKey) {
          if (key === '/') {
            e.preventDefault()
            actions.openGlobalSearch()
            return
          }
          if (key === 'Escape') {
            actions.closeModal()
            return
          }
          if (key === '?') {
            actions.toggleShortcutHelp()
            return
          }
          if (key === 'r' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault()
            actions.refreshData()
            return
          }
        }
        continue
      }

      // 组合键 (如 g + i)
      if (binding.length === 2) {
        if (key === binding[1] && pressedKeys.value.has(binding[0])) {
          e.preventDefault()
          // 路由跳转
          const match = shortcut.action.match(/router\.push\("([^"]+)"\)/)
          if (match && actions.router) {
            actions.router.push(match[1])
          }
          pressedKeys.value.clear()
          return
        }
      }
    }
  }

  function handleKeyUp(e) {
    pressedKeys.value.delete(e.key)
  }

  function toggleHelp() {
    showHelp.value = !showHelp.value
  }

  function closeHelp() {
    showHelp.value = false
  }

  return {
    shortcuts,
    customBindings,
    showHelp,
    getBinding,
    setBinding,
    resetBinding,
    registerActions,
    handleKeyDown,
    handleKeyUp,
    toggleHelp,
    closeHelp,
  }
})
