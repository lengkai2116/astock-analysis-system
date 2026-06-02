<template>
  <a-modal
    :visible="visible"
    :title="modalTitle"
    :footer="null"
    :width="680"
    :destroyOnClose="true"
    @cancel="handleClose"
    class="signal-detail-modal"
  >
    <a-spin :spinning="loading">
      <template v-if="!loading && explanations.length > 0">
        <div class="confidence-header">
          <span class="confidence-label">综合赢率</span>
          <span class="confidence-value" :class="compositeClass">
            {{ compositePercent }}%
          </span>
        </div>

        <div class="strategy-cards">
          <div
            v-for="(exp, idx) in explanations"
            :key="idx"
            class="strategy-card"
          >
            <div class="strategy-card-header">
              <span class="strategy-icon">{{ strategyIcons[exp.strategy] || '📊' }}</span>
              <span class="strategy-name">{{ exp.strategy }}</span>
              <span class="strategy-score">
                {{ strategyScores[exp.strategy] ?? '-' }}
              </span>
            </div>

            <div class="strategy-detail">
              <div class="detail-section">
                <div class="detail-label">AI 解读</div>
                <div class="detail-text">{{ exp.ai_summary }}</div>
              </div>

              <div class="detail-section">
                <div class="detail-label">操作建议</div>
                <div class="detail-text advice-text">{{ exp.ai_advice }}</div>
              </div>

              <div class="detail-section" v-if="exp.risk_tip">
                <div class="detail-label risk-label">风险提示</div>
                <div class="detail-text risk-text">{{ exp.risk_tip }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="composite-section">
          <div class="composite-header">
            <span class="composite-icon">📋</span>
            <span class="composite-title">综合建议</span>
          </div>
          <div class="composite-content">
            {{ compositeAdvice }}
          </div>
        </div>
      </template>

      <template v-if="!loading && explanations.length === 0 && !error">
        <a-empty description="暂无信号数据" />
      </template>

      <template v-if="error">
        <a-alert type="warning" show-icon :message="error" />
        <div class="fallback-section">
          <div class="fallback-hint">
            AI 解读暂时不可用，以下为基于规则的简要分析：
          </div>
          <div v-for="(sig, idx) in signals" :key="idx" class="fallback-item">
            <div class="fallback-strategy">{{ sig.strategy_name }}</div>
            <div class="fallback-score">评分: {{ formatConfidence(sig.confidence) }}</div>
            <div class="fallback-evidence" v-if="sig.evidence?.length">
              {{ sig.evidence.slice(0, 3).join('; ') }}
            </div>
          </div>
        </div>
      </template>
    </a-spin>
  </a-modal>
</template>

<script>
import { explainSignal } from '@/services/aiAnalysisService'

export default {
  name: 'SignalDetailModal',
  props: {
    visible: { type: Boolean, default: false },
    tsCode: { type: String, default: '' },
    stockName: { type: String, default: '' },
    signals: { type: Array, default: () => [] }
  },
  data() {
    return {
      loading: false,
      error: '',
      explanations: [],
      compositeAdvice: '',
      strategyIcons: {
        '筹码主力分析': '📈',
        '缠论策略验证': '📐',
        '因子评分系统': '🧮'
      }
    }
  },
  computed: {
    modalTitle() {
      if (this.tsCode && this.stockName) {
        return `📊 信号详情分析 — ${this.stockName} (${this.tsCode})`
      }
      if (this.tsCode) {
        return `📊 信号详情分析 — ${this.tsCode}`
      }
      return '📊 信号详情分析'
    },
    compositePercent() {
      const scores = this.signals
        .map(s => (s.confidence || 0) * 100)
        .filter(v => v > 0)
      if (scores.length === 0) return 0
      return Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
    },
    compositeClass() {
      const pct = this.compositePercent
      if (pct >= 65) return 'value-high'
      if (pct >= 45) return 'value-mid'
      return 'value-low'
    },
    strategyScores() {
      const scores = {}
      for (const sig of this.signals) {
        const pct = Math.round((sig.confidence || 0) * 100)
        scores[sig.strategy_name] = pct + '%'
      }
      return scores
    }
  },
  watch: {
    visible(val) {
      if (val) {
        this.loadExplanations()
      }
    }
  },
  methods: {
    async loadExplanations() {
      if (!this.tsCode || this.signals.length === 0) {
        this.error = '信号数据不足'
        return
      }

      this.loading = true
      this.error = ''
      this.explanations = []
      this.compositeAdvice = ''

      try {
        const resp = await explainSignal(this.tsCode, this.stockName, this.signals)
        if (resp.success && resp.data) {
          this.explanations = resp.data.explanations || []
          this.compositeAdvice = resp.data.composite_advice || ''
          if (this.explanations.length === 0) {
            this.error = 'AI 解读返回为空'
          }
        } else {
          this.error = resp.error || '获取 AI 解读失败'
        }
      } catch (e) {
        this.error = e.message || '网络请求失败，已切换到离线模式'
      } finally {
        this.loading = false
      }
    },
    formatConfidence(val) {
      return val != null ? Math.round(val * 100) + '%' : '-'
    },
    handleClose() {
      this.$emit('update:visible', false)
    }
  }
}
</script>

<style scoped>
.signal-detail-modal :deep(.ant-modal-header) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.signal-detail-modal :deep(.ant-modal-content) {
  background: #1e293b;
  color: #e2e8f0;
}
.signal-detail-modal :deep(.ant-modal-title) {
  color: #f1f5f9;
  font-size: 16px;
}
.signal-detail-modal :deep(.ant-modal-close) {
  color: #64748b;
}
.signal-detail-modal :deep(.ant-modal-body) {
  max-height: 70vh;
  overflow-y: auto;
}

.confidence-header {
  text-align: center;
  padding: 16px 0 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 20px;
}
.confidence-label {
  display: block;
  font-size: 13px;
  color: #64748b;
  margin-bottom: 4px;
}
.confidence-value {
  font-size: 32px;
  font-weight: 700;
}
.value-high { color: #52c41a; }
.value-mid { color: #1890ff; }
.value-low { color: #faad14; }

.strategy-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.strategy-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  overflow: hidden;
}

.strategy-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.strategy-icon {
  font-size: 18px;
}
.strategy-name {
  font-weight: 600;
  color: #f1f5f9;
  font-size: 14px;
}
.strategy-score {
  margin-left: auto;
  font-weight: 700;
  font-size: 14px;
  color: #52c41a;
}

.strategy-detail {
  padding: 12px 16px;
}

.detail-section {
  margin-bottom: 12px;
}
.detail-section:last-child {
  margin-bottom: 0;
}
.detail-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
  margin-bottom: 4px;
}
.detail-text {
  font-size: 13px;
  color: #e2e8f0;
  line-height: 1.6;
}
.advice-text {
  color: #52c41a;
}
.risk-label {
  color: #faad14;
}
.risk-text {
  color: #f59e0b;
}

.composite-section {
  background: linear-gradient(135deg, rgba(82, 196, 26, 0.08), rgba(24, 144, 255, 0.08));
  border: 1px solid rgba(82, 196, 26, 0.2);
  border-radius: 8px;
  padding: 16px;
}
.composite-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.composite-icon {
  font-size: 16px;
}
.composite-title {
  font-weight: 700;
  color: #f1f5f9;
  font-size: 14px;
}
.composite-content {
  font-size: 13px;
  color: #e2e8f0;
  line-height: 1.6;
}

.fallback-section {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fallback-hint {
  font-size: 13px;
  color: #94a3b8;
  padding: 8px 12px;
  background: rgba(250, 173, 20, 0.08);
  border-radius: 6px;
}
.fallback-item {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  padding: 12px;
}
.fallback-strategy {
  font-weight: 600;
  color: #f1f5f9;
  font-size: 14px;
  margin-bottom: 4px;
}
.fallback-score {
  color: #52c41a;
  font-size: 13px;
  margin-bottom: 4px;
}
.fallback-evidence {
  color: #94a3b8;
  font-size: 12px;
}
</style>
