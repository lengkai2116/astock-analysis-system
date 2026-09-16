"""446号：dim2 D6 盘整背驰"离开中枢段"约束单元测试

知识库《缠论走势结构量化系统配置指南》L92：
"盘整中的假背驰：只有在离开中枢的段中出现的背驰才计入信号"

- 有中枢时：底背驰（回调段）须跌破中枢下沿；顶背驰（反弹段）须突破中枢上沿；
  仍在中枢内震荡的幅度放大 = 盘整内假背驰，不判 consolidation。
- 无中枢时：无约束，保留原幅度兜底逻辑。
"""
from app.engine.framework.chanlun_strategy import (
    DivergenceDetector,
    Stroke,
    Zhongshu,
)


def _mk_stroke(direction, sp, ep, start_idx=0, end_idx=5):
    return Stroke(start_idx=start_idx, end_idx=end_idx, start_price=sp, end_price=ep,
                  start_date='2026-01-01', end_date='2026-01-06', direction=direction,
                  high=max(sp, ep), low=min(sp, ep))


def _mk_zs(high, low):
    return Zhongshu(start_idx=0, end_idx=20, start_date='2026-01-01',
                    end_date='2026-01-31', high=high, low=low)


def _mk_detector():
    return DivergenceDetector(macd_algo='area')


class TestConsolidationExitConstraint:
    """D6：盘整背驰离开中枢段约束"""

    def test_bottom_divergence_breaks_lower_breakout(self):
        """底背驰：回调段跌破中枢下沿 → 计入信号（consolidation up）"""
        det = _mk_detector()
        zs = _mk_zs(high=12.0, low=10.0)
        strokes = [
            _mk_stroke('up', 10.0, 11.0, 0, 10),          # 反弹（中枢内）
            _mk_stroke('down', 11.0, 10.5, 10, 20),       # 小回调（中枢内）
            _mk_stroke('up', 10.5, 11.5, 20, 30),         # 反弹（中枢内）
            _mk_stroke('down', 11.5, 9.0, 30, 40),        # 跌破下沿 10.0 → 离开中枢下方
        ]
        # 最后笔 down 幅度 2.5，上一笔 up 幅度 1.0 → 2.5 > 1.0*1.1；已跌破下沿
        r = det._detect_consolidation_divergence(strokes, [zs])
        assert r is not None, "跌破中枢下沿的底背驰应计入"
        assert r.type == 'consolidation' and r.direction == 'up'
        assert r.details.get('exited_zhongshu') is True
        assert r.details.get('zhongshu') is not None

    def test_bottom_divergence_inside_zhongshu_false(self):
        """底背驰：仍在盘整区间内（未跌破下沿）→ 假背驰，不计入"""
        det = _mk_detector()
        zs = _mk_zs(high=12.0, low=10.0)
        strokes = [
            _mk_stroke('up', 10.0, 11.0, 0, 10),
            _mk_stroke('down', 11.0, 10.2, 10, 20),       # 小回调（未跌破 10.0）
            _mk_stroke('up', 10.2, 11.5, 20, 30),
            _mk_stroke('down', 11.5, 10.2, 30, 40),      # 终点 10.2 > 下沿 10.0 → 未跌破
        ]
        # 最后笔 down 幅度 1.3，上一笔 up 幅度 1.3 → 1.3 > 1.3*1.1=1.43? 不满足幅度
        # 调整：上一笔 up 幅度 0.8 以满足幅度 1.3 > 0.8*1.1=0.88，但仍未离开中枢
        strokes[2] = _mk_stroke('up', 10.2, 11.0, 20, 30)
        r = det._detect_consolidation_divergence(strokes, [zs])
        assert r is None, "未跌破中枢下沿的幅度放大是盘整内假背驰，不应计入"

    def test_top_divergence_breaks_upper_breakout(self):
        """顶背驰：反弹段突破中枢上沿 → 计入信号（consolidation down）"""
        det = _mk_detector()
        zs = _mk_zs(high=12.0, low=10.0)
        strokes = [
            _mk_stroke('down', 11.5, 10.5, 0, 10),
            _mk_stroke('up', 10.5, 11.0, 10, 20),
            _mk_stroke('down', 11.0, 10.2, 20, 30),
            _mk_stroke('up', 10.2, 13.5, 30, 40),       # 突破上沿 12.0 → 离开中枢上方
        ]
        # 最后笔 up 幅度 3.3，上一笔 down 幅度 0.8 → 3.3 > 0.8*1.1；已突破上沿
        r = det._detect_consolidation_divergence(strokes, [zs])
        assert r is not None, "突破中枢上沿的顶背驰应计入"
        assert r.type == 'consolidation' and r.direction == 'down'
        assert r.details.get('exited_zhongshu') is True

    def test_top_divergence_inside_zhongshu_false(self):
        """顶背驰：仍在盘整区间内（未突破上沿）→ 假背驰，不计入"""
        det = _mk_detector()
        zs = _mk_zs(high=12.0, low=10.0)
        strokes = [
            _mk_stroke('down', 11.5, 10.5, 0, 10),
            _mk_stroke('up', 10.5, 11.0, 10, 20),
            _mk_stroke('down', 11.0, 10.2, 20, 30),
            _mk_stroke('up', 10.2, 11.5, 30, 40),       # 终点 11.5 < 上沿 12.0 → 未突破
        ]
        # 最后笔 up 幅度 1.3，上一笔 down 幅度 0.8 → 1.3 > 0.8*1.1 满足幅度但未突破
        r = det._detect_consolidation_divergence(strokes, [zs])
        assert r is None, "未突破中枢上沿的幅度放大是盘整内假背驰，不应计入"

    def test_no_zhongshu_fallback_keeps_amplitude(self):
        """无中枢时保留原幅度逻辑（兜底不约束）"""
        det = _mk_detector()
        strokes = [
            _mk_stroke('down', 12.0, 11.0, 0, 10),
            _mk_stroke('up', 11.0, 11.5, 10, 20),
            _mk_stroke('down', 11.5, 10.5, 20, 30),
            _mk_stroke('up', 10.5, 11.0, 30, 40),
            _mk_stroke('down', 11.0, 9.0, 40, 50),      # 幅度 2.0 > prev up 0.5*1.1
        ]
        r = det._detect_consolidation_divergence(strokes, [])
        assert r is not None, "无中枢时保留幅度兜底逻辑"


class TestConsolidationExitHelper:
    """D6：_consolidation_exited_zhongshu"""

    def test_up_exit(self):
        det = _mk_detector()
        zs = _mk_zs(high=12.0, low=10.0)
        strokes = [_mk_stroke('up', 10.0, 13.0)]
        zs_out, direction = det._consolidation_exited_zhongshu(strokes, [zs])
        assert zs_out is zs and direction == 'up'

    def test_down_exit(self):
        det = _mk_detector()
        zs = _mk_zs(high=12.0, low=10.0)
        strokes = [_mk_stroke('down', 11.0, 9.0)]
        zs_out, direction = det._consolidation_exited_zhongshu(strokes, [zs])
        assert zs_out is zs and direction == 'down'

    def test_inside_no_exit(self):
        det = _mk_detector()
        zs = _mk_zs(high=12.0, low=10.0)
        strokes = [_mk_stroke('up', 10.0, 11.0)]
        zs_out, direction = det._consolidation_exited_zhongshu(strokes, [zs])
        assert zs_out is None and direction is None

    def test_no_zhongshu(self):
        det = _mk_detector()
        strokes = [_mk_stroke('up', 10.0, 13.0)]
        zs_out, direction = det._consolidation_exited_zhongshu(strokes, [])
        assert zs_out is None and direction is None
