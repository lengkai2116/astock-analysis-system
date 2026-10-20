"""527号 批次3 定向测试：多日聚合增强（②指数60日线 / ⑧宽度历史序列 / ⑥板块净流入多日）。

- **②** `get_index_summary` 附 `ma60`/`ret_60d`/`above_ma60`（daily_cache 88 行可算 60 日线）
- **⑧** `get_market_breadth` 附 `history`（market_stats_cache 近20日 ma20_ratio/limit/turnover 升序）
- **⑥** `get_sector_moneyflow` 附 `trend_5d`（近5日窗口每板块净流入累计 top5，供前端「近5日趋势」）
"""
from datetime import datetime, timedelta

import pandas as pd
from app.services.dashboard_service import DashboardService


# ──────────────────────────────────────────────
# ② get_index_summary ma60/ret_60d/above_ma60
# ──────────────────────────────────────────────
def _daily_rows(n=65):
    """构造 n 行升序日线（close 递增 → 收盘站上 60 日线、ret_60d>0）。"""
    base = datetime(2026, 7, 1)
    rows = []
    for i in range(n):
        rows.append({
            'trade_date': (base + timedelta(days=i)).strftime('%Y-%m-%d'),
            'close': 3000 + i * 10,
            'open': 3000 + i * 10 - 5,
            'pre_close': 3000 + i * 10 - 10,
            'amount': 1000000,
            'pct_chg': 0.3,
        })
    return rows


def test_index_summary_exposes_ma60_fields(monkeypatch):
    rows = _daily_rows(65)
    svc = DashboardService()
    svc._try_get_index_daily = lambda code: rows
    monkeypatch.setattr('app.services.dashboard_service.INDEX_CONFIG',
                        [{'ts_code': '000001.SH', 'name': '上证指数'}])
    res = svc.get_index_summary()
    assert res is not None
    idx = res['indexes'][0]
    # 收盘=3640，60日均值≈3345 → 站上60日线、ret_60d>0
    assert idx['ma60'] is not None and idx['ma60'] > 0
    assert idx['ret_60d'] is not None and idx['ret_60d'] > 0
    assert idx['above_ma60'] is True


def test_index_summary_ma60_none_when_history_short(monkeypatch):
    rows = _daily_rows(30)  # 不足 60 日 → ma60/ret_60d/above_ma60 应为 None
    svc = DashboardService()
    svc._try_get_index_daily = lambda code: rows
    monkeypatch.setattr('app.services.dashboard_service.INDEX_CONFIG',
                        [{'ts_code': '000001.SH', 'name': '上证指数'}])
    res = svc.get_index_summary()
    assert res is not None
    idx = res['indexes'][0]
    assert idx['ma60'] is None
    assert idx['ret_60d'] is None
    assert idx['above_ma60'] is None


# ──────────────────────────────────────────────
# ⑧ get_market_breadth history（近20日宽度序列）
# ──────────────────────────────────────────────
class _FakeECM8:
    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache':
            if 'DISTINCT trade_date' in sql:
                return pd.DataFrame({'trade_date': ['2026-10-16']})
            return pd.DataFrame({'ts_code': ['A.SH', 'B.SH', 'C.SH'], 'pct_chg': [1.0, -0.5, 0.0]})
        if table == 'daily_basic_cache':
            return pd.DataFrame({'ts_code': ['A.SH', 'B.SH', 'C.SH']})
        if table == 'market_stats_cache' and 'ORDER BY stat_date DESC' in sql:
            # 模拟 ORDER BY stat_date DESC LIMIT 20 → 返回降序，实现内 reverse 成升序
            dates = ['2026-10-16', '2026-10-15', '2026-10-14', '2026-10-13', '2026-10-10',
                     '2026-10-09', '2026-10-08', '2026-09-30', '2026-09-29', '2026-09-28',
                     '2026-09-27']
            return pd.DataFrame({
                'stat_date': dates,
                'ma20_ratio': [0.16 - 0.005 * i for i in range(len(dates))],
                'limit_ratio': [3.0] * len(dates),
                'turnover_percentile': [0.5] * len(dates),
            })
        return pd.DataFrame()

    def get_cached_market_stats(self, stat_date=None):
        return {'ma20_ratio': 0.164, 'limit_ratio': 5.25, 'turnover_percentile': 0.972}


def test_market_breadth_exposes_history():
    svc = DashboardService()
    svc._data_manager = type('_DM', (), {'cache': _FakeECM8()})()
    res = svc.get_market_breadth()
    assert res is not None
    assert 'history' in res
    assert len(res['history']) >= 2
    h = res['history']
    # 升序
    assert h[0]['stat_date'] <= h[-1]['stat_date']
    # 字段齐全
    assert 'ma20_ratio' in h[0] and 'limit_ratio' in h[0] and 'turnover_percentile' in h[0]


# ──────────────────────────────────────────────
# ⑥ get_sector_moneyflow trend_5d（近5日板块净流入累计）
# ──────────────────────────────────────────────
def _rec(code, net):
    buy = net if net > 0 else 0.0
    sell = -net if net < 0 else 0.0
    return {
        'trade_date': '2026-10-16',
        'ts_code': code,
        'buy_lg_amount': buy,
        'buy_elg_amount': 0.0,
        'sell_lg_amount': sell,
        'sell_elg_amount': 0.0,
        'net_sm_amount': net,
    }


def test_sector_moneyflow_exposes_trend_5d(monkeypatch):
    # 行业映射（Stock 表）
    industry_pairs = {
        'IN1.SH': '半导体', 'IN2.SH': '半导体', 'IN3.SH': '半导体', 'IN4.SH': '半导体',
        'BK1.SH': '银行', 'BK2.SH': '银行', 'BK3.SH': '银行',
        'JT1.SH': '交通', 'JT2.SH': '交通',
        'SP1.SH': '食品', 'SP2.SH': '食品', 'SP3.SH': '食品',
    }

    class _Stock:
        """模拟 Stock 行对象（含 ts_code/industry 属性；无 name → 名称兜底用代码）。"""

        def __init__(self, ts_code, industry):
            self.ts_code = ts_code
            self.industry = industry

    stock_rows = [_Stock(k, v) for k, v in industry_pairs.items()]

    class _All:
        def all(self):
            return stock_rows

    class _Q:
        def filter(self, *a, **k):
            return _All()

    class _Session:
        def query(self, *a, **k):
            return _Q()

    monkeypatch.setattr('app.db.session', _Session())

    # 50+ 条记录：半导体净流入累计最大 → trend_5d[0]=半导体
    records = []
    for code in ('IN1.SH', 'IN2.SH', 'IN3.SH', 'IN4.SH'):
        records.append(_rec(code, 1e4))
    for code in ('BK1.SH', 'BK2.SH', 'BK3.SH'):
        records.append(_rec(code, -0.8e4))
    for code in ('JT1.SH', 'JT2.SH'):
        records.append(_rec(code, 0.5e4))
    for i in range(23):
        records.append(_rec('SP1.SH' if i % 2 == 0 else 'SP2.SH', -0.2e4))
    for i in range(20):
        records.append(_rec('SP3.SH' if i % 2 == 0 else 'IN1.SH', 0.1e4))
    assert len(records) >= 50  # get_sector_moneyflow 前置门槛

    class _FakeDM:
        def get_cached_moneyflow(self, start_date=None, end_date=None):
            return records

    monkeypatch.setattr('app.services.dashboard_service.DataManager', lambda: _FakeDM())

    svc = DashboardService()
    # 531：默认口径已改申万一级；本用例验证 trend_5d 逻辑，沿用东财映射分支
    res = svc.get_sector_moneyflow(top_n=8, stocks_per_sector=3,
                                   industry_scope='eastmoney')
    assert res is not None
    assert 'trend_5d' in res
    assert len(res['trend_5d']) >= 1
    # 半导体净流入最大 → 榜首
    assert res['trend_5d'][0]['industry'] == '半导体'
    assert 'net_inflow_5d' in res['trend_5d'][0]
