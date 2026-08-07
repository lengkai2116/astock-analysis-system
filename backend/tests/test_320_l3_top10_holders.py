"""320号 L3 回归测试：top10_holders_cache 补 hold_float_ratio 列

背景：_batch_top10_holders 写入 hold_float_ratio（Tushare 返回列），但表早期版本缺此列
→ "table top10_holders_cache has no column named hold_float_ratio"（前十大股东采集失败）。
L3 修复：ECM 初始化迁移补列 + 建表 SQL 同步。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def test_top10_holders_has_hold_float_ratio(ecm):
    """top10_holders_cache 表应含 hold_float_ratio 列（修复前缺失）"""
    cols = {r[1] for r in ecm.conn.execute("PRAGMA table_info(top10_holders_cache)").fetchall()}
    assert 'hold_float_ratio' in cols, "top10_holders_cache 应含 hold_float_ratio 列（修复前缺失）"


def test_cache_top10_with_hold_float_ratio(ecm):
    """写入含 hold_float_ratio 的记录应成功（修复前列缺失失败）"""
    import pandas as pd
    df = pd.DataFrame([{
        'ts_code': 'TEST06.SZ', 'end_date': '2026-08-07', 'ann_date': '2026-08-07',
        'holder_name': '测试股东', 'hold_amount': 1000000.0,
        'hold_ratio': 5.0, 'hold_float_ratio': 4.5,
    }])
    ecm.cache_top10_holders(df)
    try:
        row = ecm.conn.execute(
            "SELECT hold_float_ratio FROM top10_holders_cache WHERE ts_code='TEST06.SZ'"
        ).fetchone()
        assert row is not None, "hold_float_ratio 应写入成功（修复前 no column named hold_float_ratio）"
        assert abs(row[0] - 4.5) < 0.01
    finally:
        try:
            ecm.conn.execute("DELETE FROM top10_holders_cache WHERE ts_code='TEST06.SZ'")
            ecm.conn.commit()
        except Exception:
            pass
