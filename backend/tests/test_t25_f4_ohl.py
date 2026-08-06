"""T25-F4 回归测试：treemap_snapshot 补 OHL/amplitude

背景：快照表无 open/high/low/amplitude → 前端浮窗显示现价/0 兜底（非真实）。
修复后：快照含 4 列（daily_cache 源），API 透出真实值。
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


def test_snapshot_table_has_ohl_columns(ecm):
    """treemap_snapshot 应有 open/high/low/amplitude 列（修复前缺失）"""
    cols = [r[1] for r in ecm.conn.execute('PRAGMA table_info(treemap_snapshot)').fetchall()]
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
    # 对照 daily_cache 源
    conn = ecm.conn
    src = conn.execute(
        "SELECT open, high, low FROM daily_cache WHERE ts_code='000001.SZ' "
        "ORDER BY trade_date DESC LIMIT 1").fetchone()
    assert src is not None
    assert abs(item['open'] - src[0]) < 0.01, f"open 应与源一致: 快照={item['open']}, 源={src[0]}"
