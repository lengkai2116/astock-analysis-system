<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">
        A股分析系统
      </h1>

      <!-- 认证状态信息 -->
      <div
        v-if="statusLoaded && authInfo.enabled"
        class="auth-status"
      >
        <span class="auth-dot auth-on" />
        <span>服务端已开启令牌验证</span>
      </div>
      <div
        v-if="statusLoaded && !authInfo.enabled"
        class="auth-status"
      >
        <span class="auth-dot auth-off" />
        <span>服务端未开启令牌验证，可直接进入</span>
      </div>

      <a-form
        ref="loginFormRef"
        :model="{ token: token }"
        layout="vertical"
        class="login-form"
      >
        <a-form-item
          name="token"
          :rules="[
            { required: true, message: '请输入访问令牌', trigger: 'blur' },
            { min: 4, message: '令牌长度不能少于 4 个字符', trigger: 'blur' }
          ]"
        >
          <a-input-password
            v-model:value="token"
            placeholder="请输入 Token"
            size="large"
            class="login-input"
            @keyup.enter="handleLogin"
          />
        </a-form-item>

        <a-button
          type="primary"
          size="large"
          block
          :loading="loading"
          @click="handleLogin"
        >
          登录
        </a-button>
      </a-form>

      <!-- 令牌提示 -->
      <div
        v-if="statusLoaded && authInfo.enabled && !authInfo.token_preview_shown"
        class="login-hint"
      >
        <p>当前系统已配置访问令牌，请输入后登录。</p>
        <p>
          <a
            style="color:#3b82f6;cursor:pointer;text-decoration:underline"
            @click="showTokenPreview"
          >查看令牌内容</a>
        </p>
      </div>

      <div
        v-if="tokenPreview"
        class="login-hint token-preview"
      >
        <p class="token-label">
          当前令牌：
        </p>
        <code class="token-value">{{ tokenPreview }}</code>
        <p class="token-note">
          复制到输入框即可登录。令牌在项目 .env 文件中 AUTH_TOKEN 变量配置。
        </p>
      </div>

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
    return {
      token: '',
      loading: false,
      error: '',
      hint: '',
      authInfo: { enabled: false, has_token: false, token_preview_shown: false, tokenPreview: '' },
      statusLoaded: false,
      tokenPreview: '',
    }
  },
  async created() {
    try {
      const resp = await axios.get('/api/auth/status')
      this.authInfo.enabled = resp.data?.enabled === true
      this.authInfo.has_token = resp.data?.has_token === true
      this.authInfo.tokenPreview = resp.data?.token_preview || ''
      this.statusLoaded = true

      if (!this.authInfo.enabled) {
        // 免鉴权模式，尝试直接登录
        const r = await axios.post('/api/auth/login', { token: '' })
        if (r.success) {
          localStorage.setItem('token', r.data?.token || 'local-dev')
          this.$router.push('/')
        }
      } else {
        const saved = localStorage.getItem('token')
        if (saved && this.authInfo.has_token) {
          const r = await axios.post('/api/auth/login', { token: saved })
          if (r.success) {
            this.$router.push('/')
          } else {
            localStorage.removeItem('token')
          }
        }
      }
    } catch {
      this.statusLoaded = true
    }
  },
  methods: {
    showTokenPreview() {
      this.authInfo.token_preview_shown = true
      this.tokenPreview = this.authInfo.tokenPreview || '（无令牌信息）'
    },
    async handleLogin() {
      this.error = ''
      this.hint = ''
      // 表单校验：仅认证模式下才需要检查
      if (this.authInfo.enabled && this.$refs.loginFormRef) {
        try {
          await this.$refs.loginFormRef.validate()
        } catch {
          return
        }
      }
      this.loading = true
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
        if (this.authInfo.enabled) {
          this.hint = '当前系统已启用令牌验证，请输入正确的 Token。Token 在项目 .env 文件的 AUTH_TOKEN 变量中设置。'
        }
      } finally {
        this.loading = false
      }
    },
  },
}
</script>

<style>
/* 全局样式：强制 Ant Design Vue 4 登录输入框文字颜色 */
.login-input.ant-input-affix-wrapper,
.login-input.ant-input-affix-wrapper input,
.login-input input,
.ant-input-affix-wrapper .login-input input {
  color: #f1f5f9 !important;
}
.login-input input {
  color: #f1f5f9 !important;
  background: #0f1923 !important;
}
.login-input input::placeholder {
  color: #64748b !important;
}
.ant-input-affix-wrapper .ant-input-password-icon {
  color: #64748b !important;
}
</style>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #0f1923;
}
.login-card {
  width: 380px;
  padding: 40px;
  background: #1a2332;
  border-radius: 12px;
  text-align: center;
}
.login-title {
  color: #e8e8e8;
  font-size: 24px;
  margin-bottom: 16px;
}
.login-desc {
  color: #94a3b8;
  font-size: 14px;
  margin-bottom: 16px;
}
.login-error {
  color: #ff4d4f;
  margin-top: 12px;
  font-size: 13px;
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
  margin: 0 0 4px 0;
}
.login-hint p:last-child {
  margin-bottom: 0;
}
.token-preview {
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
}
.token-label {
  font-size: 12px;
  color: #94a3b8;
}
.token-value {
  display: block;
  padding: 6px 8px;
  background: #0f1923;
  border-radius: 4px;
  font-size: 12px;
  color: #f1f5f9;
  word-break: break-all;
  margin: 4px 0 8px 0;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.token-note {
  font-size: 11px;
  color: #64748b;
}
.auth-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #94a3b8;
}
.auth-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.auth-on { background: #22c55e; }
.auth-off { background: #64748b; }
</style>