"""428 号方案三处缺口修复测试（2026-09-13 补）

覆盖 428 方案核查发现的 3 处未闭环缺口：
- 缺口1动作②：RAW-2 每 500 只进度日志（源码/运行时断言，重依赖引擎不做全量重放）
- 缺口1动作③：RAW-2 单股特征提取移入 `_raw2_one` 闭包 + `_run_with_timeout(60s)` 包裹
- 缺口2：`_batch_fina_indicator` 补本地最新期增量跳过（第 4 张表，缺失此前仅覆盖三表）
- 缺口3：`tushare_provider._ts` 显式日期空返回告警（此前仅 data_daemon._ts 有）

全部故障注入、不碰开发基准数据目录（临时目录/内存）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd


# ── 缺口3：tushare_provider._ts 空返回告警 ─────────────────

def test_ts_empty_return_warns(caplog):
    """显式日期 + 空 DataFrame → [Tushare空返回] 告警（与 data_daemon._ts 同版）"""
    from app.data import tushare_provider as tp
    import logging
    def fake(*a, **k):
        return pd.DataFrame()
    with caplog.at_level(logging.WARNING, logger='app.data.tushare_provider'):
        out = tp._ts(fake, trade_date='20260911')
    assert out is not None and out.empty
    assert any('[Tushare空返回]' in r.message and 'trade_date' in r.message
               for r in caplog.records)


def test_ts_no_explicit_date_no_warn(caplog):
    """无显式日期 → 不告警"""
    from app.data import tushare_provider as tp
    import logging
    def fake(*a, **k):
        return pd.DataFrame()
    with caplog.at_level(logging.WARNING, logger='app.data.tushare_provider'):
        out = tp._ts(fake, limit=10)
    assert out is not None and out.empty
    assert not any('Tushare空返回' in r.message for r in caplog.records)


def test_ts_date_normalized_before_call():
    """横杠日期在调用前被归一为紧凑 YYYYMMDD"""
    from app.data import tushare_provider as tp
    seen = {}
    def fake(**kwargs):
        seen.update(kwargs)
        return pd.DataFrame({'x': [1]})
    tp._ts(fake, trade_date='2026-09-11')
    assert seen['trade_date'] == '20260911'


# ── 缺口2：_batch_fina_indicator 增量跳过（第 4 张表）───────

class _FakeFinaPro:
    """fake pro：stock_basic 返回 1 只；fina_indicator 若被调用则返回 DataFrame"""

    def __init__(self, called: dict):
        self.called = called

    def stock_basic(self, exchange='', list_status='L'):
        return pd.DataFrame({'ts_code': ['000001.SZ']})

    def fina_indicator(self, ts_code=None, **kwargs):
        self.called['fina'] = True
        return pd.DataFrame({
            'ts_code': [ts_code],
            'end_date': ['2026-06-30'],
            'ann_date': ['2026-08-15'],
            'eps': [1.24],
        })


def _make_fake_fina_env(monkeypatch, covers_result):
    """注入 _batch_fina_indicator 依赖：_ts / pro_api / _target_fin_period /
    _finance_covers_period / _ecm（不碰开发基准库）"""
    import data_daemon as dd
    called = {}
    fake_pro = _FakeFinaPro(called)
    monkeypatch.setattr(dd, '_target_fin_period', lambda: '2026-06-30')
    monkeypatch.setattr(dd, '_finance_covers_period',
                        lambda t, c, tp_: covers_result)
    monkeypatch.setattr(dd, '_get_tushare_provider', lambda: None)
    monkeypatch.setattr(dd, '_ts', lambda f, *a, **k: f(*a, **k))
    import tushare as ts_mod
    orig = ts_mod.pro_api
    monkeypatch.setattr(ts_mod, 'pro_api', lambda: fake_pro)
    monkeypatch.setattr(dd, '_ecm', type('_E', (), {
        'cache_fina_indicator_data': lambda self, df: True,
    })())
    return called, fake_pro


def test_fina_indicator_skip_lastest_period(monkeypatch, caplog):
    """本地已覆盖目标报告期 → 全部跳过，不调 fina_indicator（缺口2）"""
    import data_daemon as dd
    import logging
    called, fake_pro = _make_fake_fina_env(monkeypatch, covers_result=True)
    with caplog.at_level(logging.INFO):
        total = dd._batch_fina_indicator()
    assert total == 0
    assert fake_pro.called.get('fina') is not True, '已有最新期不得再调 API'
    assert any('跳过 1 只已有最新期' in r.message for r in caplog.records)


def test_fina_indicator_calls_when_not_covered(monkeypatch):
    """本地未覆盖目标报告期 → 逐只拉取并计数（缺口2 不影响缺数据场景）"""
    import data_daemon as dd
    called, fake_pro = _make_fake_fina_env(monkeypatch, covers_result=False)
    total = dd._batch_fina_indicator()
    assert total == 1
    assert fake_pro.called.get('fina') is True


def test_fina_indicator_target_none_no_skip(monkeypatch):
    """target 推导失败(None) → _finance_covers_period 不跳过（安全降级为全量拉取）"""
    import data_daemon as dd
    called, fake_pro = _make_fake_fina_env(monkeypatch, covers_result=False)
    # target=None 时用真实 _finance_covers_period：内部对 falsy 直接返回 False
    real_fcp = dd._finance_covers_period
    monkeypatch.setattr(dd, '_target_fin_period', lambda: None)
    monkeypatch.setattr(dd, '_finance_covers_period',
                        lambda t, c, tp_: real_fcp(t, c, tp_))
    total = dd._batch_fina_indicator()
    assert total == 1
    assert fake_pro.called.get('fina') is True


def test_finance_covers_period_none_target(monkeypatch):
    """_finance_covers_period 对 None target 返回 False（不跳过）"""
    import data_daemon as dd
    assert dd._finance_covers_period('fina_indicator_cache', '000001.SZ', None) is False


# ── 缺口1动作②：RAW-2 进度日志占位断言 ──────────────────
# 进度日志在 _precompute_raw_features 循环内（每 500 只），依赖 Flask 全量引擎，
# 不做全量重放；此处以源码语义断言确保格式存在（防回归丢失）。

def test_raw2_progress_log_format_present():
    """RAW-2 循环内存在每 500 只进度日志格式（缺口1动作②防回归）"""
    import data_daemon as dd
    import inspect
    src = inspect.getsource(dd._precompute_raw_features)
    assert '[RAW-2] 进度' in src, 'RAW-2 缺少每 500 只进度日志'
    assert '_progress_n % 500 == 0' in src or '% 500' in src, '进度日志应每 500 只触发'


# ── 缺口1动作③：RAW-2 单股超时（_run_with_timeout 包裹）──────
# 单股特征提取移入 _raw2_one 闭包，循环内用 _run_with_timeout(60s) 包裹，
# 超时/异常返回 None → 该只计 failed 并跳过，不中断全量（与 RAW-1 一致）。
# DB 写（cache_pre_feat / commit）留在超时线程之外（SQLite 非线程安全写）。

def test_run_with_timeout_available():
    """单股超时保护工具 _run_with_timeout 已存在，RAW-1/RAW-2 均已用"""
    import data_daemon as dd
    assert hasattr(dd, '_run_with_timeout')
    import inspect
    src = inspect.getsource(dd)
    assert 'RAW-1 指标' in src, 'RAW-1 已用单股超时'
    assert 'RAW-2 特征' in src, 'RAW-2 已用单股超时（缺口1动作③）'


def test_raw2_uses_run_with_timeout():
    """缺口1动作③：RAW-2 循环内以 _run_with_timeout 包裹单股特征提取

    源码断言（防回归）：
    - 存在 _raw2_one 闭包且以 `_run_with_timeout(_raw2_one, timeout_sec=60.0` 调用；
    - DB 写（cache_pre_feat）与 commit 位于超时调用**之外**（SQLite 写不在子线程）。
    """
    import data_daemon as dd
    import inspect
    src = inspect.getsource(dd._precompute_raw_features)
    assert '_raw2_one' in src, '应存在 _raw2_one 单股闭包'
    assert 'timeout_sec=60.0' in src, '单股超时阈值应为 60s（与 RAW-1 一致）'
    # 超时调用在 for 循环内
    assert 'def _raw2_one' in src and 'for code in codes:' in src
    # cache_pre_feat 写必须在 _run_with_timeout 调用之后、同一循环层（超时线程之外）
    t_idx = src.find('_run_with_timeout(_raw2_one')
    w_idx = src.find('_ecm.cache_pre_feat')
    assert t_idx != -1 and w_idx != -1 and t_idx < w_idx, \
        'cache_pre_feat 应位于超时调用之后（写不在超时线程内）'
