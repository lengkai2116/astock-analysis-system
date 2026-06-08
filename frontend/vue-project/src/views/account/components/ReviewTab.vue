<template>
  <div class="review-tab">
    <div class="review-toolbar">
      <a-range-picker
        v-model:value="reviewDateRange"
        style="width:260px"
      />
      <a-button
        type="primary"
        :loading="reviewLoading"
        @click="handleRunReview"
      >
        ▶ 开始复盘
      </a-button>
      <a-button
        v-if="reviewResult"
        @click="handleExport"
      >
        导出报告
      </a-button>
    </div>

    <div
      v-if="reviewLoading"
      style="text-align:center;padding:60px"
    >
      <a-spin
        size="large"
        tip="正在生成复盘报告..."
      />
    </div>

    <div
      v-else-if="reviewResult"
      class="review-content"
    >
      <ReviewReport :result="reviewResult" />
    </div>

    <div
      v-else
      class="empty-hint"
    >
      选择复盘周期，点击「开始复盘」
    </div>
  </div>
</template>

<script>
import { ref } from 'vue'
// dayjs替代: 使用原生Date
function fmtDate(d) { if (!d) return ''; const dt = d instanceof Date ? d : new Date(d); return dt.toISOString().slice(0, 10); }
import { runReview, exportReview } from '@/services/accountService'
import ReviewReport from '@/components/ReviewReport.vue'

export default {
  name: 'ReviewTab',
  components: { ReviewReport },
  setup() {
    const d30 = new Date(); d30.setDate(d30.getDate() - 30); const reviewDateRange = ref([d30, new Date()])
    const reviewLoading = ref(false)
    const reviewResult = ref(null)

    async function handleRunReview() {
      if (!reviewDateRange.value?.[0] || !reviewDateRange.value?.[1]) return
      reviewLoading.value = true
      try {
        const start = fmtDate(reviewDateRange.value[0])
        const end = fmtDate(reviewDateRange.value[1])
        const res = await runReview(start, end, 'json')
        if (res.success) reviewResult.value = res.data
      } finally { reviewLoading.value = false }
    }

    async function handleExport() {
      if (!reviewDateRange.value?.[0] || !reviewDateRange.value?.[1]) return
      try {
        const start = fmtDate(reviewDateRange.value[0])
        const end = fmtDate(reviewDateRange.value[1])
        const res = await exportReview(start, end)
        if (res.success) window.open(res.data?.filepath, '_blank')
      } catch (e) { console.warn('导出失败:', e) }
    }

    return { reviewDateRange, reviewLoading, reviewResult, handleRunReview, handleExport }
  }
}
</script>

<style scoped>
.review-toolbar { display: flex; gap: 12px; margin-bottom: 20px; }
.review-content { background: rgba(255,255,255,0.02); border: 1px solid #2a2a2a; border-radius: 8px; padding: 20px; }
.empty-hint { text-align: center; padding: 60px 0; color: #64748b; }
</style>
