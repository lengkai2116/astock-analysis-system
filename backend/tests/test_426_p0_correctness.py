"""426号方案阶段一：P0 正确性修复测试（P0-1 假数据 / P0-2 MA 守卫 / P0-3 QA 门禁）

故障注入式测试：不依赖真实数据库——monkeypatch 注入分库读取/连接与计数，
避免污染生产数据（data/ 下真实分库）。覆盖 §10 阶段一 1.1~1.3 检验标准：
- P0-1：源查询走 _shard_fetchall；源表空壳/无当日数据 → None + 告警 + 不落库；
- P0-2：len<250（无 ma120/ma250 列）df 仍写 indicator_ma（核心列守卫）；
- P0-3：indicator_ma rows_ratio=0.99；ma/macd 跨表对齐 ≤0.1%；market_stats 常量守卫。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_daemon as dd
import numpy as np
import pandas as pd
import pytest
from app.data.stg_quality import QUALITY_RULES, CheckResult, QualityChecker

# ── P0-1：_precompute_market_stats 分库读取 + 假值显式化 ─────────

class _FakeECM:
    """记录 cache_market_stats 调用的假 ECM"""

    def __init__(self):
        self.persisted = []

    def cache_market_stats(self, stats):
        self.persisted.append(dict(stats))


def _make_shard_dispatcher(rows_by_fragment):
    """构造 _shard_fetchall 假实现：按 SQL 特征片段返回行集"""
    def _fake(table, sql, params=None):
        for frag, rows in rows_by_fragment.items():
            if frag in sql:
                return rows
        return []
    return _fake


def _patch_precompute_env(monkeypatch, shard_dispatcher, row_count=1000, ecm=None):
    """注入 _precompute_market_stats 依赖：分库行数 + 分库查询 + 假 ECM"""
    monkeypatch.setattr(dd, '_ensure_ecm', lambda: None)
    fake_ecm = ecm or _FakeECM()
    monkeypatch.setattr(dd, '_ecm', fake_ecm)
    monkeypatch.setattr(dd, '_market_stats_cache', {})
    monkeypatch.setattr(dd, '_shard_fetchall', shard_dispatcher)
    import app.data.sharding_manager as sm
    monkeypatch.setattr(sm.sharding_manager, 'get_table_row_count', lambda t: row_count)
    return fake_ecm


GOOD_SHARD_ROWS = {
    'SMA_20': [(100, 60)],                          # ma20: 60/100 = 0.6
    'turnover_rate': [(0.05,), (0.08,)],            # 今日 0.05 / 60日 0.08 = 0.625
    'high_limit': [(5, 2)],                         # 涨跌停 5/2 = 2.5
    'rsi14': [(55.0,), (50.0,)],                    # (55-30)/40 = 0.625
    'pe_ttm': [(15.0,), (12.0,)],                   # erp=(1/15)/(1/12)=0.8；pe=15/12→1.0
    'rzye': [('2026-09-10', 110.0), ('2026-09-09', 100.0),
             ('2026-09-08', 95.0), ('2026-09-07', 90.0), ('2026-09-06', 85.0)],
    # margin_trend: (110-85)/85≈0.294 → 0.5+2.94 → 1.0
}


def test_p0_1_real_values_persisted(monkeypatch):
    """源数据齐备 → 7 项真实统计（非常量）落库 + 注入内存缓存"""
    ecm = _patch_precompute_env(monkeypatch, _make_shard_dispatcher(GOOD_SHARD_ROWS))
    dd._precompute_market_stats(target_date='2026-09-10')
    stats = dd._market_stats_cache
    assert stats['computed_at'] == '2026-09-10'
    vals = [stats[k] for k in ('ma20_ratio', 'turnover_percentile', 'limit_ratio',
                               'rsi_percentile', 'erp_percentile', 'margin_trend', 'pe_percentile')]
    assert all(v is not None for v in vals)
    assert len(set(vals)) > 1, '7 项不得全等（假值特征）'
    assert stats['ma20_ratio'] == pytest.approx(0.6)
    assert len(ecm.persisted) == 1
    assert ecm.persisted[0]['computed_at'] == '2026-09-10'


def test_p0_1_empty_source_no_persist(monkeypatch, caplog):
    """源表空壳（分库 0 行）→ 告警 + 不落库 + 不注入（假值显式化）"""
    _patch_precompute_env(monkeypatch, _make_shard_dispatcher(GOOD_SHARD_ROWS), row_count=0)
    with caplog.at_level('WARNING', logger='data_daemon'):
        dd._precompute_market_stats(target_date='2026-09-10')
    assert dd._market_stats_cache == {}
    assert dd._ecm.persisted == []
    assert any('源表为空壳或未登记' in r.message for r in caplog.records)


def test_p0_1_no_today_data_no_persist(monkeypatch, caplog):
    """源表有数据但当日无行 → 统计项 None + 告警 + 不落库"""
    _patch_precompute_env(monkeypatch, _make_shard_dispatcher({}))
    with caplog.at_level('WARNING', logger='data_daemon'):
        dd._precompute_market_stats(target_date='2026-09-10')
    assert dd._market_stats_cache == {}
    assert dd._ecm.persisted == []
    # 逐项"置 None"告警（daemon 去重过滤器仅影响重复消息，单项消息唯一保持 WARNING）
    assert any('置 None' in r.message for r in caplog.records)


# ── P0-2：cache_indicators_wide MA 核心列守卫 ─────────────────

def _make_wide_df(n, with_ma_long=False):
    """构造 n 根 K 线的指标宽表 df；with_ma_long 时含 ma120/ma250（模拟 len>=250 引擎产出）"""
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    df = pd.DataFrame({
        'trade_date': [d.strftime('%Y-%m-%d') for d in idx],
        'ma5': np.random.rand(n), 'ma10': np.random.rand(n),
        'ma20': np.random.rand(n), 'ma30': np.random.rand(n),
        'ma60': np.random.rand(n),
        'macd_dif': np.random.rand(n), 'macd_dea': np.random.rand(n), 'macd_hist': np.random.rand(n),
        'rsi14': np.random.rand(n) * 100, 'kdj_k': np.random.rand(n),
        'kdj_d': np.random.rand(n), 'kdj_j': np.random.rand(n),
        'boll_upper': np.random.rand(n), 'boll_mid': np.random.rand(n), 'boll_lower': np.random.rand(n),
        'bbi': np.random.rand(n), 'ene_upper': np.random.rand(n), 'ene_lower': np.random.rand(n),
        'nine_buy': np.random.randint(0, 2, n), 'nine_sell': np.random.randint(0, 2, n),
        'vol_ma5': np.random.rand(n), 'vol_ma10': np.random.rand(n),
    })
    if with_ma_long:
        df['ma120'] = np.random.rand(n)
        df['ma250'] = np.random.rand(n)
    return df


def _make_ecm_with_mock_insert():
    from unittest import mock

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm._write_lock = mock.MagicMock()  # 支持 with 上下文管理器
    ecm._insert_from_df = mock.Mock()
    ecm.conn = mock.Mock()
    return ecm


def test_p0_2_ma_written_without_ma250():
    """len=100（无 ma120/ma250）→ MA 组仍写入（核心列守卫；修复前整组不写）"""
    ecm = _make_ecm_with_mock_insert()
    ecm.cache_indicators_wide('000001.SZ', _make_wide_df(100))
    ma_calls = [c for c in ecm._insert_from_df.call_args_list if c.args[0] == 'indicator_ma']
    assert ma_calls, 'len<250 的 df 必须写 indicator_ma'
    ma_df = ma_calls[0].args[1]
    assert 'ma250' not in ma_df.columns and 'ma120' not in ma_df.columns
    assert {'ma5', 'ma10', 'ma20', 'ma60'} <= set(ma_df.columns)
    inserted = {c.args[0] for c in ecm._insert_from_df.call_args_list}
    assert {'indicator_macd', 'indicator_other'} <= inserted


def test_p0_2_ma_written_with_ma250():
    """len=300（含 ma120/ma250）→ MA 组含长均线列（语义不变）"""
    ecm = _make_ecm_with_mock_insert()
    ecm.cache_indicators_wide('000001.SZ', _make_wide_df(300, with_ma_long=True))
    ma_calls = [c for c in ecm._insert_from_df.call_args_list if c.args[0] == 'indicator_ma']
    assert ma_calls
    ma_df = ma_calls[0].args[1]
    assert {'ma120', 'ma250'} <= set(ma_df.columns)


def test_p0_2_no_core_ma_no_write():
    """连核心 MA 列都缺（极端 df）→ 不写 indicator_ma（macd/other 照常）"""
    ecm = _make_ecm_with_mock_insert()
    df = pd.DataFrame({'trade_date': ['2026-09-10'],
                       'macd_dif': [0.1], 'macd_dea': [0.2], 'macd_hist': [0.3],
                       'rsi14': [50.0], 'kdj_k': [0.5], 'kdj_d': [0.5], 'kdj_j': [0.5],
                       'boll_upper': [1.0], 'boll_mid': [0.9], 'boll_lower': [0.8],
                       'bbi': [0.9], 'ene_upper': [1.1], 'ene_lower': [0.7],
                       'nine_buy': [0], 'nine_sell': [1]})
    ecm.cache_indicators_wide('000001.SZ', df)
    inserted = {c.args[0] for c in ecm._insert_from_df.call_args_list}
    assert 'indicator_ma' not in inserted
    assert {'indicator_macd', 'indicator_other'} <= inserted


# ── P0-3：QA 门禁（rows_ratio 0.99 + ma/macd 对齐 + market_stats 常量守卫）──

def test_p0_3_rules_configured():
    assert QUALITY_RULES['indicator_ma']['rows_ratio'] == 0.99
    assert 'market_stats_cache' in QUALITY_RULES
    assert QUALITY_RULES['market_stats_cache']['check_mode'] == 'nonempty'
    assert len(QUALITY_RULES['market_stats_cache']['constant_guard']) == 7


def test_p0_3_ma_099_catches_2pct_gap(monkeypatch):
    """116 支缺口（5388/5553=97.0%）在 0.99 阈值下必须检出（0.95 曾漏检）"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5553)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 5388)
    r = checker.check_table('indicator_ma', '2026-09-11')
    assert not r.passed
    assert any('覆盖率不足' in i for i in r.issues)


def test_p0_3_ma_099_pass_full_day(monkeypatch):
    """修复后 ma==macd（5504/5553≈99.1%）→ 通过，无误报"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5553)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 5504)
    r = checker.check_table('indicator_ma', '2026-09-11')
    assert r.passed


def test_p0_3_cross_ma_macd_deviation_caught(monkeypatch):
    """ma=5388 vs macd=5504（偏差 2.1%）→ 跨表主检查检出（≤0.1%）"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5553)
    monkeypatch.setattr(checker, '_count_by_date',
                        lambda t, d: 5388 if t == 'indicator_ma' else 5504)
    results = checker.check_cross_table('2026-09-11')
    failed = [r for r in results if not r.passed]
    assert any(r.table == 'indicator_ma' and r.kind == 'cross' and 'indicator_macd' in r.issues[0]
               for r in failed)


def test_p0_3_cross_ma_macd_aligned_pass(monkeypatch):
    """ma==macd（5504）→ 跨表对齐通过，无误报"""
    checker = QualityChecker()
    monkeypatch.setattr(checker, 'daily_base', lambda d: 5553)
    monkeypatch.setattr(checker, '_count_by_date', lambda t, d: 5504)
    results = checker.check_cross_table('2026-09-11')
    assert all(r.passed for r in results)


# ── P0-3：market_stats_cache 常量守卫（假数据门禁）────────────

class _QueueCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class _QueueConn:
    def __init__(self, results):
        self._results = list(results)

    def execute(self, sql, params=None):
        return _QueueCursor(self._results.pop(0) if self._results else [])


def _patch_nonempty_conn(monkeypatch, results):
    """注入 _check_nonempty 依赖：get_db_for_table=None → ecm.conn 假连接"""
    import app.data.stg_quality as sq
    checker = QualityChecker()
    monkeypatch.setattr(checker._sm, 'get_db_for_table', lambda t: None)
    fake_ecm = type('E', (), {'conn': _QueueConn(results)})()
    monkeypatch.setattr(sq, '_resolve_ecm', lambda ecm=None: fake_ecm)
    return checker


def test_p0_3_market_stats_fake_values_caught(monkeypatch):
    """兜底假值行（0.5/0.5/0.1/0.5/0.5/0.5/0.5）→ 常量守卫检出"""
    checker = _patch_nonempty_conn(
        monkeypatch, [[(4,)], [(0.5, 0.5, 0.1, 0.5, 0.5, 0.5, 0.5)]])
    r = checker._check_nonempty('market_stats_cache', '2026-09-11')
    assert not r.passed
    assert any('疑似兜底假值' in i for i in r.issues)


def test_p0_3_market_stats_real_values_pass(monkeypatch):
    """真实统计行（非常量）→ 通过"""
    checker = _patch_nonempty_conn(
        monkeypatch, [[(4,)], [(0.62, 0.48, 2.10, 0.55, 0.40, 0.52, 0.47)]])
    r = checker._check_nonempty('market_stats_cache', '2026-09-11')
    assert r.passed


def test_p0_3_market_stats_empty_caught(monkeypatch):
    """空表 → 非空校验检出"""
    checker = _patch_nonempty_conn(monkeypatch, [[(0,)]])
    r = checker._check_nonempty('market_stats_cache', '2026-09-11')
    assert not r.passed
    assert any('空表' in i for i in r.issues)

# ── 428 P0-1：值归一化 + _insert_from_df 真实写入行数返回（根治虚报）─────

def test_428_p0_1_to_scalar_normalizes_nested():
    """_to_scalar：嵌套 Series/DataFrame/Timestamp/date 归一为可绑定的标量"""
    from app.data.enhanced_cache_manager import _to_scalar
    assert _to_scalar(pd.Series([3])) == 3
    assert _to_scalar(pd.Series([], dtype=float)) is None
    assert _to_scalar(pd.Series([pd.Series([5])])) == 5
    assert _to_scalar(pd.Timestamp('2026-09-11')) == '2026-09-11'
    assert _to_scalar(np.datetime64('2026-09-11')) == '2026-09-11'
    assert _to_scalar({'a': 1}) == {'a': 1}  # dict 原样（不强行转）
    assert _to_scalar(3.14) == 3.14


def test_428_p0_1_insert_from_df_returns_written_rows(monkeypatch, tmp_path):
    """_insert_from_df 返回实际写入行数；嵌套 Series 列被归一不抛绑参错

    隔离：用临时 dir + init_sharding 双切分库路由，禁用真实生产 financial_cache。
    """
    import sqlite3
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data import sharding_manager as sm_mod
    from app.data.sharding_manager import ShardingManager

    # 隔离：新建临时 ShardingManager 指向 tmp_path，覆盖全局单例（_insert_from_df 动态 import
    # 自 app.data.sharding_manager import sharding_manager → 必须 patch sm_mod.sharding_manager）
    tmp_sm = ShardingManager(tmp_path)
    (tmp_path / 'duckdb').mkdir(exist_ok=True)
    monkeypatch.setattr(sm_mod, 'sharding_manager', tmp_sm)

    # 手动在临时 financial_cache.db 建表（列与生产一致子集）
    conn = tmp_sm.get_connection('financial_cache.db')
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fina_indicator_cache ("
        "ts_code TEXT, end_date TEXT, ann_date TEXT, eps REAL, ebitda REAL)"
    )
    conn.commit()

    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    ecm.conn = sqlite3.connect(tmp_path / 'stock_cache.db')  # 总库（走不到，仅防缺失）
    ecm.conn.execute("CREATE TABLE IF NOT EXISTS fina_indicator_cache (ts_code TEXT, end_date TEXT, ann_date TEXT, eps REAL, ebitda REAL)")
    ecm.conn.commit()
    ecm._validate_and_fix_data_format = lambda df: df
    ecm._apply_deep_clean = lambda t, df: df

    # 构造含嵌套 Series 的 df（ebitda 列是 Series 对象 → 应归一为 123.45）
    df = pd.DataFrame({
        'ts_code': ['000001.SZ'],
        'end_date': ['2026-06-30'],
        'ann_date': ['2026-08-15'],
        'ebitda': [pd.Series([123.45])],
    })
    n = ecm._insert_from_df('fina_indicator_cache', df)
    assert n == 1, f"应返回写入行数 1，实际 {n}"

    rows = conn.execute(
        "SELECT ts_code, end_date, ann_date, ebitda FROM fina_indicator_cache").fetchall()
    assert rows == [('000001.SZ', '2026-06-30', '2026-08-15', 123.45)], \
        f"嵌套 Series 应被归一为可绑定标量，实际 {rows}"
    conn.close()
