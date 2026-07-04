"""
Gunicorn 生产配置 — 243号方案
==============================
- 4 worker 进程（eventlet 异步模式）
- on_starting hook：启动 AkshareCollector 采集器
- 通过 Redis pub/sub 实现多 worker SocketIO 消息广播
"""

import os
import multiprocessing

# ── Worker 配置 ────────────────────────────────────────────

# 检测 CPU 核心数，默认 4
workers = int(os.environ.get('GUNICORN_WORKERS', '4'))
# 使用 gevent（生产环境最稳定，与 Flask-SocketIO 兼容）
worker_class = 'gevent'
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
        from app.data.realtime_pg import init_realtime_pg
        init_realtime_pg()
        logger.info("PostgreSQL 盘中实时连接池已初始化")
    except Exception as e:
        logger.warning(f"PG 连接池初始化失败: {e}")


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
