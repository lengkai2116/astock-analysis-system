<template>
  <div class="indicator-ide theme-dark">
    <div class="ide-main">
      <!-- 左侧策略选择区域 -->
      <div class="ide-left">
        <!-- 策略选择面板 -->
        <div class="strategy-panel">
          <div class="panel-header">
            <span class="panel-title">📋 策略选择</span>
            <a-button size="small" @click="showStrategyConfig = true">⚙️ 配置</a-button>
          </div>

          <div class="strategy-list">
            <div
              v-for="strategy in strategyLibrary"
              :key="strategy.id"
              class="strategy-item"
              :class="{ active: strategy.enabled }"
            >
              <div class="strategy-header">
                <a-checkbox
                  v-model="strategy.enabled"
                  @change="toggleStrategy(strategy)"
                />
                <span class="strategy-icon">{{ strategy.icon }}</span>
                <span class="strategy-name">{{ strategy.name }}</span>
                <a-tooltip :title="strategy.description">
                  <a-icon type="info-circle" class="info-icon" />
                </a-tooltip>
              </div>

              <div v-if="strategy.enabled && strategy.params" class="strategy-params">
                <div 
                  v-for="(value, key) in strategy.params" 
                  :key="key" 
                  class="param-item"
                >
                  <span class="param-label">{{ formatParamLabel(key) }}:</span>
                  <a-input-number
                    v-if="typeof value === 'number'"
                    :value="value"
                    size="small"
                    style="width: 80px"
                    @change="updateParam(strategy, key, $event)"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 策略建议面板 -->
        <div class="advice-panel">
          <div class="panel-header">
            <span class="panel-title">📊 策略建议</span>
            <a-tag :color="consensusColor">{{ consensus }}</a-tag>
          </div>

          <div v-if="analyzing" class="loading-state">
            <a-spin size="large" />
            <span>策略分析中...</span>
          </div>

          <div v-else class="advice-list">
            <div
              v-for="advice in strategyAdvices"
              :key="advice.strategyId"
              class="advice-item"
            >
              <div class="advice-header">
                <span class="strategy-name">{{ advice.strategyName }}</span>
                <a-tag
                  :color="getSignalColor(advice.signalType)"
                  class="signal-tag"
                >
                  {{ getSignalLabel(advice.signalType) }}
                </a-tag>
                <div class="confidence">
                  置信度: {{ Math.round(advice.confidence * 100) }}%
                  <a-progress
                    :percent="advice.confidence * 100"
                    :stroke-color="getSignalColor(advice.signalType)"
                    size="small"
                    style="width: 60px"
                  />
                </div>
              </div>

              <div class="advice-body">
                <div v-if="advice.priceTarget" class="price-info">
                  <span class="label">目标价:</span>
                  <span class="value up">¥{{ advice.priceTarget.toFixed(2) }}</span>
                </div>
                <div v-if="advice.stopLoss" class="price-info">
                  <span class="label">止损位:</span>
                  <span class="value down">¥{{ advice.stopLoss.toFixed(2) }}</span>
                </div>
                <div v-if="advice.positionSize" class="price-info">
                  <span class="label">建议仓位:</span>
                  <span class="value">{{ (advice.positionSize * 100).toFixed(0) }}%</span>
                </div>

                <div class="reasons">
                  <div class="reasons-title">核心逻辑:</div>
                  <ul class="reasons-list">
                    <li v-for="(reason, idx) in advice.reasons" :key="idx">
                      • {{ reason }}
                    </li>
                  </ul>
                </div>
              </div>
            </div>
          </div>

          <div class="composite-panel" v-if="strategyAdvices.length > 1">
            <div class="composite-title">🔍 综合研判</div>

            <div class="vote-bar">
              <div
                v-for="(count, type) in composite.signalCount"
                :key="type"
                :style="{
                  flex: count,
                  background: getSignalColor(type)
                }"
                class="vote-segment"
              >
                {{ getSignalLabel(type) }} {{ count }}
              </div>
            </div>

            <div class="composite-summary">
              <div class="summary-item">
                <span class="label">建议操作:</span>
                <span class="value">{{ composite.recommendation }}</span>
              </div>
              <div class="summary-item">
                <span class="label">建议仓位:</span>
                <span class="value">{{ (composite.suggestedPosition * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧面板 -->
      <div class="ide-right ide-right--workspace">
        <!-- 顶部导航 -->
        <div class="top-nav">
          <div class="nav-items">
            <router-link to="/" class="nav-item" active-class="active">📈 指标IDE</router-link>
            <router-link to="/watchlist" class="nav-item" active-class="active">📊 自选监控</router-link>
            <router-link to="/ai-analysis" class="nav-item" active-class="active">🤖 AI分析</router-link>
          </div>
        </div>

        <!-- 工作区 Tab -->
        <div class="ide-workspace-tabs">
          <div
            class="ide-workspace-tab"
            :class="{ active: ideWorkspaceTab === 'chart' }"
            @click="ideWorkspaceTab = 'chart'"
          >
            K线图表
          </div>
          <div
            class="ide-workspace-tab"
            :class="{ active: ideWorkspaceTab === 'backtest' }"
            @click="ideWorkspaceTab = 'backtest'"
          >
            回测分析
          </div>
        </div>

        <!-- 图表工作区 -->
        <div v-show="ideWorkspaceTab === 'chart'" class="ide-workspace-pane">
          <div class="chart-panel">
            <!-- 工具栏 -->
            <div class="chart-panel-toolbar">
              <div class="chart-panel-toolbar-top">
                <span class="chart-panel-toolbar-title">K线图表</span>
                <div class="chart-panel-toolbar-top-actions">
                  <a-tooltip :title="leftPanelCollapsed ? '显示策略面板' : '隐藏策略面板'">
                    <a-button
                      size="small"
                      class="chart-panel-icon-btn"
                      @click="leftPanelCollapsed = !leftPanelCollapsed"
                    >
                      <a-icon :type="leftPanelCollapsed ? 'menu-unfold' : 'menu-fold'" />
                    </a-button>
                  </a-tooltip>
                  <a-tooltip title="全屏">
                    <a-button size="small" class="chart-panel-fs-btn" @click="toggleFullscreen">
                      <a-icon :type="isFullscreen ? 'fullscreen-exit' : 'fullscreen'" />
                    </a-button>
                  </a-tooltip>
                </div>
              </div>
              <div class="chart-panel-toolbar-controls">
                <!-- 自选标的 -->
                <div class="ide-toolbar-group ide-toolbar-group--watchlist">
                  <span class="ide-toolbar-label">自选股</span>
                  <a-select
                    v-model="selectedWatchlistKey"
                    class="chart-panel-watchlist-select"
                    size="small"
                    show-search
                    @change="handleWatchlistChange"
                  >
                    <a-select-option
                      v-for="w in watchlist"
                      :key="`${w.market}:${w.symbol}`"
                      :value="`${w.market}:${w.symbol}`"
                    >
                      <span class="wl-opt-tag" :class="'wl-mkt-' + (w.market || '').toLowerCase()">
                        {{ marketLabel(w.market) }}
                      </span>
                      <strong>{{ w.symbol }}</strong>
                      <span v-if="w.name" class="wl-opt-name">{{ w.name }}</span>
                    </a-select-option>
                  </a-select>
                </div>

                <!-- K线周期 -->
                <div class="ide-toolbar-group ide-toolbar-group--tf">
                  <span class="ide-toolbar-label">周期</span>
                  <div class="tf-group">
                    <a-radio-group v-model="timeframe" size="small">
                      <a-radio-button value="1m">1m</a-radio-button>
                      <a-radio-button value="5m">5m</a-radio-button>
                      <a-radio-button value="15m">15m</a-radio-button>
                      <a-radio-button value="30m">30m</a-radio-button>
                      <a-radio-button value="1H">1H</a-radio-button>
                      <a-radio-button value="4H">4H</a-radio-button>
                      <a-radio-button value="1D">1D</a-radio-button>
                      <a-radio-button value="1W">1W</a-radio-button>
                    </a-radio-group>
                  </div>
                </div>

                <!-- 指标选择 -->
                <div class="ide-toolbar-group ide-toolbar-group--indicator">
                  <span class="ide-toolbar-label">技术指标</span>
                  <a-dropdown :trigger="['click']">
                    <a-button size="small" class="ide-indicator-multiselect-trigger">
                      <span>{{ indicatorSummary }}</span>
                      <a-icon type="down" />
                    </a-button>
                    <div slot="overlay" class="ide-indicator-overlay" @mousedown.stop @click.stop>
                      <div class="ide-indicator-overlay-hint">点击指标添加到图表</div>
                      <div class="ide-indicator-overlay-list">
                        <div v-for="ind in indicatorButtons" :key="ind.id" class="ide-indicator-row">
                          <a-checkbox
                            :checked="isIndicatorActive(ind.id)"
                            @change="e => toggleIndicator(ind, e.target.checked)"
                          />
                          <span class="ide-indicator-name">{{ ind.name }}</span>
                        </div>
                      </div>
                    </div>
                  </a-dropdown>
                </div>
              </div>
            </div>

            <!-- 图表内容区 -->
            <div class="chart-panel-inner">
              <!-- 画线工具栏 -->
              <div class="drawing-toolbar">
                <div
                  v-for="tool in drawingTools"
                  :key="tool.name"
                  class="drawing-tool-btn"
                  :class="{ active: activeDrawingTool === tool.name }"
                  :title="tool.title"
                  @click="selectDrawingTool(tool.name)"
                >
                  <a-icon :type="tool.icon" />
                </div>
                <a-divider type="vertical" />
                <div class="drawing-tool-btn" title="清除全部" @click="clearAllDrawings">
                  <a-icon type="delete" />
                </div>
              </div>

              <!-- 激活指标显示栏 -->
              <div v-if="activeIndicators.length" class="indicator-active-bar">
                <div
                  v-for="indicator in activeIndicators"
                  :key="indicator.instanceId"
                  class="indicator-active-chip"
                  :class="{ 'indicator-active-chip--hidden': indicator.visible === false }"
                >
                  <span class="indicator-active-chip__label">{{ formatIndicatorLabel(indicator) }}</span>
                  <a-tooltip :title="indicator.visible === false ? '显示' : '隐藏'">
                    <a-icon
                      :type="indicator.visible === false ? 'eye-invisible' : 'eye'"
                      class="indicator-active-chip__action"
                      @click.stop="toggleIndicatorVisibility(indicator)"
                    />
                  </a-tooltip>
                  <a-tooltip title="删除">
                    <a-icon
                      type="close"
                      class="indicator-active-chip__action"
                      @click.stop="removeIndicatorInstance(indicator)"
                    />
                  </a-tooltip>
                </div>
              </div>

              <!-- K线图表容器 -->
              <div id="kline-chart-container" class="kline-chart-container"></div>

              <!-- 加载遮罩 -->
              <div v-if="loading" class="chart-overlay">
                <a-spin size="large">
                  <a-icon slot="indicator" type="loading" style="font-size: 24px; color: #3B82F6" spin />
                </a-spin>
              </div>

              <!-- 错误提示 -->
              <div v-if="error" class="chart-overlay">
                <div class="error-box">
                  <a-icon type="warning" style="font-size: 24px; color: var(--color-accent); margin-bottom: 10px" />
                  <span>{{ error }}</span>
                  <a-button type="primary" size="small" ghost @click="handleRetry" style="margin-top: 12px">
                    重试
                  </a-button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 回测结果工作区 -->
        <div v-show="ideWorkspaceTab === 'backtest'" class="ide-workspace-pane">
          <div class="backtest-panel">
            <div class="backtest-placeholder">
              <a-icon type="experiment" style="font-size: 64px; color: #404040; margin-bottom: 16px" />
              <div style="color: #787b86; text-align: center">
                <div style="font-size: 16px; margin-bottom: 8px">回测分析功能</div>
                <div style="font-size: 12px">敬请期待...</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 状态栏 -->
        <div class="status-bar">
          <div class="status-left">
            <span><span class="status-dot"></span>就绪</span>
            <span :class="{ 'socket-connected': socketConnected }">
              {{ socketConnected ? '🔌 实时数据' : '🟡 本地数据' }}
            </span>
            <span>{{ dataRange }}</span>
            <span>{{ dataCount }}</span>
          </div>
          <div class="status-right">
            <span v-if="currentPrice" :class="priceChangeClass">
              {{ symbol }} {{ currentPrice.toFixed(2) }} 
              ({{ priceChange >= 0 ? '+' : '' }}{{ priceChange.toFixed(2) }} / {{ priceChangePercent >= 0 ? '+' : '' }}{{ priceChangePercent.toFixed(2) }}%)
            </span>
            <span v-else>{{ symbol }} | {{ timeframe }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 策略配置弹窗 -->
    <a-modal
      v-model="showStrategyConfig"
      title="策略管理"
      width="600px"
    >
      <p>策略配置功能开发中...</p>
    </a-modal>
  </div>
</template>

<script>
import { init } from 'klinecharts'
import request from '@/utils/request'
import socketService from '@/services/socketService'

export default {
  name: 'IndicatorIDE',
  data() {
    return {
      leftPanelCollapsed: false,
      showStrategyConfig: false,
      ideWorkspaceTab: 'chart',
      isFullscreen: false,
      socketConnected: false,

      // 标的和时间周期
      symbol: '600519.SH',
      market: 'SH',
      timeframe: '1D',
      timeframes: [
        { key: '1min', label: '1分钟' },
        { key: '5min', label: '5分钟' },
        { key: '15min', label: '15分钟' },
        { key: '30min', label: '30分钟' },
        { key: '60min', label: '60分钟' },
        { key: '1D', label: '日线' },
        { key: '1W', label: '周线' },
        { key: '1M', label: '月线' }
      ],
      watchlist: [
        { symbol: '600519.SH', market: 'SH', name: '贵州茅台' },
        { symbol: '000001.SZ', market: 'SZ', name: '平安银行' },
        { symbol: '000002.SZ', market: 'SZ', name: '万科A' },
        { symbol: '600000.SH', market: 'SH', name: '浦发银行' },
        { symbol: '000858.SZ', market: 'SZ', name: '五粮液' },
        { symbol: '600036.SH', market: 'SH', name: '招商银行' },
        { symbol: '601318.SH', market: 'SH', name: '中国平安' },
        { symbol: '000333.SZ', market: 'SZ', name: '美的集团' }
      ],
      selectedWatchlistKey: 'SH:600519.SH',

      // 策略库
      strategyLibrary: [
        {
          id: 'chan_theory',
          name: '缠论分析',
          description: '基于缠中说禅理论的分型、笔、中枢、背驰分析',
          category: 'technical',
          icon: '📐',
          enabled: true,
          params: {
            enableFractal: true,
            enableBi: true,
            enableZhongshu: true,
            enableBeichi: true
          }
        },
        {
          id: 'main_capital',
          name: '主力筹码跟踪',
          description: '主力资金流向、筹码集中度、大单监控',
          category: 'flow',
          icon: '💰',
          enabled: true,
          params: {
            threshold: 500,
            lookback: 5
          }
        },
        {
          id: 'macd_strategy',
          name: 'MACD经典策略',
          description: 'MACD金叉死叉、顶底背离信号',
          category: 'indicator',
          icon: '📊',
          enabled: true,
          params: {
            fast: 12,
            slow: 26,
            signal: 9
          }
        },
        {
          id: 'bollinger',
          name: '布林带策略',
          description: '布林带突破、收窄扩张信号',
          category: 'indicator',
          icon: '📈',
          enabled: true,
          params: {
            period: 20,
            stdDev: 2
          }
        },
        {
          id: 'rsi_strategy',
          name: 'RSI超买超卖',
          description: 'RSI超买超卖区间交易',
          category: 'indicator',
          icon: '📉',
          enabled: false,
          params: {
            period: 14,
            overbought: 70,
            oversold: 30
          }
        },
        {
          id: 'volume_price',
          name: '量价关系',
          description: '成交量与价格配合度分析',
          category: 'flow',
          icon: '📏',
          enabled: false,
          params: {
            volThreshold: 1.5
          }
        }
      ],

      // 策略分析结果
      analyzing: false,
      strategyAdvices: [],
      composite: {
        signalCount: { BUY: 0, SELL: 0, HOLD: 0, WATCH: 0 },
        recommendation: '观望',
        suggestedPosition: 0,
        keyRisks: []
      },

      // 价格数据
      currentPrice: 1850.00,
      priceChange: 42.50,
      priceChangePercent: 2.35,

      // 图表
      chart: null,
      loading: false,
      error: null,
      klineData: [],

      // 指标
      activeIndicators: [],
      activeDrawingTool: null,

      // 数据范围
      dataRange: '',
      dataCount: ''
    }
  },

  computed: {
    indicatorSummary() {
      if (this.activeIndicators.length === 0) {
        return '选择指标'
      }
      return `${this.activeIndicators.length} 个指标已激活`
    },

    consensus() {
      if (!this.composite) return '分析中...'
      const { signalCount } = this.composite
      if (signalCount.BUY > signalCount.SELL) return '看多'
      if (signalCount.SELL > signalCount.BUY) return '看空'
      return '震荡'
    },

    consensusColor() {
      if (!this.composite) return 'default'
      const { signalCount } = this.composite
      if (signalCount.BUY > signalCount.SELL) return 'red'
      if (signalCount.SELL > signalCount.BUY) return 'green'
      return 'orange'
    },

    priceChangeClass() {
      return this.priceChangePercent >= 0 ? 'text-up' : 'text-down'
    }
  },

  watch: {
    timeframe() {
      this.loadChart()
    },
    symbol() {
      this.loadChart()
      this.runStrategyAnalysis()
    }
  },

  mounted() {
    this.initChart()
    this.loadChart()
    this.runStrategyAnalysis()
  },

  beforeDestroy() {
    if (this.chart) {
      this.chart.destroy()
      this.chart = null
    }
  },

  methods: {
    marketLabel(market) {
      const labels = { SH: '沪', SZ: '深' }
      return labels[market] || market
    },

    async initChart() {
      this.$nextTick(() => {
        if (document.getElementById('kline-chart-container')) {
          this.chart = init('kline-chart-container', {
            layout: {
              background: 'var(--bg-secondary)',
              textColor: 'var(--text-primary)'
            },
            grid: {
              show: true,
              horizontal: { color: '#2a2a2a' },
              vertical: { color: '#2a2a2a' }
            },
            candle: {
              type: 'candle_solid',
              upColor: 'var(--kline-up)',
              downColor: 'var(--kline-down)',
              borderUpColor: 'var(--kline-up)',
              borderDownColor: 'var(--kline-down)',
              wickUpColor: 'var(--kline-up)',
              wickDownColor: 'var(--kline-down)'
            },
            separator: { color: '#2a2a2a' },
            xAxis: {
              axisLine: { color: '#2a2a2a' },
              tickLine: { color: '#2a2a2a' },
              label: { color: 'var(--text-muted)' }
            },
            yAxis: {
              axisLine: { color: '#2a2a2a' },
              tickLine: { color: '#2a2a2a' },
              label: { color: 'var(--text-muted)' }
            }
          })

          if (window.ResizeObserver) {
            new ResizeObserver(() => {
              if (this.chart) this.chart.resize()
            }).observe(document.getElementById('kline-chart-container'))
          }
        }
      })
    },

    async loadChart() {
      if (!this.chart) {
        this.initChart()
        return
      }

      this.loading = true
      this.error = null

      try {
        const periodMap = {
          '1m': '1', '5m': '5', '15m': '15', '30m': '30',
          '1H': '60', '4H': '240', '1D': 'D', '1W': 'W'
        }
        const period = periodMap[this.timeframe] || 'D'

        // 模拟数据加载
        this.loadMockData()
      } catch (error) {
        console.error('Failed to load chart:', error)
        this.loadMockData()
      } finally {
        this.loading = false
      }
    },

    loadMockData() {
      const data = []
      let basePrice = 1800
      const now = Date.now()

      for (let i = 300; i >= 0; i--) {
        const volatility = (Math.random() - 0.5) * 40
        const open = basePrice
        const close = basePrice + volatility
        const high = Math.max(open, close) + Math.random() * 20
        const low = Math.min(open, close) - Math.random() * 20

        data.push({
          timestamp: Math.floor((now - i * 86400000) / 1000),
          open: parseFloat(open.toFixed(2)),
          high: parseFloat(high.toFixed(2)),
          low: parseFloat(low.toFixed(2)),
          close: parseFloat(close.toFixed(2)),
          volume: Math.floor(Math.random() * 50000000) + 10000000
        })

        basePrice = close
      }

      this.klineData = data
      this.chart.clearData()
      this.chart.applyNewData(data)

      if (data.length > 0) {
        const first = new Date(data[0].timestamp * 1000).toLocaleDateString()
        const last = new Date(data[data.length - 1].timestamp * 1000).toLocaleDateString()
        this.dataRange = `${first} ~ ${last}`
        this.dataCount = `${data.length}条`
        
        // 更新当前价格
        const lastCandle = data[data.length - 1]
        const prevCandle = data[data.length - 2]
        this.currentPrice = lastCandle.close
        this.priceChange = lastCandle.close - prevCandle.close
        this.priceChangePercent = ((lastCandle.close - prevCandle.close) / prevCandle.close) * 100
      }
    },

    handleWatchlistChange(value) {
      const [market, symbol] = value.split(':')
      this.market = market
      this.symbol = symbol
    },

    // 策略相关方法
    toggleStrategy(strategy) {
      this.runStrategyAnalysis()
    },

    updateParam(strategy, key, value) {
      strategy.params[key] = value
      this.runStrategyAnalysis()
    },

    formatParamLabel(key) {
      const labels = {
        period: '周期',
        fast: '快线',
        slow: '慢线',
        signal: '信号线',
        stdDev: '标准差',
        threshold: '阈值',
        lookback: '回望',
        enableFractal: '分型',
        enableBi: '笔',
        enableZhongshu: '中枢',
        enableBeichi: '背驰',
        overbought: '超买',
        oversold: '超卖',
        volThreshold: '量比阈值'
      }
      return labels[key] || key
    },

    async runStrategyAnalysis() {
      this.analyzing = true
      
      // 模拟分析延迟
      await new Promise(resolve => setTimeout(resolve, 800))
      
      const enabledStrategies = this.strategyLibrary.filter(s => s.enabled)
      this.strategyAdvices = enabledStrategies.map(strategy => this.generateMockAdvice(strategy))
      
      // 计算综合结果
      this.calculateComposite()
      this.analyzing = false
    },

    generateMockAdvice(strategy) {
      const signals = ['BUY', 'SELL', 'HOLD', 'WATCH']
      const signalType = signals[Math.floor(Math.random() * signals.length)]
      const confidence = 0.5 + Math.random() * 0.45
      
      const reasons = {
        'chan_theory': [
          '价格回调至重要支撑位',
          'MACD底背离信号确认',
          '成交量萎缩，抛压减轻'
        ],
        'main_capital': [
          '主力资金连续3日净流入',
          '大单买入占比提升',
          '筹码集中度提高'
        ],
        'macd_strategy': [
          'MACD金叉向上',
          'DIF上穿DEA',
          '柱状图由负转正'
        ],
        'bollinger': [
          '价格触及布林带下轨',
          '布林带开始收窄',
          '波动率处于低位'
        ],
        'rsi_strategy': [
          'RSI处于超卖区域',
          'RSI出现底背离',
          'RSI开始拐头向上'
        ],
        'volume_price': [
          '放量上涨，量价配合',
          '缩量回调，健康调整',
          '成交量持续放大'
        ]
      }
      
      return {
        strategyId: strategy.id,
        strategyName: strategy.name,
        signalType,
        confidence,
        priceTarget: signalType === 'BUY' ? this.currentPrice * 1.1 : signalType === 'SELL' ? this.currentPrice * 0.9 : undefined,
        stopLoss: signalType === 'BUY' ? this.currentPrice * 0.95 : signalType === 'SELL' ? this.currentPrice * 1.05 : undefined,
        positionSize: signalType === 'BUY' ? 0.25 : signalType === 'SELL' ? 0 : undefined,
        reasons: reasons[strategy.id] || ['技术面信号']
      }
    },

    calculateComposite() {
      const signalCount = { BUY: 0, SELL: 0, HOLD: 0, WATCH: 0 }
      let totalPosition = 0
      let buyCount = 0
      
      this.strategyAdvices.forEach(advice => {
        signalCount[advice.signalType]++
        if (advice.signalType === 'BUY' && advice.positionSize) {
          totalPosition += advice.positionSize
          buyCount++
        }
      })
      
      let recommendation = '观望'
      let suggestedPosition = 0
      
      if (signalCount.BUY > signalCount.SELL) {
        recommendation = '看多'
        suggestedPosition = buyCount > 0 ? totalPosition / buyCount : 0.2
      } else if (signalCount.SELL > signalCount.BUY) {
        recommendation = '看空'
        suggestedPosition = 0
      } else {
        recommendation = '震荡'
        suggestedPosition = 0.1
      }
      
      this.composite = {
        signalCount,
        recommendation,
        suggestedPosition,
        keyRisks: ['市场波动风险', '政策风险']
      }
    },

    getSignalColor(type) {
      const colors = {
        BUY: 'var(--color-up)',
        SELL: 'var(--color-down)',
        HOLD: 'var(--color-accent)',
        WATCH: 'var(--text-muted)'
      }
      return colors[type] || 'var(--text-muted)'
    },

    getSignalLabel(type) {
      const labels = {
        BUY: '买入',
        SELL: '卖出',
        HOLD: '持有',
        WATCH: '观望'
      }
      return labels[type] || type
    },

    // 指标按钮定义
    indicatorButtons: [
      { id: 'sma', name: 'SMA (简单移动平均)', shortName: 'SMA', type: 'line', defaultParams: { length: 20 }, paramSchema: [{ key: 'length', label: '周期', min: 1, max: 300, step: 1 }] },
      { id: 'ema', name: 'EMA (指数移动平均)', shortName: 'EMA', type: 'line', defaultParams: { length: 20 }, paramSchema: [{ key: 'length', label: '周期', min: 1, max: 300, step: 1 }] },
      { id: 'rsi', name: 'RSI (相对强弱)', shortName: 'RSI', type: 'line', defaultParams: { length: 14 }, paramSchema: [{ key: 'length', label: '周期', min: 1, max: 200, step: 1 }] },
      { id: 'macd', name: 'MACD', shortName: 'MACD', type: 'macd', defaultParams: { fast: 12, slow: 26, signal: 9 }, paramSchema: [{ key: 'fast', label: '快线', min: 1, max: 100, step: 1 }, { key: 'slow', label: '慢线', min: 2, max: 200, step: 1 }, { key: 'signal', label: '信号线', min: 1, max: 100, step: 1 }] },
      { id: 'boll', name: '布林带', shortName: 'BOLL', type: 'band', defaultParams: { period: 20, stdDev: 2 }, paramSchema: [{ key: 'period', label: '周期', min: 1, max: 300, step: 1 }, { key: 'stdDev', label: '标准差', min: 0.1, max: 10, step: 0.1 }] }
    ],

    isIndicatorActive(indicatorId) {
      return this.activeIndicators.some(ind => ind.id === indicatorId)
    },

    toggleIndicator(indicator, checked) {
      if (checked) {
        this.addIndicator(indicator)
      } else {
        const ind = this.activeIndicators.find(i => i.id === indicator.id)
        if (ind) {
          this.removeIndicatorInstance(ind)
        }
      }
    },

    createIndicatorInstanceId(indicatorId) {
      return `${indicatorId}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    },

    addIndicator(indicator) {
      const instanceId = this.createIndicatorInstanceId(indicator.id)
      const newIndicator = {
        ...indicator,
        instanceId,
        params: { ...indicator.defaultParams },
        visible: true
      }

      this.activeIndicators.push(newIndicator)

      if (this.chart) {
        try {
          this.chart.createIndicator(indicator.id, false, {
            id: instanceId,
            ...newIndicator.params
          })
        } catch (e) {
          console.error('Failed to create indicator:', e)
        }
      }
    },

    formatIndicatorLabel(indicator) {
      const template = this.indicatorButtons.find(b => b.id === indicator.id)
      if (!template) return indicator.id?.toUpperCase() || ''

      switch (indicator.id) {
        case 'sma':
        case 'ema':
        case 'rsi':
          return `${template.shortName}(${indicator.params?.length || indicator.params?.period || 0})`
        case 'macd':
          return `MACD(${indicator.params?.fast || 12},${indicator.params?.slow || 26},${indicator.params?.signal || 9})`
        case 'boll':
          return `BOLL(${indicator.params?.period || 20},${indicator.params?.stdDev || 2})`
        default:
          return template.shortName
      }
    },

    toggleIndicatorVisibility(indicator) {
      const newVisible = indicator.visible === false
      const index = this.activeIndicators.findIndex(ind => ind.instanceId === indicator.instanceId)
      if (index !== -1) {
        this.activeIndicators[index].visible = newVisible
        if (this.chart) {
          try {
            this.chart.setIndicatorVisible(indicator.instanceId, newVisible)
          } catch (e) {}
        }
      }
    },

    removeIndicatorInstance(indicator) {
      const instanceId = indicator.instanceId || indicator.id
      this.activeIndicators = this.activeIndicators.filter(ind => (ind.instanceId || ind.id) !== instanceId)

      if (this.chart) {
        try {
          this.chart.removeIndicator(instanceId)
        } catch (e) {}
      }
    },

    drawingTools: [
      { name: 'line', title: '线段', icon: 'minus' },
      { name: 'horizontalLine', title: '水平线', icon: 'minus' },
      { name: 'verticalLine', title: '垂直线', icon: 'column-width' },
      { name: 'ray', title: '射线', icon: 'arrow-right' },
      { name: 'straightLine', title: '直线', icon: 'menu' }
    ],

    selectDrawingTool(toolName) {
      if (this.activeDrawingTool === toolName) {
        this.activeDrawingTool = null
        return
      }
      this.activeDrawingTool = toolName
    },

    clearAllDrawings() {
      if (this.chart) {
        try {
          this.chart.clearDrawings()
        } catch (e) {}
      }
      this.activeDrawingTool = null
    },

    toggleFullscreen() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen()
        this.isFullscreen = true
      } else {
        document.exitFullscreen()
        this.isFullscreen = false
      }
    },

    handleRetry() {
      this.loadChart()
    }
  }
}
</script>

<style scoped>
.indicator-ide {
  height: 100vh;
  display: flex;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.ide-main {
  display: flex;
  flex: 1;
  min-height: 0;
}

.ide-left {
  width: 360px;
  background: var(--bg-surface);
  border-right: 1px solid #2a2a2a;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.strategy-panel {
  flex: 0 0 auto;
  border-bottom: 1px solid #2a2a2a;
}

.advice-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.panel-header {
  padding: 12px 16px;
  background: rgba(0,0,0,0.2);
  border-bottom: 1px solid #2a2a2a;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title {
  color: var(--text-primary);
  font-weight: 500;
  font-size: 14px;
}

.strategy-list {
  padding: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.strategy-item {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  margin-bottom: 8px;
  padding: 12px;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.strategy-item:hover {
  background: rgba(255,255,255,0.06);
}

.strategy-item.active {
  border-color: var(--color-primary);
  background: rgba(59, 130, 246, 0.1);
}

.strategy-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.strategy-icon {
  font-size: 18px;
}

.strategy-name {
  color: var(--text-primary);
  font-weight: 500;
  flex: 1;
  font-size: 13px;
}

.info-icon {
  color: var(--text-muted);
  cursor: help;
  font-size: 12px;
}

.strategy-params {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(255,255,255,0.1);
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.param-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.param-label {
  color: var(--text-secondary);
  min-width: 40px;
}

.loading-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-secondary);
}

.advice-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.advice-item {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  margin-bottom: 8px;
  padding: 12px;
  border-left: 3px solid var(--color-primary);
}

.advice-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.signal-tag {
  margin: 0;
  font-weight: 500;
}

.confidence {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  color: var(--text-secondary);
  font-size: 12px;
}

.advice-body {
  font-size: 12px;
}

.price-info {
  display: flex;
  gap: 4px;
  margin-bottom: 4px;
}

.price-info .label {
  color: var(--text-secondary);
  min-width: 50px;
}

.price-info .value.up {
  color: var(--color-up);
  font-weight: 500;
}

.price-info .value.down {
  color: var(--color-down);
  font-weight: 500;
}

.reasons {
  margin-top: 8px;
}

.reasons-title {
  color: var(--text-secondary);
  font-weight: 500;
  margin-bottom: 4px;
}

.reasons-list {
  list-style: none;
  padding-left: 0;
  margin: 0;
}

.reasons-list li {
  color: var(--text-secondary);
  padding: 2px 0;
}

.composite-panel {
  border-top: 1px solid rgba(255,255,255,0.1);
  padding: 12px;
}

.composite-title {
  color: var(--text-primary);
  font-weight: 500;
  margin-bottom: 8px;
  font-size: 13px;
}

.vote-bar {
  display: flex;
  height: 32px;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 8px;
}

.vote-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 500;
  font-size: 11px;
}

.composite-summary {
  font-size: 12px;
}

.summary-item {
  display: flex;
  gap: 8px;
  padding: 4px 0;
}

.summary-item .label {
  color: var(--text-secondary);
  min-width: 60px;
}

.ide-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.top-nav {
  background: var(--bg-surface);
  border-bottom: 1px solid #2a2a2a;
  padding: 0 16px;
}

.nav-items {
  display: flex;
  gap: 8px;
}

.nav-item {
  padding: 12px 16px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 14px;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
}

.nav-item:hover {
  color: var(--text-primary);
}

.nav-item.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.ide-workspace-tabs {
  display: flex;
  background: var(--bg-surface);
  border-bottom: 1px solid #2a2a2a;
}

.ide-workspace-tab {
  padding: 10px 20px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
  border-bottom: 2px solid transparent;
}

.ide-workspace-tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.ide-workspace-tab:hover {
  color: var(--text-primary);
}

.ide-workspace-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chart-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.chart-panel-toolbar {
  padding: 8px 12px;
  background: var(--bg-surface);
  border-bottom: 1px solid #2a2a2a;
}

.chart-panel-toolbar-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.chart-panel-toolbar-title {
  font-size: 13px;
  color: var(--text-muted);
}

.chart-panel-toolbar-top-actions {
  display: flex;
  gap: 6px;
}

.chart-panel-icon-btn,
.chart-panel-fs-btn {
  padding: 4px 8px;
  border: 1px solid #2a2a2a;
  background: transparent;
  color: var(--text-muted);
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.chart-panel-icon-btn:hover,
.chart-panel-fs-btn:hover {
  background: rgba(255,255,255,0.05);
  color: var(--text-primary);
}

.chart-panel-toolbar-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.ide-toolbar-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ide-toolbar-label {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.chart-panel-watchlist-select {
  width: 180px;
}

.wl-opt-tag {
  display: inline-block;
  padding: 0 4px;
  margin-right: 4px;
  background: #262626;
  border-radius: 2px;
  font-size: 10px;
}

.wl-opt-name {
  margin-left: 4px;
  color: var(--text-muted);
  font-size: 11px;
}

.tf-group {
  display: flex;
}

.ide-indicator-multiselect-trigger {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--bg-secondary);
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
}

.ide-indicator-overlay {
  background: var(--bg-surface);
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  padding: 8px;
  min-width: 200px;
}

.ide-indicator-overlay-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid #2a2a2a;
}

.ide-indicator-overlay-list {
  max-height: 300px;
  overflow-y: auto;
}

.ide-indicator-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}

.ide-indicator-name {
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
}

.ide-indicator-name:hover {
  color: var(--color-primary);
}

.chart-panel-inner {
  flex: 1;
  position: relative;
  min-height: 0;
}

.kline-chart-container {
  width: 100%;
  height: 100%;
}

.drawing-toolbar {
  position: absolute;
  left: 8px;
  top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: rgba(30, 41, 59, 0.95);
  padding: 4px;
  border-radius: 4px;
  border: 1px solid #2a2a2a;
  z-index: 10;
}

.drawing-tool-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 4px;
  font-size: 14px;
}

.drawing-tool-btn:hover {
  background: rgba(255,255,255,0.1);
  color: var(--text-primary);
}

.drawing-tool-btn.active {
  background: var(--color-primary);
  color: white;
}

.indicator-active-bar {
  position: absolute;
  left: 50px;
  top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 300px;
  background: rgba(30, 41, 59, 0.95);
  padding: 4px;
  border-radius: 4px;
  border: 1px solid #2a2a2a;
  z-index: 10;
}

.indicator-active-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  background: rgba(255,255,255,0.05);
  border-radius: 4px;
  font-size: 11px;
}

.indicator-active-chip--hidden .indicator-active-chip__label {
  text-decoration: line-through;
  color: var(--text-muted);
}

.indicator-active-chip__label {
  color: var(--text-primary);
  cursor: pointer;
}

.indicator-active-chip__label:hover {
  color: var(--color-primary);
}

.indicator-active-chip__action {
  color: var(--text-muted);
  cursor: pointer;
  font-size: 10px;
}

.indicator-active-chip__action:hover {
  color: var(--text-primary);
}

.chart-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(20, 20, 20, 0.9);
}

.error-box {
  text-align: center;
  padding: 24px;
}

.backtest-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-secondary);
}

.backtest-placeholder {
  text-align: center;
  padding: 48px;
}

.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  background: var(--bg-surface);
  border-top: 1px solid #2a2a2a;
  font-size: 11px;
  color: var(--text-muted);
}

.status-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-down);
  display: inline-block;
  margin-right: 4px;
}
</style>
