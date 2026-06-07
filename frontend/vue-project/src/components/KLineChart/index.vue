<template>
  <div class="kline-chart-container" :class="`kline-chart--${chartType}`" :style="containerStyle">
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

const PANE_MAP = {
  ma5: 'candle_pane', ma10: 'candle_pane', ma20: 'candle_pane', ma60: 'candle_pane',
  boll_upper: 'candle_pane', boll_middle: 'candle_pane', boll_lower: 'candle_pane',
  vol: 'vol_pane', macd: 'macd_pane', rsi: 'rsi_pane', kdj: 'rsi_pane',
}

export default {
  name: 'KLineChart',
  props: {
    tsCode: { type: String, default: '' },
    indicators: { type: Array, default: () => ['ma5', 'ma20', 'macd', 'rsi', 'vol'] },
    period: { type: String, default: 'D' },
    height: { type: [Number, String], default: '100%' },
    dark: { type: Boolean, default: true },
    chartType: { type: String, default: 'candle' }, // candle, area, line, heikin_ashi
    chartId: { type: String, default: '' },          // 多图标识 (150§3.1)
    syncCrosshair: { type: Boolean, default: false }, // 十字光标同步
  },
  data() {
    return {
      chart: null,
      loading: false,
      klineData: [],
      signals: [],
    }
  },
  computed: {
    containerStyle() {
      return {
        height: typeof this.height === 'number' ? this.height + 'px' : this.height,
        position: 'relative',
      }
    },
  },
  watch: {
    tsCode: {
      handler(n) { if (n) this.loadStock(n, this.period, this.indicators) },
      immediate: true,
    },
    period(n) {
      if (this.tsCode) this.loadStock(this.tsCode, n, this.indicators)
    },
    chartType() {
      if (this.chart) this.updateChartType()
    },
    indicators(n) {
      if (this.chart && this.klineData.length > 0) this.syncIndicators(n)
    },
  },
  mounted() {
    this.$nextTick(() => this.initChart())
    this._resizeObserver = new ResizeObserver(() => {
      if (this.chart) this.chart.resize()
    })
    if (this.$refs.chartRef) {
      this._resizeObserver.observe(this.$refs.chartRef.parentElement)
    }

    // 十字光标同步监听 (150§3.1)
    if (this.syncCrosshair) {
      window.addEventListener('chart:crosshair', this._onCrosshairSync)
    }
  },
  beforeUnmount() {
    if (this._resizeObserver) this._resizeObserver.disconnect()
    if (this.syncCrosshair) {
      window.removeEventListener('chart:crosshair', this._onCrosshairSync)
    }
    if (this.chart) { dispose(this.chart); this.chart = null }
  },
  methods: {
    _onCrosshairSync(e) {
      if (!this.chart || !this.chartId) return
      if (e.detail?.sourceId === this.chartId) return  // 忽略自身
      const data = e.detail
      // 如果同步了十字光标位置，KLineCharts 的 crosshair API
      if (data.timestamp && this.chart) {
        try { this.chart.setCrosshair(data) } catch {}
      }
    },

    initChart() {
      if (!this.$refs.chartRef) return

      const darkStyles = {
        grid: { horizontal: { color: 'var(--kline-grid, rgba(255,255,255,0.06))' }, vertical: { color: 'var(--kline-grid, rgba(255,255,255,0.06))' } },
        candle: {
          type: 'candle_up_down',
          bar: { upColor: 'var(--kline-up, #ef4444)', downColor: 'var(--kline-down, #22c55e)', noChangeColor: '#888888' },
          priceMark: { high: { color: 'var(--text-secondary, #94a3b8)' }, low: { color: 'var(--text-secondary, #94a3b8)' }, last: { color: 'var(--text-primary, #f1f5f9)' } },
          tooltip: { labels: ['时间', '开', '高', '低', '收', '涨幅'] },
        },
        xAxis: {
          axisLine: { color: 'var(--border-default, #2a2a2a)' },
          tickLine: { color: 'var(--border-default, #2a2a2a)' },
          tickText: { color: 'var(--text-secondary, #94a3b8)' },
        },
        yAxis: {
          axisLine: { color: 'var(--border-default, #2a2a2a)' },
          tickLine: { color: 'var(--border-default, #2a2a2a)' },
          tickText: { color: 'var(--text-secondary, #94a3b8)' },
        },
        crosshair: {
          horizontal: { color: 'var(--kline-crosshair, #64748b)' },
          vertical: { color: 'var(--kline-crosshair, #64748b)' },
        },
        separator: { color: 'var(--border-default, #2a2a2a)' },
      }

      this.chart = init(this.$refs.chartRef, {
        locale: 'zh-CN',
        styles: darkStyles,
        layout: [
          { type: this.chartType === 'candle' ? 'candle' : 'candle', options: { id: 'candle_pane', height: 400 } },
          { type: 'indicator', options: { id: 'vol_pane', height: 80 } },
          { type: 'indicator', options: { id: 'macd_pane', height: 100 } },
          { type: 'indicator', options: { id: 'rsi_pane', height: 80 } },
          { type: 'xAxis' },
        ],
      })

      if (this.chart) {
        this.$emit('ready', { chart: this.chart, chartId: this.chartId })
        if (this.tsCode) this.loadStock(this.tsCode, this.period, this.indicators)

        // 十字光标同步 (150§3.1)
        if (this.syncCrosshair && this.chartId) {
          this.chart.subscribe('crosshairChange', (data) => {
            window.dispatchEvent(new CustomEvent('chart:crosshair', {
              detail: { sourceId: this.chartId, timestamp: data?.timestamp, ...data },
            }))
          })
        }

        // 设置图表类型
        this.updateChartType()
      }
    },

    updateChartType() {
      if (!this.chart) return
      const typeMap = {
        candle: 'candle_solid',
        area: 'area',
        line: 'line',
        heikin_ashi: 'candle_solid',  // KLineCharts 通过数据转换实现
      }
      try {
        this.chart.setStyleOptions({
          candle: { type: typeMap[this.chartType] || 'candle_solid' },
        })
      } catch {}
    },

    async loadStock(tsCode, period, indicatorKeys) {
      if (!tsCode || !this.chart) return
      this.loading = true
      this.klineData = []
      const indList = indicatorKeys || this.indicators
      const indParam = Array.isArray(indList) ? indList.join(',') : indList

      try {
        const data = await chartService.fetchKlineData(tsCode, indParam, period, 300)
        let kline = data.kline || []

        // Heikin Ashi 转换 (150§3.2)
        if (this.chartType === 'heikin_ashi' && kline.length > 0) {
          kline = this._transformHeikinAshi(kline)
        }

        this.klineData = kline
        this.signals = data.signals || []

        this.$emit('data-loaded', { data, chartId: this.chartId })

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

    _transformHeikinAshi(data) {
      // Heikin Ashi 数据转换 (150§3.2)
      const ha = []
      let prevHa = null
      for (const d of data) {
        const ohlc = {
          timestamp: d.timestamp,
          open: 0, high: 0, low: 0, close: 0,
          volume: d.volume || 0,
        }
        if (!prevHa) {
          // 第一条: HA = 实际数据
          ohlc.open = d.open
          ohlc.close = d.close
        } else {
          ohlc.open = (prevHa.open + prevHa.close) / 2
          ohlc.close = (d.open + d.high + d.low + d.close) / 4
        }
        ohlc.high = Math.max(d.high, ohlc.open, ohlc.close)
        ohlc.low = Math.min(d.low, ohlc.open, ohlc.close)
        ha.push(ohlc)
        prevHa = ohlc
      }
      return ha
    },

    syncIndicators(keys) {
      if (!this.chart) return
      const ks = Array.isArray(keys) ? keys : [keys]

      // 清除旧指标
      try {
        ['candle_pane', 'vol_pane', 'macd_pane', 'rsi_pane'].forEach(pid => {
          const inds = this.chart.getIndicatorByPaneId(pid)
          if (inds && inds.length > 0) {
            ;[...inds].forEach(ind => {
              try { this.chart.removeIndicator(ind) } catch {}
            })
          }
        })
      } catch {}

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

      this.signals.forEach(s => {
        try {
          const isBuy = s.type === 'buy' || s.type === 'B'
          this.chart.createOverlay({
            name: 'simpleAnnotation',
            points: [{ timestamp: s.timestamp, value: s.price }],
            styles: {
              annotation: {
                position: s.timestamp,
                type: 'circle',
                color: isBuy ? '#ef4444' : '#22c55e',
                size: 1,
                text: {
                  color: '#ffffff',
                  size: 10,
                  offset: [0, isBuy ? -12 : 12],
                  position: isBuy ? 'top' : 'bottom',
                },
              },
            },
          }, { id: 'candle_pane' })
        } catch {}
      })
    },

    refresh() {
      if (this.tsCode) this.loadStock(this.tsCode, this.period, this.indicators)
    },

    // 外部调用：获取 chart 实例
    getChartInstance() {
      return this.chart
    },
  },
}
</script>

<style scoped>
.kline-chart-container {
  width: 100%;
  background: var(--bg-canvas);
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border-default);
  transition: border-color 0.3s ease;
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
  color: var(--text-muted);
  z-index: 10;
}

/* 面积图 / 线图特殊处理 */
.kline-chart--area .kline-chart-canvas,
.kline-chart--line .kline-chart-canvas {
  min-height: 300px;
}
</style>
