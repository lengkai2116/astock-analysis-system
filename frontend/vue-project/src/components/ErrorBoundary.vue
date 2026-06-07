<template>
  <div v-if="hasError" class="error-boundary">
    <div class="error-boundary__content">
      <div class="error-boundary__icon">
        <WarningOutlined />
      </div>
      <h3>页面渲染异常</h3>
      <p class="error-boundary__message">{{ errorMessage }}</p>
      <div class="error-boundary__actions">
        <a-button type="primary" @click="reload">重新加载</a-button>
        <a-button @click="reset">重置组件</a-button>
        <a-button type="link" @click="copyError">复制错误信息</a-button>
      </div>
      <details v-if="errorStack" class="error-boundary__stack">
        <summary>错误详情</summary>
        <pre>{{ errorStack }}</pre>
      </details>
    </div>
  </div>
  <slot v-else />
</template>

<script setup>
/**
 * Vue 3 全局错误边界组件
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §5.2
 * 捕获组件渲染异常，展示降级 UI，防止白屏
 */
import { ref, onErrorCaptured } from 'vue'
import { WarningOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

const props = defineProps({
  /** 组件名（用于日志标识） */
  componentName: { type: String, default: 'Unknown' },
})

const emit = defineEmits(['error', 'recover'])

const hasError = ref(false)
const errorMessage = ref('')
const errorStack = ref('')

onErrorCaptured((err, instance, info) => {
  hasError.value = true
  errorMessage.value = err.message || '未知错误'
  errorStack.value = err.stack || ''

  console.error(`[ErrorBoundary/${props.componentName}]`, err, info)
  emit('error', { error: err, info, component: props.componentName })

  // 阻止向上传播，由当前边界处理
  return false
})

/** 重新加载当前路由 */
function reload() {
  window.location.reload()
}

/** 重置错误状态（保留组件状态） */
function reset() {
  hasError.value = false
  errorMessage.value = ''
  errorStack.value = ''
  emit('recover')
}

/** 复制错误信息到剪贴板 */
async function copyError() {
  try {
    const text = `[ErrorBoundary/${props.componentName}]\n${errorMessage.value}\n${errorStack.value}`
    await navigator.clipboard.writeText(text)
    message.success('错误信息已复制')
  } catch {
    message.warning('复制失败')
  }
}
</script>

<style scoped>
.error-boundary {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  padding: 48px 24px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 8px;
  border: 1px solid rgba(255, 77, 79, 0.2);
}

.error-boundary__content {
  text-align: center;
  max-width: 480px;
}

.error-boundary__icon {
  font-size: 48px;
  color: #ff4d4f;
  margin-bottom: 16px;
}

.error-boundary__message {
  color: #a0a0a0;
  margin: 12px 0 24px;
}

.error-boundary__actions {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
}

.error-boundary__stack {
  margin-top: 24px;
  text-align: left;
  cursor: pointer;
}

.error-boundary__stack pre {
  font-size: 11px;
  background: rgba(0, 0, 0, 0.3);
  padding: 12px;
  border-radius: 4px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  color: #888;
}
</style>
