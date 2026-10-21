"""532号 批次4：RAW-2E 历史回算边界 + 分位校准 + yaml 回写回归。

不写业务库；yaml 用例用 tmp_path。"""
import importlib.util
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'backend' / 'scripts' / '_532_backfill_sector_heat_dim.py'

_spec = importlib.util.spec_from_file_location('_b532', SCRIPT)
_b532 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_b532)


# ──────────────────────────────────────────────
# 收益窗口 / 历史日期边界
# ──────────────────────────────────────────────
def test_ret_uses_n_day_window_and_guards_short_series():
    from app.data.sector_heat_dim import _ret

    assert _ret([100.0, 110.0], 1) == pytest.approx(10.0)
    assert _ret([100.0], 1) is None
    assert _ret([100.0] * 20, 20) is None
    assert _ret([100.0] * 21, 20) == 0.0


def test_build_sector_heat_rows_target_date_bounds_queries():
    from app.data.sector_heat_dim import build_sector_heat_rows

    calls = []

    class _Fake:
        def _query_shard(self, table, sql, params=None):
            calls.append((table, sql, params))
            if 'DISTINCT trade_date' in sql and table == 'daily_cache':
                return pd.DataFrame({'trade_date': ['2026-10-20', '2026-10-19']})
            return pd.DataFrame()

    res = build_sector_heat_rows(_Fake(), target_date='2026-10-20')
    assert res == ('', [])
    assert calls
    assert 'trade_date <= ?' in calls[0][1]
    assert calls[0][2] == ['2026-10-20']


def test_last5_dates_bounded():
    from app.data.sector_heat_dim import _last5_dates

    calls = []

    class _Fake:
        def _query_shard(self, table, sql, params=None):
            calls.append((sql, params))
            return pd.DataFrame({'trade_date': ['2026-10-19']})

    out = _last5_dates(_Fake(), 'moneyflow_cache', '2026-10-20')
    assert out == ['2026-10-19']
    assert 'trade_date <= ?' in calls[0][0]
    assert calls[0][1] == ['2026-10-20']


# ──────────────────────────────────────────────
# 分位校准
# ──────────────────────────────────────────────
def _row(i: int) -> dict:
    return {
        'rps_20': i % 101,
        'rps_120': i % 101,
        'limit_up_ratio': (i % 9) + 1,
        'zhaban_ratio': 40 + (i % 61),
        'amount_share': (i % 20) + 1,
        'dim_sentiment': 50 + (i % 50),
    }


_CFG = {'thresholds': {
    'rps_very_strong': 90.0, 'rps120_overheat': 95.0,
    'limit_up_ratio': 5.0, 'zhaban_ratio': 40.0,
    'amount_share': 15.0, 'crowding_overheat': 90.0,
}}


def test_calibrate_percentiles():
    new, rep = _b532._calibrate([_row(i) for i in range(500)], _CFG, min_sample=100)
    assert rep['rps120_overheat']['status'] == 'calibrated'
    assert rep['amount_share']['status'] == 'calibrated'
    assert new['amount_share'] > 15.0  # 1~20 的 P95 ≈19
    assert new['zhaban_ratio'] == 80.0  # P95 触顶后按 clamp 上限
    assert 80.0 <= new['rps_very_strong'] <= 99.0


def test_calibrate_insufficient_keeps_old():
    new, rep = _b532._calibrate([_row(i) for i in range(10)], _CFG, min_sample=100)
    assert all(v['status'] == 'insufficient' for v in rep.values())
    assert new == _CFG['thresholds']


# ──────────────────────────────────────────────
# yaml 回写
# ──────────────────────────────────────────────
def test_update_yaml_updates_calibrated_only(tmp_path, monkeypatch):
    p = tmp_path / 'sector_heat.yaml'
    p.write_text(
        '# 532 配置注释\nthresholds:\n'
        '  rps120_overheat: 95.0  # 保留注释\n'
        '  amount_share: 15.0\n',
        encoding='utf-8')
    monkeypatch.setattr(_b532, 'CONFIG_PATH', p)
    calib = {
        'rps120_overheat': {'status': 'calibrated', 'n': 100, 'quantile': 0.95,
                            'old': 95.0, 'new': 96.67},
        'amount_share': {'status': 'insufficient', 'n': 10,
                         'old': 15.0, 'new': 15.0},
    }
    n = _b532._update_yaml(calib, sample_dates=10, sample_rows=100)
    text = p.read_text(encoding='utf-8')
    assert n == 1
    assert '# 532 配置注释' in text and '# 保留注释' in text
    assert '96.67' in text and '15.0' in text
    loaded = yaml.safe_load(text)
    assert loaded['thresholds']['rps120_overheat'] == 96.67
    assert loaded['thresholds']['amount_share'] == 15.0
    assert loaded['calibration']['sample_dates'] == 10


# ──────────────────────────────────────────────
# 写库列契约 / dry-run 默认
# ──────────────────────────────────────────────
def test_write_columns_match_table():
    db = ROOT / 'data' / 'duckdb' / 'compute_cache.db'
    if not db.exists():
        pytest.skip('compute_cache.db 不存在')
    conn = sqlite3.connect(db)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sector_heat_dim_cache)")]
    finally:
        conn.close()
    assert _b532._COLS == [c for c in cols if c != 'cached_at']


def test_script_defaults_to_dry_run():
    src = SCRIPT.read_text(encoding='utf-8')
    assert 'if not args.write' in src
    assert 'DRY-RUN 完成' in src
