"""482号 dim8 展示层收尾单测（纯展示层，无 DB）

覆盖：
  - 482-1 risk 小节数值套 _DIM8_E_FORMAT（不再裸小数）
  - 482-2 事件枚举中文化（event_details → 描述/中文名；'事件升格：en'）
  - 482-3 dim3 背离类型中文化（top/bottom → 顶/底背离）
  - 482-4 拼接字段名后全角冒号（与段级话术一致）+ 指标释义正则兼容
  - 482-5 structure evidence 调试标记清洗
  - 482-6 dim_adapter temperature 展示串安全转换（不崩溃）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import re

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    _to_display_text, _flatten_value, _compose_dim_subsections, _compose_dim_text,
)


class TestT482_1SubsectionFormat:
    """482-1：subsection 数值套 _DIM8_E_FORMAT，与 evidence 同形"""

    def test_atr_and_volatility_formatted(self):
        sd = {'atr_pct': 1.3858990645571108, 'volatility_percentile': 0.08413461538461539,
              'risk_level': '高'}
        groups = _compose_dim_subsections('risk', sd)
        items = [it for g in groups for it in g['items']]
        joined = '；'.join(items)
        assert 'ATR占比1.39%' in joined, joined
        assert '波动率历史分位8%' in joined, joined
        assert 'ATR占比：' not in joined, f'模板命中不应再加标签前缀: {joined}'
        assert not re.search(r'\d+\.\d{6,}', joined), f'裸小数残留: {joined}'

    def test_dist_fields_formatted(self):
        sd = {'dist_to_support_pct': -5.4321, 'dist_to_resistance_pct': 4.0499}
        groups = _compose_dim_subsections('risk', sd)
        joined = '；'.join(it for g in groups for it in g['items'])
        assert '距防守位-5.4%' in joined and '距压力位4.0%' in joined, joined


class TestT482_2EventCN:
    """482-2：事件枚举中文化"""

    def test_flatten_event_dict_prefers_description(self):
        v = {'event_type': 'longhubang', 'description': '龙虎榜机构净买 12449 万',
             'event_date': '2026-06-30', 'confidence': 0.8}
        assert _flatten_value(v) == '龙虎榜机构净买 12449 万'

    def test_flatten_event_dict_fallback_cn(self):
        # 无 description → 用中文事件名兜底（不再返回裸 event_type）
        assert _flatten_value({'event_type': 'holder_concentration'}) == '股东集中'
        assert _flatten_value({'event_type': 'breakout'}) == '突破'

    def test_event_list_no_raw_enum(self):
        v = [{'event_type': 'longhubang', 'description': '龙虎榜机构净买 12449 万'},
             {'event_type': 'breakout'}]
        out = _flatten_value(v)
        assert 'longhubang' not in out and 'breakout' not in out, out
        assert '龙虎榜机构净买 12449 万' in out and '突破' in out

    def test_gateway_event_promote_note(self):
        s = '风险明细：1个高风险源：财务风险（事件升格：longhubang）'
        out = _to_display_text(s)
        assert '（事件升格：龙虎榜）' in out, out
        assert 'longhubang' not in out

    def test_gateway_event_enum_in_text(self):
        out = _to_display_text('事件：longhubang、breakout')
        assert '龙虎榜' in out and '突破' in out, out
        assert 'longhubang' not in out and 'breakout' not in out


class TestT482_3DivergenceCN:
    """482-3：dim3 背离类型中文化（展示层）"""

    def test_bottom_with_conf(self):
        out = _to_display_text('bottom（置信1.00）')
        assert out == '底背离（置信1.00）', out

    def test_top_with_conf(self):
        out = _to_display_text('top（置信0.33）')
        assert out == '顶背离（置信0.33）', out

    def test_bare_type(self):
        assert _to_display_text('bottom') == '底背离'
        assert _to_display_text('top') == '顶背离'

    def test_no_mangle_word_containing(self):
        # 'bottomland' 之类拼接词不被命中（独立成词约束）
        out = _to_display_text('bottomland')
        assert out == 'bottomland', out


class TestT482_4FullwidthColon:
    """482-4：字段名后全角冒号 + 指标释义正则兼容全角"""

    def test_text_clause_fullwidth_colon(self):
        out = _compose_dim_text('risk', {}, {'risk_level': '高'})
        assert '风险等级：高' in out, out
        assert '风险等级:高' not in out

    def test_subsection_fullwidth_colon(self):
        groups = _compose_dim_subsections('risk', {'risk_level': '高'})
        joined = '；'.join(it for g in groups for it in g['items'])
        assert '风险等级：高' in joined, joined

    def test_indicator_gloss_with_fullwidth_colon(self):
        # 482-4 兼容：指标缩写在 '字段：ASR=42' 语境仍补释义
        out = _to_display_text('筹码结构：筹码稳定，ASR=25，CYQKL=1.6')
        assert 'ASR（活跃筹码比率）=25' in out and 'CYQKL（筹码穿透力）=1.6' in out, out

    def test_env_sentence_ma20_cn(self):
        # 482 追加：环境定位句（summary 前置）在网关后拼接 → 补过网关，MA20→20日均线
        out = _to_display_text('大盘状态：全市场MA20强势占比39%（偏弱）')
        assert '20日均线' in out and 'MA20' not in out, out

    def test_engine_produced_colon_normalized(self):
        # 482-4 收尾：引擎自产串中文后半角冒号 → 全角（dim4 '投票:' / dim3 '低点: '）
        assert _to_display_text('投票:筹码形态=建仓') == '投票：筹码形态=建仓'
        assert _to_display_text('低点: 3.03, 2.98') == '低点： 3.03, 2.98'
        # 不涉中文的半角冒号不动（防误伤英文/时间）
        assert _to_display_text('a: b') == 'a: b'


class TestT482_5StructureEvidenceCleanup:
    """482-5：structure evidence 调试标记清洗（仅展示层）"""

    def test_theorem_prefix_dedup(self):
        s = 't1 未通过(0.00) T1 走势必完美：每个线段至少包含3笔：无线段数据'
        out = _to_display_text(s)
        assert out.startswith('未通过(0.00) T1 走势必完美'), out
        assert not out.startswith('t1 ')

    def test_multidigit_prefix(self):
        out = _to_display_text('t10 未通过(0.00) T10 动力结构：同向笔力度减弱')
        assert out.startswith('未通过(0.00) T10 动力结构'), out

    def test_stroke_cn(self):
        out = _to_display_text('同向笔力度减弱: Stroke(上升, 213->229, 1730.00->1970.00)')
        assert 'Stroke(' not in out and '笔(上升, 213->229' in out, out

    def test_cv_and_p1_and_vs_and_trend(self):
        assert '（变异系数<' in _to_display_text('各线段笔数应相近(CV<0.5)：无线段')
        assert 'P1-#8' not in _to_display_text('关联P1-#8特征序列缺口处理（占位实现）')
        assert '价格相对中枢' in _to_display_text('价格vs中枢')
        assert '（趋势）' in _to_display_text('中枢数判走势类型（trend）：多中枢方向不一致')

    def test_vs_not_mangled_when_latin_adjacent(self):
        # 'pricesvs' 之类两侧非 CJK 不替换
        assert _to_display_text('a vs b') == 'a vs b'


class TestT482_6TemperatureSafeFloat:
    """482-6：dim_adapter temperature 展示串安全转换（不再崩溃）"""

    def test_convert_to_dims_format_no_crash_on_display_string(self):
        from app.opportunity_atlas import dim_adapter
        dr = {'emotion': {'status_description': {'temperature': '中性58.1/100'},
                          'judgment': {}, 'audit': {}}}
        out = dim_adapter.convert_to_dims_format(dr, {})  # 不应抛 ValueError
        assert isinstance(out, dict)

    def test_safe_float_on_display_string(self):
        from app.opportunity_atlas.dim_adapter import _safe_float
        assert _safe_float('中性58.1/100', 50.0) == 50.0


def _all_tests():
    import pytest
    pytest.main([__file__, '-v'])
