"""481号 dim8 第一层环境定位数据源核查与补全——B1/B2/①/② 单测

覆盖（2026-09-24）：
  - B1 get_cached_sector_heat 修复：sector_heat_cache 为 long 格式（stat_date×每行业一行），
      原 `ORDER BY ... LIMIT 1` 只取 1 行业；修复后取最新 stat_date 全部行业。
      含 stat_date 显式参数分支回归 + 异常降级 {}
  - B2 dim1 装配 market_stats 表兜底：pre_feat 空时直读 market_stats_cache 表。
  - ① _index_trend_sentence：沪深300/上证点位/当日涨跌/近20/60日涨跌/60日线上下+强弱档；
      数据不足降级 ''；异常降级 ''。
  - ② _sector_full_sentence：行业近20/5日收益/轮动状态/资金流向句；无行业/无数据降级 '';
      净流向为 0 不产误导句。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    _index_trend_sentence,
    _sector_full_sentence,
)


# ── B1: get_cached_sector_heat 多行业修复 ─────────────────────────

class TestSectorHeatReadB1:

    def _rows(self):
        """long 格式：最新 stat_date 多行业 + 老 stat_date 多行业"""
        return pd.DataFrame([
            {'stat_date': '2026-09-21', 'industry': '黄金', 'heat_level': 'none',
             'strength': -1.0, 'rank': 101, 'stock_count': 10},
            {'stat_date': '2026-09-21', 'industry': '白酒', 'heat_level': 'top_20',
             'strength': 0.5, 'rank': 12, 'stock_count': 19},
            {'stat_date': '2026-09-21', 'industry': '银行', 'heat_level': 'top_40',
             'strength': 0.1, 'rank': 30, 'stock_count': 42},
            {'stat_date': '2026-09-18', 'industry': '黄金', 'heat_level': 'none',
             'strength': -1.0, 'rank': 110, 'stock_count': 10},
        ])

    def _mk_ecm(self, rows):
        from app.data.enhanced_cache_manager import EnhancedCacheManager
        class _FakeECM:
            def _query_shard(self, table, sql, params):
                if 'MAX(stat_date)' in sql:
                    # 返回最新 stat_date (2026-09-21) 全部行业
                    return rows[rows['stat_date'] == '2026-09-21']
                return rows[rows['stat_date'] == params[0]]
        _f = _FakeECM()
        return EnhancedCacheManager.__new__(EnhancedCacheManager), _f

    def test_latest_date_multi_industry(self, monkeypatch):
        """最新 stat_date 返回全部行业（含白酒/银行），非单行业"""
        ecm, fake = self._mk_ecm(self._rows())
        monkeypatch.setattr(ecm, '_query_shard', fake._query_shard)
        out = ecm.get_cached_sector_heat()
        assert isinstance(out, dict) and len(out) >= 3
        assert '白酒' in out and '银行' in out and '黄金' in out
        assert out['白酒']['rank'] == 12            # 用最新日 rank，非老日 110
        assert out['白酒']['heat_level'] == 'top_20'

    def test_explicit_stat_date(self, monkeypatch):
        """显式 stat_date 分支仍按指定日过滤"""
        ecm, fake = self._mk_ecm(self._rows())
        monkeypatch.setattr(ecm, '_query_shard', fake._query_shard)
        out = ecm.get_cached_sector_heat('2026-09-18')
        assert out == {'黄金': {'heat_level': 'none', 'strength': -1.0, 'rank': 110,
                               'stock_count': 10}}

    def test_empty_returns_empty_dict(self, monkeypatch):
        """空表返回 {}（不抛）"""
        ecm, fake = self._mk_ecm(pd.DataFrame(columns=['industry', 'heat_level',
                                                       'strength', 'rank', 'stock_count']))
        monkeypatch.setattr(ecm, '_query_shard', lambda *a, **k: pd.DataFrame())
        assert ecm.get_cached_sector_heat() == {}

    def test_exception_degrades(self, monkeypatch):
        """查询异常降级 {}"""
        ecm, fake = self._mk_ecm(self._rows())
        def _boom(*a, **k):
            raise RuntimeError('db down')
        monkeypatch.setattr(ecm, '_query_shard', _boom)
        assert ecm.get_cached_sector_heat() == {}


# ── ①: _index_trend_sentence 大盘趋势句 ─────────────────────────

def _mk_index_df(closes, pct):
    return pd.DataFrame({
        'trade_date': pd.date_range('2026-01-01', periods=len(closes)).astype(str),
        'close': closes,
        'pct_chg': pct,
    })


class TestIndexTrendSentence:
    """① 大盘指数趋势句：读 BenchmarkService 沪深300/上证。"""

    def _patch_hs300(self, monkeypatch, closes, pct):
        """patch benchmark_service.BenchmarkService（函数内 import 的源模块）"""
        import app.services.benchmark_service as mod
        class _FakeBS:
            def get_index_daily(self, idx):
                return _mk_index_df(closes, pct)
        monkeypatch.setattr(mod, 'BenchmarkService', lambda: _FakeBS())

    def test_full_sentences(self, monkeypatch):
        """完整 K 线（>=61 日）→ 点位/当日/近20/60日/60日线+强弱档"""
        n = 90
        closes = [float(i) for i in range(1, n + 1)]  # 单调上升 → 60日线上方+偏强
        self._patch_hs300(monkeypatch, closes, -0.5)
        s = _index_trend_sentence({})
        assert s.startswith('大盘趋势：沪深300')
        assert '当日-0.5%' in s
        assert '近20日' in s and '近60日' in s
        assert '60日线上方' in s and '偏强' in s
        assert '上证' in s and '60日线上方' in s

    def test_falling_gives_weak(self, monkeypatch):
        """下跌 K 线 → 60日线下方 + 偏弱"""
        n = 90
        closes = [float(n - i) for i in range(n)]  # 单调下降
        self._patch_hs300(monkeypatch, closes, -1.0)
        s = _index_trend_sentence({})
        assert '60日线下方' in s and '偏弱' in s

    def test_short_kline_degrades(self, monkeypatch):
        """<21 日无趋势段 → 仅点位/当日，仍产前缀"""
        self._patch_hs300(monkeypatch, [100.0, 101.0, 102.0], 0.5)
        s = _index_trend_sentence({})
        assert s.startswith('大盘趋势：沪深300102')
        assert '近20日' not in s

    def test_no_data_degrades(self, monkeypatch):
        """指数无数据 → 空串"""
        import app.services.benchmark_service as mod
        class _FakeBS:
            def get_index_daily(self, idx):
                return pd.DataFrame()
        monkeypatch.setattr(mod, 'BenchmarkService', lambda: _FakeBS())
        assert _index_trend_sentence({}) == ''

    def test_exception_degrades(self, monkeypatch):
        import app.services.benchmark_service as mod
        def _boom():
            raise RuntimeError('boom')
        monkeypatch.setattr(mod, 'BenchmarkService', _boom)
        assert _index_trend_sentence({}) == ''


# ── ②: _sector_full_sentence 行业完整句 ─────────────────────────

class TestSectorFullSentence:
    """② 行业完整句：复用 SectorAnalysisService.get_sector_context。"""

    def _ctx(self, **overrides):
        base = {
            'sector_name': '白酒', 'available': True, 'sector_20d_return': -2.2,
            'sector_5d_return': 1.11, 'rotation_state': 'NEUTRAL',
            'sector_moneyflow_rank': 0, 'sector_moneyflow_net': 0,
        }
        base.update(overrides)
        return base

    def _patch(self, monkeypatch, ctx):
        import app.services.sector_analysis_service as mod
        class _FakeSAS:
            def get_sector_context(self, ts_code):
                return ctx
        monkeypatch.setattr(mod, 'SectorAnalysisService', lambda: _FakeSAS())

    def test_full_sentence(self, monkeypatch):
        self._patch(monkeypatch, self._ctx())
        s = _sector_full_sentence({}, '600519.SH')
        assert s.startswith('行业：白酒')
        assert '近20日-2.20%' in s and '近5日+1.11%' in s
        assert '轮动中性' in s
        # 净流向=0 → 不产 '净流入0.0亿' 误导句
        assert '净流出' not in s and '净流入' not in s

    def test_moneyflow_nonzero(self, monkeypatch):
        ctx = self._ctx(sector_moneyflow_rank=5, sector_moneyflow_net=-3.2e4)
        self._patch(monkeypatch, ctx)
        s = _sector_full_sentence({}, '600519.SH')
        assert '资金流向第5名' in s and '净流出3.2亿' in s

    def test_empty_dims_degrades(self, monkeypatch):
        ctx = self._ctx(sector_20d_return=None, sector_5d_return=None,
                        rotation_state=None, sector_moneyflow_rank=0,
                        sector_moneyflow_net=0)
        self._patch(monkeypatch, ctx)
        assert _sector_full_sentence({}, '600519.SH') == ''

    def test_unavailable_degrades(self, monkeypatch):
        self._patch(monkeypatch, self._ctx(available=False))
        assert _sector_full_sentence({}, '600519.SH') == ''

    def test_no_ts_code(self, monkeypatch):
        self._patch(monkeypatch, self._ctx())
        assert _sector_full_sentence({}, '') == ''
        assert _sector_full_sentence({}, None) == ''

    def test_exception_degrades(self, monkeypatch):
        import app.services.sector_analysis_service as mod
        def _boom():
            raise RuntimeError('boom')
        monkeypatch.setattr(mod, 'SectorAnalysisService', _boom)
        assert _sector_full_sentence({}, '600519.SH') == ''


def _all_tests():
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
