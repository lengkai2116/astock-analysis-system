/**
 * useRealtimeData — WebSocket 推送优先 / REST 降级轮询 数据消费 composable
 *
 * 设计原则：
 * - 推优先（push-first）：WebSocket 在线时监听 4 种事件，实时更新
 * - 轮询降级（poll-fallback）：WebSocket 断连时按间隔轮询 REST 端点
 * - 零冗余连接：复用 socketService 全局单例，不创建第二个连接
 * - 生命周期自管理：autoConnect=true 时 onMounted/onUnmounted 自动绑定
 *
 * 后端 WsBridge 推送事件（ws_bridge.py）：
 *   market:summary    — { total_count, up_ratio, up_count, down_count, flat_count, timestamp }
 *   market:top_stocks — { up[], down[], timestamp }
 *   market:sectors    — { sectors[], timestamp }
 *   market:news       — { headlines[], total, timestamp }
 *
 * 用法（Options API）：
 *   export default {
 *     setup() {
 *       const { connected, marketSummary } = useRealtimeData({ autoConnect: true })
 *       return { wsConnected: connected, marketSummary }
 *     },
 *     watch: {
 *       marketSummary(val) { if (val) this.updateStats(val) }
 *     }
 *   }
 *
 * 用法（Composition API / <script setup>）：
 *   const { connected, marketSummary, topStocks } = useRealtimeData()
 */
import { ref, shallowRef, onMounted, onUnmounted } from 'vue'
import socketService from '@/services/socketService'
import dataService from '@/services/dataService'

/**
 * @param {Object} opts
 * @param {number}  [opts.pollInterval=30000]  — REST 降级轮询间隔（ms）
 * @param {boolean} [opts.autoConnect=true]    — 组件挂载时自动连接
 * @param {string[]}[opts.watchlist=[]]        — 自选股列表（订阅行情推送）
 * @param {string}  [opts.wsUrl='http://localhost:5001'] — Socket.IO 服务地址
 */
export function useRealtimeData(opts = {}) {
  const {
    pollInterval = 30000,
    autoConnect = true,
    watchlist = [],
    wsUrl = 'http://localhost:5001',
  } = opts

  // ── 响应式状态 ────────────────────────────────────────────

  const connected = ref(false)
  const connectionStatus = ref('disconnected')

  // 推送数据（shallowRef 避免深层次响应式开销）
  const marketSummary = shallowRef(null)
  const topStocks = shallowRef(null)
  const sectors = shallowRef(null)
  const news = shallowRef(null)

  // ── 内部状态 ──────────────────────────────────────────────

  let pollTimer = null
  let isSetup = false

  // ── WebSocket 事件处理 ──────────────────────────────────

  function handleConnect() {
    connected.value = true
    connectionStatus.value = 'connected'
    stopPollFallback()
  }

  function handleDisconnect() {
    connected.value = false
    connectionStatus.value = 'disconnected'
    startPollFallback()
  }

  function handleMarketSummary(data) { marketSummary.value = data }
  function handleTopStocks(data) { topStocks.value = data }
  function handleSectors(data) { sectors.value = data }
  function handleNews(data) { news.value = data }

  // ── WebSocket 连接管理 ──────────────────────────────────

  function setupWebSocket() {
    socketService.on('connect', handleConnect)
    socketService.on('disconnect', handleDisconnect)
    socketService.on('market:summary', handleMarketSummary)
    socketService.on('market:top_stocks', handleTopStocks)
    socketService.on('market:sectors', handleSectors)
    socketService.on('market:news', handleNews)

    if (!socketService.isConnected()) {
      socketService.connect(wsUrl)
    } else {
      connected.value = true
      connectionStatus.value = 'connected'
    }

    if (watchlist.length > 0) {
      socketService.subscribeWatchlist(watchlist)
    }
  }

  function teardownWebSocket() {
    socketService.off('connect', handleConnect)
    socketService.off('disconnect', handleDisconnect)
    socketService.off('market:summary', handleMarketSummary)
    socketService.off('market:top_stocks', handleTopStocks)
    socketService.off('market:sectors', handleSectors)
    socketService.off('market:news', handleNews)
  }

  // ── REST 降级轮询 ────────────────────────────────────────

  async function pollFallback() {
    try {
      const [watchlistData, marketData] = await Promise.all([
        dataService.getWatchlistData().catch(() => null),
        dataService.getMarketOverview().catch(() => null),
      ])

      if (watchlistData) {
        const stocks = watchlistData.stocks || []
        const up = watchlistData.up_count || 0
        const down = watchlistData.down_count || 0
        marketSummary.value = {
          total_count: stocks.length,
          up_count: up,
          down_count: down,
          flat_count: Math.max(0, stocks.length - up - down),
          up_ratio: stocks.length > 0 ? +(up / stocks.length).toFixed(4) : 0,
          timestamp: new Date().toISOString(),
        }
      }

      if (marketData) {
        topStocks.value = {
          up: (marketData.top_stocks || []).slice(0, 10),
          down: (marketData.bottom_stocks || []).slice(0, 10),
          timestamp: new Date().toISOString(),
        }
        sectors.value = {
          sectors: (marketData.sectors || []).slice(0, 20),
          timestamp: new Date().toISOString(),
        }
      }
    } catch (e) {
      // REST 降级静默失败，等待下次轮询
    }
  }

  function startPollFallback() {
    if (pollTimer) return
    pollTimer = setInterval(pollFallback, pollInterval)
    pollFallback() // 立即执行一次
  }

  function stopPollFallback() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // ── 生命周期 ──────────────────────────────────────────────

  function init() {
    if (isSetup) return
    isSetup = true
    setupWebSocket()
  }

  function destroy() {
    isSetup = false
    stopPollFallback()
    teardownWebSocket()
  }

  if (autoConnect) {
    onMounted(init)
    onUnmounted(destroy)
  }

  // ── 返回 ──────────────────────────────────────────────────

  return {
    connected,
    connectionStatus,
    marketSummary,
    topStocks,
    sectors,
    news,
    init,
    destroy,
  }
}
