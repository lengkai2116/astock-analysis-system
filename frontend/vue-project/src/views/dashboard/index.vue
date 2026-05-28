<template>
  <div class="dashboard-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">📊 仪表盘</h1>
      <div class="header-actions">
        <a-range-picker @change="onDateRangeChange" style="margin-right: 12px" />
        <a-button @click="refreshData">
          🔄 刷新数据
        </a-button>
      </div>
    </div>

    <!-- 快捷入口工具栏 -->
    <div class="quick-actions-bar">
      <div class="quick-actions">
        <a-card size="small" class="quick-action-card" hoverable @click="$router.push('/watchlist')">
          <div class="quick-action-content">
            <span class="quick-action-icon">📈</span>
            <div class="quick-action-info">
              <div class="quick-action-title">自选监控</div>
              <div class="quick-action-desc">实时监控股票行情</div>
            </div>
          </div>
        </a-card>
        
        <a-card size="small" class="quick-action-card" hoverable @click="$router.push('/indicator-ide')">
          <div class="quick-action-content">
            <span class="quick-action-icon">📊</span>
            <div class="quick-action-info">
              <div class="quick-action-title">指标IDE</div>
              <div class="quick-action-desc">策略编辑与技术分析</div>
            </div>
          </div>
        </a-card>
        
        <a-card size="small" class="quick-action-card" hoverable @click="$router.push('/backtest')">
          <div class="quick-action-content">
            <span class="quick-action-icon">🎯</span>
            <div class="quick-action-info">
              <div class="quick-action-title">回测系统</div>
              <div class="quick-action-desc">策略回测与验证</div>
            </div>
          </div>
        </a-card>
        
        <a-card size="small" class="quick-action-card" hoverable @click="$router.push('/ai-analysis')">
          <div class="quick-action-content">
            <span class="quick-action-icon">🤖</span>
            <div class="quick-action-info">
              <div class="quick-action-title">AI分析</div>
              <div class="quick-action-desc">智能投研与报告</div>
            </div>
          </div>
        </a-card>
        
        <a-card size="small" class="quick-action-card" hoverable @click="$router.push('/factor-manager')">
          <div class="quick-action-content">
            <span class="quick-action-icon">🔧</span>
            <div class="quick-action-info">
              <div class="quick-action-title">因子管理</div>
              <div class="quick-action-desc">因子组合与优化</div>
            </div>
          </div>
        </a-card>

        <a-card size="small" class="quick-action-card" hoverable @click="$router.push('/strategy-templates')">
          <div class="quick-action-content">
            <span class="quick-action-icon">📋</span>
            <div class="quick-action-info">
              <div class="quick-action-title">策略模板</div>
              <div class="quick-action-desc">策略模板与管理</div>
            </div>
          </div>
        </a-card>

        <a-card size="small" class="quick-action-card" hoverable @click="$router.push('/reports-center')">
          <div class="quick-action-content">
            <span class="quick-action-icon">📑</span>
            <div class="quick-action-info">
              <div class="quick-action-title">报告中心</div>
              <div class="quick-action-desc">策略报告与导出</div>
            </div>
          </div>
        </a-card>
      </div>
    </div>

    <!-- 策略信号展示区域 -->
    <div v-if="latestSignals.length > 0" class="strategy-signals-section">
      <div class="section-header">
        <h3 class="section-title">📡 最新策略信号</h3>
        <a-button type="link" @click="$router.push('/strategy-templates')">查看更多</a-button>
      </div>
      <div class="signals-grid">
        <StrategySignalPanel
          v-for="signal in latestSignals"
          :key="signal.id"
          :strategyOutput="signal"
        />
      </div>
    </div>

    <div class="dashboard-content">
      <!-- 概览统计卡片 -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon up">📈</div>
          <div class="stat-info">
            <div class="stat-label">自选股总数</div>
            <div class="stat-value">{{ stats.totalStocks }}</div>
            <div class="stat-change up">
              <span>上涨</span> {{ stats.upStocks }} 只
            </div>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon down">📉</div>
          <div class="stat-info">
            <div class="stat-label">平均涨跌幅</div>
            <div class="stat-value" :class="avgChangeClass">
              {{ formatPercent(stats.avgChange) }}
            </div>
            <div class="stat-change neutral">
              {{ stats.upStocks }} 涨 / {{ stats.downStocks }} 跌
            </div>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon primary">💰</div>
          <div class="stat-info">
            <div class="stat-label">总成交额</div>
            <div class="stat-value">{{ formatAmount(stats.totalAmount) }}</div>
            <div class="stat-change neutral">
              实时数据更新中
            </div>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon accent">🎯</div>
          <div class="stat-info">
            <div class="stat-label">策略信号</div>
            <div class="stat-value">{{ stats.activeSignals }}</div>
            <div class="stat-change neutral">
              {{ stats.buySignals }} 买入 / {{ stats.sellSignals }} 卖出
            </div>
          </div>
        </div>
      </div>

      <!-- 主要内容区 -->
      <div class="main-grid">
        <!-- 涨跌幅排行 -->
        <div class="panel rank-panel">
          <div class="panel-header">
            <span class="panel-title">📊 涨跌幅排行</span>
            <a-radio-group v-model="rankType" size="small">
              <a-radio-button value="change">涨幅榜</a-radio-button>
              <a-radio-button value="changePercent">跌幅榜</a-radio-button>
            </a-radio-group>
          </div>
          <div class="panel-content">
            <div
              v-for="(stock, index) in rankList"
              :key="stock.symbol"
              class="rank-item"
            >
              <span class="rank-number" :class="getRankClass(index)">{{ index + 1 }}</span>
              <div class="rank-info">
                <span class="stock-name">{{ stock.name }}</span>
                <span class="stock-symbol">{{ stock.symbol }}</span>
              </div>
              <span class="rank-price">{{ formatPrice(stock.price) }}</span>
              <span class="rank-change" :class="stock.changePercent >= 0 ? 'up' : 'down'">
                {{ formatPercent(stock.changePercent) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 市场概况 -->
        <div class="panel market-panel">
          <div class="panel-header">
            <span class="panel-title">🌐 市场概况</span>
          </div>
          <div class="panel-content">
            <div class="market-grid">
              <div class="market-item" v-for="index in marketIndexes" :key="index.symbol">
                <div class="market-name">{{ index.name }}</div>
                <div class="market-value" :class="index.change >= 0 ? 'up' : 'down'">
                  {{ formatPrice(index.value) }}
                </div>
                <div class="market-change" :class="index.change >= 0 ? 'up' : 'down'">
                  {{ formatPercent(index.changePercent) }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 策略状态 -->
        <div class="panel strategy-panel">
          <div class="panel-header">
            <span class="panel-title">📋 策略状态</span>
          </div>
          <div class="panel-content">
            <div class="strategy-list">
              <div
                v-for="strategy in strategyStatus"
                :key="strategy.id"
                class="strategy-item"
              >
                <span class="strategy-icon">{{ strategy.icon }}</span>
                <span class="strategy-name">{{ strategy.name }}</span>
                <a-tag :color="strategy.enabled ? 'green' : 'default'" size="small">
                  {{ strategy.enabled ? '运行中' : '已停止' }}
                </a-tag>
              </div>
            </div>
          </div>
        </div>

        <!-- 资金流向 -->
        <div class="panel flow-panel">
          <div class="panel-header">
            <span class="panel-title">💵 资金流向</span>
          </div>
          <div class="panel-content">
            <div class="flow-chart" ref="flowChartRef"></div>
          </div>
        </div>
      </div>

      <!-- 近期操作记录 -->
      <div class="panel activity-panel">
        <div class="panel-header">
          <span class="panel-title">📝 近期操作</span>
          <a-button type="link" size="small">查看全部</a-button>
        </div>
        <div class="panel-content">
          <a-timeline>
            <a-timeline-item
              v-for="activity in recentActivities"
              :key="activity.id"
              :color="getActivityColor(activity.type)"
            >
              <div class="activity-item">
                <span class="activity-time">{{ activity.time }}</span>
                <span class="activity-type" :class="activity.type">
                  {{ getActivityLabel(activity.type) }}
                </span>
                <span class="activity-desc">{{ activity.description }}</span>
              </div>
            </a-timeline-item>
          </a-timeline>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import axios from '@/utils/request'
import StrategySignalPanel from '@/components/StrategySignalPanel.vue'

export default {
  name: 'DashboardPage',
  components: {
    StrategySignalPanel
  },
  data() {
    return {
      rankType: 'change',
      dateRange: null,
      stats: {
        totalStocks: 0,
        upStocks: 0,
        downStocks: 0,
        avgChange: 0,
        totalAmount: 0,
        activeSignals: 12,
        buySignals: 7,
        sellSignals: 3
      },
      stocks: [],
      marketIndexes: [],
      strategyStatus: [
        { id: 'chan', name: '缠论分析', icon: '📐', enabled: true },
        { id: 'macd', name: 'MACD策略', icon: '📊', enabled: true },
        { id: 'boll', name: '布林带策略', icon: '📈', enabled: true },
        { id: 'rsi', name: 'RSI策略', icon: '📉', enabled: false },
        { id: 'vol', name: '量价策略', icon: '📏', enabled: false }
      ],
      recentActivities: [
        { id: 1, time: '10:32', type: 'buy', description: '买入 贵州茅台 100股 @1850.00' },
        { id: 2, time: '09:45', type: 'signal', description: 'MACD策略发出买入信号 - 中国平安' },
        { id: 3, time: '09:30', type: 'alert', description: '缠论分析：分型形成预警 - 万科A' },
        { id: 4, time: 'Yesterday', type: 'sell', description: '卖出 平安银行 200股 @12.61' },
        { id: 5, time: 'Yesterday', type: 'signal', description: '布林带策略发出卖出信号 - 美的集团' }
      ],
      latestSignals: [],
      flowChart: null
    }
  },

  computed: {
    rankList() {
      const sorted = [...this.stocks].sort((a, b) => {
        return this.rankType === 'change'
          ? b.change_pct - a.change_pct
          : a.change_pct - b.change_pct
      })
      return sorted.slice(0, 8)
    },

    avgChangeClass() {
      if (this.stats.avgChange > 0) return 'up'
      if (this.stats.avgChange < 0) return 'down'
      return ''
    }
  },

  mounted() {
    this.initFlowChart()
    this.refreshData()
    this.loadLatestSignals()
  },

  beforeDestroy() {
    if (this.flowChart) {
      this.flowChart.dispose()
    }
  },

  methods: {
    onDateRangeChange(date, dateString) {
      this.dateRange = dateString
      this.refreshData()
    },

    async refreshData() {
      console.log('Refreshing dashboard data...')
      await Promise.all([
        this.loadStockData(),
        this.loadIndexData()
      ])
      this.initFlowChart()
    },

    async loadStockData() {
      try {
        const response = await axios.get('/api/v3/market/realtime')
        if (response && response.data) {
          this.stocks = response.data.map(item => ({
            symbol: item.ts_code,
            name: item.name,
            price: item.price,
            changePercent: item.change_pct,
            change: item.change,
            amount: item.amount
          }))
          this.updateStats()
        }
      } catch (error) {
        console.error('加载股票数据失败:', error)
      }
    },

    async loadIndexData() {
      try {
        const response = await axios.get('/api/v3/market/indexes')
        if (response && response.success && response.data) {
          this.marketIndexes = response.data.map(item => ({
            symbol: item.ts_code,
            name: item.name,
            value: item.value,
            change: item.change,
            changePercent: item.changePercent
          }))
        }
      } catch (error) {
        console.error('加载指数数据失败:', error)
      }
    },

    updateStats() {
      const totalStocks = this.stocks.length
      const upStocks = this.stocks.filter(s => s.changePercent > 0).length
      const downStocks = this.stocks.filter(s => s.changePercent < 0).length
      const avgChange = totalStocks > 0
        ? this.stocks.reduce((sum, s) => sum + s.changePercent, 0) / totalStocks
        : 0
      const totalAmount = this.stocks.reduce((sum, s) => sum + (s.amount || 0), 0)
      
      this.stats = {
        ...this.stats,
        totalStocks,
        upStocks,
        downStocks,
        avgChange,
        totalAmount
      }
    },

    async loadLatestSignals() {
      try {
        const response = await axios.get('/api/v2/strategy/outputs', {
          params: { limit: 3 }
        })
        if (response.success) {
          this.latestSignals = response.data || []
        }
      } catch (error) {
        console.error('加载策略信号失败:', error)
      }
    },

    initFlowChart() {
      this.$nextTick(() => {
        if (this.$refs.flowChartRef && !this.flowChart) {
          this.flowChart = echarts.init(this.$refs.flowChartRef)

          const option = {
            tooltip: {
              trigger: 'axis',
              axisPointer: { type: 'shadow' }
            },
            legend: {
              data: ['主力流入', '主力流出'],
              textStyle: { color: '#94a3b8' }
            },
            grid: {
              left: '3%',
              right: '4%',
              bottom: '3%',
              containLabel: true
            },
            xAxis: {
              type: 'category',
              data: ['周一', '周二', '周三', '周四', '周五'],
              axisLine: { lineStyle: { color: '#2a2a2a' } },
              axisLabel: { color: '#94a3b8' }
            },
            yAxis: {
              type: 'value',
              axisLine: { lineStyle: { color: '#2a2a2a' } },
              axisLabel: {
                color: '#94a3b8',
                formatter: (value) => {
                  if (value >= 100000000) return (value / 100000000).toFixed(1) + '亿'
                  if (value >= 10000) return (value / 10000).toFixed(0) + '万'
                  return value
                }
              },
              splitLine: { lineStyle: { color: '#1e293b' } }
            },
            series: [
              {
                name: '主力流入',
                type: 'bar',
                stack: '总量',
                data: [520, 732, 801, 634, 820],
                itemStyle: { color: '#ef4444' }
              },
              {
                name: '主力流出',
                type: 'bar',
                stack: '总量',
                data: [-320, -582, -490, -430, -350],
                itemStyle: { color: '#22c55e' }
              }
            ]
          }

          this.flowChart.setOption(option)
        }
      })
    },

    formatPrice(price) {
      return price?.toFixed(2) || '--'
    },

    formatPercent(value) {
      if (value === undefined || value === null) return '--'
      const sign = value >= 0 ? '+' : ''
      return `${sign}${value.toFixed(2)}%`
    },

    formatAmount(amount) {
      if (!amount) return '--'
      if (amount >= 100000000) return (amount / 100000000).toFixed(2) + '亿'
      if (amount >= 10000) return (amount / 10000).toFixed(2) + '万'
      return amount.toLocaleString()
    },

    getRankClass(index) {
      if (index === 0) return 'gold'
      if (index === 1) return 'silver'
      if (index === 2) return 'bronze'
      return ''
    },

    getActivityColor(type) {
      const colors = {
        buy: '#ef4444',
        sell: '#22c55e',
        signal: '#3b82f6',
        alert: '#f59e0b'
      }
      return colors[type] || '#64748b'
    },

    getActivityLabel(type) {
      const labels = {
        buy: '买入',
        sell: '卖出',
        signal: '信号',
        alert: '预警'
      }
      return labels[type] || type
    }
  }
}
</script>

<style scoped>
.dashboard-page {
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

/* 快捷入口工具栏样式 */
.quick-actions-bar {
  margin-bottom: 24px;
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

.quick-action-card {
  background: var(--bg-surface, #1e293b) !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  border-radius: 8px !important;
  cursor: pointer;
  transition: all 0.3s;
}

.quick-action-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-primary, #3b82f6) !important;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.quick-action-content {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px;
}

.quick-action-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.05);
  border-radius: 8px;
}

.quick-action-info {
  flex: 1;
}

.quick-action-title {
  color: var(--text-primary, #f1f5f9);
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 2px;
}

.quick-action-desc {
  color: var(--text-muted, #64748b);
  font-size: 12px;
}

@media (max-width: 1400px) {
  .quick-actions {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 1000px) {
  .quick-actions {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .quick-actions {
    grid-template-columns: 1fr;
  }
}

.dashboard-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.stat-icon {
  font-size: 32px;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.05);
  border-radius: 12px;
}

.stat-info {
  flex: 1;
}

.stat-label {
  color: var(--text-secondary, #94a3b8);
  font-size: 14px;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 4px;
}

.stat-value.up {
  color: var(--color-up, #ef4444);
}

.stat-value.down {
  color: var(--color-down, #22c55e);
}

.stat-change {
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.stat-change.up {
  color: var(--color-up, #ef4444);
}

.stat-change.down {
  color: var(--color-down, #22c55e);
}

.main-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 300px;
  gap: 16px;
}

.panel {
  background: var(--bg-surface, #1e293b);
  border-radius: 12px;
  overflow: hidden;
}

.panel-header {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.panel-content {
  padding: 16px 20px;
}

.rank-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}

.rank-item:last-child {
  border-bottom: none;
}

.rank-number {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
  background: rgba(255,255,255,0.1);
  color: var(--text-secondary, #94a3b8);
}

.rank-number.gold {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  color: #1e293b;
}

.rank-number.silver {
  background: linear-gradient(135deg, #94a3b8, #64748b);
  color: #1e293b;
}

.rank-number.bronze {
  background: linear-gradient(135deg, #d97706, #b45309);
  color: #1e293b;
}

.rank-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.stock-name {
  color: var(--text-primary, #f1f5f9);
  font-weight: 500;
}

.stock-symbol {
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.rank-price {
  color: var(--text-secondary, #94a3b8);
  font-size: 14px;
}

.rank-change {
  font-weight: 600;
  font-size: 14px;
  min-width: 70px;
  text-align: right;
}

.rank-change.up {
  color: var(--color-up, #ef4444);
}

.rank-change.down {
  color: var(--color-down, #22c55e);
}

.market-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.market-item {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}

.market-name {
  font-size: 12px;
  color: var(--text-secondary, #94a3b8);
  margin-bottom: 4px;
}

.market-value {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 2px;
}

.market-value.up {
  color: var(--color-up, #ef4444);
}

.market-value.down {
  color: var(--color-down, #22c55e);
}

.market-change {
  font-size: 12px;
}

.market-change.up {
  color: var(--color-up, #ef4444);
}

.market-change.down {
  color: var(--color-down, #22c55e);
}

.strategy-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.strategy-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
}

.strategy-icon {
  font-size: 18px;
}

.strategy-name {
  flex: 1;
  color: var(--text-primary, #f1f5f9);
}

.flow-chart {
  height: 200px;
}

.activity-panel {
  grid-column: 1 / -1;
}

.activity-item {
  display: flex;
  gap: 12px;
  align-items: center;
}

.activity-time {
  color: var(--text-muted, #64748b);
  font-size: 12px;
  min-width: 60px;
}

.activity-type {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.activity-type.buy {
  background: rgba(239, 68, 68, 0.2);
  color: var(--color-up, #ef4444);
}

.activity-type.sell {
  background: rgba(34, 197, 94, 0.2);
  color: var(--color-down, #22c55e);
}

.activity-type.signal {
  background: rgba(59, 130, 246, 0.2);
  color: var(--color-primary, #3b82f6);
}

.activity-type.alert {
  background: rgba(245, 158, 11, 0.2);
  color: var(--color-accent, #f59e0b);
}

.activity-desc {
  color: var(--text-secondary, #94a3b8);
  flex: 1;
}

.up {
  color: var(--color-up, #ef4444);
}

.down {
  color: var(--color-down, #22c55e);
}

.neutral {
  color: var(--text-muted, #64748b);
}

@media (max-width: 1200px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .main-grid {
    grid-template-columns: 1fr 1fr;
  }

  .flow-panel {
    grid-column: 1 / -1;
  }
}
</style>
