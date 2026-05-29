<template>
  <div class="indicator-ide theme-dark">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <!-- 代码编辑器切换 -->
        <a-tooltip title="代码编辑器">
          <a-button size="small" @click="showEditor = !showEditor">
            {{ showEditor ? 'x 关闭编辑器' : '&lt;/&gt; 策略代码' }}
          </a-button>
        </a-tooltip>

        <a-divider type="vertical" style="border-color:#334155" />

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

        <!-- 自选股快捷选择 -->
        <a-dropdown v-model="watchlistDropdownVisible" trigger="click">
          <a-button size="small" style="margin-right: 4px">
            <StarOutlined /> 自选 <DownOutlined />
          </a-button>
          <template #overlay>
            <a-menu @click="onWatchlistMenuClick">
            <a-menu-item v-if="watchlistStocks.length === 0" disabled>
              暂无自选股，请先在自选监控中添加
            </a-menu-item>
            <a-menu-item
              v-for="s in watchlistStocks"
              :key="s.symbol"
            >
              <span v-if="s.symbol === currentTsCode" style="color: #3b82f6; font-weight: 600">
                {{ s.name || s.symbol }} ({{ s.symbol }})
              </span>
              <span v-else>
                {{ s.name || s.symbol }} ({{ s.symbol }})
              </span>
            </a-menu-item>
            <a-menu-divider v-if="watchlistStocks.length > 0" />
            <a-menu-item key="__go_watchlist__">
              <FolderOpenOutlined /> 管理自选股
            </a-menu-item>
          </a-menu>
          </template>
        </a-dropdown>

        <!-- 返回选股系统 -->
        <a-tooltip title="选股系统">
          <a-button size="small" @click="$router.push('/screener')">
            <FilterOutlined /> 选股
          </a-button>
        </a-tooltip>

        <!-- 周期切换 -->
        <a-radio-group v-model="currentPeriod" button-style="solid" size="small" @change="handlePeriodChange">
          <a-radio-button value="D">日线</a-radio-button>
          <a-radio-button value="W">周线</a-radio-button>
          <a-radio-button value="M">月线</a-radio-button>
        </a-radio-group>
      </div>

      <div class="toolbar-right">
        <a-button size="small" @click="refreshChart">刷新</a-button>
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

      <span class="chips-spacer"></span>

      <!-- 自定义策略信号清空 -->
      <a-tag v-if="customSignals.length > 0" color="orange" closable @close="customSignals = []">
        自定义: {{ customSignals.length }} 个信号
      </a-tag>
    </div>

    <!-- 主内容区 -->
    <div class="ide-body">
      <!-- 左侧：代码编辑器（可折叠） -->
      <div v-show="showEditor" class="ide-editor-panel">
        <CodeEditor
          ref="codeEditor"
          :stockCode="currentTsCode"
          @strategy-result="onCustomStrategyResult"
        />
      </div>

      <!-- 中/右侧：K线图表 + 策略信号 -->
      <div class="ide-chart-section">
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

        <!-- 右侧多维度策略信号面板 -->
        <div class="signal-sidebar" v-if="currentTsCode">
          <div class="signal-header">
            <span class="signal-title">策略信号</span>
            <a-button size="small" type="link" @click="refreshSignals">刷新</a-button>
          </div>

          <div class="signal-content">
            <a-spin :spinning="signalsLoading" size="small">
              <div class="stock-info" v-if="stockInfo">
                <div class="stock-name">{{ stockInfo.name || currentTsCode }}</div>
                <div class="stock-code">{{ currentTsCode }}</div>
              </div>

              <!-- L2 主力分析 -->
              <div class="signal-section">
                <div class="section-label section-label-l2">L2 主力分析</div>
                <div v-if="signalsL2.length === 0 && customSignals.length === 0" class="section-empty">等待数据中...</div>
                <div v-for="sig in signalsL2" :key="sig.id" class="signal-card">
                  <div class="signal-card-header">
                    <a-tag :color="getSignalColor(sig)" size="small">
                      {{ sig.signal_label || sig.signal }}
                    </a-tag>
                    <span class="signal-confidence" v-if="sig.confidence">
                      {{ (sig.confidence * 100).toFixed(0) }}%
                    </span>
                    <span class="signal-stars" v-if="sig.confidence">
                      {{ renderStars(sig.confidence) }}
                    </span>
                  </div>
                  <div class="signal-card-body">
                    <div class="signal-strategy">{{ sig.strategy_name }}</div>
                    <ul class="signal-evidence" v-if="sig.evidence && sig.evidence.length > 0">
                      <li v-for="(ev, ei) in sig.evidence" :key="ei">{{ ev }}</li>
                    </ul>
                    <div class="signal-detail" v-if="sig.entry_zone">
                      <span class="detail-item">区间: {{ sig.entry_zone[0] }} - {{ sig.entry_zone[1] }}</span>
                    </div>
                    <div class="signal-detail" v-if="sig.risk_line">
                      <span class="detail-item detail-risk">止损: {{ sig.risk_line }}</span>
                    </div>
                    <div class="signal-detail" v-if="sig.target_zone">
                      <span class="detail-item detail-target">目标: {{ sig.target_zone[0] }} - {{ sig.target_zone[1] }}</span>
                    </div>
                    <div class="signal-detail" v-if="sig.position_suggestion">
                      <span class="detail-item">仓位: {{ sig.position_suggestion }}</span>
                    </div>
                    <div class="signal-risk" v-if="sig.risk_notes && sig.risk_notes.length > 0">
                      <span class="risk-icon">⚠</span>
                      <span v-for="(rn, ri) in sig.risk_notes" :key="ri">{{ rn }}<span v-if="ri < sig.risk_notes.length-1">; </span></span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- L3 策略验证 -->
              <div class="signal-section">
                <div class="section-label section-label-l3">L3 策略验证</div>
                <div v-if="signalsL3.length === 0 && customSignals.length === 0" class="section-empty">等待数据中...</div>
                <div v-for="sig in signalsL3" :key="sig.id" class="signal-card">
                  <div class="signal-card-header">
                    <a-tag :color="getSignalColor(sig)" size="small">
                      {{ sig.signal_label || sig.signal }}
                    </a-tag>
                    <span class="signal-confidence" v-if="sig.confidence">
                      {{ (sig.confidence * 100).toFixed(0) }}%
                    </span>
                    <span class="signal-stars" v-if="sig.confidence">
                      {{ renderStars(sig.confidence) }}
                    </span>
                  </div>
                  <div class="signal-card-body">
                    <div class="signal-strategy">{{ sig.strategy_name }}</div>
                    <ul class="signal-evidence" v-if="sig.evidence && sig.evidence.length > 0">
                      <li v-for="(ev, ei) in sig.evidence" :key="ei">{{ ev }}</li>
                    </ul>
                    <div class="signal-detail" v-if="sig.entry_zone">
                      <span class="detail-item">区间: {{ sig.entry_zone[0] }} - {{ sig.entry_zone[1] }}</span>
                    </div>
                    <div class="signal-detail" v-if="sig.risk_line">
                      <span class="detail-item detail-risk">止损: {{ sig.risk_line }}</span>
                    </div>
                    <div class="signal-detail" v-if="sig.target_zone">
                      <span class="detail-item detail-target">目标: {{ sig.target_zone[0] }} - {{ sig.target_zone[1] }}</span>
                    </div>
                    <div class="signal-detail" v-if="sig.position_suggestion">
                      <span class="detail-item">仓位: {{ sig.position_suggestion }}</span>
                    </div>
                    <div class="signal-risk" v-if="sig.risk_notes && sig.risk_notes.length > 0">
                      <span class="risk-icon">⚠</span>
                      <span v-for="(rn, ri) in sig.risk_notes" :key="ri">{{ rn }}<span v-if="ri < sig.risk_notes.length-1">; </span></span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 自定义策略 -->
              <div class="signal-section">
                <div class="section-label section-label-custom">自定义策略</div>
                <div v-if="customSignals.length === 0" class="section-empty">在左侧编辑器中运行策略产生信号</div>
                <div v-for="(sig, i) in customSignals" :key="'c'+i" class="signal-card custom">
                  <div class="signal-card-header">
                    <a-tag :color="sig.type === 'buy' ? 'red' : 'green'" size="small">
                      {{ sig.type === 'buy' ? '买入' : '卖出' }}
                    </a-tag>
                    <span class="signal-confidence" v-if="sig.price">¥{{ sig.price }}</span>
                  </div>
                  <div class="signal-card-body">
                    <div class="signal-strategy">{{ sig.text || '自定义信号' }}</div>
                  </div>
                </div>
              </div>

              <!-- 综合操作建议 -->
              <div class="composite-section" v-if="signals.length > 0 || customSignals.length > 0">
                <div class="section-label section-label-composite">综合操作建议</div>
                <div class="composite-card">
                  <div class="composite-row">
                    <span class="composite-key">策略</span>
                    <span class="composite-val">{{ compositeAdvice.action }}</span>
                  </div>
                  <div class="composite-row" v-if="compositeAdvice.entry">
                    <span class="composite-key">区间</span>
                    <span class="composite-val">{{ compositeAdvice.entry }}</span>
                  </div>
                  <div class="composite-row" v-if="compositeAdvice.stopLoss">
                    <span class="composite-key">止损</span>
                    <span class="composite-val composite-risk">{{ compositeAdvice.stopLoss }}</span>
                  </div>
                  <div class="composite-row" v-if="compositeAdvice.target">
                    <span class="composite-key">目标</span>
                    <span class="composite-val composite-target">{{ compositeAdvice.target }}</span>
                  </div>
                  <div class="composite-row" v-if="compositeAdvice.position">
                    <span class="composite-key">仓位</span>
                    <span class="composite-val">{{ compositeAdvice.position }}</span>
                  </div>
                  <div class="composite-row" v-if="compositeAdvice.period">
                    <span class="composite-key">期限</span>
                    <span class="composite-val">{{ compositeAdvice.period }}</span>
                  </div>
                  <div class="composite-row" v-if="compositeAdvice.compositeConfidence">
                    <span class="composite-key">综合赢率</span>
                    <span class="composite-val composite-confidence">{{ compositeAdvice.compositeConfidence }}</span>
                  </div>
                </div>
              </div>

              <a-empty v-if="signals.length === 0 && customSignals.length === 0" description="暂无信号" />
            </a-spin>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { DownOutlined, FilterOutlined, FolderOpenOutlined, StarOutlined } from '@ant-design/icons-vue'
import KLineChart from '@/components/KLineChart'
import CodeEditor from '@/components/CodeEditor'
import chartService from '@/services/chartService'
import axios from '@/utils/request'

export default {
  name: 'IndicatorIde',
  components: { KLineChart, CodeEditor },
  data() {
    return {
      showEditor: false,
      currentTsCode: this.$route.query.symbol || '600519.SH',
      currentPeriod: 'D',
      stockSearchResults: [],
      searching: false,
      stockInfo: null,

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

      activeOverlays: ['ma5', 'ma20'],
      activeSubcharts: ['vol', 'macd', 'rsi'],

      signals: [],
      signalsLoading: false,

      customSignals: [],

      aEmptyImage: '',
      watchlistStocks: [],
      watchlistDropdownVisible: false
    }
  },

  computed: {
    activeAllIndicators() {
      return [...this.activeOverlays, ...this.activeSubcharts]
    },

    /** L2 主力分析信号：筹码、主力相关 */
    signalsL2() {
      const keywords = ['筹码', '主力', 'chip', 'ASR', '集中度', 'main force']
      return this.signals.filter(s =>
        keywords.some(k => (s.strategy_name || '').toLowerCase().includes(k.toLowerCase()))
      )
    },

    /** L3 策略验证信号：缠论、因子、量价 */
    signalsL3() {
      const keywords = ['缠论', 'chanlun', '因子', 'factor', '量价', 'volume', '策略']
      const l2Keywords = ['筹码', '主力', 'chip', 'ASR', '集中度', 'main force']
      return this.signals.filter(s =>
        keywords.some(k => (s.strategy_name || '').toLowerCase().includes(k.toLowerCase())) &&
        !l2Keywords.some(k => (s.strategy_name || '').toLowerCase().includes(k.toLowerCase()))
      )
    },

    /** 综合操作建议 */
    compositeAdvice() {
      const all = [...this.signals, ...this.customSignals.map(s => ({
        ...s,
        signal: s.type === 'buy' ? 'BULLISH' : 'BEARISH',
        confidence: s.confidence || 0.5
      }))]
      if (all.length === 0) return {}

      const bullish = all.filter(s =>
        ['BULLISH', 'BUY', '买入'].includes(s.signal || s.signal_label || '')
      ).length
      const bearish = all.filter(s =>
        ['BEARISH', 'SELL', '卖出'].includes(s.signal || s.signal_label || '')
      ).length

      const confidences = all.map(s => s.confidence || 0).filter(c => c > 0)
      const avgConf = confidences.length > 0
        ? (confidences.reduce((a, b) => a + b, 0) / confidences.length)
        : 0

      const action = bullish > bearish ? '分批建仓'
        : bearish > bullish ? '减仓观望'
        : '持续观察'

      // 取最保守的止损/最积极的止盈
      const riskLines = all.filter(s => s.risk_line || s.riskLine).map(s => s.risk_line || s.riskLine)
      const targets = all.filter(s => s.target_zone || s.targetZone).map(s => {
        const z = s.target_zone || s.targetZone
        return Array.isArray(z) ? z[1] : z
      })
      const entryZones = all.filter(s => s.entry_zone || s.entryZone).map(s => {
        const z = s.entry_zone || s.entryZone
        return Array.isArray(z) ? z : null
      }).filter(Boolean)

      return {
        action,
        entry: entryZones.length > 0
          ? entryZones.map(z => z.join('-')).join(' / ')
          : undefined,
        stopLoss: riskLines.length > 0
          ? Math.min(...riskLines).toFixed(1)
          : undefined,
        target: targets.length > 0
          ? Math.max(...targets).toFixed(1)
          : undefined,
        position: all.find(s => s.position_suggestion)?.position_suggestion || undefined,
        period: all.find(s => s.holding_period)?.holding_period || undefined,
        compositeConfidence: (avgConf * 100).toFixed(0) + '%'
      }
    }
  },

  mounted() {
    this.loadWatchlistFromStorage()
    this.loadStockInfo()
    this.loadSignals()
  },

  methods: {
    renderStars(confidence) {
      const score = confidence * 100
      if (score >= 85) return '⭐⭐⭐⭐⭐'
      if (score >= 70) return '⭐⭐⭐⭐'
      if (score >= 55) return '⭐⭐⭐'
      if (score >= 40) return '⭐⭐'
      return '⭐'
    },

    getSignalColor(sig) {
      const s = (sig.signal || sig.signal_label || '').toUpperCase()
      if (s === 'BUY' || s === 'BULLISH' || s.indexOf('买入') >= 0 || s.indexOf('多') >= 0) return 'red'
      if (s === 'SELL' || s === 'BEARISH' || s.indexOf('卖出') >= 0 || s.indexOf('空') >= 0) return 'green'
      if (s === 'WATCH' || s.indexOf('观察') >= 0) return 'orange'
      return 'default'
    },

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

    loadWatchlistFromStorage() {
      try {
        const raw = localStorage.getItem('user_watchlist')
        if (raw) {
          this.watchlistStocks = JSON.parse(raw)
        }
      } catch (e) { /* ignore */ }
    },

    onWatchlistMenuClick(item) {
      this.watchlistDropdownVisible = false
      if (item.key === '__go_watchlist__') {
        this.$router.push({ name: 'Watchlist' })
        return
      }
      const stock = this.watchlistStocks.find(s => s.symbol === item.key)
      if (stock) {
        this.currentTsCode = stock.symbol
        this.handleStockChange(stock.symbol)
      }
    },

    async loadStockInfo() {
      try {
        const res = await axios.get('/api/v1/stocks/' + this.currentTsCode)
        if (res.success && res.data) {
          this.stockInfo = res.data
        }
      } catch (err) {
        // ignore
      }
    },

    handlePeriodChange() {},

    toggleOverlay(id) {
      const idx = this.activeOverlays.indexOf(id)
      if (idx >= 0) {
        if (this.activeOverlays.length > 1) {
          this.activeOverlays.splice(idx, 1)
        }
      } else {
        this.activeOverlays.push(id)
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

    onChartReady(chart) {
      console.log('K 线图表已就绪')
    },

    onDataLoaded(data) {
      this.stockInfo = data.stock || this.stockInfo
    },

    refreshChart() {
      if (this.$refs.klineChart) {
        this.$refs.klineChart.refresh()
      }
    },

    async loadSignals() {
      if (!this.currentTsCode) return
      this.signalsLoading = true
      try {
        const res = await axios.get('/api/v2/strategy/outputs', {
          params: { ts_code: this.currentTsCode, limit: 10 }
        })
        if (res.success && res.data) {
          this.signals = res.data
        }
      } catch (err) {
        // ignore
      } finally {
        this.signalsLoading = false
      }
    },

    refreshSignals() {
      this.loadSignals()
    },

    onCustomStrategyResult(data) {
      if (data && data.signals) {
        this.customSignals = data.signals
      }
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
.chips-spacer {
  flex: 1;
}

.ide-body {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.ide-editor-panel {
  width: 420px;
  flex-shrink: 0;
  border-radius: 8px;
  overflow: hidden;
}

.ide-chart-section {
  display: flex;
  gap: 12px;
  flex: 1;
  min-width: 0;
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

/* 各维度分区 */
.signal-section {
  margin-bottom: 16px;
}
.section-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 6px;
  font-weight: 600;
}
.section-label-l2 { color: #3b82f6; }
.section-label-l3 { color: #22c55e; }
.section-label-custom { color: #f59e0b; }
.section-label-composite { color: #a78bfa; }

.section-empty {
  font-size: 12px;
  color: #475569;
  padding: 8px 0;
  font-style: italic;
}

/* 信号卡片 */
.signal-card {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border-left: 3px solid transparent;
}
.signal-card:hover {
  background: rgba(255,255,255,0.06);
}
.signal-card.custom {
  border-left: 3px solid #f59e0b;
}
.signal-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.signal-confidence {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}
.signal-stars {
  font-size: 10px;
  letter-spacing: -1px;
  margin-left: auto;
}
.signal-card-body {
  font-size: 13px;
}
.signal-strategy {
  color: #e2e8f0;
  font-weight: 500;
  margin-bottom: 4px;
}
.signal-evidence {
  margin: 4px 0;
  padding-left: 14px;
  font-size: 12px;
  color: #94a3b8;
}
.signal-evidence li {
  margin-bottom: 2px;
}
.signal-detail {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
.detail-item { margin-right: 8px; }
.detail-risk { color: #ef4444; }
.detail-target { color: #22c55e; }
.signal-risk {
  font-size: 11px;
  color: #f59e0b;
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid rgba(245,158,11,0.15);
}
.risk-icon { margin-right: 3px; }

/* 综合操作建议卡片 */
.composite-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #334155;
}
.composite-card {
  background: linear-gradient(135deg, rgba(167,139,250,0.08), rgba(139,92,246,0.04));
  border: 1px solid rgba(167,139,250,0.2);
  border-radius: 8px;
  padding: 12px;
}
.composite-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 12px;
}
.composite-key { color: #94a3b8; }
.composite-val { color: #e2e8f0; font-weight: 500; }
.composite-risk { color: #ef4444; }
.composite-target { color: #22c55e; }
.composite-confidence { color: #a78bfa; font-weight: 700; }

@media (max-width: 900px) {
  .ide-body {
    flex-direction: column;
  }
  .ide-editor-panel {
    width: 100%;
    max-height: 400px;
  }
  .ide-chart-section {
    flex-direction: column;
  }
  .signal-sidebar {
    width: 100%;
    max-height: none;
  }
}
</style>
