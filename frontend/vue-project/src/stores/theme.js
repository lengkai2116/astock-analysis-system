import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  // 从 localStorage 读取主题偏好
  const saved = localStorage.getItem('app-theme')
  const theme = ref(saved || 'dark')
  const isDark = ref(theme.value === 'dark')

  // 应用到 document
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t)
    // 添加过渡动画类
    document.documentElement.classList.add('theme-transition')
    setTimeout(() => document.documentElement.classList.remove('theme-transition'), 300)
  }

  // 切换主题
  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  function setTheme(t) {
    theme.value = t
  }

  // 监听变化
  watch(theme, (t) => {
    isDark.value = t === 'dark'
    localStorage.setItem('app-theme', t)
    applyTheme(t)
  }, { immediate: true })

  return { theme, isDark, toggle, setTheme, applyTheme }
})
