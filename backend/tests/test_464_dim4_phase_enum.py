"""464号测试：dim4 主力阶段枚举统一（raising → lifting）

背景（464 §八-1）：生产链 PhaseDetectionEngine 唯一产出 lifting（PHASE_LIFTING="lifting"），
但 dim4 evaluate 的 light/overall_direction/audit/plain 与 _assess_phase 映射此前用 raising 判断
→ 拉升期被 dim4 判 yellow（应 green）、audit 主力阶段不满足、plain 缺"主力正在拉升"。
本测试锁定统一为 lifting 后的行为（生产库 pre_feat_cache 存量 raising=0 行，无别名兼容需求）。

覆盖：
  TestAssessPhase      —— ① _assess_phase 识别 lifting（tags 路径）
  TestEvaluateEngine   —— ② evaluate 引擎路径（PhaseDetectionEngine 产 lifting）：light/overall_direction/audit/plain
  TestPhaseMap         —— ③ PHASE_MAP 无 raising 冗余键
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest

from app.opportunity_atlas.dimensions import dim4_chip_fund_engine as dim4_mod
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    PHASE_MAP, Dim4ChipFundEngine, PhaseDetectionEngine, CrowdingFactor,
    _assess_phase, _assess_cost_structure,
)


def _mk_df(n: int = 60) -> pd.DataFrame:
    dates = pd.date_range('2026-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'trade_date': dates.strftime('%Y-%m-%d'),
        'open': 10.0, 'high': 11.0, 'low': 9.5, 'close': 10.5,
        'vol': 1_000_000, 'amount': 10_000_000,
    })


class TestAssessPhase:
    """_assess_phase（tags 路径）对 lifting 的识别"""

    def test_lifting_recognized(self):
        out = _assess_phase({'main_force_phase': 'lifting'}, {})
        assert out['phase'] == 'lifting'
        assert out['phase_cn'] == '拉升期'
        assert out['light'] == 'green'

    def test_other_phases_unchanged(self):
        assert _assess_phase({'main_force_phase': 'building'}, {})['light'] == 'green'
        assert _assess_phase({'main_force_phase': 'washing'}, {})['light'] == 'yellow'
        assert _assess_phase({'main_force_phase': 'distributing'}, {})['light'] == 'red'
        assert _assess_phase({'main_force_phase': 'support'}, {})['light'] == 'yellow'

    def test_unknown_fallback(self):
        out = _assess_phase({}, {})
        assert out['phase'] == 'unknown'
        assert out['phase_cn'] == '未知'


class TestEvaluateEngine:
    """evaluate 引擎路径：PhaseDetectionEngine 产 lifting 时的输出对齐"""

    def _run_evaluate(self, monkeypatch, main_phase='lifting'):
        df = _mk_df()

        class FakeDM:
            cache = None

        fake_dm = FakeDM()
        monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: fake_dm)
        # 固定 PhaseDetectionEngine.compute_tags（类方法，绕过真实阶段分析）
        monkeypatch.setattr(
            PhaseDetectionEngine, 'compute_tags',
            staticmethod(lambda *a, **k: {
                'main_force_phase': main_phase,
                'phase_confidence': 0.7,
                'fund_flow': 'inflow',
                'trend_alignment': 'up_aligned',
                'price_position': 'mid_zone',
            }))
        # 固定拥挤度（避免真实计算触碰数据源）
        monkeypatch.setattr(
            CrowdingFactor, 'evaluate',
            lambda self, *a, **k: {
                'crowding_level': 'MODERATE_CROWDING',
                'crowding_score': 0.5,
                'risk_advice': '拥挤度适中',
            })

        engine = Dim4ChipFundEngine()
        return engine.evaluate({}, {'ts_code': '000001.SZ'},
                               data_context={'daily_df': df})

    def test_lifting_light_green(self, monkeypatch):
        res = self._run_evaluate(monkeypatch, 'lifting')
        assert res['judgment']['phase'] == 'lifting'
        assert res['judgment']['light'] == 'green'
        assert res['judgment']['overall_light'] == 'green'
        assert res['judgment']['overall_direction'] == 1

    def test_lifting_audit_satisfied(self, monkeypatch):
        res = self._run_evaluate(monkeypatch, 'lifting')
        cond = next(c for c in res['audit']['conditions'] if c['name'] == '主力阶段')
        assert cond['satisfied'] is True
        assert cond['actual'] == '拉升期'

    def test_lifting_phase_field_has_lifting(self, monkeypatch):
        # plain 已删除（dim8 唯一叙事口径）：断言 phase 结构化字段
        res = self._run_evaluate(monkeypatch, 'lifting')
        assert '拉升期' in res['status_description']['phase']
        assert res['judgment']['phase'] == 'lifting'

    def test_distributing_still_red(self, monkeypatch):
        res = self._run_evaluate(monkeypatch, 'distributing')
        assert res['judgment']['light'] == 'red'
        assert res['judgment']['overall_direction'] == -1
        cond = next(c for c in res['audit']['conditions'] if c['name'] == '主力阶段')
        assert cond['satisfied'] is True


class TestPhaseMap:
    """PHASE_MAP 已统一枚举，无 raising 冗余键"""

    def test_no_raising_key(self):
        assert 'raising' not in PHASE_MAP
        assert 'lifting' in PHASE_MAP
        assert PHASE_MAP['lifting']['name'] == '拉升期'

    def test_phase_constants_aligned(self):
        assert dim4_mod.PHASE_LIFTING == 'lifting'


class TestAssessCostStructureAsrCyqkl:
    """464 §八-2 澄清锁定：ASR/CYQKL 非死路径（chip_fund_ext 组生产 → 扁平化 → _assess_cost_structure 输出）

    461-9 仅移除 chip 组白名单（ChipDistributionEstimator 从不产该组）；真正生产者在
    chip_fund_ext 组（ChipIndicators.calculate_all_indicators，443 R1 真实化）。
    本测试用扁平化后的 flat tags 实测，防止未来误判为死路径而删段。
    """

    def test_flat_tags_carry_asr_cyqkl(self):
        """扁平化 flat tags 含 asr/cyqkl（模拟 chip_fund_ext 组真实值）"""
        from app.opportunity_atlas.status_engine import StatusEngine
        pre_feat = {
            'chip': {'chip_position': 'in_peak', 'chip_concentration': 'concentrating'},
            'chip_fund_ext': {'ssrp': 11.32, 'asr': 54.66, 'concentration': 0.0,
                              'profit_ratio': 0.778, 'cyqkl': 7.41, 'rsi': 49.72},
        }
        flat = StatusEngine._flatten_pre_feat(pre_feat)
        assert flat['asr'] == 54.66
        assert flat['cyqkl'] == 7.41

    def test_cost_structure_outputs_asr_cyqkl(self):
        """_assess_cost_structure 从 flat tags 正常产出 ASR/CYQKL 文案与 quality"""
        flat = {'chip_concentration': 'concentrating', 'asr': 54.66, 'cyqkl': 7.41, 'profit_ratio': 0.778}
        out = _assess_cost_structure(flat)
        assert 'ASR=55' in out['detail']
        assert 'CYQKL=7.4' in out['detail']
        assert '获利盘78%' in out['detail']
        assert out['concentration'] == 'concentrating'

    def test_quality_tiers_from_asr(self):
        """quality 分档真实触发：ASR>80 活跃 / ASR<30 沉寂 / 中间中性"""
        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import _assess_cost_structure as _acs
        assert _acs({'asr': 95.0})['quality'] == '活跃'
        assert _acs({'asr': 18.0})['quality'] == '沉寂'
        assert _acs({'asr': 55.0})['quality'] == '中性'


class TestCrowdingTurnoverWiring:
    """464 §八-3 处置锁定：dim4 evaluate 传 turnover_data 后换手分项真实判定

    此前 market_context 仅含 margin_df，calc_turnover_crowding 读 daily_df 无 turnover 列
    → 换手分项恒 NORMAL_TURNOVER，拥挤度仅融资+波动两维。464-3 从 data_context.daily_basic_df
    的 turnover_rate 列提取序列传 turnover_data，使换手分项真实参与 2/3 判定。
    """

    def test_turnover_high_detected(self):
        """换手率当前值 > 20日均值 1.5 倍 → HIGH_TURNOVER（拥挤信号）"""
        cf = CrowdingFactor()
        turnover = pd.Series([2.0] * 20 + [4.0])  # 当前 4.0 vs 均值 ~2.1 → ratio>1.5
        df = _mk_df(60)
        assert cf.calc_turnover_crowding(df, turnover_data=turnover) == 'HIGH_TURNOVER'

    def test_turnover_low_detected(self):
        """换手率当前值 < 20日均值 0.5 倍 → LOW_TURNOVER（分散信号）"""
        cf = CrowdingFactor()
        turnover = pd.Series([4.0] * 20 + [1.0])  # 当前 1.0 vs 均值 ~3.86 → ratio<0.5
        df = _mk_df(60)
        assert cf.calc_turnover_crowding(df, turnover_data=turnover) == 'LOW_TURNOVER'

    def test_turnover_normal_without_data(self):
        """无 turnover_data 且 daily_df 无换手列 → NORMAL_TURNOVER（原恒 NORMAL 行为兜底）"""
        cf = CrowdingFactor()
        assert cf.calc_turnover_crowding(_mk_df(60), turnover_data=None) == 'NORMAL_TURNOVER'

    def test_evaluate_passes_turnover_data(self, monkeypatch):
        """evaluate 从 data_context.daily_basic_df 提取 turnover_rate 传入 market_context.turnover_data"""
        df = _mk_df(60)
        basic_df = pd.DataFrame({
            'trade_date': pd.date_range('2026-01-01', periods=30, freq='B').strftime('%Y-%m-%d'),
            'turnover_rate': [2.0] * 29 + [6.0],  # 当前 6.0 vs 均值 ~2.14 → HIGH
        })

        captured = {}

        class FakeDM:
            cache = None

        monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: FakeDM())
        monkeypatch.setattr(
            PhaseDetectionEngine, 'compute_tags',
            staticmethod(lambda *a, **k: {
                'main_force_phase': 'lifting', 'phase_confidence': 0.7,
                'fund_flow': 'inflow', 'trend_alignment': 'up_aligned',
                'price_position': 'mid_zone',
            }))

        def _fake_crowding_eval(self, ts_code, df, market_context=None):
            captured['mc'] = market_context or {}
            return {'crowding_level': 'MODERATE_CROWDING', 'crowding_score': 0.5,
                    'risk_advice': 'x'}

        monkeypatch.setattr(CrowdingFactor, 'evaluate', _fake_crowding_eval)

        engine = Dim4ChipFundEngine()
        engine.evaluate({}, {'ts_code': '000001.SZ'},
                        data_context={'daily_df': df, 'daily_basic_df': basic_df})

        td = captured['mc'].get('turnover_data')
        assert td is not None, '应传入 turnover_data'
        assert float(td.iloc[-1]) == 6.0
        # 换手分项真实判定为高换手
        cf = CrowdingFactor()
        assert cf.calc_turnover_crowding(df, turnover_data=td) == 'HIGH_TURNOVER'


class TestDim7FinaHealthAuditText:
    """464 §八-4 处置锁定：dim7 audit「财务健康」threshold 文案与实际三维判定一致

    原文案 'ROE>6%近3年平均' 过简（仅 ROE 一维）；实际 `_fina_health`（SSOT=ve.compute_tags，
    461-2）判定为三维 fail_count：ROE 近3年均值>6% + 负债率<70%（金融除外） + 经营现金流/净利>0.8
    连续3年；≥2 fail / ≥1 suspicious / 0 pass。ROCE>15% 是独立 rokce_pass（另有「ROCE达标」条件）。
    """

    def test_fina_health_threshold_aligned(self, monkeypatch):
        from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine

        _val = {
            'valuation_level': 'fair', 'valuation_deviation': 0.0,
            'pe_percentile_5y': 50.0, 'pb_percentile_5y': 50.0, 'ps_percentile_5y': 50.0,
            'fcf_yield': 3.0, 'dividend_yield': 1.0, 'revenue_growth': 5.0,
            'fina_health': 'pass', 'roce_pass': True, 'value_trap': False, 'growth_trap': False,
            'composite_rating': 0.0,
        }

        class FakeDM:
            cache = None

        monkeypatch.setattr(Dim7ValuationEngine, '_get_dm', lambda self: FakeDM())
        monkeypatch.setattr(
            Dim7ValuationEngine, '_compute_valuation',
            lambda self, *a, **k: dict(_val))
        monkeypatch.setattr(
            Dim7ValuationEngine, '_compute_potential',
            lambda self, *a, **k: {'signal_strength': 60, 'potential_breakdown': '{}'})

        engine = Dim7ValuationEngine()
        res = engine.evaluate({}, {'ts_code': '000001.SZ'})
        cond = next(c for c in res['audit']['conditions'] if c['name'] == '财务健康')
        assert cond['satisfied'] is True
        assert 'ROE' in cond['threshold'] and '负债率' in cond['threshold'] and '现金流' in cond['threshold']
        # 三维判定文案对齐，不再只提 ROE
        assert '近3年平均' not in cond['threshold']
