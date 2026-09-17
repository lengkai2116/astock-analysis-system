"""455号方案：dim3 量价八准则处置单测

覆盖两条偏差（445 §6.3, 450 未覆盖）：
  ① 放量滞涨逻辑缺陷：`_classify_granville` 的 heavy_pressure 分支由
     `abs(price_chg)<1.5 and vr>20`（5日/20日均量平滑均值>1.2×，单日放量即触发；
     abs 允许实质下跌入选）修正为对齐 framework 权威 `_is_fangliang_zhizhang`+wiki——
     近3日每根量>前20日均量×1.5（连续数日明显放大）且 3日涨幅和<1%（价格无法加速）。
  ② 八准则装饰性输出：granville 由纯 status_description 文案升为 audit 证据项——
     新增「量价八准则」条件（负面形态不满足 confidence），消除装饰性。

验证手法：直接以模块私有/公开函数与 `_classify_granville`（模块级）构造 df 断言判据；
  evaluate 侧用 DataAwareMixin 注入 tags、data_context，断言 audit 第6条联动。
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine, _classify_granville


def _mk_df(closes, volumes, base=2000.0):
    """构造带 close/high/low/vol 的日线 df。"""
    closes = np.asarray(closes, dtype=float)
    vols = np.asarray(volumes, dtype=float)
    idx = pd.date_range('2025-01-01', periods=len(closes), freq='B')
    return pd.DataFrame({
        'ts_code': 'TEST.XSHG', 'open': closes, 'high': closes * 1.01,
        'low': closes * 0.99, 'close': closes, 'vol': vols,
    }, index=idx)


def _flat(n=70, end=(10.0, 10.02, 10.01)):
    """近3日价格滞涨（涨幅和<1%）的收平序列。"""
    base = [10.0] * (n - 3) + list(end)
    return base


# ───────── ① 放量滞涨逻辑缺陷修正 ─────────

class TestHeavyPressureLogic:
    def test_true_3day_consecutive_expansion_stall(self):
        """近3日每根放量>1.5× 且价格滞涨 → 放量滞涨。"""
        n = 70
        closes = _flat(n)                      # 近3日 ~0.3% 滞涨
        vols = np.ones(n) * 2000
        vols[-4:-1] = [4000, 4200, 4100]       # 3日连续 >3000(2000×1.5)
        res = _classify_granville(_mk_df(closes, vols), 1.0, {})
        assert res['rule'] == 'heavy_pressure'
        assert res['name'] == '放量滞涨'

    def test_single_day_spike_not_heavy(self):
        """仅1日巨量但非连续（原均值口径会误判）→ 非放量滞涨。"""
        n = 70
        closes = _flat(n)
        vols = np.ones(n) * 2000
        vols[-3] = 20000                        # 单日10倍量，前2日正常
        res = _classify_granville(_mk_df(closes, vols), 1.0, {})
        assert res['rule'] != 'heavy_pressure'

    def test_moderate_expansion_below_1_5x_not_heavy(self):
        """放量未达1.5×（如1.3×）不算「明显放大」→ 非放量滞涨。"""
        n = 70
        closes = _flat(n)
        vols = np.ones(n) * 2000
        vols[-4:-1] = [2600, 2700, 2650]       # ~1.3×<1.5×
        res = _classify_granville(_mk_df(closes, vols), 1.0, {})
        assert res['rule'] != 'heavy_pressure'

    def test_expansion_but_price_accelerating_not_heavy(self):
        """连续放量但价格上涨>1%（价格在加速）→ 非放量滞涨。"""
        n = 70
        closes = [10.0] * (n - 3) + [10.0, 10.20, 10.35]   # 3日涨幅和≈3.5%
        vols = np.ones(n) * 2000
        vols[-4:-1] = [4000, 4200, 4100]
        res = _classify_granville(_mk_df(closes, vols), 1.0, {})
        assert res['rule'] != 'heavy_pressure'

    def test_short_df_fallback_no_crash(self):
        """df 不足 20 日时 heavy 判据安全回退（不抛异常，落其它分支）。"""
        closes = np.linspace(10, 10.2, 10)
        vols = np.ones(10) * 2000
        res = _classify_granville(_mk_df(closes, vols), 0.3, {})
        assert res['rule'] in ('weakening', 'neutral', 'unknown')


# ───────── ② 八准则接入 audit（消除装饰性）─────────

class TestGranvilleAuditWiring:
    def _evaluate(self, closes, vols, vp='healthy'):
        eng = Dim3VPEngine()
        tags = {'ts_code': 'TEST.XSHG', 'volume_price_fit': vp, 'volume_ratio': 1.0}
        return eng.evaluate({}, tags, data_context={'daily_df': _mk_df(closes, vols)})

    def _qc(self, out):
        au = out['audit']
        for c in au['conditions']:
            if c['name'] == '量价八准则':
                return au, c
        raise AssertionError('audit 缺「量价八准则」条件')

    def test_audit_has_8th_condition(self):
        """granville 分类升为 audit 证据项：总条件数由5→6，含「量价八准则」。"""
        n = 70
        out = self._evaluate(_flat(n), np.ones(n) * 2000, vp='healthy')
        au = out['audit']
        names = [c['name'] for c in au['conditions']]
        assert au['total_count'] == 6, names
        assert '量价八准则' in names

    def test_positive_rule_satisfied(self):
        """健康类（量价齐升/中性）→ 量价八准则条件满足。"""
        n = 70
        closes = [10.0] * (n - 5) + list(np.linspace(10, 11.5, 5))  # 量价齐升 +15%
        vols = np.r_[np.ones(n - 5) * 1000, np.ones(5) * 1500]
        out = self._evaluate(closes, vols, vp='healthy')
        au, qc = self._qc(out)
        assert qc['satisfied'] is True
        assert qc['actual'] == '量价齐升'

    def test_negative_rule_unsatisfied(self):
        """负面形态（放量滞涨）→ 量价八准则条件不满足 + confidence 拉低。"""
        n = 70
        closes = [10.0] * (n - 3) + [10.0, 10.02, 10.01]   # 滞涨
        vols = np.ones(n) * 2000
        vols[-4:-1] = [4000, 4200, 4100]                   # 连续放量
        out = self._evaluate(closes, vols, vp='healthy')
        au, qc = self._qc(out)
        assert qc['satisfied'] is False
        assert qc['actual'] == '放量滞涨'
        # 负面 → satisfied_count 下降，confidence < 1.0（granville 真正影响 SIG 结论）
        assert au['satisfied_count'] < au['total_count']
        assert au['confidence'] < 1.0

    def test_status_description_granville_still_present(self):
        """granville 仍保留在 status_description 文案（展示不丢失）。"""
        n = 70
        closes = [10.0] * (n - 3) + [10.0, 10.02, 10.01]
        vols = np.ones(n) * 2000
        vols[-4:-1] = [4000, 4200, 4100]
        out = self._evaluate(closes, vols, vp='healthy')
        assert '放量滞涨' in out['status_description']['granville']
