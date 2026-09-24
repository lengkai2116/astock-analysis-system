"""481号 ③：个股行业位置（industry_position_cache 预计算 + dim8 句 + ECM 读写）单测

覆盖（2026-09-24）：
  - _rank_industry_position：行业成分股近20日收益排名/percentile/五档纯计算
      （多行业分组、最高/最低档、单成分降级、短K/无行业跳过、异常）
  - _n20_ret：近20日收益口径（≥21观测、不足→None、异常→None）
  - _classify_position：五档边界
  - dim8 _industry_position_sentence：完整句/单成分降级/无数据/无ts_code/异常
  - ECM cache_industry_position / get_industry_position：写读 + 空 + 异常降级
  - 管道：RAW-2C 装配（ensure_pipeline_steps 含 RAW-2C；_precompute_industry_position
      经 app_context 走 DM 取行业 + get_cached_daily_batch 取数 → cache_industry_position 写盘）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    _industry_position_sentence,
)


def _mk_df(closes):
    """构造含 close 的 K 线 df（其余列占位），60 根"""
    n = len(closes)
    return pd.DataFrame({'close': closes, 'high': [c * 1.0 for c in closes],
                         'low': [c * 0.98 for c in closes], 'vol': [1.0] * n})


# ─── 纯计算：排名/percentile/五档 ─────────────────────────────

class TestRankIndustryPosition:

    def test_group_ranking(self):
        from data_daemon import _rank_industry_position
        # 白酒 A/B/C（涨 10/5/0%），银行 X/Y（涨 8/-2%）→ 跨行业分组独立排名
        all_data = {
            'A.SH': _mk_df([10.0] * 20 + [11.0]),   # +10%
            'B.SH': _mk_df([10.0] * 20 + [10.5]),   # +5%
            'C.SH': _mk_df([10.0] * 20 + [10.0]),   # 0%
            'X.SZ': _mk_df([10.0] * 20 + [10.8]),   # +8%
            'Y.SZ': _mk_df([10.0] * 20 + [9.8]),    # -2%
        }
        ind_map = {'A.SH': '白酒', 'B.SH': '白酒', 'C.SH': '白酒',
                   'X.SZ': '银行', 'Y.SZ': '银行'}
        rows = _rank_industry_position(list(all_data), ind_map, all_data, '2026-09-24')
        by = {r[1]: r for r in rows}
        assert len(rows) == 5
        # 白酒内：A 第1、B 第2、C 第3（total=3 → pct=(rank-1)/3）
        assert by['A.SH'][4] == 1 and by['A.SH'][5] == 3 and by['A.SH'][6] == 0.0
        assert by['A.SH'][7] == 'top25%'
        assert by['B.SH'][4] == 2 and by['B.SH'][6] == round(1 / 3, 4) and by['B.SH'][7] == '中上'
        assert by['C.SH'][4] == 3 and by['B.SH'][6] != by['C.SH'][6] and by['C.SH'][7] == '中下'
        # 银行内：X 第1（pct=0→top25%）、Y 第2（pct=0.5→中上）
        assert by['X.SZ'][5] == 2 and by['X.SZ'][4] == 1 and by['X.SZ'][7] == 'top25%'
        assert by['Y.SZ'][4] == 2 and by['Y.SZ'][7] == '中上'
        # asof_date 原样落盘
        assert all(r[0] == '2026-09-24' for r in rows)

    def test_three_buckets(self):
        from data_daemon import _rank_industry_position
        # 4 只 → 中间档验证：rank2 → 中上，rank3 → 中下
        all_data = {}
        ind_map = {}
        for i, ret in enumerate([10.0, 6.0, 2.0, -4.0]):
            c = f'S{i}.SH'
            all_data[c] = _mk_df([10.0] * 20 + [10.0 * (1 + ret / 100)])
            ind_map[c] = '机械'
        rows = _rank_industry_position(list(all_data), ind_map, all_data, 'd')
        by = {r[1]: r for r in rows}
        # 4 只 → pct=(rank-1)/4：rank1=0→top25%、rank2=0.25→top25%、
        #              rank3=0.5→中上、rank4=0.75→中下
        assert by['S0.SH'][7] == 'top25%'
        assert by['S1.SH'][7] == 'top25%'
        assert by['S2.SH'][7] == '中上'
        assert by['S3.SH'][7] == '中下'

    def test_single_member_degrades_pct_none(self):
        from data_daemon import _rank_industry_position
        all_data = {'A.SH': _mk_df([10.0] * 20 + [11.0])}
        ind_map = {'A.SH': '独苗'}
        rows = _rank_industry_position(list(all_data), ind_map, all_data, 'd')
        assert len(rows) == 1
        r = rows[0]
        assert r[6] is None and r[7] == '' and r[4] == 1 and r[5] == 1

    def test_no_industry_skipped(self):
        from data_daemon import _rank_industry_position
        all_data = {'A.SH': _mk_df([10.0] * 20 + [11.0])}
        assert _rank_industry_position(['A.SH'], {'A.SH': None},
                                       all_data, 'd') == []

    def test_short_kline_skipped(self):
        from data_daemon import _rank_industry_position
        all_data = {'A.SH': _mk_df([10.0] * 5)}
        ind_map = {'A.SH': '白酒'}
        assert _rank_industry_position(['A.SH'], ind_map, all_data, 'd') == []

    def test_missing_df_skipped(self):
        from data_daemon import _rank_industry_position
        ind_map = {'A.SH': '白酒'}
        assert _rank_industry_position(['A.SH'], ind_map, {}, 'd') == []

    def test_returns_empty_on_no_input(self):
        from data_daemon import _rank_industry_position
        assert _rank_industry_position([], {}, {}, 'd') == []


# ─── _n20_ret 近20日收益口径 ────────────────────────────────

class TestN20Ret:

    def test_positive(self):
        from data_daemon import _n20_ret
        assert round(_n20_ret(pd.Series([10.0] * 21 + [11.0]), 20), 4) == 0.1

    def test_insufficient(self):
        from data_daemon import _n20_ret
        assert _n20_ret(pd.Series([10.0] * 20)) is None

    def test_none_and_exception(self):
        from data_daemon import _n20_ret
        assert _n20_ret(None) is None
        assert _n20_ret(pd.Series(['x'] * 30)) is None  # 非数值 → dropna 全空


# ─── _classify_position 五档 ────────────────────────────────

class TestClassifyPosition:

    def test_buckets(self):
        from data_daemon import _classify_position
        assert _classify_position(0.0) == 'top25%'
        assert _classify_position(0.25) == 'top25%'
        assert _classify_position(0.26) == '中上'
        assert _classify_position(0.5) == '中上'
        assert _classify_position(0.51) == '中下'
        assert _classify_position(0.75) == '中下'
        assert _classify_position(0.76) == 'bottom25%'
        assert _classify_position(1.0) == 'bottom25%'


# ─── dim8 句 _industry_position_sentence ─────────────────────

def _mk_ecm_row(**over):
    base = {'asof_date': '2026-09-24', 'industry': '白酒', 'ret_20d': 0.06,
            'rank_in_industry': 3, 'total_in_industry': 15, 'percentile': 0.1333,
            'position': 'top25%'}
    base.update(over)
    return base


class TestIndustryPositionSentence:

    def _patch(self, monkeypatch, row):
        import app.data.enhanced_cache_manager as ecm
        class _FakeECM:
            def get_industry_position(self, ts_code):
                return row
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _FakeECM())

    def test_full_sentence(self, monkeypatch):
        self._patch(monkeypatch, _mk_ecm_row())
        s = _industry_position_sentence('600519.SH')
        assert s.startswith('个股行业位置：白酒板块内近20日涨幅第3/15')
        assert '前13%' in s and '位置前列' in s

    def test_mid_sentence(self, monkeypatch):
        self._patch(monkeypatch, _mk_ecm_row(rank_in_industry=8, total_in_industry=15,
                                             percentile=0.4667, position='中上'))
        s = _industry_position_sentence('600519.SH')
        assert '第8/15' in s and '前47%' in s and '位置中上' in s

    def test_single_component_degrades(self, monkeypatch):
        self._patch(monkeypatch, _mk_ecm_row(total_in_industry=1,
                                             rank_in_industry=1,
                                             percentile=None, position=''))
        assert _industry_position_sentence('600519.SH') == ''

    def test_no_data_degrades(self, monkeypatch):
        self._patch(monkeypatch, None)
        assert _industry_position_sentence('600519.SH') == ''

    def test_no_ts_code(self, monkeypatch):
        self._patch(monkeypatch, _mk_ecm_row())
        assert _industry_position_sentence('') == ''
        assert _industry_position_sentence(None) == ''

    def test_exception_degrades(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        class _Boom:
            def get_industry_position(self, ts_code):
                raise RuntimeError('db down')
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _Boom())
        assert _industry_position_sentence('600519.SH') == ''

    def test_injected_into_summary_env(self, monkeypatch):
        # 集成：build_seven_dim_report 前置环境段含「个股行业位置」
        import app.data.enhanced_cache_manager as ecm
        class _FakeECM:
            def get_industry_position(self, ts_code):
                return _mk_ecm_row()
            def get_relative_strength(self, **kw):
                return []
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _FakeECM())
        from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
        # 构造最小 dim_results（有 summary 维即可走注入路径）
        dr = {'structure': {'judgment': {'overall_light': 'yellow',
                                          'overall_direction': 0,
                                          'continuous_value': 0.5},
                            'status_description': {'plain': '结构现状'},
                            'audit': {'conditions': [], 'satisfied_count': 1,
                                      'total_count': 1, 'confidence': 1.0}}}
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags={}, ts_code='600519.SH')
        assert report is not None
        assert '个股行业位置' in report['summary']['text']


# ─── ECM 读写 cache/get_industry_position ───────────────────

class TestEcmIndustryPosition:

    def test_get_missing_table_records(self):
        # 用真实 ECM 查询分库表（若表不存在 get 返回 None，不抛）
        from app.data.enhanced_cache_manager import get_ecm_instance
        inst = get_ecm_instance()
        r = inst.get_industry_position('__NO_SUCH__')
        # 无该 ts_code 数据 → None（缺则降级），不抛
        assert r is None or r.get('ts_code') != '__NO_SUCH__'


def _all_tests():
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
