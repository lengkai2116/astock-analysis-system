"""RPS 链路断点回归测试

背景（dim3 代码审查实证，2026-09-20）：
  三股真实运行验证 600519/000001/300750 的 audit「相对强弱RPS」全部恒不满足（RPS=nan）。
  根因两层：
    ① enhanced_cache_manager.get_relative_strength ORDER BY ts_code, benchmark 未按 asof_date
       排序 → 同 ts_code+benchmark 多 asof 行（旧行 rps 为 None）按插入序返回，消费方取 [0]
       永远命中旧/空行（表实证 2026-09-14 行 rps=None、2026-09-16 行 rps 有效）。
    ② pandas to_dict('records') 浮点列会把 SQL None → nan（Python 里 NaN 自不等、非 None），
       dim3 原 `rps_eff is None` 判据失效 → float(nan)>85 恒假 → audit 恒定不满足。

修复：
  ① get_relative_strength 增 asof_date DESC 排序（最新交易日优先）。
  ② dim3 读 rps_20d/rps_60d 用 _safe_rps 归一（None/NaN 均视为"无数据"，回退 60d/中性放行）。

知识库权威：RPS>85 → +1 分（《量价形态打分系统》）；数据不足时中性放行（不扣分）。
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine


def _mk_df(n=70):
    rng = np.random.RandomState(0)
    closes = np.linspace(10, 25, n)
    vols = rng.uniform(1000, 5000, n).astype(float)
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    return pd.DataFrame({
        'ts_code': 'TEST.XSHG', 'open': closes,
        'high': closes * 1.01, 'low': closes * 0.99,
        'close': closes, 'vol': vols,
    }, index=idx)


_P_BASE = {'volume_price_fit': 'healthy', 'volume_ratio': 2.5,
           'ma_alignment': 'bullish', 'chip_concentration': 'concentrating', 'rsi': 65}


def _asof_key(s):
    """asof_date 'YYYY-MM-DD' → 可排序整数键（越大越新）"""
    return int(s.replace('-', ''))


class TestGetRelativeStrengthLatestAsOf:
    """get_relative_strength 排序修复：最新 asof 行优先（不再命中间隙期 None 行）"""

    def _shard_for(self, rows):
        """SQL 层真实排序由 _query_shard 执行（ORDER BY ts_code, asof_date DESC, benchmark）。
        这里用 mock 模拟已排序结果：调用前先按 asof_date DESC 排，断言消费方拿到的 [0] 是最新行。
        """
        from unittest.mock import patch
        from app.data.enhanced_cache_manager import EnhancedCacheManager
        mgr = EnhancedCacheManager.__new__(EnhancedCacheManager)
        sorted_rows = sorted(rows, key=lambda r: (r['ts_code'], -_asof_key(r['asof_date']), r['benchmark']))
        with patch.object(mgr, '_query_shard', return_value=pd.DataFrame(sorted_rows)):
            return mgr.get_relative_strength(ts_code='600519.SH')

    def test_latest_asof_first(self):
        """同 ts_code+benchmark 多 asof：最新交易日行排最前（旧 None 行不再优先）"""
        rows = [
            {'ts_code': '600519.SH', 'benchmark': '000300.SH', 'asof_date': '2026-09-14',
             'rps_20d': None, 'rps_60d': None},
            {'ts_code': '600519.SH', 'benchmark': '000300.SH', 'asof_date': '2026-09-16',
             'rps_20d': 64.45, 'rps_60d': 81.45},
        ]
        out = self._shard_for(rows)
        assert out[0]['asof_date'] == '2026-09-16'
        assert out[0]['rps_60d'] == 81.45

    def test_old_none_row_not_first(self):
        """即使旧行（None rps）先插入，也应因排序落在最新行之后"""
        rows = [
            {'ts_code': '600519.SH', 'benchmark': '000300.SH', 'asof_date': '2026-09-16',
             'rps_20d': 64.45, 'rps_60d': 81.45},
            {'ts_code': '600519.SH', 'benchmark': '000300.SH', 'asof_date': '2026-09-14',
             'rps_20d': None, 'rps_60d': None},
        ]
        out = self._shard_for(rows)
        assert out[0]['asof_date'] == '2026-09-16'

    def test_two_benchmarks_same_asof(self):
        """同一 asof 双基准行都保留，且均排在最前块（09-16 两行在 09-14 之前）"""
        rows = [
            {'ts_code': '600519.SH', 'benchmark': '000001.SH', 'asof_date': '2026-09-14',
             'rps_20d': None},
            {'ts_code': '600519.SH', 'benchmark': '000300.SH', 'asof_date': '2026-09-16',
             'rps_20d': 64.45},
            {'ts_code': '600519.SH', 'benchmark': '000001.SH', 'asof_date': '2026-09-16',
             'rps_20d': 64.45},
        ]
        out = self._shard_for(rows)
        latest = [r['asof_date'] for r in out if r['asof_date'] == '2026-09-16']
        assert len(latest) == 2
        assert out[0]['asof_date'] == '2026-09-16'

    def test_source_orders_by_asof_desc(self):
        """源码级断言：ORDER BY 含 asof_date DESC"""
        import inspect
        from app.data.enhanced_cache_manager import EnhancedCacheManager
        src = inspect.getsource(EnhancedCacheManager.get_relative_strength)
        assert 'asof_date DESC' in src


class TestDim3RpsNaNHandling:
    """dim3 读 RPS：None/NaN 均视为无数据（中性放行），不再 float(NaN)>85 恒假"""

    def test_nan_rps_means_no_data_neutral_pass(self):
        """data_context 里 rps_20d=NaN（pandas 浮点转 NaN）→ audit 中性放行 + plain 无 RPS"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df,
                                         'relative_strength': {'rps_20d': np.nan, 'rps_60d': np.nan}})
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '相对强弱RPS')
        assert cond['satisfied'] is True
        assert cond['actual'] == '数据不足'
        assert out['status_description']['rps'] == '数据不足'

    def test_none_20d_falls_back_to_valid_60d(self):
        """rps_20d 缺失(None)时回退 60d（有效值）→ RPS 参与评分"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df,
                                         'relative_strength': {'rps_20d': None, 'rps_60d': 90}})
        assert out['status_description']['rps'] == '90.0/100'
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '相对强弱RPS')
        assert cond['satisfied'] is True

    def test_nan_20d_falls_back_to_valid_60d(self):
        """rps_20d=NaN 时回退 60d（有效值）"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df,
                                         'relative_strength': {'rps_20d': np.nan, 'rps_60d': 92}})
        assert out['status_description']['rps'] == '92.0/100'

    def test_real_shaped_rows_old_none_not_selected(self):
        """复刻表真实形态（09-14 行 rps=None，09-16 行有效）：取最新后 rps 是有效值而非 nan，
        且 RPS=64.45(<85) 时不加分、audit 不满足（但 actual 是真实分位，非『数据不足』）"""
        df = _mk_df()
        eng = Dim3VPEngine()
        out = eng.evaluate({}, dict(_P_BASE, ts_code='TEST'),
                           data_context={'daily_df': df,
                                         'relative_strength': {'rps_20d': 64.45, 'rps_60d': 81.45,
                                                               'asof_date': '2026-09-16'}})
        assert out['status_description']['rps'] == '64.5/100'
        cond = next(c for c in out['audit']['conditions'] if c['name'] == '相对强弱RPS')
        assert cond['satisfied'] is False
        assert cond['actual'] == 'RPS=64.5'
