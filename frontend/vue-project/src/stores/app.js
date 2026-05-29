import { defineStore } from 'pinia'
import factorService from '@/services/factorService'

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebarCollapsed: false,
    userId: null,
    symbol: '000001.SZ',
    market: 'SZ',
    timeframe: '1D',
    watchlist: [
      { symbol: '000001.SZ', market: 'SZ', name: '平安银行' },
      { symbol: '000002.SZ', market: 'SZ', name: '万科A' },
      { symbol: '600000.SH', market: 'SH', name: '浦发银行' },
      { symbol: '600519.SH', market: 'SH', name: '贵州茅台' },
      { symbol: '000858.SZ', market: 'SZ', name: '五粮液' }
    ],
    activeIndicators: [],
    indicators: [],

    factors: {
      all: [],
      loading: false,
      error: null
    },

    factorCombinations: {
      all: [],
      current: null,
      loading: false
    },

    strategies: {
      available: [],
      active: [],
      loading: false
    },

    backtestResult: {
      data: null,
      loading: false
    }
  }),

  getters: {
    currentSymbolKey: (state) => `${state.market}:${state.symbol}`,

    factorByCategory: (state) => {
      const categories = {}
      state.factors.all.forEach(factor => {
        const category = factor.category || '其他'
        if (!categories[category]) {
          categories[category] = []
        }
        categories[category].push(factor)
      })
      return categories
    }
  },

  actions: {
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },

    setSidebarCollapsed(collapsed) {
      this.sidebarCollapsed = collapsed
    },

    setSymbol({ symbol, market }) {
      this.symbol = symbol
      this.market = market || ''
    },

    setTimeframe(timeframe) {
      this.timeframe = timeframe
    },

    addActiveIndicator(indicator) {
      this.activeIndicators.push(indicator)
    },

    removeActiveIndicator(instanceId) {
      this.activeIndicators = this.activeIndicators.filter(
        ind => ind.instanceId !== instanceId
      )
    },

    updateActiveIndicator(indicator) {
      const index = this.activeIndicators.findIndex(
        ind => ind.instanceId === indicator.instanceId
      )
      if (index !== -1) {
        this.activeIndicators[index] = {
          ...this.activeIndicators[index],
          ...indicator
        }
      }
    },

    async loadIndicators() {
      return []
    },

    async loadFactors() {
      this.factors.loading = true
      try {
        const response = await factorService.getFactors()
        if (response.success && response.data) {
          this.factors.all = response.data
        }
      } catch (error) {
        this.factors.error = error.message
        console.error('加载因子列表失败:', error)
      } finally {
        this.factors.loading = false
      }
    },

    async loadFactorCombinations() {
      this.factorCombinations.loading = true
      try {
        const response = await factorService.getCombinations()
        if (response.success && response.data) {
          this.factorCombinations.all = response.data
        }
      } catch (error) {
        console.error('加载因子组合失败:', error)
      } finally {
        this.factorCombinations.loading = false
      }
    },

    async loadStrategies() {
      this.strategies.loading = true
      try {
        const response = await factorService.getStrategies()
        if (response.success && response.data) {
          this.strategies.available = response.data.available || []
          this.strategies.active = response.data.active || []
        }
      } catch (error) {
        console.error('加载策略列表失败:', error)
      } finally {
        this.strategies.loading = false
      }
    },

    async createCombination(data) {
      try {
        const response = await factorService.createCombination(data)
        if (response.success) {
          await this.loadFactorCombinations()
          return response.data
        }
      } catch (error) {
        console.error('创建因子组合失败:', error)
        throw error
      }
    },

    async updateCombination({ id, data }) {
      try {
        const response = await factorService.updateCombination(id, data)
        if (response.success) {
          await this.loadFactorCombinations()
          return response.data
        }
      } catch (error) {
        console.error('更新因子组合失败:', error)
        throw error
      }
    },

    async deleteCombination(id) {
      try {
        await factorService.deleteCombination(id)
        await this.loadFactorCombinations()
      } catch (error) {
        console.error('删除因子组合失败:', error)
        throw error
      }
    },

    async runBacktest(data) {
      this.backtestResult.loading = true
      try {
        const response = await factorService.backtestCombination(data)
        if (response.success && response.data) {
          this.backtestResult.data = response.data
          return response.data
        }
      } catch (error) {
        console.error('回测失败:', error)
        throw error
      } finally {
        this.backtestResult.loading = false
      }
    }
  }
})
