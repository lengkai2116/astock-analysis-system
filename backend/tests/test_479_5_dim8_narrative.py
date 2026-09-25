"""479号-5 dim8「实例→话术」改造单测（B1，话术叙事收官）

覆盖（479-5，dim2-dim7 定稿后话术因果链）：
  - N1 段级 text 升级「所以→因为→验证」因果链：所以=字段话术、因为=audit satisfied 条件名、
      验证=条件稽核 N/M 动态读
  - N2 因来自 audit satisfied 项（satisfied=False 的 name 不出现）
  - N3 无满足条件 → 因为节省略（防空"因"占位）
  - N4 audit 无 total → 验证节省略
  - N5 向后兼容：不传 au 的 _compose_dim_text 保持纯字段话术（summary 平铺 / strategy_analyze 不回归）
  - N6 六段（structure/volume_price/fund_chip/emotion/risk）真实装配后均含因果链
  - N7 评分键不产句（479-1 清理后，因果链句内无评分）——回归保护
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine,
    _compose_dim_text,
    _narrative_so_so_yz,
)


def _mk_dim(src_key, sd=None, au=None):
    """构造带 audit 的单维 dim_results（含 satisfied 条件）"""
    return {
        src_key: {
            'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                         'continuous_value': 0.5},
            'status_description': sd or {},
            'audit': au or {'conditions': [], 'satisfied_count': 0, 'total_count': 0,
                            'confidence': 1.0},
        }
    }


def _mk_audit(satisfied_names, total=None, got=None):
    """构造 audit：satisfied_names 全部 satisfied=True，其余条件 False"""
    conds = [{'name': n, 'satisfied': True, 'actual': 'a', 'threshold': 't'}
             for n in satisfied_names]
    conds += [{'name': f'未达成-{i}', 'satisfied': False, 'actual': 'a', 'threshold': 't'}
              for i in range(2)]
    return {
        'conditions': conds,
        'satisfied_count': got if got is not None else len(satisfied_names),
        'total_count': total if total is not None else (len(satisfied_names) + 2),
        'confidence': 0.8,
    }


# ── N1/N5: 因果链与向后兼容 ────────────────────────────────

class TestNarrativeChain:

    def test_chain_so_so_yz_zhong_yu_zheng(self):
        """段级 text 含「所以/因为/验证」三节，因为=audit satisfied 条件名、验证=条件稽核 N/M"""
        sd = {'vp_state': '强健康', 'volume_energy': '量比6.7，连续3日放量'}
        au = _mk_audit(['量价关系', '健康度'], total=6, got=4)
        text = _compose_dim_text('volume_price', {}, sd, au)
        assert '所以：量价状态：强健康' in text
        assert '；因为：量价关系、健康度' in text
        assert '；验证：条件稽核 4/6' in text

    def test_chain_reason_from_satisfied_only(self):
        """因为只列 satisfied=True 条件名；satisfied=False 的 name 不出现"""
        sd = {'risk_level': '高'}
        au = _mk_audit(['流动性', '防守位'], total=5, got=2)
        text = _compose_dim_text('risk', {}, sd, au)
        assert '因为：流动性、防守位' in text
        assert '未达成' not in text

    def test_no_satisfied_yin_clause_skipped(self):
        """无满足条件 → 因为节省略（防空'因'占位）"""
        sd = {'risk_level': '高'}
        au = {'conditions': [{'name': '风险等级', 'satisfied': False, 'actual': '高',
                              'threshold': '低或中'}],
              'satisfied_count': 0, 'total_count': 1, 'confidence': 0.5}
        text = _compose_dim_text('risk', {}, sd, au)
        assert '所以：风险等级：高' in text
        assert '因为' not in text

    def test_no_total_yz_clause_skipped(self):
        """audit 无 total → 验证节省略"""
        sd = {'vp_state': '中性'}
        au = {'conditions': [{'name': '量价关系', 'satisfied': True}],
              'satisfied_count': 1, 'total_count': 0, 'confidence': 1.0}
        text = _compose_dim_text('volume_price', {}, sd, au)
        assert '所以：量价状态：中性' in text
        assert '因为：量价关系' in text
        assert '条件稽核' not in text

    def test_compat_no_au_keeps_pure_fields(self):
        """不传 au → 保持纯字段话术（summary 平铺 _generate_text / strategy_analyze 不回归）"""
        sd = {'vp_state': '强健康', 'volume_energy': '量比6.7'}
        text = _compose_dim_text('volume_price', {}, sd)
        assert text == '量价状态：强健康；量能：量比6.7'
        assert '所以' not in text and '因为' not in text and '验证' not in text

    def test_chain_direct_function(self):
        """_narrative_so_so_yz 可直接构造（段外可复用）"""
        au = _mk_audit(['趋势方向'], total=5, got=3)
        s = _narrative_so_so_yz('缠论方向:下降', 'structure', {}, {}, au)
        assert '所以：缠论方向:下降' in s
        assert '；因为：趋势方向' in s
        assert '；验证：条件稽核 3/5' in s


# ── N6: 六段真实装配因果链 ────────────────────────────────

class TestSixDimsAssembled:

    def test_five_public_dims_chain(self):
        """五公开段（structure/volume_price/fund_chip/emotion/risk）装配后均含因果链"""
        dr = {}
        dr.update(_mk_dim('structure', sd={'stage_name': '走势结构下降',
                                           'chanlun_direction': '下降'},
                          au=_mk_audit(['趋势方向'], total=5, got=1)))
        dr.update(_mk_dim('volume_price', sd={'vp_state': '强健康'},
                          au=_mk_audit(['健康度'], total=6, got=2)))
        dr.update(_mk_dim('chip_fund', sd={'phase': '拉升期'},
                          au=_mk_audit(['主力阶段'], total=5, got=1)))
        dr.update(_mk_dim('emotion', sd={'market': '市场处于发酵'},
                          au=_mk_audit(['市场情绪'], total=5, got=2)))
        dr.update(_mk_dim('risk', sd={'risk_level': '中'},
                          au=_mk_audit(['流动性'], total=5, got=3)))
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags={}, ts_code=None)
        assert report is not None
        for key in ('structure', 'volume_price', 'fund_chip', 'emotion', 'risk'):
            seg = report.get(key)
            assert seg is not None, f'缺段 {key}'
            t = seg['text']
            assert '所以：' in t, f'{key} 无所以'
            assert '；验证：条件稽核' in t, f'{key} 无验证'
            assert '；因为：' in t, f'{key} 无因为'


# ── N7: 评分键不产句 ──────────────────────────────────────

class TestNoScoreKeysInChain:

    def test_structure_no_score(self):
        """structure 因果链句内不含评分键（structure_health_score 归 JUD，479-1 清理后回归保护）"""
        sd = {'stage_name': '走势结构下降', 'chanlun_direction': '下降',
              'structure_health_score': '38/100（不足）'}
        au = _mk_audit(['趋势方向'], total=5, got=1)
        text = _compose_dim_text('structure', {}, sd, au)
        assert '所以：缠论方向：下降；阶段：走势结构下降' in text
        assert '结构健康' not in text
        assert '38/100' not in text

    def test_volume_price_no_score(self):
        """dim3 因果链句内不含健康度/形态评分（health_score/pattern_score 归 JUD）"""
        sd = {'vp_state': '强健康', 'health_score': '9/10', 'pattern_score': '10/10'}
        au = _mk_audit(['量价关系'], total=6, got=2)
        text = _compose_dim_text('volume_price', {}, sd, au)
        assert '所以：量价状态：强健康' in text
        assert '健康度' not in text and '形态评分' not in text


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q']))
