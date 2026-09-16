"""447号：dim5 情绪引擎知识库修正 单元测试

覆盖：
- T1a：温度 7 输入全传（limit_up/sealing/sector_rank/breadth 权重生效）
- T2a：阶段双源对齐六段论（PHASE_MAP 无 recovery；fallback 无 recovery 产出）
- T3a-2：慢线改为 ERP(减国债)/融资/股债收益差，移除 PE 分位，ERP 减国债
- T4a：audit 个股情绪"极度消极"条件真实可触发（非恒真）
- T5：emotion_temperature.py 为温度 SSOT，dim5 不再内嵌副本
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from unittest import mock

import pytest


# ── T5：温度 SSOT（emotion_temperature.py 导入，dim5 无内嵌副本） ────

class TestTempSSOT:

    def test_dim5_imports_not_embeds(self):
        """dim5 通过 import 用温度 SSOT，文件内不得再定义 calc_emotion_temperature"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        src = open(mod.__file__).read()
        assert 'from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature' in src
        assert 'def calc_emotion_temperature(' not in src

    def test_ssot_function_exists(self):
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        assert callable(calc_emotion_temperature)


# ── T1a：温度 7 输入全传后权重生效（SSOT 函数直接验证） ───────────

class TestTemperatureInputs:

    def test_limit_up_weight_effective(self):
        """limit_up_count 高 → 温度升高（15% 权重激活，修复前恒 0）"""
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        low = calc_emotion_temperature(sentiment_phase='ferment', limit_up_count=0)
        high = calc_emotion_temperature(sentiment_phase='ferment', limit_up_count=100)
        assert high > low

    def test_sealing_rate_weight_effective(self):
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        low = calc_emotion_temperature(sentiment_phase='ferment', sealing_rate=0.0)
        high = calc_emotion_temperature(sentiment_phase='ferment', sealing_rate=100.0)
        assert high > low

    def test_sector_rank_effective(self):
        """sector_rank 越小板块越热→温度越高（15% 权重激活）"""
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        hot = calc_emotion_temperature(sentiment_phase='ferment', sector_rank=1)
        cold = calc_emotion_temperature(sentiment_phase='ferment', sector_rank=50)
        assert hot > cold

    def test_breadth_effective(self):
        """breadth 高→温度升高（10% 权重激活）"""
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        high = calc_emotion_temperature(sentiment_phase='ferment', breadth=0.8)
        low = calc_emotion_temperature(sentiment_phase='ferment', breadth=0.1)
        assert high > low

    def test_margin_effective(self):
        """margin_change_pct 高→温度升高（10% 权重）"""
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        high = calc_emotion_temperature(sentiment_phase='ferment', margin_change_pct=0.05)
        low = calc_emotion_temperature(sentiment_phase='ferment', margin_change_pct=-0.05)
        assert high > low

    def test_phase_base_effective(self):
        """六段论阶段基准分生效（25%）"""
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        climax = calc_emotion_temperature(sentiment_phase='climax')
        ice = calc_emotion_temperature(sentiment_phase='ice')
        assert climax > ice

    def test_volume_price_effective(self):
        from app.opportunity_atlas.emotion_temperature import calc_emotion_temperature
        healthy = calc_emotion_temperature(sentiment_phase='ferment', volume_price_fit='healthy')
        diverging = calc_emotion_temperature(sentiment_phase='ferment', volume_price_fit='diverging')
        assert healthy > diverging


# ── T2a：阶段双源对齐六段论 ─────────────────────────────────────

class TestPhaseSixStage:

    def test_phase_map_no_recovery(self):
        """dim5 PHASE_MAP 不得含 recovery（对齐六段论）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        assert 'recovery' not in mod.PHASE_MAP
        assert set(mod.PHASE_MAP) == {'ice', 'sprout', 'ferment', 'climax', 'ebb', 'regression'}

    def test_ssot_phase_base_no_recovery(self):
        from app.opportunity_atlas import emotion_temperature as et
        assert 'recovery' not in et.PHASE_BASE_TEMP

    def test_daemon_fallback_no_recovery(self):
        """data_daemon 六段论 fallback 不得产出 recovery"""
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, 'data_daemon.py')).read()
        # fallback 赋值处不得有 recovery；六段论产出不得含 recovery
        assert "_sentiment_phase_global = 'recovery'" not in src


# ── T3a-2：慢线构成（ERP 减国债 + 股债收益差 + 移除 PE 分位） ─────

class TestSlowLine:

    def test_slow_line_uses_dv_bond_diff(self):
        """慢线第 3 项应为股债收益差（dv_bond_diff），不再用 PE 分位"""
        import types
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        a = BociasiQuadrantAnalyzer.__new__(BociasiQuadrantAnalyzer)
        a._market_stats = {
            'erp_percentile': 0.5, 'margin_trend': 0.5, 'dv_bond_diff': 0.2,
        }
        a._cache = {}
        a._compute_erp_percentile = mock.Mock()
        a._compute_margin_trend = mock.Mock()
        a._compute_dv_bond_diff = mock.Mock()
        line = a._compute_slow_line()
        # 3 项：ERP(0.5→0.5) 融资(0.5) dv_bond(0.2→0.8) → 均值 0.6
        assert line == pytest.approx(0.6)
        a._compute_erp_percentile.assert_not_called()
        a._compute_dv_bond_diff.assert_not_called()
        a._compute_margin_trend.assert_not_called()

    def test_slow_line_no_pe(self):
        """framework 不得再有 _compute_pe_percentile（慢线误加项已删）"""
        import importlib
        mod = importlib.import_module('app.engine.framework.bociasi_quadrant')
        assert not hasattr(mod.BociasiQuadrantAnalyzer, '_compute_pe_percentile')

    def test_dv_bond_diff_direction(self):
        """股债收益差越高 → 慢线得分越低（性价比越高=慢线低位）"""
        import types
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        a = BociasiQuadrantAnalyzer.__new__(BociasiQuadrantAnalyzer)
        a._cache = {}
        a._market_stats = {'erp_percentile': 0.5, 'margin_trend': 0.5,
                          'dv_bond_diff': 0.9}   # 股息收益差高→性价比高
        a._compute_erp_percentile = mock.Mock()
        a._compute_margin_trend = mock.Mock()
        a._compute_dv_bond_diff = mock.Mock()
        hi = a._compute_slow_line()
        a._market_stats['dv_bond_diff'] = 0.1   # 收益差低
        lo = a._compute_slow_line()
        assert hi < lo


# ── T4a：audit 个股情绪"极度消极"真实可触发 ──────────────────────

class TestAuditStockEmotion:

    def _assess(self, vpf, vp_state=None):
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        dims = {'vp': {'judgment': {'state': vp_state}}} if vp_state else {'vp': {}}
        return mod._assess_stock_emotion({'volume_price_fit': vpf}, dims)

    def test_severe_divergence_produces_extreme_negative(self):
        """dim3 严重背离 → 个股情绪'极度消极'（audit 条件可触发）"""
        res = self._assess('diverging', vp_state='严重背离')
        assert res['emotion'] == '极度消极'
        assert res['light'] == 'red'

    def test_normal_divergence_watch(self):
        """普通背离 → '关注'（非极度消极）"""
        res = self._assess('diverging', vp_state='背离')
        assert res['emotion'] == '关注'

    def test_audit_condition_real(self):
        """audit 个股情绪条件：健康满足、极度消极不满足（非恒真）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        stock_ok = mod._assess_stock_emotion({'volume_price_fit': 'healthy'}, {'vp': {}})
        stock_bad = mod._assess_stock_emotion({'volume_price_fit': 'diverging'},
                                              {'vp': {'judgment': {'state': '严重背离'}}})
        c_ok = {'name': '个股情绪', 'satisfied': stock_ok['emotion'] not in ('极度消极',),
                'actual': stock_ok['emotion']}
        c_bad = {'name': '个股情绪', 'satisfied': stock_bad['emotion'] not in ('极度消极',),
                 'actual': stock_bad['emotion']}
        assert c_ok['satisfied'] is True      # 健康 → 满足
        assert c_bad['satisfied'] is False    # 极度消极 → 不满足（条件真可触发）


# ── T1a 集成：dim5.evaluate 温度调用补全 ──────────────────────────

class TestDim5EvaluateTemperature:
    """真实 evaluate 应透传 4 个此前锁死的入参"""

    def test_evaluate_builds_temperature_inputs(self):
        import importlib
        from app.opportunity_atlas.dimensions import dim5_emotion_engine as mod5
        eng = mod5.Dim5EmotionEngine.__new__(mod5.Dim5EmotionEngine)
        # mock dm：get_stock_industry / get_cached_margin
        eng._get_dm = mock.Mock()
        eng._get_dm().get_stock_industry = mock.Mock(return_value='白酒')
        eng._get_dm().cache.get_cached_margin = mock.Mock(return_value=None)
        data_context = {
            'sector_heat': {'白酒': {'heat_level': 'top_10', 'rank': 3}},
            'emotion_ext': {'limit_up_count': 70, 'sealing_rate': 60.0},
            'market_stats': {'ma20_ratio': 0.65},
            'margin_df': None,
        }
        tags = {'ts_code': '000001.SZ', 'sentiment_phase': 'ferment',
                'volume_price_fit': 'healthy'}
        with mock.patch.object(mod5, 'calc_emotion_temperature',
                               wraps=mod5.calc_emotion_temperature) as m:
            with mock.patch.object(mod5, 'BociasiQuadrantAnalyzer') as MockBA:
                MockBA.return_value.analyze.return_value = {'quadrant': 'MM',
                                                            'fast_score': 0.5, 'slow_score': 0.5}
                result = eng.evaluate({}, tags, data_context=data_context)
        # calc 被调用且入参含此前锁死的 4 项
        assert m.called
        kwargs = m.call_args.kwargs if m.call_args.kwargs else m.call_args[1]
        assert kwargs.get('limit_up_count') == 70
        assert kwargs.get('sealing_rate') == 60.0
        assert kwargs.get('sector_rank') == 3
        assert kwargs.get('breadth') == 0.65
        # temperature 落 judgment.continuous_value
        assert 'judgment' in result and 'continuous_value' in result.get('judgment', {})


# ── 独立模块 emotion_temperature 签名完整性 ───────────────────────

class TestSSOTFullSignature:

    def test_ssot_seven_inputs(self):
        """温度 SSOT 必须保留 7 输入（含可选 breadth/margin）"""
        import inspect
        from app.opportunity_atlas import emotion_temperature as et
        params = inspect.signature(et.calc_emotion_temperature).parameters
        assert {'sentiment_phase', 'limit_up_count', 'sealing_rate', 'sector_rank',
                'volume_price_fit', 'margin_change_pct', 'breadth'} <= set(params)


# ── 归一化：历史绝对分位（用户拍板）——负值不再 None，落为 0~1 分位 ──

class TestNegativeValuePercentileNormalization:
    """A股盈利收益率/股息率普遍低于国债，ERP/股债收益差绝对值恒为负。
    447号 用户拍板：比值归一化对负值失效 → 改「当日绝对值在近252交易日历史分位」。
    回归：负值场景不得再触发 None（426守卫整批不落库），且必须产出 0~1 分位。
    分库 dispatcher 须覆盖全部核心项，否则 426 P0-1 守卫整批不落库（防假值）。"""

    def _precompute_stats(self, erp_rows, dv_rows):
        """跑 _precompute_market_stats，返回 _market_stats_cache

        注：须在 with 块内捕获结果——mock.patch.object(_market_stats_cache) 退出时
        会恢复原值，函数内的 global 重赋值在 with 外读不到。
        """
        import data_daemon as dd
        class _FakeECM:
            persisted = []
            def cache_market_stats(self, stats):
                self.persisted.append(dict(stats))
        ecm = _FakeECM()

        # 覆盖全部 7 核心项 + pe_percentile 源；ERP/dv 用 (trade_date, val) 负值序列，
        # 其余项给足源数据使 426 守卫放行（不触发整批不落库）
        fragment_rows = {
            # ERP 分位查询（近252交易日逐日 AVG(pe_ttm)）
            'pe_ttm) AS pe FROM (': erp_rows,
            'pe_ttm': [(15.0,), (12.0,)],
        }
        # dv_bond 分位查询（含 'dv_median'）
        fragment_rows['dv_median'] = dv_rows
        # 其余核心项的单值源（复用 426 GOOD_SHARD_ROWS 结构与片段）
        good = {
            'SMA_20': [(100, 60)],
            'turnover_rate': [(0.05,), (0.08,)],
            'high_limit': [(5, 2)],
            'rsi14': [(55.0,), (50.0,)],
            'rzye': [('2026-09-15', 110.0), ('2026-09-14', 100.0),
                     ('2026-09-11', 95.0), ('2026-09-10', 90.0),
                     ('2026-09-09', 85.0)],
        }
        for k, v in good.items():
            fragment_rows[k] = v

        def _fake(table, sql, params=None):
            for frag, rows in fragment_rows.items():
                if frag in sql:
                    return rows
            return []

        with mock.patch.object(dd, '_ensure_ecm', lambda: None), \
             mock.patch.object(dd, '_ecm', ecm), \
             mock.patch.object(dd, '_market_stats_cache', {}), \
             mock.patch.object(dd, '_shard_fetchall', _fake):
            import app.data.sharding_manager as sm
            with mock.patch.object(sm.sharding_manager, 'get_table_row_count',
                                   lambda t: 1000):
                dd._precompute_market_stats(target_date='2026-09-15')
                result = dict(dd._market_stats_cache)  # 在 with 内捕获
        return result

    def test_erp_percentile_negative_series_produces_normalized_rank(self):
        """全正/全负 ERP 序列→ erp_percentile 为 0~1 分位而非 None"""
        erp_rows = [
            # pe 按日递减 → ERP 递增；用 4 个历史日 + 1 个当日
            ('2026-09-08', 40), ('2026-09-09', 30), ('2026-09-10', 25),
            ('2026-09-14', 20), ('2026-09-15', 15),
        ]
        dv_rows = [('2026-09-15', 1.0)]
        stats = self._precompute_stats(erp_rows, dv_rows)
        erp = stats.get('erp_percentile')
        assert erp is not None, '负值序列不得再返回 None（否则 426 守卫整批不落库）'
        assert 0.0 <= erp <= 1.0
        # 序列 ERP 值: pe=40→0.80, 30→1.63, 25→2.30, 20→3.30, 15→4.97（均减 1.7）
        # 当日 4.97 是最大值 → 分位 count_less/len = 4/5 = 0.8
        assert erp == pytest.approx(0.8)

    def test_erp_percentile_negative_series_and_guard_passes(self):
        """负值 ERP 序列下 7 项仍全非 None，426 守卫放行整批落库（此前恒负会拖垮核心项）"""
        erp_rows = [
            ('2026-09-08', 40), ('2026-09-09', 45), ('2026-09-10', 55),
            ('2026-09-14', 60), ('2026-09-15', 50),   # 当日 PE 居中 → ERP 分位居中
        ]
        dv_rows = [('2026-09-15', 1.0)]
        stats = self._precompute_stats(erp_rows, dv_rows)
        for k in ('ma20_ratio', 'turnover_percentile', 'limit_ratio',
                  'rsi_percentile', 'erp_percentile', 'margin_trend', 'pe_percentile'):
            assert stats.get(k) is not None, f'{k} 应为非 None（负值 ERP 不拖垮整批）'
        assert 0.0 <= stats['erp_percentile'] <= 1.0

    def test_dv_bond_diff_negative_series_produces_normalized_rank(self):
        """股债差分位（股息率恒低于国债→diff 恒负）→ 0~1 分位而非 None"""
        erp_rows = [('2026-09-15', 15)]
        dv_rows = [
            ('2026-09-08', 1.2), ('2026-09-09', 1.1), ('2026-09-10', 1.0),
            ('2026-09-14', 0.9), ('2026-09-15', 0.7),   # 当日最低 → diff 最低 → 0 分位
        ]
        stats = self._precompute_stats(erp_rows, dv_rows)
        dv = stats.get('dv_bond_diff')
        assert dv is not None, '负值分位不得返回 None'
        assert 0.0 <= dv <= 1.0
        # diff = dv_median - 1.7：1.2→-0.5, 1.1→-0.6, 1.0→-0.7, 0.9→-0.8, 0.7→-1.0
        # 当日 -1.0 是最小值 → count_less/len = 0/5 = 0.0
        assert dv == pytest.approx(0.0)
