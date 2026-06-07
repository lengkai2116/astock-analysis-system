/**
 * Web Worker — 指标计算
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §2.1
 * 在 Worker 线程中执行高频指标计算，不阻塞 UI 线程
 */

// ==================== 基础统计函数 ====================

function sma(data, period) {
  const result = new Array(data.length).fill(null)
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += data[j]
    result[i] = sum / period
  }
  return result
}

function ema(data, period) {
  const result = new Array(data.length).fill(null)
  if (data.length === 0) return result
  const k = 2 / (period + 1)
  result[0] = data[0]
  for (let i = 1; i < data.length; i++) {
    result[i] = data[i] * k + result[i - 1] * (1 - k)
  }
  return result
}

function rsi(data, period = 14) {
  const result = new Array(data.length).fill(null)
  if (data.length < period + 1) return result

  let gains = 0, losses = 0
  for (let i = 1; i <= period; i++) {
    const diff = data[i] - data[i - 1]
    if (diff >= 0) gains += diff
    else losses -= diff
  }

  let avgGain = gains / period
  let avgLoss = losses / period
  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)

  for (let i = period + 1; i < data.length; i++) {
    const diff = data[i] - data[i - 1]
    avgGain = (avgGain * (period - 1) + (diff > 0 ? diff : 0)) / period
    avgLoss = (avgLoss * (period - 1) + (diff < 0 ? -diff : 0)) / period
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }

  return result
}

function macd(data, fast = 12, slow = 26, signal = 9) {
  const emaFast = ema(data, fast)
  const emaSlow = ema(data, slow)
  const dif = emaFast.map((v, i) => v !== null && emaSlow[i] !== null ? v - emaSlow[i] : null)
  const dea = ema(dif.map(v => v || 0), signal)
  // 恢复 dea 中对应 dif 为 null 的位置
  for (let i = 0; i < dif.length; i++) {
    if (dif[i] === null) dea[i] = null
  }
  const macdBar = dif.map((v, i) => v !== null && dea[i] !== null ? (v - dea[i]) * 2 : null)
  return { dif, dea, macdBar }
}

function boll(data, period = 20, std = 2) {
  const mid = sma(data, period)
  const upper = new Array(data.length).fill(null)
  const lower = new Array(data.length).fill(null)

  for (let i = period - 1; i < data.length; i++) {
    if (mid[i] === null) continue
    let sumSq = 0
    for (let j = i - period + 1; j <= i; j++) sumSq += Math.pow(data[j] - mid[i], 2)
    const sigma = Math.sqrt(sumSq / period)
    upper[i] = mid[i] + std * sigma
    lower[i] = mid[i] - std * sigma
  }

  return { mid, upper, lower }
}

function kdj(high, low, close, n = 9, k = 3, d = 3) {
  const rsv = new Array(close.length).fill(null)
  const kValues = new Array(close.length).fill(null)
  const dValues = new Array(close.length).fill(null)

  for (let i = n - 1; i < close.length; i++) {
    let h = -Infinity, l = Infinity
    for (let j = i - n + 1; j <= i; j++) {
      if (high[j] > h) h = high[j]
      if (low[j] < l) l = low[j]
    }
    rsv[i] = h === l ? 50 : (close[i] - l) / (h - l) * 100
  }

  kValues[0] = 50
  dValues[0] = 50
  for (let i = 1; i < close.length; i++) {
    const r = rsv[i] !== null ? rsv[i] : 50
    kValues[i] = (2 / (k + 1)) * r + (1 - 2 / (k + 1)) * kValues[i - 1]
    dValues[i] = (2 / (d + 1)) * kValues[i] + (1 - 2 / (d + 1)) * dValues[i - 1]
  }

  // rsv 第一个有效位置之前不输出 K/D
  for (let i = 0; i < n - 1; i++) {
    kValues[i] = null
    dValues[i] = null
  }

  return { k: kValues, d: dValues, j: kValues.map((v, i) => v !== null ? 3 * v - 2 * dValues[i] : null) }
}

/** 简单移动汇总 */
function sum(data, period) {
  const result = new Array(data.length).fill(null)
  for (let i = period - 1; i < data.length; i++) {
    let s = 0
    for (let j = i - period + 1; j <= i; j++) s += data[j]
    result[i] = s
  }
  return result
}

/** 标准差 */
function stdev(data, period) {
  const result = new Array(data.length).fill(null)
  const means = sma(data, period)
  for (let i = period - 1; i < data.length; i++) {
    if (means[i] === null) continue
    let sumSq = 0
    for (let j = i - period + 1; j <= i; j++) sumSq += Math.pow(data[j] - means[i], 2)
    result[i] = Math.sqrt(sumSq / period)
  }
  return result
}

// ==================== 指标注册表 ====================

const INDICATOR_FUNCTIONS = {
  sma: (data, params) => sma(data.close, params.period || 20),
  ema: (data, params) => ema(data.close, params.period || 20),
  rsi: (data, params) => rsi(data.close, params.period || 14),
  macd: (data, params) => macd(data.close, params.fast || 12, params.slow || 26, params.signal || 9),
  boll: (data, params) => boll(data.close, params.period || 20, params.std || 2),
  kdj: (data, params) => kdj(data.high, data.low, data.close, params.n || 9, params.k || 3, params.d || 3),
  volume_sma: (data, params) => sma(data.volume, params.period || 5),
  volume_ratio: (data, params) => {
    const vol = data.volume
    const avgVol = sma(vol, params.period || 5)
    return vol.map((v, i) => avgVol[i] !== null && avgVol[i] > 0 ? v / avgVol[i] : null)
  },
  atr: (data, params) => {
    const period = params.period || 14
    const tr = new Array(data.high.length).fill(null)
    for (let i = 1; i < data.high.length; i++) {
      tr[i] = Math.max(
        data.high[i] - data.low[i],
        Math.abs(data.high[i] - data.close[i - 1]),
        Math.abs(data.low[i] - data.close[i - 1])
      )
    }
    return ema(tr.map(v => v || 0), period)
  },
  stoch: (data, params) => {
    // 随机指标（简化 KDJ 的 K 值）
    const result = kdj(data.high, data.low, data.close, params.n || 14, 1, 3)
    return result.k
  },
  williams_r: (data, params) => {
    const period = params.period || 14
    const result = new Array(data.high.length).fill(null)
    for (let i = period - 1; i < data.high.length; i++) {
      let h = -Infinity, l = Infinity
      for (let j = i - period + 1; j <= i; j++) {
        if (data.high[j] > h) h = data.high[j]
        if (data.low[j] < l) l = data.low[j]
      }
      result[i] = h === l ? -50 : (h - data.close[i]) / (h - l) * -100
    }
    return result
  },
  obv: (data, _params) => {
    const result = new Array(data.close.length).fill(null)
    result[0] = 0
    for (let i = 1; i < data.close.length; i++) {
      if (data.close[i] > data.close[i - 1]) {
        result[i] = result[i - 1] + (data.volume[i] || 0)
      } else if (data.close[i] < data.close[i - 1]) {
        result[i] = result[i - 1] - (data.volume[i] || 0)
      } else {
        result[i] = result[i - 1]
      }
    }
    return result
  },
}

// ==================== Worker 消息处理 ====================

self.onmessage = function (e) {
  const { id, type, data } = e.data

  try {
    if (type === 'indicator') {
      const { indicator, params, klineData } = data

      if (!INDICATOR_FUNCTIONS[indicator]) {
        self.postMessage({ id, error: `未知指标: ${indicator}` })
        return
      }

      // 准备 OHLCV 数据
      const prepared = {
        open: klineData.map((k) => k.open),
        high: klineData.map((k) => k.high),
        low: klineData.map((k) => k.low),
        close: klineData.map((k) => k.close),
        volume: klineData.map((k) => k.volume || k.vol || 0),
        tradeDate: klineData.map((k) => k.tradeDate || k.trade_date || ''),
      }

      const result = INDICATOR_FUNCTIONS[indicator](prepared, params || {})

      // 包装结果：保证与原始 K 线长度一致
      const wrapped = {
        indicator,
        params: params || {},
        values: result,
        length: klineData.length,
        dates: prepared.tradeDate,
      }

      self.postMessage({ id, result: wrapped })
    } else if (type === 'batch') {
      // 批量计算多个指标
      const { indicators, klineData } = data
      const results = {}

      const prepared = {
        open: klineData.map((k) => k.open),
        high: klineData.map((k) => k.high),
        low: klineData.map((k) => k.low),
        close: klineData.map((k) => k.close),
        volume: klineData.map((k) => k.volume || k.vol || 0),
        tradeDate: klineData.map((k) => k.tradeDate || k.trade_date || ''),
      }

      for (const ind of indicators) {
        if (INDICATOR_FUNCTIONS[ind.name]) {
          results[ind.name] = INDICATOR_FUNCTIONS[ind.name](prepared, ind.params || {})
        }
      }

      self.postMessage({
        id,
        result: {
          indicators: results,
          count: Object.keys(results).length,
          length: klineData.length,
        },
      })
    } else if (type === 'ping') {
      self.postMessage({ id, result: 'pong' })
    } else {
      self.postMessage({ id, error: `未知任务类型: ${type}` })
    }
  } catch (err) {
    self.postMessage({ id, error: err.message })
  }
}

// 通知主线程 Worker 已就绪
self.postMessage({ type: 'ready', workerId: `worker-${Date.now()}` })
