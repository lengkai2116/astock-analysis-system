"""321号 S4 测试：快照/API 透出 opportunity_state/state_evidence

背景：S1-S3 已实现跨维仲裁并写入标签表（opportunity_state/state_evidence）。
S4 将两字段透出到消费链：treemap_snapshot 快照表（建表/查询/INSERT）+
get_treemap_snapshot_items（API 读取）+ /treemap API 响应。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest  # noqa: E402

# ══════════════════════════════════════════════════════════
# 快照建表 SQL 含 state 列（_build_treemap_snapshot）
# ══════════════════════════════════════════════════════════

def test_snapshot_table_has_state_columns():
    """_build_treemap_snapshot 建表 SQL 应含 opportunity_state/state_evidence 列"""
    import inspect

    import data_daemon
    src = inspect.getsource(data_daemon._build_treemap_snapshot)
    assert 'opportunity_state TEXT' in src, "快照建表缺少 opportunity_state 列"
    assert 'state_evidence TEXT' in src, "快照建表缺少 state_evidence 列"


def test_snapshot_tags_query_has_state():
    """快照标签平铺查询应读取 opportunity_state/state_evidence"""
    import inspect

    import data_daemon
    src = inspect.getsource(data_daemon._build_treemap_snapshot)
    assert "tag_name='opportunity_state'" in src, "快照 tags 查询未读 opportunity_state"
    assert "tag_name='state_evidence'" in src, "快照 tags 查询未读 state_evidence"


def test_snapshot_insert_has_state():
    """快照 INSERT 应写入 opportunity_state/state_evidence"""
    import inspect

    import data_daemon
    src = inspect.getsource(data_daemon._build_treemap_snapshot)
    assert 'opportunity_state' in src and 'state_evidence' in src


# ══════════════════════════════════════════════════════════
# 快照读取透出（get_treemap_snapshot_items）
# ══════════════════════════════════════════════════════════

def test_snapshot_items_expose_state():
    """get_treemap_snapshot_items 返回项应含 opportunity_state/state_evidence"""
    import inspect

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    src = inspect.getsource(EnhancedCacheManager.get_treemap_snapshot_items)
    assert "'opportunity_state':" in src or '"opportunity_state"' in src, \
        "get_treemap_snapshot_items 未透出 opportunity_state"
    assert "'state_evidence':" in src or '"state_evidence"' in src, \
        "get_treemap_snapshot_items 未透出 state_evidence"


def test_snapshot_items_real_data():
    """真实快照数据：get_treemap_snapshot_items 返回含 opportunity_state 字段"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    # 取 3 只真实快照股票
    rows = ecm.conn.execute(
        "SELECT ts_code FROM treemap_snapshot LIMIT 3").fetchall()
    if not rows:
        pytest.skip("treemap_snapshot 无数据")
    codes = [r[0] for r in rows]
    items = ecm.get_treemap_snapshot_items(codes)
    assert items, "快照读取返回空"
    for it in items:
        assert 'opportunity_state' in it, f"item 缺 opportunity_state: {it.get('ts_code')}"
        assert 'state_evidence' in it, f"item 缺 state_evidence: {it.get('ts_code')}"


# ══════════════════════════════════════════════════════════
# /treemap API 响应透出
# ══════════════════════════════════════════════════════════

def test_treemap_api_exposes_state():
    """/treemap API 响应 stock 项应含 opportunity_state"""
    from app import create_app
    app = create_app()
    client = app.test_client()
    resp = client.get('/api/v3/opportunity-atlas/treemap?mode=market')
    assert resp.status_code == 200
    data = resp.get_json()
    groups = (data.get('data') or {}).get('groups') or []
    found = False
    for g in groups:
        for s in (g.get('stocks') or []):
            if 'opportunity_state' in s:
                found = True
                assert 'state_evidence' in s, \
                    f"API stock 缺 state_evidence: {s.get('ts_code')}"
                break
        if found:
            break
    assert found, "API 响应 stock 项未找到 opportunity_state 字段"


def test_l0_low_liquidity_soft_risk():
    """342号核查补齐：status_engine._apply_l0 应识别换手率<1% 为 low_liquidity 软风险

    对齐 cross_validate._evaluate_gate / 335号 L0b（low_liquidity×0.7 仓位系数）。
    通过 mock dm.get_cached_daily_basic 返回低换手率，验证 soft_risks 与 position_coeff。
    """
    from app.opportunity_atlas.status_engine import StatusEngine
    import pandas as pd

    class _FakeDM:
        def get_cached_daily_basic(self, ts_code):
            return pd.DataFrame({'ts_code': [ts_code], 'trade_date': ['2026-08-14'],
                                 'turnover_rate': [0.5]})  # 换手率 0.5% < 1%

    se = StatusEngine(dm=_FakeDM())
    l0 = se._apply_l0('000001.SZ', {}, {}, None)
    assert 'low_liquidity' in l0['soft_risks'], \
        f"换手率<1% 应识别 low_liquidity, 实际: {l0['soft_risks']}"
    assert abs(l0['position_coeff'] - 0.7) < 1e-6, \
        f"low_liquidity 仓位系数应为 0.7, 实际: {l0['position_coeff']}"

    class _FakeDM2:
        def get_cached_daily_basic(self, ts_code):
            return pd.DataFrame({'ts_code': [ts_code], 'trade_date': ['2026-08-14'],
                                 'turnover_rate': [3.0]})  # 换手率 3% 正常

    se2 = StatusEngine(dm=_FakeDM2())
    l0_ok = se2._apply_l0('000002.SZ', {}, {}, None)
    assert 'low_liquidity' not in l0_ok['soft_risks'], \
        f"换手率正常不应识别 low_liquidity, 实际: {l0_ok['soft_risks']}"
    assert abs(l0_ok['position_coeff'] - 1.0) < 1e-6
