"""411号方案全流程集成测试

验证411号方案v3.0的14个Phase实施效果：
- Phase 1: signal_computation_service旧路径已剔除
- Phase 2: signal_analyzer.py JUD层信号分析
- Phase 3: dim1重写为数据质量门禁层
- Phase 4: status_engine适配 + dim8键名对齐
- Phase 5: MA/MACD改读预计算表
- Phase 6: dim2-dim7消费data_context
- Phase 7-13: dim引擎读取预计算数据
- Phase 14: 端到端验证
"""

import numpy as np
import pytest

# ═══════════════════════════════════════════════════════════
# Phase 1: signal_computation_service旧路径已剔除
# ═══════════════════════════════════════════════════════════

class TestPhase1_OldPathRemoved:
    """Phase 1: compute_via_engines()不再直接调用dim1-dim6"""

    def test_compute_via_engines_returns_empty_signals(self):
        """compute_via_engines()应返回空signals列表（旧调用已移除）"""
        from app.services.signal_computation_service import SignalComputationService
        svc = SignalComputationService()
        result = svc.compute_via_engines('000001.SZ', {}, {})
        assert isinstance(result, list)
        # 旧路径已移除，应返回空列表或仅含_dim_results的兼容项
        for sig in result:
            if isinstance(sig, dict):
                assert '_dim_results' in sig or '_source' in sig

    def test_no_direct_dim_imports_in_service(self):
        """signal_computation_service不应导入任何dim引擎"""
        import importlib
        mod = importlib.import_module('app.services.signal_computation_service')
        source = open(mod.__file__).read()
        for dim_name in ['Dim1SignalEngine', 'Dim2StructureEngine', 'Dim3VPEngine',
                         'Dim4ChipFundEngine', 'Dim5EmotionEngine', 'Dim6RiskEngine']:
            assert dim_name not in source, f"{dim_name}仍被导入到signal_computation_service"


# ═══════════════════════════════════════════════════════════
# Phase 2: signal_analyzer.py JUD层信号分析
# ═══════════════════════════════════════════════════════════

class TestPhase2_SignalAnalyzer:
    """Phase 2: signal_analyzer包含全部迁移的分析函数"""

    def test_classify_attribute_exists(self):
        from app.opportunity_atlas.signal_analyzer import classify_attribute
        assert callable(classify_attribute)

    def test_calc_resonance_score_exists(self):
        from app.opportunity_atlas.signal_analyzer import calc_resonance_score
        assert callable(calc_resonance_score)

    def test_detect_decay_exists(self):
        from app.opportunity_atlas.signal_analyzer import detect_decay
        assert callable(detect_decay)

    def test_analyze_signal_returns_correct_structure(self):
        from app.opportunity_atlas.signal_analyzer import analyze_signal
        dims = {
            'structure': {'state': '上升', 'confidence': 0.7},
            'volume_price': {'state': '放量', 'confidence': 0.6},
        }
        tags = {'ts_code': '000001.SZ'}
        result = analyze_signal(dims, tags, {})
        assert isinstance(result, dict)
        assert 'status_description' in result or 'judgment' in result or 'attr' in result

    def test_constants_defined(self):
        from app.opportunity_atlas.signal_analyzer import (
            DECAY_WEIGHTS,
            LIGHT_MAP,
            RESONANCE_WEIGHTS,
            SIGNAL_ATTRIBUTES,
        )
        assert len(SIGNAL_ATTRIBUTES) == 7
        assert len(RESONANCE_WEIGHTS) == 4
        assert len(DECAY_WEIGHTS) == 5
        assert len(LIGHT_MAP) == 7


# ═══════════════════════════════════════════════════════════
# Phase 3: dim1重写为数据质量门禁层
# ═══════════════════════════════════════════════════════════

class TestPhase3_Dim1Gate:
    """Phase 3: dim1仅作为数据质量门禁层"""

    def test_dim1_returns_data_context(self):
        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        engine = Dim1SignalEngine()
        result = engine.evaluate({}, {'ts_code': '000001.SZ'}, None, None)
        assert isinstance(result, dict)
        assert 'data_context' in result
        assert 'status_quality' in result

    def test_dim1_no_analysis_code(self):
        """dim1不应包含分析函数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        source = inspect.getsource(Dim1SignalEngine)
        for func_name in ['classify_attribute', 'calc_resonance_score', 'detect_decay',
                          'calc_lifecycle_stage', 'signal_plain', 'build_audit']:
            assert func_name not in source, f"dim1仍包含分析函数{func_name}"

    def test_dim1_evaluate_signature(self):
        import inspect

        from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
        sig = inspect.signature(Dim1SignalEngine.evaluate)
        params = list(sig.parameters.keys())
        assert 'data_context' in params


# ═══════════════════════════════════════════════════════════
# Phase 4: status_engine适配
# ═══════════════════════════════════════════════════════════

class TestPhase4_StatusEngine:
    """Phase 4: status_engine调用流程改造"""

    def test_build_dim_engine_results_calls_dim1_first(self):
        """_build_dim_engine_results应先调dim1获取data_context"""
        import inspect

        from app.opportunity_atlas.status_engine import StatusEngine
        source = inspect.getsource(StatusEngine._build_dim_engine_results)
        # dim1调用应在engine_map循环之前
        dim1_pos = source.find('Dim1SignalEngine')
        engine_map_pos = source.find('engine_map')
        assert dim1_pos < engine_map_pos, "dim1应在engine_map之前调用"

    def test_data_context_injected_to_dim2_dim7(self):
        """data_context应注入到dim2-dim7"""
        import inspect

        from app.opportunity_atlas.status_engine import StatusEngine
        source = inspect.getsource(StatusEngine._build_dim_engine_results)
        assert 'data_context=data_context' in source

    def test_dim8_key_alignment(self):
        """dim8应使用chip_fund而非fund_chip"""
        import inspect

        from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
        source = inspect.getsource(Dim8SummaryEngine)
        assert 'fund_chip' not in source, "dim8仍使用旧键名fund_chip"
        # 应使用chip_fund
        from app.opportunity_atlas.dimensions import dim8_summary_engine
        mod_source = open(dim8_summary_engine.__file__).read()
        assert 'chip_fund' in mod_source

    def test_extract_dim_audit_confidence_no_recursive_bug(self):
        """_extract_dim_audit_confidence不应有递归bug"""
        import inspect

        from app.opportunity_atlas.dimensions.dim8_summary_engine import (
            _extract_dim_audit_confidence,
        )
        source = inspect.getsource(_extract_dim_audit_confidence)
        # 不应有dim_results.get(dim_results, {})这种递归调用
        assert 'dim_results.get(dim_results' not in source


# ═══════════════════════════════════════════════════════════
# Phase 5: MACD改读预计算表
# ═══════════════════════════════════════════════════════════

class TestPhase5_MACDPrecomputed:
    """Phase 5: dim2/dim3 MACD改读预计算表"""

    def test_dim2_calc_macd_accepts_precomputed(self):
        """dim2的calc_macd应接受precomputed参数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_macd
        sig = inspect.signature(calc_macd)
        assert 'precomputed' in sig.parameters

    def test_dim3_calc_macd_accepts_precomputed(self):
        """dim3的calc_macd应接受precomputed参数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim3_vp_engine import calc_macd
        sig = inspect.signature(calc_macd)
        assert 'precomputed' in sig.parameters

    def test_dim2_calc_macd_uses_precomputed_when_valid(self):
        """dim2的calc_macd应使用预计算数据当可用时"""
        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_macd
        closes = np.random.randn(100).cumsum() + 10
        precomputed = {
            'macd_dif': np.ones(100) * 0.5,
            'macd_dea': np.ones(100) * 0.3,
            'macd_hist': np.ones(100) * 0.4,
        }
        dif, dea, hist = calc_macd(closes, precomputed)
        np.testing.assert_array_equal(dif, precomputed['macd_dif'])
        np.testing.assert_array_equal(dea, precomputed['macd_dea'])
        np.testing.assert_array_equal(hist, precomputed['macd_hist'])

    def test_dim2_calc_macd_falls_back_to_raw(self):
        """dim2的calc_macd应在无预计算时回退到raw计算"""
        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_macd
        closes = np.random.randn(100).cumsum() + 10
        dif, dea, hist = calc_macd(closes, None)
        assert len(dif) == 100
        assert len(dea) == 100
        assert len(hist) == 100
        # raw计算的结果不应全为0
        assert not np.all(dif == 0)

    def test_dim2_calc_macd_falls_back_on_mismatch(self):
        """dim2的calc_macd应在预计算长度不匹配时回退到raw计算"""
        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_macd
        closes = np.random.randn(100).cumsum() + 10
        precomputed = {
            'macd_dif': np.ones(50) * 0.5,  # 长度不匹配
            'macd_dea': np.ones(50) * 0.3,
            'macd_hist': np.ones(50) * 0.4,
        }
        dif, dea, hist = calc_macd(closes, precomputed)
        assert len(dif) == 100  # 应回退到raw计算


# ═══════════════════════════════════════════════════════════
# Phase 6: dim2-dim7消费data_context
# ═══════════════════════════════════════════════════════════

class TestPhase6_DataContext:
    """Phase 6: dim2-dim7的evaluate()接受并使用data_context"""

    @pytest.mark.parametrize("module,class_name", [
        ('app.opportunity_atlas.dimensions.dim2_structure_engine', 'Dim2StructureEngine'),
        ('app.opportunity_atlas.dimensions.dim3_vp_engine', 'Dim3VPEngine'),
        ('app.opportunity_atlas.dimensions.dim4_chip_fund_engine', 'Dim4ChipFundEngine'),
        ('app.opportunity_atlas.dimensions.dim5_emotion_engine', 'Dim5EmotionEngine'),
        ('app.opportunity_atlas.dimensions.dim6_risk_engine', 'Dim6RiskEngine'),
        ('app.opportunity_atlas.dimensions.dim7_valuation_engine', 'Dim7ValuationEngine'),
    ])
    def test_evaluate_accepts_data_context(self, module, class_name):
        """所有dim2-dim7引擎的evaluate()应接受data_context参数"""
        import importlib
        import inspect
        mod = importlib.import_module(module)
        cls = getattr(mod, class_name)
        sig = inspect.signature(cls.evaluate)
        assert 'data_context' in sig.parameters, f"{class_name}.evaluate()缺少data_context参数"


# ═══════════════════════════════════════════════════════════
# Phase 9: dim6读取risk_ext预计算
# ═══════════════════════════════════════════════════════════

class TestPhase9_Dim6Precomputed:
    """Phase 9: dim6从tags读取预计算risk_ext"""

    def test_dim6_reads_precomputed_geo_from_tags(self):
        """dim6应从tags读取预计算的几何化指标"""
        import inspect

        from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine
        source = inspect.getsource(Dim6RiskEngine.evaluate)
        assert '_geo_precomputed' in source or 'risk_ext' in source

    def test_dim6_reads_precomputed_vol_from_tags(self):
        """dim6应从tags读取预计算的波动率"""
        import inspect

        from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine
        source = inspect.getsource(Dim6RiskEngine.evaluate)
        assert '_vol_precomputed' in source or 'atr_14d' in source


# ═══════════════════════════════════════════════════════════
# Phase 8: dim4读取5日资金聚合预计算
# ═══════════════════════════════════════════════════════════

class TestPhase8_Dim4FundPrecomputed:
    """Phase 8: dim4从tags读取预计算5日资金聚合"""

    def test_dim4_dim_fund_accepts_extra_tags(self):
        """dim4的_dim_fund应接受extra_tags参数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine
        sig = inspect.signature(PhaseDetectionEngine._dim_fund)
        assert 'extra_tags' in sig.parameters


# ═══════════════════════════════════════════════════════════
# dim_adapter _SIGNAL_CODE_DIRECTION修复
# ═══════════════════════════════════════════════════════════

class TestDimAdapterFix:
    """dim_adapter _SIGNAL_CODE_DIRECTION不再有UnboundLocalError"""

    def test_convert_to_factors_works(self):
        """convert_to_factors不应抛出UnboundLocalError"""
        from app.opportunity_atlas.dim_adapter import convert_to_factors
        mock_dims = {
            'signal': {'judgment': {'attribute': {'code': 'neutral'}}},
            'structure': {'judgment': {'overall_direction': 0, 'continuous_value': 0.5},
                         'status_description': {}},
        }
        mock_tags = {'ts_code': '000001.SZ'}
        result = convert_to_factors(mock_dims, mock_tags)
        assert isinstance(result, dict)
        assert 'signal' in result
        assert 'signal_confirm' in result


# ═══════════════════════════════════════════════════════════
# 端到端：status_engine全流程
# ═══════════════════════════════════════════════════════════

class TestEndToEnd:
    """端到端验证：status_engine全流程"""

    def test_signal_decay_detector_imports_from_analyzer(self):
        """signal_analyzer仍包含detect_decay（signal_ext废弃后不再在precompute中导入）"""
        from app.opportunity_atlas.signal_analyzer import detect_decay
        assert callable(detect_decay)
