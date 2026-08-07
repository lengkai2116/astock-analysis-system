"""317号 S3 回归测试：快照 items 应透出 style_exposure/catalyst_event 标签

背景：机会图谱三地图筛选按钮（高成长/白马股/有催化剂）依赖 style_exposure 与
catalyst_event 两个标签，但 treemap_snapshot 表无此列、get_treemap_snapshot_items
组装时未从 opportunity_tags_cache 补齐，导致前端内存过滤命中数为 0。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def _sample_ts_codes(ecm, n=10):
    """从快照表取 n 只股票代码（优先选有 style_exposure 标签的）"""
    rows = ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM opportunity_tags_cache "
        "WHERE tag_name='style_exposure' AND tag_value='large_growth' LIMIT ?", [n]
    ).fetchall()
    codes = [r[0] for r in rows]
    if len(codes) < n:
        rows2 = ecm.conn.execute(
            "SELECT ts_code FROM treemap_snapshot LIMIT ?", [n - len(codes)]
        ).fetchall()
        codes += [r[0] for r in rows2]
    return codes


def test_snapshot_items_expose_style_exposure(ecm):
    """快照 items 的 tags 字典应包含 style_exposure（修复前缺失）"""
    codes = _sample_ts_codes(ecm)
    assert codes, "标签库应有数据"
    items = ecm.get_treemap_snapshot_items(codes)
    assert items, "快照应有数据"
    with_style = [i for i in items if i.get('tags', {}).get('style_exposure')]
    assert with_style, "至少应有股票透出 style_exposure 标签（修复前全部缺失）"


def test_snapshot_items_expose_catalyst_event(ecm):
    """快照 items 的 tags 字典应包含 catalyst_event（修复前缺失）"""
    codes = _sample_ts_codes(ecm)
    items = ecm.get_treemap_snapshot_items(codes)
    assert items
    with_cat = [i for i in items if i.get('tags', {}).get('catalyst_event')]
    assert with_cat, "至少应有股票透出 catalyst_event 标签（修复前全部缺失）"


def test_snapshot_style_exposure_matches_tag_db(ecm):
    """透出的 style_exposure 值应与标签库一致（数据真实）"""
    codes = _sample_ts_codes(ecm, 3)
    items = ecm.get_treemap_snapshot_items(codes)
    for item in items:
        ts = item['ts_code']
        rows = ecm.conn.execute(
            "SELECT tag_value FROM opportunity_tags_cache "
            "WHERE ts_code=? AND tag_name='style_exposure' ORDER BY updated_at DESC LIMIT 1",
            [ts]
        ).fetchall()
        if rows:
            assert item.get('tags', {}).get('style_exposure') == rows[0][0], \
                f"{ts} style_exposure 与标签库不一致"


# ============================================================
# 318号 S5：快照 items 应透出 pe_percentile_5y / pb_percentile_5y（估值举证）
# ============================================================

def test_snapshot_items_expose_pe_pb_percentile(ecm):
    """快照 items 的 tags 字典应包含 pe_percentile_5y/pb_percentile_5y（修复前缺失）"""
    rows = ecm.conn.execute(
        "SELECT ts_code FROM opportunity_tags_cache "
        "WHERE tag_name='pe_percentile_5y' LIMIT 5"
    ).fetchall()
    assert rows, "标签库应有 pe_percentile_5y 数据"
    codes = [r[0] for r in rows]
    items = ecm.get_treemap_snapshot_items(codes)
    assert items
    with_pe = [i for i in items if i.get('tags', {}).get('pe_percentile_5y') is not None]
    assert with_pe, "至少应有股票透出 pe_percentile_5y（修复前全部缺失）"
    with_pb = [i for i in items if i.get('tags', {}).get('pb_percentile_5y') is not None]
    assert with_pb, "至少应有股票透出 pb_percentile_5y（修复前全部缺失）"


def test_snapshot_pe_percentile_matches_tag_db(ecm):
    """透出的 pe_percentile_5y 值应与标签库一致（数据真实）"""
    rows = ecm.conn.execute(
        "SELECT ts_code FROM opportunity_tags_cache "
        "WHERE tag_name='pe_percentile_5y' LIMIT 3"
    ).fetchall()
    codes = [r[0] for r in rows]
    items = ecm.get_treemap_snapshot_items(codes)
    for item in items:
        ts = item['ts_code']
        db = ecm.conn.execute(
            "SELECT tag_value FROM opportunity_tags_cache WHERE ts_code=? "
            "AND tag_name='pe_percentile_5y' ORDER BY updated_at DESC LIMIT 1", [ts]
        ).fetchone()
        if db:
            assert item.get('tags', {}).get('pe_percentile_5y') == db[0], \
                f"{ts} pe_percentile_5y 与标签库不一致"
