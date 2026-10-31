"""2026-10-31：新股元数据按需补采（修 10-30 遗留②）

stocks 全量同步只在每月 1 日 04:00，新股上市当天会出现在 daily_cache 却无元数据：
COL 清洗拿不到 list_date → IPO 首日 |pct_chg|>50% 被当脏数据剔除、地图名称为空、
每小时 K 线补采重复告警（10-30 实证 301718.SZ / 920285.BJ / 920306.BJ）。

本测试锁定：
1. 缺口识别排除指数（宽基 / 申万 / .SI / 399 段）；
2. 单只补采写入 stocks（list_date 为 YYYY-MM-DD 文本）+ 回填 treemap 名称，
   并清空 ECM 的 list_date 缓存使豁免立即生效。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402

STOCKS_DDL = """
CREATE TABLE stocks (
    ts_code VARCHAR(10) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    name VARCHAR(50) NOT NULL,
    industry VARCHAR(50),
    market VARCHAR(20),
    list_date DATE,
    created_at DATETIME,
    updated_at DATETIME,
    PRIMARY KEY (ts_code),
    UNIQUE (symbol)
)
"""


@pytest.fixture()
def app_db(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db = tmp_path / 'app.db'
    con = sqlite3.connect(db)
    con.execute(STOCKS_DDL)
    con.execute(
        "INSERT INTO stocks (ts_code, symbol, name, list_date) VALUES "
        "('600000.SH', '600000', '浦发银行', '1999-11-10')")
    con.commit()
    con.close()
    return db


@pytest.fixture()
def daemon():
    import importlib
    return importlib.import_module('data_daemon')


def test_missing_codes_excludes_indices(daemon, app_db, monkeypatch):
    latest = [
        ('301718.SZ',), ('920306.BJ',), ('600000.SH',),
        ('000001.SH',), ('000300.SH',), ('399001.SZ',), ('399006.SZ',),
        ('899050.BJ',), ('801010.SI',),
    ]
    monkeypatch.setattr(daemon, '_shard_fetchall',
                        lambda table, sql, params=None: latest)

    assert daemon._missing_stock_metadata_codes() == ['301718.SZ', '920306.BJ']


def test_backfill_upserts_stock_and_treemap(daemon, app_db, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(daemon, '_missing_stock_metadata_codes',
                        lambda limit=50: ['920306.BJ'])

    class FakePro:
        stock_basic = staticmethod(lambda **kwargs: None)

    class FakeTs:
        @staticmethod
        def pro_api():
            return FakePro()

    monkeypatch.setitem(sys.modules, 'tushare', FakeTs())
    monkeypatch.setattr(daemon, '_ts', lambda func, *a, **k: pd.DataFrame([{
        'ts_code': '920306.BJ', 'symbol': '920306', 'name': '测试新股',
        'industry': '电气设备', 'market': '北交所', 'list_date': '20261029',
    }]))

    treemap_calls = []
    monkeypatch.setattr(daemon, '_sync_treemap_stock_meta',
                        lambda code, name, industry: treemap_calls.append(
                            (code, name, industry)))

    invalidated = []
    fake_ecm = type('FakeECM', (), {
        'invalidate_list_date_map': lambda self: invalidated.append(1)})()
    monkeypatch.setattr(daemon, '_ensure_ecm', lambda: fake_ecm)
    monkeypatch.setattr(daemon, '_ecm', fake_ecm)

    assert daemon._backfill_missing_stock_metadata() == 1

    con = sqlite3.connect(app_db)
    row = con.execute(
        "SELECT ts_code, symbol, name, industry, market, list_date "
        "FROM stocks WHERE ts_code='920306.BJ'").fetchone()
    con.close()
    assert row == ('920306.BJ', '920306', '测试新股', '电气设备', '北交所', '2026-10-29')
    assert treemap_calls == [('920306.BJ', '测试新股', '电气设备')]
    assert invalidated == [1], '补到元数据后必须清空 list_date 缓存（否则豁免不生效）'


def test_backfill_is_noop_when_metadata_complete(daemon, monkeypatch):
    monkeypatch.setattr(daemon, '_missing_stock_metadata_codes',
                        lambda limit=50: [])
    assert daemon._backfill_missing_stock_metadata() == 0
