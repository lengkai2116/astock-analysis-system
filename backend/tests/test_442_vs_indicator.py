"""442号缺陷③：_assess_vs_indicator 改读 indicator_status（rsi14/kdj_j 不产出）"""

import pytest

from app.opportunity_atlas.dimensions.dim2_structure_engine import _assess_vs_indicator


class TestAssessVsIndicator:
    def test_ma_bullish(self):
        r = _assess_vs_indicator({'indicator_status': 'ma=bullish,trend='})
        assert r['detail'] == '均线多头排列'

    def test_ma_bearish(self):
        r = _assess_vs_indicator({'indicator_status': 'ma=bearish,trend='})
        assert r['detail'] == '均线空头排列'

    def test_ma_mixed_with_rsi(self):
        """461-1：rsi 个股真值（0-100）→ 强弱分档描述"""
        r = _assess_vs_indicator({'indicator_status': 'ma=mixed,trend=', 'rsi': 51})
        assert r['detail'] == '均线纠缠，RSI 51 中性'

    def test_unknown_ma_value(self):
        """indicator_status 有值但 ma 值不在映射 → 忽略，仅 RSI"""
        r = _assess_vs_indicator({'indicator_status': 'ma=weird', 'rsi': 30})
        assert r['detail'] == 'RSI 30 偏弱'

    def test_4658_five_bins(self):
        """465-8（479-10 拍板）：加中位参考档——30-40/60-70 偏侧不再吞为中性"""
        cases = {
            72: '偏强', 65: '偏强-中性', 45: '中性', 35: '偏弱-中性', 28: '偏弱',
        }
        for v, want in cases.items():
            r = _assess_vs_indicator({'rsi': v})
            assert r['detail'] == f'RSI {v} {want}', f'RSI={v}: {r["detail"]}'

    def test_4658_threshold_boundaries(self):
        """465-8 分档阈值边界：70/60/40/30 归入偏侧而非中性"""
        assert _assess_vs_indicator({'rsi': 70})['detail'] == 'RSI 70 偏强'
        assert _assess_vs_indicator({'rsi': 60})['detail'] == 'RSI 60 偏强-中性'
        assert _assess_vs_indicator({'rsi': 40})['detail'] == 'RSI 40 偏弱-中性'
        assert _assess_vs_indicator({'rsi': 30})['detail'] == 'RSI 30 偏弱'

    def test_no_data(self):
        assert _assess_vs_indicator({})['detail'] == '指标数据不足'
