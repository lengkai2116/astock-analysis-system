import Vue from 'vue'
import Vuex from 'vuex'
import factorService from '@/services/factorService'

Vue.use(Vuex)

export default new Vuex.Store({
  state: {
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
  },
  mutations: {
    toggleSidebar(state) {
      state.sidebarCollapsed = !state.sidebarCollapsed
    },
    setSidebarCollapsed(state, collapsed) {
      state.sidebarCollapsed = collapsed
    },
    setSymbol(state, { symbol, market }) {
      state.symbol = symbol
      state.market = market || ''
    },
    setTimeframe(state, timeframe) {
      state.timeframe = timeframe
    },
    addActiveIndicator(state, indicator) {
      state.activeIndicators.push(indicator)
    },
    removeActiveIndicator(state, instanceId) {
      state.activeIndicators = state.activeIndicators.filter(
        ind => ind.instanceId !== instanceId
      )
    },
    updateActiveIndicator(state, indicator) {
      const index = state.activeIndicators.findIndex(
        ind => ind.instanceId === indicator.instanceId
      )
      if (index !== -1) {
        state.activeIndicators[index] = {
          ...state.activeIndicators[index],
          ...indicator
        }
      }
    },
    
    setFactorsLoading(state, loading) {
      state.factors.loading = loading
    },
    setFactors(state, factors) {
      state.factors.all = factors
    },
    setFactorsError(state, error) {
      state.factors.error = error
    },
    
    setFactorCombinations(state, combinations) {
      state.factorCombinations.all = combinations
    },
    setCurrentCombination(state, combination) {
      state.factorCombinations.current = combination
    },
    setCombinationsLoading(state, loading) {
      state.factorCombinations.loading = loading
    },
    
    setStrategies(state, { available, active }) {
      state.strategies.available = available || []
      state.strategies.active = active || []
    },
    setStrategiesLoading(state, loading) {
      state.strategies.loading = loading
    },
    
    setBacktestResult(state, data) {
      state.backtestResult.data = data
    },
    setBacktestLoading(state, loading) {
      state.backtestResult.loading = loading
    }
  },
  actions: {
    async loadIndicators({ commit }) {
      return []
    },
    
    async loadFactors({ commit }) {
      commit('setFactorsLoading', true)
      try {
        const response = await factorService.getFactors()
        if (response.success && response.data) {
          commit('setFactors', response.data)
        }
      } catch (error) {
        commit('setFactorsError', error.message)
        console.error('加载因子列表失败:', error)
      } finally {
        commit('setFactorsLoading', false)
      }
    },
    
    async loadFactorCombinations({ commit }) {
      commit('setCombinationsLoading', true)
      try {
        const response = await factorService.getCombinations()
        if (response.success && response.data) {
          commit('setFactorCombinations', response.data)
        }
      } catch (error) {
        console.error('加载因子组合失败:', error)
      } finally {
        commit('setCombinationsLoading', false)
      }
    },
    
    async loadStrategies({ commit }) {
      commit('setStrategiesLoading', true)
      try {
        const response = await factorService.getStrategies()
        if (response.success && response.data) {
          commit('setStrategies', response.data)
        }
      } catch (error) {
        console.error('加载策略列表失败:', error)
      } finally {
        commit('setStrategiesLoading', false)
      }
    },
    
    async createCombination({ dispatch }, data) {
      try {
        const response = await factorService.createCombination(data)
        if (response.success) {
          await dispatch('loadFactorCombinations')
          return response.data
        }
      } catch (error) {
        console.error('创建因子组合失败:', error)
        throw error
      }
    },
    
    async updateCombination({ dispatch }, { id, data }) {
      try {
        const response = await factorService.updateCombination(id, data)
        if (response.success) {
          await dispatch('loadFactorCombinations')
          return response.data
        }
      } catch (error) {
        console.error('更新因子组合失败:', error)
        throw error
      }
    },
    
    async deleteCombination({ dispatch }, id) {
      try {
        await factorService.deleteCombination(id)
        await dispatch('loadFactorCombinations')
      } catch (error) {
        console.error('删除因子组合失败:', error)
        throw error
      }
    },
    
    async runBacktest({ commit }, data) {
      commit('setBacktestLoading', true)
      try {
        const response = await factorService.backtestCombination(data)
        if (response.success && response.data) {
          commit('setBacktestResult', response.data)
          return response.data
        }
      } catch (error) {
        console.error('回测失败:', error)
        throw error
      } finally {
        commit('setBacktestLoading', false)
      }
    }
  },
  getters: {
    currentSymbolKey: state => `${state.market}:${state.symbol}`,
    
    factorByCategory: state => {
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
  }
})
