"""461-8：market_stats 组市场级/个股级分离（扁平化跳过）回归测试

460 §五 P3 / 阶段1-3：扁平 `pe_percentile`/`rsi_percentile` 唯一来源=market_stats 组(19)，
全市场共享值被 `_flatten_pre_feat` 摊进每只股票的 flat tags 命名空间（污染个股分位语义）。
valuation 组只产 `_5y` 变体、从不产裸 `pe_percentile`，故扁平层这些键纯属市场级。

用户拍板（2026-09-17）：扁平化跳过 market_stats 组（不进 flat tags）；
data_context 子 dict 独立保留（dim1 从 pre_feat 嵌套读取，供 dim5/bociasi 消费）。

本测试用真实 `status_engine._flatten_pre_feat`（改动所在），验证：
- market_stats 组全键被跳过（不进 flat tags）
- 其他组（valuation/depth/derived）正常摊平，不受影响
- 嵌套 pre_feat 中 market_stats 组 dict 原样保留（dim1 读子 dict 的基线）
"""
import pytest

from app.opportunity_atlas.status_engine import StatusEngine as _SE


class TestFlattenSkipsMarketStatsGroup:
    def test_market_stats_keys_not_in_flat(self):
        """461-8：market_stats 组全键被跳过，不进 flat tags（不再污染个股分位命名空间）"""
        pre = {
            'valuation': {'valuation_level': 'fair', 'pe_percentile_5y': 45.0},
            'depth': {'main_force_phase': 'building'},
            'derived': {'price_position': 'mid_zone'},
            'market_stats': {
                'ma20_ratio': 0.6, 'turnover_percentile': 0.55,
                'limit_ratio': 1.2, 'rsi_percentile': 0.7,
                'erp_percentile': 0.4, 'margin_trend': 0.5,
                'pe_percentile': 0.3, 'dv_bond_diff': 0.8,
            },
        }
        flat = _SE._flatten_pre_feat(pre)
        # market_stats 组市场级键不进 flat
        assert 'ma20_ratio' not in flat
        assert 'rsi_percentile' not in flat
        assert 'pe_percentile' not in flat
        assert 'turnover_percentile' not in flat
        assert 'limit_ratio' not in flat
        assert 'erp_percentile' not in flat
        assert 'margin_trend' not in flat
        assert 'dv_bond_diff' not in flat

    def test_other_groups_still_flattened(self):
        """461-8：跳过 market_stats 不影响其他组正常摊平"""
        pre = {
            'valuation': {'valuation_level': 'fair', 'pe_percentile_5y': 45.0},
            'depth': {'main_force_phase': 'building', 'price_position': 'high_zone'},
            'derived': {'price_position': 'high_zone', 'risk_level': 'LOW'},
            'market_stats': {'rsi_percentile': 0.7, 'pe_percentile': 0.3},
        }
        flat = _SE._flatten_pre_feat(pre)
        # 个股级键正常保留
        assert flat['valuation_level'] == 'fair'
        assert flat['pe_percentile_5y'] == 45.0
        assert flat['main_force_phase'] == 'building'
        assert flat['price_position'] == 'high_zone'
        assert flat['risk_level'] == 'LOW'

    def test_market_stats_group_preserved_in_pre_feat(self):
        """461-8：嵌套 pre_feat 的 market_stats 组 dict 原样保留（dim1 data_context 子 dict 基线）"""
        pre = {
            'valuation': {'valuation_level': 'fair'},
            'market_stats': {
                'ma20_ratio': 0.6, 'rsi_percentile': 0.7,
                'pe_percentile': 0.3, 'dv_bond_diff': 0.8,
            },
        }
        # 扁平化是浅拷贝映射，不删除原 pre_feat 的 market_stats 组
        _SE._flatten_pre_feat(pre)
        assert 'market_stats' in pre
        assert pre['market_stats']['ma20_ratio'] == 0.6
        assert pre['market_stats']['rsi_percentile'] == 0.7


class TestMarketStatsStillAvailableViaDataContext:
    """461-8 保证：market_stats 组仍经 data_context 独立供给（dim5/bociasi 消费）"""

    def test_flatten_does_not_mutate_input(self):
        """扁平化不修改输入 pre_feat（dim1 之后仍能 ext_groups 读到 market_stats 子 dict）"""
        from app.opportunity_atlas.status_engine import StatusEngine as _SE
        pre = {
            'valuation': {'valuation_level': 'fair'},
            'market_stats': {'ma20_ratio': 0.6, 'rsi_percentile': 0.7},
        }
        orig_market = dict(pre['market_stats'])
        _ = _SE._flatten_pre_feat(pre)
        assert pre['market_stats'] == orig_market
