<template>
  <div class="review-report">
    <!-- 总评分 -->
    <div class="score-section">
      <div class="score-ring">
        <div class="score-value">
          {{ result.total_score }}
        </div>
        <div class="score-label">
          综合评分
        </div>
      </div>
      <div class="dimension-bars">
        <div
          v-for="d in dimensionList"
          :key="d.key"
          class="dim-row"
        >
          <span class="dim-label">{{ d.label }}</span>
          <div class="dim-bar-bg">
            <div
              class="dim-bar-fill"
              :style="{ width: d.score + '%', background: d.color }"
            />
          </div>
          <span class="dim-score">{{ d.score }}</span>
        </div>
      </div>
    </div>

    <!-- 各维度详情 -->
    <div class="detail-sections">
      <div
        v-for="d in dimensionList"
        :key="d.key"
        class="detail-card"
      >
        <div
          class="detail-header"
          @click="d.expanded = !d.expanded"
        >
          <span class="detail-title">{{ d.label }}</span>
          <span
            class="detail-score"
            :style="{ color: d.color }"
          >{{ d.score }}/100</span>
          <span class="expand-icon">{{ d.expanded ? '▼' : '▶' }}</span>
        </div>
        <div
          v-if="d.expanded"
          class="detail-body"
        >
          <div
            v-for="(detail, i) in d.details"
            :key="i"
            class="detail-item"
          >
            {{ detail }}
          </div>
          <div
            v-if="!d.details?.length"
            class="no-detail"
          >
            暂无详情
          </div>
        </div>
      </div>
    </div>

    <!-- 归因分析 -->
    <div
      v-if="result.attribution"
      class="attribution-section"
    >
      <div class="section-title">
        盈亏归因分析
      </div>
      <div class="attribution-grid">
        <div class="attr-col">
          <div class="attr-header winner">
            ✅ 盈利股票
          </div>
          <div
            v-for="w in result.attribution.winners"
            :key="w.ts_code"
            class="attr-item winner-item"
          >
            <span>{{ w.name || w.ts_code }}</span>
            <span class="attr-pnl">+{{ formatMoney(w.pnl) }}</span>
          </div>
        </div>
        <div class="attr-col">
          <div class="attr-header loser">
            ❌ 亏损股票
          </div>
          <div
            v-for="l in result.attribution.losers"
            :key="l.ts_code"
            class="attr-item loser-item"
          >
            <span>{{ l.name || l.ts_code }}</span>
            <span class="attr-pnl">{{ formatMoney(l.pnl) }}</span>
          </div>
        </div>
      </div>
      <div class="attr-summary">
        {{ result.attribution.summary }}
      </div>
    </div>

    <!-- 改进建议 -->
    <div
      v-if="result.improvements?.length"
      class="improvements-section"
    >
      <div class="section-title">
        改进建议
      </div>
      <div
        v-for="(imp, i) in result.improvements"
        :key="i"
        class="imp-item"
      >
        <span
          class="imp-priority"
          :class="imp.priority"
        >
          {{ { HIGH: '🔴', MEDIUM: '🟡', LOW: '🟢', INFO: 'ℹ' }[imp.priority] || '•' }}
        </span>
        <span class="imp-category">[{{ imp.category }}]</span>
        <span class="imp-text">{{ imp.suggestion }}</span>
      </div>
    </div>
  </div>
</template>

<script>
import { computed, ref } from 'vue'

const LABELS = {
  market: '① 大盘环境', sector: '② 板块题材',
  trade: '③ 个股操作', strategy: '④ 策略执行',
  capital: '⑤ 资金管理', psychology: '⑥ 心态纪律',
}
const COLORS = {
  market: '#3b82f6', sector: '#8b5cf6',
  trade: '#f59e0b', strategy: '#52c41a',
  capital: '#06b6d4', psychology: '#ec4899',
}

export default {
  name: 'ReviewReport',
  props: {
    result: { type: Object, required: true }
  },
  setup(props) {
    const dimensionList = computed(() => {
      const dims = props.result.dimensions || {}
      return Object.entries(LABELS).map(([key, label]) => {
        const d = dims[key] || {}
        const score = d.score || 0
        return { key, label, score, color: COLORS[key] || '#64748b', details: d.details || [], expanded: ref(true) }
      })
    })

    function formatMoney(v) {
      if (v == null) return '¥0'
      const n = Number(v)
      return (n >= 0 ? '+' : '') + '¥' + Math.abs(n).toLocaleString('zh-CN', { minimumFractionDigits: 2 })
    }

    return { dimensionList, formatMoney }
  }
}
</script>

<style scoped>
.review-report { color: #e2e8f0; }
.score-section { display: flex; gap: 24px; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #2a2a2a; }
.score-ring { width: 100px; height: 100px; border-radius: 50%; background: conic-gradient(#3b82f6 0deg, #52c41a 120deg, #f59e0b 240deg, #ff4d4f 360deg); display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; }
.score-value { font-size: 28px; font-weight: 800; color: #f1f5f9; background: #1e293b; width: 88px; height: 88px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.score-label { display: none; }
.dimension-bars { flex: 1; display: flex; flex-direction: column; gap: 8px; justify-content: center; }
.dim-row { display: flex; align-items: center; gap: 8px; }
.dim-label { width: 80px; font-size: 12px; color: #94a3b8; flex-shrink: 0; }
.dim-bar-bg { flex: 1; height: 8px; background: #334155; border-radius: 4px; overflow: hidden; }
.dim-bar-fill { height: 100%; border-radius: 4px; transition: width 0.6s; }
.dim-score { width: 30px; text-align: right; font-size: 12px; font-weight: 600; color: #f1f5f9; }

.detail-sections { display: flex; flex-direction: column; gap: 8px; margin-bottom: 24px; }
.detail-card { border: 1px solid #2a2a2a; border-radius: 8px; overflow: hidden; }
.detail-header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: rgba(255,255,255,0.03); cursor: pointer; }
.detail-title { flex: 1; font-weight: 600; font-size: 14px; }
.detail-score { font-weight: 700; font-size: 14px; }
.expand-icon { color: #64748b; font-size: 10px; }
.detail-body { padding: 12px 16px; }
.detail-item { font-size: 13px; padding: 4px 0; color: #cbd5e1; line-height: 1.6; }
.no-detail { color: #64748b; font-size: 13px; }

.attribution-section { margin-bottom: 24px; }
.section-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; }
.attribution-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 8px; }
.attr-header { font-weight: 600; font-size: 14px; padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; }
.attr-header.winner { background: rgba(82,196,26,0.1); color: #52c41a; }
.attr-header.loser { background: rgba(255,77,79,0.1); color: #ff4d4f; }
.attr-item { display: flex; justify-content: space-between; padding: 6px 12px; font-size: 13px; }
.attr-pnl { font-weight: 600; }
.winner-item .attr-pnl { color: #52c41a; }
.loser-item .attr-pnl { color: #ff4d4f; }
.attr-summary { padding: 8px; font-size: 13px; color: #94a3b8; }

.improvements-section { border-top: 1px solid #2a2a2a; padding-top: 16px; }
.imp-item { display: flex; gap: 8px; padding: 8px 0; font-size: 13px; line-height: 1.6; }
.imp-category { color: #3b82f6; flex-shrink: 0; }
.imp-text { color: #cbd5e1; }
</style>
