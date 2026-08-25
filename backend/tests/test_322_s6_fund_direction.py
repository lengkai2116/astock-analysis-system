"""potential_engine 有向资金强度修复测试（313号 fund 维方向 bug）

背景：compute_fund_strength 用 abs(net5)/tot5 计算强度，资金方向被抹掉——
净流出股票照样得高分（常润股份 603201.SH：5日净流出却 fund=0.816）。
修复：改为有向强度（净流入正 / 净流出负，范围 -1~1）。
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)


from app.opportunity_atlas.potential_engine import compute_fund_strength  # noqa: E402


def test_fund_strength_directional_outflow_negative():
    """净流出股票 → 强度应为负（修复前 abs 抹掉方向得正高分）"""
    # 用真实数据：找一只 5 日净流出且绝对值强度高的股票（bug 高发区）
    import pathlib
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    conn = sqlite3.connect(ecm.db_path)
    # 找 5 日净额 < 0 且 |net|/tot 高的股票
    rows = conn.execute("""
        SELECT ts_code, SUM(net_lg_amount) net5, SUM(buy_lg_amount + sell_lg_amount) tot5 FROM (
            SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
            FROM moneyflow_cache) WHERE rn <= 5 GROUP BY ts_code
        HAVING SUM(net_lg_amount) < 0
        ORDER BY ABS(SUM(net_lg_amount)) / SUM(buy_lg_amount + sell_lg_amount) DESC
        LIMIT 1
    """).fetchall()
    conn.close()
    assert rows, "应能找到净流出股票"
    tc = rows[0][0]
    strength = compute_fund_strength(ecm, tc)
    assert strength is not None, "应返回强度"
    assert strength < 0, f"净流出股票强度应为负（修复前为正），实际 {strength}"
    assert -1.0 <= strength <= 1.0, f"有向强度应在 -1~1，实际 {strength}"


def test_fund_strength_directional_inflow_positive():
    """净流入股票 → 强度应为正"""
    import pathlib
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    conn = sqlite3.connect(ecm.db_path)
    rows = conn.execute("""
        SELECT ts_code FROM (
            SELECT ts_code, SUM(net_lg_amount) net5, SUM(buy_lg_amount + sell_lg_amount) tot5 FROM (
                SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount,
                       ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
                FROM moneyflow_cache) WHERE rn <= 5 GROUP BY ts_code)
        WHERE net5 > 0 AND tot5 > 0 LIMIT 1
    """).fetchall()
    conn.close()
    assert rows, "应能找到净流入股票"
    strength = compute_fund_strength(ecm, rows[0][0])
    assert strength is not None and strength > 0, f"净流入股票强度应为正，实际 {strength}"


def test_fund_strength_603201_negative():
    """常润股份（原满分 bug 样本，5日净流出）→ 有向强度应为负"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    strength = compute_fund_strength(ecm, '603201.SH')
    assert strength is not None
    assert strength < 0, f"603201 5日净流出应有向为负，实际 {strength}"
