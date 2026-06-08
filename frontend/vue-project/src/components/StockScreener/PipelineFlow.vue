<template>
  <div class="pipeline-flow theme-dark">
    <div class="pipeline-header">
      <span class="pipeline-title">筛选流程</span>
      <a-button
        type="primary"
        size="small"
        :loading="running"
        icon="caret-right"
        @click="$emit('run')"
      >
        {{ running ? '筛选中...' : '执行筛选' }}
      </a-button>
    </div>

    <div class="pipeline-body">
      <!-- 全市场入口 -->
      <div
        class="pipeline-node"
        :class="{ active: true }"
      >
        <div class="node-icon">
          🌐
        </div>
        <div class="node-info">
          <div class="node-name">
            全市场股票
          </div>
          <div class="node-count">
            {{ totalStocks }}
          </div>
        </div>
      </div>

      <div class="pipeline-arrow">
        ↓
      </div>

      <!-- 第一层 -->
      <div
        class="pipeline-node"
        :class="layer1Class"
      >
        <div class="node-icon">
          🟢
        </div>
        <div class="node-info">
          <div class="node-name">
            L1: 风险剔除
          </div>
          <div class="node-desc">
            ST/亏损/流动性/估值
          </div>
          <div class="node-count">
            {{ layer1Count }}
          </div>
        </div>
      </div>

      <div class="pipeline-arrow">
        ↓
      </div>

      <!-- 第二层 -->
      <div
        class="pipeline-node"
        :class="layer2Class"
      >
        <div class="node-icon">
          🔵
        </div>
        <div class="node-info">
          <div class="node-name">
            L2: 主力识别
          </div>
          <div class="node-desc">
            筹码分布 + 评分排序
          </div>
          <div class="node-count">
            {{ layer2Count }}
          </div>
        </div>
      </div>

      <div class="pipeline-arrow">
        ↓
      </div>

      <!-- 第三层 -->
      <div
        class="pipeline-node"
        :class="layer3Class"
      >
        <div class="node-icon">
          🟣
        </div>
        <div class="node-info">
          <div class="node-name">
            L3: 策略验证
          </div>
          <div class="node-desc">
            缠论 + 因子 + AI
          </div>
          <div class="node-count">
            {{ layer3Count }}
          </div>
        </div>
      </div>

      <div class="pipeline-arrow">
        ↓
      </div>

      <!-- 最终结果 -->
      <div
        class="pipeline-node final"
        :class="finalClass"
      >
        <div class="node-icon">
          🏆
        </div>
        <div class="node-info">
          <div class="node-name">
            精选股票
          </div>
          <div class="node-count highlight">
            {{ finalCount }}
          </div>
        </div>
      </div>
    </div>

    <div class="pipeline-footer">
      <a-tooltip title="各层筛选参数配置">
        <a-button
          size="small"
          icon="setting"
          @click="$emit('configure')"
        >
          参数设置
        </a-button>
      </a-tooltip>
    </div>
  </div>
</template>

<script>
export default {
  name: 'PipelineFlow',
  props: {
    running: { type: Boolean, default: false },
    totalStocks: { type: Number, default: 5000 },
    layer1Count: { type: Number, default: 0 },
    layer2Count: { type: Number, default: 0 },
    layer3Count: { type: Number, default: 0 },
    finalCount: { type: Number, default: 0 },
    currentLayer: { type: Number, default: 0 }
  },
  computed: {
    layer1Class() {
      return this.getLayerClass(1)
    },
    layer2Class() {
      return this.getLayerClass(2)
    },
    layer3Class() {
      return this.getLayerClass(3)
    },
    finalClass() {
      return this.getLayerClass(4)
    }
  },
  methods: {
    getLayerClass(layer) {
      if (this.currentLayer > layer) return 'passed'
      if (this.currentLayer === layer) return 'active'
      if (this.running && this.currentLayer < layer) return 'pending'
      return ''
    }
  }
}
</script>

<style scoped>
.pipeline-flow {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1e293b;
  border-radius: 8px;
  overflow: hidden;
}

.pipeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #0f172a;
  border-bottom: 1px solid #2a2a2a;
}

.pipeline-title {
  font-weight: 600;
  color: #f1f5f9;
  font-size: 14px;
}

.pipeline-body {
  flex: 1;
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  overflow-y: auto;
}

.pipeline-node {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px;
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  border: 1px solid transparent;
  transition: all 0.3s;
}

.pipeline-node.active {
  border-color: #3b82f6;
  background: rgba(59,130,246,0.1);
}

.pipeline-node.passed {
  border-color: #22c55e;
  background: rgba(34,197,94,0.08);
}

.pipeline-node.pending {
  opacity: 0.4;
}

.pipeline-node.final.passed .node-count {
  color: #f59e0b;
  font-size: 18px;
}

.node-icon {
  font-size: 24px;
  width: 36px;
  text-align: center;
  flex-shrink: 0;
}

.node-info {
  flex: 1;
  min-width: 0;
}

.node-name {
  font-weight: 600;
  color: #e2e8f0;
  font-size: 13px;
}

.node-desc {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

.node-count {
  font-size: 20px;
  font-weight: 700;
  color: #94a3b8;
  margin-top: 2px;
}

.node-count.highlight {
  color: #f59e0b;
}

.pipeline-arrow {
  color: #334155;
  font-size: 18px;
  line-height: 1;
}

.pipeline-footer {
  padding: 8px 16px;
  border-top: 1px solid #2a2a2a;
  display: flex;
  justify-content: center;
}
</style>
