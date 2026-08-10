"""323号 S0.5 测试：get_tags_by_group 网关 + 引擎B 五维构建读标签库深度字段

背景：S0 已将深度字段（缠论结构/筹码分布）落库至 opportunity_tags_cache。
S0.5 实现：① DataManager 新增 get_tags_by_group 按 tag_group 取子集；
② 引擎B 五维构建（_build_chanlun_dimension/_build_chip_dimension）改读标签库
深度字段，信号回退（signal_computation_service 完整信号作兜底）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)



def test_get_tags_by_group_filters():
    """get_tags_by_group 按 tag_group 取子集（structure/chip_deep）"""
    from app.data import DataManager
    dm = DataManager()
    # structure 组：support_resistance/zhongshu_strength 等（S0 已落库 000426）
    struct = dm.get_tags_by_group('000426.SZ', ['structure'])
    assert 'support_resistance' in struct, "structure 组应含 support_resistance"
    assert 'zhongshu_strength' in struct, "structure 组应含 zhongshu_strength"
    # chip_deep 组
    chip = dm.get_tags_by_group('000426.SZ', ['chip_deep'])
    assert 'asr' in chip or 'cyqkl' in chip, "chip_deep 组应含筹码深度字段"
    # 组合查询
    both = dm.get_tags_by_group('000426.SZ', ['structure', 'chip_deep'])
    assert 'support_resistance' in both and 'asr' in both, "组合组应返回全部"


def test_build_chanlun_dimension_reads_tags():
    """_build_chanlun_dimension 应优先读标签库 support_resistance（信号缺失时）"""
    from app.routes.strategy_analyze import _build_chanlun_dimension
    # 模拟：信号 sig 为空（无缠论信号），但 tags 有深度字段
    dim = _build_chanlun_dimension(None, latest_close=30.0, tags={
        'support_resistance': '{"support": 28.0, "resistance": 32.0}',
        'zhongshu_strength': 'weak',
        'multi_level': '{"level": "daily"}',
    })
    # 应能从 tags 恢复 critical_levels
    cl = dim.get('critical_levels', {})
    assert cl.get('support') == 28.0, f"critical_levels.support 应从 tags 恢复，实际 {cl}"
    assert cl.get('resistance') == 32.0


def test_build_chip_dimension_reads_tags():
    """_build_chip_dimension 应优先读标签库筹码深度（信号缺失时）"""
    from app.routes.strategy_analyze import _build_chip_dimension
    # 模拟：信号 sig 为空，tags 有 chip_peak/asr
    dim = _build_chip_dimension(None, tags={
        'chip_peak': '39.65',
        'asr': '0.1357',
        'concentration': '1.1745',
        'profit_ratio': '0.6224',
    })
    assert dim.get('avg_cost') == 39.65, f"avg_cost 应从 chip_peak 恢复，实际 {dim.get('avg_cost')}"
    assert dim.get('direction') in ('neutral', 'bullish', 'bearish')


def test_build_volume_price_dimension_fallback():
    """_build_volume_price_dimension 信号缺失时应回退默认（不崩溃）"""
    from app.routes.strategy_analyze import _build_volume_price_dimension
    dim = _build_volume_price_dimension(None)
    assert dim.get('direction') == 'neutral'
    assert 'status_text' in dim
