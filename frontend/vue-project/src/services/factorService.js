import request from '@/utils/request'

const API_BASE = '/api/factors'

export const factorService = {
  // 获取所有因子列表
  getFactors(params = {}) {
    return request({
      url: `${API_BASE}`,
      method: 'get',
      params
    })
  },

  // 获取因子详情
  getFactorDetail(factorId) {
    return request({
      url: `${API_BASE}/${factorId}`,
      method: 'get'
    })
  },

  // 计算单个因子
  calculateFactor(factorId, data) {
    return request({
      url: `${API_BASE}/calculate`,
      method: 'post',
      data: {
        factorId,
        ...data
      }
    })
  },

  // 批量计算因子
  batchCalculateFactors(factorIds, data) {
    return request({
      url: `${API_BASE}/calculate/batch`,
      method: 'post',
      data: {
        factorIds,
        ...data
      }
    })
  },

  // 获取因子组合列表
  getCombinations(params = {}) {
    return request({
      url: `${API_BASE}/combinations`,
      method: 'get',
      params
    })
  },

  // 创建因子组合
  createCombination(data) {
    return request({
      url: `${API_BASE}/combinations`,
      method: 'post',
      data
    })
  },

  // 更新因子组合
  updateCombination(id, data) {
    return request({
      url: `${API_BASE}/combinations/${id}`,
      method: 'put',
      data
    })
  },

  // 删除因子组合
  deleteCombination(id) {
    return request({
      url: `${API_BASE}/combinations/${id}`,
      method: 'delete'
    })
  },

  // 计算组合因子
  calculateCombination(id, data) {
    return request({
      url: `${API_BASE}/combinations/${id}/calculate`,
      method: 'post',
      data
    })
  },

  // 回测因子组合
  backtestCombination(data) {
    return request({
      url: `${API_BASE}/backtest`,
      method: 'post',
      data
    })
  },

  // 获取策略列表
  getStrategies() {
    return request({
      url: `${API_BASE}/strategies`,
      method: 'get'
    })
  },

  // 运行策略筛选
  runStrategyScreen(data) {
    return request({
      url: `${API_BASE}/strategies/pipeline/screen`,
      method: 'post',
      data
    })
  },

  // 评估因子
  evaluateFactor(factorId, data) {
    return request({
      url: `${API_BASE}/evaluate`,
      method: 'post',
      data: {
        factorId,
        ...data
      }
    })
  }
}

export default factorService
