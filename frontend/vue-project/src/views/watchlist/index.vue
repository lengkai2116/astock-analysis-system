<template>
  <div class="watchlist-page">
    <div class="page-header">
      <h1 class="page-title">📊 自选监控</h1>
      <div class="header-actions">
        <a-dropdown>
          <a-button>
            📈 策略中心 <DownOutlined />
          </a-button>
          <template #overlay>
            <a-menu>
              <a-menu-item @click="openFactorManager">因子组合管理</a-menu-item>
              <a-menu-item @click="runStrategyScreen">策略筛选</a-menu-item>
              <a-menu-divider />
              <a-menu-item @click="goToBacktest">回测系统</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <a-badge :count="socketConnected ? 0 : 1" :number-style="{ backgroundColor: '#f5222d' }">
          <a-button :type="socketConnected ? 'primary' : 'danger'" @click="toggleSocketConnection">
            {{ socketConnected ? '🔌 已连接' : '❌ 未连接' }}
          </a-button>
        </a-badge>
        <a-input-search
          v-model="searchQuery"
          placeholder="搜索股票"
          style="width: 200px; margin-left: 12px"
          @search="onSearch"
        />
        <a-button style="margin-left: 12px" @click="showColumnConfig = true">
          ⚙️ 配置列
        </a-button>
        <a-button style="margin-left: 8px" @click="refreshData">
          🔄 刷新
        </a-button>
      </div>
    </div>

    <!-- 自选分组管理 (150§4.3) -->
    <div class="watchlist-groups">
      <div class="groups-tabs">
        <a-tabs v-model:activeKey="activeGroup" size="small" @change="onGroupChange">
          <a-tab-pane v-for="group in groups" :key="group.id" :tab="group.name" />
        </a-tabs>
      </div>
      <div class="groups-actions">
        <a-popover title="新建分组" trigger="click">
          <template #content>
            <div class="group-form">
              <a-input v-model:value="newGroupName" placeholder="分组名称" size="small" />
              <a-button type="primary" size="small" style="margin-top: 8px" @click="addGroup">创建</a-button>
            </div>
          </template>
          <a-button size="small" type="dashed">
            ＋ 新建分组
          </a-button>
        </a-popover>
        <a-popover title="管理分组" trigger="click" v-if="groups.length > 1">
          <template #content>
            <div class="group-manage-list">
              <div v-for="g in groups" :key="g.id" class="group-manage-item">
                <span>{{ g.name }}</span>
                <a-button
                  v-if="!g.builtin"
                  type="link"
                  size="small"
                  danger
                  @click="removeGroup(g.id)"
                >
                  删除
                </a-button>
              </div>
            </div>
          </template>
          <a-button size="small" style="margin-left: 8px">
            管理分组
          </a-button>
        </a-popover>
      </div>
    </div>

    <div class="watchlist-table-container">
      <a-table
        :columns="visibleColumns"
        :data-source="filteredData"
        :pagination="false"
        :scroll="{ y: 'calc(100vh - 260px)' }"
        :loading="loading"
        row-key="symbol"
      >
        <template #bodyCell="{ column, text, record }">
          <template v-if="column.dataIndex === 'name' || column.key === 'name'">
            <div class="stock-name-cell">
              <span class="stock-symbol">{{ record.symbol }}</span>
              <span class="stock-name">{{ record.name }}</span>
            </div>
          </template>
          <template v-else-if="column.dataIndex === 'price' || column.key === 'price'">
            <span :class="getPriceClass(record)">¥{{ record.price?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'change' || column.key === 'change'">
            <span :class="getPriceClass(record)">{{ record.change >= 0 ? '+' : '' }}{{ record.change?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'changePercent' || column.key === 'changePercent'">
            <span :class="getPriceClass(record)">{{ record.changePercent >= 0 ? '+' : '' }}{{ record.changePercent?.toFixed(2) || '--' }}%</span>
          </template>
          <template v-else-if="column.dataIndex === 'volume' || column.key === 'volume'">
            <span>{{ formatVolume(record.volume) }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'amount' || column.key === 'amount'">
            <span>{{ formatAmount(record.amount) }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'high' || column.key === 'high'">
            <span>{{ record.high?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'low' || column.key === 'low'">
            <span>{{ record.low?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'open' || column.key === 'open'">
            <span>{{ record.open?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'preClose' || column.key === 'preClose'">
            <span>{{ record.preClose?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'avgPrice' || column.key === 'avgPrice'">
            <span>{{ record.avgPrice?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'amplitude' || column.key === 'amplitude'">
            <span>{{ record.amplitude?.toFixed(2) || '--' }}%</span>
          </template>
          <template v-else-if="column.dataIndex === 'volumeRatio' || column.key === 'volumeRatio'">
            <span>{{ record.volumeRatio?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'turnoverRate' || column.key === 'turnoverRate'">
            <span>{{ record.turnoverRate?.toFixed(2) || '--' }}%</span>
          </template>
          <template v-else-if="column.dataIndex === 'change5d' || column.key === 'change5d'">
            <span :class="getChangeClass(record.change5d)">{{ record.change5d >= 0 ? '+' : '' }}{{ record.change5d?.toFixed(2) || '--' }}%</span>
          </template>
          <template v-else-if="column.dataIndex === 'pe' || column.key === 'pe'">
            <span>{{ record.pe?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'pb' || column.key === 'pb'">
            <span>{{ record.pb?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'ma5' || column.key === 'ma5'">
            <span>{{ record.ma5?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'ma10' || column.key === 'ma10'">
            <span>{{ record.ma10?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'ma20' || column.key === 'ma20'">
            <span>{{ record.ma20?.toFixed(2) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'macd' || column.key === 'macd'">
            <span>{{ record.macd?.toFixed(3) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'rsi' || column.key === 'rsi'">
            <span>{{ record.rsi?.toFixed(1) || '--' }}</span>
          </template>
          <template v-else-if="column.dataIndex === 'actions' || column.key === 'actions'">
            <a-space>
              <a-button size="small" type="link" @click="goToChart(record)">图表</a-button>
              <a-button size="small" type="link" danger @click="removeFromWatchlist(record)">删除</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>

    <div class="page-footer">
      <div class="stats">
        <span>共 <strong class="highlight">{{ filteredData.length }}</strong> 只股票</span>
        <span>上涨 <strong class="up">{{ upCount }}</strong> 只</span>
        <span>下跌 <strong class="down">{{ downCount }}</strong> 只</span>
        <span class="connection-status" :class="{ connected: socketConnected }">
          ● {{ socketConnected ? '实时连接' : '已断开' }}
        </span>
        <span v-if="lastUpdateTime" class="update-time">
          最后更新: {{ lastUpdateTime }}
        </span>
      </div>
    </div>

    <!-- 列配置弹窗 -->
    <a-modal
      v-model:visible="showColumnConfig"
      title="配置显示列"
      @ok="saveColumnConfig"
      @cancel="cancelColumnConfig"
      wrap-class-name="column-config-modal"
      width="600px"
    >
      <div class="column-config">
        <div v-for="cat in columnCategories" :key="cat.key" class="config-section">
          <div class="section-title">{{ cat.label }}</div>
          <div class="column-pills">
            <div v-for="col in cat.columns" :key="col.id" class="custom-tag"
                 :class="col.visible ? 'custom-tag-visible' : 'custom-tag-hidden'"
                 @click="toggleColumn(col, !col.visible)">
              <span class="tag-text">{{ col.title }}</span>
              <span v-if="col.visible" class="tag-close" @click.stop="toggleColumn(col, false)">✕</span>
              <span v-else class="tag-plus">＋</span>
            </div>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script>
import { DownOutlined } from '@ant-design/icons-vue'
import socketService from '@/services/socketService'

export default {
  name: 'WatchlistPage',
  components: { DownOutlined },
  data() {
    return {
      searchQuery: '',
      loading: false,
      socketConnected: false,
      watchlist: [],
      lastUpdateTime: '',
      showColumnConfig: false,

      // 分组管理 (150§4.3)
      groups: JSON.parse(localStorage.getItem('watchlist-groups') || '[]'),
      activeGroup: 'all',
      newGroupName: '',

      allColumns: [
        { id: 'name', title: '名称', dataIndex: 'name', fixed: 'left', width: 160, visible: true, category: 'basic' },
        { id: 'price', title: '最新价', dataIndex: 'price', width: 100, visible: true, category: 'price' },
        { id: 'change', title: '涨跌额', dataIndex: 'change', width: 100, visible: true, category: 'price' },
        { id: 'changePercent', title: '涨跌幅', dataIndex: 'changePercent', width: 100, visible: true, category: 'price' },
        { id: 'volume', title: '成交量', dataIndex: 'volume', width: 110, visible: true, category: 'volume' },
        { id: 'amount', title: '成交额', dataIndex: 'amount', width: 120, visible: true, category: 'volume' },
        { id: 'open', title: '开盘', dataIndex: 'open', width: 100, visible: false, category: 'price' },
        { id: 'high', title: '最高', dataIndex: 'high', width: 100, visible: true, category: 'price' },
        { id: 'low', title: '最低', dataIndex: 'low', width: 100, visible: true, category: 'price' },
        { id: 'preClose', title: '昨收', dataIndex: 'preClose', width: 100, visible: false, category: 'price' },
        { id: 'avgPrice', title: '均价', dataIndex: 'avgPrice', width: 100, visible: false, category: 'price' },
        { id: 'amplitude', title: '振幅', dataIndex: 'amplitude', width: 90, visible: false, category: 'tech' },
        { id: 'volumeRatio', title: '量比', dataIndex: 'volumeRatio', width: 80, visible: false, category: 'tech' },
        { id: 'turnoverRate', title: '换手率', dataIndex: 'turnoverRate', width: 90, visible: false, category: 'tech' },
        { id: 'change5d', title: '5日涨跌', dataIndex: 'change5d', width: 100, visible: false, category: 'trend' },
        { id: 'ma5', title: 'MA5', dataIndex: 'ma5', width: 100, visible: false, category: 'tech' },
        { id: 'ma10', title: 'MA10', dataIndex: 'ma10', width: 100, visible: false, category: 'tech' },
        { id: 'ma20', title: 'MA20', dataIndex: 'ma20', width: 100, visible: false, category: 'tech' },
        { id: 'macd', title: 'MACD', dataIndex: 'macd', width: 100, visible: false, category: 'tech' },
        { id: 'rsi', title: 'RSI', dataIndex: 'rsi', width: 80, visible: false, category: 'tech' },
        { id: 'pe', title: '市盈率', dataIndex: 'pe', width: 100, visible: false, category: 'fundamental' },
        { id: 'pb', title: '市净率', dataIndex: 'pb', width: 100, visible: false, category: 'fundamental' },
        { id: 'actions', title: '操作', key: 'actions', width: 120, visible: true, category: 'actions' },
      ],
    }
  },
  computed: {
    visibleColumns() {
      return this.allColumns.filter(c => c.visible).map(c => ({
        title: c.title, dataIndex: c.dataIndex, key: c.key || c.dataIndex,
        width: c.width, fixed: c.fixed,
      }))
    },
    columnCategories() {
      const catMap = {
        basic: { key: 'basic', label: '基本信息', columns: [] },
        price: { key: 'price', label: '价格数据', columns: [] },
        volume: { key: 'volume', label: '量能数据', columns: [] },
        tech: { key: 'tech', label: '技术指标', columns: [] },
        trend: { key: 'trend', label: '趋势表现', columns: [] },
        fundamental: { key: 'fundamental', label: '基本面', columns: [] },
        actions: { key: 'actions', label: '操作', columns: [] },
      }
      this.allColumns.forEach(c => {
        const cat = catMap[c.category]
        if (cat) cat.columns.push(c)
      })
      return Object.values(catMap)
    },
    filteredData() {
      if (!this.searchQuery) return this.groupedData
      const q = this.searchQuery.toLowerCase()
      return this.groupedData.filter(s =>
        s.symbol?.toLowerCase().includes(q) ||
        s.name?.toLowerCase().includes(q)
      )
    },
    groupedData() {
      if (this.activeGroup === 'all') return this.watchlist
      const group = this.groups.find(g => g.id === this.activeGroup)
      if (!group) return this.watchlist
      const symbols = group.symbols || []
      return this.watchlist.filter(s => symbols.includes(s.symbol))
    },
    upCount() {
      return this.filteredData.filter(s => (s.changePercent || 0) > 0).length
    },
    downCount() {
      return this.filteredData.filter(s => (s.changePercent || 0) < 0).length
    },
  },
  async mounted() {
    this.loadWatchlistFromStorage()

    // 若没有分组，初始化默认分组
    if (this.groups.length === 0) {
      this.groups = [
        { id: 'default', name: '默认分组', symbols: [], builtin: true },
      ]
      this.saveGroups()
    }

    await this.loadInitialData()

    // WebSocket 监听
    this._socketHandler = this.initSocket()
    window.addEventListener('app:refresh-data', this.refreshData)
  },
  beforeUnmount() {
    if (this._socketHandler) this._socketHandler()
    window.removeEventListener('app:refresh-data', this.refreshData)
  },
  methods: {
    // ====== 分组管理 (150§4.3) ======
    saveGroups() {
      localStorage.setItem('watchlist-groups', JSON.stringify(this.groups))
    },
    addGroup() {
      if (!this.newGroupName.trim()) return
      this.groups.push({
        id: 'group-' + Date.now(),
        name: this.newGroupName.trim(),
        symbols: [],
        builtin: false,
      })
      this.saveGroups()
      this.newGroupName = ''
    },
    removeGroup(id) {
      this.groups = this.groups.filter(g => g.id !== id)
      if (this.activeGroup === id) this.activeGroup = 'all'
      this.saveGroups()
    },
    onGroupChange(groupId) {
      this.activeGroup = groupId
    },

    async loadInitialData() {
      this.loading = true
      try {
        const { default: dataService } = await import('@/services/dataService')
        const res = await dataService.getWatchlistData()
        if (res?.stocks?.length) {
          this.updateWatchlistData(res.stocks)
        }
      } catch {}

      // 兜底: 使用 App Store 中的自选股
      try {
        const { useAppStore } = await import('@/stores')
        const appStore = useAppStore()
        if (appStore.watchlist?.length && this.watchlist.length === 0) {
          this.watchlist = appStore.watchlist.map(s => ({
            symbol: s.symbol,
            name: s.name || s.symbol,
            price: 0, change: 0, changePercent: 0,
          }))
        }
      } catch {}

      this.loading = false
    },

    updateWatchlistData(stocks) {
      if (!stocks?.length) return
      stocks.forEach(stock => {
        const idx = this.watchlist.findIndex(s => s.symbol === stock.ts_code || s.symbol === stock.symbol)
        const updateData = {
          symbol: stock.ts_code || stock.symbol,
          name: stock.name,
          price: stock.price || stock.close,
          change: stock.change,
          changePercent: stock.pct_chg || stock.changePercent,
          open: stock.open,
          high: stock.high,
          low: stock.low,
          preClose: stock.pre_close,
          volume: stock.vol || stock.volume,
          amount: stock.amount,
          avgPrice: stock.avg_price,
          amplitude: stock.amplitude,
          volumeRatio: stock.vol_ratio || stock.volumeRatio,
          turnoverRate: stock.turnover_rate || stock.turnoverRate,
          change5d: stock.change_5d || stock.change5d,
          pe: stock.pe,
          pb: stock.pb,
          ma5: stock.ma5,
          ma10: stock.ma10,
          ma20: stock.ma20,
          macd: stock.macd,
          rsi: stock.rsi,
          limitUp: stock.limit_up || stock.limitUp,
          limitDown: stock.limit_down || stock.limitDown,
          updateTime: new Date().toLocaleTimeString(),
        }

        if (idx !== -1) {
          this.watchlist[idx] = { ...this.watchlist[idx], ...updateData }
        } else {
          this.watchlist.push(updateData)
        }
      })
      this.lastUpdateTime = new Date().toLocaleTimeString()
    },

    initSocket() {
      if (!socketService) return () => {}
      const handler = (data) => {
        if (data?.data?.stocks) {
          this.updateWatchlistData(data.data.stocks)
        }
      }
      try {
        socketService.on('market-data', handler)
        socketService.on('connect', () => { this.socketConnected = true })
        socketService.on('disconnect', () => { this.socketConnected = false })
        this.socketConnected = socketService.connected || false
      } catch {}
      return () => {
        try { socketService.off('market-data', handler) } catch {}
      }
    },

    toggleSocketConnection() {
      if (this.socketConnected) {
        try { socketService.disconnect() } catch {}
        this.socketConnected = false
      } else {
        try { socketService.connect() } catch {}
      }
    },

    refreshData() {
      this.loadInitialData()
    },

    onSearch() {},

    toggleColumn(col, visible) {
      const target = this.allColumns.find(c => c.id === col.id)
      if (target) target.visible = visible
    },

    saveColumnConfig() { this.showColumnConfig = false },
    cancelColumnConfig() { this.showColumnConfig = false },
    resetColumns() {
      this.allColumns.forEach(c => {
        c.visible = ['name', 'price', 'change', 'changePercent', 'volume', 'amount', 'high', 'low', 'actions'].includes(c.id)
      })
    },

    openFactorManager() { this.$router.push({ name: 'FactorManager' }) },
    runStrategyScreen() { this.$router.push({ name: 'FactorManager', query: { tab: 'screen' } }) },
    goToBacktest() { this.$router.push({ name: 'Backtest' }) },

    loadWatchlistFromStorage() {
      try {
        const raw = localStorage.getItem('user_watchlist')
        if (raw && this.watchlist.length === 0) {
          const list = JSON.parse(raw)
          this.watchlist = list.map(s => ({ ...s }))
        }
      } catch {}
    },

    goToChart(record) {
      this.$router.push({ name: 'IndicatorIDE', query: { symbol: record.symbol } })
    },

    removeFromWatchlist(record) {
      const idx = this.watchlist.findIndex(s => s.symbol === record.symbol)
      if (idx !== -1) this.watchlist.splice(idx, 1)
    },

    getPriceClass(record) {
      if (!record) return ''
      if (record.changePercent > 0) return 'text-up'
      if (record.changePercent < 0) return 'text-down'
      return 'text-flat'
    },
    getChangeClass(value) {
      if (value === null || value === undefined) return ''
      if (value > 0) return 'text-up'
      if (value < 0) return 'text-down'
      return 'text-flat'
    },

    formatVolume(v) {
      if (!v) return '--'
      if (v >= 100000000) return (v / 100000000).toFixed(2) + '亿'
      if (v >= 10000) return (v / 10000).toFixed(2) + '万'
      return v.toLocaleString()
    },
    formatAmount(a) {
      if (!a) return '--'
      if (a >= 100000000) return (a / 100000000).toFixed(2) + '亿'
      if (a >= 10000) return (a / 10000).toFixed(2) + '万'
      return a.toLocaleString()
    },
  },
}
</script>

<style scoped>
.watchlist-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas);
  color: var(--text-primary);
  transition: background 0.3s ease;
}

.page-header {
  padding: 16px 24px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.header-actions { display: flex; align-items: center; }

/* 分组管理 (150§4.3) */
.watchlist-groups {
  padding: 8px 24px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.groups-tabs { flex: 1; }
.groups-tabs :deep(.ant-tabs-nav) { margin-bottom: 0; }
.groups-actions { display: flex; align-items: center; flex-shrink: 0; }

.group-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 180px;
}

.group-manage-list { min-width: 160px; }
.group-manage-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.watchlist-table-container {
  flex: 1;
  padding: 0 24px 16px;
  overflow: hidden;
}

.watchlist-table-container :deep(.ant-table) { background: transparent; }

.stock-name-cell { display: flex; flex-direction: column; }
.stock-symbol { font-weight: 600; color: var(--text-secondary); font-size: 12px; }
.stock-name { color: var(--text-primary); }
.text-up { color: var(--color-up); font-weight: 600; }
.text-down { color: var(--color-down); font-weight: 600; }
.text-flat { color: var(--text-secondary); }

.page-footer {
  padding: 12px 24px;
  background: var(--bg-surface);
  border-top: 1px solid var(--border-default);
}

.stats { display: flex; gap: 24px; align-items: center; }
.connection-status { padding: 4px 12px; border-radius: var(--radius-xs); background: var(--bg-muted); }
.connection-status.connected { background: rgba(34, 197, 94, 0.15); color: var(--color-down); }
.highlight { font-weight: 600; color: var(--color-brand-500); }
.up { color: var(--color-up); font-weight: 600; }
.down { color: var(--color-down); font-weight: 600; }
.update-time { color: var(--text-muted); font-size: 12px; }

.column-config { padding: 16px 0; }
.config-section { margin-bottom: 24px; }
.section-title { font-weight: 600; margin-bottom: 12px; color: var(--text-primary); font-size: 14px; }
.column-pills { display: flex; flex-wrap: wrap; gap: 8px; }
</style>

<style>
.column-config-modal .ant-modal-body { background: var(--bg-surface); }
.column-config-modal .section-title { color: var(--text-primary) !important; font-weight: 600; font-size: 14px; margin-bottom: 12px; }
.column-config-modal .custom-tag {
  display: inline-flex; align-items: center;
  padding: 4px 12px; border-radius: var(--radius-sm);
  font-size: 14px; margin: 4px;
  cursor: pointer; transition: all 0.2s ease;
}
.column-config-modal .custom-tag-visible {
  background: var(--color-brand-500) !important;
  color: #ffffff !important;
}
.column-config-modal .custom-tag-hidden {
  background: var(--bg-muted) !important;
  color: var(--text-secondary) !important;
}
.column-config-modal .custom-tag-hidden:hover { background: var(--border-strong) !important; }
.column-config-modal .tag-text,
.column-config-modal .tag-text * { color: inherit !important; font-weight: 500 !important; }
.column-config-modal .custom-tag-visible .tag-text,
.column-config-modal .custom-tag-visible .tag-text * { color: #ffffff !important; }
.column-config-modal .custom-tag-hidden .tag-text,
.column-config-modal .custom-tag-hidden .tag-text * { color: var(--text-secondary) !important; }
.column-config-modal .tag-close { margin-left: 8px; cursor: pointer; font-size: 16px; opacity: 0.8; }
.column-config-modal .tag-plus { margin-right: 4px; font-weight: bold; }
</style>
