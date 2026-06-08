<template>
  <div class="dashboard-page">
    <div class="page-header">
      <h1 class="page-title">
        📊 仪表盘
      </h1>
      <div class="header-actions">
        <a-range-picker
          style="margin-right: 12px"
          @change="onDateRangeChange"
        />
        <a-button @click="refreshData">
          🔄 刷新数据
        </a-button>
      </div>
    </div>

    <!-- 快捷入口工具栏 -->
    <div class="quick-actions-bar">
      <div class="quick-actions">
        <a-card
          size="small"
          class="quick-action-card"
          hoverable
          @click="$router.push('/watchlist')"
        >
          <div class="quick-action-content">
            <span class="quick-action-icon">📈</span>
            <div class="quick-action-info">
              <div class="quick-action-title">
                自选监控
              </div>
              <div class="quick-action-desc">
                实时监控股票行情
              </div>
            </div>
          </div>
        </a-card>
        <a-card
          size="small"
          class="quick-action-card"
          hoverable
          @click="$router.push('/indicator-ide')"
        >
          <div class="quick-action-content">
            <span class="quick-action-icon">📊</span>
            <div class="quick-action-info">
              <div class="quick-action-title">
                指标IDE
              </div>
              <div class="quick-action-desc">
                策略编辑与技术分析
              </div>
            </div>
          </div>
        </a-card>
        <a-card
          size="small"
          class="quick-action-card"
          hoverable
          @click="$router.push('/backtest')"
        >
          <div class="quick-action-content">
            <span class="quick-action-icon">🎯</span>
            <div class="quick-action-info">
              <div class="quick-action-title">
                回测系统
              </div>
              <div class="quick-action-desc">
                策略回测与验证
              </div>
            </div>
          </div>
        </a-card>
        <a-card
          size="small"
          class="quick-action-card"
          hoverable
          @click="$router.push('/ai-analysis')"
        >
          <div class="quick-action-content">
            <span class="quick-action-icon">🤖</span>
            <div class="quick-action-info">
              <div class="quick-action-title">
                AI分析
              </div>
              <div class="quick-action-desc">
                智能投研与报告
              </div>
            </div>
          </div>
        </a-card>
        <a-card
          size="small"
          class="quick-action-card"
          hoverable
          @click="$router.push('/factor-manager')"
        >
          <div class="quick-action-content">
            <span class="quick-action-icon">🔧</span>
            <div class="quick-action-info">
              <div class="quick-action-title">
                因子管理
              </div>
              <div class="quick-action-desc">
                因子组合与优化
              </div>
            </div>
          </div>
        </a-card>
        <a-card
          size="small"
          class="quick-action-card"
          hoverable
          @click="$router.push('/strategy-templates')"
        >
          <div class="quick-action-content">
            <span class="quick-action-icon">📋</span>
            <div class="quick-action-info">
              <div class="quick-action-title">
                策略模板
              </div>
              <div class="quick-action-desc">
                策略模板与管理
              </div>
            </div>
          </div>
        </a-card>
        <a-card
          size="small"
          class="quick-action-card"
          hoverable
          @click="$router.push('/reports-center')"
        >
          <div class="quick-action-content">
            <span class="quick-action-icon">📑</span>
            <div class="quick-action-info">
              <div class="quick-action-title">
                报告中心
              </div>
              <div class="quick-action-desc">
                策略报告与导出
              </div>
            </div>
          </div>
        </a-card>
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
        />
      </div>
    </div>

    <div class="dashboard-content">
      <!-- 概览统计卡片 -->
      <div class="stats-grid">
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
        <div class="panel rank-panel">
          <div class="panel-header">
            <span class="panel-title">📊 涨跌幅排行</span>
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
            <span class="panel-title">🌐 市场概况</span>
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
            <span class="panel-title">🔄 策略流程</span>
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
            <span class="panel-title">📋 最近活动</span>
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
      @close="signalDetailVisible = false"
    />
  </div>
          <DisclaimerFooter />
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
import DisclaimerFooter from '@/components/DisclaimerFooter'

export default {
  name: 'Dashboard',
  components: { ReloadOutlined,
    PipelineFlow,
    StrategySignalPanel,
    SignalDetailModal,
    KLineChart,
    AiSignalBus,
    ResonancePanel, DisclaimerFooter},
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
          this.latestSignals = (signalData.signals || []).slice(0, 6)
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

        // 兜底假数据
        if (this.rankList.length === 0) {
          this.rankList = this._mockRankData()
        }
        if (this.marketIndexes.length === 0) {
          this.marketIndexes = this._mockMarketData()
        }
        if (this.latestSignals.length === 0) {
          this.latestSignals = this._mockSignals()
        }
        if (this.recentActivities.length === 0) {
          this.recentActivities = this._mockActivities()
        }
      } catch (e) {
        console.warn('Dashboard 数据加载失败, 使用假数据:', e)
        this.rankList = this._mockRankData()
        this.marketIndexes = this._mockMarketData()
        this.latestSignals = this._mockSignals()
        this.recentActivities = this._mockActivities()
      } finally {
        this.loading = false
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

    onDateRangeChange() {},

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
    getActivityLabel(type) {
      const labels = { buy: '关注信号', sell: '风险退出信号', signal: '信号', alert: '预警' }
      return labels[type] || type
    },

    _mockRankData() {
      const stocks = [
        { name: '平安银行', symbol: '000001.SZ', price: 12.34, changePercent: 3.21 },
        { name: '万科A', symbol: '000002.SZ', price: 15.67, changePercent: 2.56 },
        { name: '浦发银行', symbol: '600000.SH', price: 8.90, changePercent: -1.23 },
        { name: '贵州茅台', symbol: '600519.SH', price: 1850.00, changePercent: 1.89 },
        { name: '五粮液', symbol: '000858.SZ', price: 145.20, changePercent: -0.67 },
      ]
      return stocks
    },
    _mockMarketData() {
      return [
        { symbol: '000001.SH', name: '上证指数', value: 3150.42, changePercent: 0.56, change: 17.52 },
        { symbol: '399001.SZ', name: '深证成指', value: 10200.67, changePercent: 0.89, change: 90.23 },
        { symbol: '399006.SZ', name: '创业板指', value: 2180.56, changePercent: -0.34, change: -7.45 },
        { symbol: '000688.SH', name: '科创50', value: 950.23, changePercent: 0.12, change: 1.14 },
      ]
    },
    _mockSignals() {
      return [
        { id: 1, ts_code: '000001.SZ', stock_name: '平安银行', type: 'buy', signal_strength: 'strong', signal_type: 'volbreak', strategy_name: '量价突破', signal_detail: '放量突破20日均线', signal_time: '2026-06-05 10:30', confidence: 85 },
        { id: 2, ts_code: '600519.SH', stock_name: '贵州茅台', type: 'sell', signal_strength: 'moderate', signal_type: 'macd_dead', strategy_name: 'MACD死叉', signal_detail: '日线MACD死叉', signal_time: '2026-06-05 09:45', confidence: 72 },
        { id: 3, ts_code: '000002.SZ', stock_name: '万科A', type: 'buy', signal_strength: 'weak', signal_type: 'support', strategy_name: '支撑反弹', signal_detail: '触及前期支撑位', signal_time: '2026-06-05 11:00', confidence: 60 },
      ]
    },
    _mockActivities() {
      return [
        { time: '10:30', type: 'buy', desc: '平安银行 — 放量突破关注信号' },
        { time: '09:45', type: 'sell', desc: '贵州茅台 — MACD死叉风险退出信号' },
        { time: '09:32', type: 'signal', desc: '万科A — 支撑位反弹信号' },
        { time: '09:15', type: 'alert', desc: '数据源已切换至备用通道' },
      ]
    },
  },
}
</script>

<style scoped>
.dashboard-page {
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
}

.quick-actions-bar {
  margin-bottom: 24px;
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

.quick-action-card {
  background: var(--bg-surface) !important;
  border: 1px solid var(--border-default) !important;
  border-radius: var(--radius-md) !important;
  cursor: pointer;
  transition: all 0.3s;
}

.quick-action-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-brand-500) !important;
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
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
}

.quick-action-info {
  flex: 1;
}

.quick-action-title {
  color: var(--text-primary);
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 2px;
}

.quick-action-desc {
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 1400px) { .quick-actions { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 1000px) { .quick-actions { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .quick-actions { grid-template-columns: 1fr; } }

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
</style>
