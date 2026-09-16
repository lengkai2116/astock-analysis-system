"""450号方案：dim3 量价背离处置单测

覆盖：
  ① 背离完全以 framework 权威 volume_price_fit 标签为准（删除本地 MACD 兜底段）
     —— div_det 只取决于 tags['volume_price_fit']=='diverging'，不再依赖 df/price-MACD 兜底。
  ② _classify_granville 由单日粒度改为多日窗口（5 日区间涨幅 + 5/20 日均量比率）。

验证手法：直接以 dim3 模块私有/公开函数与 `_classify_granville`（模块级）注入构造 df 断言；
  evaluate 侧用 DataAwareMixin 注入 tags 与 data_context，观察 status_description.divergence 由标签驱动。
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine, _classify_granville


def _mk_df(closes, volumes=None, n=70):
    """构造带 close/high/low/vol 的日线 df（默认随机，可由入参覆盖 close）。"""
    rng = np.random.RandomState(0)
    if closes is None:
        closes = np.linspace(10, 20, n) + rng.normal(0, 0.1, n)
    closes = np.asarray(closes, dtype=float)
    vols = (volumes if volumes is not None else rng.uniform(1000, 5000, len(closes)))
    vols = np.asarray(vols, dtype=float)
    idx = pd.date_range('2025-01-01', periods=len(closes), freq='B')
    df = pd.DataFrame({
        'ts_code': 'TEST.XSHG',
        'open': closes,
        'high': closes * 1.01,
        'low': closes * 0.99,
        'close': closes,
        'vol': vols,
    }, index=idx)
    return df


# ───────── ① 背离检测以 volume_price_fit 权威标签为准 ─────────

class TestDivergenceAuthority:
    def test_diverging_tag_drives_div_det(self):
        """volume_price_fit=diverging → status_description 有背离检测。"""
        eng = Dim3VPEngine()
        df = _mk_df(None)
        tags = {'ts_code': 'TEST.XSHG', 'volume_price_fit': 'diverging', 'volume_ratio': 1.0}
        out = eng.evaluate({}, tags, data_context={'daily_df': df})
        sd = out['status_description']
        assert sd['divergence'] == '量价背离信号已检测'

    def test_healthy_tag_drives_no_div_det_even_with_price_newhigh(self):
        """volume_price_fit != diverging → 即使价格创新高、MACD 可判顶背离，也应判无背离（删除 MACD 兜底）。"""
        eng = Dim3VPEngine()
        # 价格连创新高的强上涨走势（原 MACD 兜底段 `pn and mn` 需价格新高——此处构造价格新高但量不配合，仍应为无背离）
        closes = np.linspace(10, 30, 70) + 0.05 * np.sin(np.arange(70))
        # 成交量后段萎缩（原兜底不会触顶背离所需，但我们要验证标签是唯一来源）
        volumes = np.r_[np.linspace(4000, 4000, 40), np.linspace(4000, 800, 30)]
        df = _mk_df(closes, volumes)
        tags = {'ts_code': 'TEST.XSHG', 'volume_price_fit': 'healthy', 'volume_ratio': 1.0}
        out = eng.evaluate({}, tags, data_context={'daily_df': df})
        sd = out['status_description']
        assert sd['divergence'] == '无背离信号'

    def test_empty_df_still_works_with_tag_diverging(self):
        """df 为空时，背离仍由标签决定（无本地 df/MACD 依赖）。"""
        eng = Dim3VPEngine()
        tags = {'ts_code': 'TEST.XSHG', 'volume_price_fit': 'diverging'}
        out = eng.evaluate({}, tags, data_context={'daily_df': pd.DataFrame()})
        assert out['status_description']['divergence'] == '量价背离信号已检测'
        assert out['status_description']['vp_state'] == '背离'


# ───────── ② 格兰威尔八准则多日粒度 ─────────

class TestGranvilleMultiDayGranularity:
    def test_healthy_5d_rise_with_vol_expand(self):
        """5 日区间上涨>2% + 5日均量>20日均量 → 量价齐升。"""
        n = 70
        closes = np.r_[np.linspace(8, 10, n - 5), np.linspace(10, 11.5, 5)]  # 末 5 日 +15%
        volumes = np.r_[np.ones(n - 5) * 1000, np.ones(5) * 1500]  # 末5日均量1500，20日均量1125 → vr=33% ∈(10,40]
        df = _mk_df(closes, volumes)
        res = _classify_granville(df, 1.0, {})
        assert res['rule'] == 'healthy'

    def test_single_day_spike_no_classification(self):
        """仅单日大涨（5 日区间涨幅小）不触发任何高置信分类 → 中性（体现多日粒度抗单日噪声）。"""
        arr = np.ones(70) * 10
        arr[-1] = 11  # 仅末日 +10%
        arr[-2] = 9.8
        closes = arr
        volumes = np.ones(70) * 2000
        df = _mk_df(closes, volumes)
        res = _classify_granville(df, 1.0, {})
        # 5 日区间涨幅约为 11/9.8 ≈ +12%；量能平稳（vr≈0），不足 healthy(需量>10%)，应落 neutral
        assert res['rule'] == 'neutral'

    def test_down_shrink_with_multiday(self):
        """5 日区间下跌且量能收缩 → 回探缩量。"""
        n = 70
        closes = np.r_[np.linspace(10, 9, n - 5), np.linspace(9, 8.2, 5)]  # 末 5 日 -9%
        volumes = np.r_[np.ones(n - 5) * 3000, np.ones(5) * 900]  # 末 5 日均量为 20 日均的 0.3 倍
        df = _mk_df(closes, volumes)
        res = _classify_granville(df, 1.0, {})
        assert res['rule'] == 'pullback_shrinking'

    def test_vol_ratio_fallback_when_short_df(self):
        """df 不足 20 日时，量能比率回退用 vol_ratio 入参。"""
        df = _mk_df(np.linspace(10, 12, 10), np.ones(10) * 2000)
        # vol_ratio=0.3 → vr=(0.3-1)*100=-70 < -10，且 5 日涨幅 >1.5 → 价升量减 weakening
        res = _classify_granville(df, 0.3, {})
        assert res['rule'] == 'weakening'

    def test_diverging_tag_maps_to_diverging(self):
        """volume_price_fit=diverging 且无价量条件命中 → 量价背离。"""
        df = _mk_df(None)
        res = _classify_granville(df, 1.0, {'volume_price_fit': 'diverging'})
        assert res['rule'] == 'diverging'


# ───────── ④ 50 形态名实对齐（黑马 P-3-1~P-3-10）─────────

class TestBlackhorseRegistryAlignment:
    """450号④：registry 黑马形态描述与检测器实际实现名实对齐。

    病灶：registry `_blackhorse_wiki` 原登记另一套无关名目（压缩放量突破等），
    dim3 展示名取 registry 描述 → 名实不对应。断言 registry label 与
    BlackHorsePatternDetector._NAMES 一致，且 min_periods 修正到位（P-3-4>=250）。"""

    def test_p3_registry_label_matches_detector_names(self):
        """黑马 P-3-1~P-3-10 的 registry 中文 label 与 detector._NAMES 完全一致。"""
        from app.engine.patterns.detectors.blackhorse_patterns import BlackHorsePatternDetector
        from app.engine.patterns.registry import PatternRegistry

        reg = PatternRegistry()
        names = BlackHorsePatternDetector._NAMES  # 检测器实际实现名目（权威）
        for code in ['P-3-1', 'P-3-2', 'P-3-3', 'P-3-4', 'P-3-5',
                     'P-3-6', 'P-3-7', 'P-3-8', 'P-3-9', 'P-3-10']:
            meta = reg.get(code)
            assert meta is not None, f'{code} 未注册'
            assert meta.name == code
            # description 取 ':' 前 label，应与 detector 实际形态名一致
            label = meta.description.split(':', 1)[0].strip()
            assert label == names[code], \
                f'{code} 展示名 {label} 与检测器实际形态 {names[code]} 不对应'

    def test_p3_min_periods_aligned(self):
        """registry 黑马 min_periods 与检测器实际数据需求对齐（未统一 5）。"""
        from app.engine.patterns.registry import PatternRegistry
        reg = PatternRegistry()
        # P-3-4 突破年线需 >=250 日，P-3-9 老鸭头需 >=60，P-3-6 长期缩量需 >=40
        assert reg.get('P-3-4').min_periods == 250
        assert reg.get('P-3-9').min_periods == 60
        assert reg.get('P-3-6').min_periods == 40

    def test_pattern_code_cn_uses_correct_blackhorse_label(self):
        """dim3 消费侧 pattern_code_cn 对黑马码返回 detector 对应中文名。"""
        from app.opportunity_atlas.dimensions.enum_cn_map import pattern_code_cn
        assert pattern_code_cn('P-3-4') == '突破年线放量'
        assert pattern_code_cn('P-3-1') == '底部异动放量'
