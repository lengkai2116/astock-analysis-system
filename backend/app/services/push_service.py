"""
push_service — API 进程实时推送服务
====================================
从快照库读取数据，通过 SocketIO 推送到前端。
每 5s（交易时段）由 APScheduler 触发。

职责边界：
  - 只关心"读快照 + 计算 + 推送"
  - 不关心数据来源（data_daemon / mootdx）
  - 不关心存储细节（ECM 封装了 SQLite WAL）
  - 所有函数 try/except 容错，不向上抛异常
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── 惰性 socketio 引用（避免循环导入） ──
_socketio_instance = None


def _get_socketio():
    """惰性获取 Flask-SocketIO 实例"""
    global _socketio_instance
    if _socketio_instance is None:
        try:
            from app import socketio as sio
            _socketio_instance = sio
        except Exception as e:
            logger.debug("[push_service] socketio 引用失败: %s", e)
            return None
    return _socketio_instance


# ── 工具函数 ─────────────────────────────────────────────


def _compute_change_pct(snapshot: dict) -> float:
    """从快照行计算涨跌幅

    快照库 as_market_snapshot 不直接存储 change_pct，
    需通过 (price - prev_close) / prev_close × 100 计算。
    """
    price = float(snapshot.get('price', 0))
    prev_close = float(snapshot.get('prev_close', 0))
    if prev_close:
        return round((price - prev_close) / prev_close * 100, 2)
    return 0.0


def _get_cached_at(snapshots: list) -> str:
    """从快照列表提取 cached_at 时间戳（同批次写入，取第一条即可）"""
    if not snapshots:
        return ''
    return snapshots[0].get('cached_at', '')


def _staleness_info(cached_at_str: str) -> Optional[dict]:
    """检查数据陈旧状态

    Returns:
        None → 数据新鲜
        {'level': 'staleness_warning', 'age_seconds': N} → 30s < age ≤ 5min
        {'level': 'data_offline', 'age_seconds': N} → age > 5min
    """
    if not cached_at_str:
        return None
    try:
        cached_dt = datetime.strptime(cached_at_str, '%Y-%m-%d %H:%M:%S')
        age = (datetime.now() - cached_dt).total_seconds()
    except (ValueError, TypeError):
        return None

    if age > 300:
        return {'level': 'data_offline', 'age_seconds': int(age)}
    if age > 30:
        return {'level': 'staleness_warning', 'age_seconds': int(age)}
    return None


# ── 推送函数 ─────────────────────────────────────────────


def push_market_summary():
    """推送市场概况涨跌分布"""
    sio = _get_socketio()
    if sio is None:
        return

    try:
        from app.data import DataManager
        ecm = DataManager().cache
        snapshots = ecm.get_all_market_snapshots()

        total = len(snapshots)
        advancing = declining = unchanged = 0

        for s in snapshots:
            pct = _compute_change_pct(s)
            if pct > 0:
                advancing += 1
            elif pct < 0:
                declining += 1
            else:
                unchanged += 1

        cached_at = _get_cached_at(snapshots)

        # 陈旧状态检查
        stale = _staleness_info(cached_at)
        if stale:
            if stale['level'] == 'data_offline':
                sio.emit('market:data_offline', stale)
                logger.warning("快照数据离线: %ss 未更新", stale['age_seconds'])
            else:
                sio.emit('market:staleness_warning', stale)
                logger.debug("快照数据延迟: %ss", stale['age_seconds'])

        sio.emit('market:summary', {
            'total': total,
            'advancing': advancing,
            'declining': declining,
            'unchanged': unchanged,
            'cached_at': cached_at,
        })
    except Exception as e:
        logger.error("推送市场概况失败: %s", e)


def push_top_stocks():
    """推送涨幅榜/跌幅榜 Top10"""
    sio = _get_socketio()
    if sio is None:
        return

    try:
        from app.data import DataManager
        ecm = DataManager().cache
        snapshots = ecm.get_all_market_snapshots()

        # 补充计算 change_pct
        enriched = []
        for s in snapshots:
            s['change_pct'] = _compute_change_pct(s)
            s['change'] = round(
                float(s.get('price', 0)) - float(s.get('prev_close', 0)), 2
            )
            enriched.append(s)

        # 正序（跌幅榜）、逆序（涨幅榜）
        sorted_asc = sorted(enriched, key=lambda x: x['change_pct'])
        sorted_desc = sorted(enriched, key=lambda x: x['change_pct'], reverse=True)

        def _brief(r):
            return {
                'ts_code': r.get('ts_code', ''),
                'name': r.get('name', ''),
                'price': float(r.get('price', 0)),
                'change_pct': r['change_pct'],
                'change': r['change'],
            }

        gainers = [_brief(r) for r in sorted_desc[:10]]
        losers = [_brief(r) for r in sorted_asc[:10]]

        cached_at = _get_cached_at(snapshots)
        sio.emit('market:top_stocks', {
            'gainers': gainers,
            'losers': losers,
            'cached_at': cached_at,
        })
    except Exception as e:
        logger.error("推送涨跌幅榜失败: %s", e)


def push_sector_rankings():
    """推送板块排行 Top20

    从 Stock ORM 获取 industry 映射，按行业分组计算平均涨跌幅。
    需要 Flask app_context（由 APScheduler 包装函数提供）。
    """
    sio = _get_socketio()
    if sio is None:
        return

    try:
        from app.data import DataManager
        ecm = DataManager().cache
        snapshots = ecm.get_all_market_snapshots()

        if not snapshots:
            return

        # 从 Stock ORM 构建 ts_code → industry 映射
        from app import db
        from app.models import Stock
        stocks = Stock.query.with_entities(
            Stock.ts_code, Stock.industry
        ).all()
        code_to_industry = {s.ts_code: s.industry for s in stocks if s.industry}

        # 按行业分组聚合
        sectors = {}
        for s in snapshots:
            ts_code = s.get('ts_code', '')
            industry = code_to_industry.get(ts_code, '其他')
            if industry not in sectors:
                sectors[industry] = {
                    'stocks': 0, 'up': 0, 'down': 0, 'total_change': 0.0,
                }
            pct = _compute_change_pct(s)
            d = sectors[industry]
            d['stocks'] += 1
            d['total_change'] += pct
            if pct > 0:
                d['up'] += 1
            elif pct < 0:
                d['down'] += 1

        sector_list = []
        for industry, data in sectors.items():
            count = data['stocks']
            avg = round(data['total_change'] / count, 2) if count else 0.0
            sector_list.append({
                'sector_name': industry,
                'stock_count': count,
                'avg_change_pct': avg,
                'up_count': data['up'],
                'down_count': data['down'],
            })

        # 按 |平均涨跌幅| 降序，取 Top20
        sector_list.sort(key=lambda x: abs(x['avg_change_pct']), reverse=True)

        cached_at = _get_cached_at(snapshots)
        sio.emit('market:sectors', {
            'sectors': sector_list[:20],
            'cached_at': cached_at,
        })
    except Exception as e:
        logger.error("推送板块排行失败: %s", e)


def push_watchlist_quotes():
    """推送自选股实时行情到 watchlist 房间"""
    sio = _get_socketio()
    if sio is None:
        return

    try:
        # 从 WsBridge 获取自选股代码列表
        from app.data.ws_bridge import ws_bridge
        codes = ws_bridge.get_watchlist_codes()
        if not codes:
            return

        from app.data import DataManager
        ecm = DataManager().cache
        snapshots = ecm.get_all_market_snapshots(codes=list(codes))

        if not snapshots:
            return

        quotes = []
        for s in snapshots:
            quotes.append({
                'ts_code': s.get('ts_code', ''),
                'name': s.get('name', ''),
                'price': float(s.get('price', 0)),
                'change_pct': _compute_change_pct(s),
                'change': round(
                    float(s.get('price', 0)) - float(s.get('prev_close', 0)), 2
                ),
                'open': float(s.get('open', 0)),
                'high': float(s.get('high', 0)),
                'low': float(s.get('low', 0)),
                'volume': int(s.get('volume', 0)),
                'amount': float(s.get('amount', 0)),
            })

        cached_at = _get_cached_at(snapshots)
        sio.emit('stock:quotes', {
            'quotes': quotes,
            'cached_at': cached_at,
        }, room='watchlist')
    except Exception as e:
        logger.error("推送自选股行情失败: %s", e)
