<template>
  <div class="reports-center-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">📊 策略报告中心</h1>
      <div class="header-actions">
        <a-button type="primary" @click="showGenerateModal">
          <i slot="icon" class="anticon anticon-plus"></i>
          生成报告
        </a-button>
      </div>
    </div>

    <div class="toolbar">
      <div class="search-box">
        <a-input-search
          v-model="searchQuery"
          placeholder="搜索报告..."
          style="width: 300px"
          @search="loadReports"
        />
      </div>
      <div class="type-filter">
        <a-select
          v-model="selectedType"
          placeholder="报告类型"
          style="width: 200px"
          @change="loadReports"
        >
          <a-select-option value="">全部</a-select-option>
          <a-select-option value="single_stock">单股票策略</a-select-option>
          <a-select-option value="backtest">回测报告</a-select-option>
          <a-select-option value="research">研究报告</a-select-option>
        </a-select>
      </div>
    </div>

    <a-spin :spinning="loading">
      <div v-if="reports.length === 0" class="empty-state">
        <a-empty description="暂无报告，请生成第一份报告">
          <a-button type="primary" @click="showGenerateModal">
            生成报告
          </a-button>
        </a-empty>
      </div>

      <div v-else class="reports-grid">
        <a-card
          v-for="report in reports"
          :key="report.id"
          size="small"
          class="report-card"
          hoverable
          @click="viewReport(report)"
        >
          <div class="report-icon">
            {{ getReportIcon(report.report_type) }}
          </div>
          <div class="report-title">{{ report.title }}</div>
          <div class="report-meta">
            <a-tag :color="getTypeColor(report.report_type)">
              {{ getTypeName(report.report_type) }}
            </a-tag>
            <span class="report-date">{{ formatDate(report.created_at) }}</span>
          </div>
          <div class="report-actions" @click.stop>
            <a-button size="small" @click="viewReport(report)">查看</a-button>
            <a-dropdown>
              <a-button size="small">
                导出 <a-icon type="down" />
              </a-button>
              <a-menu slot="overlay">
                <a-menu-item key="md" @click="exportReport(report, 'md')">Markdown</a-menu-item>
                <a-menu-item key="html" @click="exportReport(report, 'html')">HTML</a-menu-item>
                <a-menu-item key="json" @click="exportReport(report, 'json')">JSON</a-menu-item>
              </a-menu>
            </a-dropdown>
            <a-popconfirm
              title="确定要删除这份报告吗？"
              @confirm="deleteReport(report.id)"
            >
              <a-button type="danger" size="small" ghost>删除</a-button>
            </a-popconfirm>
          </div>
        </a-card>
      </div>
    </a-spin>

    <!-- 报告查看抽屉 -->
    <a-drawer
      :visible="drawerVisible"
      :width="800"
      title="报告详情"
      @close="drawerVisible = false"
    >
      <div v-if="currentReport" class="report-viewer">
        <div class="report-header">
          <h2>{{ currentReport.title }}</h2>
          <a-tag :color="getTypeColor(currentReport.report_type)">
            {{ getTypeName(currentReport.report_type) }}
          </a-tag>
        </div>
        
        <a-divider />
        
        <div class="report-content" v-html="renderedContent"></div>
        
        <a-divider />
        
        <div class="report-footer">
          <span class="report-date">
            生成时间：{{ formatDate(currentReport.created_at) }}
          </span>
        </div>
      </div>
    </a-drawer>

    <!-- 生成报告弹窗 -->
    <a-modal
      v-model="generateModalVisible"
      title="生成报告"
      @ok="handleGenerate"
      :confirmLoading="generating"
    >
      <a-form :form="generateForm" layout="vertical">
        <a-form-item label="报告类型" required>
          <a-select v-decorator="['reportType', { rules: [{ required: true }] }]">
            <a-select-option value="single_stock">单股票策略报告</a-select-option>
            <a-select-option value="backtest">回测报告</a-select-option>
            <a-select-option value="research">综合研究报告</a-select-option>
          </a-select>
        </a-form-item>
        
        <a-form-item label="股票代码" v-if="generateForm.getFieldValue('reportType') === 'single_stock'">
          <a-input v-decorator="['tsCode']" placeholder="如：000001.SZ" />
        </a-form-item>
        
        <a-form-item label="报告标题">
          <a-input v-decorator="['title']" placeholder="输入报告标题" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script>
import axios from '@/utils/request'

export default {
  name: 'ReportsCenterPage',
  data() {
    return {
      reports: [],
      loading: false,
      searchQuery: '',
      selectedType: '',
      currentPage: 1,
      pageSize: 12,
      total: 0,
      
      drawerVisible: false,
      currentReport: null,
      
      generateModalVisible: false,
      generating: false,
      generateForm: this.$form.createForm(this),
    }
  },
  
  computed: {
    renderedContent() {
      if (!this.currentReport) return ''
      return this.currentReport.content_html || this.currentReport.content_md || ''
    },
  },
  
  mounted() {
    this.loadReports()
  },
  
  methods: {
    async loadReports() {
      this.loading = true
      try {
        const params = {
          page: this.currentPage,
          page_size: this.pageSize,
        }
        if (this.searchQuery) params.search = this.searchQuery
        if (this.selectedType) params.report_type = this.selectedType
        
        const response = await axios.get('/api/v2/reports', { params })
        if (response.success) {
          this.reports = response.data || []
          this.total = response.total || 0
        }
      } catch (error) {
        this.$message.error('加载报告列表失败')
      } finally {
        this.loading = false
      }
    },
    
    showGenerateModal() {
      this.generateModalVisible = true
      this.generateForm.resetFields()
    },
    
    async handleGenerate() {
      try {
        await this.generateForm.validateFields()
        const values = this.generateForm.getFieldsValue()
        
        this.generating = true
        const response = await axios.post('/api/v2/reports/generate', {
          report_type: values.reportType,
          title: values.title || '未命名报告',
          ts_code: values.tsCode,
        })
        
        if (response.success) {
          this.$message.success('报告生成成功')
          this.generateModalVisible = false
          this.loadReports()
          if (response.data) {
            this.viewReport(response.data)
          }
        }
      } catch (error) {
        this.$message.error('报告生成失败')
      } finally {
        this.generating = false
      }
    },
    
    viewReport(report) {
      this.currentReport = report
      this.drawerVisible = true
    },
    
    async exportReport(report, format) {
      this.$message.info(`正在导出${format.toUpperCase()}格式...`)
      // 实际导出逻辑
      let content = ''
      let filename = ''
      
      switch (format) {
        case 'md':
          content = report.content_md || ''
          filename = `${report.title}.md`
          break
        case 'html':
          content = report.content_html || ''
          filename = `${report.title}.html`
          break
        case 'json':
          content = JSON.stringify(report.content_json || {}, null, 2)
          filename = `${report.title}.json`
          break
      }
      
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      
      this.$message.success('导出成功')
    },
    
    async deleteReport(reportId) {
      try {
        const response = await axios.delete(`/api/v2/reports/${reportId}`)
        if (response.success) {
          this.$message.success('删除成功')
          this.loadReports()
        }
      } catch (error) {
        this.$message.error('删除失败')
      }
    },
    
    getReportIcon(type) {
      const icons = {
        'single_stock': '📈',
        'backtest': '📊',
        'research': '📑',
      }
      return icons[type] || '📄'
    },
    
    getTypeName(type) {
      const names = {
        'single_stock': '单股票',
        'backtest': '回测',
        'research': '研究',
      }
      return names[type] || '未知'
    },
    
    getTypeColor(type) {
      const colors = {
        'single_stock': 'blue',
        'backtest': 'green',
        'research': 'purple',
      }
      return colors[type] || 'default'
    },
    
    formatDate(dateStr) {
      if (!dateStr) return '-'
      const date = new Date(dateStr)
      return date.toLocaleString('zh-CN')
    },
  },
}
</script>

<style lang="less" scoped>
.reports-center-page {
  padding: 24px;
  
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    
    .page-title {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
  }
  
  .toolbar {
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
  }
  
  .empty-state {
    text-align: center;
    padding: 60px 0;
  }
  
  .reports-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
  }
  
  .report-card {
    transition: all 0.3s;
    
    .report-icon {
      font-size: 32px;
      text-align: center;
      margin-bottom: 12px;
    }
    
    .report-title {
      font-size: 16px;
      font-weight: 500;
      margin-bottom: 8px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    
    .report-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      
      .report-date {
        font-size: 12px;
        color: #999;
      }
    }
    
    .report-actions {
      display: flex;
      gap: 8px;
    }
  }
  
  .report-viewer {
    .report-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      
      h2 {
        margin: 0;
      }
    }
    
    .report-content {
      min-height: 400px;
      line-height: 1.8;
      
      :deep(h1), :deep(h2), :deep(h3) {
        margin-top: 24px;
        margin-bottom: 12px;
      }
      
      :deep(table) {
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0;
        
        th, td {
          border: 1px solid #ddd;
          padding: 8px;
        }
        
        th {
          background: #f5f5f5;
        }
      }
      
      :deep(.disclaimer) {
        background: #fff3e0;
        padding: 12px;
        border-radius: 4px;
        margin-top: 24px;
        color: #e65100;
      }
    }
    
    .report-footer {
      color: #999;
      font-size: 12px;
    }
  }
}
</style>
