import axios from 'axios'
import { message } from 'ant-design-vue'

const service = axios.create({
  baseURL: process.env.VUE_APP_API_BASE_URL || 'http://localhost:8080',
  timeout: 60000
})

service.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

service.interceptors.response.use(
  response => {
    const res = response.data
    
    // 兼容两种响应格式
    if (res.code !== undefined) {
      // 格式 1: { code: 200, msg, data }
      if (res.code !== 1 && res.code !== 200) {
        message.error(res.msg || '请求失败')
        return Promise.reject(new Error(res.msg || 'Error'))
      }
      return res
    } else if (res.success !== undefined) {
      // 格式 2: { success: true, message, data }
      if (!res.success) {
        message.error(res.message || res.msg || '请求失败')
        return Promise.reject(new Error(res.message || res.msg || 'Error'))
      }
      return res
    } else {
      // 直接返回原始数据
      return res
    }
  },
  error => {
    console.error('Response error:', error)
    message.error(error.message || '网络错误')
    return Promise.reject(error)
  }
)

export const VueAxios = {
  install(Vue) {
    Object.defineProperty(Vue.prototype, '$http', {
      get() {
        return service
      }
    })
    Vue.axios = service
    Object.defineProperty(Vue, 'axios', {
      get() {
        return service
      }
    })
  }
}

export default service
