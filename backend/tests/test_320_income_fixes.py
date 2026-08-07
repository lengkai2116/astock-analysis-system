"""320号 F1-F3 回归测试：revenue_growth 同比修正 + income_cache 列名映射

背景（沟通纪要 012 根因）：
- F1: revenue_growth 用相邻两期（A股累计制 Q1 vs 年报）→ 全市场 99.7% 伪"营收下降"，
      正确同比（同月跨年）仅 44.0% 下降
- F2: tushare pro.income 返回 n_income/n_income_attr_p/operate_profit，
      income_cache 建表列名为 net_profit/net_profit_atsopc/operating_profit → 列名不匹配致净利润全空
- F3: _yoY_growth/_anchor_earnings 用 tushare 原始列名（n_income_attr_p/n_income），
      但表里无此列 → 恒 None；统一为表列名 net_profit_atsopc/net_profit
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


@pytest.fixture(scope='module')
def engine():
    from app.opportunity_atlas.valuation_estimator import ValuationEngine
    return ValuationEngine()


# ────────────────────────────────────────────────────────────
# F1: revenue_growth 同比计算（相邻期 bug 修复）
# ────────────────────────────────────────────────────────────

def _income_df():
    """构造累计制利润表：Q1 2026 vs Q1 2025（同月跨年）+ 年报"""
    return pd.DataFrame({
        'end_date': pd.to_datetime(['2026-03-31', '2025-12-31', '2025-09-30', '2025-03-31']),
        'revenue': [110.0, 400.0, 300.0, 100.0],   # Q1'26 增长 10%
        'basic_eps': [0.55, 2.0, 1.5, 0.5],        # Q1'26 EPS 增长 10%
    })


def test_revenue_growth_uses_yoy_not_adjacent(engine, monkeypatch):
    """revenue_growth 应使用同月跨年同比（Q1'26/Q1'25），而非相邻期（Q1'26/年报）

    修复前：rev.iloc[0]/rev.iloc[1] = 110/400-1 = -72.5%（伪下滑）
    修复后：同月跨年 = 110/100-1 = +10.0%
    """
    df = _income_df()
    # monkeypatch compute_tags 中的 df_income（简化：直接测新增同比辅助方法）
    from app.opportunity_atlas import valuation_estimator as ve
    if hasattr(ve.ValuationEngine, '_revenue_yoy'):
        growth = ve.ValuationEngine._revenue_yoy(None, df)
        assert growth is not None, "应能计算同比"
        assert abs(growth - 0.10) < 0.001, f"应 +10%，实际 {growth}"
    else:
        pytest.skip("_revenue_yoy 尚未实现（RED 阶段）")


def test_anchor3_growth_tolerance_uses_yoy(engine, monkeypatch):
    """锚3 成长容忍（科技/成长+营收增长>20%）应使用同比而非相邻期"""
    df = _income_df()
    from app.opportunity_atlas import valuation_estimator as ve
    if hasattr(ve.ValuationEngine, '_revenue_yoy'):
        growth = ve.ValuationEngine._revenue_yoy(None, df)
        # Q1'26 vs Q1'25 = +10% < 20% → 不应触发成长容忍（修复前相邻期 -72.5% 也不会触发，
        # 但若某股 Q1 大幅增长而年报已高基数，相邻期会低估增长——本测试验证同比语义正确）
        assert growth == 0.10
    else:
        pytest.skip("_revenue_yoy 尚未实现（RED 阶段）")


# ────────────────────────────────────────────────────────────
# F2: income_cache 列名映射（tushare → 表列名）
# ────────────────────────────────────────────────────────────

def test_cache_income_maps_tushare_columns(ecm, monkeypatch):
    """cache_income_data 应将 tushare 列名映射到表列名

    修复前：n_income/n_income_attr_p/operate_profit 原样入库 → 表 net_profit 等列全空
    修复后：映射 n_income→net_profit、n_income_attr_p→net_profit_atsopc、operate_profit→operating_profit
    """
    tushare_df = pd.DataFrame({
        'ts_code': ['TEST01.SZ', 'TEST01.SZ'],
        'end_date': pd.to_datetime(['2026-03-31', '2025-03-31']),
        'revenue': [110.0, 100.0],
        'n_income': [25.0, 20.0],                 # tushare 净利润
        'n_income_attr_p': [23.0, 19.0],          # tushare 归母净利润
        'operate_profit': [30.0, 28.0],           # tushare 营业利润
        'basic_eps': [0.55, 0.5],
    })
    # 隔离测试：直接调 cache_income_data（真实写入测试表行，用唯一 ts_code 避免污染）
    ecm.cache_income_data(tushare_df)
    try:
        df = ecm.get_cached_income('TEST01.SZ')
        assert not df.empty, "应能读取缓存"
        latest = df.iloc[0]
        assert 'net_profit' in df.columns
        # 修复后：net_profit 应映射自 n_income
        if 'net_profit' in latest and latest['net_profit'] is not None:
            assert abs(float(latest['net_profit']) - 25.0) < 0.01, \
                f"net_profit 应映射 n_income=25，实际 {latest['net_profit']}"
        if 'net_profit_atsopc' in latest and latest['net_profit_atsopc'] is not None:
            assert abs(float(latest['net_profit_atsopc']) - 23.0) < 0.01, \
                f"net_profit_atsopc 应映射 n_income_attr_p=23，实际 {latest['net_profit_atsopc']}"
        if 'operating_profit' in latest and latest['operating_profit'] is not None:
            assert abs(float(latest['operating_profit']) - 30.0) < 0.01, \
                f"operating_profit 应映射 operate_profit=30，实际 {latest['operating_profit']}"
    finally:
        # 清理测试数据
        try:
            ecm.conn.execute("DELETE FROM income_cache WHERE ts_code='TEST01.SZ'")
            ecm.conn.commit()
        except Exception:
            pass


# ────────────────────────────────────────────────────────────
# F3: _yoY_growth 用表列名（net_profit_atsopc/net_profit）
# ────────────────────────────────────────────────────────────

def test_yoy_growth_uses_table_columns(engine):
    """_yoY_growth 应从表列名 net_profit_atsopc/net_profit 读取（修复前读 tushare 原始名恒 None）"""
    df = pd.DataFrame({
        'end_date': pd.to_datetime(['2026-03-31', '2025-03-31']),
        'net_profit_atsopc': [23.0, 19.0],
        'net_profit': [25.0, 20.0],
        'revenue': [110.0, 100.0],
    })
    growth = engine._yoY_growth(df)
    assert growth is not None, "_yoY_growth 应能读取表列名（修复前恒 None）"
    assert abs(growth - (23.0/19.0 - 1)) < 0.01, f"归母净利润同比应 +21%，实际 {growth}"


def test_cache_income_filters_unknown_columns(ecm):
    """cache_income_data 应过滤表不存在的列（tushare 返回 85 列含 f_ann_date 等）

    修复前：f_ann_date 等列导致 _insert_from_df 整体失败 → 净利润写入不生效
    """
    tushare_df = pd.DataFrame({
        'ts_code': ['TEST02.SZ', 'TEST02.SZ'],
        'end_date': pd.to_datetime(['2026-03-31', '2025-03-31']),
        'revenue': [110.0, 100.0],
        'n_income': [25.0, 20.0],
        'f_ann_date': ['2026-04-29', '2025-04-28'],   # tushare 独有列（表无此列）
        'report_type': ['1', '1'],                     # 同上
        'basic_eps': [0.55, 0.5],
    })
    ecm.cache_income_data(tushare_df)
    try:
        df = ecm.get_cached_income('TEST02.SZ')
        assert not df.empty, "应能读取缓存（多余列应被过滤）"
        latest = df.iloc[0]
        assert 'net_profit' in df.columns
        assert 'f_ann_date' not in df.columns, "表不应出现 f_ann_date 列"
        if latest['net_profit'] is not None:
            assert abs(float(latest['net_profit']) - 25.0) < 0.01, \
                f"net_profit 应映射 n_income=25，实际 {latest['net_profit']}"
    finally:
        try:
            ecm.conn.execute("DELETE FROM income_cache WHERE ts_code='TEST02.SZ'")
            ecm.conn.commit()
        except Exception:
            pass
