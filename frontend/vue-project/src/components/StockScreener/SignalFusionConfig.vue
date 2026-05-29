<template>
  <div class="signal-fusion-config theme-dark">
    <div class="config-header">
      <span class="config-title">信号融合配置</span>
    </div>

    <div class="config-body">
      <!-- 策略权重 -->
      <div class="config-section">
        <div class="section-title">策略权重</div>
        <div class="weight-sliders">
          <div class="weight-item" v-for="item in strategies" :key="item.key">
            <div class="weight-label">
              <span>{{ item.label }}</span>
              <span class="weight-value">{{ (weights[item.key] * 100).toFixed(0) }}%</span>
            </div>
            <a-slider
              :value="weights[item.key]"
              :min="0"
              :max="1"
              :step="0.05"
              @change="val => onWeightChange(item.key, val)"
            />
          </div>
        </div>
        <div class="weight-sum">
          总和: <span :class="weightSum === 1 ? 'valid' : 'invalid'">{{ (weightSum * 100).toFixed(0) }}%</span>
        </div>
      </div>

      <!-- 阶段加分 -->
      <div class="config-section">
        <div class="section-title">阶段额外加分</div>
        <div class="bonus-list">
          <div class="bonus-item">
            <a-checkbox :checked="phaseBonus.building > 0" @change="e => togglePhaseBonus('building', e.target.checked, 2)">
              建仓期
            </a-checkbox>
            <a-input-number
              :value="phaseBonus.building"
              :min="0"
              :max="5"
              :step="0.5"
              size="small"
              style="width: 60px"
              @change="val => phaseBonus.building = val"
            />
          </div>
          <div class="bonus-item">
            <a-checkbox :checked="phaseBonus.washing > 0" @change="e => togglePhaseBonus('washing', e.target.checked, 1)">
              洗盘末期
            </a-checkbox>
            <a-input-number
              :value="phaseBonus.washing"
              :min="0"
              :max="5"
              :step="0.5"
              size="small"
              style="width: 60px"
              @change="val => phaseBonus.washing = val"
            />
          </div>
        </div>
      </div>

      <!-- 当前选中股票评分预览 -->
      <div class="config-section" v-if="selectedStock">
        <div class="section-title">评分预览</div>
        <div class="score-preview">
          <div class="score-stock">{{ selectedStock.name || selectedStock.symbol }}</div>
          <div class="score-breakdown">
            <div class="score-row" v-for="(val, key) in scoreBreakdown" :key="key">
              <span class="score-label">{{ key }}</span>
              <span class="score-bar-bg">
                <span class="score-bar-fill" :style="{ width: (val * 100) + '%' }"></span>
              </span>
              <span class="score-val">{{ (val * 100).toFixed(0) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="config-footer">
      <a-button type="primary" size="small" @click="saveConfig" :loading="saving">保存配置</a-button>
      <a-button size="small" @click="resetConfig" style="margin-left: 8px">重置</a-button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'SignalFusionConfig',
  props: {
    value: { type: Object, default: null },
    selectedStock: { type: Object, default: null }
  },
  data() {
    return {
      strategies: [
        { key: 'chip', label: '筹码策略' },
        { key: 'chanlun', label: '缠论策略' },
        { key: 'factor', label: '因子策略' }
      ],
      weights: { chip: 0.4, chanlun: 0.3, factor: 0.3 },
      phaseBonus: { building: 2, washing: 1 },
      saving: false
    }
  },
  computed: {
    weightSum() {
      return Object.values(this.weights).reduce((a, b) => a + b, 0)
    },
    scoreBreakdown() {
      if (!this.selectedStock) return {}
      const s = this.selectedStock
      return {
        'ASR': s.asr_score || (s.asr || 0) * 0.3,
        '集中度': s.concentration_score || (1 - (s.concentration || 0)) * 0.2,
        '获利率': s.profit_score || (s.profit_ratio !== undefined ? (1 - s.profit_ratio) * 0.2 : 0.1),
        '成交量': s.volume_score || (s.volume_ratio || 0.5) * 0.15,
        'RSI': s.rsi_score || (s.rsi ? (s.rsi > 55 ? 0.1 : 0.15) : 0.075),
        '阶段加分': (this.phaseBonus.building + this.phaseBonus.washing) / 100
      }
    }
  },
  watch: {
    value: {
      handler(v) {
        if (v) {
          if (v.weights) this.weights = { ...this.weights, ...v.weights }
          if (v.phase_bonus) this.phaseBonus = { ...this.phaseBonus, ...v.phase_bonus }
        }
      },
      immediate: true
    }
  },
  methods: {
    onWeightChange(key, val) {
      const old = this.weights[key]
      const diff = val - old
      this.weights[key] = Math.round(val * 100) / 100

      // 自动调节其他权重保持总和 = 1
      const others = Object.keys(this.weights).filter(k => k !== key)
      const totalOthers = others.reduce((s, k) => s + this.weights[k], 0)
      if (totalOthers > 0) {
        others.forEach(k => {
          this.weights[k] = Math.max(0, Math.min(1,
            Math.round((this.weights[k] - diff * this.weights[k] / totalOthers) * 100) / 100
          ))
        })
      }
    },

    togglePhaseBonus(key, enabled, defaultVal) {
      this.phaseBonus[key] = enabled ? defaultVal : 0
    },

    async saveConfig() {
      this.saving = true
      this.$emit('save', {
        weights: { ...this.weights },
        phase_bonus: { ...this.phaseBonus }
      })
      this.saving = false
    },

    resetConfig() {
      this.weights = { chip: 0.4, chanlun: 0.3, factor: 0.3 }
      this.phaseBonus = { building: 2, washing: 1 }
      this.$emit('reset')
    }
  }
}
</script>

<style scoped>
.signal-fusion-config {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1e293b;
  border-radius: 8px;
  overflow: hidden;
}

.config-header {
  padding: 12px 16px;
  background: #0f172a;
  border-bottom: 1px solid #2a2a2a;
}

.config-title {
  font-weight: 600;
  color: #f1f5f9;
  font-size: 14px;
}

.config-body {
  flex: 1;
  padding: 12px 16px;
  overflow-y: auto;
}

.config-section {
  margin-bottom: 20px;
}

.section-title {
  font-size: 11px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 10px;
}

.weight-item {
  margin-bottom: 12px;
}

.weight-label {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #cbd5e1;
  margin-bottom: 4px;
}

.weight-value {
  color: #3b82f6;
  font-weight: 600;
}

.weight-sum {
  text-align: right;
  font-size: 12px;
  color: #64748b;
}

.weight-sum .valid { color: #22c55e; }
.weight-sum .invalid { color: #ef4444; }

.bonus-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
}

.score-preview {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  padding: 10px;
}

.score-stock {
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 8px;
}

.score-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.score-label {
  width: 50px;
  font-size: 11px;
  color: #94a3b8;
  flex-shrink: 0;
}

.score-bar-bg {
  flex: 1;
  height: 6px;
  background: #334155;
  border-radius: 3px;
  overflow: hidden;
}

.score-bar-fill {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #22c55e);
  border-radius: 3px;
  transition: width 0.3s;
}

.score-val {
  width: 24px;
  font-size: 11px;
  color: #94a3b8;
  text-align: right;
}

.config-footer {
  padding: 10px 16px;
  border-top: 1px solid #2a2a2a;
  display: flex;
  justify-content: center;
}
</style>
