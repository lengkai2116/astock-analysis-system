/**
 * 统一指标计算引擎
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §2.2
 * 封装 WorkerPool，提供上层 API 给 KLineChart 等组件使用
 */

import { getWorkerPool } from './workerPool'

class IndicatorEngine {
  constructor() {
    this._pool = null
    this._cache = new Map()
  }

  get pool() {
    if (!this._pool) {
      this._pool = getWorkerPool()
    }
    return this._pool
  }

  /**
   * 计算单个指标
   */
  async calculate(indicator, klineData, params = {}) {
    if (!klineData || klineData.length === 0) {
      return null
    }

    const cacheKey = `${indicator}|${JSON.stringify(params)}|${klineData.length}`
    if (this._cache.has(cacheKey)) {
      return this._cache.get(cacheKey)
    }

    const result = await this.pool.calculateIndicator(indicator, params, klineData)
    this._cache.set(cacheKey, result)
    return result
  }

  /**
   * 批量计算多个指标（单次 Worker 调用）
   */
  async calculateBatch(indicators, klineData) {
    if (!klineData || klineData.length === 0) {
      return {}
    }

    const result = await this.pool.calculateIndicators(indicators, klineData)
    return result.indicators || {}
  }

  /**
   * 计算 K 线图常用指标组合（MA + MACD + RSI + BOLL）
   */
  async calculateChartPreset(klineData) {
    return this.calculateBatch(
      [
        { name: 'sma', params: { period: 5 } },
        { name: 'sma', params: { period: 10 } },
        { name: 'sma', params: { period: 20 } },
        { name: 'sma', params: { period: 60 } },
        { name: 'macd', params: { fast: 12, slow: 26, signal: 9 } },
        { name: 'rsi', params: { period: 14 } },
        { name: 'boll', params: { period: 20, std: 2 } },
        { name: 'volume_sma', params: { period: 5 } },
        { name: 'volume_ratio', params: { period: 5 } },
      ],
      klineData
    )
  }

  /** 清除缓存 */
  clearCache() {
    this._cache.clear()
  }

  /** 获取缓存统计 */
  getCacheStats() {
    return { size: this._cache.size }
  }
}

// 全局单例
const indicatorEngine = new IndicatorEngine()
export default indicatorEngine
export { IndicatorEngine }
