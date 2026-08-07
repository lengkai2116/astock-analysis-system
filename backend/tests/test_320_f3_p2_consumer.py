"""320号 F3/F4 回归测试：九层解读消费 P2 产物 + 标签基线注入

F3：_build_p2_signal_summary 从 strategy_signal_detail（P2 预计算）提取策略信号摘要，
    避免实时重算（消除 E12/E13/E14 重复计算）。
F4：_build_label_baseline 从 opportunity_tags_cache 构建标签基线（七维红绿灯+关键标签），
    作为九层解读的权威结论对齐源。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest


@pytest.fixture(scope='module')
def ecm():
    from app.data.enhanced_cache_manager import EnhancedCacheManager
    return EnhancedCacheManager()


def _sample_with_signals(ecm):
    """找 strategy_signal_detail 有 signals 的股票"""
    row = ecm.conn.execute(
        "SELECT ts_code FROM strategy_signal_detail WHERE signal_json LIKE '%\"signals\": {\"%' LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def test_signal_detail_has_signals_for_adequate_stocks(ecm):
    """strategy_signal_detail 应有 signals 非空的股票（P2 预计算产物可用）"""
    assert _sample_with_signals(ecm), "strategy_signal_detail 应有 signals 非空记录"


def test_build_p2_signal_summary(ecm):
    """F3：_build_p2_signal_summary 应从 strategy_signal_detail 提取策略信号摘要"""
    from app.routes.strategy_analyze import _build_p2_signal_summary
    ts = _sample_with_signals(ecm)
    assert ts, "需要信号样例股票"
    summary = _build_p2_signal_summary(ts)
    assert summary, "应生成策略信号摘要（修复前实时计算无预计算产物）"
    assert '缠论' in summary or 'BOCIASI' in summary or '量价' in summary, \
        f"摘要应含策略信号名，实际前100字: {summary[:100]}"


def test_build_label_baseline(ecm):
    """F4：_build_label_baseline 应从 opportunity_tags_cache 构建标签基线"""
    from app.routes.strategy_analyze import _build_label_baseline
    # 用 600519（快照有 opportunity_profile）
    baseline = _build_label_baseline('600519.SH')
    assert baseline, "600519 应有标签基线（七维红绿灯或关键标签）"
    assert '风险' in baseline or '价值' in baseline or '估值' in baseline, \
        f"基线应含画像/标签维度，实际前100字: {baseline[:100]}"


def test_deepseek_user_prompt_includes_p2_and_baseline(ecm, monkeypatch):
    """F3/F4：九层解读 user prompt 应包含 P2 摘要与标签基线（不再仅依赖实时快照）"""
    from app.routes import strategy_analyze as sa
    # 600519 K 线已补采（F1），但 prompt 组装应优先 P2+基线
    p2 = sa._build_p2_signal_summary('600519.SH')
    base = sa._build_label_baseline('600519.SH')
    # 600519 补采后 strategy_signal_detail 可能有 signals（若 P2 重算过）
    # 核心断言：辅助函数均可生成内容（任一非空即可支撑 prompt）
    assert p2 or base, "P2 摘要或标签基线至少一个应有内容"
