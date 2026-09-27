"""491-J6：dim8 summary 段灯口径归 SSOT（阈值规则集中到 light_derive）

用户 2026-09-27 拍板：summary 灯**口径统一到 SSOT**，但**保留加权共识语义**
（不用 aggregate_lights 的「任一 red→red」——实测会使 6/8 股 summary 变红、
区分度塌陷）。最终＝B 方案：`light_derive.summary_light(consensus_rate)`（阈值 0.6/0.3），
dim8 只负责聚合共识率，阈值规则不再内联于 dim8。逐值等价于迁移前口径。

另：`eight_dim_summary['summary']` 行由恒 'yellow' 占位改为同口径派生。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas import light_derive as LD  # noqa: E402
from app.opportunity_atlas.dimensions import dim8_summary_engine as D8  # noqa: E402

logging.disable(logging.CRITICAL)


# ══════════════════════════════════════════════════════════
# SSOT 层：summary_light(consensus_rate) 阈值规则
# ══════════════════════════════════════════════════════════

class TestSummaryLightSsot:

    def test_thresholds(self):
        assert LD.summary_light(0.60) == 'green'
        assert LD.summary_light(0.76) == 'green'
        assert LD.summary_light(0.59) == 'yellow'
        assert LD.summary_light(0.30) == 'yellow'
        assert LD.summary_light(0.29) == 'red'
        assert LD.summary_light(0.0) == 'red'

    def test_invalid_input_is_data_missing(self):
        assert LD.summary_light(None) == LD.DATA_MISSING
        assert LD.summary_light('abc') == LD.DATA_MISSING

    def test_thresholds_constants_exist(self):
        assert LD.SUMMARY_LIGHT_GREEN == 0.6
        assert LD.SUMMARY_LIGHT_RED == 0.3


# ══════════════════════════════════════════════════════════
# dim8 层：改调 SSOT，值逐等价（不引入 aggregate 口径）
# ══════════════════════════════════════════════════════════

def _dr(**overrides):
    base = {
        'signal': {'judgment': {'attribute': {'code': 'right_confirmed'}}},
        'structure': {'judgment': {'structure': '上升'}},
        'volume_price': {'judgment': {'state': '健康'}},
        'chip_fund': {'judgment': {'phase': 'building'}},
        'emotion': {'judgment': {}, 'status_description': {'market_phase': 'ferment'}},
        'risk': {'judgment': {'risk_level': '低'}},
        'valuation': {'judgment': {'valuation_level': {'value': 'low'}}},
    }
    base.update(overrides)
    return base


class TestDim8SummaryLightUnified:

    def test_summary_light_delegates_to_ssot(self):
        dr = _dr()
        assert D8._summary_light_value(dr) == LD.summary_light(D8._calc_consensus_rate(dr))

    def test_equals_legacy_threshold(self):
        """回归守卫：与迁移前内联口径逐值等价（不因 J-6 改变 summary 灯值）"""
        for dr in (_dr(), _dr(risk={'judgment': {'risk_level': '极高'}}),
                   _dr(structure={'judgment': {'structure': '下降'}})):
            cr = D8._calc_consensus_rate(dr)
            legacy = 'green' if cr >= 0.6 else ('red' if cr < 0.3 else 'yellow')
            assert D8._summary_light_value(dr) == legacy

    def test_not_aggregate_any_red_rule(self):
        """回归守卫：单个红灯维不会使 summary 变红（旧 red 口径仅当共识率<0.3）。
        构造「结构下降但 6 维健康」→ 共识率应高于 0.3，summary 非 red。"""
        dr = _dr(structure={'judgment': {'structure': '下降'}})
        cr = D8._calc_consensus_rate(dr)
        assert cr >= 0.3, f'前置条件：共识率应 ≥0.3（实际 {cr}）'
        assert D8._summary_light_value(dr) != 'red'

    def test_eight_dim_summary_row_derived_not_placeholder(self):
        """eight_dim_summary['summary'] 由同口径派生（原恒 'yellow' 占位）——
        构造多数维转红使共识率 <0.3 → summary 应为 red（占位实现会给 yellow）"""
        dr = _dr(
            structure={'judgment': {'structure': '下降'}},
            volume_price={'judgment': {'state': '背离'}},
            chip_fund={'judgment': {'phase': 'distributing'}},
            risk={'judgment': {'risk_level': '极高'}},
            valuation={'judgment': {'valuation_level': {'value': 'extreme_high'}}},
            signal={'judgment': {'attribute': {'code': 'risk_warning'}}},
        )
        cr = D8._calc_consensus_rate(dr)
        assert cr < 0.3, f'前置条件：共识率应 <0.3（实际 {cr}）'
        summary = D8._build_eight_dim_summary(dr)
        assert summary['summary']['light'] == D8._summary_light_value(dr)
        assert summary['summary']['light'] == 'red'

    def test_evaluate_judgment_light_matches(self):
        dr = _dr()
        out = D8.Dim8SummaryEngine().evaluate(dims={}, tags={}, lifecycle={'dim_results': dr})
        assert out['judgment']['overall_light'] == D8._summary_light_value(dr)
