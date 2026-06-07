<template>
  <div class="ai-signal-bus" v-if="activeSignals.length > 0">
    <div class="ai-signal-bus__header">
      <h3 class="ai-signal-bus__title">🤖 AI 信号总线</h3>
      <span class="ai-signal-bus__count">
        <a-badge :count="activeSignals.length" :overflow-count="99" size="small" />
      </span>
    </div>
    <div class="ai-signal-bus__list">
      <div
        v-for="signal in activeSignals"
        :key="signal.id"
        class="signal-item"
        :class="`signal-item--${signal.type}`"
      >
        <span class="signal-item__icon">{{ signal.typeIcon }}</span>
        <div class="signal-item__content">
          <span class="signal-item__label">{{ signal.label }}</span>
          <span class="signal-item__desc">{{ signal.description }}</span>
        </div>
        <div class="signal-item__meta">
          <span class="signal-item__confidence" :class="confidenceClass(signal.confidence)">
            {{ signal.confidence }}%
          </span>
          <a-button size="small" type="link" @click="navigateTo(signal)" v-if="signal.target">
            查看
          </a-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'AiSignalBus',
  props: {
    signals: { type: Array, default: () => [] },
  },
  computed: {
    activeSignals() {
      return this.signals.filter(s => s.active !== false)
    },
  },
  methods: {
    confidenceClass(confidence) {
      if (!confidence && confidence !== 0) return ''
      if (confidence >= 80) return 'confidence-high'
      if (confidence >= 60) return 'confidence-mid'
      return 'confidence-low'
    },
    navigateTo(signal) {
      if (signal.target) {
        this.$router.push(signal.target)
      }
    },
  },
}
</script>

<style scoped>
.ai-signal-bus {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-default);
  padding: var(--space-16);
}

.ai-signal-bus__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-12);
}

.ai-signal-bus__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.signal-item {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  padding: var(--space-8) var(--space-10);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-4);
  transition: background 0.2s;
}

.signal-item:hover {
  background: var(--bg-subtle);
}

.signal-item__icon {
  font-size: 18px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}

.signal-item--bullish .signal-item__icon {
  background: var(--color-up-bg);
}

.signal-item--bearish .signal-item__icon {
  background: var(--color-down-bg);
}

.signal-item__content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.signal-item__label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.signal-item__desc {
  font-size: 11px;
  color: var(--text-muted);
}

.signal-item__meta {
  display: flex;
  align-items: center;
  gap: var(--space-8);
}

.signal-item__confidence {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: var(--radius-xs);
}

.confidence-high {
  color: var(--color-down);
  background: var(--color-down-bg);
}

.confidence-mid {
  color: var(--signal-watch);
  background: rgba(245, 158, 11, 0.12);
}

.confidence-low {
  color: var(--text-muted);
  background: var(--bg-subtle);
}
</style>
