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
        """volume_price T 字段按序拼「字段名:值」子句（479号：评分键移出 T 表、rps 转表述）"""
        sd = {'vp_state': '强健康', 'health_score': '8/10（强健康）',
              'volume_energy': '量比1.3，温和放量', 'vol_ratio': '量比1.3',
              'pattern': '无明确形态', 'pattern_score': '5.0/10', 'rps': '64.5/100'}
        text = _compose_dim_text('volume_price', {}, sd)
        assert '量价状态:强健康' in text
        # 479号：评分键（health_score/pattern_score）归 JUD、vol_ratio 去重并入 volume_energy
        assert '健康度' not in text
        assert '形态评分' not in text
        assert '量比:' not in text  # vol_ratio 独立子句不产（值内的"量比1.3"不受影响）
        # 479号：rps 转表述（dim3 细项6：RPS=61.5（近20日涨幅全市场前 38% 分位））
        assert 'RPS=64.5（近20日涨幅全市场前36%分位）' in text
        assert 'RPS:64.5/100' not in text
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
        """列表字段展开为多条（479号 P13：event_summary 移出 E 表，事件佐证主源改 event_details）"""
        sd = {'event_details': [{'event_type': 'longhubang', 'description': '龙虎榜机构净买52525万'},
                                {'event_type': 'breakout', 'description': '突破: 站上60日线+20日新高'}]}
        ev = _compose_dim_evidence('risk', sd)
        assert len(ev) == 2
        assert any('龙虎榜机构净买52525万' in e for e in ev)


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
        """_valuation_sentence 按 dim7 定稿话术模板（479号）：主结论+因+陷阱+潜力+验证；
        评分（potential_score/strength）仅 JUD、fina_health 去重归 dim6 → 不再拼入"""
        val = {'status_description': {
                   'valuation_level': '极度低估（composite=1.2134）',
                   'pe_percentile': 'PE近5年3.1%分位',
                   'pb_percentile': 'PB近5年5.1%分位',
                   'fcf_yield': '自由现金流收益率1.8786%',
                   'dividend_yield': '股息率4.15%',
                   'revenue_growth': '营收同比增长1.47%',
                   'value_trap': 'ROCE低于15%，存在价值陷阱风险',
                   'potential_score': '潜力评分89/100',
                   'potential_strength': '潜力强度89/100',
                   'fina_health': '财务健康✅(pass)',
                   'potential_breakdown': '{"val":1.0,"earn":0.986,"sector":0.5,"event":0.6,"fund":0.3,"trend":0.5}'},
               'audit': {'satisfied_count': 8, 'total_count': 8, 'confidence': 1.0}}
        s = _valuation_sentence({'valuation': val})
        # 主结论 + 因（分位/现金流/股息/营收）
        assert '极度低估（composite=1.2134）' in s
        assert 'PE近5年3.1%分位' in s and 'PB近5年5.1%分位' in s
        assert '自由现金流收益率1.8786%' in s and '股息率4.15%' in s
        # 陷阱现状句
        assert 'ROCE低于15%，存在价值陷阱风险' in s
        # 潜力六维解析（B 方案来源标注）
        assert '潜力六维：估值分位 1.00' in s
        assert '资金 0.30（资金→dim4）' in s
        assert '板块 0.50（板块→第一层）' in s
        # 验证句（动态读 audit）
        assert '估值条件 8/8 满足' in s
        # 评分/fina_health 不拼入（仅 JUD / 去重归 dim6）
        assert '潜力评分' not in s
        assert '潜力强度' not in s
        assert '财务健康' not in s

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


# ── F10: D1 subsections（fund_chip 内分两小节） ────────────

class TestSubsections:

    def test_chip_fund_subsections(self):
        """fund_chip 段含 subsections（筹码成本/资金博弈两小节）"""
        dr = _mk_dim('chip_fund', sd={
            'phase': '建仓期', 'cost_structure': '筹码集中', 'crowding': '拥挤度=MODERATE',
            'fund_flow': '强流入', 'margin': '融资正常',
        })
        seg = _segment_from_dim(dr, 'chip_fund', '资金与筹码状态')
        assert seg is not None
        assert 'subsections' in seg
        titles = [s['title'] for s in seg['subsections']]
        assert '筹码成本' in titles and '资金博弈' in titles
        # 小节内 items 非空
        all_items = [item for s in seg['subsections'] for item in s['items']]
        assert any('主力阶段' in i for i in all_items)
        assert any('资金流' in i for i in all_items)

    def test_no_subsections_for_other_dims(self):
        """非 fund_chip 维无 subsections 键"""
        dr = _mk_dim('volume_price', sd={'vp_state': '强健康'})
        seg = _segment_from_dim(dr, 'volume_price', '量价健康度')
        assert seg is not None
        assert 'subsections' not in seg


# ── F11: D4 emotion T 去重（stock 主源 dim3） ──────────────

class TestEmotionDedup:

    def test_emotion_t_excludes_stock(self):
        """emotion 段 T 不含 stock（个股情绪主源 dim3 vp_state，437-A §三-1）"""
        sd = {'market': '市场处于发酵', 'sector': '板块排名前10', 'stock': '个股健康',
              'quadrant': '中性', 'temperature': '55/100'}
        text = _compose_dim_text('emotion', {}, sd)
        assert '个股情绪' not in text  # stock 已移出 T
        assert '市场情绪' in text


# ── F12: signal 移出（2026-09-15 裁决） ────────────────────

class TestSignalExcluded:

    def test_build_report_no_signal_key(self):
        """build_seven_dim_report 不再产出 signal 段"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import SEVEN_DIM_SPEC
        dr = _mk_dim('volume_price', sd={'vp_state': '中性'})
        dr['signal'] = {'judgment': {'overall_light': 'green'},
                        'status_description': {'attribute': '强确认'}}
        r = Dim8SummaryEngine().build_seven_dim_report(dr, tags={'right_side_confirm': '强确认'},
                                                       ts_code=None)
        assert 'signal' not in r
        # SEVEN_DIM_SPEC 不含 signal
        assert 'signal' not in [s[0] for s in SEVEN_DIM_SPEC]


# ── F13: audit satisfied 项入 evidence（437 §一-5） ────────

class TestAuditEvidence:

    def test_satisfied_conditions_in_evidence(self):
        """audit.conditions 中 satisfied 项作 evidence 底料"""
        au = {'conditions': [{'name': '量价关系', 'satisfied': True},
                             {'name': '背离检测', 'satisfied': False}],
              'satisfied_count': 1, 'total_count': 2, 'confidence': 0.5}
        dr = _mk_dim('volume_price', sd={'vp_state': '强健康'}, au=au)
        seg = _segment_from_dim(dr, 'volume_price', '量价健康度')
        assert '量价关系' in seg['evidence']      # satisfied 项入 evidence
        assert '背离检测' not in seg['evidence']  # 未满足项不入


# ── F14: D3 环境定位（大盘/板块） ──────────────────────────

class TestEnvironmentSentences:

    def test_market_state_sentence(self):
        """大盘状态句：ma20_ratio/涨停/封板率转自然语言"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _market_state_sentence
        sig = {'data_context': {'market_stats': {'ma20_ratio': 0.62, 'limit_up_count': 85,
                                                 'sealing_rate': 0.7}}}
        s = _market_state_sentence({'signal': sig})
        assert '全市场MA20强势占比62%（偏强）' in s
        assert '涨停85家' in s
        assert '封板率70%' in s

    def test_market_state_no_data_returns_empty(self):
        """无 market_stats → ''（437 缺则降级）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _market_state_sentence
        assert _market_state_sentence({}) == ''
        assert _market_state_sentence({'signal': {'data_context': {}}}) == ''

    def test_sector_position_no_data_returns_empty(self):
        """无 sector_heat / 无行业映射 → ''（437 缺则降级）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _sector_position_sentence
        assert _sector_position_sentence({}, 'TEST') == ''
        assert _sector_position_sentence({'signal': {'data_context': {'sector_heat': {}}}}, 'TEST') == ''
