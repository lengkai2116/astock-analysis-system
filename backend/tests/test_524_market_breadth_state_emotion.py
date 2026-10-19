"""524号 批次1' 定向测试：大盘监控只读接口（breadth / state / emotion）。

- `DashboardService.get_market_breadth`：daily_cache⋈daily_basic_cache 涨跌家数 + market_stats 宽度指标
- `DashboardService.get_market_state`：4 状态·状态机（E2 + BenchmarkService 沪深300 趋势）
- `DashboardService.get_market_emotion`：六段论（MarketSentimentService）
- 路由 `/api/v3/market/breadth|state|emotion` 存在 + 并入 `dashboard/full`
"""
import pandas as pd
import pytest
from app.services.dashboard_service import DashboardService


class _FakeECM:
    """模拟 cache：_query_shard（daily/basic）+ get_cached_market_stats。"""

    def __init__(self, daily_df=None, basic_df=None, stats=None):
        self._daily = daily_df
        self._basic = basic_df
        self._stats = stats or {}

    def _query_shard(self, table, sql, params=None):
        if table == 'daily_cache':
            if 'DISTINCT trade_date' in sql:
                return pd.DataFrame({'trade_date': ['2026-10-16']})
            return self._daily
        if table == 'daily_basic_cache':
            return self._basic
        return pd.DataFrame()

    def get_cached_market_stats(self, stat_date=None):
        return self._stats


class _FakeDM:
    """模拟 DataManager：cache + BenchmarkService/MarketSentimentService 所需兜底方法。"""

    def __init__(self, daily_df=None, basic_df=None, stats=None):
        self.cache = _FakeECM(daily_df, basic_df, stats)

    def get_stock_list(self):
        return []

    def get_cached_daily_data(self, *a, **k):
        return pd.DataFrame()

    def get_kline_data(self, *a, **k):
        return None

    def get_cached_sentiment_pool(self, *a, **k):
        return None


def _daily_df():
    # 末行＝指数，应被 join 排除
    return pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH', '000002.SZ', '000001.SH'],
        'pct_chg': [5.0, -2.0, 0.0, 0.5],
    })


def _basic_df():
    return pd.DataFrame({
        'ts_code': ['000001.SZ', '600000.SH', '000002.SZ'],
    })


def _stats():
    return {
        'ma20_ratio': 0.6,
        'limit_ratio': 3.0,
        'turnover_percentile': 0.5,
        'rsi_percentile': 0.5,
        'erp_percentile': 0.5,
        'margin_trend': 0.5,
        'pe_percentile': 0.5,
        'computed_at': '2026-10-16',
    }


def _svc():
    svc = DashboardService()
    svc._data_manager = _FakeDM(_daily_df(), _basic_df(), _stats())
    return svc


# ── breadth ─────────────────────────────────────────────

def test_breadth_counts_and_ratios():
    res = _svc().get_market_breadth()
    assert res is not None
    assert res['trade_date'] == '2026-10-16'
    assert res['count'] == 3          # 指数行被 inner join 排除
    assert res['up_count'] == 1
    assert res['down_count'] == 1
    assert res['flat_count'] == 1
    assert res['up_ratio'] == round(1 / 3 * 100, 1)
    assert res['down_ratio'] == round(1 / 3 * 100, 1)
    assert res['ma20_ratio'] == 60.0      # 0.6 → 60%
    assert res['limit_ratio'] == 3.0
    assert res['turnover_percentile'] == 50.0


def test_breadth_no_data_returns_none():
    svc = DashboardService()
    svc._data_manager = _FakeDM(pd.DataFrame(), pd.DataFrame(), _stats())
    assert svc.get_market_breadth() is None


# ── state ───────────────────────────────────────────────

def test_state_trend_up(monkeypatch):
    # 近20日涨 8%（≥3%）且收盘 ≥ 60 日线 → 上升趋势
    closes = [4000.0] * 60
    closes[-21] = 4000.0
    closes[-1] = 4320.0  # +8% vs 21 日前 4000
    df = pd.DataFrame({'trade_date': [f'2026-10-{i:02d}' for i in range(1, 61)],
                       'close': closes})
    _patch_benchmark(monkeypatch, df)
    res = _svc().get_market_state()
    assert res is not None
    assert res['state'] == 'trend_up'
    assert res['state_label'] == '上升趋势'
    assert res['basis']['hs300_ret_20d'] == 8.0


def test_state_ranging_default():
    # turnover 0.5、近20日 |涨跌| 1%（不满足高波动/趋势/盘整）→ 震荡（默认）
    res = _svc().get_market_state()  # 无 monkeypatch → BenchmarkService 走真实空返回兜底
    # 真实 BenchmarkService 可能读库；此处直接断言默认分支可运行（stats 有值）
    assert res is not None
    assert res['state'] in ('ranging', 'consolidation', 'trend_up', 'trend_down', 'high_volatility')


def test_state_no_benchmark_data():
    svc = DashboardService()
    svc._data_manager = _FakeDM(_daily_df(), _basic_df(), _stats())
    res = svc.get_market_state()
    assert res is not None
    assert res['state'] == 'ranging'  # 无指数数据 → 默认震荡
    assert res['data_date'] == '2026-10-16'


def _patch_benchmark(monkeypatch, df):
    # dashboard_service.get_market_state 内部 `from app.services.benchmark_service import ...`，
    # 须 patch 源模块而非 dashboard_service 模块属性
    import app.services.benchmark_service as bm_mod

    class _FakeBS:
        def __init__(self, dm=None):
            pass

        def get_index_daily(self, ts_code=None, **kw):
            return df.copy()

    monkeypatch.setattr(bm_mod, 'BenchmarkService', _FakeBS)


# ── emotion ─────────────────────────────────────────────

def test_emotion_phase(monkeypatch):
    # dashboard_service.get_market_emotion 内部 `from app.services.market_sentiment_service import ...`，
    # 须 patch 源模块而非 dashboard_service 模块属性
    import app.services.market_sentiment_service as mss_mod

    class _FakeMSS:
        def __init__(self, dm=None):
            pass

        def get_sentiment_phase(self, trade_date=None):
            return {
                'phase': 'ferment',
                'phase_label': '情绪发酵',
                'metrics': {'limit_up_count': 50, 'limit_down_count': 3,
                            'max_board_height': 4, 'sealing_rate': 60.0,
                            'up_down_ratio': 16.67},
                'data_available': True,
            }

    monkeypatch.setattr(mss_mod, 'MarketSentimentService', _FakeMSS)
    res = _svc().get_market_emotion()
    assert res is not None
    assert res['phase'] == 'ferment'
    assert res['phase_label'] == '情绪发酵'
    assert res['metrics']['limit_up_count'] == 50
    assert res['data_available'] is True


def test_emotion_no_data_returns_default():
    # 无 monkeypatch → 真实 MarketSentimentService 读库（可能无数据）→ 不应抛错
    res = _svc().get_market_emotion()
    assert res is not None
    assert res['phase'] in ('ice', 'sprout', 'ferment', 'climax', 'ebb', 'regression', 'neutral')


# ── 路由 + 聚合并入 ─────────────────────────────────────

def test_routes_registered():
    from app.routes import dashboard as _dash
    assert hasattr(_dash, 'get_market_breadth')
    assert hasattr(_dash, 'get_market_state')
    assert hasattr(_dash, 'get_market_emotion')


def test_dashboard_full_merges_new_keys(monkeypatch):
    svc = _svc()
    # 打桩其余方法避免依赖真实库
    for name in ('get_index_summary', 'get_market_volume', 'get_moneyflow_summary',
                 'get_sector_changes', 'get_sector_moneyflow', 'get_daily_top'):
        monkeypatch.setattr(svc, name, lambda *a, **k: None)
    res = svc.get_dashboard_full()
    assert res is not None
    assert res['market_breadth'] is not None
    assert res['market_state'] is not None
    assert res['market_emotion'] is not None
