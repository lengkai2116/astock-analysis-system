<template>
  <div class="kline-chart-container" :style="containerStyle">
    <div ref="chartRef" class="kline-chart-canvas"></div>
    <div v-if="loading" class="kline-loading">
      <a-spin size="large" />
      <span>加载数据中...</span>
    </div>
    <div v-if="!loading && klineData.length === 0" class="kline-empty">
      <a-empty description="暂无数据" />
    </div>
  </div>
</template>

<script>
import { init, dispose } from 'klinecharts'
import chartService from '@/services/chartService'

const INDICATOR_MAP = {
  ma5: 'MA', ma10: 'MA', ma20: 'MA',
  boll_upper: 'BOLL', boll_middle: 'BOLL', boll_lower: 'BOLL',
  macd: 'MACD', rsi: 'RSI', kdj: 'KDJ', vol: 'VOL'
}

const PANE_MAP = {
  ma5: 'candle_pane', ma10: 'candle_pane', ma20: 'candle_pane',
  boll_upper: 'candle_pane', boll_middle: 'candle_pane', boll_lower: 'candle_pane',
  vol: 'vol_pane', macd: 'macd_pane', rsi: 'rsi_pane', kdj: 'rsi_pane'
}

export default {
  name: 'KLineChart',
  props: {
    tsCode: { type: String, default: '' },
    indicators: { type: Array, default: () => ['ma5', 'ma20', 'macd', 'rsi', 'vol'] },
    period: { type: String, default: 'D' },
    height: { type: [Number, String], default: '100%' },
    dark: { type: Boolean, default: true }
  },
  data() {
    return {
      chart: null,
      loading: false,
      klineData: [],
      signals: []
    }
  },
  computed: {
    containerStyle() {
      return {
        height: typeof this.height === 'number' ? this.height + 'px' : this.height,
        position: 'relative'
      }
    }
  },
  watch: {
    tsCode: {
      handler(n) { if (n) this.loadStock(n, this.period, this.indicators) },
      immediate: true
    },
    period(n) {
      if (this.tsCode) this.loadStock(this.tsCode, n, this.indicators)
    },
    indicators(n) {
      if (this.chart && this.klineData.length > 0) this.syncIndicators(n)
    }
  },
  mounted() {
    this.$nextTick(() => this.initChart())
    this._resizeObserver = new ResizeObserver(() => {
      if (this.chart) this.chart.resize()
    })
    if (this.$refs.chartRef) {
      this._resizeObserver.observe(this.$refs.chartRef.parentElement)
    }
  },
  beforeUnmount() {
    if (this._resizeObserver) this._resizeObserver.disconnect()
    if (this.chart) { dispose(this.chart); this.chart = null }
  },
  methods: {
    initChart() {
      if (!this.$refs.chartRef) return
      const darkStyles = {
        grid: { horizontal: { color: '#1e293b' }, vertical: { color: '#1e293b' } },
        candle: {
          type: 'candle_up_down',
          bar: { upColor: '#ef4444', downColor: '#22c55e', noChangeColor: '#888888' },
          priceMark: { high: { color: '#94a3b8' }, low: { color: '#94a3b8' }, last: { color: '#f1f5f9' } },
          tooltip: { labels: ['时间', '开', '高', '低', '收', '涨幅'] }
        },
        xAxis: { axisLine: { color: '#2a2a2a' }, tickLine: { color: '#2a2a2a' }, tickText: { color: '#94a3b8' } },
        yAxis: { axisLine: { color: '#2a2a2a' }, tickLine: { color: '#2a2a2a' }, tickText: { color: '#94a3b8' } },
        crosshair: { horizontal: { color: '#64748b' }, vertical: { color: '#64748b' } },
        separator: { color: '#2a2a2a' }
      }

      this.chart = init(this.$refs.chartRef, {
        locale: 'zh-CN',
        styles: darkStyles,
        layout: [
          { type: 'candle', options: { id: 'candle_pane', height: 400 } },
          { type: 'indicator', options: { id: 'vol_pane', height: 80 } },
          { type: 'indicator', options: { id: 'macd_pane', height: 100 } },
          { type: 'indicator', options: { id: 'rsi_pane', height: 80 } },
          { type: 'xAxis' }
        ]
      })

      if (this.chart) {
        this.$emit('ready', this.chart)
        if (this.tsCode) this.loadStock(this.tsCode, this.period, this.indicators)
      }
    },

    async loadStock(tsCode, period, indicatorKeys) {
      if (!tsCode || !this.chart) return
      this.loading = true
      this.klineData = []
      const indList = indicatorKeys || this.indicators
      const indParam = Array.isArray(indList) ? indList.join(',') : indList

      try {
        const data = await chartService.fetchKlineData(tsCode, indParam, period, 300)
        this.klineData = data.kline || []
        this.signals = data.signals || []

        this.$emit('data-loaded', data)

        if (this.klineData.length > 0) {
          this.chart.applyNewData(this.klineData)
          this.syncIndicators(indList)
          this.renderSignalMarkers()
        }
      } catch (err) {
        console.error('加载 K 线失败:', err)
      } finally {
        this.loading = false
      }
    },

    syncIndicators(keys) {
      if (!this.chart) return
      const ks = Array.isArray(keys) ? keys : [keys]

      // 清除旧指标
      try {
        const panes = ['candle_pane', 'vol_pane', 'macd_pane', 'rsi_pane']
        panes.forEach(pid => {
          const inds = this.chart.getIndicatorByPaneId(pid)
          if (inds && inds.length > 0) {
            const toRemove = [...inds]
            toRemove.forEach(ind => {
              try { this.chart.removeIndicator(ind) } catch(e) {}
            })
          }
        })
      } catch(e) {}

      // 主图：MA
      const maIds = ks.filter(k => k.startsWith('ma'))
      if (maIds.length > 0) {
        const periods = maIds.map(k => parseInt(k.replace('ma', ''))).filter(p => !isNaN(p))
        if (periods.length > 0) {
          this.chart.createIndicator({ name: 'MA', params: periods }, false, { id: 'candle_pane' })
        }
      }

      // 主图：BOLL
      if (ks.some(k => k.startsWith('boll'))) {
        this.chart.createIndicator('BOLL', false, { id: 'candle_pane' })
      }

      // 副图
      if (ks.includes('macd')) this.chart.createIndicator('MACD', false, { id: 'macd_pane', height: 100 })
      if (ks.includes('rsi')) this.chart.createIndicator('RSI', false, { id: 'rsi_pane', height: 80 })
      if (ks.includes('kdj')) this.chart.createIndicator('KDJ', false, { id: 'rsi_pane', height: 80 })
      if (ks.includes('vol')) this.chart.createIndicator('VOL', false, { id: 'vol_pane', height: 80 })
    },

    renderSignalMarkers() {
      if (!this.chart || !this.signals || this.signals.length === 0) return

      // 在 K 线主图上叠加 B/S 标记
      this.signals.forEach(s => {
        try {
          const isBuy = s.type === 'buy' || s.type === 'B'
          this.chart.createOverlay({
            name: 'simpleAnnotation',
            points: [{ timestamp: s.timestamp, value: s.price }],
            styles: {
              position: { left: '0%', top: '0%', width: '100%', height: '100%' },
              annotation: {
                position: s.timestamp,
                type: 'circle',
                color: isBuy ? '#ef4444' : '#22c55e',
                size: 1,
                text: {
                  color: '#ffffff',
                  size: 10,
                  offset: [0, isBuy ? -12 : 12],
                  position: isBuy ? 'top' : 'bottom'
                }
              }
            }
          }, { id: 'candle_pane' })
        } catch(e) {
          console.warn('创建信号标记失败:', e)
        }
      })
    },

    refresh() {
      if (this.tsCode) this.loadStock(this.tsCode, this.period, this.indicators)
    }
  }
}
</script>

<style scoped>
.kline-chart-container {
  width: 100%;
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
}
.kline-chart-canvas {
  width: 100%;
  height: 100%;
  min-height: 400px;
}
.kline-loading,
.kline-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #94a3b8;
  z-index: 10;
}
</style>
