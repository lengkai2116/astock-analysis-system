<template>
  <div class="strategy-signal-panel">
    <a-card
      size="small"
      :bordered="false"
    >
      <template #title>
        <div class="panel-header">
          <span
            class="signal-badge"
            :class="signalClass"
          >
            {{ signalText }}
          </span>
          <span class="strategy-name">{{ strategyName }}</span>
          <span class="signal-date">{{ formatDate(signalData.signal_date) }}</span>
        </div>
      </template>

      <div class="signal-content">
        <div class="confidence-section">
          <div class="section-label">
            <SafetyCertificateFilled />
            赢率
          </div>
          <div class="confidence-bar">
            <a-progress
              :percent="confidencePercent"
              :status="confidenceStatus"
              :stroke-color="confidenceColor"
              :show-info="false"
              :style="{ cursor: 'pointer' }"
              @click="handleShowDetail"
            />
            <span
              class="confidence-value clickable"
              title="点击查看详情"
              @click="handleShowDetail"
            >
              {{ confidenceText }}
            </span>
          </div>
        </div>

        <div class="detail-link-row">
          <a
            class="detail-link"
            @click="handleShowDetail"
          >查看详情 →</a>
        </div>

        <div class="price-section">
          <div class="section-label">
            <i class="anticon anticon-money-collect" />
            价格区间
          </div>
          <div class="price-grid">
            <div class="price-item entry-zone">
              <span class="price-label">入场区间</span>
              <span class="price-value">
                {{ formatPrice(signalData.entry_zone) }}
              </span>
            </div>
            <div class="price-item risk-line">
              <span class="price-label">止损线</span>
              <span class="price-value danger">
                {{ formatPrice(signalData.risk_line) }}
              </span>
            </div>
            <div class="price-item target-zone">
              <span class="price-label">目标区间</span>
              <span class="price-value success">
                {{ formatPrice(signalData.target_zone) }}
              </span>
            </div>
          </div>
        </div>

        <div class="position-section">
          <div class="section-label">
            <i class="anticon anticon-swap" />
            仓位建议
          </div>
          <div class="position-content">
            <a-tag :color="positionColor">
              {{ signalData.position_suggestion || '未提供' }}
            </a-tag>
            <span class="holding-period">
              持有周期: {{ signalData.holding_period || '未指定' }}
            </span>
          </div>
        </div>

        <div
          v-if="signalData.evidence && signalData.evidence.length > 0"
          class="evidence-section"
        >
          <div class="section-label">
            <i class="anticon anticon-branches" />
            证据链
          </div>
          <a-list
            size="small"
            :data-source="signalData.evidence"
            class="evidence-list"
          >
            <template #renderItem="{ item }">
              <a-list-item>
                <CheckCircleFilled class="evidence-icon" />
                <span>{{ item }}</span>
              </a-list-item>
            </template>
          </a-list>
        </div>

        <div
          v-if="signalData.risk_notes && signalData.risk_notes.length > 0"
          class="risk-section"
        >
          <a-alert
            type="warning"
            show-icon
          >
            <template #message>
              <div class="risk-title">
                <i class="anticon anticon-warning" />
                风险提示
              </div>
            </template>
            <template #description>
              <ul class="risk-list">
                <li
                  v-for="(risk, index) in signalData.risk_notes"
                  :key="index"
                >
                  {{ risk }}
                </li>
              </ul>
            </template>
          </a-alert>
        </div>

        <div class="action-section">
          <a-button
            type="primary"
            size="small"
            @click="handleViewDetail"
          >
            完整报告
          </a-button>
          <a-button
            size="small"
            @click="handleShowDetail"
          >
            赢率详情
          </a-button>
          <a-button
            size="small"
            @click="handleBacktest"
          >
            策略回测
          </a-button>
        </div>
      </div>
    </a-card>
  </div>
</template>

<script>
import { CheckCircleFilled, SafetyCertificateFilled } from '@ant-design/icons-vue'
export default {
  name: 'StrategySignalPanel',
  components: {
    CheckCircleFilled,
    SafetyCertificateFilled
  },
  props: {
    signalData: {
      type: Object,
      required: true,
      default: () => ({
        ts_code: '',
        stock_name: '',
        strategy_name: '',
        signal: 'neutral',
        signal_date: '',
        confidence: 0,
        entry_zone: null,
        risk_line: null,
        target_zone: null,
        position_suggestion: '',
        holding_period: '',
        evidence: [],
        risk_notes: []
      })
    },
    stockName: {
      type: String,
      default: ''
    }
  },
  computed: {
    strategyName() {
      return this.signalData.strategy_name || '策略信号'
    },

    signalText() {
      const signalMap = {
        bullish: '买入信号',
        bearish: '卖出信号',
        neutral: '中性',
        watch: '观望'
      }
      return signalMap[this.signalData.signal] || '未知'
    },

    signalClass() {
      return `signal-${this.signalData.signal}`
    },

    confidencePercent() {
      return Math.round((this.signalData.confidence || 0) * 100)
    },

    confidenceText() {
      return `${this.confidencePercent}%`
    },

    confidenceStatus() {
      if (this.confidencePercent >= 70) return 'success'
      if (this.confidencePercent >= 40) return 'normal'
      return 'exception'
    },

    confidenceColor() {
      if (this.confidencePercent >= 70) return '#52c41a'
      if (this.confidencePercent >= 40) return '#1890ff'
      return '#ff4d4f'
    },

    positionColor() {
      const pos = this.signalData.position_suggestion
      if (!pos) return 'default'
      if (pos.includes('重仓')) return 'red'
      if (pos.includes('半仓')) return 'orange'
      if (pos.includes('轻仓')) return 'blue'
      return 'default'
    }
  },
  methods: {
    formatDate(date) {
      if (!date) return ''
      if (typeof date === 'string') return date
      try {
        return date instanceof Date ? date.toLocaleDateString('zh-CN') : String(date)
      } catch {
        return String(date)
      }
    },

    formatPrice(price) {
      if (price === null || price === undefined) return '未提供'
      if (Array.isArray(price)) {
        const valid = price.filter(p => p != null)
        if (valid.length >= 2) return `${valid[0]} ~ ${valid[1]}`
        if (valid.length === 1) return String(valid[0])
        return '未提供'
      }
      return String(price)
    },

    handleViewDetail() {
      this.$emit('view-detail', this.signalData)
    },

    handleBacktest() {
      this.$emit('backtest', this.signalData)
    },

    handleShowDetail() {
      const name = this.stockName || this.signalData.stock_name || ''
      this.$emit('show-detail', {
        ts_code: this.signalData.ts_code,
        stock_name: name,
        signals: [this.signalData]
      })
    }
  }
}
</script>

<style scoped>
.strategy-signal-panel {
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.signal-badge {
  padding: 4px 12px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 14px;
}

.signal-bullish {
  background: rgba(82, 196, 26, 0.2);
  color: #52c41a;
}

.signal-bearish {
  background: rgba(255, 77, 79, 0.2);
  color: #ff4d4f;
}

.signal-neutral {
  background: rgba(24, 144, 255, 0.2);
  color: #1890ff;
}

.signal-watch {
  background: rgba(250, 173, 20, 0.2);
  color: #faad14;
}

.strategy-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.signal-date {
  margin-left: auto;
  font-size: 13px;
  color: var(--text-muted, #64748b);
}

.signal-content {
  padding: 16px 0;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary, #cbd5e1);
}

.confidence-section {
  margin-bottom: 8px;
}

.confidence-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.confidence-bar :deep(.ant-progress) {
  flex: 1;
}

.confidence-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  min-width: 50px;
  text-align: right;
}

.confidence-value.clickable {
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 3px;
}

.confidence-value.clickable:hover {
  color: #1890ff;
}

.detail-link-row {
  text-align: right;
  margin-bottom: 16px;
}

.detail-link {
  font-size: 13px;
  color: #1890ff;
  cursor: pointer;
  text-decoration: none;
}

.detail-link:hover {
  color: #40a9ff;
  text-decoration: underline;
}

.price-section {
  margin-bottom: 20px;
}

.price-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.price-item {
  background: rgba(255, 255, 255, 0.05);
  padding: 12px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.price-label {
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.price-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.price-value.danger {
  color: #ff4d4f;
}

.price-value.success {
  color: #52c41a;
}

.position-section {
  margin-bottom: 20px;
}

.position-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.holding-period {
  font-size: 13px;
  color: var(--text-secondary, #cbd5e1);
}

.evidence-section {
  margin-bottom: 20px;
}

.evidence-list {
  background: rgba(255, 255, 255, 0.02);
  border-radius: 6px;
}

.evidence-list :deep(.ant-list-item) {
  border-bottom: none;
  padding: 8px 12px;
}

.evidence-icon {
  color: #52c41a;
  margin-right: 8px;
}

.risk-section {
  margin-bottom: 20px;
}

.risk-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.risk-list {
  margin: 8px 0 0 0;
  padding-left: 20px;
}

.risk-list li {
  margin-bottom: 4px;
  color: var(--text-secondary, #cbd5e1);
}

.action-section {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
