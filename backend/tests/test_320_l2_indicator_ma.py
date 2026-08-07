"""320号 L2 回归测试：indicator_ma 表补 ma30/ma60 列

背景：cache_indicators_wide（ECM:779）写入 ma_cols 含 ma30/ma60，
但 indicator_ma 建表 SQL 只有 ma5/ma10/ma20/vol_ma5/vol_ma10 → "no column named ma60"，
P1 指标预计算全市场失败（6/5535 只）。
L2 修复：建表 SQL + 存量表 ALTER 补 ma30/ma60 列。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def test_indicator_ma_table_has_ma30_ma60(ecm):
    """indicator_ma 表应含 ma30/ma60 列（修复前缺失致写入失败）"""
    cols = {r[1] for r in ecm.conn.execute("PRAGMA table_info(indicator_ma)").fetchall()}
    assert 'ma60' in cols, "indicator_ma 表应含 ma60 列（修复前缺失）"
    assert 'ma30' in cols, "indicator_ma 表应含 ma30 列（修复前缺失）"


def test_cache_indicators_wide_with_ma60(ecm):
    """cache_indicators_wide 写入含 ma60 的 df 应成功（修复前列缺失失败）"""
    df = pd.DataFrame({
        'trade_date': ['2026-08-07'],
        'ma5': [1.0], 'ma10': [1.1], 'ma20': [1.2], 'ma30': [1.3], 'ma60': [1.4],
        'vol_ma5': [100.0], 'vol_ma10': [110.0],
    })
    ecm.cache_indicators_wide('TEST05.SZ', df)
    try:
        row = ecm.conn.execute(
            "SELECT ma60 FROM indicator_ma WHERE ts_code='TEST05.SZ'").fetchone()
        assert row is not None, "ma60 应写入成功（修复前 no column named ma60）"
        assert abs(row[0] - 1.4) < 0.01
    finally:
        try:
            ecm.conn.execute("DELETE FROM indicator_ma WHERE ts_code='TEST05.SZ'")
            ecm.conn.commit()
        except Exception:
            pass
