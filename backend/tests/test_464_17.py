"""464-17 主力识别核查测试（三方向锁定）

覆盖：
  TestCapitalNatureNoEvidence —— ① 方向一 capital_nature 无 LHB 证据→unknown（framework + dim4 双份），
                                   有真机构买入→institutional、假机构嫌疑→hot_money
  TestMainForcePresenceShard  —— ② 方向二 _compute_main_force_presence 分库错查修复：
                                   LHB 近30日→strong / 融资30日暴增→risk / 股东户数环比≥5%→moderate /
                                   筹码集中度≥60%→moderate / 全空→none
  TestConsensusPresenceSoft   —— ③ 方向三 _consensus 主力在场软修正（双份）：
                                   strong/moderate→置信+0.05、none→×0.8

背景实证（2026-09-21）：
  方向一：_score_lhb 无 LHB 数据返回 0.0，原 get_tags 判定 0.0>-0.5 → 96% 全标 hot_money。
  方向二：_compute_main_force_presence 用 ecm.conn（总库 stock_cache.db）直查 lhb_cache/
          stk_holder_cache/margin_cache——三表全在分库（system/history/market_cache.db），
          总库无表 → 查询全静默抛异常 → 恒 none；且融资窗口取历史最早（与注释 30 日不符）。
  方向三：PhaseDetectionEngine 8 维共识无主力在场维度，阶段对无主力股票也硬给结论。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest
from app.engine.framework.chip_strategy import MainForceScorer as FrameworkScorer
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    CrowdingFactor,
    Dim4ChipFundEngine,
)
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    MainForceScorer as D4Scorer,
)
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    PhaseDetectionEngine as D4PhaseEngine,
)
from app.opportunity_atlas.phase_detector import PhaseDetectionEngine


def _mk_kline(n: int = 80, last_close: float = 15.0, lo: float = 10.0, hi: float = 20.0) -> pd.DataFrame:
    """构造 K 线：先线性涨到 hi 再线性跌到 last_close

    p_high=hi / p_low=lo / 最后收盘=last_close →
      last_close=15 → price_pos≈0.5（中性，不触发假机构高位约束）
      last_close=19 → price_pos≈0.9（高位，触发假机构）
    """
    half = n // 2
    up = np.linspace(lo, hi, half)
    down = np.linspace(hi, last_close, n - half)
    prices = np.concatenate([up, down])
    return pd.DataFrame({
        'trade_date': pd.date_range('2026-05-01', periods=n, freq='B').strftime('%Y-%m-%d'),
        'open': prices,
        'high': prices * 1.01,
        'low': prices * 0.99,
        'close': prices,
        'vol': 1_000_000,
        'amount': 10_000_000,
    })


class _FakeDM:
    """framework MainForceScorer 的最小 fake dm（get_tags 路径）"""

    def __init__(self, lhb=None, daily=None, moneyflow=None):
        self._lhb = lhb
        self._daily = daily
        self._moneyflow = moneyflow

    def get_cached_moneyflow(self, *a, **k):
        return self._moneyflow

    def get_cached_lhb(self, *a, **k):
        return self._lhb

    def get_lhb_detail(self, *a, **k):
        return None

    def get_cached_daily_data(self, *a, **k):
        return self._daily


def _mk_lhb(buy_amount: float, sell_amount: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame({
        'trade_date': ['2026-09-18'],
        'buy_amount': [buy_amount],
        'sell_amount': [sell_amount],
    })


class TestCapitalNatureNoEvidence:
    """① 方向一：capital_nature 判定（无证据→unknown）"""

    def test_framework_no_lhb_unknown(self):
        """无 LHB 证据（lhb 空）→ lhb_score==0 → unknown（原实现误标 hot_money）"""
        scorer = FrameworkScorer()
        scorer._dm = _FakeDM(lhb=pd.DataFrame(), daily=_mk_kline())
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('capital_nature') == 'unknown'

    def test_framework_institutional(self):
        """真机构大额买入（5亿级）→ lhb_score≥0.5 → institutional"""
        scorer = FrameworkScorer()
        scorer._dm = _FakeDM(lhb=_mk_lhb(buy_amount=3e8), daily=_mk_kline())
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('capital_nature') == 'institutional'

    def test_framework_small_buy_hot_money(self):
        """小额真买入（未达机构门槛，>0 分）→ hot_money（有证据保留区分度）"""
        scorer = FrameworkScorer()
        # 2千万买入 → 2e7/5e8 = 0.04 分（>0 且 <0.5）→ hot_money
        scorer._dm = _FakeDM(lhb=_mk_lhb(buy_amount=2e7), daily=_mk_kline())
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('capital_nature') == 'hot_money'

    def test_framework_fake_inst_hot_money(self):
        """假机构嫌疑（高位+买入占比高→负分）→ hot_money（保留 2026-08-10 区分度）"""
        scorer = FrameworkScorer()
        # 高位 K 线（last_close=19 → price_pos≈0.9）；买入占比 8e7/(8e7+2e7)=0.8>0.4 → suspected
        scorer._dm = _FakeDM(
            lhb=_mk_lhb(buy_amount=8e7, sell_amount=2e7),
            daily=_mk_kline(last_close=19.0),
        )
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('capital_nature') == 'hot_money'

    def test_d4_no_lhb_unknown(self):
        """dim4 副本与 framework 同步：无证据→unknown"""
        scorer = D4Scorer()
        scorer._dm = _FakeDM(lhb=pd.DataFrame(), daily=_mk_kline())
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('capital_nature') == 'unknown'

    def test_d4_institutional(self):
        """dim4 副本：真机构大额买入→institutional"""
        scorer = D4Scorer()
        scorer._dm = _FakeDM(lhb=_mk_lhb(buy_amount=3e8), daily=_mk_kline())
        tags = scorer.get_tags('000001.SZ')
        assert tags.get('capital_nature') == 'institutional'


class _FakeECM:
    """_compute_main_force_presence 的最小 fake ECM（分库读方法）"""

    def __init__(self, lhb=None, margin=None, stk_holder=None, top10=None):
        self._lhb = lhb
        self._margin = margin
        self._stk_holder = stk_holder
        self._top10 = top10

    def get_cached_lhb(self, *a, **k):
        return self._lhb

    def get_cached_margin(self, *a, **k):
        return self._margin

    def get_cached_stk_holder(self, *a, **k):
        return self._stk_holder

    def get_cached_top10_holders(self, *a, **k):
        return self._top10


class TestMainForcePresenceShard:
    """② 方向二：_compute_main_force_presence 分库读修复 + 证据触发"""

    def _run(self, ecm):
        import data_daemon
        return data_daemon._compute_main_force_presence('000001.SZ', ecm)

    def test_lhb_strong(self):
        """LHB 近 30 日有席位 → strong"""
        ecm = _FakeECM(lhb=pd.DataFrame({
            'trade_date': ['2026-09-18'], 'buy_amount': [1e8], 'sell_amount': [1e7],
        }))
        r = self._run(ecm)
        assert r['main_force_presence'] == 'strong'
        assert '龙虎榜' in r['presence_evidence']

    def test_margin_risk_30d_window(self):
        """融资 30 日窗口内增幅>50% → risk（窗口对齐注释：30 日内最早记录）"""
        ecm = _FakeECM(margin=pd.DataFrame({
            'trade_date': ['2026-08-25', '2026-09-18'],
            'rzye': [100.0, 200.0],
        }))
        r = self._run(ecm)
        assert r['main_force_presence'] == 'risk'
        assert '融资余额暴增' in r['presence_evidence']

    def test_margin_oldest_outside_window_no_risk(self):
        """融资最早记录在 30 日窗口外 → 不以历史最低点计算（窗口语义）→ 不触发"""
        ecm = _FakeECM(margin=pd.DataFrame({
            # 历史最早（4 个月前）100 → 最新 200（窗口内仅 9 月数据 200）
            'trade_date': ['2026-05-20', '2026-09-18'],
            'rzye': [100.0, 200.0],
        }))
        r = self._run(ecm)
        assert r['main_force_presence'] == 'none'

    def test_stk_holder_moderate(self):
        """股东户数环比减少≥5% → moderate"""
        ecm = _FakeECM(stk_holder=pd.DataFrame({
            'end_date': ['2026-09-16', '2026-06-30'],
            'holder_number': [90000.0, 100000.0],
        }))
        r = self._run(ecm)
        assert r['main_force_presence'] == 'moderate'
        assert '股东户数减少' in r['presence_evidence']

    def test_concentration_moderate(self):
        """筹码集中度温和档：前十大股东流通占比合计≥60% → moderate"""
        ecm = _FakeECM(top10=pd.DataFrame({
            'end_date': ['2026-06-30', '2026-06-30', '2026-06-30'],
            'hold_float_ratio': [20.0, 20.0, 25.0],   # 合计 65%
        }))
        r = self._run(ecm)
        assert r['main_force_presence'] == 'moderate'
        assert '筹码集中' in r['presence_evidence']

    def test_concentration_below_threshold_none(self):
        """筹码集中度未达 60% → 不触发"""
        ecm = _FakeECM(top10=pd.DataFrame({
            'end_date': ['2026-06-30', '2026-06-30'],
            'hold_float_ratio': [20.0, 20.0],         # 合计 40%
        }))
        r = self._run(ecm)
        assert r['main_force_presence'] == 'none'

    def test_all_empty_none(self):
        """全证据空 → none"""
        r = self._run(_FakeECM())
        assert r['main_force_presence'] == 'none'
        assert r['presence_evidence'] == '[]'


def _mk_dims() -> dict:
    """构造 building 3 维确认的 dims（无冲突、无 capital_nature 干扰）"""
    return {
        'chip': {'building': 0.6},
        'fund': {'building': 0.6},
        'stage': {'building': 0.5},
    }


class TestConsensusPresenceSoft:
    """③ 方向三：_consensus 主力在场软修正（双份）"""

    def test_phase_detector_none_confidence_dampened(self):
        pde = PhaseDetectionEngine()
        _, c_base, _, _ = pde._consensus(_mk_dims(), {})
        _, c_none, _, _ = pde._consensus(_mk_dims(), {'main_force_presence': 'none'})
        assert c_none == pytest.approx(c_base * 0.8)

    def test_phase_detector_strong_confidence_boosted(self):
        pde = PhaseDetectionEngine()
        _, c_base, _, _ = pde._consensus(_mk_dims(), {})
        _, c_strong, _, _ = pde._consensus(_mk_dims(), {'main_force_presence': 'strong'})
        assert c_strong == pytest.approx(min(1.0, c_base + 0.05))

    def test_phase_detector_moderate_boosted(self):
        pde = PhaseDetectionEngine()
        _, c_base, _, _ = pde._consensus(_mk_dims(), {})
        _, c_mod, _, _ = pde._consensus(_mk_dims(), {'main_force_presence': 'moderate'})
        assert c_mod == pytest.approx(min(1.0, c_base + 0.05))

    def test_d4_engine_none_confidence_dampened(self):
        pde = D4PhaseEngine()
        _, c_base, _, _ = pde._consensus(_mk_dims(), {})
        _, c_none, _, _ = pde._consensus(_mk_dims(), {'main_force_presence': 'none'})
        assert c_none == pytest.approx(c_base * 0.8)

    def test_d4_engine_strong_confidence_boosted(self):
        pde = D4PhaseEngine()
        _, c_base, _, _ = pde._consensus(_mk_dims(), {})
        _, c_strong, _, _ = pde._consensus(_mk_dims(), {'main_force_presence': 'strong'})
        assert c_strong == pytest.approx(min(1.0, c_base + 0.05))

    def test_absent_presence_no_change(self):
        """presence 缺失（旧数据/未接线）→ 不修正（向后兼容）"""
        pde = PhaseDetectionEngine()
        _, c_base, _, _ = pde._consensus(_mk_dims(), {})
        _, c_absent, _, _ = pde._consensus(_mk_dims(), {'capital_nature': 'hot_money'})
        # 只有 capital_nature 时 presence 修正不参与
        assert c_absent == pytest.approx(c_base * 0.8)  # hot_money ×0.8（既有行为）


class TestAuditPhaseConfidenceGate:
    """④ 464-13：audit「主力阶段」置信门槛 ≥0.3（随 464-17 结论拍板）

    重估依据（2026-09-18 旧 pre_feat + 修复后逻辑模拟）：
      修复后 phase_confidence 均值 0.444→0.525；<0.3 拦截从 30%→16%；
      presence 有证据组均值 0.587 vs none 组 0.439（置信可区分主力在场）。
    """

    def _run_evaluate(self, monkeypatch, phase_result, tags=None):
        df = _mk_kline(60)

        class _FakeDM:
            cache = None

        monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: _FakeDM())
        # 注意：evaluate 内部实例化的是 dim4 模块的 PhaseDetectionEngine（D4PhaseEngine），
        # 非 phase_detector.py 的——须 monkeypatch D4PhaseEngine
        monkeypatch.setattr(
            D4PhaseEngine, 'compute_tags',
            staticmethod(lambda *a, **k: phase_result))
        monkeypatch.setattr(
            CrowdingFactor, 'evaluate',
            lambda self, *a, **k: {
                'crowding_level': 'MODERATE_CROWDING', 'crowding_score': 0.5,
                'risk_advice': '拥挤度适中',
            })
        engine = Dim4ChipFundEngine()
        _tags = {'ts_code': '000001.SZ', 'fund_flow': ''}
        _tags.update(tags or {})
        return engine.evaluate({}, _tags, data_context={'daily_df': df})

    def _cond(self, res):
        return next(c for c in res['audit']['conditions'] if c['name'] == '主力阶段')

    def test_low_confidence_not_satisfied(self, monkeypatch):
        """PhaseEngine 重算 phase='building' 但置信 0.2 <0.3 → audit 条件 1 不满足"""
        res = self._run_evaluate(monkeypatch, {
            'main_force_phase': 'building', 'phase_confidence': 0.2,
            'fund_flow': 'none', 'trend_alignment': 'up_aligned',
            'price_position': 'mid_zone',
        })
        cond = self._cond(res)
        assert cond['satisfied'] is False, cond
        assert cond['actual'] == '建仓期'

    def test_high_confidence_satisfied(self, monkeypatch):
        """PhaseEngine 重算 phase='building' 且置信 0.5 ≥0.3 → audit 条件 1 满足"""
        res = self._run_evaluate(monkeypatch, {
            'main_force_phase': 'building', 'phase_confidence': 0.5,
            'fund_flow': 'none', 'trend_alignment': 'up_aligned',
            'price_position': 'mid_zone',
        })
        assert self._cond(res)['satisfied'] is True

    def test_boundary_0_3_satisfied(self, monkeypatch):
        """置信恰为 0.3（≥0.3 边界）→ 满足"""
        res = self._run_evaluate(monkeypatch, {
            'main_force_phase': 'lifting', 'phase_confidence': 0.3,
            'fund_flow': 'none', 'trend_alignment': 'up_aligned',
            'price_position': 'mid_zone',
        })
        assert self._cond(res)['satisfied'] is True

    def test_fallback_path_no_confidence_only_phase(self, monkeypatch):
        """兜底路径：PhaseEngine 返回 unknown（不覆盖）→ phase_info 无 confidence 键 →
        仅看 phase（tags main_force_phase='building' 仍满足，不额外拦截）"""
        res = self._run_evaluate(monkeypatch, {
            'main_force_phase': 'unknown', 'phase_confidence': 0.0,
            'fund_flow': 'none', 'trend_alignment': 'no_trend',
            'price_position': 'mid_zone',
        }, tags={'main_force_phase': 'building'})
        assert self._cond(res)['satisfied'] is True

    def test_unknown_phase_not_satisfied(self, monkeypatch):
        """阶段 unknown（tags 也无明确阶段）→ 不满足（原行为保持）"""
        res = self._run_evaluate(monkeypatch, {
            'main_force_phase': 'unknown', 'phase_confidence': 0.0,
            'fund_flow': 'none', 'trend_alignment': 'no_trend',
            'price_position': 'mid_zone',
        })
        assert self._cond(res)['satisfied'] is False

    def test_confidence_key_in_source(self):
        """audit 条件 1 已含置信门槛表达式（防回归）"""
        import inspect
        src = inspect.getsource(Dim4ChipFundEngine.evaluate)
        assert '_phase_conf >= 0.3' in src

