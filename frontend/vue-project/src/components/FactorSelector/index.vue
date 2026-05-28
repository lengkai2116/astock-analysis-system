<template>
  <a-modal
    :visible="visible"
    title="选择因子"
    width="900px"
    @ok="handleOk"
    @cancel="handleCancel"
    :confirmLoading="loading"
  >
    <div class="factor-selector">
      <div class="search-bar">
        <a-input-search
          v-model="searchText"
          placeholder="搜索因子名称或描述"
          style="width: 100%"
          @search="handleSearch"
        />
      </div>

      <div class="selector-container">
        <div class="categories-panel">
          <div class="category-item"
            :class="{ active: activeCategory === 'all' }"
            @click="activeCategory = 'all'"
          >
            全部 ({{ allFactors.length }})
          </div>
          <div v-for="(factors, category) in factorByCategory" :key="category"
            class="category-item"
            :class="{ active: activeCategory === category }"
            @click="activeCategory = category"
          >
            {{ category }} ({{ factors.length }})
          </div>
        </div>

        <div class="factors-panel">
          <a-spin :spinning="loading">
            <div class="factors-list">
              <div v-for="factor in filteredFactors" :key="factor.id"
                class="factor-card"
                :class="{ selected: selectedFactors.includes(factor.id) }"
                @click="toggleFactor(factor)"
              >
                <div class="factor-header">
                  <span class="factor-name">{{ factor.name }}</span>
                  <a-tag v-if="factor.category" :color="getCategoryColor(factor.category)" size="small">
                    {{ factor.category }}
                  </a-tag>
                </div>
                <div class="factor-description">{{ factor.description }}</div>
                <div class="factor-meta">
                  <span v-if="factor.version">v{{ factor.version }}</span>
                  <span v-if="factor.author">· {{ factor.author }}</span>
                </div>
              </div>
            </div>
          </a-spin>
        </div>

        <div class="selected-panel">
          <div class="selected-header">
            <span>已选因子 ({{ selectedFactors.length }})</span>
            <a-button type="link" size="small" @click="clearSelected">
              清空
            </a-button>
          </div>
          <div class="selected-list">
            <div v-for="factor in selectedFactorsDetail" :key="factor.id" class="selected-item">
              <span class="item-name">{{ factor.name }}</span>
              <div class="item-actions">
                <a-input-number
                  :value="factorWeights[factor.id] || 1"
                  @change="(val) => updateWeight(factor.id, val)"
                  size="small"
                  :min="0.1"
                  :max="10"
                  :step="0.1"
                  style="width: 80px; margin-right: 8px;"
                />
                <a-icon type="close" @click.stop="removeFactor(factor.id)" />
              </div>
            </div>
            <div v-if="selectedFactors.length === 0" class="empty-state">
              请从左侧选择因子
            </div>
          </div>
        </div>
      </div>
    </div>
  </a-modal>
</template>

<script>
import { mapGetters, mapState } from 'vuex'

export default {
  name: 'FactorSelector',
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    value: {
      type: Array,
      default: () => []
    },
    weights: {
      type: Object,
      default: () => ({})
    }
  },
  data() {
    return {
      searchText: '',
      activeCategory: 'all',
      selectedFactors: [],
      factorWeights: {},
      loading: false,
      mockFactors: [
        { id: 'qlib_alpha1', name: 'Alpha#001', category: 'Qlib', description: '换手率因子，基于过去N天的成交量变化', version: '1.0', author: 'Qlib' },
        { id: 'qlib_alpha2', name: 'Alpha#002', category: 'Qlib', description: '价格动量因子，结合成交量过滤', version: '1.0', author: 'Qlib' },
        { id: 'qlib_alpha3', name: 'Alpha#003', category: 'Qlib', description: '波动率因子，基于股价标准差', version: '1.0', author: 'Qlib' },
        { id: 'gtja_1', name: 'GTJA#001', category: '国泰君安', description: '动量反转因子', version: '1.0', author: 'GTJA' },
        { id: 'gtja_2', name: 'GTJA#002', category: '国泰君安', description: '量价配合因子', version: '1.0', author: 'GTJA' },
        { id: 'academic_beta', name: 'Beta', category: '学术', description: '市场风险暴露因子', version: '1.0', author: 'Academic' },
        { id: 'momentum_roc', name: 'ROC', category: '动量', description: '变动率指标', version: '1.0', author: 'Technical' },
        { id: 'volatility_atr', name: 'ATR', category: '波动率', description: '真实波幅均值', version: '1.0', author: 'Technical' },
        { id: 'volume_obv', name: 'OBV', category: '成交量', description: '能量潮指标', version: '1.0', author: 'Technical' },
        { id: 'astock_1', name: 'A股动量', category: 'A股核心', description: 'A股市场特有的动量因子', version: '1.0', author: 'System' },
        { id: 'astock_2', name: 'A股反转', category: 'A股核心', description: 'A股市场特有的反转因子', version: '1.0', author: 'System' }
      ]
    }
  },
  computed: {
    ...mapState(['factors']),
    ...mapGetters(['factorByCategory']),
    
    allFactors() {
      if (this.factors.all && this.factors.all.length > 0) {
        return this.factors.all
      }
      return this.mockFactors
    },
    
    filteredFactors() {
      let factors = this.activeCategory === 'all' 
        ? this.allFactors 
        : (this.factorByCategory[this.activeCategory] || [])
      
      if (this.searchText) {
        const text = this.searchText.toLowerCase()
        factors = factors.filter(f => 
          f.name.toLowerCase().includes(text) || 
          (f.description && f.description.toLowerCase().includes(text))
        )
      }
      
      return factors
    },
    
    selectedFactorsDetail() {
      return this.allFactors.filter(f => this.selectedFactors.includes(f.id))
    }
  },
  watch: {
    visible(newVal) {
      if (newVal) {
        this.selectedFactors = [...this.value]
        this.factorWeights = { ...this.weights }
        this.$store.dispatch('loadFactors')
      }
    },
    value: {
      immediate: true,
      handler(val) {
        this.selectedFactors = [...val]
      }
    },
    weights: {
      immediate: true,
      handler(val) {
        this.factorWeights = { ...val }
      }
    }
  },
  methods: {
    getCategoryColor(category) {
      const colors = {
        'Qlib': 'blue',
        '国泰君安': 'green',
        '学术': 'purple',
        '动量': 'red',
        '波动率': 'orange',
        '成交量': 'cyan',
        'A股核心': 'gold'
      }
      return colors[category] || 'default'
    },
    
    handleSearch() {
    },
    
    toggleFactor(factor) {
      const index = this.selectedFactors.indexOf(factor.id)
      if (index > -1) {
        this.removeFactor(factor.id)
      } else {
        this.selectedFactors.push(factor.id)
        this.$set(this.factorWeights, factor.id, 1)
      }
    },
    
    removeFactor(factorId) {
      const index = this.selectedFactors.indexOf(factorId)
      if (index > -1) {
        this.selectedFactors.splice(index, 1)
        this.$delete(this.factorWeights, factorId)
      }
    },
    
    updateWeight(factorId, weight) {
      this.$set(this.factorWeights, factorId, weight)
    },
    
    clearSelected() {
      this.selectedFactors = []
      this.factorWeights = {}
    },
    
    handleOk() {
      this.$emit('ok', {
        factors: this.selectedFactors,
        weights: this.factorWeights
      })
    },
    
    handleCancel() {
      this.$emit('cancel')
    }
  }
}
</script>

<style scoped>
.factor-selector {
  height: 500px;
}

.search-bar {
  margin-bottom: 16px;
}

.selector-container {
  display: grid;
  grid-template-columns: 150px 1fr 240px;
  gap: 16px;
  height: 400px;
}

.categories-panel {
  overflow-y: auto;
  border-right: 1px solid #333;
  padding-right: 12px;
}

.category-item {
  padding: 8px 12px;
  margin-bottom: 4px;
  cursor: pointer;
  border-radius: 4px;
  color: #94a3b8;
  font-size: 13px;
  transition: all 0.2s;
}

.category-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #f1f5f9;
}

.category-item.active {
  background: rgba(59, 130, 246, 0.2);
  color: #3b82f6;
}

.factors-panel {
  overflow-y: auto;
}

.factors-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.factor-card {
  padding: 12px;
  background: #1e293b;
  border: 2px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.factor-card:hover {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.05);
}

.factor-card.selected {
  border-color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
}

.factor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.factor-name {
  font-weight: 600;
  color: #f1f5f9;
}

.factor-description {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 6px;
  line-height: 1.4;
}

.factor-meta {
  font-size: 11px;
  color: #64748b;
}

.selected-panel {
  border-left: 1px solid #333;
  padding-left: 12px;
  display: flex;
  flex-direction: column;
}

.selected-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: 600;
  color: #f1f5f9;
}

.selected-list {
  flex: 1;
  overflow-y: auto;
}

.selected-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px;
  background: #1e293b;
  border-radius: 4px;
  margin-bottom: 8px;
}

.item-name {
  color: #f1f5f9;
  font-size: 13px;
  flex: 1;
}

.item-actions {
  display: flex;
  align-items: center;
}

.empty-state {
  text-align: center;
  color: #64748b;
  padding: 40px 0;
}
</style>
