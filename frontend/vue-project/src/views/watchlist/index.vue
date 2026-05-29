<template>
  <div class="watchlist-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">📊 自选监控</h1>
      <div class="header-actions">
        <a-dropdown>
          <a-button>
            📈 策略中心 <a-icon type="down" />
          </a-button>
          <a-menu slot="overlay">
            <a-menu-item @click="openFactorManager">
              因子组合管理
            </a-menu-item>
            <a-menu-item @click="runStrategyScreen">
              策略筛选
            </a-menu-item>
            <a-menu-divider />
            <a-menu-item @click="goToBacktest">
              回测系统
            </a-menu-item>
          </a-menu>
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

    <div class="watchlist-table-container">
      <a-table
        :columns="visibleColumns"
        :data-source="filteredData"
        :pagination="false"
        :scroll="{ y: 'calc(100vh - 200px)' }"
        :loading="loading"
        row-key="symbol"
      >
        <template slot="name" slot-scope="text, record">
          <div class="stock-name-cell">
            <span class="stock-symbol">{{ record.symbol }}</span>
            <span class="stock-name">{{ record.name }}</span>
          </div>
        </template>

        <template slot="price" slot-scope="text, record">
          <span :class="getPriceClass(record)">
            ¥{{ record.price?.toFixed(2) || '--' }}
          </span>
        </template>

        <template slot="change" slot-scope="text, record">
          <span :class="getPriceClass(record)">
            {{ record.change >= 0 ? '+' : '' }}{{ record.change?.toFixed(2) || '--' }}
          </span>
        </template>

        <template slot="changePercent" slot-scope="text, record">
          <span :class="getPriceClass(record)">
            {{ record.changePercent >= 0 ? '+' : '' }}{{ record.changePercent?.toFixed(2) || '--' }}%
          </span>
        </template>

        <template slot="volume" slot-scope="text, record">
          <span>{{ formatVolume(record.volume) }}</span>
        </template>

        <template slot="amount" slot-scope="text, record">
          <span>{{ formatAmount(record.amount) }}</span>
        </template>

        <template slot="high" slot-scope="text, record">
          <span>{{ record.high?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="low" slot-scope="text, record">
          <span>{{ record.low?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="open" slot-scope="text, record">
          <span>{{ record.open?.toFixed(2) || '--' }}</span>
        </template>

        <!-- 行情相关 -->
        <template slot="preClose" slot-scope="text, record">
          <span>{{ record.preClose?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="limitUp" slot-scope="text, record">
          <span class="text-up">{{ record.limitUp?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="limitDown" slot-scope="text, record">
          <span class="text-down">{{ record.limitDown?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="avgPrice" slot-scope="text, record">
          <span>{{ record.avgPrice?.toFixed(2) || '--' }}</span>
        </template>

        <!-- 涨跌分析 -->
        <template slot="amplitude" slot-scope="text, record">
          <span>{{ record.amplitude?.toFixed(2) || '--' }}%</span>
        </template>

        <template slot="volumeRatio" slot-scope="text, record">
          <span>{{ record.volumeRatio?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="turnoverRate" slot-scope="text, record">
          <span>{{ record.turnoverRate?.toFixed(2) || '--' }}%</span>
        </template>

        <template slot="change5d" slot-scope="text, record">
          <span :class="getChangeClass(record.change5d)">
            {{ record.change5d >= 0 ? '+' : '' }}{{ record.change5d?.toFixed(2) || '--' }}%
          </span>
        </template>

        <template slot="change10d" slot-scope="text, record">
          <span :class="getChangeClass(record.change10d)">
            {{ record.change10d >= 0 ? '+' : '' }}{{ record.change10d?.toFixed(2) || '--' }}%
          </span>
        </template>

        <template slot="change20d" slot-scope="text, record">
          <span :class="getChangeClass(record.change20d)">
            {{ record.change20d >= 0 ? '+' : '' }}{{ record.change20d?.toFixed(2) || '--' }}%
          </span>
        </template>

        <!-- 技术指标 -->
        <template slot="ma5" slot-scope="text, record">
          <span>{{ record.ma5?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="ma10" slot-scope="text, record">
          <span>{{ record.ma10?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="ma20" slot-scope="text, record">
          <span>{{ record.ma20?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="ma60" slot-scope="text, record">
          <span>{{ record.ma60?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="macd" slot-scope="text, record">
          <span :class="getChangeClass(record.macd)">{{ record.macd?.toFixed(3) || '--' }}</span>
        </template>

        <template slot="kdj" slot-scope="text, record">
          <span>{{ record.kdj ? `K${record.kdj.k?.toFixed(1)} D${record.kdj.d?.toFixed(1)} J${record.kdj.j?.toFixed(1)}` : '--' }}</span>
        </template>

        <template slot="rsi" slot-scope="text, record">
          <span>{{ record.rsi?.toFixed(1) || '--' }}</span>
        </template>

        <!-- 基本面 -->
        <template slot="pe" slot-scope="text, record">
          <span>{{ record.pe?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="peTTM" slot-scope="text, record">
          <span>{{ record.peTTM?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="pb" slot-scope="text, record">
          <span>{{ record.pb?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="ps" slot-scope="text, record">
          <span>{{ record.ps?.toFixed(2) || '--' }}</span>
        </template>

        <template slot="roe" slot-scope="text, record">
          <span>{{ record.roe?.toFixed(2) || '--' }}%</span>
        </template>

        <template slot="eps" slot-scope="text, record">
          <span>{{ record.eps?.toFixed(3) || '--' }}</span>
        </template>

        <template slot="navps" slot-scope="text, record">
          <span>{{ record.navps?.toFixed(2) || '--' }}</span>
        </template>

        <!-- 市值股本 -->
        <template slot="totalMarketCap" slot-scope="text, record">
          <span>{{ formatAmount(record.totalMarketCap) }}</span>
        </template>

        <template slot="floatMarketCap" slot-scope="text, record">
          <span>{{ formatAmount(record.floatMarketCap) }}</span>
        </template>

        <template slot="totalShare" slot-scope="text, record">
          <span>{{ formatVolume(record.totalShare) }}</span>
        </template>

        <template slot="floatShare" slot-scope="text, record">
          <span>{{ formatVolume(record.floatShare) }}</span>
        </template>

        <!-- 资金流向 -->
        <template slot="mainNetInflow" slot-scope="text, record">
          <span :class="getChangeClass(record.mainNetInflow)">
            {{ record.mainNetInflow >= 0 ? '+' : '' }}{{ formatAmount(record.mainNetInflow) }}
          </span>
        </template>

        <template slot="superLargeInflow" slot-scope="text, record">
          <span :class="getChangeClass(record.superLargeInflow)">
            {{ record.superLargeInflow >= 0 ? '+' : '' }}{{ formatAmount(record.superLargeInflow) }}
          </span>
        </template>

        <template slot="largeInflow" slot-scope="text, record">
          <span :class="getChangeClass(record.largeInflow)">
            {{ record.largeInflow >= 0 ? '+' : '' }}{{ formatAmount(record.largeInflow) }}
          </span>
        </template>

        <template slot="mediumInflow" slot-scope="text, record">
          <span :class="getChangeClass(record.mediumInflow)">
            {{ record.mediumInflow >= 0 ? '+' : '' }}{{ formatAmount(record.mediumInflow) }}
          </span>
        </template>

        <template slot="smallInflow" slot-scope="text, record">
          <span :class="getChangeClass(record.smallInflow)">
            {{ record.smallInflow >= 0 ? '+' : '' }}{{ formatAmount(record.smallInflow) }}
          </span>
        </template>

        <template slot="mainNetRatio" slot-scope="text, record">
          <span :class="getChangeClass(record.mainNetRatio)">
            {{ record.mainNetRatio >= 0 ? '+' : '' }}{{ record.mainNetRatio?.toFixed(2) || '--' }}%
          </span>
        </template>

        <!-- 融资融券 -->
        <template slot="marginBalance" slot-scope="text, record">
          <span>{{ formatAmount(record.marginBalance) }}</span>
        </template>

        <template slot="shortBalance" slot-scope="text, record">
          <span>{{ formatAmount(record.shortBalance) }}</span>
        </template>

        <template slot="marginBuy" slot-scope="text, record">
          <span>{{ formatAmount(record.marginBuy) }}</span>
        </template>

        <template slot="shortSell" slot-scope="text, record">
          <span>{{ formatAmount(record.shortSell) }}</span>
        </template>

        <!-- 北向资金 -->
        <template slot="northboundHolding" slot-scope="text, record">
          <span>{{ formatAmount(record.northboundHolding) }}</span>
        </template>

        <template slot="northboundHoldingRatio" slot-scope="text, record">
          <span>{{ record.northboundHoldingRatio?.toFixed(2) || '--' }}%</span>
        </template>

        <template slot="northboundChange" slot-scope="text, record">
          <span :class="getChangeClass(record.northboundChange)">
            {{ record.northboundChange >= 0 ? '+' : '' }}{{ record.northboundChange?.toFixed(2) || '--' }}%
          </span>
        </template>

        <!-- 龙虎榜 -->
        <template slot="dragonTigerList" slot-scope="text, record">
          <span v-if="record.isOnDragonTigerList" style="color: #f59e0b; font-weight: 600;">🏆 上榜</span>
          <span v-else>--</span>
        </template>

        <template slot="limitCount" slot-scope="text, record">
          <span v-if="record.limitCount" style="color: #ef4444; font-weight: 600;">{{ record.limitCount }}板</span>
          <span v-else>--</span>
        </template>

        <template slot="firstLimitTime" slot-scope="text, record">
          <span>{{ record.firstLimitTime || '--' }}</span>
        </template>

        <template slot="lastLimitTime" slot-scope="text, record">
          <span>{{ record.lastLimitTime || '--' }}</span>
        </template>

        <template slot="limitOpenCount" slot-scope="text, record">
          <span>{{ record.limitOpenCount || '--' }}</span>
        </template>

        <template slot="updateTime" slot-scope="text, record">
          <span class="update-time">{{ record.updateTime || '--' }}</span>
        </template>

        <template slot="actions" slot-scope="text, record">
          <a @click="goToChart(record)">📈 分析</a>
          <a-divider type="vertical" />
          <a-popconfirm title="确定移除该股票吗？" @confirm="removeFromWatchlist(record)">
            <a>✕ 移除</a>
          </a-popconfirm>
        </template>
      </a-table>
    </div>

    <div class="page-footer">
      <div class="stats">
        <span class="connection-status" :class="{ connected: socketConnected }">
          {{ socketConnected ? '🟢 实时数据' : '🟡 本地数据' }}
        </span>
        <span>共 <span class="highlight">{{ watchlist.length }}</span> 只自选股</span>
        <span class="up"> {{ stats.upCount }} 只上涨</span>
        <span class="down"> {{ stats.downCount }} 只下跌</span>
        <span> {{ stats.flatCount }} 只平盘</span>
        <span>最后更新: {{ lastUpdateTime }}</span>
      </div>
    </div>

    <!-- 列配置弹窗 -->
    <a-modal
      v-model="showColumnConfig"
      title="📋 配置显示列"
      width="800px"
      class="column-config-modal"
      @ok="saveColumnConfig"
      @cancel="cancelColumnConfig"
    >
      <div class="column-config" style="background: transparent;">
        <div class="config-section">
          <div class="section-title" style="color: #ffffff !important; font-weight: 600; font-size: 14px; margin-bottom: 12px;">已显示的列</div>
          <div class="column-pills" style="display: flex; flex-wrap: wrap; gap: 8px;">
            <span
              v-for="col in visibleColumnsForModal"
              :key="col.id"
              @click="toggleColumn(col, false)"
              style="background: #d0d0d0; color: #333333; display: inline-flex; align-items: center; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin: 4px; cursor: pointer; white-space: nowrap;"
            >
              <span style="color: #333333; margin-right: 4px; font-weight: bold;">-</span>
              <span style="color: #333333; font-weight: 500;">{{ col.name }}</span>
            </span>
          </div>
        </div>
        
        <div v-for="(columns, category) in groupedHiddenColumns" :key="category" class="config-section">
          <div class="section-title" style="color: #ffffff !important; font-weight: 600; font-size: 14px; margin-bottom: 12px; margin-top: 24px;">
            📂 {{ category }}
          </div>
          <div class="column-pills" style="display: flex; flex-wrap: wrap; gap: 8px;">
            <span
              v-for="col in columns"
              :key="col.id"
              @click="toggleColumn(col, true)"
              style="background: #f0f0f0; color: #333333; display: inline-flex; align-items: center; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin: 4px; cursor: pointer; white-space: nowrap;"
            >
              <span style="color: #333333; margin-right: 4px; font-weight: bold;">+</span>
              <span style="color: #333333; font-weight: 500;">{{ col.name }}</span>
            </span>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script>
import socketService from '../../services/socketService'

export default {
  name: 'WatchlistPage',
  data() {
    return {
      searchQuery: '',
      showColumnConfig: false,
      loading: false,
      socketConnected: false,
      lastUpdateTime: '--',

      allColumns: [
        // 基础信息
        { id: 'name', name: '名称', visible: true, order: 1, width: 180, category: '基础' },
        { id: 'price', name: '最新价', visible: true, order: 2, width: 110, category: '基础' },
        { id: 'change', name: '涨跌额', visible: true, order: 3, width: 110, category: '基础' },
        { id: 'changePercent', name: '涨跌幅', visible: true, order: 4, width: 110, category: '基础' },
        
        // 价格行情
        { id: 'volume', name: '成交量', visible: true, order: 5, width: 110, category: '行情' },
        { id: 'amount', name: '成交额', visible: true, order: 6, width: 120, category: '行情' },
        { id: 'high', name: '最高', visible: true, order: 7, width: 90, category: '行情' },
        { id: 'low', name: '最低', visible: true, order: 8, width: 90, category: '行情' },
        { id: 'open', name: '今开', visible: false, order: 9, width: 90, category: '行情' },
        { id: 'preClose', name: '昨收', visible: false, order: 10, width: 90, category: '行情' },
        { id: 'limitUp', name: '涨停价', visible: false, order: 11, width: 90, category: '行情' },
        { id: 'limitDown', name: '跌停价', visible: false, order: 12, width: 90, category: '行情' },
        { id: 'avgPrice', name: '均价', visible: false, order: 13, width: 90, category: '行情' },
        
        // 涨跌分析
        { id: 'amplitude', name: '振幅', visible: false, order: 20, width: 90, category: '涨跌' },
        { id: 'volumeRatio', name: '量比', visible: false, order: 21, width: 90, category: '涨跌' },
        { id: 'turnoverRate', name: '换手率', visible: false, order: 22, width: 100, category: '涨跌' },
        { id: 'change5d', name: '5日涨跌', visible: false, order: 23, width: 100, category: '涨跌' },
        { id: 'change10d', name: '10日涨跌', visible: false, order: 24, width: 100, category: '涨跌' },
        { id: 'change20d', name: '20日涨跌', visible: false, order: 25, width: 100, category: '涨跌' },
        
        // 技术指标
        { id: 'ma5', name: 'MA5', visible: false, order: 30, width: 90, category: '技术' },
        { id: 'ma10', name: 'MA10', visible: false, order: 31, width: 90, category: '技术' },
        { id: 'ma20', name: 'MA20', visible: false, order: 32, width: 90, category: '技术' },
        { id: 'ma60', name: 'MA60', visible: false, order: 33, width: 90, category: '技术' },
        { id: 'macd', name: 'MACD', visible: false, order: 34, width: 100, category: '技术' },
        { id: 'kdj', name: 'KDJ', visible: false, order: 35, width: 100, category: '技术' },
        { id: 'rsi', name: 'RSI', visible: false, order: 36, width: 90, category: '技术' },
        
        // 基本面
        { id: 'pe', name: 'PE(动)', visible: false, order: 40, width: 80, category: '基本面' },
        { id: 'peTTM', name: 'PE(TTM)', visible: false, order: 41, width: 90, category: '基本面' },
        { id: 'pb', name: 'PB', visible: false, order: 42, width: 80, category: '基本面' },
        { id: 'ps', name: 'PS', visible: false, order: 43, width: 80, category: '基本面' },
        { id: 'roe', name: 'ROE', visible: false, order: 44, width: 90, category: '基本面' },
        { id: 'eps', name: 'EPS', visible: false, order: 45, width: 80, category: '基本面' },
        { id: 'navps', name: '每股净资产', visible: false, order: 46, width: 100, category: '基本面' },
        
        // 市值股本
        { id: 'totalMarketCap', name: '总市值', visible: false, order: 50, width: 120, category: '市值' },
        { id: 'floatMarketCap', name: '流通市值', visible: false, order: 51, width: 120, category: '市值' },
        { id: 'totalShare', name: '总股本', visible: false, order: 52, width: 120, category: '市值' },
        { id: 'floatShare', name: '流通股本', visible: false, order: 53, width: 120, category: '市值' },
        
        // 资金流向
        { id: 'mainNetInflow', name: '主力净流入', visible: false, order: 60, width: 130, category: '资金' },
        { id: 'superLargeInflow', name: '超大单流入', visible: false, order: 61, width: 130, category: '资金' },
        { id: 'largeInflow', name: '大单流入', visible: false, order: 62, width: 120, category: '资金' },
        { id: 'mediumInflow', name: '中单流入', visible: false, order: 63, width: 120, category: '资金' },
        { id: 'smallInflow', name: '小单流入', visible: false, order: 64, width: 120, category: '资金' },
        { id: 'mainNetRatio', name: '主力净占比', visible: false, order: 65, width: 120, category: '资金' },
        
        // 融资融券
        { id: 'marginBalance', name: '融资余额', visible: false, order: 70, width: 120, category: '两融' },
        { id: 'shortBalance', name: '融券余额', visible: false, order: 71, width: 120, category: '两融' },
        { id: 'marginBuy', name: '融资买入', visible: false, order: 72, width: 120, category: '两融' },
        { id: 'shortSell', name: '融券卖出', visible: false, order: 73, width: 120, category: '两融' },
        
        // 北向资金
        { id: 'northboundHolding', name: '北向持股', visible: false, order: 80, width: 120, category: '北向' },
        { id: 'northboundHoldingRatio', name: '北向持股比例', visible: false, order: 81, width: 140, category: '北向' },
        { id: 'northboundChange', name: '北向变动', visible: false, order: 82, width: 120, category: '北向' },
        
        // 龙虎榜
        { id: 'dragonTigerList', name: '龙虎榜', visible: false, order: 90, width: 100, category: '异动' },
        { id: 'limitCount', name: '连板数', visible: false, order: 91, width: 90, category: '异动' },
        { id: 'firstLimitTime', name: '首次涨停', visible: false, order: 92, width: 120, category: '异动' },
        { id: 'lastLimitTime', name: '最后涨停', visible: false, order: 93, width: 120, category: '异动' },
        { id: 'limitOpenCount', name: '开板次数', visible: false, order: 94, width: 110, category: '异动' },
        
        // 其他
        { id: 'updateTime', name: '更新时间', visible: true, order: 998, width: 140, category: '其他' },
        { id: 'actions', name: '操作', visible: true, order: 999, width: 120, fixed: 'right', category: '其他' }
      ],

      watchlist: [
        {
          symbol: '600519.SH',
          name: '贵州茅台',
          price: 1850.00,
          change: 42.50,
          changePercent: 2.35,
          volume: 52000,
          amount: 962000000,
          high: 1868.00,
          low: 1802.00,
          open: 1808.00,
          preClose: 1807.50,
          limitUp: 1988.25,
          limitDown: 1626.75,
          avgPrice: 1850.00,
          amplitude: 3.65,
          volumeRatio: 1.25,
          turnoverRate: 0.42,
          change5d: 5.8,
          change10d: 8.2,
          change20d: 12.5,
          ma5: 1830.50,
          ma10: 1810.20,
          ma20: 1780.80,
          ma60: 1750.30,
          macd: 0.025,
          kdj: { k: 65.5, d: 58.2, j: 78.3 },
          rsi: 62.5,
          pe: 35.2,
          peTTM: 33.8,
          pb: 12.5,
          ps: 18.2,
          roe: 28.5,
          eps: 52.50,
          navps: 148.00,
          totalMarketCap: 2320000000000,
          floatMarketCap: 2300000000000,
          totalShare: 1256000000,
          floatShare: 1245000000,
          mainNetInflow: 520000000,
          superLargeInflow: 380000000,
          largeInflow: 140000000,
          mediumInflow: -80000000,
          smallInflow: -60000000,
          mainNetRatio: 54.0,
          marginBalance: 1250000000,
          shortBalance: 350000000,
          marginBuy: 85000000,
          shortSell: 42000000,
          northboundHolding: 8500000,
          northboundHoldingRatio: 0.68,
          northboundChange: 0.12,
          isOnDragonTigerList: false,
          limitCount: null,
          firstLimitTime: null,
          lastLimitTime: null,
          limitOpenCount: null,
          updateTime: '--'
        },
        {
          symbol: '000001.SZ',
          name: '平安银行',
          price: 12.45,
          change: -0.16,
          changePercent: -1.27,
          volume: 1280000,
          amount: 159360000,
          high: 12.65,
          low: 12.38,
          open: 12.60,
          preClose: 12.61,
          limitUp: 13.87,
          limitDown: 11.35,
          avgPrice: 12.45,
          amplitude: 2.14,
          volumeRatio: 0.85,
          turnoverRate: 1.25,
          change5d: -2.5,
          change10d: -4.8,
          change20d: 3.2,
          ma5: 12.52,
          ma10: 12.65,
          ma20: 12.38,
          ma60: 12.10,
          macd: -0.012,
          kdj: { k: 42.5, d: 48.2, j: 31.8 },
          rsi: 45.2,
          pe: 8.5,
          peTTM: 8.2,
          pb: 0.8,
          ps: 1.8,
          roe: 9.5,
          eps: 1.32,
          navps: 15.56,
          totalMarketCap: 240000000000,
          floatMarketCap: 235000000000,
          totalShare: 19400000000,
          floatShare: 18900000000,
          mainNetInflow: -120000000,
          superLargeInflow: -60000000,
          largeInflow: -60000000,
          mediumInflow: 45000000,
          smallInflow: 75000000,
          mainNetRatio: -38.5,
          marginBalance: 850000000,
          shortBalance: 120000000,
          marginBuy: 45000000,
          shortSell: 32000000,
          northboundHolding: 32000000,
          northboundHoldingRatio: 1.70,
          northboundChange: -0.08,
          isOnDragonTigerList: false,
          limitCount: null,
          firstLimitTime: null,
          lastLimitTime: null,
          limitOpenCount: null,
          updateTime: '--'
        },
        {
          symbol: '000002.SZ',
          name: '万科A',
          price: 22.30,
          change: 0.85,
          changePercent: 3.96,
          volume: 950000,
          amount: 211850000,
          high: 22.50,
          low: 21.45,
          open: 21.45,
          preClose: 21.45,
          limitUp: 23.60,
          limitDown: 19.30,
          avgPrice: 22.30,
          amplitude: 4.89,
          volumeRatio: 1.85,
          turnoverRate: 1.85,
          change5d: 8.5,
          change10d: 12.5,
          change20d: 25.8,
          ma5: 21.20,
          ma10: 20.50,
          ma20: 18.80,
          ma60: 17.50,
          macd: 0.035,
          kdj: { k: 75.5, d: 62.3, j: 92.8 },
          rsi: 68.5,
          pe: 10.2,
          peTTM: 9.8,
          pb: 1.5,
          ps: 2.2,
          roe: 15.2,
          eps: 2.20,
          navps: 14.85,
          totalMarketCap: 258000000000,
          floatMarketCap: 242000000000,
          totalShare: 11600000000,
          floatShare: 10850000000,
          mainNetInflow: 280000000,
          superLargeInflow: 180000000,
          largeInflow: 100000000,
          mediumInflow: -45000000,
          smallInflow: -35000000,
          mainNetRatio: 62.5,
          marginBalance: 1250000000,
          shortBalance: 280000000,
          marginBuy: 120000000,
          shortSell: 45000000,
          northboundHolding: 150000000,
          northboundHoldingRatio: 1.38,
          northboundChange: 0.25,
          isOnDragonTigerList: true,
          limitCount: 2,
          firstLimitTime: '09:35',
          lastLimitTime: '10:12',
          limitOpenCount: 1,
          updateTime: '--'
        }
      ]
    }
  },

  computed: {
    visibleColumns() {
      const cols = this.allColumns.filter(c => c.visible).sort((a, b) => a.order - b.order)
      return cols.map(c => ({
        title: c.name,
        dataIndex: c.id,
        key: c.id,
        width: c.width,
        fixed: c.fixed || undefined,
        scopedSlots: c.id === 'actions' ? { customRender: 'actions' } :
                    c.id !== 'name' ? { customRender: c.id } : undefined
      }))
    },
    visibleColumnsForModal() {
      return this.allColumns.filter(c => c.visible).sort((a, b) => a.order - b.order)
    },
    hiddenColumns() {
      return this.allColumns.filter(c => !c.visible).sort((a, b) => a.order - b.order)
    },
    groupedHiddenColumns() {
      const groups = {}
      this.hiddenColumns.forEach(col => {
        if (!groups[col.category]) {
          groups[col.category] = []
        }
        groups[col.category].push(col)
      })
      return groups
    },
    filteredData() {
      const q = this.searchQuery.toLowerCase()
      if (!q) return this.watchlist
      return this.watchlist.filter(s => 
        s.name?.toLowerCase().includes(q) || 
        s.symbol?.toLowerCase().includes(q)
      )
    },
    stats() {
      let upCount = 0, downCount = 0, flatCount = 0
      this.watchlist.forEach(s => {
        if (s.changePercent > 0) upCount++
        else if (s.changePercent < 0) downCount++
        else flatCount++
      })
      const ratio = downCount > 0 ? (upCount / downCount).toFixed(2) : (upCount > 0 ? '∞' : '-')
      return { upCount, downCount, flatCount, ratio }
    }
  },


  watch: {
    watchlist: {
      handler() { this.syncWatchlistToStorage() },
      deep: true
    }
  },

  mounted() {
    this.loadWatchlistFromStorage()
    this.initSocket()
  },

  beforeDestroy() {
    this.destroySocket()
  },

  methods: {
    initSocket() {
      try {
        socketService.connect()
        socketService.on('connected', () => {
          this.socketConnected = true
          this.$message.success('实时数据服务已连接')
        })
        socketService.on('disconnect', () => {
          this.socketConnected = false
          this.$message.warning('实时数据服务已断开')
        })
        socketService.on('watchlist_update', this.handleRealtimeUpdate)
        socketService.subscribeWatchlist(this.watchlist.map(s => s.symbol))
      } catch (e) {
        console.warn('SocketIO初始化失败:', e)
      }
    },

    destroySocket() {
      try {
        socketService.off('watchlist_update', this.handleRealtimeUpdate)
      } catch (e) {
        // ignore
      }
    },

    toggleSocketConnection() {
      if (this.socketConnected) {
        this.destroySocket()
        socketService.disconnect()
      } else {
        this.initSocket()
      }
    },

    handleRealtimeUpdate(message) {
      console.log('📡 收到实时数据更新:', message)
      if (!message?.data || !Array.isArray(message.data)) return

      const now = new Date().toLocaleTimeString()
      this.lastUpdateTime = now

      message.data.forEach(stockData => {
        const symbol = stockData.ts_code
        const idx = this.watchlist.findIndex(s => s.symbol === symbol)
        
        // 基础数据
        const baseData = {
          price: stockData.price,
          change: stockData.change,
          changePercent: stockData.change_pct,
          volume: stockData.volume,
          amount: stockData.amount,
          high: stockData.high,
          low: stockData.low,
          open: stockData.open,
          preClose: stockData.pre_close
        }

        // 计算可推导的数据
        const calculatedData = this.calculateDerivedData(baseData)
        
        // 构建完整的数据更新对象
        const updateData = {
          ...baseData,
          ...calculatedData,
          
          // 涨跌停（如果后端提供）
          limitUp: stockData.limit_up,
          limitDown: stockData.limit_down,
          
          // 技术指标（依赖后端）
          ma5: stockData.ma5,
          ma10: stockData.ma10,
          ma20: stockData.ma20,
          ma60: stockData.ma60,
          macd: stockData.macd,
          kdj: stockData.kdj,
          rsi: stockData.rsi,
          
          // 基本面（依赖后端）
          pe: stockData.pe,
          peTTM: stockData.pe_ttm,
          pb: stockData.pb,
          ps: stockData.ps,
          roe: stockData.roe,
          eps: stockData.eps,
          navps: stockData.navps,
          
          // 市值股本（依赖后端）
          totalMarketCap: stockData.total_market_cap,
          floatMarketCap: stockData.float_market_cap,
          totalShare: stockData.total_share,
          floatShare: stockData.float_share,
          
          // 资金流向（依赖后端）
          mainNetInflow: stockData.main_net_inflow,
          superLargeInflow: stockData.super_large_inflow,
          largeInflow: stockData.large_inflow,
          mediumInflow: stockData.medium_inflow,
          smallInflow: stockData.small_inflow,
          mainNetRatio: stockData.main_net_ratio,
          
          // 融资融券（依赖后端）
          marginBalance: stockData.margin_balance,
          shortBalance: stockData.short_balance,
          marginBuy: stockData.margin_buy,
          shortSell: stockData.short_sell,
          
          // 北向资金（依赖后端）
          northboundHolding: stockData.northbound_holding,
          northboundHoldingRatio: stockData.northbound_holding_ratio,
          northboundChange: stockData.northbound_change,
          
          // 异动数据（依赖后端）
          isOnDragonTigerList: stockData.is_on_dragon_tiger_list,
          limitCount: stockData.limit_count,
          firstLimitTime: stockData.first_limit_time,
          lastLimitTime: stockData.last_limit_time,
          limitOpenCount: stockData.limit_open_count,
          
          updateTime: now
        }

        if (idx !== -1) {
          this.$set(this.watchlist, idx, {
            ...this.watchlist[idx],
            ...updateData
          })
        } else {
          this.watchlist.push({
            symbol: symbol,
            name: stockData.name || symbol,
            ...updateData
          })
        }
      })
    },

    calculateDerivedData(baseData) {
      const data = {}
      
      // 计算均价（金额/成交量）
      if (baseData.amount && baseData.volume && baseData.volume > 0) {
        data.avgPrice = (baseData.amount / baseData.volume).toFixed(2) * 1
      }
      
      // 计算振幅
      if (baseData.high && baseData.low && baseData.preClose && baseData.preClose > 0) {
        data.amplitude = (((baseData.high - baseData.low) / baseData.preClose) * 100).toFixed(2) * 1
      }
      
      // 计算涨停跌停价（基于昨收价）
      if (baseData.preClose) {
        // A股普通股票涨跌停10%，ST股5%，这里简化处理为10%
        data.limitUp = data.limitUp || (baseData.preClose * 1.1).toFixed(2) * 1
        data.limitDown = data.limitDown || (baseData.preClose * 0.9).toFixed(2) * 1
      }
      
      return data
    },

    refreshData() {
      this.loading = true
      setTimeout(() => {
        this.loading = false
      }, 500)
    },

    onSearch() {
      // filter handled by computed
    },

    toggleColumn(col, visible) {
      const target = this.allColumns.find(c => c.id === col.id)
      if (target) target.visible = visible
    },

    saveColumnConfig() {
      this.showColumnConfig = false
    },

    cancelColumnConfig() {
      this.showColumnConfig = false
    },

    resetColumns() {
      this.allColumns.forEach(c => {
        c.visible = ['name', 'price', 'change', 'changePercent', 'volume', 'amount', 'high', 'low', 'updateTime', 'actions'].includes(c.id)
      })
    },

    openFactorManager() {
      this.$router.push({ name: 'FactorManager' })
    },

    runStrategyScreen() {
      this.$router.push({ name: 'FactorManager', query: { tab: 'screen' } })
    },

    goToBacktest() {
      this.$router.push({ name: 'Backtest' })
    },



    loadWatchlistFromStorage() {
      try {
        const raw = localStorage.getItem('user_watchlist')
        if (raw && this.watchlist.length === 0) {
          const list = JSON.parse(raw)
          this.watchlist = list.map(s => ({ ...s, symbol: s.symbol }))
        }
      } catch (e) { /* ignore */ }
    },

    syncWatchlistToStorage() {
      try {
        const list = this.watchlist.map(s => ({ symbol: s.symbol, name: s.name }))
        localStorage.setItem('user_watchlist', JSON.stringify(list))
      } catch (e) { /* ignore */ }
    },

    goToChart(record) {
      this.$router.push({ name: 'IndicatorIDE', query: { symbol: record.symbol } })
    },

    removeFromWatchlist(record) {
      const idx = this.watchlist.findIndex(s => s.symbol === record.symbol)
      if (idx !== -1) {
        this.watchlist.splice(idx, 1)
      }
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
    }
  }
}
</script>

<style scoped>
.watchlist-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary, #0a1628);
  color: var(--text-primary, #f1f5f9);
}

.page-header {
  padding: 16px 24px;
  background: var(--bg-secondary, #141414);
  border-bottom: 1px solid #333;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  align-items: center;
}

.watchlist-table-container {
  flex: 1;
  padding: 16px 24px;
  overflow: hidden;
}

.watchlist-table-container >>> .ant-table {
  background: var(--bg-surface, #1e293b);
}

.stock-name-cell {
  display: flex;
  flex-direction: column;
}

.stock-symbol {
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  font-size: 12px;
}

.stock-name {
  color: var(--text-primary, #f1f5f9);
}

.text-up {
  color: var(--color-up, #ef4444);
  font-weight: 600;
}

.text-down {
  color: var(--color-down, #22c55e);
  font-weight: 600;
}

.text-flat {
  color: var(--text-secondary, #94a3b8);
}

.update-time {
  color: var(--text-muted, #64748b);
  font-size: 12px;
}

.page-footer {
  padding: 12px 24px;
  background: var(--bg-secondary, #141414);
  border-top: 1px solid #333;
}

.stats {
  display: flex;
  gap: 24px;
  align-items: center;
}

.connection-status {
  padding: 4px 12px;
  border-radius: 4px;
  background: #333;
  &.connected {
    background: rgba(34, 197, 94, 0.15);
  }
}

.highlight {
  font-weight: 600;
  color: var(--color-primary, #3b82f6);
}

.up {
  color: var(--color-up, #ef4444);
}

.down {
  color: var(--color-down, #22c55e);
}

.column-config {
  padding: 16px 0;
}

.config-section {
  margin-bottom: 24px;
}

.section-title {
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-primary, #f1f5f9);
  font-size: 14px;
}

.column-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>

<!-- 全局样式 - 用于修复弹窗中的标签显示问题 -->
<style>
.column-config-modal .ant-modal-body {
  background: #1e293b;
}

.column-config-modal .section-title {
  color: #f1f5f9 !important;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
}

/* 自定义标签样式 - 全局样式 */
.column-config-modal .custom-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 14px;
  margin: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.column-config-modal .custom-tag-visible {
  background: #1890ff !important;
  color: #ffffff !important;
  cursor: default;
}

.column-config-modal .custom-tag-hidden {
  background: #f0f0f0 !important;
  color: #333333 !important;
}

.column-config-modal .custom-tag-hidden:hover {
  background: #e0e0e0 !important;
}

.column-config-modal .tag-text,
.column-config-modal .tag-text * {
  color: inherit !important;
  font-weight: 500 !important;
}

.column-config-modal .custom-tag-visible .tag-text,
.column-config-modal .custom-tag-visible .tag-text * {
  color: #ffffff !important;
}

.column-config-modal .custom-tag-hidden .tag-text,
.column-config-modal .custom-tag-hidden .tag-text * {
  color: #333333 !important;
}

.column-config-modal .tag-close,
.column-config-modal .tag-close * {
  margin-left: 8px;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  opacity: 0.8;
  transition: opacity 0.2s;
  color: #ffffff !important;
}

.column-config-modal .tag-close:hover {
  opacity: 1;
}

.column-config-modal .tag-plus,
.column-config-modal .tag-plus * {
  margin-right: 4px;
  font-weight: bold;
  color: #333333 !important;
}
</style>
