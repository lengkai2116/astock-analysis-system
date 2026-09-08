"""T8 回归测试：快照表字段透出（right_side_confirm/confirm_evidence/opportunity_profile）

背景：treemap_snapshot 表与 get_treemap_snapshot_items 缺少 3 个字段，
导致前端 L1/L2 的右侧确认徽标与七维画像无法展示（数据在标签库存在但未透出）。
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


def test_snapshot_items_expose_gate_fields(ecm):
    """get_treemap_snapshot_items 应透出右侧确认三字段"""
    items = ecm.get_treemap_snapshot_items(['000001.SZ'])
    assert items, "快照应有数据"
    item = items[0]
    # 修复前：right_side_confirm/confirm_evidence/opportunity_profile 均缺失
    assert 'right_side_confirm' in item, "快照应透出 right_side_confirm（修复前缺失）"
    assert 'confirm_evidence' in item, "快照应透出 confirm_evidence（修复前缺失）"
    assert 'opportunity_profile' in item, "快照应透出 opportunity_profile（修复前缺失）"
    # T10：entry_signals/exit_conditions 也应透出（307号三元字段）
    assert 'entry_signals' in item, "快照应透出 entry_signals"
    assert 'exit_conditions' in item, "快照应透出 exit_conditions"


def test_snapshot_fields_match_tag_values(ecm):
    """透出的字段值应与标签库一致（数据完整）"""
    items = ecm.get_treemap_snapshot_items(['000001.SZ'])
    assert items
    item = items[0]

    # 从标签库读取该股票真实值对照
    conn = ecm.conn
    def _tag(tag_name):
        rows = conn.execute(
            "SELECT tag_value FROM opportunity_tags_cache WHERE ts_code='000001.SZ' AND tag_name=? "
            "ORDER BY updated_at DESC LIMIT 1", [tag_name]).fetchall()
        return rows[0][0] if rows else None

    rsc = _tag('right_side_confirm')
    if rsc:  # 标签库有值时应一致透出
        # 413号修复：daemon _check_right_side_confirm 返回值已捕获（中文），
        # 但存量快照可能仍为英文。语义等价即通过。
        _equiv = {'unconfirmed': '未确认', 'strong_confirm': '强确认',
                  'basic_confirm': '基础确认', 'veto': '否决'}
        snap_val = item['right_side_confirm']
        assert snap_val == rsc or _equiv.get(snap_val) == rsc, \
            f"right_side_confirm 不一致: 快照={snap_val}, 标签库={rsc}"
