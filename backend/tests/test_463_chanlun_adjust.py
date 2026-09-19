"""463号：缠论复权口径 + 中枢选用/级别修复回归测试

- _apply_adjust_factor 复权语义（hfq=后复权历史连续 / qfq=前复权最新价=实际价）
- _select_current_zhongshu 有效中枢选用（级别>6月跳过 / 失效跳过 / 正常返回）
- _determine_trend 用有效中枢（无有效中枢→最后段兜底）
- dim2 _assess_vs_zhongshu 中枢展示换算 + 无有效中枢文案
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest

from app.data import DataManager
from app.engine.framework.chanlun_strategy import (
    KLine, Zhongshu, _select_current_zhongshu,
)
from app.opportunity_atlas.dimensions.dim2_structure_engine import _assess_vs_zhongshu


def _mk_zs(start, end, low, high):
    """构造 Zhongshu（日期 str，跨度由 start/end 决定）"""
    return Zhongshu(start_idx=0, end_idx=10, start_date=start, end_date=end,
                    high=high, low=low, direction='up', level='daily')


# ═══════════════════════════════════════════════════════════
# 1. _apply_adjust_factor 复权语义（463号修复：hfq/qfq 标注反转）
# ═══════════════════════════════════════════════════════════

class TestAdjustFactorSemantics:
    """hfq=后复权（历史连续、最新价≠实际价）；qfq=前复权（最新价=实际价）"""

    def _mk_dm(self, monkeypatch):
        # 构造原始 df（未复权价）+ adj_factor 表
        df = pd.DataFrame({
            'ts_code': ['000001.SZ'] * 3,
            'trade_date': ['2026-08-01', '2026-08-08', '2026-08-15'],
            'open': [10.0, 11.0, 12.0],
            'high': [10.5, 11.5, 12.5],
            'low': [9.5, 10.5, 11.5],
            'close': [10.0, 11.0, 12.0],
            'vol': [1000.0, 1000.0, 1000.0],
            'amount': [10000.0, 11000.0, 12000.0],
            'pct_chg': [0.0, 0.1, 0.1],
        })
        adj = pd.DataFrame({
            'trade_date': ['2026-08-01', '2026-08-08', '2026-08-15'],
            'adj_factor': [1.5, 1.5, 1.5],  # 恒定因子 1.5（简单场景）
        })
        dm = object.__new__(DataManager)
        dm.cache = type('_C', (), {'get_cached_adj_factor': lambda self, c: adj})()
        return dm, df

    def test_hfq_is_latest_equal_raw_ratio(self):
        # 恒定因子 1.5 下 hfq 应整体缩放、最新价≠原始价（后复权历史连续）
        from app.data import DataManager as DM
        dm = object.__new__(DM)
        df = pd.DataFrame({
            'ts_code': ['000001.SZ'] * 2,
            'trade_date': ['2026-08-01', '2026-08-15'],
            'open': [10.0, 12.0], 'high': [10.5, 12.5], 'low': [9.5, 11.5],
            'close': [10.0, 12.0], 'vol': [1000.0, 1000.0],
        })
        adj = pd.DataFrame({'trade_date': ['2026-08-01', '2026-08-15'],
                            'adj_factor': [1.0, 1.5]})
        dm.cache = type('_C', (), {'get_cached_adj_factor': lambda self, c: adj})()
        # hfq：base=最早因子(1.0) → 最新价 = 12*1.5 = 18（≠原始12）
        out = dm._apply_adjust_factor(df, 'hfq')
        assert abs(out['close'].iloc[-1] - 18.0) < 1e-6
        # qfq：base=最新因子(1.5) → 最新价 = 12*1 = 12（=原始实际价）
        out2 = dm._apply_adjust_factor(df, 'qfq')
        assert abs(out2['close'].iloc[-1] - 12.0) < 1e-6


# ═══════════════════════════════════════════════════════════
# 2. _select_current_zhongshu 有效中枢选用
# ═══════════════════════════════════════════════════════════

class TestSelectCurrentZhongshu:

    def test_empty(self):
        assert _select_current_zhongshu([]) is None
        assert _select_current_zhongshu(None) is None

    def test_recent_valid(self):
        # 最近中枢 end_date 距当前 1 个月内 → 有效返回
        last = datetime(2026, 9, 17)
        zs = _mk_zs('2026-07-01', '2026-08-20', 5.0, 8.0)
        klines = [KLine(idx=0, open=1, high=1, low=1, close=1, date=last.strftime('%Y-%m-%d'))]
        assert _select_current_zhongshu([zs], klines) is zs

    def test_stale_zhongshu_skipped(self):
        # 中枢 end_date 距今 >6 个月 → 失效跳过 → None
        zs = _mk_zs('2025-01-01', '2025-03-01', 19.0, 23.0)  # 2021 旧中枢（000002 场景）
        klines = [KLine(idx=0, open=1, high=1, low=1, close=1, date='2026-09-17')]
        assert _select_current_zhongshu([zs], klines) is None

    def test_overlong_span_still_valid_if_recent(self):
        # 跨度 >6 个月（周线级横盘）但 end_date 距今 <6 个月 → 仍作为当前参考中枢返回
        # （识别层保留巨型延伸中枢，选用层以"时效"为主；000001 三年横盘场景）
        zs = _mk_zs('2025-01-01', '2026-07-01', 10.0, 15.0)  # 跨度 18 个月
        klines = [KLine(idx=0, open=1, high=1, low=1, close=12.0, date='2026-09-17')]
        assert _select_current_zhongshu([zs], klines) is zs

    def test_prefers_latest_valid(self):
        # 多个中枢：从后向前选最近有效（旧失效跳过、新有效返回）
        stale = _mk_zs('2025-01-01', '2025-03-01', 19.0, 23.0)
        recent = _mk_zs('2026-07-01', '2026-08-20', 5.0, 8.0)
        klines = [KLine(idx=0, open=1, high=1, low=1, close=1, date='2026-09-17')]
        assert _select_current_zhongshu([stale, recent], klines) is recent


# ═══════════════════════════════════════════════════════════
# 3. _determine_trend 用有效中枢（无有效中枢→最后段兜底）
# ═══════════════════════════════════════════════════════════

class TestDetermineTrendEffectiveZs:

    def _analyzer(self, zs_list, klines, segments=None, bi_zs_mode=False):
        from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
        a = object.__new__(ChanlunAnalyzer)
        a.zhongshu_list = zs_list
        a.klines = klines
        a.segments = segments or []
        a.bi_zs_mode = bi_zs_mode
        a.strokes = []
        return a

    def test_stale_zs_falls_back_to_segment(self):
        # 旧中枢失效 + 价格不在中枢区间内 → 近3段方向多数兜底
        stale = _mk_zs('2025-01-01', '2025-03-01', 19.0, 23.0)
        klines = [KLine(idx=0, open=1, high=1, low=1, close=3.0, date='2026-09-17')]
        seg = type('_S', (), {'direction': 'down'})()
        a = self._analyzer([stale], klines, segments=[seg])
        assert a._determine_trend() == 'down'
        assert a._determine_trend_basis() == '无中枢-最近3段方向'

    def test_long_term_sideways_consolidation(self):
        # 463优化2：长期横盘——旧中枢失效但价格仍在其区间内 → 判盘整（非趋势化）
        stale = _mk_zs('2025-01-01', '2025-03-01', 10.0, 15.0)  # 000001 场景
        klines = [KLine(idx=0, open=1, high=1, low=1, close=12.0, date='2026-09-17')]
        seg = type('_S', (), {'direction': 'down'})()  # 段方向向下（横盘内波动）
        a = self._analyzer([stale], klines, segments=[seg])
        assert a._determine_trend() == 'unknown'  # 价格仍在历史中枢区间 → 盘整
        assert a._determine_trend_basis() == '价格仍在历史中枢区间（长期横盘）'

    def test_price_range_sideways(self):
        # 463优化2强化：无中枢且中枢不含现价，但价格近3年区间中部震荡（000001 0.3% 场景）
        # 构造 100 根 KLine：价格在 10~15 震荡（近3年区间），近1年 11~13 未突破，现价 12
        klines = []
        import math
        for i in range(100):
            close = 12.0 + 2.0 * math.sin(i / 8.0)  # 10~14 震荡
            klines.append(KLine(idx=i, open=close, high=close + 0.5, low=close - 0.5,
                                close=close, date='2026-01-01'))
        klines[-1] = KLine(idx=99, open=12.0, high=12.2, low=11.8, close=12.0, date='2026-09-17')
        # 中枢不含现价（区间 5~8）
        zs_away = _mk_zs('2025-01-01', '2025-03-01', 5.0, 8.0)
        a = self._analyzer([zs_away], klines, segments=[])
        assert a._determine_trend() == 'unknown'  # 价格区间横盘 → 盘整
        assert '近3年区间中部震荡' in a._determine_trend_basis()

    def test_price_range_not_sideways(self):
        # 价格在近3年区间底部（持续新低）→ 非横盘 → 近3段方向兜底
        klines = []
        import math
        for i in range(100):
            close = 10.0 - i * 0.06  # 10 → 4 持续下跌（创新低）
            klines.append(KLine(idx=i, open=close, high=close + 0.3, low=close - 0.3,
                                close=close, date='2026-01-01'))
        zs_away = _mk_zs('2025-01-01', '2025-03-01', 15.0, 18.0)
        seg = type('_S', (), {'direction': 'down'})()
        a = self._analyzer([zs_away], klines, segments=[seg])
        assert a._determine_trend() == 'down'  # 价格在区间底部（非横盘）→ 段方向

    def test_valid_zs_above_up(self):
        zs = _mk_zs('2026-07-01', '2026-08-20', 5.0, 8.0)
        klines = [KLine(idx=0, open=1, high=1, low=1, close=9.0, date='2026-09-17')]
        a = self._analyzer([zs], klines)
        assert a._determine_trend() == 'up'
        assert '突破中枢上沿' in a._determine_trend_basis()

    def test_valid_zs_below_down(self):
        zs = _mk_zs('2026-07-01', '2026-08-20', 5.0, 8.0)
        klines = [KLine(idx=0, open=1, high=1, low=1, close=4.0, date='2026-09-17')]
        a = self._analyzer([zs], klines)
        assert a._determine_trend() == 'down'


# ═══════════════════════════════════════════════════════════
# 4. dim2 _assess_vs_zhongshu 中枢展示换算 + 无有效中枢
# ═══════════════════════════════════════════════════════════

class TestAssessVsZhongshu:

    def test_valid_zhongshu_above_with_time_label(self):
        # 有效中枢（end_date 距今 <6 个月）→ 判定 + 中枢时间标注（前复权口径展示=实际价）
        recent = _mk_zs('2026-08-01', '2026-09-01', 19.0, 23.0)
        r = _assess_vs_zhongshu({}, {}, {'zhongshu': [recent]}, latest_close=30.0,
                                last_date='2026-09-17')
        assert r['position'] == '上方'
        assert '2.30' not in r['detail']  # 无 scale 换算，直接展示实际价
        assert '23.00' in r['detail']
        assert '中枢2026-08-01~2026-09-01' in r['detail']  # 中枢时间标注

    def test_no_valid_zhongshu(self):
        # 旧中枢失效（end_date 距今 >6 个月）→ 无有效中枢文案（不再拿旧中枢伪对比）
        stale = _mk_zs('2025-01-01', '2025-03-01', 19.0, 23.0)
        r = _assess_vs_zhongshu({}, {}, {'zhongshu': [stale]}, latest_close=3.0,
                                last_date='2026-09-17')
        assert r['position'] == '无有效中枢'
        assert '趋势延续' in r['detail']
