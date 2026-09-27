"""439-A-1：灯色派生 SSOT（light_derive）单元测试

覆盖：
  1. 纯映射表逐维取值 + 未知状态→「数据缺失」黄；
  2. 聚合（任一红→红 / ≥2 绿→绿 / 否则黄）；
  3. 市场情绪灯的四象限覆盖（HH/LL/HL/LH）；
  4. 个股情绪灯跨维（dim3 vp_state）；
  5. 风险灯（judgment.level 优先，risk_sources 高源计数兜底）；
  6. 信号灯三源聚合（属性/强度等级/衰减状态）；
  7. dim_light 端到端 + 别名（fund_chip/vp）；
  8. **关键回归**：派生完全不依赖灯键（构造无任何 light 的 dim_results 仍正确）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas import light_derive as LD  # noqa: E402


def test_pure_mappings():
    assert LD.derive_light('structure', '上升') == 'green'
    assert LD.derive_light('structure', '下降') == 'red'
    assert LD.derive_light('volume_price', '健康') == 'green'
    assert LD.derive_light('volume_price', '严重背离') == 'red'
    assert LD.derive_light('chip_fund', 'lifting') == 'green'
    assert LD.derive_light('chip_fund', 'distributing') == 'red'
    assert LD.derive_light('valuation', 'extreme_low') == 'green'
    assert LD.derive_light('valuation', 'high') == 'red'
    assert LD.derive_light('sector', 'top_10') == 'green'
    assert LD.derive_light('signal', 'risk_warning') == 'red'
    # 未知/空 → 数据缺失黄（Q-439A-2）
    assert LD.derive_light('structure', '') == LD.DATA_MISSING
    assert LD.derive_light('unknown_dim', 'x') == LD.DATA_MISSING


def test_aggregate():
    assert LD.aggregate_lights(['green', 'green', 'yellow']) == 'green'
    assert LD.aggregate_lights(['green', 'yellow', 'yellow']) == 'yellow'
    assert LD.aggregate_lights(['green', 'red', 'green']) == 'red'
    assert LD.aggregate_lights([]) == LD.DATA_MISSING


def test_emotion_market_quadrant_override():
    assert LD.emotion_market_light('ferment') == 'green'
    assert LD.emotion_market_light('ice') == 'red'
    assert LD.emotion_market_light('climax') == 'red'
    assert LD.emotion_market_light('ebb') == LD.DATA_MISSING
    # 四象限覆盖
    assert LD.emotion_market_light('ferment', 'HH') == 'red'
    assert LD.emotion_market_light('ice', 'LL') == 'green'
    assert LD.emotion_market_light('ferment', 'HL') == 'yellow'
    assert LD.emotion_market_light('ice', 'LH') == 'yellow'
    # 不满足前置条件时不覆盖
    assert LD.emotion_market_light('ice', 'HH') == 'red'
    assert LD.emotion_market_light('ferment', 'LL') == 'green'


def test_emotion_stock_light_cross_dim():
    assert LD.emotion_stock_light('严重背离') == 'red'
    assert LD.emotion_stock_light('健康') == 'green'
    assert LD.emotion_stock_light('强健康') == 'green'
    assert LD.emotion_stock_light('中性') == LD.DATA_MISSING


def test_risk_light():
    assert LD.risk_light({'risk': {'judgment': {'level': '高'}}}) == 'red'
    assert LD.risk_light({'risk': {'judgment': {'risk_level': '极高'}}}) == 'red'
    assert LD.risk_light({'risk': {'judgment': {'level': '低'}}}) == 'green'
    # 无 level → 按 risk_sources 高源计数
    src_2 = {'risk': {'judgment': {}, 'status_description': {
        'risk_sources': [{'level': '高'}, {'level': '高'}, {'level': '低'}]}}}
    assert LD.risk_light(src_2) == 'red'
    src_1 = {'risk': {'judgment': {}, 'status_description': {
        'risk_sources': [{'level': '高'}]}}}
    assert LD.risk_light(src_1) == 'yellow'
    src_0 = {'risk': {'judgment': {}, 'status_description': {'risk_sources': []}}}
    assert LD.risk_light(src_0) == 'green'
    assert LD.risk_light({}) == LD.DATA_MISSING


def test_signal_light_three_sources():
    def sig(code, level, status):
        return {'signal': {'judgment': {
            'attribute': {'code': code},
            'strength': {'level': level},
            'maintenance': {'status': status}}}}
    assert LD.signal_light(sig('right_confirmed', '强', 'healthy')) == 'green'
    assert LD.signal_light(sig('risk_warning', '弱', 'decaying')) == 'red'
    assert LD.signal_light(sig('neutral', '中等', 'healthy')) == 'yellow'
    assert LD.signal_light({}) == LD.DATA_MISSING


def _dr_without_lights():
    """构造**不含任何灯键**的 dim_results（证明派生自分析结论，不依赖 SIG 灯色）"""
    return {
        'structure': {'judgment': {'structure': '下降'}, 'status_description': {}},
        'volume_price': {'judgment': {'state': '健康'}, 'status_description': {}},
        'chip_fund': {'judgment': {'phase': 'lifting'}, 'status_description': {}},
        'emotion': {'judgment': {}, 'status_description': {
            'market_phase': 'ferment', 'sector_heat': 'normal',
            'bociasi_quadrant': 'MM'}},
        'risk': {'judgment': {'level': '低'}, 'status_description': {}},
        'valuation': {'judgment': {'valuation_level': {'value': 'high'}},
                      'status_description': {}},
        'signal': {'judgment': {'attribute': {'code': 'trend_running'},
                                'strength': {'level': '强'},
                                'maintenance': {'status': 'healthy'}},
                   'status_description': {}},
    }


def test_dim_light_end_to_end_without_any_light_keys():
    dr = _dr_without_lights()
    assert LD.dim_light(dr, 'structure') == 'red'
    assert LD.dim_light(dr, 'volume_price') == 'green'
    assert LD.dim_light(dr, 'chip_fund') == 'green'
    assert LD.dim_light(dr, 'fund_chip') == 'green'      # 别名
    assert LD.dim_light(dr, 'vp') == 'green'             # 别名
    assert LD.dim_light(dr, 'valuation') == 'red'
    assert LD.dim_light(dr, 'risk') == 'green'
    assert LD.dim_light(dr, 'signal') == 'green'
    # emotion 整体＝三层聚合（市场 ferment 绿 + 板块 normal 黄 + 个股←dim3「健康」绿 → 2 绿 → 绿）
    assert LD.dim_light(dr, 'emotion') == 'green'
    # 个股情绪灯主源＝dim3（Q-439A-3）：dim3 为「严重背离」时个股灯红 → 整体灯红（任一红）
    dr['volume_price']['judgment']['state'] = '严重背离'
    assert LD.dim_light(dr, 'emotion') == 'red'
    # 缺维 → 数据缺失黄，不抛异常
    assert LD.dim_light({}, 'structure') == LD.DATA_MISSING
    assert LD.dim_light({'structure': None}, 'structure') == LD.DATA_MISSING
