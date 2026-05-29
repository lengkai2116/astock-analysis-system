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

const app = createApp(App)
app.use(Antd)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(VueAxios)
app.mount('#app')
