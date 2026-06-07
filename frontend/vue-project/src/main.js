import { createApp } from 'vue'
import moment from 'moment'
window.moment = moment
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import App from './App.vue'
import router from './router'
import { createPinia } from 'pinia'
import i18n from './locales'
import { VueAxios } from './utils/request'
import './global.less'

// ============================================================
// 观潮对标初始化：Schema 迁移 + 缓存预加载 + 主题 (150§2.1)
// ============================================================
import SchemaMigration from './services/schemaMigration'
import { cacheService } from './services/cacheService'

async function bootstrap() {
  // 1. 主题初始化 (从 index.html 内联脚本已读取 localStorage)
  //    确保 CSS 变量优先于页面渲染
  document.documentElement.setAttribute(
    'data-theme',
    localStorage.getItem('app-theme') || 'dark'
  )

  // 2. Schema 迁移（IndexedDB 版本升级）
  try {
    const result = await SchemaMigration.run()
    if (result.migrated) {
      console.log(`[Bootstrap] Schema 迁移: v${result.from} → v${result.to}`)
    }
  } catch (err) {
    console.warn('[Bootstrap] Schema 迁移失败（可忽略）:', err)
  }

  // 3. 清理过期缓存
  try {
    await cacheService.purgeExpired('klines')
    await cacheService.purgeExpired('indicators')
  } catch {
    // 静默
  }
}

bootstrap()

const app = createApp(App)
app.use(Antd)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(VueAxios)
app.mount('#app')
