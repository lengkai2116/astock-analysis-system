"""479号-1 dim8 结构性修正单测：T/E 表按定稿清理 + P9-P15 + 中文化扩展

覆盖（479-1，dim2-dim7 定稿后收口）：
  - T1 T 表清理：structure 删 chanlun_strength；volume_price 删 health_score/pattern_score/vol_ratio
  - T2 P15：risk 段内分「价格位置/风险状态」两小节（subsections）
  - T3 P9：audit.conditions 透传 actual/threshold（现状本体不再丢失）
  - T4 P10：evidence 截断 5→12（茅台 13 条候选不再只显 5 条）
  - T5 P11：中文化网关接入 dim6（volatility_level low/medium → 低/中）
  - T6 P12：risk_factors 呈现时剥离事件条目（事件主源 event_details）
  - T7 P13/P14：event_details/piers_leverage 渲染（dict/dict-list）
  - T8 dim2 §六-②：trend_structure_signal 条件采用（'none' 跳过、非 none 产句）
  - T9 dim3 细项6：rps 转表述（RPS=64.5（前 36% 分位））
  - T10 dim7 定稿：_valuation_sentence 无评分/fina_health；potential_breakdown 六维解析
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine,
    _DIM8_T_SUBJECTS,
    _DIM8_E_FIELDS,
    _compose_dim_text,
    _compose_dim_evidence,
    _segment_from_dim,
    _valuation_sentence,
    _parse_potential_breakdown,
    _to_display_text,
)


def _mk_dim(src_key, sd=None, jg=None, au=None):
    return {
        src_key: {
            'judgment': jg or {'overall_light': 'yellow', 'overall_direction': 0,
                               'continuous_value': 0.5},
            'status_description': sd or {},
            'audit': au or {'conditions': [], 'satisfied_count': 0, 'total_count': 0,
                            'confidence': 1.0},
        }
    }


# ── T1: T 表清理（评分归 JUD / 去重） ─────────────────────

class TestTSubjectCleanup:

    def test_structure_no_chanlun_strength(self):
        """structure T 表不含 chanlun_strength（dim2 定稿 §七①：评分归 JUD，dim8 不产句）"""
        assert 'chanlun_strength' not in _DIM8_T_SUBJECTS['structure']

    def test_volume_price_no_score_keys(self):
        """volume_price T 表不含 health_score/pattern_score/vol_ratio（dim3 定稿：归 JUD/去重）"""
        vp = _DIM8_T_SUBJECTS['volume_price']
        assert 'health_score' not in vp
        assert 'pattern_score' not in vp
        assert 'vol_ratio' not in vp

    def test_text_excludes_removed_keys(self):
        """text 不再拼评分/去重键（即使引擎仍产）"""
        sd = {'vp_state': '强健康', 'health_score': '9/10（强健康）',
              'pattern_score': '10.0/10', 'vol_ratio': '量比6.7'}
        text = _compose_dim_text('volume_price', {}, sd)
        assert '量价状态:强健康' in text
        assert '健康度' not in text and '形态评分' not in text and '量比:' not in text

    def test_structure_text_excludes_chanlun_strength(self):
        """structure text 不含 chanlun_strength 子句"""
        sd = {'chanlun_direction': 'up', 'chanlun_strength': '38'}
        text = _compose_dim_text('structure', {}, sd)
        assert '缠论方向:up' in text
        assert '结构强度' not in text


# ── T2: P15 risk 段两小节 ─────────────────────────────────

class TestRiskSubsections:

    def test_risk_two_subsections(self):
        """risk 段内分「价格位置/风险状态」两小节（dim6 定稿 §4.2）"""
        dr = _mk_dim('risk', sd={
            'risk_level': '高', 'risk_detail': '缠论风险维度为「高」',
            'support_price': 1166.33, 'resistance_price': 1284.79,
            'dist_to_support_pct': -6.98, 'dist_to_resistance_pct': 2.47,
            'dist_to_prev_high_pct': -6.35, 'rr_value': 0.35, 'rr_level': '不值得交易',
            'volatility_level': 'low', 'risk_factors': ['缠论风险：高风险（高）'],
        })
        seg = _segment_from_dim(dr, 'risk', '风险边界状态')
        assert seg is not None
        assert 'subsections' in seg
        titles = [s['title'] for s in seg['subsections']]
        assert titles == ['价格位置', '风险状态']
        pos_items = seg['subsections'][0]['items']
        risk_items = seg['subsections'][1]['items']
        assert any('防守位:1166.33' in i for i in pos_items)
        assert any('距前高:-6.35' in i for i in pos_items)
        assert any('风险等级:高' in i for i in risk_items)
        assert any('风险明细' in i for i in risk_items)
        assert any('波动率:低' in i for i in risk_items)  # P11 中文化已生效

    def test_no_subsections_for_other_dims(self):
        """非 chip_fund/risk 维无 subsections 键"""
        dr = _mk_dim('volume_price', sd={'vp_state': '强健康'})
        seg = _segment_from_dim(dr, 'volume_price', '量价健康度')
        assert 'subsections' not in seg


# ── T3: P9 audit actual/threshold 透传 ─────────────────────

class TestAuditActualThreshold:

    def test_actual_threshold_passed(self):
        """段内 audit.conditions 透传 actual/threshold（现状本体不丢失）"""
        au = {'conditions': [
            {'name': '风险等级', 'satisfied': False, 'actual': '高', 'threshold': '低或中'},
            {'name': '流动性', 'satisfied': True, 'actual': '达标', 'threshold': '达标'},
        ], 'satisfied_count': 1, 'total_count': 2, 'confidence': 0.5}
        dr = _mk_dim('risk', sd={'risk_level': '高'}, au=au)
        seg = _segment_from_dim(dr, 'risk', '风险边界状态')
        conds = seg['audit']['conditions']
        assert len(conds) == 2
        c0 = next(c for c in conds if c['name'] == '风险等级')
        assert c0['satisfied'] is False
        assert c0['actual'] == '高'
        assert c0['threshold'] == '低或中'
        c1 = next(c for c in conds if c['name'] == '流动性')
        assert c1['actual'] == '达标'

    def test_missing_actual_threshold_ok(self):
        """源条件无 actual/threshold → 键存在但为 None（前端 c.detail || c.name 兜底不崩）"""
        au = {'conditions': [{'name': '量价关系', 'satisfied': True}],
              'satisfied_count': 1, 'total_count': 1, 'confidence': 1.0}
        dr = _mk_dim('volume_price', sd={'vp_state': '强健康'}, au=au)
        seg = _segment_from_dim(dr, 'volume_price', '量价健康度')
        c = seg['audit']['conditions'][0]
        assert 'actual' in c and 'threshold' in c
        assert c['actual'] is None and c['threshold'] is None


# ── T4: P10 evidence 截断 5→16 ─────────────────────────────

class TestEvidenceCapacity:

    def test_evidence_cap_16(self):
        """evidence 上限放宽至 16（原 5 条截断致「因」丢失；479-2 后 11 定理+背驰细节总量大）"""
        sd = {'vs_zhongshu': '中枢内部', 'vs_ma': '站上均线', 'vs_indicator': 'RSI 62',
              'divergence': '无背驰', 'divergence_type': '无',
              'trend_structure_signal': 'none'}
        au = {'conditions': [{'name': f'条件{i}', 'satisfied': True} for i in range(16)],
              'satisfied_count': 16, 'total_count': 16, 'confidence': 1.0}
        dr = _mk_dim('structure', sd=sd, au=au)
        seg = _segment_from_dim(dr, 'structure', '结构位置状态')
        # 5 条 E 字段 + 16 条 satisfied 条件（去重后）> 5 → 验证截断已放宽
        assert len(seg['evidence']) > 5
        assert len(seg['evidence']) <= 16


# ── T5: P11 中文化网关扩展 ────────────────────────────────

class TestCnGatewayExtension:

    def test_volatility_level_cn(self):
        """dim6 volatility_level low/medium/high → 低/中/高（T 表 text 与小节 items）"""
        assert _to_display_text('波动率:low') == '波动率:低'
        assert _to_display_text('波动率:medium') == '波动率:中'
        assert _to_display_text('波动率:high') == '波动率:高'

    def test_volatility_word_boundary(self):
        """独立成词替换，防误伤含子串的英文（low_level 等拼接键）"""
        assert _to_display_text('volatility_low_level') == 'volatility_low_level'

    def test_existing_mappings_intact(self):
        """既有映射（拥挤度/指标缩写/缠论方向）不回归"""
        assert _to_display_text('拥挤度=MODERATE') == '拥挤度=适中'
        assert _to_display_text('ASR=42') == 'ASR（活跃筹码比率）=42'
        assert _to_display_text('缠论方向:up') == '缠论方向:上升'

    def test_point_type_variant_cn(self):
        """买卖点 465-1B 变体（first_buy_p/third_buy_a 等）中文化（dim8 展示层）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _flatten_value
        assert _flatten_value({'type': 'buy', 'point_type': 'first_buy_p', 'price': 295.5}) == '一买(295.5)'
        assert _flatten_value({'type': 'sell', 'point_type': 'third_buy_a'}) == '三买'
        assert _flatten_value({'type': 'buy', 'point_type': 'second_buy_b'}) == '二买'
        assert _flatten_value({'type': 'sell', 'point_type': 'first_sell_p'}) == '一卖'
        # 未知类型原样保留（不崩）
        assert _flatten_value({'type': 'buy', 'point_type': 'weird_x'}) == 'weird_x'


# ── T6: P12 risk_factors 剥离事件条目 ─────────────────────

class TestRiskFactorsStrip:

    def test_event_items_stripped_from_text(self):
        """risk T 表 risk_factors 呈现时剥离事件条目（事件主源 event_details，3A 落地）"""
        sd = {'risk_level': '高',
              'risk_factors': ['缠论风险：高风险（高）', '事件风险：龙虎榜（高）',
                               '事件风险：ST预警（极高）']}
        text = _compose_dim_text('risk', {}, sd)
        assert '风险等级:高' in text
        assert '缠论风险' in text
        assert '事件风险' not in text

    def test_event_items_stripped_from_subsections(self):
        """risk 小节 risk_factors 同样剥离事件条目"""
        dr = _mk_dim('risk', sd={
            'risk_level': '高', 'risk_factors': ['缠论风险：高风险（高）', '事件风险：龙虎榜（高）'],
            'volatility_level': 'low'})
        seg = _segment_from_dim(dr, 'risk', '风险边界状态')
        all_items = [item for s in seg['subsections'] for item in s['items']]
        assert any('缠论风险' in i for i in all_items)
        assert not any('事件风险' in i for i in all_items)


# ── T7: P13/P14 event_details / piers_leverage 渲染 ───────

class TestRiskNewEFields:

    def test_event_summary_removed_from_e_table(self):
        """risk E 表不含 event_summary（P13：事件佐证主源改 event_details）"""
        assert 'event_summary' not in _DIM8_E_FIELDS['risk']
        assert 'event_details' in _DIM8_E_FIELDS['risk']
        assert 'piers_leverage' in _DIM8_E_FIELDS['risk']
        assert 'dist_to_prev_high_pct' in _DIM8_E_FIELDS['risk']

    def test_event_details_dict_list_rendered(self):
        """event_details dict-list → 每条转中文句（事件话术主源）"""
        sd = {'event_details': [{'event_type': 'longhubang', 'description': '龙虎榜机构净买 12449 万',
                                 'direction': 2, 'confidence': 0.8, 'event_date': '2026-06-30'}]}
        ev = _compose_dim_evidence('risk', sd)
        assert any('龙虎榜机构净买 12449 万' in e for e in ev)

    def test_piers_leverage_dict_rendered(self):
        """piers_leverage dict → 负债率/ROCE 中文渲染（不再只取第一个子值丢 roce）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _flatten_value
        v = {'debt_to_assets': 73.51, 'roce': -17.77}
        s = _flatten_value(v)
        assert '负债率73.5%' in s
        assert 'ROCE -17.8%' in s

    def test_piers_leverage_in_evidence(self):
        """risk E 表 piers_leverage 进 evidence（P14）"""
        sd = {'piers_leverage': {'debt_to_assets': 73.51, 'roce': -17.77}}
        ev = _compose_dim_evidence('risk', sd)
        assert any('负债率73.5%' in e and 'ROCE -17.8%' in e for e in ev)


# ── T8: B8 trend_structure_signal 条件采用 ─────────────────

class TestTrendStructureConditional:

    def test_none_skipped(self):
        """trend_structure_signal='none' → 不产句（dim2 定稿 §四：条件采用）"""
        sd = {'trend_structure_signal': 'none'}
        ev = _compose_dim_evidence('structure', sd)
        assert ev == []

    def test_non_none_produced(self):
        """trend_structure_signal≠none → 产句（'123 买点突破形态'）"""
        sd = {'trend_structure_signal': '123_buy_breakout'}
        ev = _compose_dim_evidence('structure', sd)
        assert any('123_buy_breakout' in e for e in ev)


# ── T9: rps 转表述（dim3 细项6） ──────────────────────────

class TestRpsPhrase:

    def test_rps_converted_to_percentile(self):
        """"64.5/100" → RPS=64.5（近20日涨幅全市场前36%分位）"""
        text = _compose_dim_text('volume_price', {}, {'rps': '64.5/100'})
        assert 'RPS=64.5（近20日涨幅全市场前36%分位）' in text
        assert 'RPS:64.5/100' not in text

    def test_rps_data_missing_skipped(self):
        """rps 数据不足 → 不产 rps 子句（无值跳过）"""
        text = _compose_dim_text('volume_price', {}, {'rps': '数据不足', 'vp_state': '中性'})
        assert '量价状态:中性' in text
        assert 'RPS' not in text


# ── T10: dim7 定稿 _valuation_sentence / potential_breakdown ──

class TestValuationSentence479:

    def test_no_score_no_fina_health(self):
        """收益驱动句不含评分键/fina_health（仅 JUD / 去重归 dim6）"""
        sd = {'valuation_level': '极度低估（composite=1.2134）',
              'pe_percentile': 'PE近5年3.1%分位',
              'potential_score': '潜力评分89/100',
              'fina_health': '财务健康✅(pass)'}
        s = _valuation_sentence({'valuation': {'status_description': sd}})
        assert '极度低估（composite=1.2134）' in s
        assert 'PE近5年3.1%分位' in s
        assert '潜力评分' not in s and '财务健康' not in s

    def test_potential_breakdown_six_dims(self):
        """potential_breakdown JSON → 六维明细（B 方案标注来源）"""
        s = _parse_potential_breakdown(
            '{"val":1.0,"earn":0.986,"sector":0.5,"event":0.6,"fund":0.3,"trend":0.5}')
        assert '估值分位 1.00' in s
        assert 'ROE分位 0.99' in s
        assert '板块 0.50（板块→第一层）' in s
        assert '事件 0.60' in s
        assert '资金 0.30（资金→dim4）' in s
        assert '趋势 0.50（趋势→dim2/3）' in s

    def test_potential_breakdown_invalid_returns_empty(self):
        """解析失败/空 → []（437 缺则降级）"""
        assert _parse_potential_breakdown('not-json') == []
        assert _parse_potential_breakdown({}) == []
        assert _parse_potential_breakdown(None) == []

    def test_summary_valuation_tail_once(self):
        """summary 尾置收益驱动句仅一次（无 _generate_text 估值段重复）；
        '估值条件 N/M' 验证句属话术一部分，与前缀"估值："不构成双段"""
        dr = _mk_dim('volume_price', sd={'vp_state': '强健康'})
        dr['valuation'] = {'status_description': {'valuation_level': '合理（composite=0.026）',
                                                  'pe_percentile': 'PE近5年50%分位'},
                           'audit': {'satisfied_count': 5, 'total_count': 8, 'confidence': 0.6}}
        r = Dim8SummaryEngine().build_seven_dim_report(dr, tags={}, ts_code=None)
        text = r['summary']['text']
        assert text.count('估值：') == 1  # 尾置前缀唯一（_generate_text 不再产"估值："）
        # 480号 后续：尾置收益驱动句先过中文网关——composite→综合评分、PE近5年→市盈率近5年
        assert '合理（综合评分=0.026）' in text
        assert '市盈率近5年50%分位' in text
        assert '估值条件 5/8 满足' in text
