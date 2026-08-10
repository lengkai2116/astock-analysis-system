"""323号 S0.7 测试：执行层统一——弹窗 diagnose 操作建议改读 advice_builder

背景：双输出执行层冲突（止损-15%/仓位0.7vs0.6/入场规则不同）源于两套独立实现
（cross_validate._build_trade_plan vs advice_builder）。S0.7 让弹窗 diagnose 的
operation_advice 改为引用 advice_builder 输出（唯一仓位/止损/入场来源）。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


def test_build_advice_from_tags():
    """从标签构造 advice_builder 输入（diagnose 无五维时可用）"""
    from app.opportunity_atlas.advice_builder import build_operation_advice
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    from app.data import DataManager

    dm = DataManager()
    cv = L4CrossValidator(dm)
    tags = cv._load_tags('000426.SZ')
    df = dm.get_cached_daily_data('000426.SZ')
    # 从标签构造简化 dimensions（screen 组）
    dimensions = {
        'factor': {'trend': 'bullish' if str(tags.get('trend_alignment', '')) == 'up_aligned' else 'neutral'},
        'chanlun': {'direction': '上升', 'buy_point': tags.get('buy_sell_point', '')},
        'volume_price': {'direction': 'up'},
        'chip': {'direction': 'bullish' if tags.get('fund_flow') == '5d_inflow' else 'neutral'},
        'emotion': {'direction': 'bullish'},
    }
    advice = build_operation_advice('000426.SZ', dimensions, [], df, tags=tags)
    assert 'state' in advice and 'executable' in advice
    assert advice['executable']['position']['max_pct'] >= 0


def test_diagnose_operation_advice_unified_format():
    """弹窗 diagnose 的 operation_advice 应为 advice_builder 新格式（含 state/executable）"""
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    from app.data import DataManager

    dm = DataManager()
    cv = L4CrossValidator(dm)
    tags = cv._load_tags('000426.SZ')
    d = cv.diagnose('000426.SZ', tags)
    oa = d['operation_advice']
    # 新格式：应有 state/executable（advice_builder 产物），而非仅旧格式 action/label
    assert 'state' in oa or 'executable' in oa, \
        f"operation_advice 应为新格式（含 state/executable），实际键: {list(oa.keys())}"
    assert 'executable' in oa, "应含 executable（机器可执行）"
    assert 'action_type' in oa['executable'], "executable 应含 action_type"


def test_stop_loss_consistent_between_engines():
    """双输出止损一致（S0.7 核心：消除 -15% 止损冲突）"""
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    from app.data import DataManager

    dm = DataManager()
    cv = L4CrossValidator(dm)
    tags = cv._load_tags('000426.SZ')
    d = cv.diagnose('000426.SZ', tags)
    oa = d['operation_advice']
    # 新格式 executable.exit_rules 的止损价
    exit_rules = oa.get('executable', {}).get('exit_rules', [])
    assert exit_rules, "executable 应含 exit_rules（止损）"
    # 与 advice_builder 独立计算一致（同源）
    from app.opportunity_atlas.advice_builder import build_operation_advice
    df = dm.get_cached_daily_data('000426.SZ')
    dims = {'factor': {'trend': 'neutral'}, 'chanlun': {'direction': '上升'},
            'volume_price': {'direction': 'up'}, 'chip': {'direction': 'neutral'},
            'emotion': {'direction': 'bullish'}}
    advice = build_operation_advice('000426.SZ', dims, [], df, tags=tags)
    if advice['executable']['exit_rules'] and exit_rules:
        assert exit_rules == advice['executable']['exit_rules'], \
            f"双输出止损应一致: {exit_rules} vs {advice['executable']['exit_rules']}"
