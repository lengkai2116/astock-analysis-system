<template>
  <div class="resonance-panel" v-if="hasData">
    <div class="resonance-panel__header">
      <h3 class="resonance-panel__title">🎯 共振评分 (150§5.3)</h3>
      <span class="resonance-panel__overall" :class="overallColor">
        {{ overallScore }}
      </span>
    </div>
    <div class="resonance-panel__desc">
      <p>{{ overallDesc }}</p>
    </div>
    <div class="resonance-panel__dimensions">
      <div v-for="dim in dimensions" :key="dim.id" class="dimension-item">
        <div class="dimension-item__header">
          <span class="dimension-item__name">{{ dim.name }}</span>
          <span class="dimension-item__score" :class="scoreColor(dim.score)">
            {{ dim.score }}
          </span>
        </div>
        <div class="dimension-bar">
          <div
            class="dimension-bar__fill"
            :style="{ width: dim.score + '%', background: dim.color }"
          />
        </div>
        <span class="dimension-item__weight">权重 {{ dim.weight }}%</span>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ResonancePanel',
  props: {
    overallScore: { type: Number, default: 0 },
    dimensions: { type: Array, default: () => [] },
  },
  computed: {
    hasData() {
      return this.overallScore > 0 || this.dimensions.length > 0
    },
    overallColor() {
      if (this.overallScore >= 70) return 'score-bullish'
      if (this.overallScore >= 40) return 'score-neutral'
      return 'score-bearish'
    },
    overallDesc() {
      if (this.overallScore >= 70) return '多维度信号共振，建议重点关注'
      if (this.overallScore >= 40) return '部分维度形成支撑，需进一步确认'
      return '整体信号偏弱，建议观望'
    },
  },
  methods: {
    scoreColor(score) {
      if (score >= 70) return 'score-bullish'
      if (score >= 40) return 'score-neutral'
      return 'score-bearish'
    },
  },
}
</script>

<style scoped>
.resonance-panel {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-default);
  padding: var(--space-16);
}

.resonance-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-8);
}

.resonance-panel__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.resonance-panel__overall {
  font-size: 28px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.score-bullish { color: var(--color-up); }
.score-neutral { color: var(--signal-watch); }
.score-bearish { color: var(--color-down); }

.resonance-panel__desc {
  margin-bottom: var(--space-16);
}

.resonance-panel__desc p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.dimension-item {
  margin-bottom: var(--space-12);
}

.dimension-item:last-child {
  margin-bottom: 0;
}

.dimension-item__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.dimension-item__name {
  font-size: 13px;
  color: var(--text-secondary);
}

.dimension-item__score {
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-mono);
}

.dimension-bar {
  height: 6px;
  background: var(--bg-subtle);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.dimension-bar__fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.6s ease;
}

.dimension-item__weight {
  font-size: 11px;
  color: var(--text-muted);
}
</style>
