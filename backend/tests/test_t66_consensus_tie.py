"""T6.6 回归测试：L4 共识率打平应标记"多空分歧"而非仅显示 0%

根因：cross_validate.py:437-439 —— bullish == bearish 时 direction='neutral', rate=0，
前端显示 "0.0%" 误导为"无共识"。修复后应输出 tie=True 标记供前端显示"多空分歧"。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


@pytest.fixture(scope='module')
def validator():
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    return L4CrossValidator()


def _tie_tags() -> dict:
    """构造 5多5空 的打平标签集（316号 P2 适配：sector none 现为 0，补 pattern 看跌形态）"""
    return {
        'main_force_phase': 'building',       # +1
        'valuation_level': 'low',              # +1
        'trend_alignment': 'up_aligned',       # +1
        'fund_flow': '5d_inflow',              # +1
        'fina_health': 'pass',                 # +1
        'buy_sell_point': 'first_sell',        # -1
        'ma_alignment': 'bearish',             # -1
        'price_position': 'high_zone',         # -1
        'sector_heat': 'none',                 # 0（316号P2校准）
        'catalyst_event': 'fraud_sign',        # -1
        'pattern_signal': '乌云盖顶',          # -1
    }


def test_tie_consensus_flagged_as_tie(validator):
    """打平时 consensus 应带 tie=True 标记（区别于真无共识）"""
    consensus, _ = validator._compute_consensus(_tie_tags(), {})

    assert consensus['bullish_votes'] == consensus['bearish_votes'], \
        f"应构造打平: {consensus['bullish_votes']} vs {consensus['bearish_votes']}"
    assert consensus['direction'] == 'neutral'
    assert consensus.get('tie') is True, "打平应标记 tie=True（修复前缺失）"


def test_non_tie_not_flagged(validator):
    """非打平（多方占优）不应标记 tie"""
    tags = _tie_tags()
    tags['fina_health'] = 'fail'  # 变 -1 → 4多6空
    consensus, _ = validator._compute_consensus(tags, {})

    assert consensus.get('tie') is False, "非打平不应标记 tie"
    assert consensus['direction'] == 'bearish'
