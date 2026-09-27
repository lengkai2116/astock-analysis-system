"""493号 批次3（P2-g）市场状态 regime 可达性回归

原实现 `tags['status_bar']` 分支恒不可达（RAW 无该键）；trending_up/extreme_panic
恒 0 → MARKET_REGIME_WEIGHTS 实为单档。493 P2-g 改以**市场级** `market_emotion`
（情绪周期六段论）为基准（Wiki《市场状态感知因子》《情绪周期-仓位联动》）。
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

_D = StatusEngine._detect_market_regime


# ── 市场级情绪阶段映射 ──────────────────────────────────────────────

def test_market_emotion_up_phases():
    for m in ('sprout', 'ferment', 'climax'):
        assert _D({'market_emotion': m}, {}) == 'trending_up', m


def test_market_emotion_ebb_down():
    assert _D({'market_emotion': 'ebb'}, {}) == 'trending_down'


def test_market_emotion_ice_extreme():
    assert _D({'market_emotion': 'ice'}, {}) == 'extreme_panic'


def test_market_emotion_regression_neutral():
    for m in ('regression', 'normal', 'neutral', ''):
        assert _D({'market_emotion': m}, {}) == 'ranging', m


def test_cn_market_emotion_variants():
    assert _D({'market_emotion': '发酵'}, {}) == 'trending_up'
    assert _D({'market_emotion': '退潮'}, {}) == 'trending_down'
    assert _D({'market_emotion': '冰点'}, {}) == 'extreme_panic'


def test_status_bar_branch_removed():
    """旧 status_bar 分支已死**（RAW 无该键）——不再据其返回 trending_up/ranging"""
    ae = (pathlib.Path(__file__).resolve().parents[1] / 'app' / 'opportunity_atlas'
          / 'status_engine.py').read_text(encoding='utf-8')
    assert "tags.get('status_bar'" not in ae


# ── 回退链 ──────────────────────────────────────────────────────────

def test_fallback_dim5_emotion():
    assert _D({}, {'emotion': {'state': '高潮'}}) == 'trending_up'
    assert _D({}, {'emotion': {'state': '退潮'}}) == 'trending_down'
    assert _D({}, {'emotion': {'state': '冰点'}}) == 'extreme_panic'


def test_fallback_risk_high():
    assert _D({}, {'risk': {'state': '高'}}) == 'trending_down'


def test_default_ranging():
    assert _D({}, {}) == 'ranging'
    assert _D({}, {'emotion': {'state': '正常'}}) == 'ranging'


def test_market_emotion_takes_priority_over_fallback():
    """市场级信号优先于个股维度回退"""
    assert _D({'market_emotion': 'ferment'}, {'risk': {'state': '高'}}) == 'trending_up'
