"""446号：dim2 D4 起始包含对静默丢弃 单元测试

知识库《缠论走势结构量化系统配置指南》L41-42：
"是否跳过前两根K线包含……跳过可能导致起始位置识别不完整，建议不跳过"

缺陷：`_merge_once` 原实现 `result=[klines[0]]` + `direction is None` 守卫，
当起始两根 K 线存在包含关系时进入 is_contained 分支但 direction 为 None，
既不合并不 append → 起始包含对被静默丢弃。

修复：direction is None 且包含时先按锚定规则确定方向（与 else 分支一致），
再按该方向合并，消除静默丢弃。
"""
from app.engine.framework.chanlun_strategy import KLine, KLineMerger


def _k(idx, high, low, close=None, open_=None, vol=1.0):
    return KLine(idx=idx, open=open_ if open_ is not None else high,
                 high=high, low=low,
                 close=close if close is not None else high,
                 date=f'd{idx}', volume=vol)


class TestStartingContainmentMerge:
    """起始包含对不再静默丢弃，改为合并"""

    def test_first_two_contain_not_dropped(self):
        """起始两根包含 → 合并，不丢弃；结果长度 = 1（后续无新笔）"""
        k = [
            _k(0, high=10.0, low=8.0),   # 大
            _k(1, high=9.0, low=9.0),     # 被前一根包含（9<=10 且 9>=8）
        ]
        # current.high=9 < prev.high=10 → direction='down' → 取 min
        out = KLineMerger._merge_once(k)
        assert len(out) == 1, f"起始包含应合并为 1 根，实际 {len(out)}"
        assert out[0].high == 9.0, f"down 方向取 min 高，实际 {out[0].high}"
        assert out[0].low == 8.0, f"low 取 min，实际 {out[0].low}"

    def test_first_two_contain_up_merge_values(self):
        """起始两根包含（direction=up）→ max 高 max 低"""
        # prev(10,8) 被 cur(11,9) 包含（10<=11 且 8>=9? 否）→ 需 cur 包含 prev：
        # cur(11,9) 包含 prev(10,8) 需 prev.low>=cur.low? 8>=9 否 → 不包含
        # 真正'包含且上行'：cur 完全覆盖 prev 且 cur.high 更高
        #   prev(9,8), cur(10,8)：prev 完全包含于 cur（9<=10 且 8>=8），cur.high=10>9 → up
        k = [
            _k(0, high=9.0, low=8.0),
            _k(1, high=10.0, low=8.0),
        ]
        # 包含判断：cur(10,8) 包含 prev(9,8)？ 9<=10 T 且 8>=8 T → 包含成立
        out = KLineMerger._merge_once(k)
        assert len(out) == 1, f"起始包含应合并为 1 根，实际 {len(out)}"
        # direction=up → max 高 max 低
        assert out[0].high == 10.0, f"up 取 max 高，实际 {out[0].high}"
        assert out[0].low == 8.0, f"up 取 max 低，实际 {out[0].low}"

    def test_non_containing_start_unchanged(self):
        """起始两根不包含 → 行为不变（2 根均保留）"""
        k = [
            _k(0, high=10.0, low=8.0),
            _k(1, high=7.0, low=5.0),     # 不包含（7<8）
        ]
        out = KLineMerger._merge_once(k)
        assert len(out) == 2, f"不包含起始应保留 2 根，实际 {len(out)}"
        assert out[0].idx == 0 and out[1].idx == 1

    def test_single_kline_unchanged(self):
        """单根 K 线 → 原样返回"""
        k = [_k(0, high=10.0, low=8.0)]
        out = KLineMerger._merge_once(k)
        assert out == k

    def test_down_direction_contain_merges_min(self):
        """下行包含 → 取 min 高 min 低（高方向向下）"""
        k = [
            _k(0, high=11.0, low=10.5),
            _k(1, high=10.8, low=10.8),  # 10.8<=11 且 10.8>=10.5 → 被前一根包含
        ]
        # current.high=10.8 < prev.high=11 → direction='down' → 取 min
        out = KLineMerger._merge_once(k)
        assert len(out) == 1
        assert out[0].high == 10.8 and out[0].low == 10.5

    def test_contain_then_new_direction_kept(self):
        """起始包含合并后，后续不包含新笔正常 append"""
        k = [
            _k(0, high=11.0, low=10.0),
            _k(1, high=10.5, low=10.5),   # 起始包含 → down 合并
            _k(2, high=9.0, low=8.0),      # 不包含 → append
        ]
        out = KLineMerger._merge_once(k)
        assert len(out) == 2, f"起始包含合并 + 后续新笔 = 2，实际 {len(out)}"
        # 第一根为合并结果（down 合并，high=min(11,10.5)=10.5）
        assert out[0].high == 10.5 and out[0].low == 10.0
        assert out[1].idx == 2
