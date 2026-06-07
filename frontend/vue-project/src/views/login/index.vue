<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">A股分析系统</h1>
      <p class="login-desc">请输入访问令牌</p>
      <a-input-password
        v-model:value="token"
        placeholder="请输入 Token"
        size="large"
        @keyup.enter="handleLogin"
      />
      <a-button type="primary" size="large" block :loading="loading" @click="handleLogin">
        登录
      </a-button>
      <p v-if="error" class="login-error">{{ error }}</p>
    </div>
  </div>
</template>

<script>
import axios from '@/utils/request'

export default {
  name: 'LoginPage',
  data() {
    return { token: '', loading: false, error: '' }
  },
  async created() {
    const saved = localStorage.getItem('token')
    if (saved) {
      try {
        const resp = await axios.get('/api/auth/status')
        if (resp.data?.enabled === false) {
          this.$router.push('/')
        }
      } catch {}
    }
  },
  methods: {
    async handleLogin() {
      this.loading = true
      this.error = ''
      try {
        const resp = await axios.post('/api/auth/login', { token: this.token })
        if (resp.success) {
          localStorage.setItem('token', resp.data.token)
          this.$router.push('/')
        } else {
          this.error = resp.error || '登录失败'
        }
      } catch (e) {
        this.error = e.response?.data?.error || e.message || '网络错误'
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
</style>
