"""321号 S3 测试：机会类型规则树 avoid 降级 + 标签落库

背景：S1/S2 已实现跨维仲裁（opportunity_state）。S3 完成两件事：
1. _classify_opportunity_type 规则树互斥：state=avoid 时类型强制降级为
   "回避·仅观察"（avoid_only），不再输出"主力建仓观察/慢牛上涨"等看多类型（修 T2）；
2. TAG_META 注册 opportunity_state/state_evidence（write_tags 落库元数据）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

from data_daemon import _classify_opportunity_type  # noqa: E402

# ══════════════════════════════════════════════════════════
# T2：state=avoid → 机会类型降级为"回避·仅观察"
# ══════════════════════════════════════════════════════════

def test_avoid_state_degrades_to_avoid_only():
    """state=avoid → 机会类型强制降级为 avoid_only（不再输出看多类型）

    修复前：000039 等 490 只"否决+主力建仓观察/慢牛上涨"类型与时机行矛盾
    """
    tags = {'opportunity_state': 'avoid', 'main_force_phase': 'building'}
    result = _classify_opportunity_type(tags)
    assert result['opportunity_type'] == 'avoid_only'
    assert '回避' in result['opportunity_label'], \
        f"avoid 类型标签应含'回避'，实际 {result['opportunity_label']}"


def test_avoid_overrides_bullish_rule():
    """avoid 优先于规则树全部看多分支（R2-R9），无论其他条件多强"""
    tags = {
        'opportunity_state': 'avoid',
        'main_force_phase': 'building',
        'fina_health': 'pass',
        'valuation_level': 'extreme_low',
        'sentiment_phase': 'recovery',
        'sector_heat': 'top_10',
    }
    result = _classify_opportunity_type(tags)
    assert result['opportunity_type'] == 'avoid_only'
    assert result['opportunity_type'] != 'value_bottom'
    assert result['opportunity_type'] != 'building_watch'


def test_avoid_overrides_danger_rules():
    """avoid 也优先于危险区规则（R1），统一为回避"""
    tags = {'opportunity_state': 'avoid', 'main_force_phase': 'distributing', 'fina_health': 'fail'}
    result = _classify_opportunity_type(tags)
    assert result['opportunity_type'] == 'avoid_only'


# ══════════════════════════════════════════════════════════
# 非 avoid 时规则树原逻辑不受影响
# ══════════════════════════════════════════════════════════

def test_non_avoid_keeps_original_rules():
    """state 非 avoid（或不含 state）→ 原规则树不变（维度链主体功能保留）"""
    tags = {'main_force_phase': 'building', 'fina_health': 'pass', 'valuation_level': 'low'}
    result = _classify_opportunity_type(tags)
    assert result['opportunity_type'] == 'value_bottom', \
        f"非 avoid 应走原规则树，实际 {result['opportunity_type']}"


def test_non_avoid_building_watch_kept():
    """非 avoid 的 building_watch 保留（T2 只对 avoid 生效）"""
    tags = {'main_force_phase': 'building'}
    result = _classify_opportunity_type(tags)
    assert result['opportunity_type'] == 'building_watch'


def test_no_state_attr_default_rules():
    """无 opportunity_state 字段（旧数据兼容）→ 走原规则树"""
    tags = {'main_force_phase': 'lifting', 'sentiment_phase': 'climax', 'sector_heat': 'top_10'}
    result = _classify_opportunity_type(tags)
    assert result['opportunity_type'] == 'main_upsurge'


# ══════════════════════════════════════════════════════════
# TAG_META 注册：opportunity_state/state_evidence 落库元数据
# ══════════════════════════════════════════════════════════

def test_tag_meta_registered_for_state_fields():
    """write_tags 的 TAG_META 应注册 opportunity_state/state_evidence（derived 组）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    import inspect
    src = inspect.getsource(ecm.write_tags)
    assert 'opportunity_state' in src, "TAG_META 未注册 opportunity_state"
    assert 'state_evidence' in src, "TAG_META 未注册 state_evidence"


def test_write_tags_state_fields_persist(tmp_path):
    """write_tags 能写入 opportunity_state/state_evidence 并读回"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    ecm.write_tags('ZZZZZZ.SZ', {
        'opportunity_state': 'avoid',
        'state_evidence': '["右侧否决：出现卖出/背离/预跌信号"]',
    })
    tags = ecm.get_tags('ZZZZZZ.SZ')
    assert tags.get('opportunity_state') == 'avoid'
    assert '右侧否决' in (tags.get('state_evidence') or '')
