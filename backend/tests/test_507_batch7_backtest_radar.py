"""507号批次7：潜伏 + 非管道修复验证（#S6/#S8/#S10）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §三。

覆盖：
  #S6 StatusEngine.evaluate 新增 asof_date 历史求值（读该日 pre_feat/signal_detail
      历史快照 + 历史收盘价），backtest 逐日传历史 dim_results + asof_date——
      消除原「逐日调用返回同一当前状态」前视偏差；param_stability_check 明确报错
      （JUD_PARAM_* 无消费方，防静默无效）
  #S8 dim4 BenchmarkService 未导入——已随批次6 死副本删除自动关闭（断言无残留）
  #S9 get_risk_tags roce 键——dim4 死副本已删；framework 版同为死方法（断言全仓无调用方）
  #S10 radar 排序后截断 + Top-N 取名（原 candidates[:200] 排序前截断致 Top-N 失效）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

# ── #S6 evaluate asof_date 数据源选择 ─────────────────────

def _mk_status_engine(monkeypatch, cache):
    """object.__new__ 构造 StatusEngine（绕过 __init__），注入 fake dm/cache"""
    from types import SimpleNamespace

    from app.opportunity_atlas.status_engine import StatusEngine

    se = object.__new__(StatusEngine)
    se.dm = SimpleNamespace(cache=cache, get_cached_daily_data=lambda ts_code: None)
    se.registry = {}
    se.cfg = {}
    return se


class _Cache:
    """记录调用参数的最小 fake cache"""

    def __init__(self):
        self.calls = []

    def get_pre_feat(self, ts_code, trade_date=None):
        self.calls.append(('pre_feat', trade_date))
        return {'valuation': {'valuation_level': 'fair'}}

    def get_latest_signal_detail(self, ts_code):
        self.calls.append(('latest_signal_detail', None))
        return {'signals': {'sig': 1}}

    def get_signal_detail(self, ts_code, trade_date=None):
        self.calls.append(('signal_detail', trade_date))
        return {'signals': {'sig': 1}}


def test_s6_load_tags_uses_asof_date():
    """_load_tags(asof_date) 按该日期读 pre_feat（YYYY-MM-DD 归一化）"""
    cache = _Cache()
    se = _mk_status_engine(None, cache)
    tags = se._load_tags('000001.SZ', asof_date='2026-09-30')
    assert tags.get('valuation_level') == 'fair'
    assert ('pre_feat', '2026-09-30') in cache.calls, cache.calls


def test_s6_load_tags_defaults_latest():
    """_load_tags 缺省 asof_date → 读最新（trade_date=None）"""
    cache = _Cache()
    se = _mk_status_engine(None, cache)
    se._load_tags('000001.SZ')
    assert ('pre_feat', None) in cache.calls, cache.calls


def test_s6_load_signals_uses_asof_date_compact():
    """_load_signals(asof_date) 按该日期读 signal_detail（YYYYMMDD 归一化）"""
    cache = _Cache()
    se = _mk_status_engine(None, cache)
    sig = se._load_signals('000001.SZ', asof_date='2026-09-30')
    assert sig == {'sig': 1}
    assert ('signal_detail', '20260930') in cache.calls, cache.calls


def test_s6_load_signals_defaults_latest():
    """_load_signals 缺省 asof_date → get_latest_signal_detail"""
    cache = _Cache()
    se = _mk_status_engine(None, cache)
    se._load_signals('000001.SZ')
    assert ('latest_signal_detail', None) in cache.calls, cache.calls


def test_s6_signal_lifecycle_uses_asof_close():
    """_signal_lifecycle(asof_date) 用截至该日的收盘价（回测消除前视）"""
    from app.opportunity_atlas.status_engine import StatusEngine

    se = object.__new__(StatusEngine)
    idx = pd.date_range('2026-09-01', periods=30, freq='B')
    df = pd.DataFrame({
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
        'close': list(range(10, 40)),
    })

    class _FakeDM:
        cache = None

        def get_cached_daily_data(self, ts_code):
            return df

    se.dm = _FakeDM()
    se.registry = {}
    tags = {'active_signal': {'date': '2026-09-01', 'price': 10.0}}
    # asof_date=2026-09-07（周一交易日，第 5 行）→ 收盘价 14 → dist_pct=40%（中期）
    lc = se._signal_lifecycle('000001.SZ', tags, {}, asof_date='2026-09-07')
    assert lc is not None
    assert abs(lc['dist_pct'] - 40.0) < 0.1, lc


def test_s6_evaluate_accepts_asof_date(monkeypatch):
    """evaluate 签名接受 asof_date，且内部按 asof_date 读历史快照"""
    from app.opportunity_atlas.status_engine import StatusEngine

    cache = _Cache()
    se = _mk_status_engine(None, cache)
    # 截断 evaluate 下游（L0/L2/dim8/assemble 不在此测），只验证数据源选择
    monkeypatch.setattr(se, '_build_dim_engine_results',
                        lambda tags, signals, dims, lifecycle, ts_code=None: {})
    monkeypatch.setattr(se, '_convert_to_dims_format', lambda dr, tags: {})
    monkeypatch.setattr(se, '_apply_l0', lambda *a, **k: {})
    monkeypatch.setattr(se, '_aggregate_v390',
                        lambda tags, dims, l0, lifecycle, dim_engine_results, ts_code: {})
    monkeypatch.setattr(se, '_detect_registered_signals', lambda *a: [])
    monkeypatch.setattr(se, '_assemble',
                        lambda *a, **k: {'opportunity_state': 'wait'})
    from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
    monkeypatch.setattr(Dim8SummaryEngine, 'evaluate', lambda self, **k: None)
    se.cfg = {'jud_engine_version': 'v390'}  # 走 _aggregate_v390（已 patch），跳过 legacy _aggregate

    r = se.evaluate('000001.SZ', asof_date='2026-09-30')
    assert r == {'opportunity_state': 'wait'}
    assert ('pre_feat', '2026-09-30') in cache.calls
    assert ('signal_detail', '20260930') in cache.calls
    # 缺省 asof_date → 读最新
    cache.calls.clear()
    se.evaluate('000001.SZ')
    assert ('pre_feat', None) in cache.calls
    assert ('latest_signal_detail', None) in cache.calls


# ── #S6 backtest 逐日历史求值 ─────────────────────────────

def test_s6_backtest_passes_asof_and_dim_results(monkeypatch):
    """backtest run() 逐日传历史 dim_results + asof_date（前视修复）"""
    import app.opportunity_atlas.backtest_minimal as bt
    from app.opportunity_atlas.status_engine import StatusEngine

    idx = pd.date_range('2026-09-01', periods=5, freq='B')
    df = pd.DataFrame({
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
        'close': [10, 11, 12, 13, 14],
    })

    class _FakeCache:
        def get_signal_detail(self, ts_code, trade_date=None):
            return {'dim_results': {'signal': {'hist': trade_date}}}

    class _FakeDM:
        cache = _FakeCache()

        def get_cached_daily_data(self, ts_code):
            return df

    calls = []

    def _fake_evaluate(self, ts_code, dim_results=None, asof_date=None):
        calls.append((ts_code, dim_results, asof_date))
        return {'opportunity_state': 'enter', 'consensus_rate': 0.8,
                'direction': 'bullish'}

    monkeypatch.setattr(StatusEngine, 'evaluate', _fake_evaluate)
    b = bt.MinimalBacktester(dm=_FakeDM())
    r = b.run('000001.SZ')
    assert len(calls) == 5, f'应逐日求值 5 次: {calls}'
    # 每行传当日 asof_date + 该日历史 dim_results（YYYYMMDD）
    for i, (ts, dr, asof) in enumerate(calls):
        assert asof == df['trade_date'].iloc[i]
        assert dr == {'signal': {'hist': df['trade_date'].iloc[i].replace('-', '')}}
    assert r['summary']['enter_count'] == 5


def test_s6_param_stability_check_raises():
    """param_stability_check 明确报错（JUD_PARAM_* 无消费方，防静默无效）"""
    # 仅验证方法本身抛 ValueError（不跑真实回测）
    import inspect

    from app.opportunity_atlas.backtest_minimal import MinimalBacktester
    src = inspect.getsource(MinimalBacktester.param_stability_check)
    assert 'raise ValueError' in src, '应明确抛错而非静默无效'
    assert 'JUD_PARAM_' in src


# ── #S8 / #S9 已随批次6 关闭 ──────────────────────────────

def test_s8_dim4_no_benchmark_service_reference():
    """dim4 已无 BenchmarkService 引用（死副本删除自动关闭 #S8）"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'opportunity_atlas', 'dimensions',
                        'dim4_chip_fund_engine.py')
    src = open(path, encoding='utf-8').read()
    assert 'BenchmarkService' not in src, '#S8 应已随死副本删除关闭'


def test_s9_dim4_dead_copy_removed_and_no_callers():
    """dim4 get_risk_tags 死副本已删；framework 版定义存在但全仓无调用方"""
    import importlib
    m = importlib.import_module('app.opportunity_atlas.dimensions.dim4_chip_fund_engine')
    assert not hasattr(m, 'get_risk_tags'), 'dim4 get_risk_tags 死副本应已删'
    import subprocess
    out = subprocess.run(['grep', '-rn', 'get_risk_tags(', 'app/'],
                         capture_output=True, text=True).stdout
    # 仅定义处一处（framework/chip_pre_filter.py:959），无任何调用方
    assert out.count('def get_risk_tags') == 1
    assert out.count('get_risk_tags(') == 1, f'应仅定义无调用: {out}'


# ── #S10 radar 排序后截断 + Top-N 取名 ─────────────────────

def test_s10_radar_top_n_after_sort(monkeypatch):
    """radar 排序后截断：排位 200 之后的高强度股票进入 Top-N；取名仅限 Top-N"""
    from app.opportunity_atlas.radar_service import RadarService

    n = 250
    codes = [f'{i:06d}.SZ' for i in range(n)]

    class _FakeCache:
        def _query_df(self, sql):
            return pd.DataFrame({'ts_code': codes})

        def get_tags_batch(self, ts_codes):
            # 509号 #J23：get_tags_batch 分块调用后，强度须与分批无关（股票固有属性），
            #   故按 ts_code 序号（非批内索引）赋强度——最强股票恒定 = 末位（249）
            tags = {}
            for c in ts_codes:
                idx = int(c.split('.')[0])
                # 第 250 只（原排序前截断会漏掉）信号最强
                tags[c] = {'signal_strength': str(idx + 1)}
            return tags

    class _FakeDM:
        cache = _FakeCache()

        def get_library_ts_codes(self):
            return []

    name_calls = []

    def _fake_name(ts_code):
        name_calls.append(ts_code)
        return f'name_{ts_code}'

    radar = object.__new__(RadarService)
    monkeypatch.setattr(radar, '_get_dm', lambda: _FakeDM())
    monkeypatch.setattr(radar, '_safe_float',
                        lambda v, d: float(v) if v is not None else d)
    monkeypatch.setattr(radar, '_get_stock_name', _fake_name)

    top = radar.get_radar_signals(limit=5)
    assert len(top) == 5
    # 最强（第 250 只）应进入 Top-5
    assert top[0]['ts_code'] == f'{n - 1:06d}.SZ', '排序后截断失效'
    assert top[0]['name'] == f'name_{n - 1:06d}.SZ'
    # 取名仅 5 次（消除全量 N+1）
    assert len(name_calls) == 5, f'应仅对 Top-N 取名: {len(name_calls)}'
