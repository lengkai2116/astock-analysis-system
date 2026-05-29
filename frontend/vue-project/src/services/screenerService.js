/**
 * 三层策略筛选器 API 服务
 * 对接后端筛选器路由，支持全市场股票批量筛选
 */
import axios from '@/utils/request'

const API_BASE = '/api/v3/screener'

/**
 * 执行完整的三层筛选流程
 * @param {Object} options - 筛选参数
 * @param {Array} options.stockPool - 股票池列表（可选，不传则全市场）
 * @param {Object} options.filters - 各层筛选参数
 * @returns {Promise<{ layers, results, summary }>}
 */
export async function runScreener(options = {}) {
  try {
    const res = await axios.post(`${API_BASE}/run`, options, { timeout: 300000 })
    if (res.success && res.data) return res.data
    return { layers: [], results: [], summary: {} }
  } catch (err) {
    console.error('筛选器执行失败:', err)
    return { layers: [], results: [], summary: {} }
  }
}

/**
 * 仅执行第一层：风险剔除
 * @param {Array} stockPool
 * @param {Object} params - 筛选参数阈值
 * @returns {Promise<Object>}
 */
export async function runLayer1(stockPool, params = {}) {
  try {
    const res = await axios.post(`${API_BASE}/layer1`, { stock_pool: stockPool, params })
    return res.success ? res.data : { passed: [], filtered: 0 }
  } catch (err) {
    console.error('Layer1 执行失败:', err)
    return { passed: [], filtered: 0 }
  }
}

/**
 * 仅执行第二层：主力识别
 * @param {Array} stockPool
 * @param {Object} params
 * @returns {Promise<Object>}
 */
export async function runLayer2(stockPool, params = {}) {
  try {
    const res = await axios.post(`${API_BASE}/layer2`, { stock_pool: stockPool, params })
    return res.success ? res.data : { passed: [], scored: [] }
  } catch (err) {
    console.error('Layer2 执行失败:', err)
    return { passed: [], scored: [] }
  }
}

/**
 * 仅执行第三层：策略验证
 * @param {Array} candidates - 候选股票列表
 * @param {Object} params
 * @returns {Promise<Object>}
 */
export async function runLayer3(candidates, params = {}) {
  try {
    const res = await axios.post(`${API_BASE}/layer3`, { candidates, params })
    return res.success ? res.data : { validated: [] }
  } catch (err) {
    console.error('Layer3 执行失败:', err)
    return { validated: [] }
  }
}

/**
 * 获取当前信号融合权重配置
 * @returns {Promise<Object>}
 */
export async function getFusionConfig() {
  try {
    const res = await axios.get(`${API_BASE}/fusion-config`)
    if (res.success && res.data) return res.data
    return null
  } catch (err) {
    console.error('获取融合配置失败:', err)
    return null
  }
}

/**
 * 更新信号融合权重配置
 * @param {Object} config - { weights: { chip: 0.4, chanlun: 0.3, factor: 0.3 }, phase_bonus: { building: 2, washing: 1 } }
 * @returns {Promise<boolean>}
 */
export async function updateFusionConfig(config) {
  try {
    const res = await axios.post(`${API_BASE}/fusion-config`, config)
    return res.success === true
  } catch (err) {
    console.error('更新融合配置失败:', err)
    return false
  }
}

/**
 * 获取可用筛选器参数范围
 * @returns {Promise<Object>}
 */
export async function getScreenerParams() {
  try {
    const res = await axios.get(`${API_BASE}/params`)
    if (res.success && res.data) return res.data
    return { layers: {} }
  } catch (err) {
    console.error('获取筛选参数失败:', err)
    return { layers: {} }
  }
}

export default {
  runScreener,
  runLayer1,
  runLayer2,
  runLayer3,
  getFusionConfig,
  updateFusionConfig,
  getScreenerParams
}
