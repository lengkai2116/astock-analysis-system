"""436号 B1 契约单测：dim8 整体归集器产出 seven_dim_json 对齐前端契约

覆盖 §5.1 T1-T10：
  - T1 全维齐备 → 恰 7 键 {signal,structure,volume_price,fund_chip,emotion,risk,summary}
        不含 signal_confirm/chip_fund/valuation
  - T2 灯色双轨：顶层 light=emoji，judgment.overall_light 保持颜色名
  - T3 段内字段齐备：title/light/text/evidence/confidence/judgment/audit/plain
  - T4 部分维缺失 → 该键不产出，summary 恒存在
  - T5 dim_results 为 None/{}/非法类型 → 返回 None 不抛异常
  - T6 dim1 回退：无 signal 维但 tags.right_side_confirm 有值 → 产 signal 段；tags 空跳过
  - T7 summary 由 dim8 组装（含状态条/共识率）
  - T8 幂等稳定 + json 往返 emoji 可解析
  - T9 兼容包装 generate_seven_dim_from_signals 不抛异常
  - T10 死代码清除：status_engine 中 snapshot_row 不再出现
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine,
    _segment_from_dim,
)
from app.opportunity_atlas.status_engine import (
    build_seven_dim_from_dim_results,
    generate_seven_dim_from_signals,
)

_SEG_FIELDS = ['title', 'light', 'text', 'evidence', 'confidence',
               'judgment', 'audit', 'plain']
_EXPECTED_KEYS = {'signal', 'structure', 'volume_price', 'fund_chip',
                  'emotion', 'risk', 'summary'}


def _mk_dim_results(overrides=None):
    """构造基准 dim_results：全维 yellow + continuous_value 0.5"""
    base = {}
    for dim in ['signal', 'structure', 'volume_price', 'chip_fund',
                'emotion', 'risk', 'valuation']:
        base[dim] = {
            'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                         'continuous_value': 0.5},
            'status_description': {'plain': f'{dim}现状说明'},
            'audit': {'conditions': [{'name': f'{dim}条件1', 'satisfied': True}],
                      'satisfied_count': 1, 'total_count': 1, 'confidence': 1.0},
        }
    if overrides:
        for dim, patch in overrides.items():
            d = base.get(dim, {})
            if 'judgment' in patch:
                d.setdefault('judgment', {}).update(patch['judgment'])
            if 'status_description' in patch:
                d.setdefault('status_description', {}).update(patch['status_description'])
            if 'audit' in patch:
                d.setdefault('audit', {}).update(patch['audit'])
            base[dim] = d
    return base


# ── T1: 全维齐备 → 恰 7 键、键名契约对齐 ──────────────────

class TestKeyContract:

    def test_full_dims_produce_exact_seven_keys(self):
        dr = _mk_dim_results()
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        assert set(report.keys()) == _EXPECTED_KEYS

    def test_no_legacy_or_valuation_keys(self):
        dr = _mk_dim_results()
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        for banned in ('signal_confirm', 'chip_fund', 'valuation'):
            assert banned not in report, f'不应产出旧键/非前端键: {banned}'

    def test_fund_chip_maps_from_chip_fund_source(self):
        dr = _mk_dim_results()
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        # fund_chip 段必须存在，且数据来自 chip_fund 维
        assert 'fund_chip' in report
        assert 'chip_fund' in dr  # 数据源键仍是 chip_fund


# ── T2: 灯色双轨（顶层 emoji / judgment 颜色名） ──────────

class TestLightDualTrack:

    def test_top_light_is_emoji_judgment_keeps_color(self):
        dr = _mk_dim_results({'structure': {'judgment': {
            'overall_light': 'green', 'overall_direction': 1, 'continuous_value': 0.9}}})
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        seg = report['structure']
        assert seg['light'] == '🟢'
        assert seg['judgment']['overall_light'] == 'green'

    def test_red_and_yellow_emoji(self):
        dr = _mk_dim_results({
            'risk': {'judgment': {'overall_light': 'red', 'overall_direction': -1,
                                  'continuous_value': 0.1}},
            'emotion': {'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                                     'continuous_value': 0.5}},
        })
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        assert report['risk']['light'] == '🔴'
        assert report['emotion']['light'] == '🟡'


# ── T3: 段内字段齐备 ───────────────────────────────────────

class TestSegmentFields:

    def test_every_segment_has_all_contract_fields(self):
        dr = _mk_dim_results()
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        for key, seg in report.items():
            for field in _SEG_FIELDS:
                assert field in seg, f'段 {key} 缺字段: {field}'
            # audit.conditions 条目结构
            for c in seg['audit']['conditions']:
                assert 'name' in c and 'satisfied' in c


# ── T4: 部分维缺失 ────────────────────────────────────────

class TestPartialDims:

    def test_missing_dim_omits_key_but_summary_present(self):
        dr = _mk_dim_results()
        dr.pop('structure', None)  # 缺 structure
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        assert 'structure' not in report
        assert 'summary' in report  # summary 恒存在（门禁依赖）
        # 其余正常维在
        assert 'volume_price' in report and 'risk' in report


# ── T5: dim_results 空/非法 → None ────────────────────────

class TestNoneHandling:

    @pytest.mark.parametrize('bad', [None, {}, [], 'x', 0])
    def test_invalid_dim_results_returns_none(self, bad):
        assert Dim8SummaryEngine().build_seven_dim_report(bad) is None

    @pytest.mark.parametrize('bad', [None, {}, [], 'x'])
    def test_status_engine_entry_returns_none(self, bad):
        assert build_seven_dim_from_dim_results(bad) is None


# ── T6: dim1 回退（tags.right_side_confirm） ───────────────

class TestDim1Fallback:

    def test_fallback_when_no_signal_dim(self):
        dr = _mk_dim_results()
        del dr['signal']  # 无 signal 维
        tags = {'right_side_confirm': '强确认'}
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags=tags)
        assert 'signal' in report
        assert report['signal']['light'] == '🟢'

    def test_no_fallback_when_tags_empty(self):
        dr = _mk_dim_results()
        del dr['signal']
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags={})
        assert 'signal' not in report
        assert 'summary' in report  # 门禁恒含

    def test_no_fallback_when_tags_none(self):
        dr = _mk_dim_results()
        del dr['signal']
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags=None)
        assert 'signal' not in report


# ── T7: summary 由 dim8 组装 ──────────────────────────────

class TestSummary:

    def test_summary_contains_status_bar_and_consensus(self):
        dr = _mk_dim_results({
            'structure': {'judgment': {'overall_light': 'green',
                                       'overall_direction': 1, 'continuous_value': 0.8}},
            'volume_price': {'judgment': {'overall_light': 'green',
                                          'overall_direction': 1, 'continuous_value': 0.8}},
            'signal': {'judgment': {'overall_light': 'green',
                                    'overall_direction': 1, 'continuous_value': 0.8}},
        })
        report = Dim8SummaryEngine().build_seven_dim_report(dr)
        s_sum = report['summary']
        assert s_sum['title'] == '状态总结'
        assert s_sum['text']  # 含状态条/共识率字样
        assert '共识' in s_sum['text']
        assert s_sum['judgment']['consensus_rate'] is not None


# ── T8: 幂等 + json 往返 emoji ────────────────────────────

class TestStability:

    def test_idempotent_and_json_roundtrip(self):
        dr = _mk_dim_results()
        eng = Dim8SummaryEngine()
        r1 = eng.build_seven_dim_report(dr)
        r2 = eng.build_seven_dim_report(dr)
        assert r1 == r2
        s = json.dumps(r1, ensure_ascii=False)
        rt = json.loads(s)
        assert rt['structure']['light'] == '🟢' or rt['structure']['light'] == '🟡'


# ── T9: 兼容包装不抛异常 ──────────────────────────────────

class TestCompatWrapper:

    def test_empty_signals_no_raise(self):
        # signals 恒空场景：兼容包装应返回可处理结果（本实现为空 dict，无 dim_results）
        result = generate_seven_dim_from_signals({'signals': {}})
        assert isinstance(result, dict)

    def test_compat_wrapper_with_dim_results_delegates(self):
        dr = _mk_dim_results()
        result = generate_seven_dim_from_signals({'dim_results': dr, 'tags': {}})
        assert set(result.keys()) == _EXPECTED_KEYS  # 委派 dim8 → 7 键


# ── T10: 死代码清除 ───────────────────────────────────────

class TestDeadCodeRemoval:

    def test_no_snapshot_row_in_status_engine(self):
        # 434 死代码块（return result 之后引用未定义 snapshot_row）已被清除
        with open(os.path.join(os.path.dirname(__file__), '..',
                               'app', 'opportunity_atlas', 'status_engine.py'),
                  encoding='utf-8') as f:
            src = f.read()
        # 允许出现在其他合法上下文（如 status_bar 相关）——此处只断言旧 _gen_summary 块特征消失
        assert "snapshot_row.get('dim_states')" not in src


# ── 辅助：_segment_from_dim 单维整形边界 ─────────────────

class TestSegmentHelper:

    def test_empty_or_missing_seg_returns_none(self):
        assert _segment_from_dim({}, 'structure', 'x') is None
        assert _segment_from_dim({'structure': None}, 'structure', 'x') is None
        assert _segment_from_dim({'structure': 'notdict'}, 'structure', 'x') is None

    def test_segment_flattens_nested_judgment(self):
        seg = _segment_from_dim(
            {'volume_price': {'judgment': {'vp_state': {'value': '强健康'}},
                              'status_description': {'plain': '量价健康'},
                              'audit': {}}},
            'volume_price', '量价健康度')
        assert seg is not None
        assert '强健康' in seg['text']
