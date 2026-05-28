import Vue from 'vue'
import moment from 'moment'
window.moment = moment
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/antd.less'
import App from './App.vue'
import router from './router'
import store from './store'
import i18n from './locales'
import { VueAxios } from './utils/request'
import './global.less'

Vue.config.productionTip = false

Vue.use(Antd)
Vue.use(VueAxios)

if (typeof window !== 'undefined') {
  const ignoreResizeObserverError = (e) => {
    const msg = (e && (e.reason && e.reason.message || e.message)) || ''
    if (msg.includes('ResizeObserver loop') || msg.includes('ResizeObserver loop limit exceeded')) {
      e.preventDefault && e.preventDefault()
      e.stopImmediatePropagation && e.stopImmediatePropagation()
      return false
    }
  }
  window.addEventListener('error', ignoreResizeObserverError)
  window.addEventListener('unhandledrejection', ignoreResizeObserverError)
}

new Vue({
  router,
  store,
  i18n,
  render: h => h(App)
}).$mount('#app')
