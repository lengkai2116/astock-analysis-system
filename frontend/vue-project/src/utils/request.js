import axios from 'axios'
import { message } from 'ant-design-vue'

const service = axios.create({
  baseURL: (window.__API_BASE__ || import.meta.env.VITE_API_BASE_URL || ''),
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
      if (res.code !== 1 && res.code !== 200) {
        message.error(res.msg || '请求失败')
        return Promise.reject(new Error(res.msg || 'Error'))
      }
      return res
    } else if (res.success !== undefined) {
      if (!res.success) {
        message.error(res.message || res.msg || '请求失败')
        return Promise.reject(new Error(res.message || res.msg || 'Error'))
      }
      return res
    } else {
      return res
    }
  },
  error => {
    console.error('Response error:', error)
    message.error(error.message || '网络错误')
    return Promise.reject(error)
  }
)

// Vue 3 插件形式
export const VueAxios = {
  install(app) {
    app.config.globalProperties.$http = service
    app.config.globalProperties.$axios = service
  }
}

export default service
