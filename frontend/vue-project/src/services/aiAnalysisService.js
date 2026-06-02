import request from '@/utils/request'

/**
 * 开始 AI 分析
 */
export function startAnalysis(tsCode, stockName = '') {
  return request.post('/api/v3/ai/analyze', { ts_code: tsCode, stock_name: stockName })
}

/**
 * 获取分析进度
 */
export function getProgress(analysisId) {
  return request.get('/api/v3/ai/analyst-progress', { params: { analysis_id: analysisId } })
}

/**
 * 获取最终报告
 */
export function getFinalReport(analysisId) {
  return request.get('/api/v3/ai/final-report', { params: { analysis_id: analysisId } })
}

/**
 * 获取健康状态
 */
export function getAIHealth() {
  return request.get('/api/v3/ai/health')
}

/**
 * 获取信号 AI 解读
 * @param {string} tsCode - 股票代码
 * @param {string} stockName - 股票名称
 * @param {Array} signals - 信号列表（包含 strategy_name, confidence, evidence 等）
 */
export function explainSignal(tsCode, stockName, signals) {
  return request.post('/api/v3/ai/signal-explain', {
    ts_code: tsCode,
    stock_name: stockName,
    signals
  })
}
