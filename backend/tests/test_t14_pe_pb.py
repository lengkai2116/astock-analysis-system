"""T14 回归测试：快照表 pe/pb 字段透出（修复点击弹窗崩溃根因）

背景：treemap_snapshot 无 pe/pb 列 → API 返回 null → 前端 showDetail 在
data.pe.toFixed(1) 崩溃 → 弹窗不打开（三个地图全部无弹窗）。
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


def test_snapshot_items_expose_pe_pb(ecm):
    """get_treemap_snapshot_items 应透出 pe/pb 字段（修复前缺失→null）"""
    items = ecm.get_treemap_snapshot_items(['000001.SZ'])
    assert items, "快照应有数据"
    item = items[0]
    assert 'pe' in item, "快照应透出 pe（修复前缺失）"
    assert 'pb' in item, "快照应透出 pb（修复前缺失）"
    # 000001.SZ 应有 pe/pb 实际值（非 null）
    assert item['pe'] is not None, "000001.SZ 的 pe 应有值"
    assert item['pb'] is not None, "000001.SZ 的 pb 应有值"


def test_snapshot_pe_matches_source(ecm):
    """透出的 pe/pb 应与 daily_basic_cache 源数据一致"""
    conn = ecm.conn
    src = conn.execute(
        "SELECT pe, pb FROM daily_basic_cache WHERE ts_code='000001.SZ' "
        "ORDER BY trade_date DESC LIMIT 1").fetchone()
    assert src, "源数据应有记录"
    items = ecm.get_treemap_snapshot_items(['000001.SZ'])
    item = items[0]
    assert abs(item['pe'] - src[0]) < 0.01, f"pe 不一致: 快照={item['pe']}, 源={src[0]}"


def test_snapshot_exposes_amount_turnover(ecm):
    """310号方案：快照应透出 amount/turnover_rate/circ_mv（成交额视图数据源）"""
    items = ecm.get_treemap_snapshot_items(['000001.SZ'])
    assert items
    item = items[0]
    assert 'amount' in item, "快照应透出 amount（修复前缺失）"
    assert 'turnover_rate' in item, "快照应透出 turnover_rate（修复前缺失）"
    assert 'circ_mv' in item, "快照应透出 circ_mv（修复前缺失）"
    # 000001.SZ 应有实际值
    assert item['amount'] is not None and item['amount'] > 0, "amount 应有值"
    assert item['turnover_rate'] is not None, "turnover_rate 应有值"
