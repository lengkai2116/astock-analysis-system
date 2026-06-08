<template>
  <div class="screening-results theme-dark">
    <div class="results-header">
      <span class="results-title">选股结果</span>
      <div class="results-toolbar">
        <span
          v-if="results.length > 0"
          class="results-count"
        >共 {{ results.length }} 只</span>
        <a-button
          size="small"
          :disabled="results.length === 0"
          @click="$emit('export')"
        >
          导出 CSV
        </a-button>
      </div>
    </div>

    <div class="results-body">
      <a-spin
        :spinning="loading"
        size="large"
      >
        <div
          v-if="results.length === 0 && !loading"
          class="empty-state"
        >
          <a-empty description="点击左侧「执行筛选」开始选股" />
        </div>

        <a-table
          v-if="results.length > 0"
          :columns="columns"
          :data-source="results"
          :pagination="{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['20', '50', '100'] }"
          :scroll="{ y: 'calc(100vh - 280px)' }"
          size="small"
          row-key="symbol"
          :custom-row="customRow"
          :row-class-name="rowClassName"
        >
          <template #bodyCell="{ column, text, record, index }">
            <template v-if="column.dataIndex === 'rank' || column.key === 'rank'">
              <span
                class="rank-badge"
                :class="getRankClass(index)"
              >{{ index + 1 }}</span>
            </template>
            <template v-else-if="column.dataIndex === 'name' || column.key === 'name'">
              <div class="stock-cell">
                <span class="stock-code">{{ record.symbol }}</span>
                <span class="stock-name">{{ record.name || record.symbol }}</span>
              </div>
            </template>
            <template v-else-if="column.dataIndex === 'score' || column.key === 'score'">
              <span
                class="score-value"
                :class="getScoreClass(text)"
              >{{ text?.toFixed(1) || '-' }}</span>
            </template>
            <template v-else-if="column.dataIndex === 'phase' || column.key === 'phase'">
              <a-tag
                :color="getPhaseColor(text)"
                size="small"
              >
                {{ text || '-' }}
              </a-tag>
            </template>
            <template v-else-if="column.dataIndex === 'asr' || column.key === 'asr'">
              <span>{{ text?.toFixed(3) || '-' }}</span>
            </template>
            <template v-else-if="column.dataIndex === 'concentration' || column.key === 'concentration'">
              <span>{{ text?.toFixed(3) || '-' }}</span>
            </template>
          </template>
        </a-table>
      </a-spin>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ScreeningResults',
  props: {
    results: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false }
  },
  data() {
    return {
      columns: [
        { title: '#', width: 48, scopedSlots: { customRender: 'rank' }, dataIndex: 'rank' },
        { title: '股票', width: 160, scopedSlots: { customRender: 'name' }, dataIndex: 'name' },
        { title: '综合评分', width: 90, scopedSlots: { customRender: 'score' }, dataIndex: 'score', sorter: (a, b) => (b.score || 0) - (a.score || 0), defaultSortOrder: 'descend' },
        { title: '主力阶段', width: 90, scopedSlots: { customRender: 'phase' }, dataIndex: 'phase' },
        { title: 'ASR', width: 80, scopedSlots: { customRender: 'asr' }, dataIndex: 'asr' },
        { title: '集中度', width: 80, scopedSlots: { customRender: 'concentration' }, dataIndex: 'concentration' }
      ]
    }
  },
  methods: {
    customRow(record) {
      return {
        on: {
          click: () => {
            this.$emit('select-stock', record)
          },
          dblclick: () => {
            this.$emit('navigate-stock', record)
          }
        }
      }
    },
    rowClassName(record) {
      return record._selected ? 'row-selected' : ''
    },
    getRankClass(index) {
      if (index === 0) return 'rank-gold'
      if (index === 1) return 'rank-silver'
      if (index === 2) return 'rank-bronze'
      return ''
    },
    getScoreClass(score) {
      if (!score) return ''
      if (score >= 80) return 'score-high'
      if (score >= 60) return 'score-mid'
      return 'score-low'
    },
    getPhaseColor(phase) {
      const colors = {
        'BUILDING': 'blue',
        'WASHING': 'orange',
        'LIFTING': 'red',
        'DISTRIBUTING': 'purple',
        'FALLING': 'green'
      }
      return colors[phase] || 'default'
    }
  }
}
</script>

<style scoped>
.screening-results {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1e293b;
  border-radius: 8px;
  overflow: hidden;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #0f172a;
  border-bottom: 1px solid #2a2a2a;
}

.results-title {
  font-weight: 600;
  color: #f1f5f9;
  font-size: 14px;
}

.results-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.results-count {
  font-size: 12px;
  color: #64748b;
}

.results-body {
  flex: 1;
  overflow: hidden;
}

.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  min-height: 300px;
}

.stock-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}

.stock-code {
  font-weight: 600;
  font-size: 12px;
  color: #94a3b8;
}

.stock-name {
  font-size: 13px;
  color: #e2e8f0;
}

.rank-badge {
  display: inline-block;
  width: 24px;
  height: 24px;
  line-height: 24px;
  text-align: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  background: #334155;
  color: #94a3b8;
}

.rank-gold { background: #f59e0b; color: #0f172a; }
.rank-silver { background: #94a3b8; color: #0f172a; }
.rank-bronze { background: #b45309; color: #f1f5f9; }

.score-value { font-weight: 700; }
.score-high { color: #22c55e; }
.score-mid { color: #f59e0b; }
.score-low { color: #64748b; }

:deep(.row-selected) {
  background: rgba(59,130,246,0.08) !important;
}
</style>
