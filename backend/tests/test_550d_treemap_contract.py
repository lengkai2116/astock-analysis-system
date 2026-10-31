"""550-D：treemap 契约回归（mode 废弃 / 交易日历 stale / 缺失代码登记）。"""
import inspect
from pathlib import Path

from app.routes.opportunity_atlas import _is_panel_stale

ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / 'backend/app/routes/opportunity_atlas.py'


def test_stale_uses_expected_trading_day():
    assert _is_panel_stale('2026-10-23', '2026-10-23') is False
    assert _is_panel_stale('2026-10-23', '2026-10-26') is True
    assert _is_panel_stale(None, '2026-10-23') is True


def test_opportunity_mode_is_explicitly_deprecated():
    src = ROUTE.read_text(encoding='utf-8')
    assert "if mode == 'opportunity':" in src
    assert "'data_status': 'deprecated'" in src
    assert "'deprecated': True" in src
    assert 'mode=opportunity 已废弃' in src


def test_response_exposes_trading_day_and_missing_codes():
    src = ROUTE.read_text(encoding='utf-8')
    assert 'panel_expected_date' in src
    assert 'signal_strength_missing_codes' in src
    assert 'eod_date()' in src
