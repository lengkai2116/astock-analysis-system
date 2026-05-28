import Vue from 'vue'
import VueRouter from 'vue-router'

Vue.use(VueRouter)

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
    meta: { title: '指标IDE' }
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
  }
]

const router = new VueRouter({
  mode: 'hash',
  routes
})

router.beforeEach((to, from, next) => {
  if (to.meta.title) {
    document.title = to.meta.title + ' - A股分析系统'
  }
  next()
})

export default router
