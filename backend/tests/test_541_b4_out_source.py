"""541号 B4 定向测试。

覆盖：
- `apply_tag_overlay`：treemap_snapshot 覆盖 state/rsc/label/profile；
- `get_tags` 集成：旧标签被 OUT 值覆盖，无快照行时清空关键判定字段；
- `/treemap`：快照缺失返回 `snapshot_missing`，不再走旧表回退；
- dim7：composite 截面基准改从 `pre_feat_cache` 读取。
"""
import json

import pandas as pd
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.data.out_market import apply_tag_overlay
from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine
from app.routes import opportunity_atlas as oa
from flask import Flask

# ── apply_tag_overlay ───────────────────────────────────

def test_apply_tag_overlay_overrides_state_rsc_label():
    tags = {
        'opportunity_state': 'wait',
        'right_side_confirm': '未确认',
        'opportunity_label': '旧标签',
        'signal_strength': '90',
        'trend_alignment': 'up',
    }
    row = {
        'opportunity_state': 'avoid',
        'right_side_confirm': '否决',
        'opportunity_label': '慢牛上涨',
        'opportunity_type': 'trend_up',
        'opportunity_profile': '{"risk": 1}',
        'signal_strength': 90.0,
        'consensus_rate': 0.618,
    }
    out = apply_tag_overlay(tags, row)

    assert out['opportunity_state'] == 'avoid'
    assert out['right_side_confirm'] == '否决'
    assert out['opportunity_label'] == '慢牛上涨'
    assert out['opportunity_type'] == 'trend_up'
    assert out['opportunity_profile'] == '{"risk": 1}'
    assert out['signal_strength'] == '90.0'
    assert out['consensus_rate'] == 0.618
    # 非 OUT 字段保持
    assert out['trend_alignment'] == 'up'


def test_apply_tag_overlay_empty_row_clears_judgement_fields():
    out = apply_tag_overlay({
        'opportunity_state': 'wait',
        'right_side_confirm': '未确认',
        'opportunity_label': '旧标签',
        'signal_strength': '90',
        'trend_alignment': 'up',
    }, None)

    assert out['opportunity_state'] is None
    assert out['right_side_confirm'] is None
    assert out['opportunity_label'] is None
    assert out['signal_strength'] is None
    assert out['trend_alignment'] == 'up'


def test_apply_tag_overlay_nan_signal_is_none():
    out = apply_tag_overlay({'signal_strength': '90'}, {'signal_strength': float('nan')})
    assert out['signal_strength'] is None


# ── get_tags 集成 ──────────────────────────────────────

class _FakeTagsECM:
    def __init__(self, tm_rows=None):
        self.tm_rows = tm_rows

    def _query_shard(self, table, sql, params=None):
        if table == 'opportunity_tags_cache':
            return pd.DataFrame([
                {'tag_name': 'opportunity_state', 'tag_value': 'wait'},
                {'tag_name': 'right_side_confirm', 'tag_value': '未确认'},
                {'tag_name': 'opportunity_label', 'tag_value': '旧标签'},
                {'tag_name': 'trend_alignment', 'tag_value': 'up'},
            ])
        if table == 'treemap_snapshot':
            return self.tm_rows if self.tm_rows is not None else pd.DataFrame()
        return pd.DataFrame()

    def get_pre_feat_tags(self, ts_code):
        # 541 B5：get_tags 已冻结旧表，trend_alignment 由 pre_feat 提供
        return {'trend_alignment': 'up'}


def test_get_tags_overlays_out_row():
    tm_rows = pd.DataFrame([{
        'signal_strength': 90.0,
        'opportunity_state': 'avoid',
        'right_side_confirm': '否决',
        'opportunity_label': '慢牛上涨',
        'opportunity_type': 'trend_up',
        'opportunity_profile': '{"risk": 1}',
        'confirm_evidence': None,
        'state_evidence': '右侧否决',
        'entry_signals': None,
        'exit_conditions': None,
        'main_force_presence': None,
        'presence_evidence': None,
        'consensus_rate': 0.618,
        'conflict': None,
    }])
    tags = EnhancedCacheManager.get_tags(_FakeTagsECM(tm_rows), '000001.SZ')

    assert tags['opportunity_state'] == 'avoid'
    assert tags['right_side_confirm'] == '否决'
    assert tags['opportunity_label'] == '慢牛上涨'
    assert tags['signal_strength'] == '90.0'
    assert tags['trend_alignment'] == 'up'


def test_get_tags_without_out_row_clears_legacy_state():
    tags = EnhancedCacheManager.get_tags(_FakeTagsECM(pd.DataFrame()), '000001.SZ')
    assert tags['opportunity_state'] is None
    assert tags['right_side_confirm'] is None
    assert tags['opportunity_label'] is None
    assert tags['signal_strength'] is None


# ── /treemap 不再回退旧表 ──────────────────────────────

class _FakeCache:
    def get_treemap_snapshot_codes(self):
        return ['000001.SZ']

    def get_all_active_codes(self):
        return ['000001.SZ']


class _FakeDM:
    cache = _FakeCache()

    def get_treemap_snapshot_items(self, codes, include_detail=False):
        raise RuntimeError('snapshot missing')

    def get_all_ts_codes(self, limit=10000):
        return ['000001.SZ']


def test_treemap_snapshot_missing_does_not_fallback(monkeypatch):
    monkeypatch.setattr(oa, 'get_data_manager', lambda: _FakeDM())
    app = Flask(__name__)
    with app.test_request_context('/api/v3/opportunity-atlas/treemap?mode=market'):
        resp = oa.treemap()

    payload = json.loads(resp.get_data(as_text=True))
    assert payload['data']['data_status'] == 'snapshot_missing'
    assert payload['data']['groups'] == []


# ── dim7 截面基准走 pre_feat ───────────────────────────

class _FakeFeatECM:
    def _query_shard(self, table, sql, params=None):
        if 'MAX(trade_date)' in sql:
            return pd.DataFrame({'d': ['2026-10-22']})
        rows = [
            {
                'ts_code': f'{i:06d}.SZ',
                'features_json': json.dumps({
                    'valuation': {'composite_rating': i / 100}
                }),
            }
            for i in range(120)
        ]
        return pd.DataFrame(rows)


class _EmptyFeatECM:
    def _query_shard(self, table, sql, params=None):
        return pd.DataFrame()


def test_dim7_composite_items_from_pre_feat():
    items = Dim7ValuationEngine._composite_items_from_pre_feat(_FakeFeatECM())
    assert len(items) == 120
    assert items[0][1] == 0.0


def test_dim7_composite_items_empty_pre_feat():
    assert Dim7ValuationEngine._composite_items_from_pre_feat(_EmptyFeatECM()) == []
