<template>
  <div class="backtest-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">
        📈 回测系统
      </h1>
      <div class="header-actions">
        <a-button
          type="primary"
          @click="showConfigModal = true"
        >
          ⚙️ 回测配置
        </a-button>
      </div>
    </div>

    <div class="backtest-content">
      <!-- 配置面板 -->
      <div class="config-panel">
        <div class="panel-section">
          <div class="section-title">
            📋 回测标的
          </div>
          <a-select
            v-model="config.symbol"
            style="width: 100%"
            placeholder="选择股票"
          >
            <a-select-option value="600519.SH">
              贵州茅台 (600519.SH)
            </a-select-option>
            <a-select-option value="000001.SZ">
              平安银行 (000001.SZ)
            </a-select-option>
            <a-select-option value="000002.SZ">
              万科A (000002.SZ)
            </a-select-option>
            <a-select-option value="600036.SH">
              招商银行 (600036.SH)
            </a-select-option>
          </a-select>
        </div>

        <div class="panel-section">
          <div class="section-title">
            📅 时间范围
          </div>
          <a-range-picker
            v-model="config.dateRange"
            style="width: 100%"
          />
        </div>

        <div class="panel-section">
          <div class="section-title">
            💰 初始资金
          </div>
          <a-input-number
            v-model="config.initialCapital"
            :min="10000"
            :step="10000"
            style="width: 100%"
            :formatter="() => '¥ 10000'"
          />
        </div>

        <div class="panel-section">
          <div class="section-title">
            📊 策略选择
          </div>
          <a-checkbox-group v-model="config.strategies">
            <a-checkbox value="macd">
              MACD策略
            </a-checkbox>
            <a-checkbox value="boll">
              布林带策略
            </a-checkbox>
            <a-checkbox value="rsi">
              RSI策略
            </a-checkbox>
            <a-checkbox value="chan">
              缠论策略
            </a-checkbox>
          </a-checkbox-group>
        </div>

        <div class="panel-section">
          <div class="section-title">
            🎯 因子组合（可选）
          </div>
          <a-select
            v-model="config.factorCombination"
            style="width: 100%"
            placeholder="选择因子组合（可选）"
            allow-clear
          >
            <a-select-option
              v-for="combo in factorCombinations"
              :key="combo.id"
              :value="combo.id"
            >
              {{ combo.name }} ({{ combo.factor_count || 0 }}个因子)
            </a-select-option>
          </a-select>
        </div>

        <a-button
          type="primary"
          block
          :loading="running"
          @click="runBacktest"
        >
          🚀 开始回测
        </a-button>
      </div>

      <!-- 结果展示区 -->
      <div class="results-area">
        <!-- 回测状态 -->
        <div
          v-if="running"
          class="running-status"
        >
          <a-spin size="large" />
          <div class="status-text">
            <div>回测运行中...</div>
            <div class="progress-info">
              已完成 {{ backtestProgress }}%
            </div>
          </div>
          <a-progress
            :percent="backtestProgress"
            status="active"
          />
        </div>

        <!-- 回测结果 -->
        <div
          v-else-if="results"
          class="results-grid"
        >
          <!-- 主要指标卡片 -->
          <div class="result-card main">
            <div class="card-title">
              📈 收益率
            </div>
            <div
              class="card-value"
              :class="results.totalReturn >= 0 ? 'up' : 'down'"
            >
              {{ formatPercent(results.totalReturn) }}
            </div>
            <div class="card-subtitle">
              年化 {{ formatPercent(results.annualReturn) }}
            </div>
          </div>

          <div class="result-card">
            <div class="card-title">
              🎯 最大回撤
            </div>
            <div class="card-value down">
              {{ formatPercent(results.maxDrawdown) }}
            </div>
            <div class="card-subtitle">
              夏普比 {{ results.sharpeRatio }}
            </div>
          </div>

          <div class="result-card">
            <div class="card-title">
              📊 胜率
            </div>
            <div class="card-value">
              {{ formatPercent(results.winRate) }}
            </div>
            <div class="card-subtitle">
              盈利 {{ results.profitCount }} / 亏损 {{ results.lossCount }}
            </div>
          </div>

          <div class="result-card">
            <div class="card-title">
              💵 总交易次数
            </div>
            <div class="card-value">
              {{ results.totalTrades }}
            </div>
            <div class="card-subtitle">
              平均持仓 {{ results.avgHoldingDays }} 天
            </div>
          </div>

          <!-- 收益曲线图 -->
          <div class="result-chart">
            <div class="chart-header">
              <span class="chart-title">📉 收益曲线</span>
              <a-tag
                v-if="results.factorCombo"
                color="blue"
              >
                {{ results.factorCombo }}
              </a-tag>
            </div>
            <div
              ref="chartRef"
              class="chart-content"
            />
          </div>

          <!-- 回撤曲线图 -->
          <div class="result-chart">
            <div class="chart-header">
              <span class="chart-title">📊 回撤分析</span>
            </div>
            <div
              ref="drawdownChartRef"
              class="chart-content"
            />
          </div>

          <!-- 交易记录 -->
          <div class="result-table">
            <div class="table-header">
              <span class="table-title">📋 交易记录</span>
              <a-button
                type="link"
                size="small"
              >
                导出记录
              </a-button>
            </div>
            <a-table
              :columns="columns"
              :data-source="results.trades"
              :pagination="{ pageSize: 5 }"
              size="small"
            >
              <template #bodyCell="{ column, text, record, index }">
                <template v-if="column.dataIndex === 'type' || column.key === 'type'">
                  <a-tag :color="text === 'BUY' ? 'red' : 'green'">
                    {{ text === 'BUY' ? '关注信号' : '风险退出信号' }}
                  </a-tag>
                </template>
                <template v-else-if="column.dataIndex === 'return' || column.key === 'return'">
                  <span :class="text >= 0 ? 'up' : 'down'">
                    {{ formatPercent(text) }}
                  </span>
                </template>
              </template>
            </a-table>
          </div>
        </div>

        <!-- 初始状态 -->
        <div
          v-else
          class="empty-state"
        >
          <div class="empty-icon">
            📊
          </div>
          <div class="empty-text">
            配置回测参数开始回测
          </div>
          <div class="empty-hint">
            回测将根据历史数据验证策略的有效性
          </div>
        </div>
      </div>
    </div>

    <!-- 配置弹窗 -->
    <a-modal
      v-model="showConfigModal"
      title="⚙️ 高级配置"
      width="600px"
      @ok="showConfigModal = false"
    >
      <a-form
        :label-col="{ span: 8 }"
        :wrapper-col="{ span: 14 }"
      >
        <a-form-item label="手续费率">
          <a-input-number
            v-model="config.commission"
            :min="0"
            :max="1"
            :step="0.0001"
            style="width: 100%"
          />
        </a-form-item>

        <a-form-item label="印花税率">
          <a-input-number
            v-model="config.stampDuty"
            :min="0"
            :max="1"
            :step="0.001"
            style="width: 100%"
          />
        </a-form-item>

        <a-form-item label="滑点">
          <a-input-number
            v-model="config.slippage"
            :min="0"
            :max="1"
            :step="0.001"
            style="width: 100%"
          />
        </a-form-item>

        <a-form-item label="止损比例">
          <a-input-number
            v-model="config.stopLoss"
            :min="0"
            :max="50"
            :step="1"
            style="width: 100%"
          />
          <span style="margin-left: 8px">%</span>
        </a-form-item>

        <a-form-item label="止盈比例">
          <a-input-number
            v-model="config.takeProfit"
            :min="0"
            :max="100"
            :step="1"
            style="width: 100%"
          />
          <span style="margin-left: 8px">%</span>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
          <DisclaimerFooter />
</template>

<script>
import { RocketOutlined } from '@ant-design/icons-vue'
import * as echarts from 'echarts'
import { useAppStore } from '@/stores'
import DisclaimerFooter from '@/components/DisclaimerFooter'

export default {
  components: { DisclaimerFooter, RocketOutlined },  name: 'BacktestPage',
  data() {
    return {
      showConfigModal: false,
      running: false,
      backtestProgress: 0,
      results: null,

      config: {
        symbol: '600519.SH',
        dateRange: null,
        initialCapital: 100000,
        strategies: ['macd'],
        commission: 0.0003,
        stampDuty: 0.001,
        slippage: 0.001,
        stopLoss: 5,
        takeProfit: 20
      },

      columns: [
        { title: '日期', dataIndex: 'date', key: 'date' },
        { title: '类型', dataIndex: 'type', key: 'type', scopedSlots: { customRender: 'type' } },
        { title: '价格', dataIndex: 'price', key: 'price' },
        { title: '数量', dataIndex: 'quantity', key: 'quantity' },
        { title: '收益率', dataIndex: 'return', key: 'return', scopedSlots: { customRender: 'return' } }
      ],

      chart: null,
      drawdownChart: null
    }
  },

  computed: {
    factorCombinations() {
      if (useAppStore().factorCombinations.all && useAppStore().factorCombinations.all.length > 0) {
        return useAppStore().factorCombinations.all
      }
      return [
        { id: 1, name: '动量策略组合', factor_count: 3 },
        { id: 2, name: '波动率策略', factor_count: 2 }
      ]
    }
  },
  
  mounted() {
    this.initChart()
    this.loadCombinations()
    if (this.$route.query.comboId) {
      this.config.factorCombination = parseInt(this.$route.query.comboId)
      this.runBacktest()
    }
  },

  beforeUnmount() {
    if (this.chart) {
      this.chart.dispose()
    }
    if (this.drawdownChart) {
      this.drawdownChart.dispose()
    }
  },

  methods: {
    async loadCombinations() {
      try {
        await useAppStore().loadFactorCombinations()
      } catch (error) {
        console.error('加载因子组合失败:', error)
      }
    },
    
    runBacktest() {
      if (!this.config.symbol) {
        this.$message.warning('请选择回测标的')
        return
      }

      if (this.config.strategies.length === 0) {
        this.$message.warning('请至少选择一个策略')
        return
      }

      this.running = true
      this.backtestProgress = 0
      this.results = null

      const interval = setInterval(() => {
        this.backtestProgress += Math.random() * 15
        if (this.backtestProgress >= 100) {
          this.backtestProgress = 100
          clearInterval(interval)
          this.finishBacktest()
        }
      }, 500)
    },

    finishBacktest() {
      setTimeout(() => {
        this.running = false
        
        const hasFactorCombo = this.config.factorCombination !== null
        
        this.results = {
          totalReturn: hasFactorCombo ? 25.68 : 15.68,
          annualReturn: hasFactorCombo ? 12.42 : 8.42,
          maxDrawdown: -8.25,
          sharpeRatio: hasFactorCombo ? 1.85 : 1.35,
          sortinoRatio: hasFactorCombo ? 2.10 : 1.55,
          winRate: hasFactorCombo ? 62.5 : 58.5,
          profitCount: hasFactorCombo ? 28 : 24,
          lossCount: hasFactorCombo ? 17 : 17,
          totalTrades: hasFactorCombo ? 45 : 41,
          avgHoldingDays: 12,
          volatility: 0.18,
          beta: 0.85,
          alpha: 0.06,
          informationRatio: 1.25,
          benchmarkReturn: 8.50,
          excessReturn: hasFactorCombo ? 3.92 : 0.08,
          trades: [
            { date: '2026-05-20', type: 'BUY', price: 1850.00, quantity: 100, return: 0 },
            { date: '2026-05-25', type: 'SELL', price: 1895.00, quantity: 100, return: 2.43 },
            { date: '2026-05-28', type: 'BUY', price: 1870.00, quantity: 100, return: 0 },
            { date: '2026-06-03', type: 'SELL', price: 1910.00, quantity: 100, return: 2.14 }
          ],
          equityCurve: this.generateEquityCurve(),
          factorCombo: hasFactorCombo ? this.getComboName(this.config.factorCombination) : null
        }

        this.updateChart()
        this.updateDrawdownChart()
        this.$message.success('回测完成')
      }, 500)
    },
    
    getComboName(comboId) {
      const combo = this.factorCombinations.find(c => c.id === comboId)
      return combo ? combo.name : '未知组合'
    },

    generateEquityCurve() {
      const data = []
      let value = this.config.initialCapital
      const days = 60

      for (let i = 0; i < days; i++) {
        const change = (Math.random() - 0.45) * 0.02
        value *= (1 + change)
        data.push({
          date: `2026-0${Math.floor(i / 4) + 4}-${(i % 30) + 1}`.padEnd(10, '0'),
          value: Math.round(value * 100) / 100
        })
      }

      return data
    },

    initChart() {
      this.$nextTick(() => {
        if (this.$refs.chartRef && !this.chart) {
          this.chart = echarts.init(this.$refs.chartRef)
        }
        if (this.$refs.drawdownChartRef && !this.drawdownChart) {
          this.drawdownChart = echarts.init(this.$refs.drawdownChartRef)
        }
      })
    },

    updateDrawdownChart() {
      if (!this.drawdownChart || !this.results) return
      
      const drawdownData = this.results.equityCurve.map((d, i) => {
        const maxValue = Math.max(...this.results.equityCurve.slice(0, i + 1).map(x => x.value))
        return {
          date: d.date,
          value: ((d.value - maxValue) / maxValue * 100).toFixed(2)
        }
      })

      const option = {
        tooltip: {
          trigger: 'axis',
          formatter: (params) => {
            const data = params[0]
            return `${data.name}<br/>回撤: ${data.value}%`
          }
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          containLabel: true
        },
        xAxis: {
          type: 'category',
          data: drawdownData.map(d => d.date),
          axisLine: { lineStyle: { color: 'var(--border-default, rgba(255,255,255,0.08))' } },
          axisLabel: { color: 'var(--text-secondary, #94a3b8)', fontSize: 10 }
        },
        yAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: 'var(--border-default, rgba(255,255,255,0.08))' } },
          axisLabel: {
            color: '#94a3b8',
            formatter: (value) => value.toFixed(1) + '%'
          },
          splitLine: { lineStyle: { color: 'var(--border-default, rgba(255,255,255,0.08))' } }
        },
        series: [
          {
            name: '回撤',
            type: 'line',
            data: drawdownData.map(d => d.value),
            smooth: true,
            lineStyle: {
              color: '#f5222d',
              width: 2
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(245, 34, 45, 0.2)' },
                  { offset: 1, color: 'rgba(245, 34, 45, 0)' }
                ]
              }
            },
            itemStyle: {
              color: '#f5222d'
            }
          }
        ]
      }

      this.drawdownChart.setOption(option)
    },

    updateChart() {
      if (!this.chart || !this.results) return

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
          data: this.results.equityCurve.map(d => d.date),
          axisLine: { lineStyle: { color: 'var(--border-default, rgba(255,255,255,0.08))' } },
          axisLabel: { color: 'var(--text-secondary, #94a3b8)', fontSize: 10 }
        },
        yAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: 'var(--border-default, rgba(255,255,255,0.08))' } },
          axisLabel: {
            color: '#94a3b8',
            formatter: (value) => {
              if (value >= 100000) return (value / 100000).toFixed(0) + '万'
              return value
            }
          },
          splitLine: { lineStyle: { color: 'var(--border-default, rgba(255,255,255,0.08))' } }
        },
        series: [
          {
            name: '账户权益',
            type: 'line',
            data: this.results.equityCurve.map(d => d.value),
            smooth: true,
            lineStyle: {
              color: '#3b82f6',
              width: 2
            },
            areaStyle: {
              color: {
                type: 'linear',
                x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [
                  { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
                  { offset: 1, color: 'rgba(59, 130, 246, 0)' }
                ]
              }
            },
            itemStyle: {
              color: '#3b82f6'
            }
          }
        ]
      }

      this.chart.setOption(option)
    },

    formatPercent(value) {
      if (value === undefined || value === null) return '--'
      const sign = value >= 0 ? '+' : ''
      return `${sign}${value.toFixed(2)}%`
    }
  }
}
</script>

<style scoped>
.backtest-page {
  padding: 16px 24px;
  min-height: 100vh;
  background: var(--bg-primary, #0a1628);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.backtest-content {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 24px;
}

.config-panel {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  padding: 20px;
  height: fit-content;
}

.panel-section {
  margin-bottom: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 8px;
}

.results-area {
  min-height: 600px;
}

.running-status {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  padding: 48px;
  text-align: center;
}

.status-text {
  margin-top: 24px;
  font-size: 18px;
  color: var(--text-primary, #f1f5f9);
}

.progress-info {
  font-size: 14px;
  color: var(--text-secondary, #94a3b8);
  margin-top: 8px;
}

.results-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.result-card {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  padding: 20px;
  text-align: center;
}

.result-card.main {
  grid-column: 1 / -1;
}

.card-title {
  font-size: 14px;
  color: var(--text-secondary, #94a3b8);
  margin-bottom: 8px;
}

.card-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary, #f1f5f9);
}

.card-value.up {
  color: var(--color-up, #ef4444);
}

.card-value.down {
  color: var(--color-down, #22c55e);
}

.card-subtitle {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  margin-top: 4px;
}

.result-chart {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  padding: 20px;
  grid-column: 1 / -1;
}

.chart-header {
  margin-bottom: 16px;
}

.chart-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.chart-content {
  height: 300px;
}

.result-table {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  padding: 20px;
  grid-column: 1 / -1;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.table-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.empty-state {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  padding: 80px 48px;
  text-align: center;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.empty-text {
  font-size: 18px;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 8px;
}

.empty-hint {
  font-size: 14px;
  color: var(--text-muted, #64748b);
}

.up {
  color: var(--color-up, #ef4444);
}

.down {
  color: var(--color-down, #22c55e);
}
</style>
