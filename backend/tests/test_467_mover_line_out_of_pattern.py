"""467号回归测试：体系A 均线形态移出量价 pattern_signal（B·消费点过滤）+ 均线改读 indicator_ma 预计算（A）

445 冻结边界约束：framework VolumeStateAnalyzer 复用 EnhancedPatternDetector.detect_all 的
预涨/预跌形态计算 resonance_score（→ dim3 强度 + BUY/SELL 方向门控），该判定逻辑不得改动。
因此 B 采用**消费点过滤**而非从 detect_all 删规则：
  - detect_all 规则保持原样（framework 共振评分不受影响；316号守卫要求 detect_all 方向形态
    ⊆ VOTE_MAP，故 VOTE_MAP 仍含均线键——消费点即使不产出也保留映射语义）；
  - 仅 data_daemon._add_vp_simple_tags 产出 pattern_signal 前剔除均线类形态名。

覆盖三组：
B1. _add_vp_simple_tags 产出的 pattern_signal 不含均线类形态名（消费点过滤生效）
B2. detect_all 规则/方法定义保留 + VOTE_MAP 仍含均线键 + 316守卫（方向形态⊆VOTE_MAP）延续
A1. _add_vp_simple_tags 优先读 indicator_ma 预计算 → ma_alignment；缺失回退 raw np.mean
"""
import numpy as np
import pandas as pd
import data_daemon as dd


# 应移出的均线类形态名（wiki 归入均线系统/格兰威尔均线八法则，由 ma_alignment 票源独立承接）
MA_LABELS = {
    '放量站上60日线', 'MA5金叉MA10', 'MA5死叉MA10', '均线多头排列', '均线空头排列',
    '连续站上60日线', 'MA5上穿MA20', '回踩MA60获支撑', 'MA5上穿MA60',
    '三线开花多头', '三线开花空头', 'MA30>MA60', '站上MA120', '站上MA250',
    '格兰维尔买点1-突破买', '格兰维尔买点2-回踩买', '格兰维尔买点3-偏离买', '格兰维尔买点4-新低买',
    '格兰维尔卖点1-跌破卖', '格兰维尔卖点2-反抽卖', '格兰维尔卖点3-偏离卖', '格兰维尔卖点4-新高卖',
}


def _gen_df(n=270, seed=42):
    rng = np.random.RandomState(seed)
    base = rng.uniform(10, 12, n).cumsum() * 0.02 + 11
    return pd.DataFrame({'open': base, 'close': base,
                         'high': base * 1.01, 'low': base * 0.99,
                         'vol': rng.uniform(1e6, 3e6, n)})


class Test467MoverLineOutOfPatternSignal:
    """B：均线形态在 pattern_signal 消费点过滤（framework detect_all 保持产出）"""

    def test_add_vp_simple_tags_filters_ma_shapes(self, monkeypatch):
        """_add_vp_simple_tags 产出的 pattern_signal 不含均线类形态名（消费点过滤）"""
        from app.engine.framework.volume_price_strategy import EnhancedPatternDetector

        # 构造同时命中均线形态 + 非均线方向形态的 detect_all 输出，
        # 验证过滤后 pattern_signal 取非均线形态（预跌优先）。
        def _fake_detect(self_, closes, opens, highs, lows, volumes, **kw):
            return ['均线多头排列(预涨)', '看涨吞没(预涨)', 'M顶(预跌)']

        monkeypatch.setattr(EnhancedPatternDetector, 'detect_all', _fake_detect)
        df = _gen_df()
        tags = {}
        if not hasattr(dd, 'np'):
            dd.np = np
        dd._add_vp_simple_tags(df, tags)
        # 预跌优先 + 均线过滤 → M顶(预跌) 胜出；"均线多头排列" 不进入 pattern_signal
        assert tags['pattern_signal'] == 'M顶', \
            f"均线形态应被消费点过滤，实得 {tags.get('pattern_signal')}"

    def test_add_vp_simple_tags_only_ma_shapes_gives_none(self, monkeypatch):
        """detect_all 只命中均线形态时，过滤后 pattern_signal = 'none'（不以均线形态充当量价形态）"""
        from app.engine.framework.volume_price_strategy import EnhancedPatternDetector

        def _fake_detect(self_, closes, opens, highs, lows, volumes, **kw):
            return ['MA5金叉MA10(预涨)', '均线空头排列(预跌)']

        monkeypatch.setattr(EnhancedPatternDetector, 'detect_all', _fake_detect)
        df = _gen_df()
        tags = {}
        if not hasattr(dd, 'np'):
            dd.np = np
        dd._add_vp_simple_tags(df, tags)
        assert tags['pattern_signal'] == 'none', \
            f"仅均线形态时 pattern_signal 应为 none，实得 {tags.get('pattern_signal')}"

    def test_detect_all_rules_still_present(self):
        """detect_all 的均线规则/方法定义保留（framework 共振评分冻结）"""
        import os
        vps_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'engine',
                                'framework', 'volume_price_strategy.py')
        with open(vps_path, encoding='utf-8') as f:
            src = f.read()
        seg = src[src.index('def detect_all'):src.index('        for name, method_name in checks:')]
        for needle in ('_is_fangliang_zhan60', '_is_ma5_jinchai_ma10', '_is_ma_tuo_pailie',
                       '_is_granville_buy1', '_is_granville_sell4'):
            assert needle in seg, f"detect_all 不得删除均线规则 {needle}（framework 冻结）"

    def test_vote_map_still_has_ma_keys(self):
        """VOTE_MAP 仍保留均线键（detect_all 方向形态⊆VOTE_MAP 守卫要求）"""
        from app.opportunity_atlas.cross_validate import VOTE_MAP
        keys = set(VOTE_MAP['pattern_signal'])
        assert '均线多头排列' in keys and '格兰维尔卖点2-反抽卖' in keys, \
            "VOTE_MAP 不应删均线键（detect_all 仍产出，须守卫覆盖）"

    def test_vote_map_still_covers_detector_shapes(self):
        """316号守卫延续：detect_all 全部方向性形态 ⊆ VOTE_MAP（未删 detect_all 即守卫不变）"""
        import os, re
        from app.opportunity_atlas.cross_validate import VOTE_MAP
        vps_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'engine',
                                'framework', 'volume_price_strategy.py')
        with open(vps_path, encoding='utf-8') as f:
            src = f.read()
        seg = src[src.index('def detect_all'):src.index('        for name, method_name in checks:')]
        names = set(re.findall(r"\(\s*'([^']+?\([^)]*\))'\s*,\s*'_is_\w+'\s*\)", seg))
        direction_names = {n.split('(')[0] for n in names}
        assert direction_names, "应从检测器源码提取到形态名"
        missing = {n for n in direction_names if n not in VOTE_MAP['pattern_signal']}
        assert not missing, f"Detector 方向性形态未映射到 VOTE_MAP: {sorted(missing)}"


class Test467MaAlignmentFromIndicator:
    """A：_add_vp_simple_tags 均线改读 indicator_ma 预计算"""

    def _make_df(self, trend='up'):
        n = 120
        rng = np.random.RandomState(1)
        if trend == 'up':
            closes = np.linspace(10, 20, n) + rng.normal(0, 0.1, n)
        elif trend == 'down':
            closes = np.linspace(20, 10, n) + rng.normal(0, 0.1, n)
        else:
            closes = np.linspace(15, 16, n) + rng.normal(0, 0.5, n)
        return pd.DataFrame({'close': closes, 'open': closes,
                            'high': closes * 1.01, 'low': closes * 0.99,
                            'vol': rng.uniform(1e6, 2e6, n)})

    def test_ma_alignment_prefers_indicator_ma(self):
        """传入 indicator_ma（含 ma5/10/20/60）时，ma_alignment 由预计算值判定"""
        df = self._make_df(trend='up')
        closes = df['close'].values
        ind_ma = pd.DataFrame({'ma5': [float(np.mean(closes[-5:]))],
                               'ma10': [float(np.mean(closes[-10:]))],
                               'ma20': [float(np.mean(closes[-20:]))],
                               'ma60': [float(np.mean(closes[-60:]))]})
        tags = {}
        dd._add_vp_simple_tags(df, tags, indicator_ma=ind_ma)
        assert tags['ma_alignment'] == 'bullish', \
            f"上行趋势应判 bullish，实得 {tags.get('ma_alignment')}"

    def test_ma_alignment_fallback_raw_when_no_indicator(self):
        """不传 indicator_ma 或空表时，回退 raw np.mean 计算（行为不变）"""
        df = self._make_df(trend='up')
        tags = {}
        dd._add_vp_simple_tags(df, tags)
        assert tags['ma_alignment'] == 'bullish'
        tags2 = {}
        dd._add_vp_simple_tags(df, tags2, indicator_ma=pd.DataFrame())
        assert tags2['ma_alignment'] == 'bullish'

    def test_ma_alignment_indicator_missing_col_fallback(self):
        """indicator_ma 缺 ma60 列时，ma60 回退 raw，ma5/10/20 用预计算"""
        df = self._make_df(trend='down')
        closes = df['close'].values
        ind_ma = pd.DataFrame({'ma5': [float(np.mean(closes[-5:]))],
                               'ma10': [float(np.mean(closes[-10:]))],
                               'ma20': [float(np.mean(closes[-20:]))]})  # 缺 ma60
        tags = {}
        dd._add_vp_simple_tags(df, tags, indicator_ma=ind_ma)
        assert tags['ma_alignment'] == 'bearish', \
            f"下行趋势应判 bearish，实得 {tags.get('ma_alignment')}"

    def test_ma_alignment_downfall_with_indicator(self):
        """下行趋势（indicator_ma 预计算）→ bearish"""
        df = self._make_df(trend='down')
        closes = df['close'].values
        ind_ma = pd.DataFrame({'ma5': [float(np.mean(closes[-5:]))],
                               'ma10': [float(np.mean(closes[-10:]))],
                               'ma20': [float(np.mean(closes[-20:]))],
                               'ma60': [float(np.mean(closes[-60:]))]})
        tags = {}
        dd._add_vp_simple_tags(df, tags, indicator_ma=ind_ma)
        assert tags['ma_alignment'] == 'bearish'
