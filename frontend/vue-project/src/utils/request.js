import axios from 'axios'
import { message } from 'ant-design-vue'

const service = axios.create({
  baseURL: (window.__API_BASE__ || import.meta.env.VITE_API_BASE_URL || ''),
  timeout: 30000
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
    if (error.response) {
      const status = error.response.status
      const data = error.response.data || {}
      if (status === 401) {
        message.warning('请先登录')
        localStorage.removeItem('token')
        window.location.hash = '#/login'
      } else if (status === 403) {
        message.error('令牌无效，请重新登录')
        localStorage.removeItem('token')
        window.location.hash = '#/login'
      } else if (status >= 500 && status < 600) {
        // 500 系列错误：幂等请求自动重试一次
        if (error.config && ['get', 'head', 'options'].includes(error.config.method) && !error.config._retry) {
          error.config._retry = true
          return new Promise(resolve => setTimeout(resolve, 1000))
            .then(() => service(error.config))
        }
        message.error('服务暂时不可用，请稍后重试')
      } else {
        message.error(data.error || data.msg || data.message || `请求失败(${status})`)
      }
    } else if (error.code === 'ECONNABORTED') {
      message.error('请求超时，请检查网络')
    } else {
      message.error(error.message || '网络错误')
    }
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
