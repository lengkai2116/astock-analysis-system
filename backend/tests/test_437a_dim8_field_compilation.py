"""437-A 字段级归集编排单测：dim8 _compose_dim_text/_compose_dim_evidence/_segment_from_dim

覆盖（2026-09-20 机制层改造）：
  - F1 T 字段拼 text：按 _DIM8_T_SUBJECTS 顺序拼「字段名:值」子句
  - F2 E 字段进 evidence：按 _DIM8_E_FIELDS 收集；空值/'无'/None 跳过
  - F3 缺字段不占位：字段缺失子句跳过，段仍产出
  - F4 list[dict] 转中文：买卖点 buy_sell_points_detail → 一买(price)
  - F5 数值转表述：atr_pct/dist_to_*_pct 按 _DIM8_E_FORMAT 转自然语言
  - F6 text 全空回退 _brief_text（无 T 字段时）
  - F7 缺维 → None（437-A D7 缺维不产段）
  - F8 估值去重：summary 已含"估值："时不重复追加（437-A D2）
  - F9 契约回归：段结构字段齐备（title/light/text/evidence/confidence/judgment/audit/plain）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine,
    _compose_dim_text,
    _compose_dim_evidence,
    _segment_from_dim,
    _valuation_sentence,
)

_SEG_FIELDS = ['title', 'light', 'text', 'evidence', 'confidence',
               'judgment', 'audit', 'plain']


def _mk_dim(src_key='volume_price', sd=None, jg=None, au=None):
    """构造单维 dim_results"""
    return {
        src_key: {
            'judgment': jg or {'overall_light': 'yellow', 'overall_direction': 0,
                               'continuous_value': 0.5},
            'status_description': sd or {'plain': '现状说明'},
            'audit': au or {'conditions': [], 'satisfied_count': 0, 'total_count': 0,
                            'confidence': 1.0},
        }
    }


# ── F1: T 字段拼 text ─────────────────────────────────────

class TestComposeText:

    def test_t_fields_joined_in_order(self):
        """volume_price T 字段按序拼「字段名:值」子句"""
        sd = {'vp_state': '强健康', 'health_score': '8/10（强健康）',
              'volume_energy': '量比1.3，温和放量', 'vol_ratio': '量比1.3',
              'pattern': '无明确形态', 'pattern_score': '5.0/10', 'rps': '64.5/100'}
        text = _compose_dim_text('volume_price', {}, sd)
        assert '量价状态:强健康' in text
        assert '健康度:8/10（强健康）' in text
        assert 'RPS:64.5/100' in text
        # 顺序：vp_state 在 rps 之前
        assert text.index('量价状态') < text.index('RPS')

    def test_missing_field_skipped(self):
        """缺字段不占位：仅有的字段拼句，段仍产出"""
        sd = {'vp_state': '中性'}
        text = _compose_dim_text('volume_price', {}, sd)
        assert text == '量价状态:中性'

    def test_none_field_skipped(self):
        """none/None/空值字段全部跳过 → 回退 _brief_text"""
        sd = {'vp_state': None, 'health_score': '', 'volume_energy': 'none'}
        text = _compose_dim_text('volume_price', {'state': '中性'}, sd)
        assert '量价状态' not in text
        assert text  # 回退 _brief_text 非空


# ── F2/F5: E 字段收集 + 数值转表述 ─────────────────────────

class TestComposeEvidence:

    def test_e_fields_collected(self):
        """volume_price E 字段进 evidence；空值跳过"""
        sd = {'divergence': '无背离信号', 'granville': '回探缩量（回调缩量）'}
        ev = _compose_dim_evidence('volume_price', sd)
        assert '无背离信号' in ev
        assert '回探缩量（回调缩量）' in ev

    def test_empty_and_placeholder_skipped(self):
        """'无'/'none'/None/'' 占位值全部跳过"""
        sd = {'divergence': '无', 'granville': ''}
        assert _compose_dim_evidence('volume_price', sd) == []

    def test_numeric_format(self):
        """risk 数值字段转表述（437 §七-6 不裸放数值）"""
        sd = {'atr_pct': 2.9475, 'volatility_percentile': 0.778,
              'dist_to_support_pct': -5.71, 'rr_assessment': '盈亏比0.42<1R'}
        ev = _compose_dim_evidence('risk', sd)
        assert any('ATR占比2.95%' in e for e in ev)
        assert any('波动率历史分位78%' in e for e in ev)
        assert any('距防守位-5.7%' in e for e in ev)
        assert not any(e in ('2.9475', '0.778', '-5.71') for e in ev)  # 无裸数值

    def test_list_field_expanded(self):
        """列表字段展开为多条（risk E 字段里的列表：event_summary/invalidation）"""
        sd = {'event_summary': ['龙虎榜机构净买52525万', '涨停', '突破: 站上60日线+20日新高']}
        ev = _compose_dim_evidence('risk', sd)
        assert len(ev) == 3


# ── F4: list[dict] 转中文 ──────────────────────────────────

class TestListDictFlatten:

    def test_buy_sell_points_detail_cn(self):
        """structure 买卖点 detail list[dict] 转中文（437-A 键名修正③）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _flatten_value
        v = [{'type': 'buy', 'point_type': 'first_buy', 'confirmed': True,
              'confidence': 1.0, 'price': 2.98}]
        s = _flatten_value(v)
        assert '一买' in s
        assert '2.98' in s

    def test_empty_list_skipped_in_text(self):
        """空买卖点列表 → text 子句跳过（不产出'买卖点:'空句）"""
        sd = {'chanlun_direction': 'up', 'buy_sell_points_detail': []}
        text = _compose_dim_text('structure', {}, sd)
        assert '买卖点' not in text
        assert '缠论方向:up' in text


# ── F7: 缺维 → None ───────────────────────────────────────

class TestSegmentMissingDim:

    def test_missing_dim_returns_none(self):
        """缺维（D7：缺维不产段）"""
        assert _segment_from_dim({}, 'volume_price', '量价') is None
        assert _segment_from_dim({'volume_price': {}}, 'volume_price', '量价') is None


# ── F8: 估值去重 ───────────────────────────────────────────

class TestValuationDedup:

    def test_valuation_sentence(self):
        """_valuation_sentence 从 valuation 维取 T 字段拼句"""
        val = {'status_description': {'valuation_level': '合理（composite=0.026）',
                                      'potential_score': '71/100',
                                      'fina_health': '财务健康✅(pass)'}}
        s = _valuation_sentence({'valuation': val})
        assert '估值水平:合理' in s
        assert '财务健康:财务健康✅(pass)' in s

    def test_valuation_empty_returns_empty(self):
        """无 valuation / 全空 → ''（D2 降级不占位）"""
        assert _valuation_sentence({}) == ''
        assert _valuation_sentence({'valuation': {'status_description': {'valuation_level': None}}}) == ''


# ── F9: 契约回归 ───────────────────────────────────────────

class TestSegmentContract:

    def test_segment_fields_complete(self):
        """段结构字段齐备（436 契约）"""
        dr = _mk_dim('volume_price', sd={'vp_state': '强健康', 'divergence': '无背离信号'})
        seg = _segment_from_dim(dr, 'volume_price', '量价健康度')
        assert seg is not None
        assert all(f in seg for f in _SEG_FIELDS)
        assert seg['text'] == '量价状态:强健康'
        assert '无背离信号' in seg['evidence']

    def test_segment_d7_absent_dim_skipped(self):
        """build_seven_dim_report 缺维不产段但 summary 恒在"""
        dr = _mk_dim('volume_price', sd={'vp_state': '中性'})
        r = Dim8SummaryEngine().build_seven_dim_report(dr, tags={}, ts_code=None)
        assert r is not None
        assert 'volume_price' in r
        assert 'summary' in r
        # 其余维缺失 → 段不产出
        assert 'structure' not in r
        assert 'risk' not in r
