"""
realtime_pg — PostgreSQL 盘中实时数据持久化层
===============================================
盘中数据双写管道的 L2 持久化层。采集器线程写入 InMemoryStateStore(L1) 后，
通过本模块写入 PostgreSQL(L2)，实现：
- 跨 Gunicorn worker 数据共享（所有 worker 读到相同数据）
- 进程重启后热恢复（从 PG 重建 InMemoryStateStore）
- 盘中数据仅保留当日（或短时限），无长期存档需求

使用方式（由采集器线程调用）：
    from app.data.realtime_pg import upsert_snapshot, upsert_top_stocks, ...
    upsert_snapshot(records)

设计原则：
- 使用 psycopg2 直连（非 SQLAlchemy ORM），减少开销
- 全量使用 batch UPSERT (INSERT ... ON CONFLICT DO UPDATE)
- 连接池共享，避免每次采集创建新连接
- 非阻塞：写入失败仅记日志，不影响采集主流程
"""

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ── 连接池 ──────────────────────────────────────────────────

_pg_pool = None
_pg_lock = threading.Lock()


def _get_pg_url() -> str:
    """从 DATABASE_URL 或默认值获取 PG 连接字符串"""
    url = os.environ.get('DATABASE_URL', '')
    if url and url.startswith('postgresql'):
        return url
    # 默认 PostgreSQL 连接（OS X 本地，peer 认证）
    return 'postgresql:///stock_analysis'


def init_realtime_pg():
    """初始化 PostgreSQL 连接池和盘中实时表结构

    在 Flask app factory 中被调用，确保采集器启动前就绪。
    """
    global _pg_pool
    with _pg_lock:
        if _pg_pool is not None:
            return
        url = _get_pg_url()
        try:
            import psycopg2
            from psycopg2 import pool as pg_pool_module
            _pg_pool = pg_pool_module.ThreadedConnectionPool(
                minconn=2,
                maxconn=10,
                dsn=url,
            )
            _ensure_tables(_pg_pool)
            logger.info(f"realtime_pg 连接池已就绪（{url[:40]}...）")
        except Exception as e:
            logger.warning(f"realtime_pg 初始化失败（盘中数据不会写入 PG）: {e}")


def _get_conn():
    """从连接池获取连接"""
    if _pg_pool is None:
        return None
    try:
        return _pg_pool.getconn()
    except Exception as e:
        logger.warning(f"获取 PG 连接失败: {e}")
        return None


def _put_conn(conn):
    """归还连接到池"""
    if conn is not None and _pg_pool is not None:
        try:
            _pg_pool.putconn(conn)
        except Exception:
            pass


def _ensure_tables(pool):
    """确保盘中实时表存在（幂等创建）"""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_snapshot (
                    ts_code TEXT PRIMARY KEY,
                    name TEXT,
                    price REAL,
                    change REAL,
                    change_pct REAL,
                    open REAL,
                    high REAL,
                    low REAL,
                    prev_close REAL,
                    volume REAL,
                    amount REAL,
                    turnover_rate REAL,
                    pe REAL,
                    pb REAL,
                    amplitude REAL,
                    circ_mv REAL,
                    total_mv REAL,
                    volume_ratio REAL,
                    timestamp TEXT,
                    source TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_top_stocks (
                    id SERIAL PRIMARY KEY,
                    rank_type TEXT NOT NULL,
                    ts_code TEXT NOT NULL,
                    name TEXT,
                    price REAL,
                    change REAL,
                    change_pct REAL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_sectors (
                    id SERIAL PRIMARY KEY,
                    sector_code TEXT UNIQUE NOT NULL,
                    sector_name TEXT,
                    change_pct REAL,
                    price REAL,
                    volume REAL,
                    amount REAL,
                    up_count INTEGER,
                    down_count INTEGER,
                    rank INTEGER,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_concepts (
                    id SERIAL PRIMARY KEY,
                    concept_code TEXT UNIQUE NOT NULL,
                    concept_name TEXT,
                    change_pct REAL,
                    price REAL,
                    volume REAL,
                    amount REAL,
                    up_count INTEGER,
                    down_count INTEGER,
                    rank INTEGER,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_limit_pool (
                    id SERIAL PRIMARY KEY,
                    limit_type TEXT NOT NULL,
                    ts_code TEXT NOT NULL,
                    name TEXT,
                    price REAL,
                    change_pct REAL,
                    force_amount REAL,
                    turn_over REAL,
                    limit_count INTEGER,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_minute_kline (
                    id BIGSERIAL PRIMARY KEY,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    trade_time TEXT NOT NULL,
                    freq TEXT DEFAULT '5min',
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_minute_kline_ts_code
                ON realtime_minute_kline(ts_code, trade_date)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_lhb (
                    id SERIAL PRIMARY KEY,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    name TEXT,
                    reason_category TEXT,
                    total_amount REAL,
                    net_amount REAL,
                    buy_amount REAL,
                    sell_amount REAL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS realtime_news (
                    id INTEGER PRIMARY KEY,
                    ts_code TEXT,
                    title TEXT,
                    content TEXT,
                    publish_time TEXT,
                    source TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
    finally:
        pool.putconn(conn)


# ══════════════════════════════════════════════════════════════
# UPSERT 函数（采集器线程调用）
# ══════════════════════════════════════════════════════════════


def upsert_snapshot(records: list[dict]):
    """全市场快照 upsert（覆盖式，每 15s）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_snapshot
                        (ts_code, name, price, change, change_pct, open, high, low,
                         prev_close, volume, amount, turnover_rate, pe, pb,
                         amplitude, circ_mv, total_mv, volume_ratio, timestamp, source)
                    VALUES (%(ts_code)s, %(name)s, %(price)s, %(change)s, %(change_pct)s,
                            %(open)s, %(high)s, %(low)s, %(prev_close)s, %(volume)s,
                            %(amount)s, %(turnover_rate)s, %(pe)s, %(pb)s, %(amplitude)s,
                            %(circ_mv)s, %(total_mv)s, %(volume_ratio)s, %(timestamp)s, %(source)s)
                    ON CONFLICT (ts_code)
                    DO UPDATE SET
                        price=EXCLUDED.price, change=EXCLUDED.change,
                        change_pct=EXCLUDED.change_pct, high=EXCLUDED.high,
                        low=EXCLUDED.low, volume=EXCLUDED.volume,
                        amount=EXCLUDED.amount, timestamp=EXCLUDED.timestamp
                """, r)
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_snapshot 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def upsert_top_stocks(rank_type: str, records: list[dict]):
    """涨跌榜 upsert（覆盖式，每 30s）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            # 先删除该类型旧数据，再插入新数据
            cur.execute("DELETE FROM realtime_top_stocks WHERE rank_type = %s", (rank_type,))
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_top_stocks
                        (rank_type, ts_code, name, price, change, change_pct)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (rank_type, r['ts_code'], r['name'], r['price'], r['change'], r['change_pct']))
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_top_stocks 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def upsert_sectors(records: list[dict]):
    """行业板块 upsert（覆盖式，每 5min）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_sectors
                        (sector_code, sector_name, change_pct, price, volume,
                         amount, up_count, down_count, rank)
                    VALUES (%(sector_code)s, %(sector_name)s, %(change_pct)s, %(price)s,
                            %(volume)s, %(amount)s, %(up_count)s, %(down_count)s, %(rank)s)
                    ON CONFLICT (sector_code)
                    DO UPDATE SET
                        change_pct=EXCLUDED.change_pct, price=EXCLUDED.price,
                        volume=EXCLUDED.volume, amount=EXCLUDED.amount,
                        up_count=EXCLUDED.up_count, down_count=EXCLUDED.down_count,
                        rank=EXCLUDED.rank
                """, r)
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_sectors 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def upsert_concepts(records: list[dict]):
    """概念板块 upsert（覆盖式，每 5min）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_concepts
                        (concept_code, concept_name, change_pct, price, volume,
                         amount, up_count, down_count, rank)
                    VALUES (%(concept_code)s, %(concept_name)s, %(change_pct)s, %(price)s,
                            %(volume)s, %(amount)s, %(up_count)s, %(down_count)s, %(rank)s)
                    ON CONFLICT (concept_code)
                    DO UPDATE SET
                        change_pct=EXCLUDED.change_pct, price=EXCLUDED.price,
                        volume=EXCLUDED.volume, amount=EXCLUDED.amount,
                        up_count=EXCLUDED.up_count, down_count=EXCLUDED.down_count,
                        rank=EXCLUDED.rank
                """, r)
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_concepts 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def upsert_limit_pool(records: list[dict], limit_type: str):
    """涨跌停池 upsert（覆盖式，每 5min）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM realtime_limit_pool WHERE limit_type = %s", (limit_type,))
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_limit_pool
                        (limit_type, ts_code, name, price, change_pct,
                         force_amount, turn_over, limit_count)
                    VALUES (%(limit_type)s, %(ts_code)s, %(name)s, %(price)s, %(change_pct)s,
                            %(force_amount)s, %(turn_over)s, %(limit_count)s)
                """, {'limit_type': limit_type, **r})
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_limit_pool 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def upsert_minute_kline(records: list[dict]):
    """分钟K线追加（累积式，每 5min）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_minute_kline
                        (ts_code, trade_date, trade_time, freq, open, high, low,
                         close, volume, amount)
                    VALUES (%(ts_code)s, %(trade_date)s, %(trade_time)s, %(freq)s,
                            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(amount)s)
                    ON CONFLICT DO NOTHING
                """, r)
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_minute_kline 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def upsert_lhb(records: list[dict]):
    """龙虎榜 upsert（覆盖式，每 30min）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM realtime_lhb")
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_lhb
                        (ts_code, trade_date, name, reason_category, total_amount,
                         net_amount, buy_amount, sell_amount)
                    VALUES (%(ts_code)s, %(trade_date)s, %(name)s, %(reason_category)s,
                            %(total_amount)s, %(net_amount)s, %(buy_amount)s, %(sell_amount)s)
                """, r)
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_lhb 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def upsert_news(records: list[dict]):
    """新闻 upsert（覆盖式，每 30min）"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO realtime_news
                        (id, ts_code, title, content, publish_time, source)
                    VALUES (%(id)s, %(ts_code)s, %(title)s, %(content)s,
                            %(publish_time)s, %(source)s)
                    ON CONFLICT (id)
                    DO UPDATE SET
                        ts_code=EXCLUDED.ts_code, title=EXCLUDED.title,
                        publish_time=EXCLUDED.publish_time
                """, r)
        conn.commit()
    except Exception as e:
        logger.warning(f"[realtime_pg] upsert_news 失败: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)
