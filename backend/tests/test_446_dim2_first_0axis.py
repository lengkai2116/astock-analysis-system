"""446号：dim2 D9 一买/一卖 0轴绝对位置校验单元测试

知识库《缠中说禅MACD定律》（wiki concepts/缠中说禅MACD定律.md L16/L20-22）：
- 第一类买点都在 **0 轴之下** 背驰形成
- 第一类卖点都在 **0 轴之上** 背驰形成（对称）

缺陷（445 §6.1 dim2 D9：一买无 0 轴校验）：
引擎 `BuySellPointDetector.find` 生成 first_buy/first_sell 仅凭背驰 direction
（底背驰→一买、顶背驰→一卖），背驰力度虽用 MACD area/peak 做相对比值确认，
但 **完全无 0 轴绝对位置校验**——不检查背驰点 DIF 是否确实在 0 轴之下（买）/之上（卖）。

修复：`find` 增 closes 入参，`_check_first_0axis` 用背驰点 position.idx 处 DIF
相对 0 轴作闸门：一买须 DIF<0（水下）、一卖须 DIF>0（水上）。无 closes/DIF 数据
时放行（向后兼容）。
"""
from app.engine.framework.chanlun_strategy import (
    Divergence,
    BuySellPointDetector,
    Stroke,
)


def _mk_stroke(direction, sp, ep, start_idx=0, end_idx=5):
    return Stroke(start_idx=start_idx, end_idx=end_idx, start_price=sp, end_price=ep,
                  start_date='2026-01-01', end_date='2026-01-06', direction=direction,
                  high=max(sp, ep), low=min(sp, ep))


def _mk_div(type_, direction, idx):
    return Divergence(type=type_, direction=direction, confidence=0.85,
                      position={'idx': idx, 'price': 10.0})


def _mk_detector(precomputed=None):
    det = BuySellPointDetector()
    if precomputed is not None:
        det._precomputed = precomputed
    return det


def _monotonic_up_dif(n=40):
    """合成单调上升 DIF 序列（-1.0 → +1.0），覆盖 0 轴两侧，用于确定性测试。"""
    import numpy as np
    return np.linspace(-1.0, 1.0, n)


class TestFirstPointZeroAxisGate:
    """D9：一买/一卖 0轴绝对位置闸门（直接测 _check_first_0axis）"""

    def test_first_buy_requires_dif_below_zero(self):
        """一买：背驰点 DIF<0（0轴之下）→ 放行"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'down', idx=5)   # DIF≈-0.74 < 0
        assert det._check_first_0axis(True, div, [0.0] * 40) is True

    def test_first_buy_blocked_when_dif_above_zero(self):
        """一买：背驰点 DIF>0（0轴之上）→ 拦截（违反缠中说禅MACD定律）"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'down', idx=35)  # DIF≈+0.79 > 0
        assert det._check_first_0axis(True, div, [0.0] * 40) is False

    def test_first_sell_requires_dif_above_zero(self):
        """一卖：背驰点 DIF>0（0轴之上）→ 放行"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'up', idx=35)    # DIF≈+0.79 > 0
        assert det._check_first_0axis(False, div, [0.0] * 40) is True

    def test_first_sell_blocked_when_dif_below_zero(self):
        """一卖：背驰点 DIF<0（0轴之下）→ 拦截"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'up', idx=5)     # DIF≈-0.74 < 0
        assert det._check_first_0axis(False, div, [0.0] * 40) is False

    def test_no_closes_or_dif_releases_gate(self):
        """无 closes / 无预计算DIF → 放行（向后兼容），不因缺数据丢弃一买"""
        det = _mk_detector()
        div = _mk_div('trend', 'down', idx=5)
        assert det._check_first_0axis(True, div, None) is True
        assert det._check_first_0axis(True, div, []) is True


class TestFirstPointZeroAxisIntegration:
    """D9：通过 find 集成验证 0轴闸门"""

    ZS = None  # 不需要中枢，一买纯由 trend 背驰产生

    def _strokes(self):
        return [_mk_stroke('up', 10.0, 11.0, 0, 10),
                _mk_stroke('down', 11.0, 8.0, 10, 20),
                _mk_stroke('up', 8.0, 9.0, 20, 30),
                _mk_stroke('down', 9.0, 5.0, 30, 40)]

    def test_buy_below_zero_emits_first_buy(self):
        """底背驰（trend down）且 DIF<0 → 产出 first_buy"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'down', idx=35)   # DIF≈+0.79 > 0 → 应被拦截
        buy, sell = det.find(self._strokes(), None, div, closes=[0.0] * 40)
        assert buy == [] and sell == [], \
            "底背驰在0轴之上不应产一买（缠中说禅MACD定律）"

    def test_buy_below_zero_emits_first_buy_pass(self):
        """底背驰（trend down）且 DIF<0 → 产出 first_buy"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'down', idx=5)    # DIF≈-0.74 < 0 → 放行
        buy, sell = det.find(self._strokes(), None, div, closes=[0.0] * 40)
        assert any(p.type == 'first_buy' for p in buy), \
            "底背驰在0轴之下应产 first_buy"

    def test_sell_above_zero_emits_first_sell(self):
        """顶背驰（trend up）且 DIF>0 → 产出 first_sell"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'up', idx=35)     # DIF≈+0.79 > 0 → 放行
        buy, sell = det.find(self._strokes(), None, div, closes=[0.0] * 40)
        assert any(p.type == 'first_sell' for p in sell), \
            "顶背驰在0轴之上应产 first_sell"

    def test_sell_below_zero_blocked(self):
        """顶背驰（trend up）但 DIF<0 → 拦截 first_sell"""
        det = _mk_detector(precomputed={'macd_dif': _monotonic_up_dif(),
                                        'macd_dea': _monotonic_up_dif(),
                                        'macd_hist': _monotonic_up_dif()})
        div = _mk_div('trend', 'up', idx=5)      # DIF≈-0.74 < 0 → 拦截
        buy, sell = det.find(self._strokes(), None, div, closes=[0.0] * 40)
        assert not any(p.type == 'first_sell' for p in sell), \
            "顶背驰在0轴之下不应产 first_sell"
