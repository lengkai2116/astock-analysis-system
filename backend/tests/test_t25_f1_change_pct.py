"""T25-F1 回归测试：change_pct 三段断裂修复

背景：as_market_snapshot 表无 change_pct 列 → 采集端算好的涨跌幅写入时被丢弃
→ _merge_snapshot_with_realtime 读 rt['change_pct'] 抛 KeyError → 盘中覆盖从未生效。
修复后：表含 change_pct 列、写入保留、merge 能读取。
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


def test_snapshot_table_has_change_pct_column(ecm):
    """as_market_snapshot 表应有 change_pct 列（修复前缺失）"""
    cols = [r[1] for r in ecm.snapshot_conn.execute('PRAGMA table_info(as_market_snapshot)').fetchall()]
    assert 'change_pct' in cols, f"as_market_snapshot 应有 change_pct 列（修复前缺失）: {cols}"


def test_write_preserves_change_pct(ecm):
    """写入快照后 change_pct 应被保留（修复前写入时丢弃）"""
    # 构造一条测试记录（不覆盖真实数据，用唯一 ts_code）
    ts = 'T25TEST.SH'
    try:
        ecm.snapshot_conn.execute("DELETE FROM as_market_snapshot WHERE ts_code=?", [ts])
        rec = {
            'ts_code': ts, 'code': '000000', 'name': '测试',
            'price': 10.5, 'open': 10.0, 'high': 10.8, 'low': 9.9,
            'prev_close': 10.0, 'volume': 1000, 'amount': 10000.0,
            'change': 0.5, 'change_pct': 5.0,
        }
        ecm.cache_market_snapshot_data([rec])
        row = ecm.get_market_snapshot(ts)
        assert row.get('change_pct') == 5.0, f"change_pct 应被保留: {row}"
    finally:
        ecm.snapshot_conn.execute("DELETE FROM as_market_snapshot WHERE ts_code=?", [ts])
        ecm.snapshot_conn.commit()


def test_merge_uses_change_pct(ecm):
    """_merge_snapshot_with_realtime 应能读取 change_pct（修复前 KeyError）"""
    from app.routes.opportunity_atlas import _merge_snapshot_with_realtime
    items = [{'ts_code': '000001.SZ', 'pct_change': 0.17, 'price': 11.63, 'snapshot': False}]
    rt = [{'ts_code': '000001.SZ', 'price': 11.80, 'change_pct': 1.46}]
    try:
        merged = _merge_snapshot_with_realtime(items, rt)
        assert merged[0]['pct_change'] == 1.46, f"merge 应更新 pct_change: {merged[0]}"
        assert merged[0]['price'] == 11.80
        assert merged[0]['snapshot'] is True
    except KeyError as e:
        pytest.fail(f"merge 仍 KeyError: {e}")
