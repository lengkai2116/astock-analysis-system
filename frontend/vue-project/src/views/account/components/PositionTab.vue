<template>
  <div class="position-tab">
    <a-table
      :columns="columns"
      :data-source="positions"
      size="small"
      row-key="ts_code"
      :loading="loading"
      :pagination="false"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'current_price'">
          <span>{{ record.current_price ? '¥' + formatMoney(record.current_price) : '—' }}</span>
        </template>
        <template v-if="column.key === 'market_value'">
          <span>¥{{ formatMoney(record.market_value) }}</span>
        </template>
        <template v-if="column.key === 'unrealized_pnl'">
          <span :style="{ color: record.unrealized_pnl >= 0 ? '#EF4444' : '#22C55E', fontWeight: 600 }">
            {{ record.unrealized_pnl >= 0 ? '+' : '' }}¥{{ formatMoney(record.unrealized_pnl) }}
          </span>
        </template>
        <template v-if="column.key === 'realized_pnl'">
          <span :style="{ color: record.realized_pnl >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 600 }">
            {{ record.realized_pnl >= 0 ? '+' : '' }}¥{{ formatMoney(record.realized_pnl) }}
          </span>
        </template>
      </template>
    </a-table>
    <div
      v-if="positions.length === 0 && !loading"
      class="empty-hint"
    >
      暂无持仓，录入交易记录后自动计算
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { getPositions } from '@/services/accountService'

export default {
  name: 'PositionTab',
  setup() {
    const positions = ref([])
    const loading = ref(false)
    const columns = [
      { title: '股票', key: 'stock', render: (_, r) => `${r.stock_name} (${r.ts_code})` },
      { title: '持仓', dataIndex: 'hold_qty', key: 'qty', width: 80 },
      { title: '均价', dataIndex: 'avg_cost', key: 'avg', width: 100 },
      { title: '成本', dataIndex: 'total_cost', key: 'cost', width: 120 },
      { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 100 },
      { title: '市值', dataIndex: 'market_value', key: 'market_value', width: 120 },
      { title: '浮动盈亏', key: 'unrealized_pnl', width: 120 },
      { title: '已实现盈亏', key: 'realized_pnl', width: 120 },
    ]

    async function load() {
      loading.value = true
      try {
        const res = await getPositions()
        if (res.success) positions.value = res.data || []
      } finally { loading.value = false }
    }
    function formatMoney(v) { return Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }

    onMounted(load)
    return { positions, loading, columns, formatMoney }
  }
}
</script>

<style scoped>
.empty-hint { text-align: center; padding: 60px 0; color: #64748b; }
</style>
