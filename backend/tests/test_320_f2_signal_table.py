"""320号 F2 回归测试：策略信号双表数据新鲜度守卫

背景：strategy_signals 旧表 07-22 停更（P2 已切换 strategy_signal_detail 08-06 正常），
胜率计算若基于旧表过期数据将产生误导。
F2 修复：compute_win_rates 加数据新鲜度守卫——旧表停更时跳过计算并告警。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
from datetime import datetime, timedelta


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def _legacy_max_date(ecm):
    return ecm.conn.execute("SELECT MAX(trade_date) FROM strategy_signals").fetchone()[0]


def test_legacy_signal_table_is_stale(ecm):
    """旧表 strategy_signals 应已停更（数据超过 3 天）——触发守卫"""
    max_date = _legacy_max_date(ecm)
    assert max_date, "旧表应有数据"
    try:
        d = datetime.strptime(max_date, '%Y%m%d')
    except ValueError:
        d = datetime.strptime(max_date, '%Y-%m-%d')
    assert (datetime.now() - d).days > 3, f"旧表应已停更超 3 天，实际最新 {max_date}"


def test_signal_detail_is_fresh(ecm):
    """新表 strategy_signal_detail 应为最新（近 3 天内更新）"""
    max_date = ecm.conn.execute("SELECT MAX(trade_date) FROM strategy_signal_detail").fetchone()[0]
    assert max_date, "新表应有数据"
    try:
        d = datetime.strptime(max_date, '%Y%m%d')
    except ValueError:
        d = datetime.strptime(max_date, '%Y-%m-%d')
    assert (datetime.now() - d).days <= 3, f"新表应近 3 天更新，实际最新 {max_date}"


def test_win_rate_guard_skips_stale(ecm, monkeypatch):
    """旧表停更时胜率计算应跳过（守卫生效，不基于过期数据计算）"""
    from app.data.precompute_indicator_manager import PrecomputeIndicatorManager
    from app.data.enhanced_cache_manager import get_ecm_instance
    # 直接调用 compute_win_rates，守卫生效应返回空 DataFrame（旧表停更）
    manager = PrecomputeIndicatorManager(ecm)
    win_df = manager.compute_win_rates()
    # 守卫逻辑：旧表停更超 3 天 → 返回空 DataFrame（不基于过期数据计算）
    assert win_df is not None, "应返回 DataFrame"
    assert win_df.empty, f"旧表停更时应跳过计算返回空，实际 {len(win_df)} 行"
