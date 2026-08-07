"""320号 L1 回归测试：因子预计算 Timestamp bug 修复

背景：P3 因子预计算全市场失败，报错 "Error binding parameter 5: type 'Timestamp' is not supported"。
根因：_batch_cache_factor_series 的 records 中 cached_at 为 datetime 对象（:65），
      cache_factor_data → _insert_from_df 直接绑定 datetime 参数 → SQLite 不支持。
L1 修复：cached_at/trade_date 统一转字符串后再写入。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest
from datetime import datetime


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def test_cache_factor_data_with_datetime(ecm):
    """cache_factor_data 应能写入含 datetime 的 records（修复前 Timestamp 绑定失败）

    模拟 _batch_cache_factor_series 产出的 records 格式（cached_at 为 datetime）
    """
    records = [
        {'ts_code': 'TEST03.SZ', 'trade_date': '2026-08-07',
         'factor_name': 'QLIB_ROC_20', 'value': 1.5, 'cached_at': datetime.now()},
    ]
    ecm.cache_factor_data(records)
    try:
        df = ecm.get_cached_factors('TEST03.SZ')
        assert df is not None and not df.empty, "因子写入应成功（修复前 datetime 绑定失败）"
        matched = df[df['factor_name'] == 'QLIB_ROC_20']
        assert not matched.empty, "应读到 QLIB_ROC_20 因子"
        assert abs(float(matched['value'].iloc[0]) - 1.5) < 0.01
    finally:
        try:
            ecm.conn.execute("DELETE FROM factor_cache WHERE ts_code='TEST03.SZ'")
            ecm.conn.commit()
        except Exception:
            pass


def test_batch_cache_factor_series_datetime_index(ecm):
    """factor_series 的 index 为 datetime 时应正确转字符串后写入

    修复前：factor_series.items() 的 date 为 Timestamp → trade_date 未转 → 绑定失败
    """
    from app.data.factor_precompute import FactorPrecomputeManager
    fpm = FactorPrecomputeManager(ecm)
    # 构造 datetime index 的 series
    idx = pd.to_datetime(['2026-08-05', '2026-08-06', '2026-08-07'])
    series = pd.Series([1.0, 2.0, 3.0], index=idx)
    fpm._batch_cache_factor_series(series, 'TEST04.SZ', 'QLIB_ROC_5')
    try:
        df = ecm.get_cached_factors('TEST04.SZ')
        assert df is not None and len(df) >= 1, "datetime index 因子应写入成功"
        # trade_date 应为字符串格式
        assert isinstance(df['trade_date'].iloc[0], str), "trade_date 应为字符串"
    finally:
        try:
            ecm.conn.execute("DELETE FROM factor_cache WHERE ts_code='TEST04.SZ'")
            ecm.conn.commit()
        except Exception:
            pass
