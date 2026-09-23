"""479号-2 dim2 补产出单测（A1 中枢区位比例 / A2 reason中文+窗口截取 / A3 divergence
details+dual_confirmed / A4 theorem_check.details）

覆盖（479-2，dim2 定稿 §六 补产出 ①③④⑤）：
  - A1 _assess_vs_zhongshu 返回 ratio（区间内 0~1、上方>1、下方<0；无有效中枢 None）
  - A2 _cn_reason type 转中文；evaluate 买卖点窗口截取（_recent_by_type k=3）
  - A3 _fmt_divergence_details 中文明细；evaluate status_description 透传 details/dual_confirmed
  - A4 _fmt_theorem_details 11 定理逐条（含"跳过/占位"标注保留）
  - dim8 侧：_flatten_value 买卖点带 reason；E 表 structure 含新字段
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace
from unittest import mock

from app.opportunity_atlas.dimensions import dim2_structure_engine as dim2
from app.opportunity_atlas.dimensions.dim2_structure_engine import (
    Dim2StructureEngine,
    _assess_vs_zhongshu,
    _cn_reason,
    _fmt_divergence_details,
    _fmt_theorem_details,
)


def _mk_df(n=90):
    closes = np.linspace(10, 20, n) + np.sin(np.linspace(0, 8, n)) * 0.5
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    df = pd.DataFrame({
        'ts_code': 'T.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes, 'vol': [1e5] * n, 'amount': [3e5] * n,
    }, index=idx)
    df['trade_date'] = df.index.strftime('%Y-%m-%d')
    return df


def _mk_zs(high=15.0, low=10.0):
    return SimpleNamespace(high=high, low=low,
                           start_date='2025-02-01', end_date='2025-04-30')


def _mk_buy(conf, ptype='first_buy', price=12.0, idx=40, reason='上涨趋势背驰，zhongshu类型'):
    return SimpleNamespace(
        type=ptype, confidence=conf,
        position={'price': price, 'date': '2025-04-01', 'idx': idx},
        reason=reason)


# ── A1: 中枢区位比例 ───────────────────────────────────────

class TestZhongshuLocationRatio:

    def test_ratio_inside(self):
        """价格在中枢内部 → 0<ratio<1"""
        r = _assess_vs_zhongshu({}, {}, chanlun_result={'zhongshu': [_mk_zs(15, 10)]},
                                latest_close=12.5)
        assert r['position'] == '内部'
        assert r['ratio'] == pytest.approx(0.5, abs=0.01)

    def test_ratio_above(self):
        """价格在中枢上方 → ratio>1"""
        r = _assess_vs_zhongshu({}, {}, chanlun_result={'zhongshu': [_mk_zs(15, 10)]},
                                latest_close=20.0)
        assert r['position'] == '上方'
        assert r['ratio'] > 1.0

    def test_ratio_below(self):
        """价格在中枢下方 → ratio<0"""
        r = _assess_vs_zhongshu({}, {}, chanlun_result={'zhongshu': [_mk_zs(15, 10)]},
                                latest_close=5.0)
        assert r['position'] == '下方'
        assert r['ratio'] < 0.0

    def test_ratio_none_when_no_zs(self):
        """无有效中枢 → ratio=None（降级，不占位）"""
        r = _assess_vs_zhongshu({}, {}, chanlun_result={'zhongshu': []}, latest_close=12.5)
        assert r['position'] == '无有效中枢'
        assert r['ratio'] is None

    def test_status_description_has_ratio(self):
        """evaluate status_description 透传 zhongshu_location_ratio"""
        with mock.patch.object(dim2, 'ChanlunAnalyzer') as _MockAna:
            _MockAna.return_value.analyze.return_value = {
                'trend': 'up', 'trend_basis': '价格突破中枢上沿',
                'zhongshu': [_mk_zs(15, 10)],
                'divergence': None, 'buy_points': [], 'sell_points': [],
                'theorem_check': {'summary': {'overall_score': 0.7},
                                  'details': {'t1': {'passed': True, 'score': 1.0,
                                                     'issues': [], 'description': '分型有效'}}},
            }
            eng = Dim2StructureEngine()
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                res = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={})
            sd = res['status_description']
            # latest_close≈20 > high=15 → 上方，ratio>1
            assert sd['zhongshu_location_ratio'] is not None
            assert sd['zhongshu_location_ratio'] > 1.0


# ── A2: reason 中文 + 窗口截取 ─────────────────────────────

class TestReasonCnAndWindow:

    def test_cn_reason_type(self):
        """'zhongshu类型'→'中枢背驰'；trend/consolidation 同映射"""
        assert _cn_reason('上涨趋势背驰，zhongshu类型') == '上涨趋势背驰，中枢背驰'
        assert _cn_reason('下跌趋势背驰，trend类型') == '下跌趋势背驰，趋势背驰'
        assert _cn_reason('盘整背驰，consolidation类型') == '盘整背驰，盘整背驰'
        assert _cn_reason('') == ''
        assert _cn_reason('无英文类型') == '无英文类型'

    def test_window_cut_to_recent(self):
        """买卖点窗口截取：同 type 4 个 → 只保留 idx 最近 3 个（465-1A _recent_by_type）"""
        with mock.patch.object(dim2, 'ChanlunAnalyzer') as _MockAna:
            _MockAna.return_value.analyze.return_value = {
                'trend': 'down', 'trend_basis': '价格跌破中枢下沿',
                'zhongshu': [],
                'divergence': None,
                'buy_points': [],
                # 4 个历史三卖（idx 10/20/30/40）→ 截取最近 3 个
                'sell_points': [_mk_buy(0.8, ptype='third_sell', idx=10),
                                _mk_buy(0.8, ptype='third_sell', idx=20),
                                _mk_buy(0.8, ptype='third_sell', idx=30),
                                _mk_buy(0.8, ptype='third_sell', idx=40)],
                'theorem_check': {'summary': {'overall_score': 0.5},
                                  'details': {}},
            }
            eng = Dim2StructureEngine()
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                res = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={})
            sd = res['status_description']
            bsp = sd['buy_sell_points_detail']
            assert len(bsp) == 3, f'窗口截取应保留 3 个，实际 {len(bsp)}'
            idxs = sorted(p['index'] for p in bsp)
            assert idxs == [20, 30, 40]

    def test_reason_cn_in_evaluate(self):
        """evaluate 序列化 reason 已中文化（'zhongshu类型'→'中枢背驰'）"""
        with mock.patch.object(dim2, 'ChanlunAnalyzer') as _MockAna:
            _MockAna.return_value.analyze.return_value = {
                'trend': 'down', 'trend_basis': 'x',
                'zhongshu': [], 'divergence': None,
                'buy_points': [_mk_buy(0.8, ptype='first_buy', idx=40)],
                'sell_points': [],
                'theorem_check': {'summary': {'overall_score': 0.5}, 'details': {}},
            }
            eng = Dim2StructureEngine()
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                res = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={})
            bsp = res['status_description']['buy_sell_points_detail']
            assert any('中枢背驰' in p['reason'] for p in bsp)
            assert all('zhongshu类型' not in p['reason'] for p in bsp)


# ── A3: divergence details + dual_confirmed ────────────────

class TestDivergenceDetails:

    def test_fmt_trend_details(self):
        """趋势背驰 details → 中文明细（力度比/MACD面积比/确认）"""
        details = {'strength_ratio': 0.46, 'macd_area_ratio': 0.22, 'macd_confirmed': True}
        out = _fmt_divergence_details(details)
        assert any('力度比:0.46' in s for s in out)
        assert any('MACD面积比:0.22' in s for s in out)
        assert any('MACD确认:确认' in s for s in out)

    def test_fmt_zhongshu_repr_skipped(self):
        """中枢背驰 details 仅 repr → 跳过（framework 侧缺口，定稿④）"""
        assert _fmt_divergence_details({'zhongshu': 'Zhongshu(up,[1250.10,1292.70])'}) == []

    def test_evaluate_passthrough(self):
        """evaluate status_description 透传 divergence_details + divergence_dual_confirmed"""
        with mock.patch.object(dim2, 'ChanlunAnalyzer') as _MockAna:
            _div = SimpleNamespace(direction='down', type='trend', confidence=0.8,
                                   dual_confirmed=True,
                                   details={'strength_ratio': 0.46, 'macd_area_ratio': 0.22,
                                            'macd_confirmed': True})
            _MockAna.return_value.analyze.return_value = {
                'trend': 'down', 'trend_basis': 'x',
                'zhongshu': [], 'divergence': _div,
                'buy_points': [], 'sell_points': [],
                'theorem_check': {'summary': {'overall_score': 0.5}, 'details': {}},
            }
            eng = Dim2StructureEngine()
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                res = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={})
            sd = res['status_description']
            assert sd['divergence_dual_confirmed'] is True
            assert any('力度比:0.46' in s for s in sd['divergence_details'])

    def test_no_divergence_empty(self):
        """无背驰 → divergence_details 空列表、dual_confirmed False"""
        with mock.patch.object(dim2, 'ChanlunAnalyzer') as _MockAna:
            _MockAna.return_value.analyze.return_value = {
                'trend': 'up', 'trend_basis': 'x',
                'zhongshu': [], 'divergence': None,
                'buy_points': [], 'sell_points': [],
                'theorem_check': {'summary': {'overall_score': 0.7}, 'details': {}},
            }
            eng = Dim2StructureEngine()
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                res = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={})
            sd = res['status_description']
            assert sd['divergence_details'] == []
            assert sd['divergence_dual_confirmed'] is False


# ── A4: theorem_check.details ──────────────────────────────

class TestTheoremDetails:

    def test_fmt_eleven_rules(self):
        """11 定理逐条：通过/未通过 + score + description（含跳过标注保留）"""
        tc = {'summary': {'passed': 5, 'total': 11, 'overall_score': 0.6},
              'details': {
                  't1': {'passed': True, 'score': 1.0, 'issues': [], 'description': '分型有效'},
                  't4': {'passed': True, 'score': 1.0, 'issues': [], 'description': '数据不足，跳过'},
                  't9': {'passed': True, 'score': 1.0, 'issues': [], 'description': '占位实现（无中枢后数据）'},
                  't10': {'passed': False, 'score': 0.0, 'issues': ['下降趋势', '顶背驰'],
                          'description': '趋势结构健康'},
              }}
        out = _fmt_theorem_details(tc)
        joined = '；'.join(out)
        assert any(s.startswith('t1 通过(1.00) 分型有效') for s in out)
        # 跳过/占位标注保留（与真实 FAIL 区分，定稿⑤）
        assert any('数据不足，跳过' in s for s in out)
        assert any('占位实现' in s for s in out)
        assert any(s.startswith('t10 未通过(0.00) 趋势结构健康：下降趋势、顶背驰') for s in out)
        # t1 < t4 < t9 < t10 自然排序
        assert joined.index('t1') < joined.index('t4') < joined.index('t9') < joined.index('t10')

    def test_empty_returns_empty(self):
        """无 theorem_check → []"""
        assert _fmt_theorem_details(None) == []
        assert _fmt_theorem_details({}) == []
        assert _fmt_theorem_details({'details': {}}) == []

    def test_evaluate_passthrough(self):
        """evaluate status_description 透传 theorem_check_details"""
        with mock.patch.object(dim2, 'ChanlunAnalyzer') as _MockAna:
            _MockAna.return_value.analyze.return_value = {
                'trend': 'up', 'trend_basis': 'x',
                'zhongshu': [], 'divergence': None,
                'buy_points': [], 'sell_points': [],
                'theorem_check': {'summary': {'overall_score': 0.7},
                                  'details': {'t1': {'passed': True, 'score': 1.0,
                                                     'issues': [], 'description': '分型有效'}}},
            }
            eng = Dim2StructureEngine()
            with mock.patch.object(eng, '_get_dm') as _dm:
                _dm.return_value.cache.get_cached_daily.return_value = _mk_df()
                res = eng.evaluate({}, {'ts_code': 'T.XSHG'}, data_context={})
            sd = res['status_description']
            assert any('分型有效' in s for s in sd['theorem_check_details'])


# ── dim8 侧：_flatten_value reason + E 表字段 ──────────────

class TestDim8Side:

    def test_flatten_bsp_with_reason(self):
        """dim8 _flatten_value 买卖点带 reason（A2 双重缺口第二半）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _flatten_value
        v = {'type': 'sell', 'point_type': 'first_sell', 'price': 1323.0,
             'reason': '上涨趋势背驰，中枢背驰'}
        s = _flatten_value(v)
        assert '一卖(1323.0)' in s
        assert '上涨趋势背驰，中枢背驰' in s

    def test_e_table_has_new_fields(self):
        """dim8 E 表 structure 含 479-2 新透传字段"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _DIM8_E_FIELDS, _DIM8_E_FORMAT
        s = _DIM8_E_FIELDS['structure']
        assert 'zhongshu_location_ratio' in s
        assert 'divergence_details' in s
        assert 'divergence_dual_confirmed' in s
        assert 'theorem_check_details' in s
        assert 'zhongshu_location_ratio' in _DIM8_E_FORMAT

    def test_evidence_from_new_fields(self):
        """dim8 evidence 消费新字段（中枢区位比格式/背驰明细/定理明细）"""
        from app.opportunity_atlas.dimensions.dim8_summary_engine import _compose_dim_evidence
        sd = {'vs_zhongshu': '价格位于中枢上方',
              'zhongshu_location_ratio': 1.5,
              'divergence_details': ['力度比:0.46', 'MACD面积比:0.22'],
              'divergence_dual_confirmed': True,
              'theorem_check_details': ['t1 通过(1.00) 分型有效', 't4 通过(1.00) 数据不足，跳过']}
        ev = _compose_dim_evidence('structure', sd)
        joined = '；'.join(ev)
        assert '中枢区位比1.50' in joined
        assert '力度比:0.46' in joined
        # E 表 evidence 机制不带字段标签（subsections 才带）；bool 值裸展示 True
        assert 'True' in ev
        assert 't4 通过(1.00) 数据不足，跳过' in joined
