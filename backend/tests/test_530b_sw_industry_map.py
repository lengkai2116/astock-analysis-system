"""530号 第二轮：股票 → 申万一级行业映射（sw_industry_map）定向测试。

覆盖：
- `normalize_code`：ts_code 去交易所后缀 / 6 位代码原样
- `get_sw_industry_map`：读出映射、空表返回空、脏值过滤
- `refresh_sw_industry_map`：新鲜度未过期不拉取；akshare 失败保留旧表；成功写盘
"""
import sys
import types

import pandas as pd
import pytest
from app.data import sw_industry_map as mod


@pytest.fixture(autouse=True)
def _clear_cache():
    mod._invalidate_cache()
    yield
    mod._invalidate_cache()


class _FakeECM:
    def __init__(self, df):
        self._df = df

    def _query_shard(self, table, sql, params=None):
        return self._df


class _FakeAk:
    def __init__(self, n_industries=31, per_industry=100):
        self.n_industries = n_industries
        self.per_industry = per_industry

    def sw_index_first_info(self):
        return pd.DataFrame({
            '行业代码': [f'801{i:03d}.SI' for i in range(self.n_industries)],
            '行业名称': [f'行业{i}' for i in range(self.n_industries)],
        })

    def index_component_sw(self, symbol):
        idx = int(symbol[-3:])
        codes = [f'{idx:02d}{j:04d}' for j in range(self.per_industry)]
        return pd.DataFrame({'证券代码': codes})


def test_normalize_code():
    assert mod.normalize_code('600000.SH') == '600000'
    assert mod.normalize_code('000001.sz') == '000001'
    assert mod.normalize_code(' 600000 ') == '600000'
    assert mod.normalize_code(None) == ''


def test_get_map_reads_and_normalizes(monkeypatch):
    df = pd.DataFrame({
        'ts_code': ['600000', '000001.SZ', ''],
        'industry': ['银行', '银行', '电子'],
    })
    monkeypatch.setattr(mod, '_ecm', lambda ecm=None: _FakeECM(df))
    m = mod.get_sw_industry_map(use_cache=False)
    assert m == {'600000': '银行', '000001': '银行'}


def test_get_map_empty_returns_empty(monkeypatch):
    monkeypatch.setattr(mod, '_ecm', lambda ecm=None: _FakeECM(pd.DataFrame()))
    assert mod.get_sw_industry_map(use_cache=False) == {}


def test_refresh_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(mod, '_is_fresh', lambda ecm, days: True)
    monkeypatch.setattr(mod, 'get_sw_industry_status', lambda ecm=None: (5000, '2026-10-01T00:00:00'))
    called = {'n': 0}

    def _no_fetch(*a, **k):
        called['n'] += 1
        raise AssertionError('不应拉取')

    monkeypatch.setitem(sys.modules, 'akshare', types.SimpleNamespace(
        sw_index_first_info=_no_fetch, index_component_sw=_no_fetch))
    assert mod.refresh_sw_industry_map(_FakeECM(pd.DataFrame())) == 5000
    assert called['n'] == 0


def test_refresh_failure_keeps_old_table(monkeypatch):
    monkeypatch.setattr(mod, '_is_fresh', lambda ecm, days: False)
    monkeypatch.setattr(mod, 'get_sw_industry_status', lambda ecm=None: (4800, '2026-01-01T00:00:00'))

    def _boom(*a, **k):
        raise RuntimeError('network down')

    monkeypatch.setitem(sys.modules, 'akshare', types.SimpleNamespace(
        sw_index_first_info=_boom, index_component_sw=_boom))
    assert mod.refresh_sw_industry_map(_FakeECM(pd.DataFrame())) == 4800


def test_refresh_writes_sw_l1_rows(monkeypatch):
    monkeypatch.setattr(mod, '_is_fresh', lambda ecm, days: False)
    monkeypatch.setattr(mod, 'get_sw_industry_status', lambda ecm=None: (0, None))
    monkeypatch.setitem(sys.modules, 'akshare', _FakeAk())
    captured = {}

    def _fake_write(ecm, rows):
        captured['rows'] = rows

    monkeypatch.setattr(mod, '_write_rows', _fake_write)
    n = mod.refresh_sw_industry_map(_FakeECM(pd.DataFrame()))
    assert n == 31 * 100
    rows = captured['rows']
    assert len(rows) == 31 * 100
    assert rows[0][1].startswith('行业')
    assert rows[0][2].endswith('.SI')
    assert all(len(r[0]) == 6 for r in rows)
