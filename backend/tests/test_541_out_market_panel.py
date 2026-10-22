"""541号 B0/B1 定向测试。

覆盖：
- `out_market_panel` 分库建表/写入/读取/最新日期；
- 17 个仪表盘模块的 OUT payload 契约校验；
- 日期提取；
- `_collect_out_market_payloads` 的模块收集与异常隔离。
"""
import copy

import pytest
from app.data.out_market import (
    OUT_MARKET_MODULES,
    extract_dates,
    get_latest_asof_date,
    get_panel,
    upsert_panel,
    validate_payload,
)
from app.data.sharding_manager import ShardingManager

# 每个模块的最小合法 payload（与 dashboard_service 真实返回的顶层键对齐）
MIN_PAYLOADS = {
    'market_index_daily': {'days': [{'date': '10/22', 'total_amount': 1.0}]},
    'market_daily_top_up': {'stocks': [{'ts_code': '000001.SZ'}], 'type': 'up'},
    'market_daily_top_down': {'stocks': [{'ts_code': '000001.SZ'}], 'type': 'down'},
    'market_eod_snapshot': {'stocks': [{'ts_code': '000001.SZ'}], 'trade_date': '20261021'},
    'market_overview_panel': {'as_of': '20261021', 'breadth': {'up_count': 1}},
    'market_moneyflow_summary': {'days': [{'date': '10/21'}]},
    'market_sector_changes': {'gainers': [{'industry': 'x'}], 'losers': [], 'date': '20261021'},
    'market_sector_moneyflow': {'sectors': [{'industry': 'x'}], 'date': '20261021'},
    'market_flows_30d': {
        'industry_flow_5d': [{'industry': 'x'}],
        'margin_30d': [{'date': '10/21'}],
        'etf_30d': [{'date': '10/21'}],
    },
    'market_breadth': {'up_count': 1, 'down_count': 0, 'trade_date': '20261021'},
    'market_limit_ecology': {'up': 1, 'down': 0, 'as_of': '20261021'},
    'market_state': {'state': 'ranging', 'state_label': '震荡', 'data_date': '20261021'},
    'market_emotion': {'phase': 'ferment', 'phase_label': '发酵', 'data_date': '20261021'},
    'market_sector_heat': {'sectors': [{'industry': 'x'}], 'date': '20261021'},
    'market_sector_heat_dim': {'sectors': [{'industry': 'x'}], 'date': '20261021'},
    'market_alerts': {'alerts': [], 'date': '20261021'},
    'market_overview': {'indexes': [{'ts_code': '000001.SH'}]},
}


def _tmp_sharding(tmp_path):
    (tmp_path / 'duckdb').mkdir(parents=True, exist_ok=True)
    return ShardingManager(str(tmp_path))


# ── 契约校验 ──────────────────────────────────────────────

@pytest.mark.parametrize('module', sorted(OUT_MARKET_MODULES))
def test_min_payload_is_valid(module):
    ok, reason = validate_payload(module, copy.deepcopy(MIN_PAYLOADS[module]))
    assert ok, f'{module}: {reason}'


def test_missing_required_key_is_invalid():
    ok, reason = validate_payload('market_state', {'state': 'ranging'})
    assert not ok
    assert '缺字段' in reason


def test_empty_required_list_is_invalid():
    ok, reason = validate_payload(
        'market_sector_heat', {'sectors': [], 'date': '20261021'})
    assert not ok
    assert '为空' in reason


def test_alerts_allow_empty_list():
    ok, reason = validate_payload(
        'market_alerts', {'alerts': [], 'date': '20261021'})
    assert ok, reason


def test_unknown_module_is_invalid():
    ok, _ = validate_payload('not_a_module', {'x': 1})
    assert not ok


# ── 日期提取 ──────────────────────────────────────────────

def test_extract_dates_collects_nested_dates():
    payload = {
        'trade_date': '20261021',
        'nested': {'data_date': '20261022'},
        'rows': [{'date': '20261023'}, {'date': '20261020'}],
    }
    found = extract_dates(payload)
    assert found['trade_date'] == '20261021'
    assert found['data_date'] == '20261022'
    assert found['date'] == '20261023'


def test_extract_dates_ignores_empty_values():
    assert extract_dates({'date': '', 'trade_date': None}) == {}


# ── 分库读写 ──────────────────────────────────────────────

def test_panel_roundtrip_and_latest(tmp_path):
    sm = _tmp_sharding(tmp_path)
    p1 = dict(MIN_PAYLOADS['market_state'], state='wait')
    p2 = dict(MIN_PAYLOADS['market_state'], state='avoid')

    assert upsert_panel(sm, 'market_state', '20261021', p1, {'data_date': '20261021'})
    assert upsert_panel(sm, 'market_state', '20261022', p2, {'data_date': '20261022'})

    latest = get_panel(sm, 'market_state')
    assert latest['asof_date'] == '20261022'
    assert latest['payload']['state'] == 'avoid'

    older = get_panel(sm, 'market_state', asof_date='20261021')
    assert older['payload']['state'] == 'wait'
    assert get_latest_asof_date(sm) == '20261022'


def test_panel_missing_returns_none(tmp_path):
    sm = _tmp_sharding(tmp_path)
    assert get_panel(sm, 'market_state') is None


# ── 构建收集器 ────────────────────────────────────────────

class _FakeDashboardService:
    """按方法名返回最小 payload；get_daily_top 按 type 区分涨/跌。"""

    _METHOD_TO_MODULE = {
        method: module for module, method, _ in __import__(
            'data_daemon').OUT_MARKET_BUILDERS
    }

    def __getattr__(self, name):
        def _call(**kwargs):
            if name == 'get_daily_top':
                module = ('market_daily_top_up'
                          if kwargs.get('type') == 'up'
                          else 'market_daily_top_down')
            else:
                module = self._METHOD_TO_MODULE.get(name)
            if not module:
                return None
            return copy.deepcopy(MIN_PAYLOADS[module])
        return _call


def test_collect_out_market_payloads_covers_all_modules():
    import data_daemon as dd

    payloads, errors = dd._collect_out_market_payloads(_FakeDashboardService())
    assert not errors
    assert set(payloads) == set(OUT_MARKET_MODULES)
    for module, (payload, dates) in payloads.items():
        assert payload
        assert isinstance(dates, dict)


def test_collect_reports_invalid_payload():
    import data_daemon as dd

    class _BadService:
        def __getattr__(self, name):
            return lambda **kwargs: {'unexpected': True}

    payloads, errors = dd._collect_out_market_payloads(_BadService())
    assert not payloads
    assert set(errors) == set(OUT_MARKET_MODULES)
