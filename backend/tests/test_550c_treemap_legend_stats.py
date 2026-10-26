"""550-C：reduce 五色/筛选、统计卡与 fallback 阈值回归。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / '_ui-prototype' / 'opportunity-treemap.html'
ROUTE = ROOT / 'backend/app/routes/opportunity_atlas.py'


def test_reduce_has_legend_and_filter():
    html = HTML.read_text(encoding='utf-8')
    assert 'id="timingOrangeBtn"' in html
    assert "toggleTimingFilter('reduce')" in html
    assert "'reduce': 'timingOrangeBtn'" in html
    assert '橙=减仓' in html
    assert 'background:#f97316' in html


def test_stats_labels_are_aligned():
    html = HTML.read_text(encoding='utf-8')
    assert '机会信号 (潜力≥70)' in html
    assert "s.phase === 'building'" in html
    assert '评分≥7' not in html


def test_fallback_uses_missing_rate_and_nonnull_coverage():
    src = ROUTE.read_text(encoding='utf-8')
    assert '_missing_rate > 0.01' in src
    assert 'signal_strength_missing_count' in src
    assert 'signal_strength_missing_rate' in src
    assert 'signal_strength_positive_coverage' in src
    assert 'signal_strength_coverage' in src
