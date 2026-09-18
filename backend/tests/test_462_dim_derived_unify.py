"""462号：444 事实层剩余收尾回归测试

- 462-1 right_side_confirm 值域统一：RAW-2 derived 接 _check_right_side_confirm 四档中文
  （否决/强确认/基础确认/未确认），消除 SIG 消费方（arbiter P0-P6 / factor_arbiter 门控 /
  conflict_matrix / signal_analyzer / dim6:403）判中文四档、derived 产英文两值恒不触发错位
- 462-2 active_signal 补产 dict：{type,date,price} JSON，信号生命周期（334 §5.3）真实化
- 462-3 相对强弱接线：dim8 summary 段前置环境定位句（437-A D3）

边界：只改值域/生产点/口径（事实层），不触碰任何判定条件集。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd
import pytest

from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine,
    _relative_strength_sentence,
)
from app.opportunity_atlas.status_engine import build_seven_dim_from_dim_results


def _mk_df(closes, vols=None):
    """构造 K 线 df（close/vol/high/low 列，60 根）"""
    n = len(closes)
    highs = [c * 1.02 for c in closes]
    lows = [c * 0.98 for c in closes]
    if vols is None:
        vols = [1.0] * n
    return pd.DataFrame({'close': closes, 'high': highs, 'low': lows, 'vol': vols})


def _mk_dim_results():
    base = {}
    for dim in ['signal', 'structure', 'volume_price', 'chip_fund',
                'emotion', 'risk', 'valuation']:
        base[dim] = {
            'judgment': {'overall_light': 'yellow', 'overall_direction': 0,
                         'continuous_value': 0.5},
            'status_description': {'plain': f'{dim}现状说明'},
            'audit': {'conditions': [{'name': f'{dim}条件1', 'satisfied': True}],
                      'satisfied_count': 1, 'total_count': 1, 'confidence': 1.0},
        }
    return base


# ═══════════════════════════════════════════════════════════
# 462-1 right_side_confirm 四档值域（_check_right_side_confirm）
# ═══════════════════════════════════════════════════════════

class TestRightSideConfirmDomain:
    """值域对齐：_check_right_side_confirm 产中文四档，SIG 消费方判读一致"""

    @pytest.fixture(autouse=True)
    def _no_trend(self, monkeypatch):
        # 屏蔽 TrendStructureDetector 增强分支，保证 基础确认/强确认 判定确定
        from app.engine.framework import trend_structure_detector as tsd

        class _NoDetect:
            def detect(self, df):
                return {'signal': None}

        monkeypatch.setattr(tsd, 'TrendStructureDetector', lambda: _NoDetect())

    def _rsc(self, tags, df):
        from data_daemon import _check_right_side_confirm
        return _check_right_side_confirm('', tags, df)['right_side_confirm']

    def test_vpf_diverging_veto(self):
        # 量价背离 → 否决（600519/300750 实测 vpf=diverging 现被两值代理吞成 unconfirmed）
        df = _mk_df([10.0] * 60)
        tags = {'buy_sell_point': 'none', 'volume_price_fit': 'diverging',
                'pattern_signal': 'none'}
        assert self._rsc(tags, df) == '否决'

    def test_first_sell_veto(self):
        df = _mk_df([10.0] * 60)
        tags = {'buy_sell_point': 'first_sell', 'volume_price_fit': 'neutral',
                'pattern_signal': 'none'}
        assert self._rsc(tags, df) == '否决'

    def test_predict_down_pattern_veto(self):
        df = _mk_df([10.0] * 60)
        tags = {'buy_sell_point': 'none', 'volume_price_fit': 'neutral',
                'pattern_signal': '预跌形态'}
        assert self._rsc(tags, df) == '否决'

    def test_second_sell_downgrade_unconfirmed(self):
        # 弱卖点（second_sell）降级未确认（325 档案修复：收缩否决面）
        df = _mk_df([10.0] * 60)
        tags = {'buy_sell_point': 'second_sell', 'volume_price_fit': 'neutral',
                'pattern_signal': 'none'}
        assert self._rsc(tags, df) == '未确认'

    def test_no_base_unconfirmed(self):
        # 收盘低于 MA20 且无放量 → 基础确认不满足 → 未确认
        closes = [10.0] * 40 + [9.0] * 20
        df = _mk_df(closes, vols=[2.0] * 60)
        tags = {'buy_sell_point': 'none', 'volume_price_fit': 'neutral',
                'pattern_signal': 'none'}
        assert self._rsc(tags, df) == '未确认'

    def test_strong_confirm_with_second_buy(self):
        # second_buy + 放量站上 MA20（df≥100 触发中期趋势向上增强）→ 增强=2 → 强确认
        closes = [10.0] * 90 + [12.5] * 15
        vols = [1.0] * 100 + [3.0] * 5
        df = _mk_df(closes, vols=vols)
        tags = {'buy_sell_point': 'second_buy', 'volume_price_fit': 'healthy',
                'pattern_signal': 'none'}
        assert self._rsc(tags, df) == '强确认'

    def test_base_confirm_no_enhance(self):
        # 放量站上 MA20 但无买点 → 仅中期趋势向上 +1 → 基础确认
        closes = [10.0] * 90 + [12.5] * 15
        vols = [1.0] * 100 + [3.0] * 5
        df = _mk_df(closes, vols=vols)
        tags = {'buy_sell_point': 'none', 'volume_price_fit': 'healthy',
                'pattern_signal': 'none'}
        assert self._rsc(tags, df) == '基础确认'

    def test_derived_production_uses_check_rsc(self):
        # 源码断言：derived 组 right_side_confirm 改接 _check_right_side_confirm
        # （生产赋值形态，避免命中注释）
        import data_daemon
        src = open(data_daemon.__file__, encoding='utf-8').read()
        assert "_derived['right_side_confirm'] = _rsc.get('right_side_confirm', '未确认')" in src
        # 原英文两值代理已移除
        assert "'strong_confirm' if _cl.get('buy_sell_point', '') in ('first_buy', 'second_buy')" not in src


# ═══════════════════════════════════════════════════════════
# 462-2 active_signal 补产 dict（_build_active_signal 纯函数）
# ═══════════════════════════════════════════════════════════

class _Pt:
    def __init__(self, type_, position):
        self.type = type_
        self.position = position


class TestActiveSignalDict:

    def test_no_point_none(self):
        from data_daemon import _build_active_signal
        assert _build_active_signal({}, '') is None
        assert _build_active_signal({}, 'none') is None

    def test_matched_builds_json(self):
        from data_daemon import _build_active_signal
        cl = {'buy_points': [_Pt('second_buy', {'idx': 5, 'price': 10.2, 'date': '2026-09-10'})]}
        out = _build_active_signal(cl, 'second_buy')
        d = json.loads(out)
        assert d == {'type': 'second_buy', 'date': '2026-09-10', 'price': 10.2}

    def test_buy_priority_over_sell(self):
        from data_daemon import _build_active_signal
        cl = {'buy_points': [_Pt('first_buy', {'idx': 1, 'price': 9.1, 'date': '2026-09-01'})],
              'sell_points': [_Pt('first_sell', {'idx': 2, 'price': 11.0, 'date': '2026-09-02'})]}
        d = json.loads(_build_active_signal(cl, 'first_buy'))
        assert d['type'] == 'first_buy' and d['price'] == 9.1

    def test_sell_point_matched(self):
        from data_daemon import _build_active_signal
        cl = {'sell_points': [_Pt('second_sell', {'idx': 3, 'price': 8.8, 'date': '2026-09-05'})]}
        d = json.loads(_build_active_signal(cl, 'second_sell'))
        assert d['type'] == 'second_sell' and d['date'] == '2026-09-05'

    def test_unmatched_fallback_enum(self):
        from data_daemon import _build_active_signal
        # 详情里无匹配类型 → 回退枚举字符串（生命周期降级，不产假 dict）
        cl = {'buy_points': [_Pt('third_buy', {'idx': 5, 'price': 10.2, 'date': '2026-09-10'})]}
        assert _build_active_signal(cl, 'first_buy') == 'first_buy'

    def test_no_price_fallback_enum(self):
        from data_daemon import _build_active_signal
        cl = {'buy_points': [_Pt('second_buy', {'idx': 5})]}
        assert _build_active_signal(cl, 'second_buy') == 'second_buy'

    def test_signal_lifecycle_consumes_dict(self):
        # 集成：_signal_lifecycle 能解析 dict JSON 并算生命周期（初期/已延伸/回撤）
        from app.opportunity_atlas.status_engine import StatusEngine

        class _DM:
            def __init__(self, closes):
                self._closes = closes
            def get_cached_daily_data(self, ts_code):
                return _mk_df(self._closes)

        # 信号价 10.0；当前价 10.5 → +5% → 初期；12.5 → +25% → 已延伸；9.5 → -5% → 回撤
        se = StatusEngine(dm=_DM([10.0] * 50 + [10.5]))
        sig = json.dumps({'type': 'second_buy', 'date': '2026-09-10', 'price': 10.0})
        lc = se._signal_lifecycle('000001.SZ', {'active_signal': sig}, {})
        assert lc is not None
        assert lc.get('stage') == '初期'

        se2 = StatusEngine(dm=_DM([10.0] * 50 + [12.5]))
        lc2 = se2._signal_lifecycle('000001.SZ', {'active_signal': sig}, {})
        assert lc2.get('stage') == '已延伸'

        se3 = StatusEngine(dm=_DM([10.0] * 50 + [9.5]))
        lc3 = se3._signal_lifecycle('000001.SZ', {'active_signal': sig}, {})
        assert lc3.get('stage') == '回撤'

    def test_derived_production_uses_helper(self):
        import data_daemon
        src = open(data_daemon.__file__, encoding='utf-8').read()
        assert "_derived['active_signal'] = _build_active_signal(" in src


# ═══════════════════════════════════════════════════════════
# 462-4 RAW-2 估值组 app_context 修复（子线程无 context 恒空）
# ═══════════════════════════════════════════════════════════

class TestValuationBlockAppContext:
    """估值块包 _raw_app.app_context()（同 sector 块先例），子线程 db.session 依赖有 context"""

    def test_valuation_block_wraps_app_context(self):
        import data_daemon
        src = open(data_daemon.__file__, encoding='utf-8').read()
        # 生产赋值形态断言（避免命中注释）：ve.compute_tags 调用被 app_context 包裹
        assert "with _raw_app.app_context():\n                    v_tags = ve.compute_tags(code)" in src

    def test_sector_block_still_wrapped(self):
        # 对照：sector 块包裹仍在（442 号缺陷④修复未被破坏）
        import data_daemon
        src = open(data_daemon.__file__, encoding='utf-8').read()
        assert "with _raw_app.app_context():\n                    sector = sr.evaluate(code)" in src


# ═══════════════════════════════════════════════════════════
# 462-3 相对强弱并入 summary 段（_relative_strength_sentence + 注入）
# ═══════════════════════════════════════════════════════════

def _fake_ecm(rows):
    class _ECM:
        def get_relative_strength(self, ts_code=None, asof_date=None, benchmark=None):
            return rows
    return _ECM()


_RS_ROWS = [
    {'asof_date': '2026-09-16', 'ts_code': '000001.SZ', 'benchmark': '000300.SH',
     'ret_20d': 0.07, 'ret_60d': 0.10, 'ex_ret_20d': 0.1247, 'ex_ret_60d': 0.2182},
    {'asof_date': '2026-09-16', 'ts_code': '000001.SZ', 'benchmark': '000001.SH',
     'ret_20d': 0.07, 'ret_60d': 0.10, 'ex_ret_20d': -0.0941, 'ex_ret_60d': None},
    {'asof_date': '2026-09-15', 'ts_code': '000001.SZ', 'benchmark': '000300.SH',
     'ret_20d': 0.05, 'ret_60d': 0.08, 'ex_ret_20d': 0.10, 'ex_ret_60d': 0.15},
]


class TestRelativeStrengthSentence:

    def test_sentence_format(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm(_RS_ROWS))
        s = _relative_strength_sentence('000001.SZ')
        assert '相对强弱' in s
        assert '跑赢沪深300' in s and '12.5%' in s and '21.8%' in s
        assert '跑输上证' in s and '9.4%' in s
        # 60d 上证 ex_ret 为 None → 只表述 20d（缺则降级，不输出空段）
        assert s.count('上证') == 1

    def test_latest_asof_only(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm(_RS_ROWS))
        s = _relative_strength_sentence('000001.SZ')
        # 只用 asof 2026-09-16（09-15 的 10.0% 不应出现）
        assert '10.0%' not in s

    def test_empty_rows(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm([]))
        assert _relative_strength_sentence('000001.SZ') == ''

    def test_no_ts_code(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm(_RS_ROWS))
        assert _relative_strength_sentence('') == ''
        assert _relative_strength_sentence(None) == ''

    def test_exception_degrades(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        class _Boom:
            def get_relative_strength(self, **kw):
                raise RuntimeError('db down')
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _Boom())
        assert _relative_strength_sentence('000001.SZ') == ''


class TestSummaryInjection:

    def test_summary_prepends_env_sentence(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm(_RS_ROWS))
        dr = _mk_dim_results()
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags={}, ts_code='000001.SZ')
        assert '相对强弱' in report['summary']['text']
        assert '相对强弱' in report['summary']['plain']
        assert report['summary']['plain'].count('相对强弱') == 1

    def test_no_ts_code_no_injection(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm(_RS_ROWS))
        dr = _mk_dim_results()
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags={})
        assert '相对强弱' not in report['summary']['text']

    def test_entry_point_passes_ts_code(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm(_RS_ROWS))
        dr = _mk_dim_results()
        report = build_seven_dim_from_dim_results(dr, tags={}, ts_code='000001.SZ')
        assert '相对强弱' in report['summary']['text']

    def test_six_dim_contract_unchanged(self, monkeypatch):
        import app.data.enhanced_cache_manager as ecm
        monkeypatch.setattr(ecm, 'get_ecm_instance', lambda: _fake_ecm(_RS_ROWS))
        dr = _mk_dim_results()
        report = Dim8SummaryEngine().build_seven_dim_report(dr, tags={}, ts_code='000001.SZ')
        assert set(report.keys()) == {'signal', 'structure', 'volume_price', 'fund_chip',
                                      'emotion', 'risk', 'summary'}
