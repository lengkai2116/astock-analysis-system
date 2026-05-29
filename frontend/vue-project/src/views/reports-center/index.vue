<template>
  <div class="reports-center-page theme-dark">
    <div class="page-header">
      <h1 class="page-title">策略报告中心</h1>
      <div class="header-actions">
        <a-button type="primary" icon="plus" @click="showGenerateModal">
          生成报告
        </a-button>
      </div>
    </div>

    <div class="toolbar">
      <a-input-search
        v-model="searchQuery"
        placeholder="搜索报告..."
        style="width: 300px"
        @search="loadReports"
      />
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

    <a-spin :spinning="loading">
      <div v-if="reports.length === 0" class="empty-state">
        <a-empty description="暂无报告">
          <a-button type="primary" @click="showGenerateModal">生成报告</a-button>
        </a-empty>
      </div>

      <div v-else>
        <div class="reports-grid">
          <a-card
            v-for="report in reports"
            :key="report.id"
            size="small"
            class="report-card"
            hoverable
            @click="viewReport(report)"
          >
            <div class="report-icon">{{ getReportIcon(report.report_type) }}</div>
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
                <a-button size="small">导出 <DownOutlined /></a-button>
                <a-menu slot="overlay">
                  <a-menu-item key="md" @click="exportReport(report, 'md')">Markdown</a-menu-item>
                  <a-menu-item key="html" @click="exportReport(report, 'html')">HTML</a-menu-item>
                  <a-menu-item key="json" @click="exportReport(report, 'json')">JSON</a-menu-item>
                  <a-menu-item key="txt" @click="exportReport(report, 'txt')">纯文本</a-menu-item>
                </a-menu>
              </a-dropdown>
              <a-popconfirm title="确定删除？" @confirm="deleteReport(report.id)">
                <a-button type="danger" size="small" ghost>删除</a-button>
              </a-popconfirm>
            </div>
          </a-card>
        </div>

        <div class="pagination-bar" v-if="total > pageSize">
          <a-pagination
            v-model="currentPage"
            :total="total"
            :pageSize="pageSize"
            showSizeChanger
            :pageSizeOptions="['12', '24', '48']"
            showTotal="共 {total} 条"
            @change="loadReports"
            @showSizeChange="onPageSizeChange"
          />
        </div>
      </div>
    </a-spin>

    <a-drawer
      :visible="drawerVisible"
      :width="800"
      title="报告详情"
      @close="drawerVisible = false"
      placement="right"
    >
      <div v-if="currentReport" class="report-viewer">
        <div class="report-viewer-header">
          <h2>{{ currentReport.title }}</h2>
          <div class="report-viewer-meta">
            <a-tag :color="getTypeColor(currentReport.report_type)">
              {{ getTypeName(currentReport.report_type) }}
            </a-tag>
            <span class="report-viewer-date">
              生成时间: {{ formatDate(currentReport.created_at) }}
            </span>
          </div>
          <div class="report-viewer-actions">
            <a-button size="small" icon="file-text" @click="exportReport(currentReport, 'md')">MD</a-button>
            <a-button size="small" icon="file" @click="exportReport(currentReport, 'html')">HTML</a-button>
            <a-button size="small" icon="download" @click="exportReport(currentReport, 'json')">JSON</a-button>
          </div>
        </div>

        <a-divider />

        <a-spin :spinning="reportContentLoading">
          <div class="report-content" v-html="renderedContent"></div>
        </a-spin>

        <div class="report-viewer-footer">
          <span>报告 ID: {{ currentReport.id }}</span>
        </div>
      </div>
    </a-drawer>

    <a-modal
      v-model="generateModalVisible"
      title="生成报告"
      @ok="handleGenerate"
      :confirmLoading="generating"
    >
      <a-form :form="generateForm" layout="vertical">
        <a-form-item label="报告类型" required>
          <a-select
            v-decorator="['reportType', { rules: [{ required: true, message: '请选择报告类型' }] }]"
          >
            <a-select-option value="single_stock">单股票策略报告</a-select-option>
            <a-select-option value="backtest">回测报告</a-select-option>
            <a-select-option value="research">综合研究报告</a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item label="股票代码">
          <a-input v-decorator="['tsCode']" placeholder="如: 000001.SZ" />
        </a-form-item>

        <a-form-item label="报告标题">
          <a-input v-decorator="['title']" placeholder="输入报告标题" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script>
import { DownOutlined } from '@ant-design/icons-vue'
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
      reportContentLoading: false,
      fullContent: null,

      generateModalVisible: false,
      generating: false,
      generateForm: this.$form.createForm(this)
    }
  },

  computed: {
    renderedContent() {
      if (this.fullContent) return this.fullContent
      if (!this.currentReport) return ''
      const html = this.currentReport.content_html
      if (html) return html
      const md = this.currentReport.content_md
      if (md) return '<pre>' + this.escapeHtml(md) + '</pre>'
      return '暂无内容'
    }
  },

  mounted() {
    this.loadReports()
  },

  methods: {
    escapeHtml(text) {
      if (!text) return ''
      return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    },

    async loadReports() {
      this.loading = true
      try {
        const params = { page: this.currentPage, page_size: this.pageSize }
        if (this.searchQuery) params.search = this.searchQuery
        if (this.selectedType) params.report_type = this.selectedType

        const res = await axios.get('/api/v2/reports', { params })
        if (res.success) {
          this.reports = res.data || []
          this.total = res.total || this.reports.length
        }
      } catch (err) {
        this.$message.error('加载报告列表失败')
      } finally {
        this.loading = false
      }
    },

    onPageSizeChange(size) {
      this.pageSize = size
      this.loadReports()
    },

    showGenerateModal() {
      this.generateModalVisible = true
      this.$nextTick(() => this.generateForm.resetFields())
    },

    async handleGenerate() {
      try {
        const values = await new Promise((resolve, reject) => {
          this.generateForm.validateFields((err, vals) => {
            if (err) reject(err); else resolve(vals)
          })
        })

        this.generating = true
        const res = await axios.post('/api/v2/reports/generate', {
          report_type: values.reportType,
          title: values.title || '未命名报告',
          ts_code: values.tsCode
        })

        if (res.success) {
          this.$message.success('报告生成成功')
          this.generateModalVisible = false
          this.loadReports()
          if (res.data) this.viewReport(res.data)
        }
      } catch (err) {
        if (err && err.errorFields) return
        this.$message.error('报告生成失败')
      } finally {
        this.generating = false
      }
    },

    async viewReport(report) {
      this.currentReport = report
      this.fullContent = null
      this.drawerVisible = true

      if (!this.fullContent) {
        this.reportContentLoading = true
        try {
          const res = await axios.get('/api/v2/reports/' + report.id)
          if (res.success && res.data) {
            this.fullContent = res.data.content_html
              || '<pre>' + this.escapeHtml(res.data.content_md) + '</pre>'
          }
        } catch (err) {
          this.fullContent = '<p class="load-error">加载报告内容失败</p>'
        } finally {
          this.reportContentLoading = false
        }
      }
    },

    async exportReport(report, format) {
      this.$message.info('正在导出 ' + format.toUpperCase() + '...')

      try {
        const res = await axios.get('/api/v2/reports/' + report.id + '/export', {
          params: { format },
          responseType: 'blob'
        })

        if (res instanceof Blob) {
          const mimeTypes = {
            md: 'text/markdown',
            html: 'text/html',
            json: 'application/json',
            txt: 'text/plain'
          }
          const blob = new Blob([res], { type: mimeTypes[format] || 'text/plain' })
          const url = URL.createObjectURL(blob)
          const link = document.createElement('a')
          link.href = url
          link.download = report.title.replace(/[^\w\u4e00-\u9fff-]/g, '_') + '.' + format
          link.click()
          URL.revokeObjectURL(url)
          this.$message.success('导出成功: ' + format.toUpperCase())
          return
        }

        const data = res.data || report.content_json || report
        const contentMap = {
          md: data.content_md || data.content || '',
          html: data.content_html || '<pre>' + (data.content_md || '') + '</pre>',
          json: JSON.stringify(data.content_json || data, null, 2),
          txt: (data.content_md || data.content || JSON.stringify(data, null, 2))
        }

        const content = contentMap[format] || JSON.stringify(data, null, 2)
        const filename = report.title.replace(/[^\w\u4e00-\u9fff-]/g, '_') + '.' + format
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        link.click()
        URL.revokeObjectURL(url)
        this.$message.success('导出成功')
      } catch (err) {
        this.$message.error('导出失败: ' + (err.message || '网络错误'))
      }
    },

    async deleteReport(reportId) {
      try {
        const res = await axios.delete('/api/v2/reports/' + reportId)
        if (res.success) {
          this.$message.success('删除成功')
          this.loadReports()
        }
      } catch (err) {
        this.$message.error('删除失败')
      }
    },

    getReportIcon(type) {
      return { single_stock: '📈', backtest: '📊', research: '📑' }[type] || '📄'
    },

    getTypeName(type) {
      return { single_stock: '单股票', backtest: '回测', research: '研究' }[type] || '未知'
    },

    getTypeColor(type) {
      return { single_stock: 'blue', backtest: 'green', research: 'purple' }[type] || 'default'
    },

    formatDate(dateStr) {
      if (!dateStr) return '-'
      return new Date(dateStr).toLocaleString('zh-CN')
    }
  }
}
</script>

<style lang="less" scoped>
.reports-center-page {
  padding: 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  h1 { margin: 0; font-size: 24px; font-weight: 600; }
}
.toolbar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}
.empty-state { text-align: center; padding: 80px 0; }
.reports-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.pagination-bar {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}
.report-card {
  transition: all 0.3s;
  .report-icon { font-size: 32px; text-align: center; margin-bottom: 12px; }
  .report-title {
    font-size: 16px; font-weight: 500; margin-bottom: 8px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .report-meta {
    display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
    .report-date { font-size: 12px; color: #999; }
  }
  .report-actions { display: flex; gap: 8px; }
}
.report-viewer {
  .report-viewer-header h2 { margin: 0 0 8px 0; }
  .report-viewer-meta { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }
  .report-viewer-date { font-size: 12px; color: #94a3b8; }
  .report-viewer-actions { display: flex; gap: 8px; margin-bottom: 16px; }
  .report-content {
    min-height: 400px; line-height: 1.8;
    :deep(h1), :deep(h2), :deep(h3) { margin-top: 24px; margin-bottom: 12px; }
    :deep(table) {
      width: 100%; border-collapse: collapse; margin: 16px 0;
      th, td { border: 1px solid #334155; padding: 8px; }
      th { background: #1e293b; }
    }
    :deep(pre) {
      background: #0f172a; padding: 16px; border-radius: 8px; overflow-x: auto;
      font-size: 13px; line-height: 1.5;
    }
    :deep(.load-error) { color: #ef4444; text-align: center; padding: 40px; }
  }
  .report-viewer-footer {
    margin-top: 24px; padding-top: 16px; border-top: 1px solid #2a2a2a;
    color: #64748b; font-size: 12px;
  }
}
</style>
