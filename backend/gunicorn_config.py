"""
Gunicorn 生产配置 — 243号方案（2026-07-07 修订）
=============================================
⚠️ 当前不使用 Gunicorn。启动方式：run.py（socketio.run + eventlet）
Gunicorn 后续版本（26.x）移除了 eventlet worker 支持，
待 gevent-websocket 方案验证后恢复使用。

保留此文件供未来参考。"""
# 每个 worker 的最大连接数
worker_connections = 1000
# 超时时间（秒）
timeout = 120
# 优雅重启超时
graceful_timeout = 30
# 最大请求数（避免内存泄漏）
max_requests = 10000
max_requests_jitter = 2000

# ── 端口配置 ───────────────────────────────────────────────
bind = f"0.0.0.0:{os.environ.get('PORT', '5001')}"

# ── 日志配置 ───────────────────────────────────────────────
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
accesslog = os.environ.get('GUNICORN_ACCESS_LOG', '-')  # stdout
errorlog = os.environ.get('GUNICORN_ERROR_LOG', '-')     # stdout
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# ── 进程管理 ───────────────────────────────────────────────
proc_name = 'stock_analyzer'

# 预加载应用代码（加速 worker 启动）
preload_app = True

# 守护模式（后台运行）
daemon = False


def on_starting(server):
    """master 进程启动时初始化采集器和 PG 连接池"""
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('gunicorn.startup')

    try:
        from app.data.akshare_collector import akshare_collector
        akshare_collector.start()
        import atexit
        atexit.register(lambda: akshare_collector.stop())
        logger.info("AkshareCollector 已启动（on_starting hook）")
    except Exception as e:
        logger.warning(f"AkshareCollector 启动失败（盘中数据推送不可用）: {e}")

    try:
        from app.data.mootdx_collector import mootdx_collector
        mootdx_collector.start()
        atexit.register(lambda: mootdx_collector.stop())
        logger.info("MootdxCollector 已启动（on_starting hook, TCP 直连）")
    except Exception as e:
        logger.warning(f"MootdxCollector 启动失败: {e}")



def when_ready(server):
    """所有 worker 就绪后回调"""
    import logging
    logger = logging.getLogger('gunicorn.ready')
    logger.info(f"Stock Analyzer 服务就绪 (workers={server.num_workers})")


def on_exit(server):
    """进程退出时清理"""
    import logging
    logger = logging.getLogger('gunicorn.exit')
    try:
        from app.data.akshare_collector import akshare_collector
        akshare_collector.stop()
        logger.info("AkshareCollector 已停止")
    except Exception:
        pass
    try:
        from app.data.mootdx_collector import mootdx_collector
        mootdx_collector.stop()
        logger.info("MootdxCollector 已停止")
    except Exception:
        pass
