<template>
  <div
    v-if="status"
    class="data-source-bar"
    :class="`data-source-bar--${status.active_status}`"
  >
    <span class="data-source-bar__dot" />
    <span class="data-source-bar__label">
      {{ status.active_source }}
    </span>
    <span
      v-if="status.status !== 'normal'"
      class="data-source-bar__warn"
    >
      {{ statusText }}
    </span>
  </div>
</template>

<script>
export default {
  name: 'DataSourceStatusBar',
  props: {
    status: { type: Object, default: null },
  },
  computed: {
    statusText() {
      const map = {
        normal: '正常',
        degraded: '延迟',
        fallback: '备用源',
        unavailable: '不可用',
      }
      return map[this.status?.status] || this.status?.status
    },
  },
}
</script>

<style scoped>
.data-source-bar {
  position: fixed;
  bottom: 0;
  right: 16px;
  display: flex;
  align-items: center;
  gap: var(--space-6, 6px);
  padding: 4px 12px;
  font-size: 11px;
  border-radius: var(--radius-sm, 6px) var(--radius-sm, 6px) 0 0;
  background: var(--data-source-bar-bg);
  backdrop-filter: blur(var(--data-source-bar-blur));
  -webkit-backdrop-filter: blur(var(--data-source-bar-blur));
  z-index: 1000;
  transition: background 0.3s ease;
}

.data-source-bar__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

.data-source-bar--normal .data-source-bar__dot {
  background: #52c41a;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.data-source-bar--degraded .data-source-bar__dot {
  background: #faad14;
}

.data-source-bar--fallback .data-source-bar__dot,
.data-source-bar--unavailable .data-source-bar__dot {
  background: #ff4d4f;
}

.data-source-bar__label {
  color: var(--text-secondary);
}

.data-source-bar__warn {
  color: #faad14;
  font-weight: 500;
}
</style>
