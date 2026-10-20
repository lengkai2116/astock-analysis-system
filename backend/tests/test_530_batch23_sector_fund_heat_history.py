"""530号 批次2/3 定向测试：

批次2（② 板块热度改资金占比）：
- ECM `cache_sector_fund_heat` / `get_cached_sector_fund_heat`（sector_fund_heat_cache 读写）
- `DashboardService.get_sector_heat` 优先读资金热度表（方向 B），为空回退趋势表（MA5>MA20）

批次3（③ 近20日板块涨跌折线）：
- `DashboardService._get_sector_history_20d`：daily_cache 近20日按行业聚合日均涨跌幅序列
"""
import pandas as pd
from app.services.dashboard_service import DashboardService


# ──────────────────────────────────────────────
# 批次2：sector_fund_heat_cache ECM 读写
# ──────────────────────────────────────────────
class _FakeECMShard:
    """模拟 ECM：sector_fund_heat_cache / sector_heat_cache 读写（内存 dict 行）。"""

    def __init__(self):
        self._fund_rows = []  # 每行 dict（模拟 long 格式行）
        self._heat_rows = []

    # ── _exec_shard（写）──
    def _exec_shard(self, table, sql, params=None):
        params = params or []
        if table == 'sector_fund_heat_cache':
            if sql.startswith('DELETE'):
                self._fund_rows = [r for r in self._fund_rows if r['stat_date'] != params[0]]
            elif sql.startswith('INSERT'):
                self._fund_rows.append({
                    'stat_date': params[0], 'industry': params[1],
                    'net_inflow_5d': params[2], 'circ_mv': params[3],
                    'ratio': params[4], 'rank': params[5], 'heat_level': params[6],
                })
        elif table == 'sector_heat_cache':
            if sql.startswith('DELETE'):
                self._heat_rows = [r for r in self._heat_rows if r['stat_date'] != params[0]]
            elif sql.startswith('INSERT'):
                self._heat_rows.append({
                    'stat_date': params[0], 'industry': params[1],
                    'heat_level': params[2], 'strength': params[3],
                    'rank': params[4], 'stock_count': params[5],
                })
        return None

    # ── _query_shard（读，返回 DataFrame；SELECT * 全行优先于 MAX/DISTINCT）──
    def _query_shard(self, table, sql, params=None):
        params = params or []
        if table == 'sector_fund_heat_cache':
            if sql.startswith('SELECT *'):
                stat = None
                if 'stat_date = ?' in sql and params:
                    stat = params[0]
                rows = [r for r in self._fund_rows
                        if stat is None or r['stat_date'] == stat]
                return pd.DataFrame(rows) if rows else pd.DataFrame()
            if 'MAX(stat_date)' in sql:
                mx = max((r['stat_date'] for r in self._fund_rows), default=None)
                return pd.DataFrame({'d': [mx]}) if mx else pd.DataFrame()
            if 'DISTINCT stat_date' in sql:
                dates = sorted({r['stat_date'] for r in self._fund_rows})
                return pd.DataFrame({'stat_date': dates}) if dates else pd.DataFrame()
        if table == 'sector_heat_cache':
            if sql.startswith('SELECT *'):
                stat = None
                if 'stat_date = ?' in sql and params:
                    stat = params[0]
                rows = [r for r in self._heat_rows
                        if stat is None or r['stat_date'] == stat]
                return pd.DataFrame(rows) if rows else pd.DataFrame()
            if 'MAX(stat_date)' in sql:
                mx = max((r['stat_date'] for r in self._heat_rows), default=None)
                return pd.DataFrame({'d': [mx]}) if mx else pd.DataFrame()
            if 'DISTINCT stat_date' in sql:
                dates = sorted({r['stat_date'] for r in self._heat_rows})
                return pd.DataFrame({'stat_date': dates}) if dates else pd.DataFrame()
        return pd.DataFrame()

    # ── ECM 读方法（get_sector_heat 调用）──
    def get_cached_sector_fund_heat(self, stat_date=None):
        df = self._query_shard('sector_fund_heat_cache', 'SELECT *', [])
        if stat_date is not None:
            df = df[df['stat_date'] == stat_date] if not df.empty else df
        if df is not None and not df.empty:
            result = {}
            for _, r in df.iterrows():
                result[str(r.get('industry', ''))] = {
                    'net_inflow_5d': float(r.get('net_inflow_5d', 0.0)),
                    'circ_mv': float(r.get('circ_mv', 0.0)),
                    'ratio': float(r.get('ratio', 0.0)),
                    'rank': int(r.get('rank', -1)),
                    'heat_level': str(r.get('heat_level', 'none')),
                }
            return result
        return {}

    def get_cached_sector_heat(self, stat_date=None):
        df = self._query_shard('sector_heat_cache', 'SELECT *', [])
        if stat_date is not None:
            df = df[df['stat_date'] == stat_date] if not df.empty else df
        if df is not None and not df.empty:
            result = {}
            for _, r in df.iterrows():
                result[str(r.get('industry', ''))] = {
                    'heat_level': str(r.get('heat_level', 'none')),
                    'strength': float(r.get('strength', 0.0)),
                    'rank': int(r.get('rank', -1)),
                    'stock_count': int(r.get('stock_count', 0)),
                }
            return result
        return {}


def test_ecm_sector_fund_heat_roundtrip():
    """cache_sector_fund_heat 写入 → get_cached_sector_fund_heat 读取。"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    shard = _FakeECMShard()
    ecm._exec_shard = shard._exec_shard
    ecm._query_shard = shard._query_shard
    ecm.cache_sector_fund_heat([
        {'industry': '造纸', 'net_inflow_5d': 107722.0, 'circ_mv': 2e8,
         'ratio': 0.5631, 'rank': 1, 'heat_level': 'top_10'},
        {'industry': '渔业', 'net_inflow_5d': 9647.0, 'circ_mv': 2e7,
         'ratio': 0.4787, 'rank': 2, 'heat_level': 'top_10'},
    ], stat_date='2026-10-19')
    got = ecm.get_cached_sector_fund_heat()
    assert '造纸' in got and '渔业' in got
    assert got['造纸']['ratio'] == 0.5631
    assert got['造纸']['heat_level'] == 'top_10'
    assert got['渔业']['rank'] == 2
    # 按日替换：同日重写后旧行业消失
    ecm.cache_sector_fund_heat(
        [{'industry': '黄金', 'net_inflow_5d': 1.0, 'circ_mv': 1.0,
          'ratio': 0.1, 'rank': 1, 'heat_level': 'top_10'}], stat_date='2026-10-19')
    got2 = ecm.get_cached_sector_fund_heat()
    assert set(got2.keys()) == {'黄金'}


def test_dashboard_get_sector_heat_prefers_fund(monkeypatch):
    """get_sector_heat 优先资金热度表（方向 B）；资金表为空时回退趋势表。"""
    svc = DashboardService()
    ecm = _FakeECMShard()
    # 资金表有数据
    ecm._exec_shard('sector_fund_heat_cache', 'DELETE', ['2026-10-19'])
    ecm._exec_shard('sector_fund_heat_cache', 'INSERT', [
        '2026-10-19', '造纸', 107722.0, 2e8, 0.5631, 1, 'top_10'])
    svc._data_manager = type('_DM', (), {'cache': ecm})()
    res = svc.get_sector_heat(top_n=8)
    assert res is not None
    assert res['source'].find('fund') >= 0
    assert res['sectors'][0]['industry'] == '造纸'
    assert res['sectors'][0]['ratio'] == 0.5631


def test_dashboard_get_sector_heat_fallback_trend():
    """资金表为空 → 回退趋势表（sector_heat_cache：strength/stock_count 字段）。"""
    svc = DashboardService()
    ecm = _FakeECMShard()
    ecm._heat_rows.append({
        'stat_date': '2026-10-19', 'industry': '出版业',
        'heat_level': 'top_10', 'strength': 0.7931, 'rank': 1, 'stock_count': 29,
    })
    svc._data_manager = type('_DM', (), {'cache': ecm})()
    res = svc.get_sector_heat(top_n=8)
    assert res is not None
    assert res['source'].find('sector_heat_cache') >= 0  # 趋势表（非 fund）
    assert res['sectors'][0]['industry'] == '出版业'
    assert res['sectors'][0]['strength'] == 0.7931


# ──────────────────────────────────────────────
# 批次3：_get_sector_history_20d
# ──────────────────────────────────────────────
class _FakeECMHist:
    def __init__(self):
        self._dates = ['2026-10-16', '2026-10-19']
        self._rows = [
            # (date, ts_code, pct_chg)
            ('2026-10-16', 'A.SH', 1.0), ('2026-10-16', 'B.SH', -0.5),
            ('2026-10-19', 'A.SH', 2.0), ('2026-10-19', 'B.SH', -1.0),
            ('2026-10-19', 'C.SZ', 3.0),
        ]

    def _query_shard(self, table, sql, params=None):
        params = params or []
        if 'DISTINCT trade_date' in sql:
            return pd.DataFrame({'trade_date': self._dates})
        if 'WHERE trade_date IN' in sql:
            return pd.DataFrame(self._rows, columns=['trade_date', 'ts_code', 'pct_chg'])
        return pd.DataFrame()


def _mk_hist_session(monkeypatch):
    ind = {
        'A.SH': '半导体', 'B.SH': '银行', 'C.SZ': '半导体',
        # 填充行业（不参与数据聚合，仅越过生产代码 len(industry_map)<10 门槛）
        'X1.SH': '其他', 'X2.SH': '其他', 'X3.SH': '其他', 'X4.SH': '其他',
        'X5.SH': '其他', 'X6.SH': '其他', 'X7.SH': '其他',
    }

    class _Stock:
        def __init__(self, ts_code, industry):
            self.ts_code = ts_code
            self.industry = industry

    stock_rows = [_Stock(k, v) for k, v in ind.items()]

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


def test_get_sector_history_20d(monkeypatch):
    """_get_sector_history_20d：dates 升序、每行业逐日序列、全市场 avg 基准线。"""
    _mk_hist_session(monkeypatch)
    svc = DashboardService()
    svc._data_manager = type('_DM', (), {'cache': _FakeECMHist()})()
    res = svc._get_sector_history_20d(days=2)
    assert res.get('dates') == ['2026-10-16', '2026-10-19']
    assert set(res['industries'].keys()) == {'半导体', '银行'}
    # 半导体 10-16 平均 (1.0+(-0.5? 不，B 属银行))——A.SH=1.0 仅 A → 1.0；C.SZ 属半导体
    # 10-16 半导体：A.SH 1.0 → [1.0, (2.0+3.0)/2=2.5]
    assert res['industries']['半导体'] == [1.0, 2.5]
    # 银行：B.SH [-0.5, -1.0]
    assert res['industries']['银行'] == [-0.5, -1.0]
    # 全市场 avg：10-16 (1.0-0.5)/2=0.25；10-19 (2.0-1.0+3.0)/3≈1.33
    assert abs(res['avg'][0] - 0.25) < 1e-6
    assert abs(res['avg'][1] - 1.33) < 0.01


def test_get_sector_history_20d_failure_returns_empty():
    """异常回退空 dict（不阻断主接口）。"""
    class _Bad:
        def _query_shard(self, *a, **k):
            raise RuntimeError('db down')

    svc = DashboardService()
    svc._data_manager = type('_DM', (), {'cache': _Bad()})()
    assert svc._get_sector_history_20d() == {}
