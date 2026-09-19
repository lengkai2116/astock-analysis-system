"""446号：dim2 趋势判定修正（D1+D2）单元测试

- 方案C：价格 vs 中枢为主判据，中枢序列为内部时的辅助，无中枢兜底最后笔/段
- D2：线段中枢优先（bi_zs_mode=False）+ 段不足自动回退笔中枢
"""
import numpy as np
import pandas as pd

from app.engine.framework.chanlun_strategy import (
    ChanlunAnalyzer,
    KLine,
    Segment,
    Stroke,
    Zhongshu,
)


def _mk_analyzer(bi_zs_mode=False):
    return ChanlunAnalyzer({'bi_zs_mode': bi_zs_mode})


def _mk_zs(high, low):
    return Zhongshu(start_idx=0, end_idx=10, start_date='2026-01-01',
                    end_date='2026-01-31', high=high, low=low)


def _mk_stroke(direction, sp=1.0, ep=1.1):
    return Stroke(start_idx=0, end_idx=5, start_price=sp, end_price=ep,
                  start_date='2026-01-01', end_date='2026-01-06', direction=direction,
                  high=max(sp, ep), low=min(sp, ep))


def _mk_segment(direction, sp=1.0, ep=1.1):
    return Segment(start_idx=0, end_idx=5, start_price=sp, end_price=ep,
                   start_date='2026-01-01', end_date='2026-01-06', direction=direction)


def _mk_kline(close):
    return KLine(idx=0, open=close, high=close, low=close, close=close,
                 date='2026-01-31', volume=1000)


class TestTrendZhongshu:
    """方案 C：价格 vs 中枢主判据"""

    def test_price_above_upper_bound_up(self):
        """场景1：价格突破中枢上沿（即使最后笔向下）→ up（D1 矛盾消除）"""
        a = _mk_analyzer()
        a.zhongshu_list = [_mk_zs(high=5.0, low=4.0)]
        a.strokes = [_mk_stroke('down', sp=6.0, ep=5.5)]  # 最后笔向下
        a.klines = [_mk_kline(close=5.5)]  # 价格 > 上沿 5.0
        assert a._determine_trend() == 'up'
        assert a._determine_trend_basis() == '价格突破中枢上沿'

    def test_price_below_lower_bound_down(self):
        a = _mk_analyzer()
        a.zhongshu_list = [_mk_zs(high=5.0, low=4.0)]
        a.klines = [_mk_kline(close=3.5)]
        assert a._determine_trend() == 'down'
        assert a._determine_trend_basis() == '价格跌破中枢下沿'

    def test_inside_2zs_seq_up(self):
        """场景2：价格在中枢内部 + 中枢序列上移 → up"""
        a = _mk_analyzer()
        a.zhongshu_list = [_mk_zs(high=4.5, low=4.0), _mk_zs(high=6.0, low=5.5)]
        a.klines = [_mk_kline(close=5.7)]  # 在最后中枢 5.5-6.0 内部
        assert a._determine_trend() == 'up'
        assert a._determine_trend_basis() == '价格在中枢内部-中枢上移'

    def test_inside_2zs_seq_down(self):
        """场景3：价格在中枢内部 + 中枢序列下移 → down"""
        a = _mk_analyzer()
        a.zhongshu_list = [_mk_zs(high=6.0, low=5.5), _mk_zs(high=4.5, low=4.0)]
        a.klines = [_mk_kline(close=4.2)]  # 在最后中枢 4.0-4.5 内部
        assert a._determine_trend() == 'down'
        assert a._determine_trend_basis() == '价格在中枢内部-中枢下移'

    def test_inside_1zs_unknown(self):
        a = _mk_analyzer()
        a.zhongshu_list = [_mk_zs(high=5.0, low=4.0)]
        a.klines = [_mk_kline(close=4.5)]
        assert a._determine_trend() == 'unknown'
        assert a._determine_trend_basis() == '价格在中枢内部'

    def test_no_zs_fallback_stroke(self):
        """场景4：无中枢（笔中枢模式）→ 兜底最后笔方向"""
        a = _mk_analyzer(bi_zs_mode=True)
        a.zhongshu_list = []
        a.strokes = [_mk_stroke('up')]
        a.klines = [_mk_kline(close=1.05)]
        assert a._determine_trend() == 'up'
        assert a._determine_trend_basis() == '无中枢-最近3笔方向'

    def test_no_zs_fallback_segment(self):
        """场景4b：线段模式无中枢 → 兜底最近3段方向"""
        a = _mk_analyzer(bi_zs_mode=False)
        a.zhongshu_list = []
        a.segments = [_mk_segment('up')]
        assert a._determine_trend() == 'up'
        assert a._determine_trend_basis() == '无中枢-最近3段方向'

    def test_trend_basis_in_result(self):
        """场景5：analyze 结果含 trend_basis 输出"""
        a = _mk_analyzer()
        a.zhongshu_list = [_mk_zs(high=5.0, low=4.0)]
        a.klines = [_mk_kline(close=5.5)]
        # 补齐 _generate_result 引用的其余属性（未走 analyze 全流程）
        a.fractals = []
        a.segments = []
        a.divergence = None
        a.buy_points = []
        a.sell_points = []
        a.theorem_check = None
        a.factor_position = 'none'
        a.factor_weight_adj = 1.0
        a.selected_factors = {'factors': [], 'strategy': '无中枢'}
        a.pending_judgment = None
        res = a._generate_result()
        assert res['trend'] == 'up'
        assert res['trend_basis'] == '价格突破中枢上沿'


class TestSegmentFallback:
    """D2：线段中枢优先 + 段不足自动回退笔中枢（analyze 全流程不崩）"""

    def test_segment_mode_analyze_not_crash(self):
        """线段中枢模式全流程：成功构建（段足）或安全回退/报错，不抛异常"""
        n = 60
        closes = np.linspace(10, 12, n)
        df = pd.DataFrame({
            'open': closes, 'high': closes * 1.01, 'low': closes * 0.99,
            'close': closes, 'volume': np.full(n, 10000.0),
            'trade_date': pd.date_range('2026-01-01', periods=n, freq='D').astype(str),
        })
        a = ChanlunAnalyzer({'bi_zs_mode': False})
        res = a.analyze(df)
        assert isinstance(res, dict)
        assert 'trend' in res or 'error' in res

    def test_segment_short_data_fallback(self):
        """线段模式数据不足时安全返回（回退或数据不足错误），不抛异常"""
        n = 32
        closes = np.linspace(10, 10.3, n)
        df = pd.DataFrame({
            'open': closes, 'high': closes * 1.005, 'low': closes * 0.995,
            'close': closes, 'volume': np.full(n, 10000.0),
            'trade_date': pd.date_range('2026-01-01', periods=n, freq='D').astype(str),
        })
        a = ChanlunAnalyzer({'bi_zs_mode': False})
        res = a.analyze(df)
        assert isinstance(res, dict)
