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
        { symbol: '000333.SZ', name: '美的集团' }
      ],
      analyzing: false,
      sessionId: null,
      progress: 0,
      progressText: '准备中...',
      analysisLog: [],
      roles: [
        { id: 'tech', name: '技术分析师', icon: '📈', status: 'waiting', report: null },
        { id: 'fundamental', name: '基本面分析师', icon: '📊', status: 'waiting', report: null },
        { id: 'macro', name: '宏观策略师', icon: '🌐', status: 'waiting', report: null },
        { id: 'risk', name: '风险控制官', icon: '⚠️', status: 'waiting', report: null },
        { id: 'manager', name: '资深基金经理', icon: '👨‍💼', status: 'waiting', report: null }
      ],
      finalReport: null
    }
  },
  methods: {
    async startAnalysis() {
      if (!this.selectedSymbol) return

      this.analyzing = true
      this.sessionId = Date.now()
      this.progress = 0
      this.progressText = '准备中...'
      this.analysisLog = []
      this.finalReport = null
      this.roles.forEach(r => {
        r.status = 'waiting'
        r.report = null
      })

      this.addLog('', '🚀', `开始分析 ${this.selectedSymbol}...`)

      // 模拟分析过程
      await this.simulateAnalysis()
    },

    async simulateAnalysis() {
      // 阶段1: 数据收集
      await this.delay(800)
      this.progress = 10
      this.progressText = '收集市场数据...'
      this.addLog('', '📊', '正在收集股票历史数据...')

      await this.delay(600)
      this.progress = 20
      this.addLog('', '📰', '正在获取相关新闻资讯...')

      // 阶段2: 技术分析
      await this.delay(500)
      this.progress = 30
      this.progressText = '技术分析中...'
      this.roles[0].status = 'analyzing'
      this.addLog('tech', '📈', '技术分析师: 正在分析K线形态和技术指标...')

      await this.delay(1200)
      this.roles[0].status = 'done'
      this.roles[0].report = { bullishScore: 65, bearishScore: 35 }
      this.progress = 45
      this.addLog('tech', '📈', '技术分析师: 发现MACD金叉，RSI处于合理区间')

      // 阶段3: 基本面分析
      await this.delay(300)
      this.progress = 50
      this.progressText = '基本面分析中...'
      this.roles[1].status = 'analyzing'
      this.addLog('fundamental', '📊', '基本面分析师: 正在加载财报和估值数据...')

      await this.delay(1000)
      this.roles[1].status = 'done'
      this.roles[1].report = { bullishScore: 55, bearishScore: 45 }
      this.progress = 60
      this.addLog('fundamental', '📊', '基本面分析师: 业绩稳定增长，但估值略高')

      // 阶段4: 宏观分析
      await this.delay(300)
      this.progress = 65
      this.progressText = '宏观分析中...'
      this.roles[2].status = 'analyzing'
      this.addLog('macro', '🌐', '宏观策略师: 分析行业政策和市场情绪...')

      await this.delay(800)
      this.roles[2].status = 'done'
      this.roles[2].report = { bullishScore: 60, bearishScore: 40 }
      this.progress = 75
      this.addLog('macro', '🌐', '宏观策略师: 行业政策利好，市场情绪偏乐观')

      // 阶段5: 风险分析
      await this.delay(300)
      this.progress = 80
      this.progressText = '风险评估中...'
      this.roles[3].status = 'analyzing'
      this.addLog('risk', '⚠️', '风险控制官: 评估潜在风险点...')

      await this.delay(700)
      this.roles[3].status = 'done'
      this.roles[3].report = { bullishScore: 45, bearishScore: 55 }
      this.progress = 90
      this.addLog('risk', '⚠️', '风险控制官: 注意市场波动风险，建议控制仓位')

      // 阶段6: 圆桌辩论
      await this.delay(300)
      this.progress = 92
      this.addLog('', '💬', '圆桌辩论开始 - 各角色交换观点...')
      await this.delay(500)
      this.addLog('', '💬', '技术面看多，基本面审慎，宏观面乐观...')

      // 阶段7: 整合报告
      await this.delay(300)
      this.progress = 95
      this.progressText = '生成最终报告...'
      this.roles[4].status = 'analyzing'
      this.addLog('manager', '👨‍💼', '资深基金经理: 正在整合分析报告...')

      await this.delay(800)
      this.roles[4].status = 'done'
      this.roles[4].report = { bullishScore: 60, bearishScore: 40 }
      this.progress = 100
      this.progressText = '分析完成！'
      this.addLog('', '✅', '分析完成！')

      // 生成最终报告
      this.generateFinalReport()

      this.analyzing = false
    },

    generateFinalReport() {
      const currentPrice = this.selectedSymbol === '600519.SH' ? 1850 : 45
      this.finalReport = {
        overallRating: 'BUY',
        targetPriceRange: { min: currentPrice * 1.05, max: currentPrice * 1.15 },
        stopLoss: currentPrice * 0.92,
        suggestedPosition: 0.2,
        summary: '综合来看，该股票当前具有一定投资价值。技术面显示向好信号，基本面稳健，宏观环境有利。建议轻仓配置，注意控制风险。',
        sections: [
          {
            title: '📈 技术面分析摘要',
            content: 'MACD金叉确认，成交量温和放大，趋势线支撑有效。短期技术形态向好。'
          },
          {
            title: '📊 基本面分析摘要',
            content: '业绩稳定增长，行业地位领先，估值处于合理区间。长期投资价值凸显。'
          },
          {
            title: '💬 辩论记录摘要',
            content: '技术面看多，但基本面提示估值略高。综合权衡后倾向于审慎看多，建议分批建仓。'
          }
        ]
      }
    },

    delay(ms) {
      return new Promise(resolve => setTimeout(resolve, ms))
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
