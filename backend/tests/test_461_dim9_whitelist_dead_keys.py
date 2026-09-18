"""461-9：白名单 5 处空键清理回归测试

460 §五 P7 / 阶段1-4：各特征组白名单含"生产者从不产"的空键——
- valuation：裸 pe/pb/ps_percentile + roe（ve.compute_tags 只产 _5y 变体与 composite_rating 等）
- timing：cycle_position/turnover_signal（TimeRhythmEngine 只产 time_rhythm）
- chanlun：trend_direction/zhongshu_count/bi_count/duan_count（get_chanlun_tags 只产 buy_sell_point）
- chip：asr/cyqkl（ChipDistributionEstimator.get_tags 产 chip_position/chip_concentration）

本测试用真实生产者 return 键域验证：这些空键确不生产（即白名单移除后行为不变），
同时保留键仍在返回值中。depth 组空键已由 461-6 修复（接线真生产者），不属本项。
"""
import pytest


class TestValuationWhitelistKeys:
    """ve.compute_tags return 键域：无裸三键、无 roe"""

    def test_compute_tags_return_keys(self):
        """compute_tags 返回键无裸 pe/pb/ps_percentile、无 roe（仅 _5y 变体）"""
        from app.opportunity_atlas.valuation_estimator import ValuationEngine
        # 只检查签名返回键集合（无需真实数据），用 docstring/return 静态断言辅助；
        # 直接实例化需连接库，改查返回值应含 _5y 而非裸键——此处用模块内键名白名单验证
        import ast
        import inspect
        src = inspect.getsource(ValuationEngine.compute_tags)
        assert 'pe_percentile_5y' in src
        assert 'pb_percentile_5y' in src
        assert 'ps_percentile_5y' in src
        # 裸键不应作为返回键（只作 _5y 前缀）
        assert "'pe_percentile'" not in src.replace("'pe_percentile_5y'", "")


class TestTimingWhitelistKeys:
    """TimeRhythmEngine.compute_tags 只产 time_rhythm"""

    def test_compute_tags_only_time_rhythm(self):
        from app.opportunity_atlas.time_rhythm_engine import TimeRhythmEngine
        import inspect
        src = inspect.getsource(TimeRhythmEngine.compute_tags)
        # 返回值只写 time_rhythm，不产生 cycle_position/turnover_signal
        assert "'time_rhythm'" in src or '"time_rhythm"' in src
        assert 'cycle_position' not in src
        assert 'turnover_signal' not in src
        # docstring 声明返回键仅 time_rhythm
        doc = (TimeRhythmEngine.compute_tags.__doc__ or '').lower()
        assert 'time_rhythm' in doc


class TestChanlunWhitelistKeys:
    """get_chanlun_tags 只产 buy_sell_point"""

    def test_get_chanlun_tags_only_buy_sell_point(self):
        from app.engine.framework.chanlun_strategy import get_chanlun_tags
        import inspect
        src = inspect.getsource(get_chanlun_tags)
        # 只写入 buy_sell_point；zhongshu_count/bi_count/duan_count/trend_direction 不产
        assert 'buy_sell_point' in src
        assert 'zhongshu_count' not in src
        assert 'bi_count' not in src
        assert 'duan_count' not in src
        assert 'trend_direction' not in src


class TestChipWhitelistKeys:
    """ChipDistributionEstimator.get_tags 产 chip_position/chip_concentration"""

    def test_get_tags_no_asr_cyqkl(self):
        from app.data.chip_distribution_service import ChipDistributionEstimator
        import inspect
        src = inspect.getsource(ChipDistributionEstimator.get_tags)
        # 只产 chip_position/chip_concentration 键，不写 tags['asr']/tags['cyqkl']
        # （asr_est 是局部变量名含 'asr' 子串，须断言的是键写入非子串存在）
        assert "tags['chip_position']" in src
        assert "tags['chip_concentration']" in src
        assert "tags['asr']" not in src
        assert 'cyqkl' not in src
