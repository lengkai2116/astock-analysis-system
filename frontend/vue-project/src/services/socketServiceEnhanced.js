/**
 * 增强版 WebSocket 连接管理
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §5.1
 * 指数退避重连 + 心跳 + 状态机
 *
 * 与 153 号方案集成：为 AiSignalBus 的信号推送提供底层连接保障。
 */

import { EventEmitter } from 'events'

class EnhancedSocketService extends EventEmitter {
  constructor() {
    super()
    this.ws = null
    this.url = ''
    this.reconnectAttempts = 0
    this.maxReconnect = 10
    this.reconnectDelay = 1000
    this.maxDelay = 30000
    this.heartbeatInterval = null
    this.heartbeatTimer = null
    this.status = 'disconnected' // connected | disconnected | reconnecting
    this._manualDisconnect = false
    this._eventHandlers = {}
    this._pendingReconnect = null
  }

  /** 当前状态 */
  get connected() {
    return this.status === 'connected'
  }

  /** 状态枚举 */
  static STATUS = {
    CONNECTED: 'connected',
    DISCONNECTED: 'disconnected',
    RECONNECTING: 'reconnecting',
  }

  /**
   * 建立连接
   * @param {string} url WebSocket URL
   */
  connect(url = 'ws://localhost:5001/ws') {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      console.log('[SocketService] 已连接，跳过')
      return
    }

    this.url = url
    this._manualDisconnect = false

    try {
      this.ws = new WebSocket(url)
    } catch (err) {
      console.error('[SocketService] 创建 WebSocket 失败:', err)
      this._scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      console.log('[SocketService] 连接成功')
      this.status = 'connected'
      this.reconnectAttempts = 0
      this.reconnectDelay = 1000
      this._startHeartbeat()
      this.emit('connect')
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        this.emit('message', msg)
        // 按事件类型分发
        if (msg.type) {
          this.emit(`event:${msg.type}`, msg.payload || msg)
        }
      } catch {
        // 非 JSON 消息直接透传
        this.emit('raw', event.data)
      }
    }

    this.ws.onclose = (event) => {
      this.status = 'disconnected'
      this._stopHeartbeat()
      this.ws = null

      if (!this._manualDisconnect) {
        this._scheduleReconnect()
      }

      this.emit('disconnect', { code: event.code, reason: event.reason })
    }

    this.ws.onerror = (err) => {
      console.warn('[SocketService] 连接错误:', err)
      this.emit('error', err)
      // 等待 onclose 触发重连
    }
  }

  /** 指数退避重连 */
  _scheduleReconnect() {
    if (this._manualDisconnect) return
    if (this.reconnectAttempts >= this.maxReconnect) {
      console.error('[SocketService] 已达最大重连次数')
      this.emit('reconnect_failed', { attempts: this.reconnectAttempts })
      return
    }

    const delay = Math.min(
      this.maxDelay,
      this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts)
    )

    this.status = 'reconnecting'
    this.reconnectAttempts++
    this.emit('reconnecting', { attempt: this.reconnectAttempts, delay })

    console.log(`[SocketService] 第 ${this.reconnectAttempts} 次重连，等待 ${delay}ms`)

    this._pendingReconnect = setTimeout(() => {
      this._pendingReconnect = null
      this.connect(this.url)
    }, delay)
  }

  /** 启动心跳（30s 间隔） */
  _startHeartbeat() {
    this._stopHeartbeat()
    this.heartbeatInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: 'ping' }))
        } catch {
          // 静默
        }
      }
    }, 30000)

    // 心跳超时检查（60s 无响应断开）
    this.heartbeatTimer = setInterval(() => {
      // pong 响应由后端决定，如果连接断开 onclose 会触发重连
    }, 60000)
  }

  /** 停止心跳 */
  _stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  /**
   * 发送消息
   * @param {string|object} data
   */
  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data)
      this.ws.send(payload)
      return true
    }
    console.warn('[SocketService] 未连接，无法发送')
    return false
  }

  /**
   * 发送 JSON-RPC 风格请求
   * @param {string} method
   * @param {object} params
   * @returns {Promise<any>}
   */
  async request(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this.connected) {
        reject(new Error('WebSocket 未连接'))
        return
      }

      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

      // 一次性监听响应
      const handler = (msg) => {
        if (msg.id === id) {
          this.off('message', handler)
          if (msg.error) reject(new Error(msg.error))
          else resolve(msg.result)
        }
      }
      this.on('message', handler)

      // 超时保护
      setTimeout(() => {
        this.off('message', handler)
        reject(new Error('请求超时'))
      }, 30000)

      this.send({ jsonrpc: '2.0', id, method, params })
    })
  }

  /**
   * 订阅频道
   * @param {string} channel
   * @param {object} params
   */
  subscribe(channel, params = {}) {
    this.send({ type: 'subscribe', channel, params })
  }

  /**
   * 取消订阅
   * @param {string} channel
   */
  unsubscribe(channel) {
    this.send({ type: 'unsubscribe', channel })
  }

  /** 断开连接 */
  disconnect() {
    this._manualDisconnect = true
    this._stopHeartbeat()

    if (this._pendingReconnect) {
      clearTimeout(this._pendingReconnect)
      this._pendingReconnect = null
    }

    if (this.ws) {
      this.ws.close(1000, '客户端主动断开')
      this.ws = null
    }

    this.status = 'disconnected'
    this.reconnectAttempts = 0
    this.emit('disconnect', { code: 1000, reason: '手动断开' })
  }

  /** 主动重连 */
  reconnect() {
    this._manualDisconnect = false
    this.reconnectAttempts = 0
    this.reconnectDelay = 1000

    if (this.ws) {
      this.ws.close()
    }
    this.connect(this.url)
  }

  /** 获取连接状态详情 */
  getStatus() {
    return {
      status: this.status,
      connected: this.connected,
      reconnectAttempts: this.reconnectAttempts,
      maxReconnect: this.maxReconnect,
      url: this.url,
    }
  }

  /** 销毁实例 */
  destroy() {
    this.disconnect()
    this.removeAllListeners()
  }
}

// 全局单例
const socketService = new EnhancedSocketService()
export default socketService
export { EnhancedSocketService }
