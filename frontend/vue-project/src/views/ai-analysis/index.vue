<template>
  <div class="ai-analysis-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">🤖 AI分析助手</h1>
      <div class="header-actions">
        <a-select
          v-model="selectedSymbol"
          style="width: 200px"
          placeholder="选择股票"
        >
          <a-select-option
            v-for="s in watchlist"
            :key="s.symbol"
            :value="s.symbol"
          >
            {{ s.symbol }} {{ s.name }}
          </a-select-option>
        </a-select>
        <a-button
          type="primary"
          style="margin-left: 12px"
          :loading="analyzing"
          @click="startAnalysis"
          :disabled="!selectedSymbol"
        >
          开始分析
        </a-button>
      </div>
    </div>

    <div v-if="!sessionId" class="welcome-section">
      <a-empty description="选择股票开始AI投研分析" />
    </div>

    <div v-else class="analysis-container">
      <!-- 进度条 -->
      <div v-if="analyzing || progress < 100" class="progress-section">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <span class="progress-text">{{ progressText }}</span>
      </div>

      <div class="main-content">
        <!-- 左侧：分析日志 -->
        <div class="log-panel">
          <div class="panel-title">⏱️ 分析日志</div>
          <div class="log-content">
            <div
              v-for="(log, idx) in analysisLog"
              :key="idx"
              class="log-item"
              :class="log.type"
            >
              <span class="log-time">{{ formatTime(log.timestamp) }}</span>
              <span class="log-icon">{{ log.icon }}</span>
              <span class="log-content">{{ log.content }}</span>
            </div>
          </div>
        </div>

        <!-- 中间：角色卡片 -->
        <div class="roles-panel">
          <div class="panel-title">👨‍👩‍👧‍👦 角色团队</div>
          <div class="roles-grid">
            <div
              v-for="role in roles"
              :key="role.id"
              class="role-card"
              :class="role.status"
            >
              <div class="role-icon">{{ role.icon }}</div>
              <div class="role-name">{{ role.name }}</div>
              <div class="role-status">
                <a-tag v-if="role.status === 'done'" color="green">完成</a-tag>
                <a-spin v-else-if="role.status === 'analyzing'" size="small" />
                <span v-else class="waiting">等待中...</span>
              </div>
              <div v-if="role.report" class="role-score">
                <span class="bullish">看多 {{ role.report.bullishScore }}%</span>
                <span class="bearish">看空 {{ role.report.bearishScore }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右侧：最终报告 -->
        <div class="report-panel">
          <div class="panel-title">📋 最终投研报告</div>
          <div v-if="finalReport" class="report-content">
            <div class="rating-badge">
              {{ getRatingLabel(finalReport.overallRating) }}
            </div>

            <div class="report-section">
              <div class="section-title">🎯 目标价位</div>
              <div class="price-range">
                <span class="price-min">¥{{ finalReport.targetPriceRange.min.toFixed(2) }}</span>
                <span class="price-divider">-</span>
                <span class="price-max">¥{{ finalReport.targetPriceRange.max.toFixed(2) }}</span>
              </div>
            </div>

            <div class="report-section">
              <div class="section-title">⚠️ 止损位置</div>
              <div class="stop-loss">¥{{ finalReport.stopLoss.toFixed(2) }}</div>
            </div>

            <div class="report-section">
              <div class="section-title">💰 建议仓位</div>
              <div class="position">{{ (finalReport.suggestedPosition * 100).toFixed(0) }}%</div>
            </div>

            <a-divider />

            <div class="summary-section">
              {{ finalReport.summary }}
            </div>

            <div v-for="section in finalReport.sections" :key="section.title" class="report-section">
              <div class="section-title">{{ section.title }}</div>
              <div class="section-content">{{ section.content }}</div>
            </div>

            <a-button type="primary" block style="margin-top: 16px">
              📄 导出完整报告
            </a-button>
          </div>
          <div v-else class="report-placeholder">
            <FileTextOutlined style="font-size: 48px; color: var(--text-muted)" />
            <div>等待分析完成...</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { FileTextOutlined } from '@ant-design/icons-vue'
import { startAnalysis, getProgress, getFinalReport } from '@/services/aiAnalysisService'

export default {
  name: 'AIAnalysisPage',
  data() {
    return {
      selectedSymbol: '',
      watchlist: [
        { symbol: '600519.SH', name: '贵州茅台' },
        { symbol: '000001.SZ', name: '平安银行' },
        { symbol: '600000.SH', name: '浦发银行' },
        { symbol: '601318.SH', name: '中国平安' },
        { symbol: '000333.SZ', name: '美的集团' },
        { symbol: '002415.SZ', name: '海康威视' },
        { symbol: '300750.SZ', name: '宁德时代' }
      ],
      analyzing: false,
      analysisId: null,
      progress: 0,
      progressText: '准备中...',
      analysisLog: [],
      pollTimer: null,
      roles: [
        { id: 'technical', name: '技术分析师', icon: '📈', status: 'waiting', report: null },
        { id: 'fundamental', name: '基本面分析师', icon: '📊', status: 'waiting', report: null },
        { id: 'macro', name: '宏观策略师', icon: '🌐', status: 'waiting', report: null },
        { id: 'risk', name: '风险控制官', icon: '⚠️', status: 'waiting', report: null },
        { id: 'fund_manager', name: '资深基金经理', icon: '👨‍💼', status: 'waiting', report: null }
      ],
      finalReport: null
    }
  },
  beforeUnmount() {
    this.stopPolling()
  },
  methods: {
    async startAnalysis() {
      if (!this.selectedSymbol) return

      this.analyzing = true
      this.analysisId = null
      this.progress = 0
      this.progressText = '准备中...'
      this.analysisLog = []
      this.finalReport = null
      this.roles.forEach(r => {
        r.status = 'waiting'
        r.report = null
      })

      this.addLog('', '🚀', `开始分析 ${this.selectedSymbol}...`)

      try {
        const res = await startAnalysis(this.selectedSymbol)
        if (res.success && res.data) {
          this.analysisId = res.data.analysis_id
          this.addLog('', '📡', '分析请求已提交，等待结果...')
          this.startPolling()
        } else {
          this.addLog('error', '❌', '启动分析失败')
          this.analyzing = false
        }
      } catch (e) {
        this.addLog('error', '❌', `启动分析失败: ${e.message}`)
        this.analyzing = false
      }
    },

    startPolling() {
      this.stopPolling()
      this.pollTimer = setInterval(() => this.pollProgress(), 1500)
    },

    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },

    async pollProgress() {
      if (!this.analysisId) return

      try {
        const res = await getProgress(this.analysisId)
        if (!res.success || !res.data) return

        const data = res.data
        this.progress = data.progress || 0
        this.progressText = data.progress_text || ''

        // 更新角色状态
        if (data.analysts) {
          for (const role of this.roles) {
            const analystData = data.analysts[role.id]
            if (analystData) {
              const isCurrent = data.current_role === role.id
              role.status = data.status === 'completed' ? 'done' : (isCurrent ? 'analyzing' : 'done')
              if (analystData.bullishScore !== undefined) {
                role.report = {
                  bullishScore: analystData.bullishScore,
                  bearishScore: analystData.bearishScore
                }
              }
            }
          }
        }

        // 更新日志
        if (data.logs && data.logs.length > this.analysisLog.length) {
          for (let i = this.analysisLog.length; i < data.logs.length; i++) {
            const log = data.logs[i]
            this.analysisLog.push({
              role: log.role || '',
              icon: log.icon || '•',
              content: log.content || '',
              timestamp: new Date(log.timestamp).getTime(),
              type: 'normal'
            })
          }
        }

        // 检查是否完成
        if (data.status === 'completed') {
          this.stopPolling()
          this.progress = 100
          this.progressText = '分析完成！'
          this.addLog('', '✅', '分析完成！')
          await this.loadFinalReport()
          this.analyzing = false
        } else if (data.status === 'failed') {
          this.stopPolling()
          this.addLog('error', '❌', '分析失败')
          this.analyzing = false
        }
      } catch (e) {
        console.error('轮询进度失败:', e)
      }
    },

    async loadFinalReport() {
      if (!this.analysisId) return

      try {
        const res = await getFinalReport(this.analysisId)
        if (res.success && res.data && res.data.report) {
          this.finalReport = res.data.report
          this.addLog('', '📋', '最终报告已生成')
        }
      } catch (e) {
        console.error('获取最终报告失败:', e)
      }
    },

    addLog(role, icon, content) {
      this.analysisLog.push({
        role,
        icon,
        content,
        timestamp: Date.now(),
        type: role === 'error' ? 'error' : 'normal'
      })
    },

    formatTime(timestamp) {
      const date = new Date(timestamp)
      return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
    },

    getRatingLabel(rating) {
      const labels = {
        'STRONGLY_BUY': '强烈看多',
        'BUY': '看多',
        'HOLD': '中性',
        'SELL': '看空',
        'STRONGLY_SELL': '强烈看空'
      }
      return labels[rating] || rating
    }
  }
}
</script>

<style scoped>
.ai-analysis-page {
  padding: 16px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #2a2a2a;
}

.page-title {
  color: var(--text-primary);
  margin: 0;
  font-size: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
}

.welcome-section {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.analysis-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.progress-section {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: rgba(255,255,255,0.1);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), var(--color-accent));
  transition: width 0.3s ease;
}

.progress-text {
  color: var(--text-secondary);
  font-size: 12px;
}

.main-content {
  flex: 1;
  display: grid;
  grid-template-columns: 300px 280px 1fr;
  gap: 16px;
  min-height: 0;
}

.log-panel, .roles-panel, .report-panel {
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 16px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.panel-title {
  color: var(--text-primary);
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
}

.log-content {
  flex: 1;
  overflow-y: auto;
  font-family: monospace;
}

.log-item {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}

.log-time {
  color: var(--text-muted);
  min-width: 70px;
}

.log-icon {
  font-size: 14px;
}

.log-content {
  flex: 1;
  color: var(--text-secondary);
}

.roles-grid {
  display: grid;
  gap: 12px;
}

.role-card {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid transparent;
  transition: all 0.2s ease;
}

.role-card.analyzing {
  border-color: var(--color-primary);
  background: rgba(59, 130, 246, 0.1);
}

.role-card.done {
  border-color: var(--color-up);
}

.role-icon {
  font-size: 24px;
  margin-bottom: 4px;
}

.role-name {
  color: var(--text-primary);
  font-weight: 500;
  font-size: 13px;
}

.role-score {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}

.role-score .bullish {
  color: var(--color-up);
}

.role-score .bearish {
  color: var(--color-down);
}

.waiting {
  color: var(--text-muted);
  font-size: 12px;
}

.report-content {
  flex: 1;
  overflow-y: auto;
}

.rating-badge {
  display: inline-block;
  padding: 8px 24px;
  background: linear-gradient(135deg, var(--color-up), #dc2626);
  color: white;
  font-weight: 600;
  border-radius: 8px;
  margin-bottom: 16px;
}

.report-section {
  margin-bottom: 12px;
}

.section-title {
  color: var(--text-secondary);
  font-size: 12px;
  margin-bottom: 4px;
}

.price-range {
  display: flex;
  gap: 8px;
  align-items: center;
}

.price-min, .price-max {
  color: var(--text-primary);
  font-weight: 500;
  font-size: 16px;
}

.price-divider {
  color: var(--text-muted);
}

.stop-loss, .position {
  color: var(--text-primary);
  font-weight: 500;
  font-size: 14px;
}

.summary-section {
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 16px;
}

.report-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
}
</style>
