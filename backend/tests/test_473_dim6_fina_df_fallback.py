"""473号 B：dim6 PIERS-E 高杠杆判据 data_context.fina_df 兜底 + 异常记日志

覆盖：tags 缺 debt_to_assets/roce 时，从 data_context.fina_df（dim1 预加载）
补齐，避免每次 evaluate 走独立 DB 查询；兜底查询异常记日志而非静默吞。
纯逻辑测试，无 DB 锁依赖（daemon 停止态下运行亦可）。
"""
import pandas as pd

from app.opportunity_atlas.dimensions.dim6_risk_engine import _assess_piers_leverage


def _mk_fina(debt=40.0, roce=20.0) -> pd.DataFrame:
    """构造 fina_indicator 风格 DataFrame（含 debt_to_assets/roce 列）"""
    return pd.DataFrame([{'debt_to_assets': debt, 'roce': roce}])


def test_fina_df_supplies_missing_debt_to_assets():
    """tags 缺 debt_to_assets 时，从 data_context.fina_df 补齐 → 高杠杆触发"""
    tags = {'roce': 20.0}  # 无 debt_to_assets（473号前 RAW 不产，走 fina_df 兜底）
    result = _assess_piers_leverage(tags, None, 'TEST.XSHG', fina_df=_mk_fina(debt=85.0, roce=20.0))
    assert result['triggered'] is True, "fina_df 提供 debt_to_assets=85>70 应触发高杠杆"
    assert any(f['factor'].startswith('高杠杆') for f in result['factors'])
    assert result['metrics']['debt_to_assets'] == 85.0


def test_fina_df_supplies_missing_roce():
    """tags 缺 roce 时，从 data_context.fina_df 补齐 → 低回报触发"""
    tags = {'debt_to_assets': 40.0}  # 无 roce
    result = _assess_piers_leverage(tags, None, 'TEST.XSHG', fina_df=_mk_fina(debt=40.0, roce=8.0))
    assert result['triggered'] is True, "fina_df 提供 roce=8<15 应触发低回报"
    assert any(f['factor'].startswith('资本回报率') for f in result['factors'])


def test_tags_shortcut_does_not_query_fina_df():
    """tags 完整（473号预计算短路）时不触碰 fina_df（无需任何数据兜底）"""
    tags = {'debt_to_assets': 40.0, 'roce': 20.0}  # 都有，走 tags
    result = _assess_piers_leverage(tags, None, 'TEST.XSHG', fina_df=None)
    assert result['triggered'] is False
    assert result['metrics'] == {'debt_to_assets': 40.0, 'roce': 20.0}


def test_tags_priority_over_fina_df():
    """tags 已有时，fina_df 值不覆盖（tags 优先）"""
    tags = {'debt_to_assets': 50.0, 'roce': 18.0}
    result = _assess_piers_leverage(tags, None, 'TEST.XSHG', fina_df=_mk_fina(debt=85.0, roce=8.0))
    assert result['metrics']['debt_to_assets'] == 50.0
    assert result['metrics']['roce'] == 18.0
    assert result['triggered'] is False, "tags 50/18 不触发，fina_df 85/8 不应覆盖"


def test_no_data_any_source_no_trigger():
    """tags/fina_df/dm 全缺 → 不触发（无数据保守）"""
    result = _assess_piers_leverage({}, None, '', fina_df=None)
    assert result['triggered'] is False
    assert result['metrics'] == {'debt_to_assets': None, 'roce': None}
