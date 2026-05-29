<template>
  <div class="factor-manager-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">📈 因子组合管理</h1>
      <div class="header-actions">
        <a-button type="primary" @click="showCreateModal = true">
          + 新建组合
        </a-button>
      </div>
    </div>

    <div class="content-container">
      <a-tabs v-model="activeTab">
        <a-tab-pane key="combinations" tab="我的组合">
          <div class="combinations-section">
            <div class="section-header">
              <span>因子组合列表</span>
              <a-button size="small" @click="loadCombinations">
                🔄 刷新
              </a-button>
            </div>
            
            <a-spin :spinning="loading">
              <div class="combinations-grid">
                <div v-for="combo in combinations" :key="combo.id" 
                  class="combination-card"
                  :class="{ active: selectedCombo && selectedCombo.id === combo.id }"
                  @click="selectCombination(combo)"
                >
                  <div class="card-header">
                    <span class="combo-name">{{ combo.name }}</span>
                    <a-tag v-if="combo.is_default" color="blue">默认</a-tag>
                    <a-tag v-if="combo.is_favorite" color="gold">收藏</a-tag>
                  </div>
                  <div class="card-description">{{ combo.description || '暂无描述' }}</div>
                  <div class="card-factors">
                    <span class="factor-count">{{ combo.factor_count || 0 }} 个因子</span>
                    <div class="factor-tags">
                      <a-tag v-for="(factor, idx) in (combo.factors || []).slice(0, 3)" :key="idx" size="small">
                        {{ factor }}
                      </a-tag>
                      <span v-if="(combo.factors || []).length > 3">
                        +{{ combo.factors.length - 3 }}
                      </span>
                    </div>
                  </div>
                  <div class="card-meta">
                    <span>创建于: {{ formatDate(combo.created_at) }}</span>
                  </div>
                  <div class="card-actions">
                    <a-button type="link" size="small" @click.stop="editCombination(combo)">
                      编辑
                    </a-button>
                    <a-button type="link" size="small" @click.stop="runBacktest(combo)">
                      回测
                    </a-button>
                    <a-popconfirm
                      title="确定删除该组合？"
                      @confirm="deleteCombination(combo.id)"
                    >
                      <a-button type="link" size="small" danger>
                        删除
                      </a-button>
                    </a-popconfirm>
                  </div>
                </div>

                <div v-if="combinations.length === 0 && !loading" class="empty-state">
                  <div class="empty-icon">📊</div>
                  <div class="empty-text">暂无因子组合</div>
                  <a-button type="primary" @click="showCreateModal = true">
                    创建第一个组合
                  </a-button>
                </div>
              </div>
            </a-spin>
          </div>
        </a-tab-pane>

        <a-tab-pane key="screen" tab="策略筛选">
          <div class="screen-section">
            <div class="screen-header">
              <h3>策略筛选</h3>
              <p class="screen-desc">基于选定的因子组合进行股票筛选</p>
            </div>

            <div class="screen-controls">
              <div class="control-group">
                <label>选择组合:</label>
                <a-select v-model="screenComboId" placeholder="请选择因子组合" style="width: 300px">
                  <a-select-option v-for="combo in combinations" :key="combo.id" :value="combo.id">
                    {{ combo.name }} ({{ combo.factor_count || 0 }}个因子)
                  </a-select-option>
                </a-select>
              </div>

              <div class="control-group">
                <label>股票池:</label>
                <a-select v-model="screenPool" style="width: 200px">
                  <a-select-option value="all">全部A股</a-select-option>
                  <a-select-option value="hs300">沪深300</a-select-option>
                  <a-select-option value="zz500">中证500</a-select-option>
                  <a-select-option value="watchlist">自选股</a-select-option>
                </a-select>
              </div>

              <div class="control-group">
                <label>筛选数量:</label>
                <a-input-number v-model="screenTopN" :min="1" :max="100" />
              </div>

              <a-button type="primary" @click="runScreen" :loading="screenLoading">
                开始筛选
              </a-button>
            </div>

            <div v-if="screenResults.length > 0" class="screen-results">
              <div class="results-header">
                <span>筛选结果 ({{ screenResults.length }} 只)</span>
                <a-button size="small" @click="exportResults">
                  导出
                </a-button>
              </div>
              <a-table
                :columns="screenColumns"
                :data-source="screenResults"
                :pagination="{ pageSize: 10 }"
                row-key="symbol"
              >
                <template slot="rank" slot-scope="text, record, index">
                  {{ index + 1 }}
                </template>
                <template slot="symbol" slot-scope="text, record">
                  <span class="stock-symbol">{{ record.symbol }}</span>
                  <span class="stock-name">{{ record.name }}</span>
                </template>
                <template slot="score" slot-scope="text">
                  <a-progress :percent="text * 100" :showInfo="false" :strokeColor="getScoreColor(text)" />
                  <span>{{ (text * 100).toFixed(1) }}分</span>
                </template>
                <template slot="action" slot-scope="text, record">
                  <a-button type="link" size="small" @click="goToChart(record)">
                    分析
                  </a-button>
                </template>
              </a-table>
            </div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </div>

    <a-modal
      v-model="showCreateModal"
      :title="editingCombo ? '编辑组合' : '新建组合'"
      @ok="handleSaveCombination"
      @cancel="closeCreateModal"
      width="600px"
    >
      <a-form :form="form" layout="vertical">
        <a-form-item label="组合名称" required>
          <a-input v-model="formData.name" placeholder="请输入组合名称" />
        </a-form-item>

        <a-form-item label="组合描述">
          <a-textarea v-model="formData.description" placeholder="请输入组合描述" :rows="2" />
        </a-form-item>

        <a-form-item label="选择因子" required>
          <div class="factor-selector-btn">
            <a-button @click="showFactorSelector = true">
              + 选择因子 ({{ selectedFactors.length }})
            </a-button>
          </div>
          <div class="selected-factors-list" v-if="selectedFactors.length > 0">
            <div v-for="factorId in selectedFactors" :key="factorId" class="selected-factor-item">
              <span>{{ getFactorName(factorId) }}</span>
              <div class="factor-weight">
                <label>权重:</label>
                <a-input-number
                  v-model="factorWeights[factorId]"
                  :min="0.1"
                  :max="10"
                  :step="0.1"
                  size="small"
                />
              </div>
              <CloseOutlined @click="removeSelectedFactor(factorId)" />
            </div>
          </div>
        </a-form-item>

        <a-form-item>
          <a-checkbox v-model="formData.is_default">设为默认组合</a-checkbox>
          <a-checkbox v-model="formData.is_favorite">收藏</a-checkbox>
        </a-form-item>
      </a-form>
    </a-modal>

    <FactorSelector
      :visible="showFactorSelector"
      :value="selectedFactors"
      :weights="factorWeights"
      @ok="handleFactorSelected"
      @cancel="showFactorSelector = false"
    />
  </div>
</template>

<script>
import { CloseOutlined } from '@ant-design/icons-vue'
import { mapState } from 'pinia'
import { useAppStore } from '@/stores'
import FactorSelector from '@/components/FactorSelector'

export default {
  name: 'FactorManagerPage',
  components: {
    FactorSelector
  },
  data() {
    return {
      activeTab: 'combinations',
      loading: false,
      showCreateModal: false,
      showFactorSelector: false,
      editingCombo: null,
      selectedCombo: null,
      
      selectedFactors: [],
      factorWeights: {},
      
      formData: {
        name: '',
        description: '',
        is_default: false,
        is_favorite: false
      },
      
      screenComboId: null,
      screenPool: 'all',
      screenTopN: 10,
      screenLoading: false,
      screenResults: [],
      
      screenColumns: [
        { title: '排名', key: 'rank', scopedSlots: { customRender: 'rank' }, width: 80 },
        { title: '股票', key: 'symbol', scopedSlots: { customRender: 'symbol' } },
        { title: '综合得分', key: 'score', scopedSlots: { customRender: 'score' }, width: 150 },
        { title: '操作', key: 'action', scopedSlots: { customRender: 'action' }, width: 100 }
      ],
      
      mockCombinations: [
        {
          id: 1,
          name: '动量策略组合',
          description: '基于动量因子的选股策略',
          factor_count: 3,
          factors: ['qlib_alpha1', 'momentum_roc', 'gtja_1'],
          is_default: true,
          is_favorite: true,
          created_at: '2026-05-20'
        },
        {
          id: 2,
          name: '波动率策略',
          description: '低波动率因子组合',
          factor_count: 2,
          factors: ['volatility_atr', 'qlib_alpha3'],
          is_default: false,
          is_favorite: false,
          created_at: '2026-05-21'
        }
      ],
      
      mockFactors: [
        { id: 'qlib_alpha1', name: 'Alpha#001', category: 'Qlib' },
        { id: 'qlib_alpha2', name: 'Alpha#002', category: 'Qlib' },
        { id: 'qlib_alpha3', name: 'Alpha#003', category: 'Qlib' },
        { id: 'gtja_1', name: 'GTJA#001', category: '国泰君安' },
        { id: 'gtja_2', name: 'GTJA#002', category: '国泰君安' },
        { id: 'academic_beta', name: 'Beta', category: '学术' },
        { id: 'momentum_roc', name: 'ROC', category: '动量' },
        { id: 'volatility_atr', name: 'ATR', category: '波动率' },
        { id: 'volume_obv', name: 'OBV', category: '成交量' },
        { id: 'astock_1', name: 'A股动量', category: 'A股核心' }
      ]
    }
  },
  
  computed: {
    ...mapState(useAppStore, ['factors']),
    
    combinations() {
      if (useAppStore().factorCombinations.all && useAppStore().factorCombinations.all.length > 0) {
        return useAppStore().factorCombinations.all
      }
      return this.mockCombinations
    }
  },
  
  mounted() {
    this.loadCombinations()
    if (this.$route.query.tab === 'screen') {
      this.activeTab = 'screen'
    }
  },
  
  methods: {
    async loadCombinations() {
      this.loading = true
      try {
        await useAppStore().loadFactorCombinations()
      } catch (error) {
        console.error('加载组合失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    selectCombination(combo) {
      this.selectedCombo = combo
    },
    
    editCombination(combo) {
      this.editingCombo = combo
      this.formData = {
        name: combo.name,
        description: combo.description,
        is_default: combo.is_default,
        is_favorite: combo.is_favorite
      }
      
      if (combo.factors && Array.isArray(combo.factors)) {
        this.selectedFactors = [...combo.factors]
        this.factorWeights = {}
        combo.factors.forEach(f => {
          this.factorWeights[f] = 1
        })
      }
      
      this.showCreateModal = true
    },
    
    closeCreateModal() {
      this.showCreateModal = false
      this.editingCombo = null
      this.formData = {
        name: '',
        description: '',
        is_default: false,
        is_favorite: false
      }
      this.selectedFactors = []
      this.factorWeights = {}
    },
    
    async handleSaveCombination() {
      if (!this.formData.name) {
        this.$message.error('请输入组合名称')
        return
      }
      
      if (this.selectedFactors.length === 0) {
        this.$message.error('请至少选择一个因子')
        return
      }
      
      try {
        const data = {
          name: this.formData.name,
          description: this.formData.description,
          factors: JSON.stringify(this.selectedFactors),
          weights: JSON.stringify(this.factorWeights),
          is_default: this.formData.is_default ? 1 : 0,
          is_favorite: this.formData.is_favorite ? 1 : 0
        }
        
        if (this.editingCombo) {
          await useAppStore().updateCombination({
            id: this.editingCombo.id,
            data
          })
          this.$message.success('组合更新成功')
        } else {
          await useAppStore().createCombination(data)
          this.$message.success('组合创建成功')
        }
        
        this.closeCreateModal()
        this.loadCombinations()
      } catch (error) {
        this.$message.error('保存失败')
      }
    },
    
    async deleteCombination(id) {
      try {
        await useAppStore().deleteCombination(id)
        this.$message.success('删除成功')
        if (this.selectedCombo && this.selectedCombo.id === id) {
          this.selectedCombo = null
        }
      } catch (error) {
        this.$message.error('删除失败')
      }
    },
    
    async runBacktest(combo) {
      this.$router.push({
        name: 'Backtest',
        query: { comboId: combo.id }
      })
    },
    
    handleFactorSelected(data) {
      this.selectedFactors = data.factors
      this.factorWeights = data.weights
      this.showFactorSelector = false
    },
    
    removeSelectedFactor(factorId) {
      const index = this.selectedFactors.indexOf(factorId)
      if (index > -1) {
        this.selectedFactors.splice(index, 1)
        delete this.factorWeights[factorId]
      }
    },
    
    getFactorName(factorId) {
      const factor = this.mockFactors.find(f => f.id === factorId)
      return factor ? factor.name : factorId
    },
    
    formatDate(date) {
      if (!date) return '--'
      return new Date(date).toLocaleDateString('zh-CN')
    },
    
    async runScreen() {
      if (!this.screenComboId) {
        this.$message.error('请选择因子组合')
        return
      }
      
      this.screenLoading = true
      try {
        const response = await useAppStore().runBacktest({
          combination_id: this.screenComboId,
          pool: this.screenPool,
          top_n: this.screenTopN
        })
        
        this.screenResults = this.mockScreenResults()
        this.$message.success('筛选完成')
      } catch (error) {
        this.$message.error('筛选失败')
      } finally {
        this.screenLoading = false
      }
    },
    
    mockScreenResults() {
      const stocks = [
        { symbol: '600519.SH', name: '贵州茅台' },
        { symbol: '000001.SZ', name: '平安银行' },
        { symbol: '000002.SZ', name: '万科A' },
        { symbol: '601318.SH', name: '中国平安' },
        { symbol: '000858.SZ', name: '五粮液' },
        { symbol: '600036.SH', name: '招商银行' },
        { symbol: '000333.SZ', name: '美的集团' },
        { symbol: '600000.SH', name: '浦发银行' }
      ]
      
      return stocks.slice(0, this.screenTopN).map((stock, index) => ({
        ...stock,
        score: 1 - (index * 0.1) + (Math.random() * 0.1)
      }))
    },
    
    getScoreColor(score) {
      if (score >= 0.8) return '#52c41a'
      if (score >= 0.6) return '#1890ff'
      if (score >= 0.4) return '#faad14'
      return '#f5222d'
    },
    
    exportResults() {
      this.$message.info('导出功能开发中')
    },
    
    goToChart(record) {
      this.$router.push({
        name: 'IndicatorIDE',
        query: { symbol: record.symbol }
      })
    }
  }
}
</script>

<style scoped>
.factor-manager-page {
  min-height: 100vh;
  background: #141414;
  padding: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #f1f5f9;
}

.content-container {
  background: #1e293b;
  border-radius: 12px;
  padding: 24px;
}

.combinations-section {
  min-height: 400px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  font-size: 16px;
  font-weight: 600;
  color: #f1f5f9;
}

.combinations-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.combination-card {
  background: #0f172a;
  border: 2px solid transparent;
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
}

.combination-card:hover {
  border-color: #3b82f6;
}

.combination-card.active {
  border-color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.combo-name {
  font-size: 16px;
  font-weight: 600;
  color: #f1f5f9;
}

.card-description {
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 12px;
  line-height: 1.5;
}

.card-factors {
  margin-bottom: 12px;
}

.factor-count {
  font-size: 12px;
  color: #64748b;
  display: block;
  margin-bottom: 8px;
}

.factor-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.card-meta {
  font-size: 11px;
  color: #64748b;
  margin-bottom: 12px;
}

.card-actions {
  display: flex;
  gap: 8px;
  border-top: 1px solid #2a2a2a;
  padding-top: 12px;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-text {
  font-size: 16px;
  margin-bottom: 24px;
}

.screen-section {
  min-height: 400px;
}

.screen-header {
  margin-bottom: 24px;
}

.screen-header h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
  color: #f1f5f9;
}

.screen-desc {
  margin: 0;
  color: #94a3b8;
  font-size: 14px;
}

.screen-controls {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  padding: 20px;
  background: #0f172a;
  border-radius: 8px;
  margin-bottom: 24px;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-group label {
  color: #94a3b8;
  font-size: 14px;
  white-space: nowrap;
}

.screen-results {
  background: #0f172a;
  border-radius: 8px;
  padding: 20px;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  font-size: 14px;
  font-weight: 600;
  color: #f1f5f9;
}

.stock-symbol {
  font-weight: 600;
  color: #f1f5f9;
  margin-right: 8px;
}

.stock-name {
  color: #94a3b8;
  font-size: 12px;
}

.factor-selector-btn {
  margin-bottom: 12px;
}

.selected-factors-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.selected-factor-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #0f172a;
  border-radius: 4px;
}

.factor-weight {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

.factor-weight label {
  font-size: 12px;
  color: #64748b;
}
</style>
