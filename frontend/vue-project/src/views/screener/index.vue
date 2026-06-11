<template>
  <div class="screener-page theme-dark">
    <!-- 页面头部 -->
    <div class="screener-header">
      <div class="header-left">
        <h2 class="page-title">
          🎯 选股系统
        </h2>
        <span class="page-desc">三层流水线筛选 → 精选股票排行榜</span>
      </div>
      <div class="header-right">
        <a-button
          type="primary"
          size="small"
          :loading="screenerRunning"
          @click="startScreening"
        >
          <PlayCircleOutlined /> 执行筛选
        </a-button>
      </div>
    </div>

    <!-- 三栏布局 -->
    <div class="screener-body">
      <!-- 左栏：筛选流程 -->
      <div class="screener-pipeline">
        <PipelineFlow
          :running="screenerRunning"
          :total-stocks="screenerLayers.total"
          :layer1-count="screenerLayers.layer1"
          :layer2-count="screenerLayers.layer2"
          :layer3-count="screenerLayers.layer3"
          :final-count="screenerLayers.final"
          :current-layer="currentLayer"
          @configure="showScreenerConfig"
        />
      </div>

      <!-- 中栏：选股结果 -->
      <div class="screener-results">
        <ScreeningResults
          :results="screeningResults"
          :loading="screeningLoading"
          @select-stock="onScreenerSelectStock"
          @export="exportScreenerResults"
          @navigate-stock="onScreenerStockDoubleClick"
        />
      </div>

      <!-- 右栏：信号融合配置 -->
      <div class="screener-fusion">
        <SignalFusionConfig
          :value="screeningConfig"
          :selected-stock="selectedScreenerStock"
          @save="saveFusionConfig"
          @reset="resetFusionConfig"
        />
      </div>
    </div>
  </div>
          <DisclaimerFooter />
</template>

<script>
import { PlayCircleOutlined } from '@ant-design/icons-vue'
import PipelineFlow from '@/components/StockScreener/PipelineFlow'
import ScreeningResults from '@/components/StockScreener/ScreeningResults'
import SignalFusionConfig from '@/components/StockScreener/SignalFusionConfig'
import screenerService from '@/services/screenerService'
import DisclaimerFooter from '@/components/DisclaimerFooter'

export default {
  name: 'StockScreener',
  components: { PipelineFlow, ScreeningResults, SignalFusionConfig, DisclaimerFooter},
  data() {
    return {
      screenerRunning: false,
      screenerLayers: { total: 5000, layer1: 0, layer2: 0, layer3: 0, final: 0 },
      currentLayer: 0,
      screeningResults: [],
      screeningLoading: false,
      screeningConfig: null,
      selectedScreenerStock: null
    }
  },
  methods: {
    async startScreening() {
      this.screenerRunning = true
      this.currentLayer = 0
      this.screeningResults = []
      this.screenerLayers = { total: 5000, layer1: 0, layer2: 0, layer3: 0, final: 0 }

      try {
        this.currentLayer = 1
        this.screeningLoading = true
        const l1 = await screenerService.runLayer1()
        this.screenerLayers.layer1 = l1.filtered || 0

        this.currentLayer = 2
        const l2 = await screenerService.runLayer2()
        this.screenerLayers.layer2 = l2.passed?.length || 0

        this.currentLayer = 3
        const l3 = await screenerService.runLayer3()
        this.screenerLayers.layer3 = l3.validated?.length || 0

        this.screeningResults = l3.validated || l2.scored || []
        this.screenerLayers.final = this.screeningResults.length
        this.currentLayer = 4
      } catch (err) {
        console.error('筛选执行失败:', err)
        this.$message.error('筛选执行失败')
      } finally {
        this.screenerRunning = false
        this.screeningLoading = false
      }
    },

    onScreenerSelectStock(stock) {
      this.selectedScreenerStock = stock
    },

    onScreenerStockDoubleClick(stock) {
      this.$router.push({
        name: 'IndicatorIDE',
        query: { symbol: stock.symbol }
      })
    },

    saveFusionConfig(config) {
      this.screeningConfig = config
      screenerService.updateFusionConfig(config)
    },

    resetFusionConfig() {
      this.screeningConfig = null
    },

    showScreenerConfig() {
      this.$info({
        title: '筛选参数设置',
        content: '各层筛选参数可在后续版本中通过后端配置',
        okText: '知道了'
      })
    },

    exportScreenerResults() {
      if (this.screeningResults.length === 0) return
      const headers = '排名,代码,名称,综合评分,主力阶段,ASR,集中度,成交量,RSI'
      const rows = this.screeningResults.map((s, i) =>
        [i+1, s.symbol, s.name, s.score?.toFixed(1), s.phase, s.asr?.toFixed(3), s.concentration?.toFixed(3), s.volume_ratio?.toFixed(2), s.rsi?.toFixed(1)].join(',')
      ).join('\n')
      const blob = new Blob([headers + '\n' + rows], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = '选股结果.csv'; a.click()
      URL.revokeObjectURL(url)
    }
  }
}
</script>

<style scoped>
.screener-page {
  padding: 12px 16px;
  min-height: 100vh;
  background: var(--bg-primary, #0a1628);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.screener-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
}

.header-left {
  display: flex;
  align-items: baseline;
  gap: 16px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #f1f5f9;
}

.page-desc {
  font-size: 12px;
  color: #64748b;
}

.header-right {
  display: flex;
  gap: 8px;
}

.screener-body {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.screener-pipeline {
  width: 260px;
  flex-shrink: 0;
}

.screener-results {
  flex: 1;
  min-width: 0;
}

.screener-fusion {
  width: 300px;
  flex-shrink: 0;
}

@media (max-width: 1200px) {
  .screener-body {
    flex-direction: column;
  }
  .screener-pipeline {
    width: 100%;
    max-height: 300px;
  }
  .screener-fusion {
    width: 100%;
    max-height: 400px;
  }
}
</style>
