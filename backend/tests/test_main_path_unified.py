"""412号方案B5：主路径统一回归测试

验证dim2/dim5/dim7的data_context-first路径和降级fallback路径。
"""
import pandas as pd


class TestDim2MAPrecomputed:
    """dim2 calc_support_resistance MA precomputed-first"""

    def test_calc_support_resistance_accepts_indicator_ma_df(self):
        """calc_support_resistance接受indicator_ma_df参数（v3.0架构合规）"""
        import inspect

        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_support_resistance
        sig = inspect.signature(calc_support_resistance)
        assert 'indicator_ma_df' in sig.parameters

    def test_calc_support_resistance_works_without_ts_code(self):
        """无ts_code时回退raw计算"""
        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_support_resistance
        df = pd.DataFrame({
            'close': [10.0 + i * 0.1 for i in range(65)],
            'high': [10.5 + i * 0.1 for i in range(65)],
            'low': [9.5 + i * 0.1 for i in range(65)],
        })
        result = calc_support_resistance(df)
        assert 'support_price' in result
        assert 'resistance_price' in result

    def test_calc_support_resistance_empty_df(self):
        """空df返回None值"""
        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_support_resistance
        result = calc_support_resistance(None)
        assert result['support_price'] is None
        assert result['resistance_price'] is None

    def test_calc_support_resistance_accepts_indicator_ma_df(self):
        """calc_support_resistance接受indicator_ma_df参数（v3.0架构合规）"""
        import inspect

        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_support_resistance
        sig = inspect.signature(calc_support_resistance)
        assert 'indicator_ma_df' in sig.parameters
        # 不应再有ts_code参数（绕过dim1）
        assert 'ts_code' not in sig.parameters

    def test_calc_support_resistance_uses_indicator_ma_df(self):
        """calc_support_resistance从indicator_ma_df读取MA值"""
        from app.opportunity_atlas.dimensions.dim2_structure_engine import calc_support_resistance
        df = pd.DataFrame({
            'close': [10.0 + i * 0.1 for i in range(65)],
            'high': [10.5 + i * 0.1 for i in range(65)],
            'low': [9.5 + i * 0.1 for i in range(65)],
        })
        indicator_ma_df = pd.DataFrame({'ma20': [11.0], 'ma60': [10.5]})
        result = calc_support_resistance(df, indicator_ma_df=indicator_ma_df)
        assert 'support_price' in result
        assert result['support_price'] is not None


class TestDim5BociasiImport:
    """dim5 BociasiQuadrantAnalyzer改import模块"""

    def test_dim5_imports_from_module(self):
        """dim5从bociasi_quadrant模块导入"""
        import inspect

        from app.opportunity_atlas.dimensions.dim5_emotion_engine import Dim5EmotionEngine
        source = inspect.getsource(Dim5EmotionEngine)
        # 不应包含本地BociasiQuadrantAnalyzer类定义
        assert 'class BociasiQuadrantAnalyzer' not in source

    def test_dim5_bociasi_module_import_exists(self):
        """dim5文件头有bociasi_quadrant模块import"""
        import pathlib
        dim5_path = pathlib.Path(__file__).parent.parent / 'app' / 'opportunity_atlas' / 'dimensions' / 'dim5_emotion_engine.py'
        with open(dim5_path, encoding='utf-8') as f:
            content = f.read()
        assert 'from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer' in content

    def test_sector_rotation_model_has_get_ma(self):
        """SectorRotationModel有_get_ma辅助方法（419号：特性已从dim5副本迁至framework版）"""
        from app.engine.framework.sector_rotation_model import SectorRotationModel
        assert hasattr(SectorRotationModel, '_get_ma')

    def test_sector_rotation_model_ma_precomputed_first(self):
        """SectorRotationModel compute_all_heat接收indicator_ma_dict参数（419号：framework版）"""
        import inspect

        from app.engine.framework.sector_rotation_model import SectorRotationModel
        sig = inspect.signature(SectorRotationModel.compute_all_heat)
        assert 'indicator_ma_dict' in sig.parameters


class TestDim7DataContext:
    """dim7财务数据data_context-first"""

    def test_dim7_compute_valuation_uses_data_context(self):
        """_compute_valuation优先使用data_context"""
        import inspect

        from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine
        source = inspect.getsource(Dim7ValuationEngine._compute_valuation)
        assert 'data_context.get' in source
        assert 'income_df' in source
        assert 'balancesheet_df' in source
        assert 'cashflow_df' in source

    def test_dim7_preserves_ecm_fallback(self):
        """dim7保留ecm fallback"""
        import inspect

        from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine
        source = inspect.getsource(Dim7ValuationEngine._compute_valuation)
        assert 'ecm.get_cached_income' in source
        assert 'ecm.get_cached_balancesheet' in source
        assert 'ecm.get_cached_cashflow' in source
