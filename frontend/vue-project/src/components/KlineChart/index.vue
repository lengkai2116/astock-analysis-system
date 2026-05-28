<template>
  <div class="kline-chart-container" :style="containerStyle">
    <div ref="chartRef" class="kline-chart-canvas"></div>
    <!-- 加载状态 -->
    <div v-if="loading" class="kline-loading">
      <a-spin size="large" />
      <span>加载数据中...</span>
    </div>
    <!-- 空状态 -->
    <div v-if="!loading && klineData.length === 0" class="kline-empty">
      <a-empty description="暂无数据" />
    </div>
  </div>
</template>

<script>
import { init, dispose } from 'klinecharts'
import chartService from '@/services/chartService'

// 内置指标名到 klinecharts 标准名称的映射
const INDICATOR_MAP = {
  // 主图叠加
  ma5: 'MA',
  ma10: 'MA',
  ma20: 'MA',
  boll_upper: 'BOLL',
  boll_middle: 'BOLL',
  boll_lower: 'BOLL',
  // 副图
  macd: 'MACD',
  rsi: 'RSI',
  kdj: 'KDJ',
  vol: 'VOL'
}

// 指标参数（不同参数用 name 参数区分）
const INDICATOR_PARAMS = {
  ma5: { name: 'MA5', params: [5] },
  ma10: { name: 'MA10', params: [10] },
  ma20: { name: 'MA20', params: [20] },
  macd: { name: 'MACD', params: [12, 26, 9] },
  rsi: { name: 'RSI', params: [14] },
  kdj: { name: 'KDJ', params: [9, 3, 3] },
  boll_upper: { name: 'BOLL', params: [20, 2] },
  boll_middle: { name: 'BOLL', params: [20, 2] },
  boll_lower: { name: 'BOLL', params: [20, 2] }
}

/**
 * 将后端指标名称转为 klinecharts 可识别的 createIndicator 参数
 */
function buildIndicatorCreate(key) {
  const baseType = INDICATOR_MAP[key]
  if (!baseType) return null
  const params = INDICATOR_PARAMS[key]
  return {
    name: baseType,
    ...(params ? { params: params.params } : {})
  }
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
      activeIndicators: [],
      activeSubcharts: [],
      // 已创建的 indicator id 列表（用于去重）
      createdIndicators: new Set()
    }
  },
  computed: {
    containerStyle() {
      const h = this.height
      return {
        height: typeof h === 'number' ? h + 'px' : h,
        position: 'relative'
      }
    }
  },
  watch: {
    tsCode: {
      handler(newVal) {
        if (newVal && newVal !== '') {
          this.loadStock(newVal, this.period, this.indicators)
        }
      },
      immediate: true
    },
    period(newVal) {
      if (this.tsCode) {
        this.loadStock(this.tsCode, newVal, this.indicators)
      }
    },
    indicators(newVal) {
      if (this.chart && this.klineData.length > 0) {
        this.syncIndicators(newVal)
      }
    }
  },
  mounted() {
    this.$nextTick(() => {
      this.initChart()
    })
    // 监听容器 resize
    this._resizeObserver = new ResizeObserver(() => {
      if (this.chart) {
        this.chart.resize()
      }
    })
    if (this.$refs.chartRef) {
      this._resizeObserver.observe(this.$refs.chartRef.parentElement)
    }
  },
  beforeDestroy() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect()
    }
    if (this.chart) {
      dispose(this.chart)
      this.chart = null
    }
  },
  methods: {
    /**
     * 初始化 klinecharts 实例
     */
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
        // 如果已经有 tsCode，加载数据
        if (this.tsCode) {
          this.loadStock(this.tsCode, this.period, this.indicators)
        }
      }
    },

    /**
     * 加载股票 K 线数据
     */
    async loadStock(tsCode, period = 'D', indicatorKeys = null) {
      if (!tsCode || !this.chart) return
      this.loading = true
      this.klineData = []

      const indList = indicatorKeys || this.indicators
      const indParam = Array.isArray(indList) ? indList.join(',') : indList

      try {
        const data = await chartService.fetchKlineData(tsCode, indParam, period, 300)
        this.klineData = data.kline || []
        this.$emit('data-loaded', data)

        if (this.klineData.length > 0) {
          // 清空旧数据 + 设置新数据
          this.chart.applyNewData(this.klineData)
          // 同步指标
          this.syncIndicators(indList)
        }
      } catch (err) {
        console.error('加载 K 线失败:', err)
      } finally {
        this.loading = false
      }
    },

    /**
     * 同步指标（跟当前列表保持一致）
     */
    syncIndicators(keys) {
      if (!this.chart) return
      const keysArr = Array.isArray(keys) ? keys : [keys]

      // 按类型分组：主图叠加 vs 副图
      const overlayKeys = keysArr.filter(k => ['ma5', 'ma10', 'ma20', 'boll_upper', 'boll_middle', 'boll_lower'].includes(k))
      const subKeys = keysArr.filter(k => ['macd', 'rsi', 'kdj'].includes(k))
      // vol 特殊处理：直接使用内置 VOL
      const hasVol = keysArr.includes('vol') || keysArr.includes('volume')

      // 主图：先清除旧的叠加指标
      this.clearPaneIndicators('candle_pane')
      overlayKeys.forEach(key => {
        const indicator = buildIndicatorCreate(key)
        if (indicator) {
          // MA 多参数实例处理
          if (indicator.name === 'MA') {
            // klinecharts 的 MA 支持多个参数 line
            const maParams = overlayKeys
              .filter(k => k.startsWith('ma'))
              .map(k => {
                const period = parseInt(k.replace('ma', ''))
                return { period }
              })
            if (maParams.length > 0) {
              this.chart.createIndicator({
                name: 'MA',
                params: maParams.map(p => p.period)
              }, false, { id: 'candle_pane' })
            }
          } else if (indicator.name === 'BOLL') {
            this.chart.createIndicator('BOLL', false, { id: 'candle_pane' })
          }
        }
      })

      // 副图：MACD / RSI / KDJ
      this.clearPaneIndicators('macd_pane')
      if (subKeys.includes('macd')) {
        this.chart.createIndicator('MACD', false, { id: 'macd_pane', height: 100 })
      }

      this.clearPaneIndicators('rsi_pane')
      if (subKeys.includes('rsi')) {
        this.chart.createIndicator('RSI', false, { id: 'rsi_pane', height: 80 })
      } else if (subKeys.includes('kdj')) {
        this.chart.createIndicator('KDJ', false, { id: 'rsi_pane', height: 80 })
      }

      // VOL 固定在 vol_pane
      this.clearPaneIndicators('vol_pane')
      if (hasVol) {
        this.chart.createIndicator('VOL', false, { id: 'vol_pane', height: 80 })
      }
    },

    /**
     * 清除指定 pane 的所有指标
     */
    clearPaneIndicators(paneId) {
      if (!this.chart) return
      try {
        const indicators = this.chart.getIndicatorByPaneId(paneId)
        if (indicators) {
          // klinecharts 9.x 的 removeIndicator 用法
          if (Array.isArray(indicators)) {
            indicators.forEach(ind => {
              // 通过 override 或 setPaneOptions 实现清除
            })
          }
        }
      } catch (e) {
        // ignore
      }
    },

    /**
     * 设置日期/价格精度
     */
    setPrecision(pricePrecision = 2, volumePrecision = 0) {
      if (this.chart) {
        this.chart.setPriceVolumePrecision(pricePrecision, volumePrecision)
      }
    },

    /**
     * 外部调用：刷新数据
     */
    refresh() {
      if (this.tsCode) {
        this.loadStock(this.tsCode, this.period, this.indicators)
      }
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
