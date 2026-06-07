import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/dashboard'),
    meta: { title: '仪表盘' }
  },
  {
    path: '/dashboard',
    name: 'DashboardPage',
    component: () => import('@/views/dashboard'),
    meta: { title: '仪表盘' }
  },
  {
    path: '/indicator-ide',
    name: 'IndicatorIDE',
    component: () => import('@/views/indicator-ide'),
    meta: { title: '个股策略分析' }
  },
  {
    path: '/screener',
    name: 'StockScreener',
    component: () => import('@/views/screener'),
    meta: { title: '选股系统' }
  },
  {
    path: '/watchlist',
    name: 'Watchlist',
    component: () => import('@/views/watchlist'),
    meta: { title: '自选监控' }
  },
  {
    path: '/ai-analysis',
    name: 'AIAnalysis',
    component: () => import('@/views/ai-analysis'),
    meta: { title: 'AI分析' }
  },
  {
    path: '/backtest',
    name: 'Backtest',
    component: () => import('@/views/backtest'),
    meta: { title: '回测系统' }
  },
  {
    path: '/factor-manager',
    name: 'FactorManager',
    component: () => import('@/views/factor-manager'),
    meta: { title: '因子组合管理' }
  },
  {
    path: '/strategy-templates',
    name: 'StrategyTemplates',
    component: () => import('@/views/strategy-templates'),
    meta: { title: '策略模板' }
  },
  {
    path: '/reports-center',
    name: 'ReportsCenter',
    component: () => import('@/views/reports-center'),
    meta: { title: '报告中心' }
  },
  {
    path: '/account',
    name: 'AccountManage',
    component: () => import('@/views/account'),
    meta: { title: '账户管理' }
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach((to) => {
  if (to.meta.title) {
    document.title = to.meta.title + ' - A股分析系统'
  }
})

export default router
