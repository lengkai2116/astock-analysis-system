<template>
  <div class="account-page theme-dark">
    <!-- 总览指标卡 -->
    <div class="summary-cards">
      <div class="summary-card">
        <div class="card-label">总资产</div>
        <div class="card-value">¥{{ formatMoney(summary.total_asset) }}</div>
        <div class="card-sub">初始本金 ¥{{ formatMoney(summary.initial_capital) }}</div>
      </div>
      <div class="summary-card">
        <div class="card-label">总盈亏</div>
        <div class="card-value" :class="summary.total_profit >= 0 ? 'profit' : 'loss'">
          {{ summary.total_profit >= 0 ? '+' : '' }}¥{{ formatMoney(summary.total_profit) }}
        </div>
        <div class="card-sub">{{ (summary.total_return_pct * 100).toFixed(2) }}%</div>
      </div>
      <div class="summary-card">
        <div class="card-label">总交易次数</div>
        <div class="card-value">{{ summary.total_trades }}</div>
        <div class="card-sub">买入 {{ summary.buy_count }} / 卖出 {{ summary.sell_count }}</div>
      </div>
      <div class="summary-card">
        <div class="card-label">胜率</div>
        <div class="card-value">{{ (summary.win_rate * 100).toFixed(1) }}%</div>
        <div class="card-sub">当前持仓 {{ summary.positions_count }} 只</div>
      </div>
    </div>

    <!-- 主 Tab 区域 -->
    <a-card class="main-card" :bordered="false">
      <a-tabs v-model:activeKey="activeTab" :tabBarStyle="{ marginBottom: '16px' }">
        <a-tab-pane key="trades" tab="交易记录">
          <TradeTab />
        </a-tab-pane>
        <a-tab-pane key="positions" tab="持仓概览">
          <PositionTab />
        </a-tab-pane>
        <a-tab-pane key="equity" tab="资金曲线">
          <EquityTab />
        </a-tab-pane>
        <a-tab-pane key="review" tab="智能复盘">
          <ReviewTab />
        </a-tab-pane>
      </a-tabs>
    </a-card>
  </div>
</template>

<script>
import { ref, reactive, onMounted } from 'vue'
import { getAccountSummary } from '@/services/accountService'
import TradeTab from './components/TradeTab.vue'
import PositionTab from './components/PositionTab.vue'
import EquityTab from './components/EquityTab.vue'
import ReviewTab from './components/ReviewTab.vue'

export default {
  name: 'AccountManage',
  components: { TradeTab, PositionTab, EquityTab, ReviewTab },
  setup() {
    const activeTab = ref('trades')
    const summary = reactive({
      total_asset: 0, cash_balance: 0, position_value: 0,
      total_profit: 0, total_return_pct: 0, initial_capital: 0,
      total_trades: 0, buy_count: 0, sell_count: 0,
      positions_count: 0, win_rate: 0,
    })

    async function loadSummary() {
      try {
        const res = await getAccountSummary()
        if (res.success && res.data) {
          Object.assign(summary, res.data)
        }
      } catch (e) {
        console.warn('加载账户概览失败:', e)
      }
    }

    function formatMoney(val) {
      if (val == null) return '0.00'
      return Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }

    onMounted(loadSummary)

    return { activeTab, summary, formatMoney }
  }
}
</script>

<style scoped>
.account-page {
  padding: 20px;
  background: #141414;
  min-height: calc(100vh - 0px);
}

.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.summary-card {
  background: #1e293b;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 20px;
}

.card-label {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 8px;
}

.card-value {
  font-size: 24px;
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 4px;
}

.card-value.profit { color: #52c41a; }
.card-value.loss { color: #ff4d4f; }

.card-sub {
  font-size: 12px;
  color: #64748b;
}

.main-card {
  background: #1e293b !important;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
}

.main-card :deep(.ant-card-body) {
  padding: 16px 24px 24px;
}

.main-card :deep(.ant-tabs-tab) {
  color: #94a3b8;
  font-size: 14px;
  padding: 8px 16px;
}

.main-card :deep(.ant-tabs-tab-active) {
  color: #3b82f6;
}

.main-card :deep(.ant-tabs-ink-bar) {
  background: #3b82f6;
}

@media (max-width: 1024px) {
  .summary-cards { grid-template-columns: repeat(2, 1fr); }
}
</style>
