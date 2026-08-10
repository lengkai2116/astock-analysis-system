"""323号 S0 测试：深度字段落库（缠论结构 + 筹码分布 + 资金风险）

背景：引擎B（个股页五维）需要缠论结构/筹码分布/资金风险深度字段（约 20 个），
当前存于 strategy_signal_detail 信号 status_recognition 或 phase_detector 内部，
未落 opportunity_tags_cache 标签库。S0 将这些深度字段从信号/引擎迁移至标签库，
实现"单一标签库 + 两引擎差异化取用"（323号 §二）。

实证（2026-08-09）：
- 缠论深度字段（support_resistance/zhongshu_strength/multi_level 等）在 P2 信号中 99% 覆盖；
- 筹码深度字段（asr/cyqkl/concentration/profit_ratio/ssrp）由 ChipIndicators 产出，
  但 _build_chip_status 只透出 6 个字段——P2 信号筹码深度缺失（仅 1.2% 覆盖）；
- phase_detector._last_chip_indicators 已含完整筹码指标但未落库。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)



def test_extract_chanlun_deep_tags_from_p2_signal():
    """从 strategy_signal_detail 缠论信号提取深度字段（support_resistance 等）"""
    from app.opportunity_atlas.tag_extractor import extract_chanlun_deep_tags

    tags = extract_chanlun_deep_tags('000426.SZ')
    assert 'support_resistance' in tags, "应提取 support_resistance"
    assert 'zhongshu_strength' in tags, "应提取 zhongshu_strength"
    assert 'multi_level' in tags, "应提取 multi_level"
    # 支撑/阻力应有真实值（000426 实测 support=31.88 resistance=38.45）
    import json
    sr = (json.loads(tags['support_resistance'])
          if isinstance(tags['support_resistance'], str) else tags['support_resistance'])
    assert sr.get('support', 0) > 0, "支撑价应 >0"
    assert sr.get('resistance', 0) > 0, "阻力价应 >0"


def test_extract_chip_deep_tags_from_phase_detector():
    """从 phase_detector._last_chip_indicators 提取筹码深度字段（asr/cyqkl 等）"""
    from app.opportunity_atlas.tag_extractor import extract_chip_deep_tags

    tags = extract_chip_deep_tags('000426.SZ')
    assert 'asr' in tags, "应提取 asr"
    assert 'cyqkl' in tags, "应提取 cyqkl"
    assert 'concentration' in tags, "应提取 concentration"
    assert 'profit_ratio' in tags, "应提取 profit_ratio"
    assert 'ssrp' in tags, "应提取 ssrp"
    assert 'chip_peak' in tags, "应提取 chip_peak（由 main_peak 映射）"


def test_tag_group_columns_exist():
    """opportunity_tags_cache 已有 tag_group 列（S0 复用，不新增列）"""
    import sqlite3
    conn = sqlite3.connect('../data/duckdb/stock_cache.db')
    cols = [r[1] for r in conn.execute("PRAGMA table_info(opportunity_tags_cache)").fetchall()]
    conn.close()
    assert 'tag_group' in cols, "tag_group 列应已存在"


def test_existing_tag_groups_preserved():
    """现有 tag_group（derived/direction/position 等）不受 S0 影响"""
    import sqlite3
    conn = sqlite3.connect('../data/duckdb/stock_cache.db')
    rows = conn.execute("SELECT DISTINCT tag_group FROM opportunity_tags_cache").fetchall()
    conn.close()
    groups = {r[0] for r in rows}
    assert 'derived' in groups and 'direction' in groups, "现有 tag_group 应保留"
    assert 'screen' not in groups, "不应存在方案早期设想的 screen 组（用现有组）"
