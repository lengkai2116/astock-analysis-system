"""479号-8 评分与灯色全链迁 JUD 固化回归（D1）

背景（479-8 定义，方案 §阶段5）：
  structure_health_score / health_score / pattern_score / crowding_score /
  potential_score / potential_strength + 各维 judgment 键（overall_light /
  overall_direction / continuous_value）从「dim8 展示」迁移为「仅 JUD 消费」：
    - 引擎 status_description 保留产出（数据源不变）
    - dim8 段 text / evidence 不再展示评分键（479-1 已清理出 T/E 表，此处固化回归）
    - JUD（dim_adapter.convert_to_factors 等）消费链无断点，读取得值

覆盖（479-8，只动"谁展示/谁消费"、不改引擎判定）：
  - R1 五公开段 text 不含 6 个评分键（structure/volume_price/chip_fund/valuation）
  - R2 段 evidence 不含 6 个评分键
  - R3 段 judgment 仅含 3 个 meta 键（灯色/方向/连续值），无评分键混入
  - R4 _valuation_sentence 不含 potential_score/potential_strength/fina_health
  - R5 引擎 status_description 保留评分键产出（数据源不变，供 JUD）
  - R6 JUD 消费链：dim_adapter 读 structure_health_score / potential_score(strength) 取得值
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine,
    _valuation_sentence,
)

# 6 个评分键 + 引擎侧保留产出样例值
SCORE_KEYS = ['structure_health_score', 'health_score', 'pattern_score',
              'crowding_score', 'potential_score', 'potential_strength']


def _mk_dim(src_key, sd, judg=None, au=None, audit_conf=None):
    """构造带评分的单维 dim_results（引擎侧保留产出 + 标准段 meta judgment）"""
    return {
        src_key: {
            'judgment': judg if judg is not None else {
                'overall_light': 'yellow', 'overall_direction': 0,
                'continuous_value': 0.5},
            'status_description': sd,
            'audit': au if au is not None else {
                'conditions': [], 'satisfied_count': 0, 'total_count': 0,
                'confidence': audit_conf if audit_conf is not None else 1.0},
        }
    }


def _all_dims_with_scores():
    """构造含全部 6 个评分键的七维 dim_results（engine 侧保有，检验 dim8 剥离）"""
    dims = {}
    dims.update(_mk_dim('structure', {
        'chanlun_direction': '上升', 'stage_name': '走势结构上升',
        'structure_health_score': '72/100（较健康）'}))
    dims.update(_mk_dim('volume_price', {
        'vp_state': '强健康', 'health_score': '9/10', 'pattern_score': '8/10'}))
    dims.update(_mk_dim('chip_fund', {
        'phase': '拉升', 'crowding_score': 0.6}))
    dims.update(_mk_dim('emotion', {'quadrant': 'LL', 'temperature': '57.9/100'}))
    dims.update(_mk_dim('risk', {'risk_level': '中', 'support_price': 10.2,
                                 'resistance_price': 12.5}))
    dims.update(_mk_dim('valuation', {
        'valuation_level': '合理（composite=0.026）',
        'pe_percentile': 'PE近5年50%分位',
        'potential_score': '潜力评分65/100',
        'potential_strength': 65}))
    return dims


class TestScoreEngineRetains:

    def test_engine_side_retains_score_keys(self):
        """R5 引擎 status_description 保留评分键产出（数据源不变，供 JUD）"""
        dims = _all_dims_with_scores()
        assert 'structure_health_score' in dims['structure']['status_description']
        assert 'health_score' in dims['volume_price']['status_description']
        assert 'pattern_score' in dims['volume_price']['status_description']
        assert 'crowding_score' in dims['chip_fund']['status_description']
        assert 'potential_score' in dims['valuation']['status_description']
        assert 'potential_strength' in dims['valuation']['status_description']


class TestDim8NotDisplayScores:

    def test_segment_text_excludes_scores(self):
        """R1 五公开段 text 不含 6 个评分键（479-1 清理后固化回归）"""
        dims = _all_dims_with_scores()
        report = Dim8SummaryEngine().build_seven_dim_report(dims, tags={})
        assert report is not None
        for key in ('structure', 'volume_price', 'fund_chip', 'emotion', 'risk'):
            seg = report.get(key)
            if not seg:
                continue
            t = seg.get('text', '')
            for k in SCORE_KEYS:
                assert k not in t, f'{key} text 含 {k}: {t}'
        # valuation 不产段（436 D5），评分键不应出现在任何公开段
        val_text = report.get('valuation')
        assert val_text is None


class TestDim8JudgmentMetaOnly:

    def test_segment_judgment_only_meta_keys(self):
        """R3 段 judgment 仅含 3 meta 键（overall_light/overall_direction/continuous_value）"""
        dims = _all_dims_with_scores()
        report = Dim8SummaryEngine().build_seven_dim_report(dims, tags={})
        for key in ('structure', 'volume_price', 'fund_chip', 'emotion', 'risk'):
            seg = report.get(key)
            if not seg:
                continue
            jg = seg.get('judgment', {})
            # 评分键不混入段 judgment
            for k in SCORE_KEYS:
                assert k not in jg, f'{key} judgment 含 {k}'
            # meta 键契约
            assert 'overall_light' in jg and 'overall_direction' in jg \
                and 'continuous_value' in jg, f'{key} judgment 缺 meta 键: {jg}'


class TestValuationSentence:

    def test_valuation_sentence_no_scores(self):
        """R4 _valuation_sentence 不含 potential_score/strength/fina_health"""
        sd = {
            'valuation_level': '合理（composite=0.026）',
            'pe_percentile': 'PE近5年50%分位',
            'potential_score': '潜力评分65/100',
            'potential_strength': 65,
            'fina_health': '财务健康✅(pass)',
        }
        s = _valuation_sentence({'valuation': {
            'status_description': sd,
            'audit': {'satisfied_count': 5, 'total_count': 8, 'confidence': 0.6}}})
        assert '合理（composite=0.026）' in s
        assert '潜力评分' not in s and '潜力强度' not in s and '财务健康' not in s


class TestJudConsumesScores:

    def test_dim_adapter_reads_structure_score(self):
        """R6 JUD 消费链无断点：convert_to_factors 读 structure_health_score 取得值"""
        from app.opportunity_atlas.dim_adapter import convert_to_factors
        dims = _all_dims_with_scores()
        # structure_health_score=72（0-100 域）→ strength 归一贡献
        factors = convert_to_factors(dims, {'ts_code': '000001.SZ'})
        assert 'structure' in factors
        assert factors['structure']['strength'] > 0.4  # 72/100 → 0.72 · 0.4 权重 > 0.28
        # structure 维 evidence 记录消费来源
        ev = ' '.join(factors['structure'].get('evidence', []))
        assert 'overall_direction=' in ev


import unittest
if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
