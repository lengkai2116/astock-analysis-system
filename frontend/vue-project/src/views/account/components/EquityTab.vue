<template>
  <div class="equity-tab">
    <div class="metrics-grid">
      <div
        v-for="m in metrics"
        :key="m.key"
        class="metric-card"
      >
        <div class="metric-label">
          {{ m.label }}
        </div>
        <div
          class="metric-value"
          :class="m.class"
        >
          {{ m.value }}
        </div>
      </div>
    </div>

    <div class="chart-container">
      <div
        ref="chartRef"
        style="width:100%;height:350px"
      />
    </div>

    <div
      v-if="curve.length === 0 && !loading"
      class="empty-hint"
    >
      暂无资金曲线数据，录入交易后自动生成
    </div>
  </div>
</template>

<script>
import { ref, onMounted, nextTick } from 'vue'
import { getEquityCurve, getPerformance } from '@/services/accountService'
import * as echarts from 'echarts'

export default {
  name: 'EquityTab',
  setup() {
    const curve = ref([])
    const perf = ref({})
    const loading = ref(false)
    const chartRef = ref(null)
    const metrics = ref([])

    async function load() {
      loading.value = true
      try {
        const [eqRes, perfRes] = await Promise.all([getEquityCurve(365), getPerformance()])
        if (eqRes.success) curve.value = eqRes.data || []
        if (perfRes.success) {
          perf.value = perfRes.data || {}
          metrics.value = [
            { key: 'total', label: '累计收益', value: perf.value.total_return + '%', class: (perf.value.total_return || 0) >= 0 ? 'profit' : 'loss' },
            { key: 'annual', label: '年化收益', value: perf.value.annual_return + '%', class: (perf.value.annual_return || 0) >= 0 ? 'profit' : 'loss' },
            { key: 'dd', label: '最大回撤', value: '-' + perf.value.max_drawdown + '%', class: 'loss' },
            { key: 'sharpe', label: '夏普比率', value: perf.value.sharpe_ratio || '—', class: (perf.value.sharpe_ratio || 0) >= 1 ? 'profit' : '' },
            { key: 'wr', label: '胜率', value: ((perf.value.win_rate || 0) * 100).toFixed(1) + '%', class: (perf.value.win_rate || 0) >= 0.5 ? 'profit' : 'loss' },
            { key: 'pl', label: '盈亏比', value: perf.value.profit_loss_ratio || '—', class: (perf.value.profit_loss_ratio || 0) >= 1.5 ? 'profit' : '' },
          ]
        }
        await nextTick()
        if (curve.value.length > 0 && chartRef.value) renderChart()
      } finally { loading.value = false }
    }

    function renderChart() {
      const chart = echarts.init(chartRef.value)
      const dates = curve.value.map(c => c.snapshot_date)
      const returns = curve.value.map(c => (c.total_return_pct * 100).toFixed(2))
      chart.setOption({
        tooltip: { trigger: 'axis', formatter: p => `${p[0].axisValue}<br/>收益率: ${p[0].value}%` },
        grid: { left: 50, right: 20, top: 20, bottom: 25 },
        xAxis: { type: 'category', data: dates, axisLabel: { color: '#64748b', fontSize: 11, rotate: 45 } },
        yAxis: { type: 'value', axisLabel: { color: '#64748b', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#2a2a2a' } } },
        series: [{
          type: 'line', data: returns, smooth: true,
          lineStyle: { color: '#52c41a', width: 2 },
          areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(82,196,26,0.25)' }, { offset: 1, color: 'rgba(82,196,26,0)' }] } },
          symbol: 'none',
        }],
      })
      window.addEventListener('resize', () => chart.resize())
    }

    onMounted(load)
    return { curve, perf, loading, metrics, chartRef }
  }
}
</script>

<style scoped>
.metrics-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 20px; }
.metric-card { background: rgba(255,255,255,0.03); border: 1px solid #2a2a2a; border-radius: 8px; padding: 16px; text-align: center; }
.metric-label { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.metric-value { font-size: 18px; font-weight: 700; color: #f1f5f9; }
.metric-value.profit { color: #52c41a; }
.metric-value.loss { color: #ff4d4f; }
.chart-container { background: rgba(255,255,255,0.02); border: 1px solid #2a2a2a; border-radius: 8px; padding: 16px; }
.empty-hint { text-align: center; padding: 60px 0; color: #64748b; }
@media (max-width: 1024px) { .metrics-grid { grid-template-columns: repeat(3, 1fr); } }
</style>
