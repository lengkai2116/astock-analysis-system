"""479号-6 机会地图页 seven_dim 接线单测（treemap API 补 one_liner_detail）

覆盖（479-6，C1 断点修复）：
  - U1 get_one_liner_detail_batch：批量取 status_snapshot.one_liner_detail（非空过滤）
  - U2 get_treemap_snapshot_items：items 含 one_liner_detail 字段（前端
       opportunity-treemap.html:754 读 s.one_liner_detail，缺 → None 回退旧画像）
  - U3 空输入/异常 → 空 map / 字段为 None（437 缺则降级，不抛错）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest

from app.data.enhanced_cache_manager import EnhancedCacheManager


def _mk_snapshot_df(ts_codes=('600519.SH', '000002.SZ')):
    rows = []
    for ts in ts_codes:
        rows.append({
            'ts_code': ts, 'name': f'股票{ts[:4]}',
            'industry': '白酒', 'close': 100.0, 'pct_chg': 1.2, 'open': 99.0,
            'high': 101.0, 'low': 98.0, 'amplitude': 3.0, 'total_mv': 1e6,
            'pe': 30.0, 'pb': 5.0, 'amount': 1e5, 'turnover_rate': 1.5,
            'circ_mv': 8e5, 'dividend_yield': 2.0, 'signal_strength': 0.6,
            'valuation_level': 'fair', 'main_force_phase': '建仓', 'sentiment_phase': '发酵',
            'sector_heat': 'top_10', 'fina_health': 'pass', 'opportunity_type': 'x',
            'opportunity_label': 'y', 'evidence_count': 3, 'right_side_confirm': 'y',
            'main_force_presence': '1', 'presence_evidence': 'z', 'opportunity_state': 's',
            'state_evidence': 'e', 'confirm_evidence': 'c', 'consensus_rate': 0.6,
            'opportunity_profile': '{"trend":{"light":"green","status":"上升"}}',
            'entry_signals': '', 'exit_conditions': '', 'valuation_deviation': 0.1,
            'trend_alignment': 'a', 'price_position': 'p', 'fund_flow': 'f',
            'capital_nature': 'n', 'chip_concentration': 'c', 'volatility_level': 'low',
            'composite_rating': 'r',
        })
    return pd.DataFrame(rows)


class TestOneLinerDetailBatch:

    def test_batch_returns_map(self, monkeypatch):
        """批量取 one_liner_detail：{ts_code: detail}，空值行过滤"""
        df = pd.DataFrame({
            'ts_code': ['600519.SH', '000002.SZ', '000001.SZ'],
            'one_liner_detail': ['{"summary":{"text":"状态总结：数据不足"}}', None, ''],
        })
        mgr = EnhancedCacheManager()

        def fake_query_shard(table, sql, params=None):
            assert table == 'status_snapshot'
            # 模拟 SQL 的 ts_code IN (...) AND one_liner_detail IS NOT NULL AND != ''
            d = df[df['ts_code'].isin(params or [])]
            d = d[d['one_liner_detail'].notna() & (d['one_liner_detail'] != '')]
            return d.reset_index(drop=True)

        monkeypatch.setattr(mgr, '_query_shard', fake_query_shard)
        out = mgr.get_one_liner_detail_batch(['600519.SH', '000002.SZ', '000001.SZ'])
        assert out == {'600519.SH': '{"summary":{"text":"状态总结：数据不足"}}'}
        assert '000002.SZ' not in out  # NULL 过滤
        assert '000001.SZ' not in out  # 空串过滤

    def test_empty_input(self):
        """空 ts_codes → {}（不查库）"""
        assert EnhancedCacheManager().get_one_liner_detail_batch([]) == {}

    def test_query_exception_returns_empty(self, monkeypatch):
        """查询异常 → {}（437 缺则降级，不抛错）"""
        mgr = EnhancedCacheManager()

        def boom(*a, **k):
            raise RuntimeError('db locked')

        monkeypatch.setattr(mgr, '_query_shard', boom)
        assert mgr.get_one_liner_detail_batch(['600519.SH']) == {}


class TestTreemapItemsLinkage:

    def test_items_include_one_liner_detail(self, monkeypatch):
        """treemap items 含 one_liner_detail（前端 :754 读 s.one_liner_detail）"""
        mgr = EnhancedCacheManager()
        snapshot = _mk_snapshot_df()

        def fake_get_snapshot(codes):
            return snapshot

        monkeypatch.setattr(mgr, 'get_treemap_snapshot', fake_get_snapshot)
        monkeypatch.setattr(mgr, '_get_latest_tags_for_codes', lambda codes, names: {})
        monkeypatch.setattr(mgr, 'get_one_liner_detail_batch',
                            lambda codes: {'600519.SH': '{"summary":{"text":"状态总结：数据不足"}}'})

        items = mgr.get_treemap_snapshot_items(['600519.SH', '000002.SZ'])
        by_ts = {i['ts_code']: i for i in items}
        assert by_ts['600519.SH']['one_liner_detail'] == '{"summary":{"text":"状态总结：数据不足"}}'
        # 无 one_liner_detail 的股票 → None（前端回退旧画像，437 缺则降级）
        assert by_ts['000002.SZ']['one_liner_detail'] is None
        # 既有字段不回归
        assert by_ts['600519.SH']['name'] == '股票6005'
        assert by_ts['600519.SH']['opportunity_profile'] is not None

    def test_empty_snapshot_returns_empty(self, monkeypatch):
        """快照空 → []（不查 one_liner_detail）"""
        mgr = EnhancedCacheManager()

        def fake_get_snapshot(codes):
            return pd.DataFrame()

        monkeypatch.setattr(mgr, 'get_treemap_snapshot', fake_get_snapshot)
        assert mgr.get_treemap_snapshot_items(['600519.SH']) == []
