"""464号批次2测试：dim4 判定类已拍板项锁定（464-14 / 464-10 / 464-12）

覆盖：
  TestAuditFundFlowEnum      —— ① 464-14 audit「资金流向」判定集补 strong_out + 清死枚举
  TestMarginRzmreMapping     —— ② 464-10 _batch_margin rzmre→rzmje 映射（采集层根治）
  TestMarginCostPriceCalc    —— ③ 464-10 _calc_margin_cost_price OHLC 兜底（margin_df 无 K 线列，
                                  改 daily 收盘价近似；双份同步）
  TestLimitUpCrossCheck      —— ④ 464-12 规则3「次日低开」改判定窗口（T-1 高位涨停巨量 + T 低开≥3%，
                                  T 无需涨停；双涨停低开高走被覆盖）

背景实证（2026-09-21）：
  464-14：实现只产 strong/strong_out/none；原判定集 ('very_strong','strong','medium','weak')
          含死枚举且漏 strong_out → 资金强流出时 audit 恒 False（与强流入不对称）。
  464-10：Tushare margin_detail 实测返回 rzmre（融资买入额，2026-09-18 4448 行有值），
          margin_cache 表结构列为 rzmje → 采集原样入库时 rzmre 被列过滤丢弃、rzmje 恒 NULL
          （全市场 66598 行 rzmje 有值行=0）→ margin_cost_price 全市场死路；
          回补后（347151 行有值）另暴露 _calc_margin_cost_price 读 margin_df OHLC 列不存在。
  464-12：日终节奏下 T+1 数据不可得，298「次日低开」忠实近似 = T-1 涨停日 + T 低开日（改窗口）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import inspect

import numpy as np
import pandas as pd
import pytest
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    CrowdingFactor,
    Dim4ChipFundEngine,
    PhaseDetectionEngine,
)
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import (
    MainForceScorer as D4Scorer,
)


def _mk_df(n: int = 60) -> pd.DataFrame:
    dates = pd.date_range('2026-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'trade_date': dates.strftime('%Y-%m-%d'),
        'open': 10.0, 'high': 11.0, 'low': 9.5, 'close': 10.5,
        'vol': 1_000_000, 'amount': 10_000_000,
    })


class TestAuditFundFlowEnum:
    """464-14：audit「资金流向」补 strong_out（强流出=有明确流向）+ 清死枚举"""

    def _run_evaluate(self, monkeypatch, fund_flow_tag):
        df = _mk_df(60)

        class _FakeDM:
            cache = None

        monkeypatch.setattr(Dim4ChipFundEngine, '_get_dm', lambda self: _FakeDM())
        # 引擎覆盖路径产 fund_flow='none' → 走 tags 路径（_assess_fund_flow 消费 tags['fund_flow']）
        monkeypatch.setattr(
            PhaseDetectionEngine, 'compute_tags',
            staticmethod(lambda *a, **k: {
                'main_force_phase': 'unknown', 'phase_confidence': 0.0,
                'fund_flow': 'none', 'trend_alignment': 'no_trend',
                'price_position': 'mid_zone',
            }))
        monkeypatch.setattr(
            CrowdingFactor, 'evaluate',
            lambda self, *a, **k: {
                'crowding_level': 'MODERATE_CROWDING', 'crowding_score': 0.5,
                'risk_advice': '拥挤度适中',
            })
        engine = Dim4ChipFundEngine()
        return engine.evaluate({}, {'ts_code': '000001.SZ', 'fund_flow': fund_flow_tag},
                               data_context={'daily_df': df})

    def _cond(self, res):
        return next(c for c in res['audit']['conditions'] if c['name'] == '资金流向')

    def test_strong_outflow_satisfied(self, monkeypatch):
        """tags fund_flow='5d_outflow'（强流出）→ audit「资金流向」satisfied True（修复前恒 False）"""
        res = self._run_evaluate(monkeypatch, '5d_outflow')
        cond = self._cond(res)
        assert cond['satisfied'] is True, cond
        assert cond['actual'] == '强流出'

    def test_strong_inflow_satisfied(self, monkeypatch):
        """tags fund_flow='5d_inflow'（强流入）→ satisfied True（原行为保持）"""
        res = self._run_evaluate(monkeypatch, '5d_inflow')
        assert self._cond(res)['satisfied'] is True

    def test_neutral_not_satisfied(self, monkeypatch):
        """tags 无 fund_flow（中性）→ satisfied False（原行为保持）"""
        res = self._run_evaluate(monkeypatch, '')
        assert self._cond(res)['satisfied'] is False

    def test_dead_enums_removed_from_source(self):
        """判定集已收敛为 ('strong','strong_out')——死枚举不再出现在判定表达式"""
        src = inspect.getsource(Dim4ChipFundEngine.evaluate)
        assert "fund_flow_info['level'] in ('strong', 'strong_out')" in src


class TestMarginRzmreMapping:
    """464-10：_batch_margin rzmre→rzmje 映射（采集层根治）"""

    def test_rzmre_mapped_to_rzmje(self, monkeypatch):
        """API 返回 rzmre（无 rzmje）→ 入库前 df 含 rzmje=rzmre"""
        import data_daemon

        raw = pd.DataFrame({
            'ts_code': ['600519.SH', '000001.SZ'],
            'trade_date': ['20260918', '20260918'],
            'rzye': [1.71e10, 4.58e9],
            'rzmre': [5.5e7, 5.5e7],
            'rqyl': [133548.0, 9880337.0],
            'rqchl': [None, 113500.0],  # 采集会删 rqchl 列
            'name': ['贵州茅台', '平安银行'],  # 采集会删 name 列
        })
        captured = {}

        class _FakeProvider:
            def get_margin_detail(self, trade_date):
                return raw

        class _FakeECM:
            def cache_margin_data(self, df):
                captured['df'] = df

        monkeypatch.setattr(data_daemon, '_get_tushare_provider', lambda: _FakeProvider())
        monkeypatch.setattr(data_daemon, '_ecm', _FakeECM())

        n = data_daemon._batch_margin('20260918')
        assert n == 2
        out = captured['df']
        assert 'rzmje' in out.columns, out.columns.tolist()
        assert 'rzmre' in out.columns, '保留原列（入库时由列过滤收敛）'
        assert 'name' not in out.columns, 'name 列已删'
        assert 'rqchl' not in out.columns, 'rqchl 列已删'
        pd.testing.assert_series_equal(out['rzmje'], out['rzmre'], check_names=False)
        assert float(out['rzmje'].iloc[0]) == 5.5e7

    def test_rzmje_kept_when_api_returns_it(self, monkeypatch):
        """API 直接返回 rzmje（无 rzmre）→ 不覆盖原值"""
        import data_daemon

        raw = pd.DataFrame({
            'ts_code': ['600519.SH'],
            'trade_date': ['20260918'],
            'rzye': [1.71e10],
            'rzmje': [9.9e7],
        })
        captured = {}

        class _FakeProvider:
            def get_margin_detail(self, trade_date):
                return raw

        class _FakeECM:
            def cache_margin_data(self, df):
                captured['df'] = df

        monkeypatch.setattr(data_daemon, '_get_tushare_provider', lambda: _FakeProvider())
        monkeypatch.setattr(data_daemon, '_ecm', _FakeECM())

        data_daemon._batch_margin('20260918')
        assert float(captured['df']['rzmje'].iloc[0]) == 9.9e7

    def test_empty_api_returns_zero(self, monkeypatch):
        """API 空返回 → 0（不写库，走既有降级逻辑）"""
        import data_daemon

        class _FakeProvider:
            def get_margin_detail(self, trade_date):
                return pd.DataFrame()

        monkeypatch.setattr(data_daemon, '_get_tushare_provider', lambda: _FakeProvider())
        assert data_daemon._batch_margin('20260918') == 0


def _mk_margin_df(no_ohlc=True):
    """构造 margin_df（margin_cache 真实列：rzye/rzmje/...，无 OHLC）"""
    return pd.DataFrame({
        'ts_code': ['600519.SH'] * 3,
        'trade_date': [pd.Timestamp('2026-09-16').date(), pd.Timestamp('2026-09-17').date(),
                       pd.Timestamp('2026-09-18').date()],
        'rzye': [1.7e10] * 3,
        'rzmje': [100.0, 200.0, 300.0],
        'rzrqye': [1.7e10] * 3,
    })


def _mk_daily_close():
    """daily 收盘价映射（trade_date 字符串 → close）"""
    return pd.DataFrame({
        'trade_date': ['2026-09-16', '2026-09-17', '2026-09-18'],
        'close': [10.0, 11.0, 12.0],
    })


class TestMarginCostPriceCalc:
    """464-10：_calc_margin_cost_price OHLC 兜底——margin_df 无 K 线列改用 daily 收盘价近似"""

    def test_dim4_copy_computes_with_close_fallback(self):
        """dim4 内嵌版：margin_df 无 OHLC → daily 收盘价加权 → cost_price=(100*10+200*11+300*12)/600=11.33"""
        scorer = object.__new__(D4Scorer)
        scorer._data_context = {'margin_df': _mk_margin_df(), 'daily_df': _mk_daily_close()}
        scorer._dm = None
        out = scorer._calc_margin_cost_price('600519.SH', latest_close=12.0)
        assert out['cost_price'] == 11.33, out
        # distance 用未舍入 cost_price(11.3333)：(12-11.3333)/11.3333*100 = 5.88
        assert out['distance_pct'] == pytest.approx(5.88, abs=0.01)

    def test_framework_copy_computes_with_close_fallback(self):
        """framework 版（双份同步）：同样以 daily 收盘价兜底计算"""
        from app.engine.framework.chip_strategy import MainForceScorer as FWScorer

        class _FakeDM:
            def get_cached_margin(self, *a, **k):
                return _mk_margin_df()

            def get_cached_daily_data(self, *a, **k):
                return _mk_daily_close()

        scorer = object.__new__(FWScorer)
        scorer._dm = _FakeDM()
        out = scorer._calc_margin_cost_price('600519.SH', latest_close=12.0)
        assert out['cost_price'] == 11.33, out

    def test_ohlc_columns_use_four_price_avg(self):
        """margin_df 若含 OHLC（兼容旧路径）→ 仍用四价均值（原行为保持）"""
        scorer = object.__new__(D4Scorer)
        mdf = _mk_margin_df()
        mdf['open'] = [9.8, 10.8, 11.8]
        mdf['high'] = [10.2, 11.2, 12.2]
        mdf['low'] = [9.6, 10.6, 11.6]
        mdf['close'] = [10.0, 11.0, 12.0]
        scorer._data_context = {'margin_df': mdf}
        scorer._dm = None
        out = scorer._calc_margin_cost_price('600519.SH', latest_close=12.0)
        # 四价均值：9.9/10.9/11.9 加权（100/200/300）→ 11.233 → 11.23
        assert out['cost_price'] == pytest.approx(11.23, abs=0.01), out

    def test_insufficient_buy_days_returns_none(self):
        """融资买入日 <3 → None（数据不足，不产伪值）"""
        scorer = object.__new__(D4Scorer)
        mdf = _mk_margin_df()
        mdf['rzmje'] = [0.0, 0.0, 100.0]  # 仅 1 日买入
        scorer._data_context = {'margin_df': mdf}
        scorer._dm = None
        assert scorer._calc_margin_cost_price('600519.SH', 12.0)['cost_price'] is None


class TestLimitUpCrossCheck:
    """464-12：规则3「次日低开」改判定窗口——T-1 高位涨停巨量 + T 低开≥3%（T 无需涨停）"""

    @staticmethod
    def _mk_rule3_df(prev_limit_up=True, t_limit_up=False, t_open=10.6):
        """61 根日线：0..58 平（close 10, vol 100）→ T-1(idx59) 涨停 vol300 → T(idx60)"""
        n = 61
        rows = []
        for i in range(n):
            if i == 59:  # T-1：涨停日
                rows.append({'trade_date': f'2026-0{i % 9 + 1}-0{i % 28 + 1}', 'open': 10.9,
                             'high': 11.1, 'low': 10.8, 'close': 11.0, 'vol': 300})
            elif i == 60:  # T：次日
                c = 11.0 * 1.1 if t_limit_up else 10.8
                rows.append({'trade_date': f'2026-0{i % 9 + 1}-0{i % 28 + 1}', 'open': t_open,
                             'high': max(t_open, c) + 0.1, 'low': min(t_open, c) - 0.1,
                             'close': c, 'vol': 100})
            else:
                rows.append({'trade_date': f'2026-0{i % 9 + 1}-0{i % 28 + 1}', 'open': 9.9,
                             'high': 10.1, 'low': 9.8, 'close': 10.0, 'vol': 100})
        df = pd.DataFrame(rows)
        if not prev_limit_up:
            df.loc[59, 'close'] = 10.1  # T-1 非涨停（+1%）
        return df

    def test_single_limit_up_next_day_low_open_corrected(self):
        """T-1 涨停 + T 低开≥3%（T 未涨停）→ lifting 修正为 distributing（修复前漏检）"""
        df = self._mk_rule3_df(prev_limit_up=True, t_limit_up=False, t_open=10.6)
        pde = PhaseDetectionEngine()
        out = pde._limit_up_cross_check(df, 'lifting', 'high_zone')
        assert out == 'distributing', out

    def test_double_limit_up_low_open_still_corrected(self):
        """双涨停 + 第二日低开高走（旧场景）→ 仍被覆盖修正为 distributing"""
        df = self._mk_rule3_df(prev_limit_up=True, t_limit_up=True, t_open=10.6)
        pde = PhaseDetectionEngine()
        out = pde._limit_up_cross_check(df, 'lifting', 'high_zone')
        assert out == 'distributing', out

    def test_no_low_open_keeps_lifting(self):
        """T-1 涨停但 T 平开（≥0.97）→ 不触发，保持 lifting"""
        df = self._mk_rule3_df(prev_limit_up=True, t_limit_up=False, t_open=10.8)  # 10.8 ≥ 11*0.97=10.67
        pde = PhaseDetectionEngine()
        assert pde._limit_up_cross_check(df, 'lifting', 'high_zone') == 'lifting'

    def test_no_prev_limit_up_keeps_lifting(self):
        """T-1 非涨停 + T 低开 → 不触发规则3，保持 lifting"""
        df = self._mk_rule3_df(prev_limit_up=False, t_limit_up=False, t_open=10.6)
        pde = PhaseDetectionEngine()
        assert pde._limit_up_cross_check(df, 'lifting', 'high_zone') == 'lifting'

    def test_not_high_zone_keeps_lifting(self):
        """T-1 涨停+巨量 + T 低开但非高位 → 不触发规则3（需高位诱多语义）"""
        df = self._mk_rule3_df(prev_limit_up=True, t_limit_up=False, t_open=10.6)
        pde = PhaseDetectionEngine()
        assert pde._limit_up_cross_check(df, 'lifting', 'low_zone') == 'lifting'

    def test_rule1_2_4_unchanged_when_t_limit_up(self):
        """规则1/2/4（当日 T 涨停）行为保持：building+低位+非巨量确认 / building+高位→distributing /
        distributing+低位+缩量→building"""
        pde = PhaseDetectionEngine()
        df = self._mk_rule3_df(prev_limit_up=True, t_limit_up=True, t_open=10.6)
        # 规则1：building + low_zone + 非巨量（T vol=100 < 2*均值~115）→ 确认 building
        assert pde._limit_up_cross_check(df, 'building', 'low_zone') == 'building'
        # 规则2：building + high_zone → distributing
        assert pde._limit_up_cross_check(df, 'building', 'high_zone') == 'distributing'
        # 规则4：distributing + low_zone + 缩量（T vol=100 < 0.6*~115=69? 否——用更小量构造）
        df_shrink = self._mk_rule3_df(prev_limit_up=True, t_limit_up=True, t_open=10.6)
        df_shrink.loc[60, 'vol'] = 30  # 缩量
        assert pde._limit_up_cross_check(df_shrink, 'distributing', 'low_zone') == 'building'
