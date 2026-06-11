<template>
  <a-modal
    :visible="visible"
    title="选择因子"
    width="900px"
    :confirm-loading="loading"
    @ok="handleOk"
    @cancel="handleCancel"
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
          <div
            class="category-item"
            :class="{ active: activeCategory === 'all' }"
            @click="activeCategory = 'all'"
          >
            全部 ({{ allFactors.length }})
          </div>
          <div
            v-for="(factors, category) in factorByCategory"
            :key="category"
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
              <div
                v-for="factor in filteredFactors"
                :key="factor.id"
                class="factor-card"
                :class="{ selected: selectedFactors.includes(factor.id) }"
                @click="toggleFactor(factor)"
              >
                <div class="factor-header">
                  <span class="factor-name">{{ factor.name }}</span>
                  <a-tag
                    v-if="factor.category"
                    :color="getCategoryColor(factor.category)"
                    size="small"
                  >
                    {{ factor.category }}
                  </a-tag>
                </div>
                <div class="factor-description">
                  {{ factor.description }}
                </div>
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
            <a-button
              type="link"
              size="small"
              @click="clearSelected"
            >
              清空
            </a-button>
          </div>
          <div class="selected-list">
            <div
              v-for="factor in selectedFactorsDetail"
              :key="factor.id"
              class="selected-item"
            >
              <span class="item-name">{{ factor.name }}</span>
              <div class="item-actions">
                <a-input-number
                  :value="factorWeights[factor.id] || 1"
                  size="small"
                  :min="0.1"
                  :max="10"
                  :step="0.1"
                  style="width: 80px; margin-right: 8px;"
                  @change="(val) => updateWeight(factor.id, val)"
                />
                <CloseOutlined @click.stop="removeFactor(factor.id)" />
              </div>
            </div>
            <div
              v-if="selectedFactors.length === 0"
              class="empty-state"
            >
              请从左侧选择因子
            </div>
          </div>
        </div>
      </div>
    </div>
  </a-modal>
</template>

<script>
import { CloseOutlined } from '@ant-design/icons-vue'
import { mapState, mapGetters } from 'pinia'
import { useAppStore } from '@/stores'

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
    }
  },
  computed: {
    ...mapState(['factors']),
    ...mapGetters(['factorByCategory']),
    
    allFactors() {
      if (this.factors.all && this.factors.all.length > 0) {
        return this.factors.all
      }
      return this.factors.all || []
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
        useAppStore().loadFactors()
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
        this.factorWeights[factor.id] = 1
      }
    },
    
    removeFactor(factorId) {
      const index = this.selectedFactors.indexOf(factorId)
      if (index > -1) {
        this.selectedFactors.splice(index, 1)
        delete this.factorWeights[factorId]
      }
    },
    
    updateWeight(factorId, weight) {
      this.factorWeights[factorId] = weight
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
