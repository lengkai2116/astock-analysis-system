/**
 * 请求去重与防抖工具
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §5.3
 * 解决 K 线缩放时重复请求的问题
 */
import request from './request'

// 全局去重表：url|params → Promise
const pendingRequests = new Map()
// 内存缓存：url|params → { data, ts }
const responseCache = new Map()

/**
 * 带去重和缓存的请求
 *
 * @param {string} url - API 端点
 * @param {object} params - 请求参数
 * @param {object} options
 * @param {boolean} options.dedupe - 是否去重（默认 true）
 * @param {boolean} options.cache - 是否缓存（默认 false）
 * @param {number} options.cacheTTL - 缓存有效期 ms（默认 5000）
 * @param {number} options.timeout - 超时 ms（默认 30000）
 * @returns {Promise<any>}
 */
export async function dedupedRequest(url, params = {}, options = {}) {
  const {
    dedupe = true,
    cache = false,
    cacheTTL = 5000,
    timeout = 30000,
  } = options

  const key = `${url}|${JSON.stringify(params)}`

  // 缓存命中
  if (cache && responseCache.has(key)) {
    const entry = responseCache.get(key)
    if (Date.now() - entry.ts < cacheTTL) {
      return entry.data
    }
    responseCache.delete(key)
  }

  // 去重：相同请求未完成时复用
  if (dedupe && pendingRequests.has(key)) {
    return pendingRequests.get(key)
  }

  const promise = request.get(url, { params, timeout }).then((r) => {
    const data = r.data
    if (cache) {
      responseCache.set(key, { data, ts: Date.now() })
    }
    return data
  })

  if (dedupe) {
    pendingRequests.set(key, promise)
    promise.finally(() => pendingRequests.delete(key))
  }

  return promise
}

/**
 * 批量请求
 */
export async function batchRequests(requests) {
  return Promise.all(
    requests.map((r) => dedupedRequest(r.url, r.params, r.options))
  )
}

/**
 * 清除指定 URL 的缓存
 */
export function clearCache(urlPrefix) {
  if (urlPrefix) {
    for (const key of responseCache.keys()) {
      if (key.startsWith(urlPrefix)) {
        responseCache.delete(key)
      }
    }
  } else {
    responseCache.clear()
    pendingRequests.forEach((p) => p.finally && p.finally())
    pendingRequests.clear()
  }
}

/**
 * 防抖：延迟执行，重复调用重置计时器
 * @param {Function} fn
 * @param {number} delay ms
 * @returns {Function}
 */
export function debounce(fn, delay = 300) {
  let timer = null
  return function (...args) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      fn.apply(this, args)
      timer = null
    }, delay)
  }
}

/**
 * 节流：固定频率执行
 * @param {Function} fn
 * @param {number} interval ms
 * @returns {Function}
 */
export function throttle(fn, interval = 500) {
  let last = 0
  return function (...args) {
    const now = Date.now()
    if (now - last >= interval) {
      last = now
      fn.apply(this, args)
    }
  }
}

export default { dedupedRequest, batchRequests, clearCache, debounce, throttle }
