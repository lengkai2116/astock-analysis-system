"""量价形态 kline_pattern 接线缺陷回归测试

根因（探针实证 / 会话核查）：
  `_precompute_raw_features` 量价特征段（data_daemon 3395 附近）原本写成
      'kline_pattern': vp_tags.get('pattern_signal', 'none'),
  但 `vp_tags = vps._detect_kline_patterns(df)`（volume_price_strategy:4129）返回的
  dict **只有** {ma_alignment, volume_price_fit, volatility_level, gap_type,
  breakout_attempts}，从不产出 'pattern_signal' 键 → kline_pattern 恒 'none'。
  真正算出形态的是同段的 `_simple = {}; _add_vp_simple_tags(df, _simple)`，
  形态写在 `_simple['pattern_signal']`（EnhancedPatternDetector + 预跌优先），
  却从未被合并进输出字段 → 形态算出来又被丢。

实证（真实数据三股）：
  600519.SH detect_all 查出 5 个形态（MA30>MA60/格兰维尔买4/卖2/下降楔形/M顶），
  _add_vp_simple_tags pattern_signal='格兰维尔卖点2-反抽卖'
  000001.SZ 查出 7 个（看涨吞没/镊子底/三线开花多头/...），pattern_signal='看涨吞没'
  300750.SZ 查出 3 个（均线空头排列/看跌捉腰带/三线开花空头），pattern_signal='均线空头排列'

修复：`kline_pattern` 改从 `_simple.get('pattern_signal', 'none')` 读取。
注意：本修复只接对 `pattern_signal` → `kline_pattern` 的事实链路，
**不改** `_add_vp_simple_tags` 的预跌优先压缩语义（形态取舍问题另行讨论）。
"""
import inspect
import numpy as np
import pandas as pd
import data_daemon as dd


def _precompute_src() -> str:
    """_precompute_raw_features 当前源码文本"""
    return inspect.getsource(dd._precompute_raw_features)


def _mk_df(n=80, base=10.0, step=0.02):
    """构造足够长的 OHLCV DataFrame（默认多头趋势，满足 _add_vp_simple_tags 计算约束）"""
    closes = base + np.arange(n) * step
    idx = pd.date_range('2026-01-01', periods=n, freq='D')
    return pd.DataFrame({
        'close': closes,
        'open': closes - 0.01,
        'high': closes + 0.02,
        'low': closes - 0.02,
        'vol': np.full(n, 1_000_000.0),
    }, index=idx)


class TestKlinePatternWiring:
    """kline_pattern 必须来自 _add_vp_simple_tags 算出的 pattern_signal 而非无该键的 detect_kline_patterns"""

    def test_kline_pattern_from_simple_pattern_signal(self):
        """kline_pattern 从 _simple.get('pattern_signal', ...) 读取（修复目标）"""
        src = _precompute_src()
        # 断言修复：features['volume_price']['kline_pattern'] 取自 _simple 的 pattern_signal
        assert "_simple.get('pattern_signal" in src, \
            "kline_pattern 应从 _add_vp_simple_tags 算出的 _simple['pattern_signal'] 读取"

    def test_kline_pattern_not_from_vp_tags(self):
        """不再从 _detect_kline_patterns 的 vp_tags 取 pattern_signal（该 dict 无此键 → 恒 none）"""
        src = _precompute_src()
        assert "vp_tags.get('pattern_signal" not in src, \
            "_detect_kline_patterns 返回 dict 无 pattern_signal 键，原写法恒 'none'"

    def test_simple_pattern_signal_still_computed(self):
        """_add_vp_simple_tags 仍在量价段内被调用并以 _simple 承接（形态真值来源保留）"""
        src = _precompute_src()
        assert "_add_vp_simple_tags(df, _simple)" in src, \
            "形态真值由 _add_vp_simple_tags 产出，必须保留"

    def test_simple_pattern_signal_never_dropped(self):
        """_simple 字典必须被消费（不再"算出来又丢"）：kline_pattern 引用了它"""
        src = _precompute_src()
        assert "_simple.get('pattern_signal" in src and "'pattern_signal':" in src, \
            "_simple 的 pattern_signal 已接入输出字段"


class TestAddVpSimpleTagsPatternSignal:
    """功能级：_add_vp_simple_tags 确实产出 pattern_signal（真值链路保留，非恒 none）"""

    def _run_with(self, monkeypatch, patterns):
        from app.engine.framework.volume_price_strategy import EnhancedPatternDetector

        def _fake_detect(self_, closes, opens, highs, lows, volumes, **kw):
            return list(patterns)

        monkeypatch.setattr(EnhancedPatternDetector, 'detect_all', _fake_detect)

        df = _mk_df()
        tags = {}
        # data_daemon._add_vp_simple_tags 内部直接用 np（模块级按需注入）
        if not hasattr(dd, 'np'):
            dd.np = np
        dd._add_vp_simple_tags(df, tags)
        # restore 由 monkeypatch 自动处理
        assert 'pattern_signal' in tags, "pattern_signal 必须被产出"
        return tags['pattern_signal']

    def test_prefer_bearish_when_mixed(self, monkeypatch):
        """预跌优先：同时存在预涨+预跌形态时取预跌（否决语义保留，本次不改）"""
        out = self._run_with(monkeypatch, ['看涨吞没(预涨)', 'M顶(预跌)', '下降楔形(预涨)'])
        assert out == 'M顶'

    def test_bearish_when_only_bearish(self, monkeypatch):
        """只含预跌形态时取预跌"""
        out = self._run_with(monkeypatch, ['射击之星(预跌)'])
        assert out == '射击之星'

    def test_bullish_when_only_bullish(self, monkeypatch):
        """只含预涨形态时取预涨"""
        out = self._run_with(monkeypatch, ['镊子底(预涨)'])
        assert out == '镊子底'

    def test_none_when_no_patterns(self, monkeypatch):
        """未命中任何形态 → 'none'（合法中性，非接线错误）"""
        out = self._run_with(monkeypatch, [])
        assert out == 'none'
