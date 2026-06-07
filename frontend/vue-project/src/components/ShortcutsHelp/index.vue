<template>
  <div class="shortcuts-overlay" @click.self="$emit('close')">
    <div class="shortcuts-panel">
      <div class="shortcuts-header">
        <h3>⌨️ 快捷键</h3>
        <button class="shortcuts-close" @click="$emit('close')">✕</button>
      </div>
      <div class="shortcuts-grid">
        <div v-for="s in shortcuts" :key="s.id" class="shortcut-row">
          <span class="shortcut-desc">{{ s.label }}</span>
          <span class="shortcut-keys">
            <span v-for="(key, i) in getBinding(s.id)" :key="i" class="shortcut-key">
              {{ key === 'Escape' ? 'Esc' : key === '/' ? '/' : key.length === 1 ? key.toUpperCase() : key }}
            </span>
          </span>
        </div>
      </div>
      <div class="shortcuts-footer">
        <span class="shortcuts-hint">按 <span class="shortcut-key">?</span> 打开/关闭此面板</span>
      </div>
    </div>
  </div>
</template>

<script>
import { useShortcutStore } from '@/stores/shortcuts'

export default {
  name: 'ShortcutsHelp',
  emits: ['close'],
  setup() {
    const shortcutStore = useShortcutStore()
    return { shortcuts: shortcutStore.shortcuts, getBinding: shortcutStore.getBinding }
  },
  mounted() {
    this._keyHandler = (e) => {
      if (e.key === 'Escape' || e.key === '?') {
        this.$emit('close')
      }
    }
    window.addEventListener('keydown', this._keyHandler)
  },
  beforeUnmount() {
    window.removeEventListener('keydown', this._keyHandler)
  },
}
</script>

<style scoped>
.shortcuts-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
}

.shortcuts-panel {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-dropdown);
  padding: var(--space-24);
  max-width: 560px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
}

.shortcuts-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-20);
}

.shortcuts-header h3 {
  font-size: 18px;
  color: var(--text-primary);
  margin: 0;
}

.shortcuts-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-xs);
}

.shortcuts-close:hover {
  background: var(--bg-subtle);
  color: var(--text-primary);
}

.shortcuts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-6);
}

.shortcut-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-6) var(--space-8);
  border-radius: var(--radius-sm);
}

.shortcut-row:hover {
  background: var(--bg-subtle);
}

.shortcut-desc {
  color: var(--text-secondary);
  font-size: 13px;
}

.shortcut-keys {
  display: flex;
  gap: 4px;
}

.shortcut-key {
  padding: 2px 6px;
  background: var(--bg-muted);
  border-radius: var(--radius-xs);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.shortcuts-footer {
  margin-top: var(--space-16);
  padding-top: var(--space-12);
  border-top: 1px solid var(--border-default);
  text-align: center;
}

.shortcuts-hint {
  color: var(--text-muted);
  font-size: 12px;
}

.shortcuts-hint .shortcut-key {
  display: inline;
  padding: 1px 5px;
  font-size: 11px;
}
</style>
