<template>
  <div class="trade-tab">
    <div class="toolbar">
      <a-input-search
        v-model:value="searchCode"
        placeholder="股票代码"
        style="width:160px"
        @search="loadTrades"
      />
      <a-range-picker
        v-model:value="dateRange"
        @change="loadTrades"
      />
      <a-select
        v-model:value="dirFilter"
        style="width:130px"
        placeholder="信号类型"
        allow-clear
        @change="loadTrades"
      >
        <a-select-option value="买入">
          关注信号
        </a-select-option>
        <a-select-option value="卖出">
          风险退出信号
        </a-select-option>
      </a-select>
      <a-button
        type="primary"
        @click="showAddModal = true"
      >
        + 新建记录
      </a-button>
      <a-button @click="showImportModal = true">
        批量导入
      </a-button>
      <a-button @click="handleMatch">
        匹配信号
      </a-button>
    </div>
    <a-table
      :columns="columns"
      :data-source="trades"
      :pagination="{ pageSize: 20 }"
      size="small"
      row-key="id"
      :loading="loading"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'direction'">
          <a-tag :color="record.direction === '买入' ? '#EF4444' : '#22C55E'">
            {{ record.direction === '买入' ? '关注信号' : '风险退出信号' }}
          </a-tag>
        </template>
        <template v-if="column.key === 'signal_match'">
          <span
            v-if="record.signal_match"
            :style="{ color: '#52c41a' }"
          >✅ {{ record.signal_match.signal_type }}</span>
          <span
            v-else
            style="color:#64748b"
          >—</span>
        </template>
        <template v-if="column.key === 'actions'">
          <a-space>
            <a @click="handleEdit(record)">编辑</a>
            <a-popconfirm
              title="确认删除?"
              @confirm="handleDelete(record.id)"
            >
              <a style="color:#ff4d4f">删除</a>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <!-- 新建记录弹窗 -->
    <a-modal
      v-model:visible="showAddModal"
      title="新建记录"
      :footer="null"
      width="500"
      @ok="handleCreate"
    >
      <a-form
        :model="form"
        layout="vertical"
      >
        <a-form-item
          label="股票代码"
          required
        >
          <a-input v-model:value="form.ts_code" />
        </a-form-item>
        <a-form-item label="股票名称">
          <a-input v-model:value="form.stock_name" />
        </a-form-item>
        <a-form-item
          label="信号类型"
          required
        >
          <a-radio-group v-model:value="form.direction">
            <a-radio value="买入">
              关注信号
            </a-radio>
            <a-radio value="卖出">
              风险退出信号
            </a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item
          label="日期"
          required
        >
          <a-date-picker
            v-model:value="form.trade_date"
            style="width:100%"
          />
        </a-form-item>
        <a-form-item
          label="价格"
          required
        >
          <a-input-number
            v-model:value="form.price"
            :min="0"
            :precision="2"
            style="width:100%"
          />
        </a-form-item>
        <a-form-item
          label="数量"
          required
        >
          <a-input-number
            v-model:value="form.quantity"
            :min="1"
            style="width:100%"
          />
        </a-form-item>
        <a-form-item label="备注">
          <a-textarea
            v-model:value="form.notes"
            rows="2"
          />
        </a-form-item>
        <a-button
          type="primary"
          block
          @click="handleCreate"
        >
          提交
        </a-button>
      </a-form>
    </a-modal>
  </div>
</template>

<script>
import { ref, reactive, onMounted } from 'vue'
import { getTrades, createTrade, deleteTrade, matchTrades } from '@/services/accountService'
function fmtDate(d) { if (!d) return ''; const dt = d instanceof Date ? d : new Date(d); return dt.toISOString().slice(0, 10); }

export default {
  name: 'TradeTab',
  setup() {
    const trades = ref([])
    const loading = ref(false)
    const searchCode = ref('')
    const dateRange = ref([])
    const dirFilter = ref(undefined)
    const showAddModal = ref(false)
    const form = reactive({ ts_code: '', stock_name: '', direction: '买入', trade_date: null, price: null, quantity: null, notes: '' })

    const columns = [
      { title: '日期', dataIndex: 'trade_date', key: 'date', width: 100 },
      { title: '股票', key: 'stock', width: 140, render: (_, r) => `${r.stock_name || ''} ${r.ts_code}` },
      { title: '信号类型', key: 'direction', width: 80 },
      { title: '价格', dataIndex: 'price', key: 'price', width: 80 },
      { title: '数量', dataIndex: 'quantity', key: 'qty', width: 60 },
      { title: '金额', dataIndex: 'amount', key: 'amount', width: 100 },
      { title: '信号匹配', key: 'signal_match', width: 120 },
      { title: '操作', key: 'actions', width: 100 },
    ]

    async function loadTrades() {
      loading.value = true
      try {
        const params = {}
        if (searchCode.value) params.ts_code = searchCode.value
        if (dateRange.value?.[0]) params.start_date = fmtDate(dateRange.value[0])
        if (dateRange.value?.[1]) params.end_date = fmtDate(dateRange.value[1])
        if (dirFilter.value) params.direction = dirFilter.value
        const res = await getTrades(params)
        if (res.success) trades.value = res.data || []
      } finally { loading.value = false }
    }

    async function handleCreate() {
      try {
        await createTrade({ ...form, trade_date: fmtDate(form.trade_date) })
        showAddModal.value = false
        Object.assign(form, { ts_code: '', stock_name: '', direction: '买入', trade_date: null, price: null, quantity: null, notes: '' })
        await loadTrades()
      } catch (e) { console.warn('创建失败:', e) }
    }

    async function handleDelete(id) {
      try { await deleteTrade(id); await loadTrades() }
      catch (e) { console.warn('删除失败:', e) }
    }

    function handleEdit(rec) {
      Object.assign(form, rec)
      form.trade_date = new Date(rec.trade_date)
      showAddModal.value = true
    }

    async function handleMatch() {
      try {
        const res = await matchTrades()
        await loadTrades()
      } catch (e) { console.warn('匹配失败:', e) }
    }

    onMounted(loadTrades)

    return { trades, loading, searchCode, dateRange, dirFilter, showAddModal, form, columns, loadTrades, handleCreate, handleDelete, handleEdit, handleMatch }
  }
}
</script>

<style scoped>
.trade-tab {}
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
</style>
