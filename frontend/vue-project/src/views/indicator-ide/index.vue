<template>
  <div class="indicator-ide theme-dark">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <!-- 股票搜索 + 切换 -->
        <a-select
          v-model="currentTsCode"
          show-search
          :filter-option="false"
          :not-found-content="searching ? '搜索中...' : '无结果'"
          style="width: 220px"
          placeholder="搜索股票代码/名称"
          @search="handleStockSearch"
          @change="handleStockChange"
        >
          <a-select-option
            v-for="s in stockSearchResults"
            :key="s.ts_code"
            :value="s.ts_code"
          >
            {{ s.name }} ({{ s.ts_code }})
          </a-select-option>
        </a-select>

        <!-- 周期切换 -->
        <a-radio-group v-model="currentPeriod" button-style="solid" size="small" @change="handlePeriodChange">
          <a-radio-button value="D">日线</a-radio-button>
          <a-radio-button value="W">周线</a-radio-button>
          <a-radio-button value="M">月线</a-radio-button>
        </a-radio-group>
      </div>

      <div class="toolbar-right">
        <a-button size="small" @click="refreshChart">🔄 刷新</a-button>
      </div>
    </div>

    <!-- 指标芯片选择器 -->
    <div class="indicator-chips">
      <span class="chips-label">主图：</span>
      <a-tag
        v-for="ind in overlayIndicators"
        :key="ind.id"
        :color="activeOverlays.includes(ind.id) ? 'blue' : 'default'"
        style="cursor: pointer; user-select: none;"
        :closable="activeOverlays.includes(ind.id) && ind.id !== 'ma5'"
        @click="toggleOverlay(ind.id)"
        @close="removeOverlay(ind.id)"
      >
        {{ ind.name }}
      </a-tag>

      <span class="chips-separator"></span>

      <span class="chips-label">副图：</span>
      <a-tag
        v-for="ind in subIndicators"
        :key="ind.id"
        :color="activeSubcharts.includes(ind.id) ? 'green' : 'default'"
        style="cursor: pointer; user-select: none;"
        :closable="activeSubcharts.includes(ind.id)"
        @click="toggleSubchart(ind.id)"
        @close="removeSubchart(ind.id)"
      >
        {{ ind.name }}
      </a-tag>
    </div>

    <!-- 主内容区：K线图表 + 右侧策略面板 -->
    <div class="ide-body">
      <div class="chart-area">
        <KLineChart
          ref="klineChart"
          :tsCode="currentTsCode"
          :period="currentPeriod"
          :indicators="activeAllIndicators"
          @ready="onChartReady"
          @data-loaded="onDataLoaded"
        />
      </div>

      <!-- 右侧策略信号面板 -->
      <div class="signal-sidebar" v-if="currentTsCode">
        <div class="signal-header">
          <span class="signal-title">📡 策略信号</span>
          <a-button size="small" type="link" @click="refreshSignals">刷新</a-button>
        </div>

        <div class="signal-content">
          <a-spin :spinning="signalsLoading" size="small">
            <!-- 股票基本信息 -->
            <div class="stock-info" v-if="stockInfo">
              <div class="stock-name">{{ stockInfo.name || currentTsCode }}</div>
              <div class="stock-code">{{ currentTsCode }}</div>
            </div>

            <!-- 策略信号列表 -->
            <div v-if="signals.length > 0" class="signal-list">
              <div v-for="sig in signals" :key="sig.id" class="signal-card">
                <div class="signal-card-header">
                  <a-tag :color="sig.signal === 'BUY' || sig.signal === 'bullish' ? 'red' : sig.signal === 'SELL' || sig.signal === 'bearish' ? 'green' : 'default'" size="small">
                    {{ sig.signal_label || sig.signal }}
                  </a-tag>
                  <span class="signal-confidence" v-if="sig.confidence">
                    {{ (sig.confidence * 100).toFixed(0) }}%
                  </span>
                </div>
                <div class="signal-card-body">
                  <div class="signal-strategy">{{ sig.strategy_name }}</div>
                  <div v-if="sig.entry_zone" class="signal-price">
                    区间: {{ sig.entry_zone[0] }} - {{ sig.entry_zone[1] }}
                  </div>
                </div>
              </div>
            </div>

            <a-empty v-else description="暂无信号" :image="aEmptyImage" />
          </a-spin>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import KLineChart from '@/components/KLineChart'
import chartService from '@/services/chartService'
import axios from '@/utils/request'

export default {
  name: 'IndicatorIde',
  components: { KLineChart },
  data() {
    return {
      // 股票选择
      currentTsCode: '600519.SH',
      currentPeriod: 'D',
      stockSearchResults: [],
      searching: false,
      stockInfo: null,

      // 可用指标列表
      overlayIndicators: [
        { id: 'ma5', name: 'MA5' },
        { id: 'ma10', name: 'MA10' },
        { id: 'ma20', name: 'MA20' },
        { id: 'boll', name: 'BOLL' }
      ],
      subIndicators: [
        { id: 'vol', name: '成交量' },
        { id: 'macd', name: 'MACD' },
        { id: 'rsi', name: 'RSI' },
        { id: 'kdj', name: 'KDJ' }
      ],

      // 已激活的指标
      activeOverlays: ['ma5', 'ma20'],
      activeSubcharts: ['vol', 'macd', 'rsi'],

      // 信号
      signals: [],
      signalsLoading: false,

      // 占位图（antd empty 默认）
      aEmptyImage: ''
    }
  },

  computed: {
    // 给 KLineChart 传递的合并指标列表
    activeAllIndicators() {
      return [...this.activeOverlays, ...this.activeSubcharts]
    }
  },

  mounted() {
    // 加载默认股票的数据
    this.loadStockInfo()
    this.loadSignals()
  },

  methods: {
    // ============ 股票搜索 ============
    async handleStockSearch(keyword) {
      if (!keyword || keyword.length < 1) return
      this.searching = true
      try {
        const results = await chartService.searchStocks(keyword, 15)
        this.stockSearchResults = results
      } catch (err) {
        console.error('股票搜索失败:', err)
      } finally {
        this.searching = false
      }
    },

    handleStockChange(tsCode) {
      this.currentTsCode = tsCode
      this.loadStockInfo()
      this.loadSignals()
    },

    async loadStockInfo() {
      try {
        const res = await axios.get(`/api/v1/stocks/${this.currentTsCode}`)
        if (res.success && res.data) {
          this.stockInfo = res.data
        }
      } catch (err) {
        // 可以忽略
      }
    },

    // ============ 周期切换 ============
    handlePeriodChange() {
      // KLineChart 组件通过 watch period 自动加载
    },

    // ============ 指标芯片 ============
    toggleOverlay(id) {
      const idx = this.activeOverlays.indexOf(id)
      if (idx >= 0) {
        // 至少保留 MA5
        if (this.activeOverlays.length > 1) {
          this.activeOverlays.splice(idx, 1)
        }
      } else {
        this.activeOverlays.push(id)
        // 如果选了 boll，展开为三个子项
        if (id === 'boll') {
          this.activeOverlays.push('boll_upper')
          this.activeOverlays.push('boll_middle')
          this.activeOverlays.push('boll_lower')
        }
      }
      this.refreshChart()
    },

    removeOverlay(id) {
      if (this.activeOverlays.length > 1) {
        this.activeOverlays = this.activeOverlays.filter(i => i !== id)
        this.refreshChart()
      }
    },

    toggleSubchart(id) {
      const idx = this.activeSubcharts.indexOf(id)
      if (idx >= 0) {
        this.activeSubcharts.splice(idx, 1)
      } else {
        this.activeSubcharts.push(id)
      }
      this.refreshChart()
    },

    removeSubchart(id) {
      this.activeSubcharts = this.activeSubcharts.filter(i => i !== id)
      this.refreshChart()
    },

    // ============ 图表回调 ============
    onChartReady(chart) {
      console.log('📊 K 线图表已就绪')
    },

    onDataLoaded(data) {
      this.stockInfo = data.stock || this.stockInfo
    },

    refreshChart() {
      if (this.$refs.klineChart) {
        this.$refs.klineChart.refresh()
      }
    },

    // ============ 策略信号 ============
    async loadSignals() {
      if (!this.currentTsCode) return
      this.signalsLoading = true
      try {
        const res = await axios.get('/api/v2/strategy/outputs', {
          params: { ts_code: this.currentTsCode, limit: 5 }
        })
        if (res.success && res.data) {
          this.signals = res.data
        }
      } catch (err) {
        // can ignore
      } finally {
        this.signalsLoading = false
      }
    },

    refreshSignals() {
      this.loadSignals()
    }
  }
}
</script>

<style scoped>
.indicator-ide {
  padding: 12px 16px;
  min-height: 100vh;
  background: var(--bg-primary, #0a1628);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ========= 工具栏 ========= */
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

/* ========= 指标芯片 ========= */
.indicator-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px;
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
}

.chips-label {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
}

.chips-separator {
  width: 1px;
  height: 24px;
  background: #334155;
  margin: 0 8px;
}

/* ========= 主区域 ========= */
.ide-body {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.chart-area {
  flex: 1;
  min-width: 0;
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
  overflow: hidden;
}

/* ========= 右侧信号面板 ========= */
.signal-sidebar {
  width: 280px;
  flex-shrink: 0;
  background: var(--bg-surface, #1e293b);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 180px);
}

.signal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a2a;
}

.signal-title {
  font-weight: 600;
  color: #f1f5f9;
  font-size: 14px;
}

.signal-content {
  flex: 1;
  padding: 12px 16px;
  overflow-y: auto;
}

.stock-info {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #2a2a2a;
}

.stock-name {
  font-size: 18px;
  font-weight: 600;
  color: #f1f5f9;
}

.stock-code {
  font-size: 12px;
  color: #64748b;
}

.signal-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.signal-card {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  padding: 10px 12px;
}

.signal-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.signal-confidence {
  font-size: 12px;
  color: #64748b;
}

.signal-card-body {
  font-size: 13px;
}

.signal-strategy {
  color: #e2e8f0;
  font-weight: 500;
  margin-bottom: 2px;
}

.signal-price {
  color: #64748b;
  font-size: 12px;
}

/* ========= 响应式 ========= */
@media (max-width: 900px) {
  .ide-body {
    flex-direction: column;
  }
  .signal-sidebar {
    width: 100%;
    max-height: none;
  }
}
</style>
