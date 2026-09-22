"""474号：cache_balancesheet_data 的 Tushare 字段名→表列名映射

验证写入层映射：Tushare 返回 total_current_liab/total_current_assets，
入库前须 rename 为缓存表列 current_liab/current_assets（否则被 _insert_from_df
动态列过滤丢弃 → 流动负债/流动资产列恒 NULL）。

纯逻辑验证：用 object.__new__ 构造裸实例绕过 __init__（避免连真实数据 DB），
monkeypatch _insert_from_df 捕获映射后的 DataFrame，不触碰任何数据库。
"""
import threading

import pandas as pd
import pytest

from app.data.enhanced_cache_manager import EnhancedCacheManager


@pytest.fixture()
def captured():
    """捕获传入 _insert_from_df 的 table 与映射后 df"""
    holder = {'table': None, 'df': None}
    yield holder


def _make_detached_ecm(captured):
    """构造不连库的裸 ECM 实例：patch _insert_from_df 收集入参"""
    # object.__new__ 绕过 __init__：不初始化 DB 连接/线程栈，避免连真实库写锁挂起
    ecm = object.__new__(EnhancedCacheManager)
    ecm._write_lock = threading.RLock()  # cache_balancesheet_data 内 with 需要

    def _fake_insert(self_, table, df):
        captured['table'] = table
        captured['df'] = df.copy()
        return len(df)

    # 用 lambda 包裹避免实例方法 self 绑定占位（cache_balancesheet_data 以 (table, df) 调用）
    ecm._insert_from_df = lambda table, df: _fake_insert(ecm, table, df)
    return ecm


def test_balancesheet_total_current_liab_mapped_to_current_liab(captured):
    """total_current_liab/total_current_assets 入库前被重命名 → current_liab/current_assets"""
    ecm = _make_detached_ecm(captured)

    df = pd.DataFrame([{
        'ts_code': '000001.SZ', 'end_date': '2026-06-30', 'ann_date': '2026-08-30',
        'total_assets': 1000000000.0, 'total_liab': 450000000.0,
        'total_current_liab': 400000000.0, 'total_current_assets': 600000000.0,
        'money_cap': 500000000.0,
    }])
    ecm.cache_balancesheet_data(df)

    assert captured['table'] == 'balancesheet_cache'
    assert 'current_liab' in captured['df'].columns, 'current_liab 列应存在'
    assert 'current_assets' in captured['df'].columns, 'current_assets 列应存在'
    assert 'total_current_liab' not in captured['df'].columns, 'Tushare 原名不应透传'
    assert captured['df'].iloc[0]['current_liab'] == 400000000.0
    assert captured['df'].iloc[0]['current_assets'] == 600000000.0


def test_balancesheet_already_normalized_cols_untouched(captured):
    """已是表列名的列（total_assets/total_liab/money_cap）不被重命名破坏"""
    ecm = _make_detached_ecm(captured)

    df = pd.DataFrame([{
        'ts_code': '000002.SZ', 'end_date': '2026-06-30', 'ann_date': '2026-08-30',
        'total_assets': 20000000.0, 'total_liab': 8000000.0,
        'money_cap': 3000000.0,
    }])
    ecm.cache_balancesheet_data(df)

    assert captured['df'].iloc[0]['total_assets'] == 20000000.0
    assert captured['df'].iloc[0]['total_liab'] == 8000000.0
    assert captured['df'].iloc[0]['money_cap'] == 3000000.0


def test_balancesheet_empty_returns_without_insert(captured):
    """空 df 直接返回，不进入写路径（_insert_from_df 不被调用）"""
    ecm = _make_detached_ecm(captured)

    def _boom(self_, table, df):
        pytest.fail("空 df 不应调用 _insert_from_df")

    ecm._insert_from_df = lambda table, df: _boom(ecm, table, df)
    ecm.cache_balancesheet_data(pd.DataFrame())
    assert captured['table'] is None
