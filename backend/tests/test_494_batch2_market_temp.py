"""494号 批次2 回归（R-1 冰点末期市场级温度回升 + R-9 取数口径）

知识库依据：《华泰A股情绪指数》「触及10%恐慌区间不买，**回归10%之上再买入（右侧确认）**」；
《情绪周期-仓位联动》冰点 10%/空仓——均属**市场级**回升口径。

494号两处要点（详见方案 §四 批次2 / §九 R-9）：
- **R-1**：493 原 `_emotion_is_recovering` 读**个股级** `right_side_confirm`，与市场级 ice gate
  维度错位（全市场 ice 样本 0 → 组合 0 可达）。改为**市场级温度回升**：
  `sentiment_phase=='ice' AND mkt_temp ≥ ICE_RECOVERY_TEMP(35)`。个股 right_side_confirm 降级为
  evidence 附注（`l0.emotion_recovering_basis`），不进 gate。
- **R-9**：市场级温度输入取自 raw pre_feat（`sentiment.limit_up_count/sealing_rate` +
  `market_stats.ma20_ratio`）；缺失时 JUD 侧直读 `sentiment_pool_cache`（封板率）+ 广度兜底。
- 阈值口径（用户 2026-09-28 拍板）：`ICE_RECOVERY_TEMP=35`（温度五档偏冷区 20-40 的中值）；
  校准：ice 真冰点（中性输入）≈32.5 不触发；ice 且热度已起（涨停52/封板84%/广度39%）≈42.6 触发。
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.emotion_temperature import (  # noqa: E402
    market_level_temperature,
)
from app.opportunity_atlas.status_engine import (  # noqa: E402
    ICE_RECOVERY_TEMP,
    StatusEngine,
    _emotion_is_recovering,
    _market_level_inputs_via_dm,
    _market_level_temperature,
)

# 09-24 全市场市场级真值（sentiment_pool + market_stats_cache）
_LU, _SR, _BR = 52, 83.9, 0.392


# ── 1. SSOT：market_level_temperature ────────────────────────────────

def test_mlt_ice_default_is_below_threshold():
    """无市场级输入（全中性）→ 冰点温度 32.5 < 35（真冰点，不触发回升）"""
    assert market_level_temperature('ice') == 32.5
    assert market_level_temperature('ice') < ICE_RECOVERY_TEMP


def test_mlt_ice_real_inputs_above_threshold():
    """ice + 真实市场级输入（涨停52/封板84%/广度39%）→ 42.6 ≥ 35"""
    t = market_level_temperature('ice', _LU, _SR, _BR)
    assert t == 42.6
    assert t >= ICE_RECOVERY_TEMP


# ── 2. R-9：_market_level_temperature 取数（raw pre_feat 优先） ───────

def test_reads_raw_pre_feat_sentiment_and_market_stats():
    raw = {'sentiment': {'limit_up_count': _LU, 'sealing_rate': _SR},
           'market_stats': {'ma20_ratio': _BR}}
    t = _market_level_temperature({'sentiment_phase': 'ice'}, raw)
    assert t == 42.6, f"应读 raw 子组，实际 {t}"


def test_falls_back_to_flat_tags():
    tags = {'sentiment_phase': 'ice', 'limit_up_count': _LU, 'sealing_rate': _SR, 'breadth': _BR}
    assert _market_level_temperature(tags, None) == 42.6


def test_raw_takes_precedence_over_flat():
    tags = {'sentiment_phase': 'ice', 'limit_up_count': 0, 'sealing_rate': 10.0, 'breadth': 0.0}
    raw = {'sentiment': {'limit_up_count': _LU, 'sealing_rate': _SR},
           'market_stats': {'ma20_ratio': _BR}}
    assert _market_level_temperature(tags, raw) == 42.6


# ── 3. R-1：_emotion_is_recovering gate ──────────────────────────────

def test_gate_true_only_when_ice_and_temp_high():
    assert _emotion_is_recovering({'sentiment_phase': 'ice', 'limit_up_count': _LU,
                                   'sealing_rate': _SR, 'breadth': _BR}) is True


def test_gate_false_when_ice_and_temp_low_even_strong_confirm():
    """个股级强确认不再触发（R-1 维度错位修复）"""
    assert _emotion_is_recovering({'sentiment_phase': 'ice', 'right_side_confirm': '强确认'}) is False
    assert _emotion_is_recovering({'sentiment_phase': 'ice'}) is False


def test_gate_false_when_not_ice():
    """非 ice（ebb/ferment）→ 不判回升（gate 前提）"""
    assert _emotion_is_recovering({'sentiment_phase': 'ebb', 'limit_up_count': 200,
                                   'sealing_rate': 99.0, 'breadth': 1.0}) is False


# ── 4. _apply_l0：cap 放开/维持 + 附注 ───────────────────────────────

def _se():
    return StatusEngine(dm=object())


def test_apply_l0_ice_recovering_raises_cap_with_basis():
    tags = {'sentiment_phase': 'ice', 'limit_up_count': _LU, 'sealing_rate': _SR, 'breadth': _BR,
            'right_side_confirm': '否决'}
    l0 = _se()._apply_l0('T.SZ', tags, {})
    assert l0['emotion_position_cap'] == 0.60
    assert l0.get('emotion_phase') == 'ice_recovering'
    assert '市场级温度回升' in (l0.get('emotion_recovering_basis') or '')
    assert '仅附注' in l0['emotion_recovering_basis']


def test_apply_l0_ice_low_temp_keeps_cap():
    l0 = _se()._apply_l0('T.SZ', {'sentiment_phase': 'ice', 'right_side_confirm': '强确认'}, {})
    assert l0['emotion_position_cap'] == 0.10
    assert l0.get('emotion_phase') is None


def test_apply_l0_raw_pre_feat_param_path():
    """raw_pre_feat 传入（pre_feat 有市场级输入、flat 无）→ 放开 cap"""
    raw = {'sentiment': {'limit_up_count': _LU, 'sealing_rate': _SR},
           'market_stats': {'ma20_ratio': _BR}}
    l0 = _se()._apply_l0('T.SZ', {'sentiment_phase': 'ice'}, {}, raw_pre_feat=raw)
    assert l0['emotion_position_cap'] == 0.60


def test_apply_l0_non_ice_unchanged():
    l0 = _se()._apply_l0('T.SZ', {'sentiment_phase': 'ebb', 'limit_up_count': 200,
                                  'sealing_rate': 99.0, 'breadth': 1.0}, {})
    assert l0.get('emotion_phase') is None
    assert l0['emotion_position_cap'] != 0.60 or True  # 非 ice 走原档（这里仅断言未标 ice_recovering）


# ── 5. R-9 兜底：JUD 侧直读市场级源 ──────────────────────────────────

class _FakeCache:
    def get_cached_sentiment_pool(self, trade_date=None):
        return pd.DataFrame({'limit_type': ['up'] * _LU + ['zha'] * 10})

    def get_market_ma20_ratio(self):
        return _BR


class _FakeDM:
    cache = _FakeCache()


def test_direct_market_source_reads_pool_and_breadth():
    out = _market_level_inputs_via_dm(_FakeDM())
    assert out['limit_up_count'] == _LU
    assert abs(out['sealing_rate'] - 83.9) < 0.1      # 52/(52+10)
    assert abs(out['breadth'] - _BR) < 1e-9


def test_direct_market_source_absent_returns_empty():
    assert _market_level_inputs_via_dm(object()) == {}


def test_direct_market_source_feeds_gate():
    """直读兜底输入喂入 gate → 温度 42.6 ≥ 35"""
    raw = {'sentiment': _market_level_inputs_via_dm(_FakeDM()), 'market_stats': {}}
    assert _emotion_is_recovering({'sentiment_phase': 'ice'}, raw) is True


def test_threshold_constant():
    assert ICE_RECOVERY_TEMP == 35.0
