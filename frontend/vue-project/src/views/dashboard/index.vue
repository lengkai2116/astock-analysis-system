<template>
  <div class="dashboard-page">
    <div class="page-header">
      <h1 class="page-title">
        仪表盘
      </h1>
      <div class="header-actions">
        <a-range-picker
          style="margin-right: 12px"
          @change="onDateRangeChange"
        />
        <a-button @click="refreshData">
          刷新数据
        </a-button>
      </div>
    </div>


    <!-- 策略信号展示区域 -->
    <div
      v-if="latestSignals.length > 0"
      class="strategy-signals-section"
    >
      <div class="section-header">
        <h3 class="section-title">
          📡 最新策略信号
        </h3>
        <a-button
          type="link"
          @click="$router.push('/strategy-templates')"
        >
          查看更多
        </a-button>
      </div>
      <div class="signals-grid">
        <StrategySignalPanel
          v-for="signal in latestSignals"
          :key="signal.id"
          :signal-data="signal"
          @show-detail="handleSignalDetail"
          @view-detail="handleViewFullReport"
          @backtest="handleSignalBacktest"
        />
      </div>
    </div>

    <div class="dashboard-content">
      <!-- 概览统计卡片 -->
      <a-skeleton v-show="loadingAreas.stats" active :paragraph="{ rows: 3 }" class="section-skeleton" />
      <div v-show="!loadingAreas.stats" class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon up">
            📈
          </div>
          <div class="stat-info">
            <div class="stat-label">
              自选股总数
            </div>
            <div class="stat-value">
              {{ stats.totalStocks }}
            </div>
            <div class="stat-change up">
              <span>上涨</span> {{ stats.upStocks }} 只
            </div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon down">
            📉
          </div>
          <div class="stat-info">
            <div class="stat-label">
              平均涨跌幅
            </div>
            <div
              class="stat-value"
              :class="avgChangeClass"
            >
              {{ formatPercent(stats.avgChange) }}
            </div>
            <div class="stat-change neutral">
              {{ stats.upStocks }} 涨 / {{ stats.downStocks }} 跌
            </div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon primary">
            💰
          </div>
          <div class="stat-info">
            <div class="stat-label">
              总成交额
            </div>
            <div class="stat-value">
              {{ formatAmount(stats.totalAmount) }}
            </div>
            <div class="stat-change neutral">
              实时数据更新中
            </div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon accent">
            🎯
          </div>
          <div class="stat-info">
            <div class="stat-label">
              策略信号
            </div>
            <div class="stat-value">
              {{ stats.activeSignals }}
            </div>
            <div class="stat-change neutral">
              {{ stats.buySignals }} 关注信号 / {{ stats.sellSignals }} 风险退出信号
            </div>
          </div>
        </div>
      </div>

      <!-- 主要内容区 -->
      <div class="main-grid">
        <!-- 涨跌幅排行 -->

        <!-- 涨跌幅排行 -->
        <div class="panel rank-panel">
          <div class="panel-header">
            <span class="panel-title">涨跌幅排行</span>
            <a-radio-group
              v-model="rankType"
              size="small"
            >
              <a-radio-button value="change">
                涨幅榜
              </a-radio-button>
              <a-radio-button value="changePercent">
                跌幅榜
              </a-radio-button>
            </a-radio-group>
          </div>
          <div class="panel-content">
            <div
              v-for="(stock, index) in rankList"
              :key="stock.symbol"
              class="rank-item"
            >
              <span
                class="rank-number"
                :class="getRankClass(index)"
              >{{ index + 1 }}</span>
              <div class="rank-info">
                <span class="stock-name">{{ stock.name }}</span>
                <span class="stock-symbol">{{ stock.symbol }}</span>
              </div>
              <span class="rank-price">{{ formatPrice(stock.price) }}</span>
              <span
                class="rank-change"
                :class="stock.changePercent >= 0 ? 'up' : 'down'"
              >
                {{ formatPercent(stock.changePercent) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 市场概况 -->
        <div class="panel market-panel">
          <div class="panel-header">
            <span class="panel-title">市场概况</span>
          </div>
          <div class="panel-content">
            <div class="market-grid">
              <div
                v-for="index in marketIndexes"
                :key="index.symbol"
                class="market-item"
              >
                <div class="market-name">
                  {{ index.name }}
                </div>
                <div
                  class="market-value"
                  :class="index.change >= 0 ? 'up' : 'down'"
                >
                  {{ formatPrice(index.value) }}
                </div>
                <div
                  class="market-change"
                  :class="index.change >= 0 ? 'up' : 'down'"
                >
                  {{ formatPercent(index.changePercent) }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 策略流程 -->
        <div class="panel flow-panel">
          <div class="panel-header">
            <span class="panel-title">策略流程</span>
          </div>
          <div class="panel-content">
            <div class="flow-chart">
              <PipelineFlow :compact="true" />
            </div>
          </div>
        </div>

        <!-- 共振评分 (150§5.3) -->
        <div class="panel resonance-panel-wrapper">
          <ResonancePanel
            :overall-score="resonance.overallScore"
            :dimensions="resonance.dimensions"
          />
        </div>

        <!-- 最近活动 -->
        <div class="panel activity-panel">
          <div class="panel-header">
            <span class="panel-title">最近活动</span>
          </div>
          <div class="panel-content">
            <div class="activity-list">
              <div
                v-for="(activity, index) in recentActivities"
                :key="index"
                class="activity-item"
              >
                <span class="activity-time">{{ activity.time }}</span>
                <span
                  class="activity-type"
                  :class="activity.type"
                >{{ getActivityLabel(activity.type) }}</span>
                <span class="activity-desc">{{ activity.desc }}</span>
              </div>
              <div
                v-if="recentActivities.length === 0"
                class="empty-placeholder"
              >
                暂无活动记录
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ====== 多K线分屏 (150§3.1) ====== -->
      <div class="chart-grid-section">
        <div class="section-header">
          <h3 class="section-title">
            📈 K线图表
          </h3>
          <div class="chart-controls">
            <a-select
              v-model:value="stockSearch"
              :show-search="true"
              :filter-option="false"
              placeholder="搜索并切换股票..."
              style="width: 180px; margin-right: 8px;"
              :options="stockSearchResults"
              @search="onStockSearch"
              @change="onStockSelect"
              allow-clear
            />
            <a-radio-group
              v-model:value="chartLayout"
              size="small"
              @change="resetChartGrid"
            >
              <a-radio-button value="single">
                单图
              </a-radio-button>
              <a-radio-button value="dual-v">
                双图
              </a-radio-button>
              <a-radio-button value="triple">
                三图
              </a-radio-button>
              <a-radio-button value="quad">
                四图
              </a-radio-button>
            </a-radio-group>
            <a-select
              v-model:value="chartPeriod"
              size="small"
              style="width: 80px; margin-left: 8px;"
              @change="refreshCharts"
            >
              <a-select-option value="D">
                日线
              </a-select-option>
              <a-select-option value="W">
                周线
              </a-select-option>
              <a-select-option value="M">
                月线
              </a-select-option>
            </a-select>
          </div>
        </div>
        <div
          class="chart-grid"
          :class="`chart-grid--${chartLayout}`"
        >
          <div
            v-for="(chart, idx) in chartCells"
            :key="idx"
            class="chart-cell"
            :class="{ 'chart-cell--active': activeChartIndex === idx }"
            @click="activeChartIndex = idx"
          >
            <div class="chart-cell__header">
              <span class="chart-cell__symbol">{{ chart.symbol }}</span>
              <a-select
                v-model:value="chart.period"
                size="small"
                style="width: 70px;"
                @change="chart.period = $event"
              >
                <a-select-option value="D">
                  日线
                </a-select-option>
                <a-select-option value="W">
                  周线
                </a-select-option>
                <a-select-option value="M">
                  月线
                </a-select-option>
              </a-select>
            </div>
            <KLineChart
              :ref="el => registerChartRef(el, idx)"
              :key="`chart-${idx}`"
              :ts-code="chart.symbol"
              :period="chart.period"
              :indicators="chart.indicators"
              :height="chartHeight"
              :chart-type="chart.chartType"
              :chart-id="`dashboard-chart-${idx}`"
              :sync-crosshair="chartCells.length > 1"
            />
          </div>
        </div>
        <!-- AI 信号总线 (150§5.1) -->
        <AiSignalBus
          v-if="aiSignals.length > 0"
          :signals="aiSignals"
          style="margin-top: 16px;"
        />
      </div>
    </div>

    <!-- Signal Detail Modal -->
    <SignalDetailModal
      v-if="signalDetailVisible"
      :visible="signalDetailVisible"
      :ts-code="signalDetailData.ts_code"
      :stock-name="signalDetailData.stock_name"
      :signals="signalDetailData.signals"
      @update:visible="signalDetailVisible = $event"
    />
  </div>
</template>

<script>
import { ReloadOutlined } from '@ant-design/icons-vue'
import { mapState } from 'pinia'
import { useAppStore } from '@/stores'
import PipelineFlow from '@/components/StockScreener/PipelineFlow'
import StrategySignalPanel from '@/components/StrategySignalPanel'
import SignalDetailModal from '@/components/StockScreener/SignalDetailModal'
import KLineChart from '@/components/KLineChart'
import AiSignalBus from '@/components/AiSignalBus'
import ResonancePanel from '@/components/ResonancePanel'
import dataService from '@/services/dataService'

export default {
  name: 'Dashboard',
  components: { ReloadOutlined,
    PipelineFlow,
    StrategySignalPanel,
    SignalDetailModal,
    KLineChart,
    AiSignalBus,
    ResonancePanel},
  data() {
    return {
      loading: true,
      rankType: 'change',
      stats: {
        totalStocks: 12,
        upStocks: 7,
        downStocks: 5,
        avgChange: 1.23,
        totalAmount: 12580000000,
        activeSignals: 3,
        buySignals: 2,
        sellSignals: 1,
      },
      rankList: [],
      marketIndexes: [],
      latestSignals: [],
      recentActivities: [],
      signalDetailVisible: false,
      signalDetailData: { ts_code: '', stock_name: '', signals: [] },

      // 多K线分屏 (150§3.1)
      chartLayout: 'single',
      chartPeriod: 'D',
      activeChartIndex: 0,
      chartRefs: {},
      chartCells: [
        { symbol: '000001.SZ', period: 'D', indicators: ['ma5', 'ma20', 'macd', 'rsi', 'vol'], chartType: 'candle' },
      ],
      stockSearch: undefined,
      stockSearchResults: [],
      chartHeight: 480,

      // AI 信号 (150§5.1)
      aiSignals: [],

      // 共振评分 (150§5.3)
      resonance: {
        overallScore: 0,
        dimensions: [],
      },
    }
  },
  computed: {
    avgChangeClass() {
      return this.stats.avgChange >= 0 ? 'up' : 'down'
    },
  },
  async mounted() {
    await this.loadData()

    // 监听全局数据刷新事件
    window.addEventListener('app:refresh-data', this.refreshData)
  },
  beforeUnmount() {
    window.removeEventListener('app:refresh-data', this.refreshData)
  },
  methods: {
    registerChartRef(el, idx) {
      if (el) this.chartRefs[idx] = el
    },

    async loadData() {
      this.loading = true
      try {
        const [watchlistData, marketData, signalData, aiData] = await Promise.all([
          dataService.getWatchlistData().catch(() => null),
          dataService.getMarketOverview().catch(() => null),
          dataService.getStrategySignals().catch(() => null),
          dataService.getAIAnalysisSignals().catch(() => null),
        ])

        if (watchlistData) {
          this.stats.totalStocks = watchlistData.stocks?.length || 0
          this.stats.upStocks = watchlistData.up_count || 0
          this.stats.downStocks = watchlistData.down_count || 0
          this.stats.avgChange = watchlistData.avg_change || 0
          this.stats.totalAmount = watchlistData.total_amount || 0
          this.rankList = (watchlistData.stocks || []).slice(0, 10).map(s => ({
            ...s,
            changePercent: s.changePercent || s.pct_chg || 0,
          }))
        }

        if (marketData) {
          this.marketIndexes = marketData.indexes || []
        }

        if (signalData) {
          // 转换后端信号格式 -> StrategySignalPanel 期望的格式
          const rawSignals = signalData.signals || []
          this.latestSignals = rawSignals.slice(0, 6).map(s => {
            const sigType = (s.signal_type || '').toLowerCase()
            const indicators = s.indicators || {}
            // 使用 stock_name 展示个股名称，策略名称回退到 strategy_type 或 indicators
            const stockLabel = s.stock_name || s.ts_code || ''
            const strategyLabel = indicators.strategy_name || s.strategy_type || '策略信号'
            return {
              id: s.id,
              ts_code: s.ts_code || '',
              stock_name: stockLabel,
              strategy_name: `${stockLabel} · ${strategyLabel}`,
              signal: sigType === 'bullish' ? 'bullish' : sigType === 'watch' ? 'watch' : sigType === 'bearish' ? 'bearish' : 'neutral',
              signal_date: s.signal_date || '',
              confidence: s.confidence || 0,
              entry_zone: s.entry_price ? [s.entry_price] : null,
              risk_line: s.stop_loss || null,
              target_zone: s.take_profit ? [s.take_profit] : null,
              position_suggestion: indicators.position_suggestion || '',
              holding_period: indicators.holding_period || '',
              evidence: s.reason ? [s.reason] : [],
              risk_notes: [],
            }
          })
          this.stats.activeSignals = signalData.active_count || 0
          this.stats.buySignals = signalData.buy_count || 0
          this.stats.sellSignals = signalData.sell_count || 0
        }

        if (aiData) {
          this.aiSignals = aiData.signals || []
          this.resonance = {
            overallScore: aiData.resonance?.overall_score || 0,
            dimensions: (aiData.resonance?.dimensions || []).map(d => ({
              id: d.id,
              name: d.name,
              score: d.score,
              weight: d.weight,
              color: d.score >= 70 ? 'var(--signal-bullish, #EF4444)' : d.score >= 40 ? 'var(--signal-watch, #F59E0B)' : 'var(--signal-bearish, #22C55E)',
            })),
          }
        }

        // 数据暂不可用时显示空状态
      } catch (e) {
        console.warn('Dashboard 数据加载失败', e)
      } finally {
        this.loading = false
        this.loadingAreas = {
          stats: false,
          rank: false,
          market: false,
          signals: false,
          activities: false
        }
      }
    },

    refreshData() {
      this.loadData()
    },

    resetChartGrid() {
      const count = { single: 1, 'dual-v': 2, triple: 3, quad: 4 }[this.chartLayout] || 1
      const symbols = ['000001.SZ', '600519.SH', '000002.SZ', '600036.SH']
      const chartTypes = ['candle', 'area', 'line', 'candle']

      this.chartCells = Array.from({ length: count }, (_, i) => ({
        symbol: symbols[i] || symbols[0],
        period: this.chartPeriod,
        indicators: ['ma5', 'ma20', 'macd', 'rsi', 'vol'],
        chartType: chartTypes[i] || 'candle',
      }))

      // 动态计算高度
      this.chartHeight = count <= 2 ? 480 : 360
    },

    refreshCharts() {
      this.chartCells.forEach(c => { c.period = this.chartPeriod })
    },

    onDateRangeChange(dates) {
      if (dates && dates.length === 2) {
        this.$message?.info(`日期范围已更新: ${dates[0].format('YYYY-MM-DD')} ~ ${dates[1].format('YYYY-MM-DD')}`);
        this.refreshData();
      }
    },

    // ... helper methods from original
    formatPrice(value) {
      if (value === undefined || value === null) return '--'
      return value.toFixed(2)
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
    handleSignalDetail(data) {
      this.signalDetailData = {
        ts_code: data.ts_code || '',
        stock_name: data.stock_name || '',
        signals: data.signals || [],
      }
      this.signalDetailVisible = true
    },

    handleViewFullReport(data) {
      // 跳转到个股策略分析页查看完整 K 线和信号
      this.$router.push('/indicator-ide')
    },

    handleSignalBacktest(data) {
      // 跳转到回测系统
      this.$router.push('/backtest')
    },
    async onStockSearch(value) {
      if (!value || value.length < 1) { this.stockSearchResults = []; return }
      try {
        const { searchStocks } = await import('@/services/chartService')
        const results = await searchStocks(value, 10)
        this.stockSearchResults = results.map(r => ({
          value: r.ts_code,
          label: `${r.ts_code} ${r.name}`,
        }))
      } catch { this.stockSearchResults = [] }
    },

    onStockSelect(value) {
      if (value) {
        this.chartCells[this.activeChartIndex] = {
          ...this.chartCells[this.activeChartIndex],
          symbol: value,
        }
        this.stockSearch = undefined
        this.stockSearchResults = []
      }
    },

    getActivityLabel(type) {
      const labels = { buy: '关注信号', sell: '风险退出信号', signal: '信号', alert: '预警' }
      return labels[type] || type
    },

  },
}
</script>

<style scoped>
.dashboard-page {
  width: 100%;
  padding: 16px 24px;
  min-height: 100vh;
  background: var(--bg-canvas);
  transition: background 0.3s ease;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-default);
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
  max-width: 100%;
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
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 20px;
  display: flex;
  gap: 16px;
  align-items: flex-start;
  transition: background 0.3s ease;
}

.stat-icon {
  font-size: 32px;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-subtle);
  border-radius: var(--radius-lg);
}

.stat-info { flex: 1; }
.stat-label { color: var(--text-secondary); font-size: 14px; margin-bottom: 4px; }
.stat-value { font-size: 28px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.stat-value.up { color: var(--color-up); }
.stat-value.down { color: var(--color-down); }
.stat-change { font-size: 12px; color: var(--text-muted); }
.stat-change.up { color: var(--color-up); }
.stat-change.down { color: var(--color-down); }

.main-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
}

.panel {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: background 0.3s ease;
}

.panel-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.panel-content { padding: 16px 20px; }

.rank-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-default);
}

.rank-item:last-child { border-bottom: none; }

.rank-number {
  width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 50%;
  font-size: 12px; font-weight: 600;
  background: var(--bg-muted);
  color: var(--text-secondary);
}
.rank-number.gold { background: linear-gradient(135deg, #fbbf24, #f59e0b); color: var(--text-inverse, #1e293b); }
.rank-number.silver { background: linear-gradient(135deg, #94a3b8, #64748b); color: var(--text-inverse, #1e293b); }
.rank-number.bronze { background: linear-gradient(135deg, #d97706, #b45309); color: var(--text-inverse, #1e293b); }

.rank-info { flex: 1; display: flex; flex-direction: column; }
.stock-name { color: var(--text-primary); font-weight: 500; }
.stock-symbol { font-size: 12px; color: var(--text-muted); }
.rank-price { color: var(--text-secondary); font-size: 14px; }
.rank-change { font-weight: 600; font-size: 14px; min-width: 70px; text-align: right; }
.rank-change.up { color: var(--color-up); }
.rank-change.down { color: var(--color-down); }

.market-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.market-item { background: var(--bg-subtle); border-radius: var(--radius-md); padding: 12px; text-align: center; }
.market-name { font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }
.market-value { font-size: 18px; font-weight: 600; margin-bottom: 2px; }
.market-value.up { color: var(--color-up); }
.market-value.down { color: var(--color-down); }
.market-change { font-size: 12px; }
.market-change.up { color: var(--color-up); }
.market-change.down { color: var(--color-down); }

.flow-chart { height: 200px; }

.resonance-panel-wrapper {
  /* resonance panel is a self-contained component */
}

.activity-item {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 6px 0;
}
.activity-time { color: var(--text-muted); font-size: 12px; min-width: 60px; }
.activity-type {
  padding: 2px 8px; border-radius: var(--radius-xs);
  font-size: 12px; font-weight: 500;
}
.activity-type.buy { background: rgba(239, 68, 68, 0.2); color: var(--color-up); }
.activity-type.sell { background: rgba(34, 197, 94, 0.2); color: var(--color-down); }
.activity-type.signal { background: rgba(59, 130, 246, 0.2); color: var(--color-brand-500); }
.activity-type.alert { background: rgba(245, 158, 11, 0.2); color: var(--signal-watch); }
.activity-desc { color: var(--text-secondary); flex: 1; }
.empty-placeholder { color: var(--text-muted); font-size: 13px; padding: 12px; text-align: center; }

/* ====== 多K线分屏 (150§3.1) ====== */
.chart-grid-section {
  margin-top: 24px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.chart-controls {
  display: flex;
  align-items: center;
  gap: 4px;
}

.chart-grid {
  display: grid;
  gap: 16px;
}

.chart-grid--single { grid-template-columns: 1fr; }
.chart-grid--dual-v { grid-template-columns: 1fr 1fr; }
.chart-grid--triple { grid-template-columns: 1fr 1fr; grid-template-rows: auto auto; }
.chart-grid--quad { grid-template-columns: 1fr 1fr; }

.chart-cell {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: border-color 0.3s;
}

.chart-cell--active {
  border-color: var(--color-brand-500);
  box-shadow: 0 0 0 1px var(--color-brand-500);
}

.chart-cell__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-default);
}

.chart-cell__symbol {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

@media (max-width: 1200px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .main-grid { grid-template-columns: 1fr 1fr; }
  .flow-panel { grid-column: 1 / -1; }
  .chart-grid--dual-v { grid-template-columns: 1fr; }
  .chart-grid--triple { grid-template-columns: 1fr; }
  .chart-grid--quad { grid-template-columns: 1fr; }
}

.strategy-signals-section {
  margin-bottom: 24px;
}

.signals-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 12px;
}

.up { color: var(--color-up); }
.down { color: var(--color-down); }
.neutral { color: var(--text-muted); }

/* Ant Design DatePicker dark theme fixes via :deep() */
:deep(.ant-picker) {
  background: transparent !important;
  border-color: var(--border-default) !important;
}
:deep(.ant-picker-input > input) {
  color: var(--text-primary) !important;
}
:deep(.ant-picker-suffix) {
  color: var(--text-secondary) !important;
}
:deep(.ant-picker-clear) {
  background: var(--bg-surface) !important;
  color: var(--text-muted) !important;
}

.section-skeleton { padding: 16px; margin-bottom: 16px; }
</style>
