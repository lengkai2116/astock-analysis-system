/**
 * IndexedDB 前端数据级联缓存
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §4.2
 * 为 K 线数据、指标计算结果、自选股、画图数据提供持久化缓存
 */

const DB_NAME = 'a-stock-cache'
const DB_VERSION = 2

/** 存储桶定义 */
export const STORES = {
  KLINES: 'klines',
  INDICATORS: 'indicators',
  WATCHLIST: 'watchlist',
  DRAWINGS: 'drawings',
  PREFERENCES: 'preferences',
}

class IndexedDBCache {
  constructor() {
    this._db = null
    this._openPromise = null
  }

  /**
   * 打开/获取数据库连接（单例）
   */
  async open() {
    if (this._db) return this._db
    if (this._openPromise) return this._openPromise

    this._openPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION)

      request.onupgradeneeded = (e) => {
        const db = e.target.result
        const oldVersion = e.oldVersion

        // v1: 基础存储
        if (oldVersion < 1) {
          if (!db.objectStoreNames.contains(STORES.KLINES)) {
            const store = db.createObjectStore(STORES.KLINES, { keyPath: 'cacheKey' })
            store.createIndex('symbol', 'symbol', { unique: false })
            store.createIndex('expires', 'expires', { unique: false })
          }
          if (!db.objectStoreNames.contains(STORES.INDICATORS)) {
            db.createObjectStore(STORES.INDICATORS, { keyPath: 'cacheKey' })
          }
          if (!db.objectStoreNames.contains(STORES.WATCHLIST)) {
            db.createObjectStore(STORES.WATCHLIST, { keyPath: 'id' })
          }
          if (!db.objectStoreNames.contains(STORES.DRAWINGS)) {
            db.createObjectStore(STORES.DRAWINGS, { keyPath: 'id' })
          }
          if (!db.objectStoreNames.contains(STORES.PREFERENCES)) {
            db.createObjectStore(STORES.PREFERENCES, { keyPath: 'key' })
          }
        }

        // v2: 为 klines 增加 period 索引
        if (oldVersion < 2) {
          if (db.objectStoreNames.contains(STORES.KLINES)) {
            const tx = e.target.transaction
            const store = tx.objectStore(STORES.KLINES)
            if (!store.indexNames.contains('period')) {
              store.createIndex('period', 'period', { unique: false })
            }
          }
        }
      }

      request.onsuccess = () => {
        this._db = request.result
        this._db.onversionchange = () => {
          this._db.close()
          this._db = null
          this._openPromise = null
        }
        resolve(this._db)
      }

      request.onerror = () => {
        this._openPromise = null
        reject(request.error)
      }
    })

    return this._openPromise
  }

  /**
   * 写入缓存
   * @param {string} storeName
   * @param {string} key - 缓存键
   * @param {*} data - 数据
   * @param {number} ttlSeconds - 过期时间（秒），默认 300（5分钟）
   */
  async set(storeName, key, data, ttlSeconds = 300) {
    try {
      const db = await this.open()
      const tx = db.transaction(storeName, 'readwrite')
      const store = tx.objectStore(storeName)
      const record = {
        cacheKey: key,
        data,
        expires: Date.now() + ttlSeconds * 1000,
        updatedAt: Date.now(),
      }
      store.put(record)
      await new Promise((resolve, reject) => {
        tx.oncomplete = resolve
        tx.onerror = () => reject(tx.error)
      })
    } catch (err) {
      console.warn('[IndexedDBCache] set error:', err)
    }
  }

  /**
   * 读取缓存
   * @param {string} storeName
   * @param {string} key
   * @returns {*|null} 过期或不存在返回 null
   */
  async get(storeName, key) {
    try {
      const db = await this.open()
      const tx = db.transaction(storeName, 'readonly')
      const store = tx.objectStore(storeName)
      const result = await new Promise((resolve, reject) => {
        const req = store.get(key)
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
      })

      if (!result) return null
      if (result.expires < Date.now()) {
        // 惰性过期：后台删除，不阻塞读取
        this.delete(storeName, key)
        return null
      }
      return result.data
    } catch (err) {
      console.warn('[IndexedDBCache] get error:', err)
      return null
    }
  }

  /**
   * 删除单条缓存
   */
  async delete(storeName, key) {
    try {
      const db = await this.open()
      const tx = db.transaction(storeName, 'readwrite')
      tx.objectStore(storeName).delete(key)
    } catch (err) {
      // 静默
    }
  }

  /**
   * 按 symbol 查询 K 线缓存
   */
  async getKlinesBySymbol(symbol) {
    try {
      const db = await this.open()
      const tx = db.transaction(STORES.KLINES, 'readonly')
      const store = tx.objectStore(STORES.KLINES)
      const index = store.index('symbol')
      const results = await new Promise((resolve, reject) => {
        const req = index.getAll(symbol)
        req.onsuccess = () => resolve(req.result || [])
        req.onerror = () => reject(req.error)
      })
      // 过滤过期
      const now = Date.now()
      return results.filter((r) => r.expires > now).map((r) => r.data)
    } catch {
      return []
    }
  }

  /**
   * 清除指定 store 的过期数据
   */
  async purgeExpired(storeName) {
    try {
      const db = await this.open()
      const tx = db.transaction(storeName, 'readwrite')
      const store = tx.objectStore(storeName)
      const all = await new Promise((resolve, reject) => {
        const req = store.getAll()
        req.onsuccess = () => resolve(req.result || [])
        req.onerror = () => reject(req.error)
      })
      const now = Date.now()
      let count = 0
      for (const record of all) {
        if (record.expires && record.expires < now) {
          store.delete(record.cacheKey || record.id || record.key)
          count++
        }
      }
      if (count > 0) {
        console.log(`[IndexedDBCache] Purged ${count} expired entries from ${storeName}`)
      }
      return count
    } catch {
      return 0
    }
  }

  /**
   * 清除全部缓存
   */
  async clear() {
    try {
      const db = await this.open()
      const storeNames = Object.values(STORES)
      for (const name of storeNames) {
        const tx = db.transaction(name, 'readwrite')
        tx.objectStore(name).clear()
        await new Promise((resolve, reject) => {
          tx.oncomplete = resolve
          tx.onerror = () => reject(tx.error)
        })
      }
      console.log('[IndexedDBCache] All stores cleared')
    } catch (err) {
      console.warn('[IndexedDBCache] clear error:', err)
    }
  }

  /**
   * 获取缓存统计
   */
  async getStats() {
    const stats = {}
    try {
      const db = await this.open()
      for (const [key, name] of Object.entries(STORES)) {
        const tx = db.transaction(name, 'readonly')
        const store = tx.objectStore(name)
        const count = await new Promise((resolve) => {
          const req = store.count()
          req.onsuccess = () => resolve(req.result)
          req.onerror = () => resolve(0)
        })
        stats[key] = count
      }
    } catch {
      // 静默
    }
    return stats
  }
}

// 全局单例
export const cacheService = new IndexedDBCache()

export default cacheService
