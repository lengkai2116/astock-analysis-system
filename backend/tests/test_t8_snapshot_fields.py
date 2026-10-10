"""T8 回归测试：快照表字段透出（right_side_confirm/confirm_evidence/opportunity_profile）

背景：treemap_snapshot 表与 get_treemap_snapshot_items 缺少 3 个字段，
导致前端 L1/L2 的右侧确认徽标与七维画像无法展示（数据在标签库存在但未透出）。
注：2026-10-10 处置——opportunity_tags_cache 已停更（08-19 起无生产写入，JUD 富化
改走 _jud_meta_cache → treemap_snapshot），原「与标签库数值比对」用例删除，仅保留
字段透出/非空验证。
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


def test_snapshot_fields_non_empty(ecm):
    """透出的核心字段应有实际值（非空透出，而非占位）"""
    items = ecm.get_treemap_snapshot_items(['000001.SZ'])
    assert items
    item = items[0]
    # 快照 right_side_confirm 为 JUD 预计算直接落库值（2026-10-10 起替代
    # opportunity_tags_cache 旧比对；标签库已停更无权威性）
    assert item['right_side_confirm'] not in (None, ''), \
        "right_side_confirm 应有 JUD 判定值"
