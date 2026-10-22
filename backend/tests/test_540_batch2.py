"""540号 批次2 定向测试。

覆盖：
- 13 个标签字段从 `pre_feat_cache` 提取并覆盖旧标签；
- `get_tags()` 以 pre_feat 为准，`signal_strength` 取 treemap_snapshot（JUD）且缺失为 None；
- `query_tags()` 只匹配每标签最新日期，并带确定性排序；
- `value` 模式默认仅 `extreme_low/low`；
- API 项透出 `signal_strength_source` 与快照新列（style/catalyst/估值分位）。
"""
import json
import sqlite3

import pandas as pd
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.routes.opportunity_atlas import _collect_ts_codes
from data_daemon import _pre_feat_treemap_fields


def test_pre_feat_treemap_fields_mapping():
    features = {
        'valuation': {
            'valuation_level': 'low',
            'valuation_deviation': 13.7,
            'dividend_yield': 5.32,
            'composite_rating': 0.6833,
            'fina_health': 'suspicious',
            'pe_percentile_5y': 51.8,
            'pb_percentile_5y': 11.6,
        },
        'depth': {
            'main_force_phase': 'washing',
            'trend_alignment': 'mixed',
            'fund_flow': '5d_inflow',
            'capital_nature': 'unknown',
            'price_position': 'high_zone',
            'main_force_presence': 'moderate',
            'presence_evidence': '["筹码集中"]',
            'phase_confidence': 0.3889,
        },
        'sentiment': {'sentiment_phase': 'ferment'},
        'sector': {'sector_heat': 'top_10'},
        'chip': {'chip_concentration': 'concentrating'},
        'risk_ext': {'volatility_level': 'high'},
        'style': {'style_exposure': 'large_value'},
        'event': {'catalyst_event': 'reduce'},
    }
    out = _pre_feat_treemap_fields(features)
    assert out['valuation_level'] == 'low'
    assert out['valuation_deviation'] == 13.7
    assert out['dividend_yield'] == 5.32
    assert out['main_force_phase'] == 'washing'
    assert out['sentiment_phase'] == 'ferment'
    assert out['sector_heat'] == 'top_10'
    assert out['chip_concentration'] == 'concentrating'
    assert out['volatility_level'] == 'high'
    assert out['style_exposure'] == 'large_value'
    assert out['catalyst_event'] == 'reduce'
    assert out['pe_percentile_5y'] == 51.8
    assert out['pb_percentile_5y'] == 11.6


def test_get_tags_prefers_pre_feat_and_jud_signal(monkeypatch):
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    pre = {
        'valuation': {'valuation_level': 'low'},
        'depth': {'main_force_phase': 'washing'},
        'sentiment': {'sentiment_phase': 'ferment'},
    }

    def fake_query_shard(table, sql, params=None):
        if table == 'opportunity_tags_cache':
            return pd.DataFrame([
                {'tag_name': 'valuation_level', 'tag_value': 'fair'},
                {'tag_name': 'buy_sell_point', 'tag_value': 'third_buy'},
            ])
        if table == 'pre_feat_cache':
            return pd.DataFrame([{'features_json': json.dumps(pre)}])
        if table == 'treemap_snapshot':
            return pd.DataFrame([{'signal_strength': 90.0}])
        return pd.DataFrame()

    monkeypatch.setattr(ecm, '_query_shard', fake_query_shard)
    tags = ecm.get_tags('000001.SZ')
    assert tags['valuation_level'] == 'low'          # pre_feat 覆盖旧标签
    assert tags['main_force_phase'] == 'washing'
    assert tags['sentiment_phase'] == 'ferment'
    assert tags['buy_sell_point'] == 'third_buy'      # 非 pre_feat 字段保留
    assert tags['signal_strength'] == '90.0'          # JUD 快照优先


def test_get_tags_signal_is_none_when_jud_missing(monkeypatch):
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)

    def fake_query_shard(table, sql, params=None):
        if table == 'opportunity_tags_cache':
            return pd.DataFrame([{'tag_name': 'signal_strength', 'tag_value': '55'}])
        if table == 'pre_feat_cache':
            return pd.DataFrame()
        if table == 'treemap_snapshot':
            return pd.DataFrame([{'signal_strength': None}])
        return pd.DataFrame()

    monkeypatch.setattr(ecm, '_query_shard', fake_query_shard)
    assert ecm.get_tags('000001.SZ')['signal_strength'] is None


def test_value_mode_defaults_to_undervalued():
    class _Cache:
        last_filters = None

        def query_tags(self, filters):
            self.last_filters = filters
            return []

    class _DM:
        cache = _Cache()

    dm = _DM()
    assert _collect_ts_codes('value', dm, '', '') == []
    assert dm.cache.last_filters == {'valuation_level': ['extreme_low', 'low']}


def test_query_tags_uses_latest_tag_date_only(monkeypatch, tmp_path):
    db = tmp_path / 'tags.db'
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE opportunity_tags_cache ("
        "id INTEGER PRIMARY KEY, ts_code TEXT, tag_name TEXT, tag_value TEXT, "
        "tag_group TEXT, confidence REAL, source TEXT, updated_at TEXT)"
    )
    rows = [
        (1, 'A.SZ', 'valuation_level', 'low', 'valuation', None, None, '2026-08-18'),
        (2, 'A.SZ', 'valuation_level', 'fair', 'valuation', None, None, '2026-08-19'),
        (3, 'B.SZ', 'valuation_level', 'low', 'valuation', None, None, '2026-08-18'),
        (4, 'B.SZ', 'valuation_level', 'low', 'valuation', None, None, '2026-08-19'),
        (5, 'C.SZ', 'valuation_level', 'low', 'valuation', None, None, '2026-08-19'),
    ]
    con.executemany(
        "INSERT INTO opportunity_tags_cache VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()

    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    monkeypatch.setattr(
        ecm, '_query_shard',
        lambda table, sql, params=None: pd.read_sql_query(sql, con, params=params),
    )
    result = [r['ts_code'] for r in ecm.query_tags({'valuation_level': ['low']})]
    assert result == ['B.SZ', 'C.SZ']   # A 的最新值是 fair，不应命中
    con.close()


def test_snapshot_items_null_signal_and_new_extra_columns(monkeypatch):
    ecm = EnhancedCacheManager.__new__(EnhancedCacheManager)
    df = pd.DataFrame([{
        'ts_code': '000001.SZ', 'name': '平安银行', 'industry': '银行',
        'close': 11.65, 'pct_chg': 1.3, 'open': 11.5, 'high': 11.7, 'low': 11.4,
        'amplitude': 2.2, 'total_mv': 22607894.7, 'pe': 5.0, 'pb': 0.6,
        'amount': 1466720.0, 'turnover_rate': 0.65, 'circ_mv': 20000000.0,
        'dividend_yield': 5.0, 'signal_strength': None,
        'valuation_level': 'low', 'main_force_phase': 'washing',
        'sentiment_phase': 'ferment', 'sector_heat': 'top_10',
        'fina_health': 'suspicious', 'opportunity_type': 'default',
        'opportunity_label': '一般机会', 'evidence_count': 0,
        'right_side_confirm': '未确认', 'main_force_presence': 'moderate',
        'presence_evidence': '[]', 'opportunity_state': 'wait',
        'state_evidence': '[]', 'confirm_evidence': '[]', 'consensus_rate': 0.8,
        'opportunity_profile': '{}', 'entry_signals': '[]', 'exit_conditions': '[]',
        'valuation_deviation': 13.7,
        'style_exposure': 'large_value', 'catalyst_event': 'reduce',
        'pe_percentile_5y': 51.8, 'pb_percentile_5y': 11.6,
        'trend_alignment': 'mixed', 'price_position': 'high_zone',
        'fund_flow': '5d_inflow', 'capital_nature': 'unknown',
        'chip_concentration': 'concentrating', 'volatility_level': 'high',
        'composite_rating': 0.68,
    }])
    monkeypatch.setattr(ecm, 'get_treemap_snapshot', lambda codes: df)
    monkeypatch.setattr(ecm, 'get_one_liner_detail_batch', lambda codes: {})
    monkeypatch.setattr(
        ecm, '_get_latest_tags_for_codes',
        lambda *a, **k: (_ for _ in ()).throw(AssertionError('不应回读旧标签')),
    )
    item = ecm.get_treemap_snapshot_items(['000001.SZ'])[0]
    assert item['signal_strength'] is None
    assert item['signal_strength_source'] is None
    assert item['tags']['style_exposure'] == 'large_value'
    assert item['tags']['catalyst_event'] == 'reduce'
    assert item['tags']['pe_percentile_5y'] == 51.8
    assert item['tags']['pb_percentile_5y'] == 11.6
