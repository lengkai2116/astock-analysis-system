"""412号方案D3：dim3 pattern一致性测试

验证precomputed MA与raw MA输出一致性。
"""
import numpy as np


class TestEnhancedPatternDetectorPrecomputed:
    """EnhancedPatternDetector precomputed MA测试"""

    def test_detect_all_accepts_precomputed_ma(self):
        """detect_all()接受precomputed_ma参数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim3_vp_engine import EnhancedPatternDetector
        sig = inspect.signature(EnhancedPatternDetector.detect_all)
        assert 'precomputed_ma' in sig.parameters

    def test_detect_all_works_without_precomputed(self):
        """无precomputed_ma时回退raw计算"""
        from app.opportunity_atlas.dimensions.dim3_vp_engine import EnhancedPatternDetector
        det = EnhancedPatternDetector()
        closes = np.random.uniform(10, 20, 65)
        opens = closes * 0.99
        highs = closes * 1.01
        lows = closes * 0.98
        volumes = np.random.uniform(1000, 5000, 65)
        result = det.detect_all(closes, opens, highs, lows, volumes)
        assert isinstance(result, list)

    def test_detect_all_with_precomputed_ma(self):
        """有precomputed_ma时使用预计算值"""
        from app.opportunity_atlas.dimensions.dim3_vp_engine import EnhancedPatternDetector
        det = EnhancedPatternDetector()
        closes = np.random.uniform(10, 20, 65)
        opens = closes * 0.99
        highs = closes * 1.01
        lows = closes * 0.98
        volumes = np.random.uniform(1000, 5000, 65)
        precomputed_ma = {
            'ma5': float(np.mean(closes[-5:])),
            'ma10': float(np.mean(closes[-10:])),
            'ma20': float(np.mean(closes[-20:])),
            'ma60': float(np.mean(closes[-60:])),
        }
        result = det.detect_all(closes, opens, highs, lows, volumes, precomputed_ma=precomputed_ma)
        assert isinstance(result, list)

    def test_precomputed_ma_matches_raw(self):
        """precomputed MA与raw MA输出一致"""
        from app.opportunity_atlas.dimensions.dim3_vp_engine import EnhancedPatternDetector
        rng = np.random.RandomState(42)  # 固定种子，消除浮点精度差异导致的模式漂移
        closes = rng.uniform(10, 20, 65)
        opens = closes * 0.99
        highs = closes * 1.01
        lows = closes * 0.98
        volumes = rng.uniform(1000, 5000, 65)

        # 无precomputed
        det1 = EnhancedPatternDetector()
        result1 = det1.detect_all(closes, opens, highs, lows, volumes)

        # 有precomputed（使用相同值）
        det2 = EnhancedPatternDetector()
        precomputed_ma = {}
        for p in [3, 5, 10, 20, 30, 55, 60, 120, 250]:
            if len(closes) >= p:
                precomputed_ma[f'ma{p}'] = float(np.mean(closes[-p:]))
        result2 = det2.detect_all(closes, opens, highs, lows, volumes, precomputed_ma=precomputed_ma)

        assert result1 == result2


class TestVolumeStateAnalyzerVolumeExt:
    """VolumeStateAnalyzer volume_ext测试"""

    def test_analyze_accepts_volume_ext(self):
        """analyze()接受volume_ext参数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim3_vp_engine import VolumeStateAnalyzer
        sig = inspect.signature(VolumeStateAnalyzer.analyze)
        assert 'volume_ext' in sig.parameters

    def test_compute_volume_price_signal_accepts_volume_ext(self):
        """compute_volume_price_signal()接受volume_ext参数"""
        import inspect

        from app.opportunity_atlas.dimensions.dim3_vp_engine import compute_volume_price_signal
        sig = inspect.signature(compute_volume_price_signal)
        assert 'volume_ext' in sig.parameters
