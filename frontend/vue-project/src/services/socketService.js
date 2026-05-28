import io from 'socket.io-client'

class SocketService {
  constructor() {
    this.socket = null
    this.connected = false
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 10
    this.reconnectDelay = 1000
    this.maxDelay = 30000
    this.subscriptions = []
    this.eventListeners = {}
    this.autoReconnect = true
  }

  connect(url = 'http://localhost:5001') {
    if (this.socket?.connected) {
      console.log('🔌 SocketIO已连接')
      return this.socket
    }

    console.log('🚀 尝试连接SocketIO服务:', url)
    
    this.socket = io(url, {
      transports: ['websocket', 'polling'],
      reconnection: this.autoReconnect,
      reconnectionDelay: this.reconnectDelay,
      reconnectionDelayMax: this.maxDelay,
      reconnectionAttempts: this.maxReconnectAttempts,
      timeout: 20000
    })

    this.setupEventHandlers()
    
    return this.socket
  }

  setupEventHandlers() {
    this.socket.on('connect', () => {
      console.log('✅ SocketIO连接成功')
      this.connected = true
      this.reconnectAttempts = 0
      this.reconnectDelay = 1000
      
      this.notifyConnectionChange(true)
      this.resubscribeAll()
    })

    this.socket.on('disconnect', (reason) => {
      console.log('❌ SocketIO连接断开:', reason)
      this.connected = false
      this.notifyConnectionChange(false)
    })

    this.socket.on('reconnect', (attempt) => {
      console.log('🔄 SocketIO重连成功, 尝试次数:', attempt)
      this.connected = true
      this.reconnectAttempts = 0
      this.reconnectDelay = 1000
      
      this.notifyConnectionChange(true)
      this.resubscribeAll()
    })

    this.socket.on('reconnect_attempt', (attempt) => {
      this.reconnectAttempts = attempt
      console.log(`🔄 SocketIO重连尝试 ${attempt}/${this.maxReconnectAttempts}`)
      this.notifyReconnectProgress(attempt)
    })

    this.socket.on('reconnect_error', (error) => {
      console.log('⚠️ SocketIO重连失败:', error)
    })

    this.socket.on('reconnect_failed', () => {
      console.log('❌ SocketIO重连失败，已达到最大重试次数')
      this.notifyReconnectFailed()
    })

    this.socket.on('error', (error) => {
      console.log('⚠️ SocketIO错误:', error)
      this.notifyError(error)
    })
    
    this.socket.on('connect_error', (error) => {
      console.log('❌ SocketIO连接错误:', error)
      this.notifyError(error)
    })
  }

  subscribeWatchlist(watchlist = []) {
    const subscription = { type: 'watchlist', data: { watchlist } }
    this.subscriptions.push(subscription)
    
    if (this.socket?.connected) {
      this.socket.emit('subscribe_watchlist', { watchlist })
    }
  }

  subscribeKline(tsCode, freq = '15min') {
    const subscription = { type: 'kline', data: { tsCode, freq } }
    this.subscriptions.push(subscription)
    
    if (this.socket?.connected) {
      this.socket.emit('subscribe_kline', { ts_code: tsCode, freq })
    }
  }

  resubscribeAll() {
    console.log('📡 重新订阅所有订阅项')
    
    this.subscriptions.forEach(sub => {
      switch (sub.type) {
        case 'watchlist':
          this.socket?.emit('subscribe_watchlist', sub.data)
          break
        case 'kline':
          this.socket?.emit('subscribe_kline', sub.data)
          break
      }
    })
    
    Object.keys(this.eventListeners).forEach(event => {
      this.eventListeners[event].callbacks.forEach(cb => {
        this.socket?.on(event, cb)
      })
    })
  }

  joinRoom(room) {
    if (this.socket?.connected) {
      this.socket.emit('join_room', { room })
    }
  }

  on(event, callback) {
    if (!this.eventListeners[event]) {
      this.eventListeners[event] = { callbacks: [], original: null }
    }
    this.eventListeners[event].callbacks.push(callback)
    
    if (this.socket) {
      this.socket.on(event, callback)
    }
  }

  off(event, callback) {
    if (this.eventListeners[event]) {
      if (callback) {
        this.eventListeners[event].callbacks = 
          this.eventListeners[event].callbacks.filter(cb => cb !== callback)
      } else {
        this.eventListeners[event].callbacks = []
      }
    }
    
    if (this.socket) {
      if (callback) {
        this.socket.off(event, callback)
      } else {
        this.socket.off(event)
      }
    }
  }

  emit(event, data) {
    if (this.socket?.connected) {
      this.socket.emit(event, data)
    } else {
      console.warn(`⚠️ Socket未连接，无法发送事件: ${event}`)
    }
  }

  isConnected() {
    return this.socket?.connected || false
  }

  getConnectionStatus() {
    return {
      connected: this.connected,
      reconnectAttempts: this.reconnectAttempts,
      maxReconnectAttempts: this.maxReconnectAttempts,
      canReconnect: this.reconnectAttempts < this.maxReconnectAttempts
    }
  }

  reconnect() {
    console.log('🔄 手动触发重连')
    this.reconnectAttempts = 0
    if (this.socket) {
      this.socket.connect()
    }
  }

  disconnect() {
    this.autoReconnect = false
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
      this.connected = false
      console.log('🔌 SocketIO已断开')
    }
  }

  clearSubscriptions() {
    this.subscriptions = []
  }

  notifyConnectionChange(connected) {
    this.emit('connection_change', { connected })
  }

  notifyReconnectProgress(attempt) {
    this.emit('reconnect_progress', {
      attempt,
      maxAttempts: this.maxReconnectAttempts,
      progress: (attempt / this.maxReconnectAttempts) * 100
    })
  }

  notifyReconnectFailed() {
    this.emit('reconnect_failed', { message: '已达到最大重试次数' })
  }

  notifyError(error) {
    this.emit('socket_error', { error: error.message || error })
  }
}

export default new SocketService()
