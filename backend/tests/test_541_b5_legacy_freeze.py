"""541号 B5 定向测试。

覆盖：
- pre_feat 四个迁移字段（ma_alignment / buy_sell_point / pattern_signal / state_label）；
- `get_tags` 不再读取旧 opportunity_tags_cache；
- `get_tags_by_group` / `get_tags_batch` / `get_tags_by_date` 改走 pre_feat + treemap。
"""
import json

import pandas as pd
from app.data.enhanced_cache_manager import EnhancedCacheManager

FEATURES = {
    'volume_price': {'ma_alignment': 'bullish'},
    'chanlun': {'buy_sell_point': 'first_buy'},
    'derived': {
        'pattern_signal': '突破',
        'state_label': '上升',
        'support_resistance': '{"support": 1.0, "resistance": 2.0}',
    },
    'chip_fund_ext': {'asr': 12.5, 'concentration': 0.3},
}

TM_ROW = {
    'signal_strength': 88.0,
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
}


class _FakeTagsECM:
    get_pre_feat_tags = EnhancedCacheManager.get_pre_feat_tags
    _pre_feat_fields_from_json = EnhancedCacheManager._pre_feat_fields_from_json

    def _query_shard(self, table, sql, params=None):
        if table == 'opportunity_tags_cache':
            raise AssertionError('旧表读取应已冻结')
        if table == 'pre_feat_cache':
            return pd.DataFrame([{'features_json': json.dumps(FEATURES)}])
        if table == 'treemap_snapshot':
            return pd.DataFrame([TM_ROW])
        return pd.DataFrame()


class _FakeDateECM:
    _pre_feat_fields_from_json = EnhancedCacheManager._pre_feat_fields_from_json

    def _query_shard(self, table, sql, params=None):
        if table == 'pre_feat_cache':
            return pd.DataFrame([{'features_json': json.dumps(FEATURES)}])
        if table == 'treemap_snapshot_history':
            return pd.DataFrame([TM_ROW])
        return pd.DataFrame()


def test_pre_feat_mapping_includes_four_migrated_fields():
    out = EnhancedCacheManager._pre_feat_fields_from_json(FEATURES)
    assert out['ma_alignment'] == 'bullish'
    assert out['buy_sell_point'] == 'first_buy'
    assert out['pattern_signal'] == '突破'
    assert out['state_label'] == '上升'
    assert out['asr'] == 12.5


def test_get_tags_never_reads_legacy_table():
    tags = EnhancedCacheManager.get_tags(_FakeTagsECM(), '000001.SZ')
    assert tags['ma_alignment'] == 'bullish'
    assert tags['buy_sell_point'] == 'first_buy'
    assert tags['pattern_signal'] == '突破'
    assert tags['state_label'] == '上升'
    assert tags['opportunity_state'] == 'avoid'
    assert tags['right_side_confirm'] == '否决'
    assert tags['signal_strength'] == '88.0'


def test_pre_feat_mapping_keeps_support_price_single_owner():
    out = EnhancedCacheManager._pre_feat_fields_from_json({
        'risk_ext': {'support_price': 9.0, 'resistance_price': 10.0},
        'structure_ext': {'support_price': 8.0, 'indicator_status': 'ma=up'},
    })
    assert out['support_price'] == 9.0
    assert out['resistance_price'] == 10.0
    assert out['indicator_status'] == 'ma=up'


def test_get_tags_by_group_filters_to_requested_group():
    class _GroupFake:
        _TAG_GROUP_MAP = EnhancedCacheManager._TAG_GROUP_MAP
        _PRE_FEAT_FIELD_MAP = EnhancedCacheManager._PRE_FEAT_FIELD_MAP

        def get_tags(self, ts_code):
            return {'ma_alignment': 'bullish', 'asr': 12.5,
                    'valuation_level': 'low', 'opportunity_state': 'avoid'}

    chip = EnhancedCacheManager.get_tags_by_group(
        _GroupFake(), '000001.SZ', ['chip_deep'])
    assert chip == {'asr': 12.5}

    both = EnhancedCacheManager.get_tags_by_group(
        _GroupFake(), '000001.SZ', ['structure', 'chip_deep'])
    assert both == {'ma_alignment': 'bullish', 'asr': 12.5}

    # 未知组名保持旧行为（返回全集），避免静默丢字段
    unknown = EnhancedCacheManager.get_tags_by_group(
        _GroupFake(), '000001.SZ', ['not_a_group'])
    assert 'opportunity_state' in unknown


def test_get_tags_by_date_reads_pre_feat_and_history():
    out = EnhancedCacheManager.get_tags_by_date(
        _FakeDateECM(), '000001.SZ', '2026-10-21')
    assert out['ma_alignment'] == 'bullish'
    assert out['state_label'] == '上升'
    assert out['opportunity_state'] == 'avoid'
    assert out['signal_strength'] == '88.0'


class _BatchFake:
    _TAG_BATCH_CHUNK = 500
    _pre_feat_fields_from_json = EnhancedCacheManager._pre_feat_fields_from_json

    def __init__(self):
        self.calls = []

    def _query_shard(self, table, sql, params=None):
        self.calls.append((table, sql, list(params or [])))
        if table == 'pre_feat_cache':
            return pd.DataFrame([
                {'ts_code': 'A', 'features_json': json.dumps(FEATURES)},
                {'ts_code': 'B', 'features_json': json.dumps(
                    {'valuation': {'valuation_level': 'low'}})},
            ])
        if table == 'treemap_snapshot':
            return pd.DataFrame([{**TM_ROW, 'ts_code': 'A'}])
        return pd.DataFrame()


def test_get_tags_batch_uses_two_queries_per_chunk():
    fake = _BatchFake()
    out = EnhancedCacheManager.get_tags_batch(fake, ['A', 'B'])
    assert [call[0] for call in fake.calls] == [
        'pre_feat_cache', 'treemap_snapshot']
    assert 'ROW_NUMBER() OVER' in fake.calls[0][1]
    assert out['A']['ma_alignment'] == 'bullish'
    assert out['A']['opportunity_state'] == 'avoid'
    # B 无 treemap 行 → 判定字段清空，pre_feat 字段保留
    assert out['B']['valuation_level'] == 'low'
    assert out['B']['opportunity_state'] is None


def test_get_tags_batch_chunks_large_requests():
    class _ChunkFake(_BatchFake):
        _TAG_BATCH_CHUNK = 1

    fake = _ChunkFake()
    EnhancedCacheManager.get_tags_batch(fake, ['A', 'B'])
    assert len(fake.calls) == 4
