/**
 * 统一数据服务层
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §2.3
 * 封装所有后端 API 请求，提供缓存、去重、批量请求能力
 */
import request from '../utils/request'
import { dedupedRequest, batchRequests, clearCache } from '../utils/requestDedupe'
import { message } from 'ant-design-vue'

class DataService {
  constructor() {
    this._baseURL = window.__API_BASE__ || import.meta.env.VITE_API_BASE_URL || ''
  }

  /** 基础路径 */
  get baseURL() {
    return this._baseURL
  }

  set baseURL(url) {
    this._baseURL = url
  }

  // ==================== 行情数据 ====================

  /** K 线数据 */
  async getKline(tsCode, period = 'D', startDate, endDate) {
    return this._get('/api/v3/chart/kline', {
      ts_code: tsCode,
      period,
      start_date: startDate,
      end_date: endDate,
    })
  }

  /** 批量 K 线（Phase 2+） */
  async getKlinesBatch(requests) {
    return this._post('/api/v3/klines/batch', { requests })
  }

  /** 股票搜索 */
  async searchSymbols(query, limit = 20) {
    return this._get('/api/v3/symbols/search', { q: query, limit })
  }

  /** 股票池列表 */
  async getUniverseList(category) {
    return this._get('/api/v3/universe/list', { category })
  }

  // ==================== 自选股 ====================

  /** 获取自选列表 */
  async getWatchlist() {
    return this._get('/api/v3/watchlist')
  }

  /** 添加自选 */
  async addWatchlist(tsCode, note) {
    return this._post('/api/v3/watchlist', { ts_code: tsCode, note })
  }

  /** 删除自选 */
  async removeWatchlist(tsCode) {
    return this._delete(`/api/v3/watchlist/${tsCode}`)
  }

  /** 更新自选排序 */
  async reorderWatchlist(tsCodes) {
    return this._put('/api/v3/watchlist/reorder', { ts_codes: tsCodes })
  }

  // ==================== 市场数据 ====================

  /** 品种分类树 */
  async getMarketCategories() {
    return this._get('/api/v3/market/categories')
  }

  /** 数据源状态 */
  async getDataSourceStatus() {
    return this._get('/api/v3/data-source/status')
  }

  // ==================== 模拟交易 ====================

  /** 下单 */
  async placeOrder(order) {
    return this._post('/api/v3/sim/order', order)
  }

  /** 订单列表 */
  async getOrders(status) {
    return this._get('/api/v3/sim/orders', { status })
  }

  /** 撤单 */
  async cancelOrder(orderId) {
    return this._post(`/api/v3/sim/order/${orderId}/cancel`)
  }

  /** 持仓查询 */
  async getPositions() {
    return this._get('/api/v3/sim/positions')
  }

  /** 平仓 */
  async closePosition(positionId, price) {
    return this._post(`/api/v3/sim/position/${positionId}/close`, { price })
  }

  /** 交易汇总 */
  async getTradeSummary() {
    return this._get('/api/v3/sim/trades/summary')
  }

  /** 重置模拟账户 */
  async resetAccount() {
    return this._post('/api/v3/sim/account/reset')
  }

  // ==================== 告警 ====================

  /** 条件告警列表 */
  async getAlerts() {
    return this._get('/api/v3/alerts')
  }

  /** 创建告警 */
  async createAlert(alert) {
    return this._post('/api/v3/alerts', alert)
  }

  /** 删除告警 */
  async deleteAlert(alertId) {
    return this._delete(`/api/v3/alerts/${alertId}`)
  }

  // ==================== 画图持久化 ====================

  /** 批量存储画图 */
  async saveDrawings(symbol, drawings) {
    return this._post('/api/v3/drawings/batch', { symbol, drawings })
  }

  /** 读取画图 */
  async loadDrawings(symbol) {
    return this._get('/api/v3/drawings/load', { symbol })
  }

  // ==================== Dashboard 专用 ====================

  /** 仪表盘 - 自选股概览数据 */
  async getWatchlistData() {
    return this._get('/api/v3/watchlist/dashboard')
  }

  /** 仪表盘 - 市场概况 */
  async getMarketOverview() {
    return this._get('/api/v3/market/overview')
  }

  /** 仪表盘 - 策略信号摘要 */
  async getStrategySignals() {
    return this._get('/api/v3/signals/summary')
  }

  /** 仪表盘 - AI 分析信号摘要 */
  async getAIAnalysisSignals() {
    return this._get('/api/v3/ai-analysis/signals')
  }


  // ==================== 内部方法 ====================

  async _get(endpoint, params = {}, options = {}) {
    try {
      const res = await dedupedRequest(`${this._baseURL}${endpoint}`, params, {
        ...options,
        dedupe: options.dedupe !== false,
      })
      // 兼容不同响应格式
      return this._unwrap(res)
    } catch (err) {
      message.error(`请求失败: ${endpoint}`)
      throw err
    }
  }

  async _post(endpoint, data = {}) {
    try {
      // using configured request instance
      const res = await request.post(`${this._baseURL}${endpoint}`, data, {
        timeout: 30000,
      })
      return this._unwrap(res)
    } catch (err) {
      message.error(`请求失败: ${endpoint}`)
      throw err
    }
  }

  async _put(endpoint, data = {}) {
    try {
      // using configured request instance
      const res = await request.put(`${this._baseURL}${endpoint}`, data, {
        timeout: 30000,
      })
      return this._unwrap(res)
    } catch (err) {
      throw err
    }
  }

  async _delete(endpoint) {
    try {
      // using configured request instance
      const res = await request.delete(`${this._baseURL}${endpoint}`, {
        timeout: 10000,
      })
      return this._unwrap(res)
    } catch (err) {
      throw err
    }
  }

  _unwrap(res) {
    if (!res) return null
    if (res.code === 1 || res.code === 200) return res.data !== undefined ? res.data : res
    if (res.success === true) return res.data !== undefined ? res.data : res
    if (res.code === undefined && res.success === undefined) return res
    if (res.code && res.code !== 1 && res.code !== 200) {
      throw new Error(res.msg || res.message || '请求失败')
    }
    return res
  }

  /** 清除缓存 */
  clearCache(endpointPrefix) {
    clearCache(endpointPrefix ? `${this._baseURL}${endpointPrefix}` : undefined)
  }
}

// 全局单例
const dataService = new DataService()
export default dataService
export { DataService }
