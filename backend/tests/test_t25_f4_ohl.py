"""T25-F4 回归测试：treemap_snapshot 补 OHL/amplitude

背景：快照表无 open/high/low/amplitude → 前端浮窗显示现价/0 兜底（非真实）。
修复后：快照含 4 列（daily_cache 源），API 透出真实值。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def test_snapshot_table_has_ohl_columns(ecm):
    """treemap_snapshot 应有 open/high/low/amplitude 列（修复前缺失）"""
    from app.data.sharding_manager import sharding_manager
    # 421号R4a：treemap_snapshot 属 snapshot_cache.db，走分库路由
    cols = [r[1] for r in sharding_manager.execute_query(
        'treemap_snapshot', 'PRAGMA table_info(treemap_snapshot)')]
    for c in ('open', 'high', 'low', 'amplitude'):
        assert c in cols, f"treemap_snapshot 应有 {c} 列（修复前缺失）"


def test_snapshot_ohl_values(ecm):
    """透出的 OHL/amplitude 应有真实值（修复前为 None/0）"""
    items = ecm.get_treemap_snapshot_items(['000001.SZ'])
    assert items
    item = items[0]
    assert 'open' in item and item['open'] is not None, f"open 应有值: {item.get('open')}"
    assert 'high' in item and item['high'] is not None, "high 应有值"
    assert 'low' in item and item['low'] is not None, "low 应有值"
    assert 'amplitude' in item, "amplitude 应透出"
    # 合理性：high >= low > 0
    assert item['high'] >= item['low'] > 0, f"OHL 应合理: {item}"
    # 对照 daily_cache 源（421号R4a：属 market_cache.db，走分库路由）
    from app.data.sharding_manager import sharding_manager
    rows = sharding_manager.execute_query(
        'daily_cache',
        "SELECT open, high, low FROM daily_cache WHERE ts_code='000001.SZ' "
        "ORDER BY trade_date DESC LIMIT 1")
    assert rows, "daily_cache 应有源数据"
    src = rows[0]
    assert abs(item['open'] - src[0]) < 0.01, f"open 应与源一致: 快照={item['open']}, 源={src[0]}"
