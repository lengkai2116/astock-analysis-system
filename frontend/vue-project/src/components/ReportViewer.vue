<template>
  <div class="report-viewer-container">
    <div class="viewer-header">
      <div class="header-left">
        <h2 class="viewer-title">
          {{ reportTitle }}
        </h2>
        <div class="report-meta">
          <a-tag :color="getReportTypeColor(reportType)">
            {{ getReportTypeLabel(reportType) }}
          </a-tag>
          <span class="meta-separator">|</span>
          <span class="meta-item">{{ tsCode }}</span>
          <span class="meta-separator">|</span>
          <span class="meta-item">{{ generatedAt }}</span>
        </div>
      </div>
      
      <div class="header-right">
        <a-space>
          <a-select
            v-model="selectedFormat"
            style="width: 120px"
            @change="handleFormatChange"
          >
            <a-select-option value="markdown">
              Markdown
            </a-select-option>
            <a-select-option value="html">
              HTML
            </a-select-option>
            <a-select-option value="json">
              JSON
            </a-select-option>
          </a-select>
          
          <a-button
            :loading="exporting"
            @click="handleExport"
          >
            <DownloadOutlined />
            导出报告
          </a-button>
          
          <a-button @click="handlePrint">
            <PrinterOutlined />
            打印
          </a-button>
          
          <a-button
            :loading="loading"
            @click="handleRefresh"
          >
            <ReloadOutlined />
            刷新
          </a-button>
        </a-space>
      </div>
    </div>

    <div
      v-if="loading"
      class="loading-container"
    >
      <a-spin
        size="large"
        tip="加载报告中..."
      />
    </div>

    <div
      v-else-if="error"
      class="error-container"
    >
      <a-alert
        message="加载失败"
        :description="error"
        type="error"
        show-icon
      />
      <a-button
        type="primary"
        style="margin-top: 16px"
        @click="handleRefresh"
      >
        重试
      </a-button>
    </div>

    <div
      v-else
      class="viewer-content"
    >
      <div class="content-sidebar">
        <div class="sidebar-section">
          <div class="section-title">
            📊 关键指标
          </div>
          <div class="metrics-list">
            <div class="metric-item">
              <span class="metric-label">总体评分</span>
              <span class="metric-value score">{{ overallScore }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">风险等级</span>
              <a-tag :color="getRiskLevelColor(riskLevel)">
                {{ riskLevel }}
              </a-tag>
            </div>
            <div
              v-if="totalReturn !== undefined"
              class="metric-item"
            >
              <span class="metric-label">总收益率</span>
              <span
                class="metric-value"
                :class="totalReturn >= 0 ? 'up' : 'down'"
              >
                {{ formatPercent(totalReturn) }}
              </span>
            </div>
            <div
              v-if="sharpeRatio !== undefined"
              class="metric-item"
            >
              <span class="metric-label">夏普比率</span>
              <span class="metric-value">{{ sharpeRatio }}</span>
            </div>
            <div
              v-if="maxDrawdown !== undefined"
              class="metric-item"
            >
              <span class="metric-label">最大回撤</span>
              <span class="metric-value down">{{ formatPercent(maxDrawdown) }}</span>
            </div>
            <div
              v-if="winRate !== undefined"
              class="metric-item"
            >
              <span class="metric-label">胜率</span>
              <span class="metric-value">{{ formatPercent(winRate) }}</span>
            </div>
          </div>
        </div>

        <a-divider />

        <div
          v-if="interpretation"
          class="sidebar-section"
        >
          <div class="section-title">
            💡 AI分析
          </div>
          
          <div
            v-if="interpretation.summary"
            class="interpretation-summary"
          >
            {{ interpretation.summary }}
          </div>

          <div
            v-if="interpretation.strengths && interpretation.strengths.length"
            class="strengths-section"
          >
            <div class="sub-section-title">
              ✓ 优势
            </div>
            <ul class="strengths-list">
              <li
                v-for="(strength, idx) in interpretation.strengths"
                :key="idx"
              >
                {{ strength }}
              </li>
            </ul>
          </div>

          <div
            v-if="interpretation.weaknesses && interpretation.weaknesses.length"
            class="weaknesses-section"
          >
            <div class="sub-section-title">
              ✗ 劣势
            </div>
            <ul class="weaknesses-list">
              <li
                v-for="(weakness, idx) in interpretation.weaknesses"
                :key="idx"
              >
                {{ weakness }}
              </li>
            </ul>
          </div>

          <div
            v-if="interpretation.suggestions && interpretation.suggestions.length"
            class="suggestions-section"
          >
            <div class="sub-section-title">
              📝 建议
            </div>
            <ol class="suggestions-list">
              <li
                v-for="(suggestion, idx) in interpretation.suggestions"
                :key="idx"
              >
                {{ suggestion }}
              </li>
            </ol>
          </div>
        </div>

        <a-divider />

        <div
          v-if="tradingAdvice"
          class="sidebar-section"
        >
          <div class="section-title">
            💼 交易建议
          </div>
          
          <div
            v-if="tradingAdvice.suitable_for"
            class="advice-item"
          >
            <div class="advice-label">
              适用对象
            </div>
            <div class="advice-content">
              {{ tradingAdvice.suitable_for }}
            </div>
          </div>
          
          <div
            v-if="tradingAdvice.position_management"
            class="advice-item"
          >
            <div class="advice-label">
              仓位管理
            </div>
            <div class="advice-content">
              {{ tradingAdvice.position_management }}
            </div>
          </div>
          
          <div
            v-if="tradingAdvice.risk_control"
            class="advice-item"
          >
            <div class="advice-label">
              风险控制
            </div>
            <div class="advice-content">
              {{ tradingAdvice.risk_control }}
            </div>
          </div>
          
          <div
            v-if="tradingAdvice.next_steps"
            class="advice-item"
          >
            <div class="advice-label">
              下一步
            </div>
            <div class="advice-content">
              {{ tradingAdvice.next_steps }}
            </div>
          </div>
        </div>
      </div>

      <div class="content-main">
        <a-tabs v-model="activeTab">
          <a-tab-pane
            key="content"
            tab="报告内容"
          >
            <div class="report-content-wrapper">
              <div
                v-if="selectedFormat === 'markdown' || selectedFormat === 'html'"
                class="content-renderer"
                v-html="renderedContent"
              />
              <div
                v-else-if="selectedFormat === 'json'"
                class="json-content"
              >
                <pre>{{ formattedJson }}</pre>
              </div>
            </div>
          </a-tab-pane>

          <a-tab-pane
            v-if="strategy"
            key="strategy"
            tab="策略详情"
          >
            <div class="strategy-details">
              <a-descriptions
                bordered
                :column="2"
              >
                <a-descriptions-item label="策略类型">
                  {{ strategy.indicator_type }}
                </a-descriptions-item>
                <a-descriptions-item label="指标公式">
                  <code>{{ strategy.formula }}</code>
                </a-descriptions-item>
                <a-descriptions-item
                  label="策略描述"
                  :span="2"
                >
                  {{ strategy.description }}
                </a-descriptions-item>
                <a-descriptions-item
                  label="信号逻辑"
                  :span="2"
                >
                  {{ strategy.signal }}
                </a-descriptions-item>
              </a-descriptions>

              <a-divider>代码模板</a-divider>
              
              <div class="code-block">
                <pre>{{ strategy.code_template }}</pre>
              </div>
            </div>
          </a-tab-pane>

          <a-tab-pane
            v-if="backtest"
            key="backtest"
            tab="回测数据"
          >
            <div class="backtest-details">
              <a-descriptions
                bordered
                :column="2"
              >
                <a-descriptions-item label="初始资金">
                  ¥{{ formatNumber(backtest.config.initial_capital) }}
                </a-descriptions-item>
                <a-descriptions-item label="最终价值">
                  ¥{{ formatNumber(backtest.metrics.final_value) }}
                </a-descriptions-item>
                <a-descriptions-item label="总交易次数">
                  {{ backtest.metrics.total_trades }}
                </a-descriptions-item>
                <a-descriptions-item label="手续费率">
                  {{ backtest.config.commission_rate }}
                </a-descriptions-item>
              </a-descriptions>

              <a-divider>收益曲线</a-divider>
              <div
                ref="equityChartRef"
                class="equity-chart"
              />

              <a-divider>交易记录</a-divider>
              <a-table
                :columns="tradeColumns"
                :data-source="backtest.trades"
                :pagination="{ pageSize: 10 }"
                size="small"
              >
                <template #bodyCell="{ column, text, record, index }">
                  <template v-if="column.dataIndex === 'type' || column.key === 'type'">
                    <a-tag :color="text === 'buy' ? 'red' : 'green'">
                      {{ text === 'buy' ? '关注信号' : '风险退出信号' }}
                    </a-tag>
                  </template>
                  <template v-else-if="column.dataIndex === 'amount' || column.key === 'amount'">
                    ¥{{ formatNumber(text) }}
                  </template>
                </template>
              </a-table>
            </div>
          </a-tab-pane>
        </a-tabs>
      </div>
    </div>

    <a-modal
      v-model="exportModalVisible"
      title="导出报告"
      @ok="confirmExport"
      @cancel="exportModalVisible = false"
    >
      <a-form
        :form="exportForm"
        layout="vertical"
      >
        <a-form-item label="文件格式">
          <a-radio-group v-model="exportFormat">
            <a-radio value="md">
              Markdown (.md)
            </a-radio>
            <a-radio value="html">
              HTML (.html)
            </a-radio>
            <a-radio value="json">
              JSON (.json)
            </a-radio>
            <a-radio value="pdf">
              PDF (.pdf)
            </a-radio>
          </a-radio-group>
        </a-form-item>
        
        <a-form-item label="文件名">
          <a-input
            v-model="exportFilename"
            placeholder="请输入文件名"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script>
import { DownloadOutlined, PrinterOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import marked from 'marked'
import hljs from 'highlight.js'

export default {
  name: 'ReportViewer',
  
  props: {
    reportId: {
      type: String,
      required: true
    }
  },
  
  data() {
    return {
      loading: false,
      exporting: false,
      error: null,
      
      reportTitle: '报告加载中...',
      reportType: '',
      tsCode: '',
      generatedAt: '',
      selectedFormat: 'markdown',
      activeTab: 'content',
      
      reportData: null,
      content: '',
      strategy: null,
      backtest: null,
      interpretation: null,
      tradingAdvice: null,
      
      overallScore: 0,
      riskLevel: '未知',
      totalReturn: undefined,
      sharpeRatio: undefined,
      maxDrawdown: undefined,
      winRate: undefined,
      
      exportModalVisible: false,
      exportFormat: 'md',
      exportFilename: '',
      
      tradeColumns: [
        { title: '日期', dataIndex: 'date', key: 'date' },
        { title: '类型', dataIndex: 'type', key: 'type', scopedSlots: { customRender: 'type' } },
        { title: '价格', dataIndex: 'price', key: 'price' },
        { title: '数量', dataIndex: 'quantity', key: 'quantity' },
        { title: '金额', dataIndex: 'amount', key: 'amount', scopedSlots: { customRender: 'amount' } }
      ],
      
      equityChart: null
    }
  },
  
  computed: {
    renderedContent() {
      if (this.selectedFormat === 'html') {
        return this.content
      }
      
      if (this.selectedFormat === 'markdown') {
        try {
          marked.setOptions({
            highlight: function(code, lang) {
              if (lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value
              }
              return code
            },
            breaks: true,
            gfm: true
          })
          return marked(this.content)
        } catch (e) {
          console.error('Markdown渲染失败:', e)
          return this.content
        }
      }
      
      return ''
    },
    
    formattedJson() {
      try {
        if (typeof this.reportData === 'string') {
          return JSON.stringify(JSON.parse(this.reportData), null, 2)
        }
        return JSON.stringify(this.reportData, null, 2)
      } catch (e) {
        return this.reportData || '{}'
      }
    }
  },
  
  mounted() {
    this.loadReport()
  },
  
  beforeUnmount() {
    if (this.equityChart) {
      this.equityChart.dispose()
    }
  },
  
  methods: {
    async loadReport() {
      this.loading = true
      this.error = null
      
      try {
        const response = await this.$axios.get(`/api/v2/reports/${this.reportId}`)
        
        if (response.data.success) {
          this.reportData = response.data.data
          this.parseReportData(this.reportData)
        } else {
          this.error = response.data.error || '加载报告失败'
        }
      } catch (error) {
        console.error('加载报告失败:', error)
        this.error = error.message || '网络错误，请重试'
      } finally {
        this.loading = false
      }
    },
    
    parseReportData(data) {
      this.reportTitle = data.title || '未命名报告'
      this.reportType = data.report_type || 'unknown'
      this.tsCode = data.ts_code || ''
      this.generatedAt = this.formatDate(data.generated_at)
      this.content = data.content || ''
      
      this.strategy = data.strategy || null
      this.backtest = data.backtest || null
      this.interpretation = data.interpretation || null
      
      if (this.interpretation) {
        this.overallScore = this.interpretation.overall_score || 0
        this.riskLevel = this.interpretation.risk_level || '未知'
        this.tradingAdvice = this.interpretation.trading_advice || null
      }
      
      if (this.backtest && this.backtest.metrics) {
        const metrics = this.backtest.metrics
        this.totalReturn = metrics.total_return
        this.sharpeRatio = metrics.sharpe_ratio
        this.maxDrawdown = metrics.max_drawdown
        this.winRate = metrics.win_rate
      }
      
      this.$nextTick(() => {
        if (this.backtest && this.backtest.daily_equity && this.backtest.daily_equity.length > 0) {
          this.initEquityChart()
        }
      })
    },
    
    initEquityChart() {
      if (!this.$refs.equityChartRef) return
      
      import('echarts').then(echarts => {
        const chart = echarts.init(this.$refs.equityChartRef)
        
        const equityData = this.backtest.daily_equity.map(d => [
          d.date,
          d.total_value
        ])
        
        const option = {
          tooltip: {
            trigger: 'axis'
          },
          grid: {
            left: '3%',
            right: '4%',
            bottom: '3%',
            containLabel: true
          },
          xAxis: {
            type: 'category',
            data: this.backtest.daily_equity.map(d => d.date),
            axisLabel: {
              rotate: 45
            }
          },
          yAxis: {
            type: 'value'
          },
          series: [{
            name: '账户权益',
            type: 'line',
            data: equityData.map(d => d[1]),
            smooth: true,
            lineStyle: {
              width: 2
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
                  { offset: 1, color: 'rgba(59, 130, 246, 0.05)' }
                ]
              }
            }
          }]
        }
        
        chart.setOption(option)
        this.equityChart = chart
      })
    },
    
    handleFormatChange(format) {
      this.selectedFormat = format
    },
    
    handleExport() {
      this.exportFilename = `${this.tsCode}_${this.reportType}_${Date.now()}`
      this.exportModalVisible = true
    },
    
    async confirmExport() {
      this.exporting = true
      
      try {
        const extension = this.exportFormat === 'html' ? 'html' : 
                         this.exportFormat === 'json' ? 'json' : 'md'
        
        let content = this.content
        
        if (this.exportFormat === 'json') {
          content = JSON.stringify(this.reportData, null, 2)
        }
        
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        
        const link = document.createElement('a')
        link.href = url
        link.download = `${this.exportFilename}.${extension}`
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        URL.revokeObjectURL(url)
        
        this.$message.success('报告导出成功')
        this.exportModalVisible = false
        
      } catch (error) {
        console.error('导出失败:', error)
        this.$message.error('导出失败: ' + error.message)
      } finally {
        this.exporting = false
      }
    },
    
    handlePrint() {
      window.print()
    },
    
    async handleRefresh() {
      await this.loadReport()
      this.$message.success('报告已刷新')
    },
    
    getReportTypeColor(type) {
      const colors = {
        'single_stock': 'blue',
        'backtest': 'green',
        'research': 'purple'
      }
      return colors[type] || 'default'
    },
    
    getReportTypeLabel(type) {
      const labels = {
        'single_stock': '单股票策略',
        'backtest': '回测报告',
        'research': '研究报告'
      }
      return labels[type] || type
    },
    
    getRiskLevelColor(level) {
      const colors = {
        '低风险': 'green',
        '较低风险': 'cyan',
        '中等风险': 'orange',
        '高风险': 'red'
      }
      return colors[level] || 'default'
    },
    
    formatPercent(value) {
      if (value === undefined || value === null) return '--'
      const sign = value >= 0 ? '+' : ''
      return `${sign}${(value * 100).toFixed(2)}%`
    },
    
    formatNumber(value) {
      if (value === undefined || value === null) return '--'
      return value.toLocaleString('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })
    },
    
    formatDate(dateStr) {
      if (!dateStr) return '--'
      try {
        const date = new Date(dateStr)
        return date.toLocaleString('zh-CN')
      } catch (e) {
        return dateStr
      }
    }
  }
}
</script>

<style scoped>
.report-viewer-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary, #0a1628);
  color: var(--text-primary, #f1f5f9);
}

.viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: var(--bg-surface, #1e293b);
  border-bottom: 1px solid rgba(255,255,255,0.1);
}

.header-left {
  flex: 1;
}

.viewer-title {
  margin: 0 0 8px 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.report-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--text-secondary, #94a3b8);
}

.meta-separator {
  color: var(--text-muted, #64748b);
}

.loading-container,
.error-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
}

.viewer-content {
  flex: 1;
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 0;
  overflow: hidden;
}

.content-sidebar {
  background: var(--bg-surface, #1e293b);
  padding: 20px;
  overflow-y: auto;
  border-right: 1px solid rgba(255,255,255,0.1);
}

.sidebar-section {
  margin-bottom: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 12px;
}

.metrics-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.metric-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.metric-label {
  font-size: 13px;
  color: var(--text-secondary, #94a3b8);
}

.metric-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.metric-value.score {
  font-size: 18px;
  color: var(--color-primary, #3b82f6);
}

.metric-value.up {
  color: var(--color-up, #ef4444);
}

.metric-value.down {
  color: var(--color-down, #22c55e);
}

.interpretation-summary {
  font-size: 13px;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.6;
  margin-bottom: 16px;
}

.sub-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin: 12px 0 8px 0;
}

.strengths-list,
.weaknesses-list,
.suggestions-list {
  margin: 0;
  padding-left: 20px;
  font-size: 12px;
}

.strengths-list li {
  color: #10b981;
  margin-bottom: 6px;
}

.weaknesses-list li {
  color: #ef4444;
  margin-bottom: 6px;
}

.suggestions-list li {
  color: var(--text-secondary, #94a3b8);
  margin-bottom: 6px;
}

.advice-item {
  margin-bottom: 12px;
}

.advice-label {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  margin-bottom: 4px;
}

.advice-content {
  font-size: 13px;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.5;
}

.content-main {
  padding: 20px;
  overflow-y: auto;
}

.report-content-wrapper {
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
  padding: 24px;
  min-height: 600px;
}

.content-renderer {
  line-height: 1.8;
  color: var(--text-secondary, #94a3b8);
}

.content-renderer :deep(h1) {
  color: var(--text-primary, #f1f5f9);
  border-bottom: 2px solid var(--color-primary, #3b82f6);
  padding-bottom: 8px;
  margin-top: 24px;
}

.content-renderer :deep(h2) {
  color: var(--text-primary, #f1f5f9);
  margin-top: 20px;
}

.content-renderer :deep(h3) {
  color: var(--text-primary, #f1f5f9);
  margin-top: 16px;
}

.content-renderer :deep(code) {
  background: rgba(59, 130, 246, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  color: #60a5fa;
}

.content-renderer :deep(pre) {
  background: #0f172a;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
}

.json-content pre {
  background: #0f172a;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: #94a3b8;
}

.strategy-details,
.backtest-details {
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
  padding: 24px;
}

.code-block {
  background: #0f172a;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
}

.code-block pre {
  margin: 0;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: #94a3b8;
}

.equity-chart {
  height: 300px;
  margin: 16px 0;
}

@media print {
  .viewer-header,
  .content-sidebar {
    display: none;
  }
  
  .viewer-content {
    display: block;
  }
  
  .content-main {
    padding: 0;
  }
}
</style>
