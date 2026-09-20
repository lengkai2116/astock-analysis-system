"""466号：日线笔中枢切换 + BiZhongshuFinder 延展判定修复回归测试

覆盖：
1. 笔中枢形成：连续3笔重叠→中枢起点（中枢鉴别正确）
2. 延展判定（修复核心）：笔终点离开中枢区间、但整笔区间与中枢有交集→仍延伸；
   整笔完全离开中枢区间→闭合（对齐 czsc ZS.is_valid 整笔交集语义）
3. 新中枢产生：闭合后从离开笔开始检测新中枢
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

from app.engine.framework.chanlun_strategy import BiZhongshuFinder, Stroke


def _mk(direction, sp, ep, idx, date):
    """构造笔（含 high/low 与端点）。"""
    return Stroke(start_idx=idx, end_idx=idx + 5, start_price=sp, end_price=ep,
                  start_date=date, end_date=date, direction=direction,
                  high=max(sp, ep), low=min(sp, ep))


class TestBiZhongshuFinder:
    def test_three_overlap_forms_zs(self):
        """连续3笔重叠→形成笔中枢（中枢鉴别）。"""
        # s1 up:10->13, s2 down:13->11.5, s3 up:11.5->12.5 → 三笔重叠 [11.5, 12.5] 宽1.0>0.5
        strokes = [
            _mk('up', 10.0, 13.0, 0, '2026-01-01'),
            _mk('down', 13.0, 11.5, 5, '2026-01-08'),
            _mk('up', 11.5, 12.5, 10, '2026-01-15'),
        ]
        zs = BiZhongshuFinder().find(strokes)
        assert len(zs) == 1
        # 重叠区间：max(lows)=max(10,11.5,11.5)=11.5, min(highs)=min(13,13,12.5)=12.5
        assert abs(zs[0].low - 11.5) < 1e-9
        assert abs(zs[0].high - 12.5) < 1e-9
        assert zs[0].type == 'bi_zhongshu'

    def test_point_exit_but_segment_overlap_still_extends(self):
        """修复核心：笔终点已离开中枢上沿、但整笔区间仍与中枢有交集→仍延伸（不闭合）。"""
        # 中枢由前3笔构成 [11.5, 12.5]
        base = [
            _mk('up', 10.0, 12.5, 0, '2026-01-01'),    # 参与3笔重叠下沿计算
            _mk('down', 12.5, 11.5, 5, '2026-01-08'),
            _mk('up', 11.5, 12.3, 10, '2026-01-15'),   # 中枢上沿=min(high)=min(12.5,12.5,12.3)=12.3
        ]
        # 第4笔：up 12.0->12.8，终点 12.8 已>上沿12.3（单点判离开），但整笔区间[12.0,12.8]
        # 与中枢[?,12.3]有交集（12.0~12.3重叠）→ 旧实现会闭合，新实现应延伸
        extending = [_mk('up', 12.0, 12.8, 15, '2026-01-20')]
        zs = BiZhongshuFinder().find(base + extending)
        assert len(zs) == 1
        assert zs[0].end_idx == extending[0].end_idx, "整笔仍有交集→应延伸不闭合"
        assert zs[0].end_date == extending[0].end_date

    def test_fully_detached_closes(self):
        """整笔区间完全离开中枢上沿之下/之上→闭合（新中枢产生）。"""
        base = [
            _mk('up', 10.0, 12.3, 0, '2026-01-01'),
            _mk('down', 12.3, 11.5, 5, '2026-01-08'),
            _mk('up', 11.5, 12.2, 10, '2026-01-15'),   # 中枢 [11.5, 12.2]
        ]
        # 第4笔跌破下沿 10.5->8.0，整笔区间[8.0,10.5]完全位于中枢下沿11.5之下 → 闭合
        detach = [_mk('down', 10.5, 8.0, 15, '2026-01-20')]
        zs = BiZhongshuFinder().find(base + detach)
        assert len(zs) == 1
        assert zs[0].end_idx == base[-1].end_idx, "离开笔不并入→中枢以第3笔结束"
        assert zs[0].end_date == base[-1].end_date
        # 但该离开笔仍会参与后续新中枢检测（find 从 j 继续）——此处仅验证闭合行为
        assert zs[0].high == pytest.approx(12.2)

    def test_new_zs_after_detach(self):
        """闭合后从离开笔开始检测新中枢（新中枢产生）。"""
        # 段1：中枢A（3笔重叠），然后大幅上涨离开（整笔低于或高于）
        seg1 = [
            _mk('up', 10.0, 12.0, 0, '2026-01-01'),
            _mk('down', 12.0, 11.0, 5, '2026-01-08'),
            _mk('up', 11.0, 12.2, 10, '2026-01-15'),   # 中枢A [11.0, 12.0]
        ]
        # 第4-6笔大幅上探离开→再落回高位形成中枢B（价格抬升，新中枢）
        seg2 = [
            _mk('up', 12.2, 16.0, 15, '2026-01-20'),   # 整笔在中枢A上方→闭合A
            _mk('down', 16.0, 15.0, 20, '2026-01-25'),
            _mk('up', 15.0, 16.2, 25, '2026-01-30'),
        ]
        zs = BiZhongshuFinder().find(seg1 + seg2)
        assert len(zs) >= 2, "应有新旧两个中枢"
        # 第二中枢上沿上移（>第一中枢上沿），符合"中枢上移"
        assert zs[1].high > zs[0].high

    def test_insufficient_strokes_no_zs(self):
        assert BiZhongshuFinder().find([]) == []
        assert BiZhongshuFinder().find([_mk('up', 1, 2, 0, '2026-01-01')]) == []
