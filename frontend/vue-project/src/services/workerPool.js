/**
 * Web Worker 计算池
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §2.1
 * 浏览器后台线程池，并行计算不阻塞 UI 线程
 */

class WorkerPool {
  /**
   * @param {number} workerCount - Worker 数量（默认使用硬件并发数）
   */
  constructor(workerCount) {
    this.workerCount = workerCount || navigator.hardwareConcurrency || 4
    /** @type {Array<{worker: Worker, busy: boolean}>} */
    this.workers = []
    /** @type {Array<{id: number, type: string, data: any, priority: string, resolve: Function, reject: Function}>} */
    this.taskQueue = []
    /** @type {Map<number, {resolve: Function, reject: Function}>} */
    this.pendingTasks = new Map()
    this.taskId = 0
    this._initialized = false
    this._workerErrors = 0
    this._maxWorkerErrors = 5
  }

  /**
   * 初始化 Worker 池
   */
  init() {
    if (this._initialized) return

    for (let i = 0; i < this.workerCount; i++) {
      this._createWorker(i)
    }

    this._initialized = true
    console.log(`[WorkerPool] 初始化完成: ${this.workerCount} 个 Worker`)
  }

  _createWorker(index) {
    try {
      const worker = new Worker(
        new URL('../workers/indicatorWorker.js', import.meta.url),
        { type: 'module' }
      )

      worker.onmessage = (e) => this._handleResult(e, worker)
      worker.onerror = (err) => this._handleWorkerError(index, err)

      this.workers.push({ worker, busy: false })
    } catch (err) {
      console.error(`[WorkerPool] Worker ${index} 创建失败:`, err)
      // 回退：减少 Worker 数量
      if (this.workers.length === 0) {
        // 零 Worker → 后续计算在主线程进行
        console.warn('[WorkerPool] 回退到主线程计算模式')
      }
    }
  }

  /**
   * 提交计算任务
   *
   * @param {string} type - 任务类型 ('indicator' | 'batch' | 'ping')
   * @param {object} data - 任务数据
   * @param {'high'|'normal'|'low'} priority - 优先级
   * @returns {Promise<any>}
   */
  submit(type, data, priority = 'normal') {
    if (!this._initialized) {
      this.init()
    }

    return new Promise((resolve, reject) => {
      const task = {
        id: ++this.taskId,
        type,
        data,
        priority,
        resolve,
        reject,
      }
      this.taskQueue.push(task)
      this._schedule()
    })
  }

  /**
   * 调度：按优先级排序 + 分配空闲 Worker
   */
  _schedule() {
    // 按优先级排序
    const prio = { high: 0, normal: 1, low: 2 }
    this.taskQueue.sort((a, b) => prio[a.priority] - prio[b.priority])

    for (const entry of this.workers) {
      if (!entry.busy && this.taskQueue.length > 0) {
        const task = this.taskQueue.shift()
        entry.busy = true
        this.pendingTasks.set(task.id, task)

        try {
          entry.worker.postMessage({
            id: task.id,
            type: task.type,
            data: task.data,
          })
        } catch (err) {
          entry.busy = false
          this.pendingTasks.delete(task.id)
          task.reject(err)
        }
      }
    }
  }

  _handleResult(e, worker) {
    const { id, result, error } = e.data

    // Worker 就绪消息
    if (id === undefined && e.data.type === 'ready') {
      return
    }

    const task = this.pendingTasks.get(id)
    if (task) {
      if (error) {
        task.reject(new Error(error))
      } else {
        task.resolve(result)
      }
      this.pendingTasks.delete(id)
    }

    // 释放 Worker
    const entry = this.workers.find((w) => w.worker === worker)
    if (entry) {
      entry.busy = false
    }

    // 继续调度
    this._schedule()
  }

  _handleWorkerError(index, err) {
    this._workerErrors++
    console.error(`[WorkerPool] Worker ${index} 错误:`, err)

    if (this._workerErrors >= this._maxWorkerErrors) {
      console.warn('[WorkerPool] Worker 错误过多，停止重试')
      return
    }

    // 重建 Worker
    const entry = this.workers[index]
    if (entry) {
      try {
        entry.worker.terminate()
        this._createWorker(index)
        this.workers[index] = this.workers.pop()
      } catch {
        // 静默
      }
    }
  }

  /**
   * 批量计算多个指标
   *
   * @param {Array<{name: string, params?: object}>} indicators
   * @param {Array<object>} klineData
   * @returns {Promise<object>}
   */
  async calculateIndicators(indicators, klineData) {
    return this.submit('batch', { indicators, klineData }, 'normal')
  }

  /**
   * 计算单个指标
   */
  async calculateIndicator(indicator, params, klineData) {
    return this.submit('indicator', { indicator, params, klineData }, 'normal')
  }

  /**
   * 获取 Worker 池状态
   */
  getStatus() {
    return {
      total: this.workers.length,
      busy: this.workers.filter((w) => w.busy).length,
      idle: this.workers.filter((w) => !w.busy).length,
      pending: this.taskQueue.length,
      active: this.pendingTasks.size,
      initialized: this._initialized,
    }
  }

  /**
   * 终止所有 Worker（用于组件销毁）
   */
  terminate() {
    for (const entry of this.workers) {
      try {
        entry.worker.terminate()
      } catch {
        // 静默
      }
    }
    this.workers = []
    this.taskQueue = []
    this.pendingTasks.clear()
    this._initialized = false
    console.log('[WorkerPool] 已终止')
  }

  /**
   * 终止并重新初始化
   */
  restart() {
    this.terminate()
    this.init()
  }
}

// 全局单例
let _pool = null

export function getWorkerPool() {
  if (!_pool) {
    _pool = new WorkerPool()
  }
  return _pool
}

export function destroyWorkerPool() {
  if (_pool) {
    _pool.terminate()
    _pool = null
  }
}

export default WorkerPool
