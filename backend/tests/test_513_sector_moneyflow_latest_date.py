"""513号 #D1 — 板块资金流向选日口径：取「最新」有足够数据的交易日。

背景（2026-10-13 实证）：`get_sector_moneyflow` 原按「记录数最多」选日，
`moneyflow_cache` 的 10-12 与 10-09 记录数并列 5573 时 `max` 命中先出现的
10-09 → 接口静默回退旧交易日。修复＝按「最新」选日（仍要求记录数≥50）。
"""
from datetime import datetime

from app.services.dashboard_service import DashboardService


def test_records_count_tie_picks_latest():
    # 2026-10-13 真实场景：10-12 与 10-09 并列 5573
    date_counts = {'2026-10-08': 5572, '2026-10-09': 5573, '2026-10-12': 5573}
    assert DashboardService._pick_latest_trade_date(date_counts) == '2026-10-12'


def test_sparse_latest_day_falls_back_to_previous():
    # 最新日记录数不足 50 → 回退到最近一个充足交易日
    date_counts = {'2026-10-09': 5573, '2026-10-12': 10}
    assert DashboardService._pick_latest_trade_date(date_counts) == '2026-10-09'


def test_no_day_has_enough_records_returns_none():
    assert DashboardService._pick_latest_trade_date({'2026-10-12': 49}) is None
    assert DashboardService._pick_latest_trade_date({}) is None


def test_handles_datetime_keys():
    date_counts = {datetime(2026, 10, 9): 100, datetime(2026, 10, 12): 100}
    assert DashboardService._pick_latest_trade_date(date_counts) == datetime(2026, 10, 12)


def test_handles_compact_date_strings():
    date_counts = {'20261009': 5573, '20261012': 5573}
    assert DashboardService._pick_latest_trade_date(date_counts) == '20261012'
