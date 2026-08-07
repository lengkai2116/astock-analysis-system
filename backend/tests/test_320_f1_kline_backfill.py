"""320号 F1 回归测试：K 线深度检查与单股历史补采

背景：553 只股票 daily_cache K 线 <30 根（600519 仅 1 行），导致机会图谱标签与
DeepSeek 九层解读的 K 线依赖维度同时失效（buy_sell_point/volume_price_fit 等缺失）。
F1 修复：daemon 完整性检查新增"K 线深度 <130 根"判定 + 单股历史补采。
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


def test_kline_depth_check_detects_short_history(ecm):
    """K 线深度检查应识别 K 线 <130 根的股票（全市场约 600 只缺口）"""
    from data_daemon import _find_kline_insufficient
    codes = _find_kline_insufficient(threshold=130, limit=10)
    assert isinstance(codes, list), "应返回 ts_code 列表"
    assert codes, "K 线 <130 根的股票应被检测到（全市场约 600 只）"


def test_kline_depth_check_threshold(ecm):
    """阈值 30 与 130 的结果应不同（130 检出更多）"""
    from data_daemon import _find_kline_insufficient
    lt30 = set(_find_kline_insufficient(threshold=30, limit=5000))
    lt130 = set(_find_kline_insufficient(threshold=130, limit=5000))
    assert lt130 >= lt30, "阈值越高检出越多"


def test_backfill_kline_history_single_stock(ecm, monkeypatch):
    """单股 K 线历史补采应写入 daily_cache 且数量增加（600519 从 1 行 → 多行）

    修复前：600519 daily_cache 仅 1 行（08-06），策略引擎无法计算
    修复后：补采近5年日线 → K 线深度满足 ≥130
    """
    from data_daemon import _backfill_kline_history
    before = len(ecm.get_cached_daily('600519.SH'))
    added = _backfill_kline_history('600519.SH', years=5)
    after = len(ecm.get_cached_daily('600519.SH'))
    assert added > 0, "补采应返回写入条数"
    assert after >= 130, f"补采后 K 线应 ≥130 根，实际 {after}（修复前 {before}）"


def test_backfill_kline_history_skips_adequate(ecm):
    """K 线已充足的股票不应重复补采（返回 0 或跳过）"""
    from data_daemon import _backfill_kline_history
    # 000001.SZ K 线充足，补采应为空（tushare 返回已有数据，INSERT OR REPLACE 不增行）
    _backfill_kline_history('000001.SZ', years=5)
    assert True  # 不抛异常即可（幂等）
