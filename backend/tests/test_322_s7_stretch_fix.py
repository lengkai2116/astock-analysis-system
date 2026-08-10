"""potential_engine 拉伸饱和修复测试（313号 score 映射）

背景：原线性映射 (score-0.14)/0.52 在 score>=0.66 即饱和 100，导致全市场
98 只满分（1.79%）。修复：混合映射——线性段 0.14→0, 0.58→85；顶部 0.58+
用指数渐近 85→100（永不饱和，极高分才接近 100）。
目标分布：满分<=0.5%、80+ 5-10%、中位 40-46。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)


from app.opportunity_atlas.potential_engine import _map_score  # noqa: E402


def test_map_score_saturation_fixed():
    """score 极高（如 0.98）不应饱和 100，而是渐近接近（如 95+ 但 <100）"""
    high = _map_score(0.98)
    assert 90 <= high < 100, f"极高 score 应渐近接近 100 但永不饱和，实际 {high}"
    assert high >= 95, f"0.98 应接近 100（>95），实际 {high}"


def test_map_score_linear_mid():
    """score 中段（0.36=0.14与0.58中点）→ 约 42.5"""
    mid = _map_score(0.36)
    assert 40 <= mid <= 45, f"0.36 应约 42.5，实际 {mid}"


def test_map_score_zero_low():
    """score <=0.14 → 0 分"""
    assert _map_score(0.10) == 0
    assert _map_score(0.14) == 0


def test_map_score_monotonic():
    """映射应单调不减"""
    prev = -1
    for s in [0.1, 0.2, 0.3, 0.4, 0.5, 0.58, 0.6, 0.7, 0.8, 0.9, 0.98]:
        v = _map_score(s)
        assert v >= prev, f"映射应单调：{s}→{v} < 前值{prev}"
        prev = v
        assert 0 <= v <= 100


def test_map_score_603201_not_saturated():
    """常润股份（score=0.519）→ 不应满分，应在 70-80 区间"""
    v = _map_score(0.519)
    assert 70 <= v <= 80, f"603201 score=0.519 应约 73，实际 {v}"


def test_signal_strength_range_0_100():
    """compute_potential 返回 signal_strength 应在 0-100（修复双重缩放 bug）"""
    from app.opportunity_atlas.potential_engine import PotentialEngine, compute_fund_strength
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    engine = PotentialEngine()
    engine.build_percentile_tables(ecm)
    tags = {}
    for r in ecm.conn.execute(
            "SELECT tag_name, tag_value FROM opportunity_tags_cache WHERE ts_code='603201.SH'").fetchall():
        tags[r[0]] = r[1]
    mf = compute_fund_strength(ecm, '603201.SH')
    tags['roe'] = 1.8512
    pot = engine.compute_potential(tags, mf)
    ss = pot['signal_strength']
    assert isinstance(ss, int) and 0 <= ss <= 100, \
        f"signal_strength 应在 0-100，实际 {ss}（双重缩放 bug）"
