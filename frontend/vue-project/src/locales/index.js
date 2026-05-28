import Vue from 'vue'
import VueI18n from 'vue-i18n'

Vue.use(VueI18n)

const messages = {
  'zh-CN': {
    indicatorIde: {
      codeRailLabel: '代码',
      modified: '已修改',
      purchasedReadOnlyTag: '只读',
      save: '保存',
      delete: '删除',
      publish: '发布',
      createStrategy: '创建策略',
      saveAsNew: '另存为',
      fullscreenEditor: '编辑器全屏',
      exitFullscreen: '退出全屏',
      runIndicatorOnChart: '运行指标到图表',
      stopIndicatorOnChart: '停止运行',
      devGuideTooltip: '查看指标/策略代码编写教程',
      devGuide: '开发教程',
      codeQualityTitle: '代码质量检查',
      codeQualityRecheck: '重新检查',
      aiGenerate: 'AI 生成',
      aiAssistHint: '用自然语言描述您的指标想法，生成后可直接保存和回测',
      aiPromptPlaceholder: '描述您想生成的指标逻辑...',
      generateCode: '生成代码',
      generating: '生成中...',
      goIndicatorMarket: '前往指标市场',
      hideCode: '隐藏代码',
      showCode: '显示代码',
      chartWindow: '图表窗口',
      workspaceTabChart: '图表与回测',
      workspaceTabBacktest: '回测结果',
      toolbar: {
        watchlist: '自选标的',
        timeframe: 'K线周期',
        indicator: '指标'
      },
      editor: {
        period: '周期',
        fastLine: '快线周期',
        slowLine: '慢线周期',
        signalLine: '信号线周期',
        multiplier: '乘数',
        color: '颜色',
        lineWidth: '线宽',
        showIndicator: '显示指标',
        hideIndicator: '隐藏指标',
        settings: '设置',
        deleteIndicator: '删除指标',
        noEditableParams: '该指标无可编辑参数'
      }
    },
    dashboard: {
      indicator: {
        create: '创建指标',
        delete: '删除',
        action: {
          delete: '删除',
          publish: '发布',
          createStrategy: '创建策略'
        },
        drawing: {
          line: '线段',
          horizontalLine: '水平线',
          verticalLine: '垂直线',
          ray: '射线',
          straightLine: '直线',
          parallelLine: '平行线',
          priceLine: '价格线',
          priceChannel: '价格通道',
          fibonacciLine: '斐波那契',
          clearAll: '清除全部'
        },
        hint: {
          selectSymbol: '选择交易标的',
          selectSymbolDesc: '从上方下拉菜单中选择一个股票开始分析'
        },
        warning: {
          pyodideLoadFailed: 'Python引擎加载失败',
          pyodideLoadFailedDesc: '请刷新页面重试'
        },
        retry: '重试'
      }
    },
    common: {
      confirm: '确定',
      cancel: '取消'
    }
  }
}

const i18n = new VueI18n({
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages
})

export default i18n
