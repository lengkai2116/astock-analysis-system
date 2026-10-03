"""507号批次8：Q1/Q2/Q4 处置验证（+ 登记-11 已关闭确认）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §七。

覆盖：
  Q1 删 dim4 ASR 信号死分支 + _asr_to_phase 死方法（result['signal'] 无消费者；
      0~1 比例 vs 0~100 阈值死代码随删，生产零影响）
  Q2 potential_engine dev>30 惩罚注释订正（正=低估口径：composite 大=低估、
      deviation=composite*20 → dev>30=深度低估=价值陷阱防御；行为不变）
  Q4 light_derive._risk_source_is_high dict 分支补 'risk_level' 回退
  登记-11 dim5 '严重背离' 分支可达性（447号 T4a 已让 dim3 产 judgment.state）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

_ATLAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'opportunity_atlas')


# ── Q1 dim4 ASR 死分支 / 死方法删除 ─────────────────────────

def test_q1_asr_to_phase_dead_method_removed():
    """dim4 已无 _asr_to_phase 死方法"""
    import importlib
    m = importlib.import_module('app.opportunity_atlas.dimensions.dim4_chip_fund_engine')
    assert not hasattr(m, '_asr_to_phase'), '_asr_to_phase 死方法应已删'
    assert not hasattr(m.PhaseDetectionEngine, '_asr_to_phase')


def test_q1_chip_distribution_analysis_no_signal_branch():
    """_chip_distribution_analysis 不再产 signal（0~1 vs 0~100 阈值死分支已删）"""
    import inspect
    from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine

    src = inspect.getsource(PhaseDetectionEngine._chip_distribution_analysis)
    assert 'result["signal"]' not in src, 'signal 死分支应已删'
    assert 'PHASE_DISTRIBUTING' not in src, 'asr 信号分支应已删'
    # 保留被消费键
    assert 'result["asr"]' in src
    assert 'result["peak_position"]' in src


# ── Q2 potential_engine 注释订正（正=低估→价值陷阱防御） ────

def test_q2_dev30_comment_value_trap_and_condition_kept():
    """dev>30 惩罚注释订正为价值陷阱防御；惩罚条件保留（零行为）"""
    src = open(os.path.join(_ATLAS, 'potential_engine.py'), encoding='utf-8').read()
    assert '价值陷阱防御' in src, '注释应订正为价值陷阱防御'
    assert '# 风险否决：极端泡沫（正偏离过大）' not in src, '旧矛盾注释行应移除'
    assert 'dev_f > 30' in src and 'score *= 0.3' in src, '惩罚条件应保留'
    assert '正=低估' in src, '符号口径应写明确'


def test_q2_deviation_sign_positive_means_undervalued():
    """valuation_deviation 正=低估口径（composite 大=低估，deviation=composite*20）"""
    import inspect
    from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine

    src = inspect.getsource(Dim7ValuationEngine._compute_valuation)
    assert 'deviation = round(composite * 20.0, 1)' in src
    assert "c > 1.0" in src and "'extreme_low'" in src  # composite 大 → extreme_low（低估）


# ── Q4 light_derive dict 分支 risk_level 回退 ───────────────

@pytest.mark.parametrize('item,expected', [
    ({'level': '高'}, True),
    ({'risk_level': '高'}, True),          # 新增回退键
    ({'level': '低'}, False),
    ({'risk_level': '低'}, False),
    ('风险：高', True),                     # 字符串形态不变
    ('流动性：正常', False),
])
def test_q4_risk_source_is_high_dict_fallback(item, expected):
    from app.opportunity_atlas.light_derive import _risk_source_is_high

    assert _risk_source_is_high(item) is expected


# ── 登记-11 dim5 严重背离分支可达性（447号 T4a 后） ─────────

def test_reg11_dim5_severe_divergence_branch_reachable():
    """dim5 严重背离分支经 _vp_state（dim3 judgment.state）可达——447号 T4a 已接通"""
    import inspect
    from app.opportunity_atlas.dimensions import dim5_emotion_engine as d5

    src = inspect.getsource(d5._assess_stock_emotion)
    # 447号 T4a：_vp_state 读 dims['vp'].judgment.state（dim3 可产 '严重背离'）
    assert "_vp_state = (dims.get('vp') or {}).get('judgment', {}).get('state')" in src
    assert "_vp_state == '严重背离' or vp == '严重背离'" in src
    assert '极度消极' in src
