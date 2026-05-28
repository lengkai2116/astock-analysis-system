/**
 * K线图表数据服务
 * 对接后端 /api/v3/chart/ 路由
 */
import axios from '@/utils/request'

/**
 * 获取 K 线数据（含叠加指标 + 副图指标）
 * @param {string} tsCode - 股票代码
 * @param {string} indicators - 逗号分隔的指标名列表，如 'ma5,ma20,macd,rsi,kdj'
 * @param {string} period - 周期：D / W / M
 * @param {number} limit - 数据条数
 * @returns {Promise<{kline, overlays, subcharts, stock}>}
 */
export async function fetchKlineData(tsCode, indicators = 'ma5,ma20,macd,rsi,kdj', period = 'D', limit = 200) {
  try {
    const res = await axios.get(`/api/v3/chart/kline/${tsCode}`, {
      params: { indicators, period, limit }
    })
    if (res.success && res.data) {
      // 将后端 tradingview 风格数据转为 klinecharts 格式
      const kline = (res.data.kline || []).map(item => ({
        timestamp: item.time,     // 后端返回的是秒级 unix timestamp
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close,
        volume: item.volume || 0
      }))
      return {
        kline,
        overlays: res.data.overlays || [],
        subcharts: res.data.subcharts || [],
        signals: res.data.signals || [],
        stock: res.data.stock || {}
      }
    }
    return { kline: [], overlays: [], subcharts: [], signals: [], stock: {} }
  } catch (err) {
    console.error('获取 K 线数据失败:', err)
    return { kline: [], overlays: [], subcharts: [], signals: [], stock: {} }
  }
}

/**
 * 获取 B/S 信号标记
 * @param {string} tsCode
 * @param {number} limit
 * @returns {Promise<Array>}
 */
export async function fetchSignals(tsCode, limit = 100) {
  try {
    const res = await axios.get(`/api/v3/chart/signals/${tsCode}`, {
      params: { limit }
    })
    if (res.success && res.data) {
      return res.data.map(s => ({
        timestamp: s.time,
        type: s.type,       // 'buy' | 'sell'
        price: s.price,
        text: s.text,
        color: s.color
      }))
    }
    return []
  } catch (err) {
    console.error('获取信号数据失败:', err)
    return []
  }
}

/**
 * 获取可用指标列表
 * @returns {Promise<{overlays, subcharts}>}
 */
export async function fetchIndicatorList() {
  try {
    const res = await axios.get('/api/v3/chart/indicators')
    if (res.success && res.data) {
      return res.data
    }
    return { overlays: [], subcharts: [] }
  } catch (err) {
    console.error('获取指标列表失败:', err)
    return { overlays: [], subcharts: [] }
  }
}

/**
 * 搜索股票
 * @param {string} keyword
 * @param {number} limit
 * @returns {Promise<Array>}
 */
export async function searchStocks(keyword, limit = 20) {
  try {
    const res = await axios.get('/api/v3/chart/stock-list', {
      params: { keyword, limit }
    })
    if (res.success && res.data) {
      return res.data
    }
    return []
  } catch (err) {
    console.error('搜索股票失败:', err)
    return []
  }
}

export default {
  fetchKlineData,
  fetchSignals,
  fetchIndicatorList,
  searchStocks
}
