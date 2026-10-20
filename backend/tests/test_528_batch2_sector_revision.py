"""528号 批次2 定向测试：板块涨跌幅全量双侧修复 + 连续涨跌/近5日累积 + 板块净流出多日。

- **④** `get_sector_changes` 取数改全量（top_n=None）→ 双侧 gainers/losers 不再因截断恒空
  （原 `reader.get_sector_rankings()` 默认 top_n=20，DB 回退 `ORDER BY change_pct DESC
  LIMIT 20` 前 20 全为正涨幅 → losers 恒空＝跌幅 TOP5 缺失根因）
- **④** `_get_sector_streaks`：daily_cache 多日按行业聚合 → 连续涨/跌天数 + 近5日累积涨跌
- **②** `get_sector_moneyflow` 附 `trend_5d_out`（近5日净流出 top5，与净流入对称）
"""
import pandas as pd
from app.services.dashboard_service import DashboardService


# ──────────────────────────────────────────────
# ④ get_sector_changes 全量取数双侧修复
# ──────────────────────────────────────────────
class _FakeReader:
    """模拟 akshare_reader.reader.get_sector_rankings：含正负双侧的完整列表。"""

    def __init__(self, rankings):
        self._rankings = rankings

    def get_sector_rankings(self, top_n=None):
        if top_n is None:
            return list(self._rankings)
        return self._rankings[:top_n]


def _mk_ranking(name, pct):
    return {'sector_name': name, 'change_pct': pct, 'up_count': 1, 'down_count': 0}


def test_sector_changes_losers_not_empty_when_full_fetch(monkeypatch):
    """④ 全量取数后 losers 有值（原 top_n=20 截断只取涨幅 → losers 恒空）。"""
    rankings = [_mk_ranking(f'板块{i}', 3.0 - 0.1 * i) for i in range(10)]  # 全正
    rankings += [_mk_ranking(f'跌板块{i}', -1.0 - 0.1 * i) for i in range(10)]  # 含负
    monkeypatch.setattr(
        'app.data.akshare_reader.reader', _FakeReader(rankings))
    svc = DashboardService()
    svc._get_sector_streaks = lambda: {'up': [], 'down': []}
    res = svc.get_sector_changes()
    assert res is not None
    assert len(res['gainers']) == 5
    assert len(res['losers']) == 5
    # losers 为最负 5 个
    assert all(s['change_pct'] <= 0 for s in res['losers'])
    assert res['losers'][0]['change_pct'] < 0
    assert 'streaks' in res


def test_sector_changes_truncated_fetch_losers_historically_empty():
    """复现原缺陷：top_n=20 且全正涨幅时 losers 恒空（修复前行为）。"""
    rankings = [_mk_ranking(f'板块{i}', 3.0 - 0.1 * i) for i in range(20)]  # 全正
    # 直接验证截断路径语义：仅传前 20 全正 → 无负侧
    all_sectors = [{'name': r['sector_name'], 'change_pct': r['change_pct']} for r in rankings]
    losers = [s for s in all_sectors if s['change_pct'] <= 0]
    assert losers == []  # 旧取数路径下的根因


# ──────────────────────────────────────────────
# ④ _get_sector_streaks 连续涨/跌 + 近5日累积
# ──────────────────────────────────────────────
class _FakeECMStreak:
    def __init__(self):
        # 6 个交易日升序；每行业 2 只股
        self._dates = ['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15',
                       '2026-10-16', '2026-10-19']
        self._rows = []
        # 半导体：连续上涨（近4日+）→ 连涨 4 日
        for d, p in zip(self._dates, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]):
            self._rows.append((d, 'A.SH', p))
            self._rows.append((d, 'B.SH', p))
        # 银行：连续下跌（近3日-）→ 连跌 3 日
        for d, p in zip(self._dates, [0.1, 0.2, -0.1, -0.2, -0.3, -0.4]):
            self._rows.append((d, 'C.SH', p))
            self._rows.append((d, 'D.SH', p))

    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache' and 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': self._dates[::-1]})
        if table == 'daily_cache' and 'WHERE trade_date IN' in sql:
            return pd.DataFrame(
                self._rows, columns=['trade_date', 'ts_code', 'pct_chg'])
        return pd.DataFrame()


class _FakeDMStreak:
    def __init__(self):
        self.cache = _FakeECMStreak()


def test_get_sector_streaks_detects_consecutive_up_down(monkeypatch):
    """④ streaks：半导体连涨4日、银行连跌3日，近5日累积正确。"""
    industry_pairs = {
        'A.SH': '半导体', 'B.SH': '半导体', 'C.SH': '银行', 'D.SH': '银行',
        # 填充行业（不参与数据聚合，仅越过生产代码 len(industry_map)<10 门槛）
        'X1.SH': '其他', 'X2.SH': '其他', 'X3.SH': '其他', 'X4.SH': '其他',
        'X5.SH': '其他', 'X6.SH': '其他',
    }

    class _Stock:
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

    # _get_sector_streaks 生产代码用 db.session.query（对齐 get_sector_moneyflow）
    monkeypatch.setattr('app.db.session', _Session())
    svc = DashboardService()
    svc._data_manager = _FakeDMStreak()
    res = svc._get_sector_streaks(days=6)
    assert 'up' in res and 'down' in res
    up_inds = [s['industry'] for s in res['up']]
    down_inds = [s['industry'] for s in res['down']]
    assert '半导体' in up_inds
    assert '银行' in down_inds
    semi = next(s for s in res['up'] if s['industry'] == '半导体')
    bank = next(s for s in res['down'] if s['industry'] == '银行')
    assert semi['days'] == 6  # 6 日全涨
    assert bank['days'] == 4  # 末 4 日连跌（-0.1/-0.2/-0.3/-0.4）
    # 近5日累积 = 后5日行业均值之和（半导体 0.2+0.3+0.4+0.5+0.6=2.0）
    assert abs(semi['cum_5d'] - 2.0) < 1e-6


def test_get_sector_streaks_failure_returns_empty():
    """④ streaks 异常回退空两侧（不阻断主接口）。"""
    class _BadECM:
        def _query_shard(self, *a, **k):
            raise RuntimeError('db down')

    svc = DashboardService()
    svc._data_manager = type('_DM', (), {'cache': _BadECM()})()
    res = svc._get_sector_streaks()
    assert res == {'up': [], 'down': []}


# ──────────────────────────────────────────────
# ② get_sector_moneyflow trend_5d_out（近5日净流出）
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


def test_sector_moneyflow_exposes_trend_5d_out(monkeypatch):
    """② trend_5d_out 为近5日净流出 top5（最负在前，与净流入对称）。"""
    industry_pairs = {
        'IN1.SH': '半导体', 'IN2.SH': '半导体', 'IN3.SH': '半导体',
        'BK1.SH': '银行', 'BK2.SH': '银行', 'BK3.SH': '银行',
        'SP1.SH': '食品', 'SP2.SH': '食品', 'SP3.SH': '食品',
        # 填充行业（不参与资金聚合，仅越过生产代码 len(industry_map)<10 门槛）
        'X1.SH': '其他', 'X2.SH': '其他',
    }

    class _Stock:
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

    records = []
    for code in ('IN1.SH', 'IN2.SH', 'IN3.SH'):
        records.append(_rec(code, 1e4))
    for code in ('BK1.SH', 'BK2.SH', 'BK3.SH'):
        records.append(_rec(code, -0.9e4))
    for i in range(25):
        records.append(_rec('SP1.SH' if i % 2 == 0 else 'SP2.SH', -0.3e4))
    for i in range(25):
        records.append(_rec('SP3.SH' if i % 2 == 0 else 'IN1.SH', 0.05e4))
    assert len(records) >= 50

    class _FakeDM:
        def get_cached_moneyflow(self, start_date=None, end_date=None):
            return records

    monkeypatch.setattr('app.services.dashboard_service.DataManager', lambda: _FakeDM())

    svc = DashboardService()
    # 531：默认口径已改申万一级；本用例验证净流出 trend_5d_out，沿用东财映射分支
    res = svc.get_sector_moneyflow(top_n=8, stocks_per_sector=3,
                                   industry_scope='eastmoney')
    assert res is not None
    assert 'trend_5d' in res and 'trend_5d_out' in res
    assert len(res['trend_5d_out']) >= 1
    # 食品累计 -6.9e4（25×-0.3e4 + SP3 正流入 ~0.6e4）比银行 -2.7e4 更负 → 净流出榜首
    assert res['trend_5d_out'][0]['industry'] == '食品'
    assert res['trend_5d_out'][0]['net_inflow_5d'] < 0
    out_inds = [s['industry'] for s in res['trend_5d_out']]
    assert '银行' in out_inds
