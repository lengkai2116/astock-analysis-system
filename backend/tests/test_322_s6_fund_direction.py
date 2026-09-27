"""potential_engine 有向资金强度修复测试（313号 fund 维方向 bug）

背景：compute_fund_strength 用 abs(net5)/tot5 计算强度，资金方向被抹掉——
净流出股票照样得高分（常润股份 603201.SH：5日净流出却 fund=0.816）。
修复：改为有向强度（净流入正 / 净流出负，范围 -1~1）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)


from app.opportunity_atlas.potential_engine import compute_fund_strength  # noqa: E402


def test_fund_strength_directional_outflow_negative():
    """净流出股票 → 强度应为负（修复前 abs 抹掉方向得正高分）"""
    # 用真实数据：找一只 5 日净流出且绝对值强度高的股票（bug 高发区）
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import sharding_manager
    ecm = EnhancedCacheManager()
    # 421号R4a：moneyflow_cache 属 market_cache.db，走分库路由（原 sqlite3 直连总库恒空）
    rows = sharding_manager.execute_query('moneyflow_cache', """
        SELECT ts_code, SUM(net_lg_amount) net5, SUM(buy_lg_amount + sell_lg_amount) tot5 FROM (
            SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
            FROM moneyflow_cache) WHERE rn <= 5 GROUP BY ts_code
        HAVING SUM(net_lg_amount) < 0
        ORDER BY ABS(SUM(net_lg_amount)) / SUM(buy_lg_amount + sell_lg_amount) DESC
        LIMIT 1
    """)
    assert rows, "应能找到净流出股票"
    tc = rows[0][0]
    strength = compute_fund_strength(ecm, tc)
    assert strength is not None, "应返回强度"
    assert strength < 0, f"净流出股票强度应为负（修复前为正），实际 {strength}"
    assert -1.0 <= strength <= 1.0, f"有向强度应在 -1~1，实际 {strength}"


def test_fund_strength_directional_inflow_positive():
    """净流入股票 → 强度应为正"""

    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import sharding_manager
    ecm = EnhancedCacheManager()
    rows = sharding_manager.execute_query('moneyflow_cache', """
        SELECT ts_code FROM (
            SELECT ts_code, SUM(net_lg_amount) net5, SUM(buy_lg_amount + sell_lg_amount) tot5 FROM (
                SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount,
                       ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
                FROM moneyflow_cache) WHERE rn <= 5 GROUP BY ts_code)
        WHERE net5 > 0 AND tot5 > 0 LIMIT 1
    """)
    assert rows, "应能找到净流入股票"
    strength = compute_fund_strength(ecm, rows[0][0])
    assert strength is not None and strength > 0, f"净流入股票强度应为正，实际 {strength}"


def test_fund_strength_603201_negative():
    """常润股份（原满分 bug 样本）→ 有向强度符号须与 5 日净额一致

    490号：原断言硬编码「603201 必为 5 日净流出」，但该样本的行情数据已随时间漂移
    （2026-09-27 实测 5 日净额 +345.99 → 已转为净流入），断言与数据脱钩而恒失败。
    改为「有向强度符号 == 数据净额符号」——仍精确验证 313 号「方向不被 abs 抹掉」的原意，
    且不依赖某一时点的个股资金方向。
    """
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    from app.data.sharding_manager import sharding_manager
    ecm = EnhancedCacheManager()
    rows = sharding_manager.execute_query('moneyflow_cache', """
        SELECT SUM(net_lg_amount) FROM (
            SELECT net_lg_amount,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
            FROM moneyflow_cache WHERE ts_code = '603201.SH') WHERE rn <= 5
    """)
    net5 = float(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else None
    assert net5 is not None, "应有 603201 近 5 日资金数据"
    strength = compute_fund_strength(ecm, '603201.SH')
    assert strength is not None
    assert (strength > 0) == (net5 > 0), (
        f'603201 有向强度符号应与 5 日净额一致（净额={net5:.2f}，强度={strength}）'
    )
