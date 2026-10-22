"""541号 B3 定向测试。

覆盖：
- 实时 overlay 只覆盖白名单字段，EOD 序列/判定字段不被改写；
- 指数实时价按 ts_code 合并；
- 涨跌家数/涨跌停家数/情绪指标 overlay；
- 实时源样本不足 / 无数据时不 overlay；
- `/dashboard/full` 的混合模块已接入 live_overlay。
"""
import pytest
from app.services import live_overlay as lo


def test_breadth_overlay_only_whitelisted_fields():
    payload = {
        'count': 5000, 'up_count': 3000, 'down_count': 1800, 'flat_count': 200,
        'up_ratio': 60.0, 'down_ratio': 36.0,
        'ma20_ratio': 17.0, 'limit_ratio': 59.0, 'turnover_percentile': 93.0,
        'history': [{'stat_date': '2026-10-21', 'ma20_ratio': 17.0}],
        'source': 'DuckDB 盘后数据（前一完整交易日）',
    }
    live = {
        'breadth': {
            'count': 5500, 'up_count': 3200, 'down_count': 2200,
            'flat_count': 100, 'up_ratio': 58.2, 'down_ratio': 40.0,
        },
        'source': 'in_memory_store',
        'at': '2026-10-22 10:00:00',
    }
    out = lo.apply_overlay('market_breadth', payload, live)

    assert out['count'] == 5500
    assert out['up_count'] == 3200
    assert out['down_count'] == 2200
    assert out['up_ratio'] == 58.2
    # EOD 字段不被覆盖
    assert out['ma20_ratio'] == 17.0
    assert out['limit_ratio'] == 59.0
    assert out['history'] == payload['history']
    assert out['source'] == payload['source']
    # 元信息
    assert out['live_source'] == 'in_memory_store'
    assert out['live_at'] == '2026-10-22 10:00:00'
    assert out['panel_source'] == 'out'


def test_breadth_no_live_keeps_payload():
    payload = {'up_count': 1, 'history': [1, 2]}
    assert lo.apply_overlay('market_breadth', payload, {}) == payload


def test_overview_merges_index_quotes_only():
    payload = {
        'indexes': [{
            'ts_code': '000001.SH', 'price': 3700.0, 'change_pct': 0.1,
            'mini_kline': [{'date': '10/21'}],
        }],
        'market_status': 'closed',
        'data_is_live': False,
        'total_volume': 100,
    }
    live = {
        'index_quotes': {'000001.SH': {'price': 3731.2, 'change_pct': 0.4}},
        'market_status': 'trading',
        'source': 'in_memory_store',
        'at': '2026-10-22 10:00:00',
    }
    out = lo.apply_overlay('market_overview', payload, live)

    assert out['indexes'][0]['price'] == 3731.2
    assert out['indexes'][0]['change_pct'] == 0.4
    assert out['indexes'][0]['mini_kline'] == [{'date': '10/21'}]
    assert out['market_status'] == 'trading'
    assert out['data_is_live'] is True
    assert out['total_volume'] == 100


def test_overview_partial_coverage_keeps_eod_live_flag():
    payload = {
        'indexes': [{'ts_code': '000001.SH'}, {'ts_code': '399001.SZ'}],
        'data_is_live': False,
    }
    live = {
        'index_quotes': {'000001.SH': {'price': 3731.2, 'change_pct': 0.4}},
        'source': 'in_memory_store',
        'at': '2026-10-22 10:00:00',
    }
    out = lo.apply_overlay('market_overview', payload, live)
    assert out['indexes'][0]['price'] == 3731.2
    assert out['data_is_live'] is False


def test_market_status_uses_holiday_enum(monkeypatch):
    from datetime import datetime
    from app.utils import trading_hours as th
    monkeypatch.setattr(th, '_now', lambda: datetime(2026, 10, 24, 10, 0))
    assert lo._market_status_now() == 'holiday'


def test_limit_ecology_merges_counts_only():
    payload = {
        'up': {'count': 54, 'stocks': [{'ts_code': 'A'}], 'industries': [{'x': 1}]},
        'down': {'count': 7, 'stocks': [{'ts_code': 'B'}]},
        'boards': {'max_height': 5, 'distribution': [{'days': 5, 'count': 1}]},
        'data_available': True,
    }
    live = {'limits': {'up': 60, 'down': 5}, 'source': 'in_memory_store',
            'at': '2026-10-22 10:00:00'}
    out = lo.apply_overlay('market_limit_ecology', payload, live)

    assert out['up']['count'] == 60
    assert out['down']['count'] == 5
    # 明细/连板不被实时覆盖
    assert out['up']['stocks'] == [{'ts_code': 'A'}]
    assert out['boards']['max_height'] == 5
    assert out['data_available'] is True


def test_emotion_merges_metrics_only():
    payload = {
        'phase': 'ferment', 'phase_label': '发酵',
        'metrics': {
            'limit_up_count': 54, 'limit_down_count': 7,
            'max_board_height': 5, 'sealing_rate': 65.1, 'up_down_ratio': 7.71,
        },
        'data_available': True,
    }
    live = {'limits': {'up': 60, 'down': 5}, 'source': 'in_memory_store',
            'at': '2026-10-22 10:00:00'}
    out = lo.apply_overlay('market_emotion', payload, live)

    assert out['metrics']['limit_up_count'] == 60
    assert out['metrics']['limit_down_count'] == 5
    assert out['metrics']['up_down_ratio'] == 12.0
    # 阶段/封板率/连板高仍为 OUT
    assert out['phase'] == 'ferment'
    assert out['metrics']['sealing_rate'] == 65.1
    assert out['metrics']['max_board_height'] == 5


# ── 实时源新鲜度/样本门槛 ────────────────────────────────

def test_breadth_requires_min_sample(monkeypatch):
    monkeypatch.setattr(lo, '_snapshot_records',
                        lambda: ([{'change_pct': 1.0}] * 50, 'in_memory_store'))
    assert lo._breadth_counts(lo._snapshot_records()[0]) is None


def test_breadth_counts_200(monkeypatch):
    records = ([{'change_pct': 1.0}] * 150
               + [{'change_pct': -1.0}] * 40
               + [{'change_pct': 0.0}] * 10)
    counts = lo._breadth_counts(records)
    assert counts == {
        'count': 200, 'up_count': 150, 'down_count': 40, 'flat_count': 10,
        'up_ratio': 75.0, 'down_ratio': 20.0,
    }


def test_breadth_low_coverage_keeps_eod_anchor():
    payload = {
        'count': 5500, 'up_count': 3200, 'down_count': 2200,
        'up_ratio': 58.2, 'down_ratio': 40.0,
    }
    live = {'breadth': {'count': 3000, 'up_count': 1800, 'down_count': 1150,
                        'flat_count': 50, 'up_ratio': 60.0, 'down_ratio': 38.3},
            'source': 'in_memory_store', 'at': '2026-10-22 10:00:00'}
    out = lo.apply_overlay('market_breadth', payload, live)
    assert out['count'] == 5500
    assert out['up_count'] == 3200
    assert out['up_ratio'] == 58.2


def test_get_live_overlay_breadth(monkeypatch):
    monkeypatch.setattr(lo, '_snapshot_records',
                        lambda: ([{'change_pct': 1.0}] * 200, 'in_memory_store'))
    monkeypatch.setattr(lo, '_live_at', lambda: '2026-10-22 10:00:00')
    live = lo.get_live_overlay('market_breadth')
    assert live['breadth']['up_count'] == 200
    assert live['source'] == 'in_memory_store'


def test_get_live_overlay_limits(monkeypatch):
    monkeypatch.setattr(lo, '_limit_counts',
                        lambda: ({'up': 54, 'down': 7}, 'in_memory_store'))
    monkeypatch.setattr(lo, '_live_at', lambda: '2026-10-22 10:00:00')
    live = lo.get_live_overlay('market_limit_ecology')
    assert live['limits'] == {'up': 54, 'down': 7}


def test_recent_text_rejects_old_timestamp():
    assert lo._recent_text('2026-09-09 15:00:00') is False


# ── /dashboard/full 接线 ────────────────────────────────

def test_dashboard_full_applies_overlay(monkeypatch):
    from app.services import out_market_reader as omr
    from app.services.dashboard_service import DashboardService

    overlay_calls = []

    def _fake_out(module, fallback, transform=None, expected_date=None):
        return {'module': module, 'panel_source': 'out'}

    def _fake_overlay(module, payload, live=None):
        overlay_calls.append(module)
        return payload

    monkeypatch.setattr(omr, 'get_out_or_legacy', _fake_out)
    monkeypatch.setattr(lo, 'apply_overlay', _fake_overlay)

    svc = DashboardService()
    result = svc.get_dashboard_full()
    assert result is not None
    for module in ('market_overview', 'market_limit_ecology',
                   'market_breadth', 'market_emotion'):
        assert module in overlay_calls
