"""521号 O4 — 龙虎榜席位明细补采判据（与主表 lhb_cache 当日股票数对齐）

背景：10-13/10-14 席位明细严重缺失（45 行/5~7 只 vs 主表 62/68 只）。根因：
完整性检查旧判据 `detail_cnt == 0` 才补采——18:00 巡检补采时 Tushare top_inst
仅发布部分数据（80/60 条落库 45 行），非 0 即视为「✅ 已通过」，后续巡检永不重补；
而 top_inst（席位）发布时间晚于 top_list（主表），10-12 正常日也是 18:00 补 0 条
→ 18:57 二次补 829 条才全量（幸运多触发一次）。修复：判据改为「明细覆盖股票数
< 主表上榜股票数即补采」（覆盖式写入幂等，整点巡检天然重试直至对齐）。
"""
from data_daemon import _lhb_detail_backfill_needed


def test_main_empty_returns_false():
    """主表当日为空（源未发布）→ 不补采（由调用方跳过）"""
    assert _lhb_detail_backfill_needed(0, 0) is False
    assert _lhb_detail_backfill_needed(0, 5) is False


def test_detail_less_than_main_returns_true():
    """明细覆盖股票数 < 主表上榜股票数 → 需补采（10-13/10-14 实证：7/5 vs 62/68）"""
    assert _lhb_detail_backfill_needed(62, 7) is True
    assert _lhb_detail_backfill_needed(68, 5) is True


def test_aligned_returns_false():
    """明细覆盖股票数 == 主表上榜股票数 → 已对齐，不补采"""
    assert _lhb_detail_backfill_needed(62, 62) is False
    assert _lhb_detail_backfill_needed(68, 68) is False


def test_detail_more_than_main_returns_false():
    """明细覆盖多于主表（源侧超额）→ 不补采"""
    assert _lhb_detail_backfill_needed(62, 70) is False
