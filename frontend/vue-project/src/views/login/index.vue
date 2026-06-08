<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">
        A股分析系统
      </h1>
      <p class="login-desc">
        请输入访问令牌
      </p>
      <a-input-password
        v-model:value="token"
        placeholder="请输入 Token"
        size="large"
        @keyup.enter="handleLogin"
      />
      <a-button
        type="primary"
        size="large"
        block
        :loading="loading"
        @click="handleLogin"
      >
        登录
      </a-button>
      <div
        v-if="hint"
        class="login-hint"
      >
        <p>{{ hint }}</p>
      </div>
      <p
        v-if="error"
        class="login-error"
      >
        {{ error }}
      </p>
    </div>
  </div>
</template>

<script>
import axios from '@/utils/request'

export default {
  name: 'LoginPage',
  data() {
    return { token: '', loading: false, error: '', hint: '' }
  },
  async created() {
    // Check auth status - skip login if auth disabled or already have a valid token
    try {
      const resp = await axios.get('/api/auth/status')
      if (resp.data?.enabled === false) {
        this.$router.push('/')
        return
      }
      // If auth is enabled and we have a saved token, try using it
      const saved = localStorage.getItem('token')
      if (saved) {
        this.$router.push('/')
      }
    } catch {}  // Silently handle if backend not reachable
  },
  methods: {
    async handleLogin() {
      this.loading = true
      this.error = ''
      this.hint = ''
      try {
        const resp = await axios.post('/api/auth/login', { token: this.token })
        if (resp.success) {
          localStorage.setItem('token', resp.data.token)
          this.$router.push('/')
        } else {
          this.error = resp.error || '登录失败'
          this.hint = 'Token 在服务端 .env 文件中 AUTH_TOKEN 变量配置，可联系管理员获取'
        }
      } catch (e) {
        this.error = e.response?.data?.error || e.message || '网络错误'
        this.hint = '支持留空登录（如果服务端未启用鉴权）或输入 .env 中 AUTH_TOKEN 的值'
      } finally {
        this.loading = false
      }
    },
  },
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #0f1923;
}
.login-card {
  width: 360px;
  padding: 40px;
  background: #1a2332;
  border-radius: 12px;
  text-align: center;
}
.login-title {
  color: #e8e8e8;
  font-size: 24px;
  margin-bottom: 8px;
}
.login-desc {
  color: #888;
  margin-bottom: 24px;
}
.login-error {
  color: #ff4d4f;
  margin-top: 12px;
}
.login-hint {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #94a3b8;
  text-align: left;
}
.login-hint p {
  margin: 0;
}

/* 确保登录页输入框文字清晰可见 */
.login-card :deep(.ant-input) {
  color: #f1f5f9 !important;
  background: #0f1923 !important;
  border-color: #334155 !important;
}
.login-card :deep(.ant-input:focus) {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
}
.login-card :deep(.ant-input-password-icon) {
  color: #64748b !important;
}
.login-card :deep(.ant-input::placeholder) {
  color: #64748b !important;
}
</style>
