"""521号 O1 — 新股「上市前 5 个交易日」豁免 pct_chg>50% 清洗

背景：深度清洗规则6 `|pct_chg|>50 → 剔除`（417号方案）未豁免注册制新股
上市前 5 个交易日（创业板/科创板/北交所无涨跌幅限制）。实证：301660.SZ
10-13 首日 +223.06%、920157.BJ 10-09 首日 +449.45% 均被误剔 → K线首日
缺失 → JUD 因 kline=false 跳过。修复：_detect_outliers 对上市首日起
5 个交易日内（按 is_holiday 交易日历）的行豁免剔除（判据见
_is_within_first5_trading_days）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    ecm = EnhancedCacheManager()
    # _load_list_date_map 读取的是类属性 EnhancedCacheManager._list_date_map；
    # 用受控映射替代真实 app.db 读取（生产值在 daemon 进程内由 stocks 表填充）
    EnhancedCacheManager._list_date_map = {
        '301660.SZ': '2026-10-13',  # 创业板新股
        '920157.BJ': '2026-10-09',  # 北交所新股
        '000001.SZ': '1991-04-03',  # 老股票（平安银行）
        '600519.SH': '2001-08-27',  # 老股票（贵州茅台）
    }
    yield ecm
    EnhancedCacheManager._list_date_map = None  # 清理，避免影响其它测试


# ── _is_within_first5_trading_days ────────────────────────

def test_new_stock_first_day_within_window(ecm):
    """上市首日 → 豁免窗口内（301660.SZ 10-13 首日）"""
    assert ecm._is_within_first5_trading_days('301660.SZ', '2026-10-13') is True


def test_new_stock_second_day_within_window(ecm):
    """上市次日 → 豁免窗口内"""
    assert ecm._is_within_first5_trading_days('301660.SZ', '2026-10-14') is True


def test_new_stock_beyond_window(ecm):
    """上市 5 个交易日后 → 不豁免（创业板 10-13 首日 + 5 个交易日 = 10-20 附近）"""
    assert ecm._is_within_first5_trading_days('301660.SZ', '2026-10-21') is False


def test_old_stock_not_within_window(ecm):
    """老股票上市已久 → 不豁免"""
    assert ecm._is_within_first5_trading_days('000001.SZ', '2026-10-14') is False


def test_unknown_stock_not_within_window(ecm):
    """无 list_date 记录 → 不豁免（保持原剔除语义）"""
    assert ecm._is_within_first5_trading_days('999999.SZ', '2026-10-14') is False


# ── _detect_outliers 豁免行为 ─────────────────────────────

def _mk_df(ts_code, trade_date, pct_chg):
    return pd.DataFrame({
        'ts_code': [ts_code],
        'trade_date': [trade_date],
        'open': [10.0], 'high': [11.0], 'low': [9.0], 'close': [10.5],
        'vol': [1000], 'amount': [5000], 'pct_chg': [pct_chg],
    })


def test_new_stock_first_day_kept(ecm):
    """新股首日 pct_chg>50（无涨跌幅限制）→ 豁免保留"""
    out = ecm._detect_outliers(_mk_df('301660.SZ', '2026-10-13', 223.06))
    assert len(out) == 1, "新股首日 +223% 应豁免保留"


def test_new_stock_beijing_first_day_kept(ecm):
    """北交所新股首日 pct_chg>50 → 豁免保留"""
    out = ecm._detect_outliers(_mk_df('920157.BJ', '2026-10-09', 449.45))
    assert len(out) == 1, "北交所新股首日 +449% 应豁免保留"


def test_old_stock_outlier_dropped(ecm):
    """老股票 pct_chg>50 → 仍剔除（真脏数据）"""
    out = ecm._detect_outliers(_mk_df('000001.SZ', '2026-10-14', 60.0))
    assert len(out) == 0, "老股票 +60% 应剔除"


def test_old_stock_normal_kept(ecm):
    """老股票正常涨跌幅 → 保留"""
    out = ecm._detect_outliers(_mk_df('600519.SH', '2026-10-14', 3.5))
    assert len(out) == 1, "正常涨跌幅应保留"
