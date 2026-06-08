<template>
  <div class="strategy-templates-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">
        策略模板
      </h1>
      <div class="header-actions">
        <a-button
          type="primary"
          @click="showCreateModal"
        >
          <template #icon>
            <PlusOutlined />
          </template>
          创建模板
        </a-button>
      </div>
    </div>

    <div class="toolbar">
      <div class="search-box">
        <a-input-search
          v-model="searchQuery"
          placeholder="搜索策略模板..."
          style="width: 300px"
          @search="loadTemplates"
        />
      </div>
      <div class="category-filter">
        <a-select
          v-model="selectedCategory"
          placeholder="选择分类"
          style="width: 200px"
          @change="loadTemplates"
        >
          <a-select-option value="">
            全部
          </a-select-option>
          <a-select-option
            v-for="cat in categories"
            :key="cat.id"
            :value="cat.id"
          >
            {{ cat.icon }} {{ cat.name }}
          </a-select-option>
        </a-select>
      </div>
    </div>

    <div class="templates-grid">
      <a-card
        v-for="template in templates"
        :key="template.id"
        size="small"
        class="template-card"
        hoverable
        @click="viewTemplate(template)"
      >
        <div class="template-card-content">
          <div class="template-header">
            <span class="template-icon">{{ getCategoryIcon(template.category) }}</span>
            <div class="template-title">
              <h3>{{ template.name }}</h3>
              <span
                v-if="template.is_system"
                class="system-badge"
              >
                系统
              </span>
            </div>
          </div>
          <p class="template-description">
            {{ template.description }}
          </p>
          <div class="template-meta">
            <span class="meta-item">
              <i class="anticon anticon-star" />
              {{ template.rating.toFixed(1) }}
            </span>
            <span class="meta-item">
              <i class="anticon anticon-team" />
              {{ template.usage_count }}
            </span>
            <span class="category-tag">
              {{ getCategoryName(template.category) }}
            </span>
          </div>
          <div class="template-actions">
            <a-button
              size="small"
              @click.stop="useTemplate(template)"
            >
              使用
            </a-button>
            <a-button
              size="small"
              @click.stop="viewTemplate(template)"
            >
              查看
            </a-button>
            <a-button
              v-if="!template.is_system"
              size="small"
              type="danger"
              @click.stop="deleteTemplate(template)"
            >
              删除
            </a-button>
          </div>
        </div>
      </a-card>
    </div>

    <div class="pagination-wrapper">
      <a-pagination
        :current="currentPage"
        :total="total"
        :page-size="pageSize"
        @change="handlePageChange"
      />
    </div>

    <a-modal
      v-model="templateDetailVisible"
      :title="currentTemplate?.name"
      width="800px"
      :footer="null"
    >
      <div
        v-if="currentTemplate"
        class="template-detail"
      >
        <div class="detail-section">
          <h4>基本信息</h4>
          <p><strong>分类:</strong> {{ getCategoryName(currentTemplate.category) }}</p>
          <p><strong>描述:</strong> {{ currentTemplate.description }}</p>
          <p><strong>评分:</strong> {{ currentTemplate.rating.toFixed(1) }}</p>
          <p><strong>使用次数:</strong> {{ currentTemplate.usage_count }}</p>
        </div>

        <div
          v-if="currentTemplate.parameters?.length"
          class="detail-section"
        >
          <h4>参数配置</h4>
          <a-table
            :data-source="currentTemplate.parameters"
            :pagination="false"
            size="small"
            row-key="name"
          >
            <a-table-column
              key="name"
              title="参数名"
              data-index="name"
            />
            <a-table-column
              key="type"
              title="类型"
              data-index="type"
            />
            <a-table-column
              key="default_value"
              title="默认值"
              data-index="default_value"
            />
            <a-table-column
              key="range"
              title="范围"
            >
              <template #default="{ text, record }">
                {{ record.min_value }} ~ {{ record.max_value }}
              </template>
            </a-table-column>
            <a-table-column
              key="description"
              title="描述"
              data-index="description"
            />
          </a-table>
        </div>

        <div class="detail-section">
          <h4>代码模板</h4>
          <div class="code-preview">
            <pre><code>{{ currentTemplate.code_template }}</code></pre>
          </div>
        </div>

        <div class="detail-actions">
          <a-button
            type="primary"
            @click="useTemplate(currentTemplate)"
          >
            使用此模板
          </a-button>
        </div>
      </div>
    </a-modal>

    <a-modal
      v-model="createModalVisible"
      title="创建策略模板"
      width="800px"
      :confirm-loading="saving"
      @ok="saveTemplate"
    >
      <a-form layout="vertical">
        <a-form-item label="模板名称">
          <a-input
            v-model="newTemplate.name"
            placeholder="输入模板名称"
          />
        </a-form-item>
        <a-form-item label="模板分类">
          <a-select
            v-model="newTemplate.category"
            placeholder="选择分类"
          >
            <a-select-option
              v-for="cat in categories"
              :key="cat.id"
              :value="cat.id"
            >
              {{ cat.icon }} {{ cat.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="模板描述">
          <a-textarea
            v-model="newTemplate.description"
            :rows="3"
            placeholder="输入模板描述"
          />
        </a-form-item>
        <a-form-item label="代码模板">
          <a-textarea
            v-model="newTemplate.code_template"
            :rows="15"
            placeholder="输入策略代码模板"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script>
import strategyTemplateService from '@/services/strategyTemplateService'

export default {
  name: 'StrategyTemplatesPage',
  data() {
    return {
      templates: [],
      categories: [],
      searchQuery: '',
      selectedCategory: '',
      currentPage: 1,
      pageSize: 12,
      total: 0,
      templateDetailVisible: false,
      createModalVisible: false,
      currentTemplate: null,
      saving: false,
      newTemplate: {
        name: '',
        category: '',
        description: '',
        code_template: '',
        parameters: []
      }
    }
  },
  mounted() {
    this.loadTemplates()
    this.loadCategories()
  },
  methods: {
    async loadTemplates() {
      try {
        const params = {
          page: this.currentPage,
          page_size: this.pageSize
        }
        if (this.selectedCategory) params.category = this.selectedCategory
        if (this.searchQuery) params.search = this.searchQuery

        const result = await strategyTemplateService.getTemplates(params)
        if (result.success) {
          this.templates = result.data
          this.total = result.total
        }
      } catch (error) {
        this.$message.error('加载策略模板失败')
      }
    },

    async loadCategories() {
      try {
        const result = await strategyTemplateService.getCategories()
        if (result.success) {
          this.categories = result.data
        }
      } catch (error) {
        this.$message.error('加载分类失败')
      }
    },

    viewTemplate(template) {
      this.currentTemplate = template
      this.templateDetailVisible = true
    },

    useTemplate(template) {
      this.$message.info('正在跳转到策略编辑器...')
      this.$router.push({
        path: '/indicator-ide',
        query: { templateId: template.id }
      })
    },

    async deleteTemplate(template) {
      try {
        await this.$confirm({
          title: '确认删除',
          content: '确定要删除此策略模板吗？'
        })

        const result = await strategyTemplateService.deleteTemplate(template.id)
        if (result.success) {
          this.$message.success('删除成功')
          this.loadTemplates()
        }
      } catch (error) {
        if (error !== 'cancel') {
          this.$message.error('删除失败')
        }
      }
    },

    showCreateModal() {
      this.newTemplate = {
        name: '',
        category: '',
        description: '',
        code_template: '',
        parameters: []
      }
      this.createModalVisible = true
    },

    async saveTemplate() {
      if (!this.newTemplate.name || !this.newTemplate.category || !this.newTemplate.code_template) {
        this.$message.error('请填写完整的信息')
        return
      }

      try {
        this.saving = true
        const result = await strategyTemplateService.createTemplate(this.newTemplate)
        if (result.success) {
          this.$message.success('创建成功')
          this.createModalVisible = false
          this.loadTemplates()
        }
      } catch (error) {
        this.$message.error('创建失败')
      } finally {
        this.saving = false
      }
    },

    handlePageChange(page) {
      this.currentPage = page
      this.loadTemplates()
    },

    getCategoryIcon(category) {
      const icons = {
        trend_following: '📈',
        mean_reversion: '📉',
        arbitrage: '⚖️',
        event_driven: '📰',
        custom: '🎯'
      }
      return icons[category] || '📦'
    },

    getCategoryName(category) {
      const names = {
        trend_following: '趋势跟踪',
        mean_reversion: '均值回归',
        arbitrage: '套利',
        event_driven: '事件驱动',
        custom: '自定义'
      }
      return names[category] || category
    }
  }
}
</script>

<style scoped>
.strategy-templates-page {
  padding: 16px 24px;
  min-height: 100vh;
  background: var(--bg-primary, #0a1628);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.toolbar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.templates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}

.template-card {
  background: var(--bg-surface, #1e293b) !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  transition: all 0.3s;
}

.template-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}

.template-card-content {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.template-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.template-icon {
  font-size: 32px;
}

.template-title {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
}

.template-title h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary, #f1f5f9);
}

.system-badge {
  background: var(--color-primary, #3b82f6);
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.template-description {
  color: var(--text-secondary, #cbd5e1);
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 16px;
  flex: 1;
}

.template-meta {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-muted, #64748b);
  font-size: 13px;
}

.category-tag {
  background: rgba(255,255,255,0.1);
  color: var(--text-secondary, #cbd5e1);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.template-actions {
  display: flex;
  gap: 8px;
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
}

.template-detail {
  padding: 8px 0;
}

.detail-section {
  margin-bottom: 24px;
}

.detail-section h4 {
  margin: 0 0 12px 0;
  color: var(--text-primary, #f1f5f9);
}

.detail-section p {
  margin: 8px 0;
  color: var(--text-secondary, #cbd5e1);
}

.code-preview {
  background: #1a1a2e;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
}

.code-preview pre {
  margin: 0;
  color: #e0e0e0;
  font-size: 13px;
  line-height: 1.6;
}

.detail-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid rgba(255,255,255,0.1);
}
</style>
