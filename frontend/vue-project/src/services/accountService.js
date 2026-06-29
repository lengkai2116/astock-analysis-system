/**
 * 账户管理与复盘 API 服务 (P3)
 */
import request from '@/utils/request'

const BASE = '/api/v1/account'

// ── 交易记录 ──

export function getTrades(params = {}) {
  return request.get(`${BASE}/trades`, { params })
}

export function createTrade(data) {
  return request.post(`${BASE}/trades`, data)
}

export function updateTrade(id, data) {
  return request.put(`${BASE}/trades/${id}`, data)
}

export function deleteTrade(id) {
  return request.delete(`${BASE}/trades/${id}`)
}

export function importTrades(trades) {
  return request.post(`${BASE}/trades/import`, { trades })
}

export function matchTrades() {
  return request.post(`${BASE}/trades/match`)
}

// ── 持仓/总览 ──

export function getPositions() {
  return request.get(`${BASE}/positions`)
}

export function getAccountSummary() {
  return request.get(`${BASE}/summary`)
}

// ── 资金曲线/绩效 ──

export function getEquityCurve(days = 365) {
  return request.get(`${BASE}/equity-curve`, { params: { days } })
}

export function getPerformance() {
  return request.get(`${BASE}/performance`)
}

// ── 复盘 ──

export function runReview(startDate, endDate, format = 'json') {
  return request.post(`${BASE}/review`, { start_date: startDate, end_date: endDate, format })
}

export function exportReview(startDate, endDate) {
  return request.post(`${BASE}/review/export`, { start_date: startDate, end_date: endDate })
}

// ── 策略沙箱（原虚拟验证）— 待废弃，复盘中心已替代 ──

export function getVirtualReviews() {
  return request.get(`${BASE}/virtual-reviews`)
}

export default {
  getTrades, createTrade, updateTrade, deleteTrade, importTrades, matchTrades,
  getPositions, getAccountSummary, getEquityCurve, getPerformance,
  runReview, exportReview, getVirtualReviews,
}
