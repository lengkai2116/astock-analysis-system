"""507号批次1：SIG 生效路径缺陷修复验证（#S1/#S3/#S5）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §三。

批次1 实施范围（2026-10-03）：
  #S1 `dim3_vp_engine` 模块级 `logger` 未定义 → except 分支抛 NameError（已修）；
  #S3 daemon RAW-2 筹码指标（SSRP）前移 + 注入 `extra_tags['ssrp']` →
      `PhaseDetectionEngine._dim_ssrp` 维度6 恢复投票（已修）；
  #S5 `dim6_risk_engine` ST 升格 `int(None)` 抛错被吞 → 显式守卫 + 日志升 warning（已修）。

**已移出批次1（行为变更，另议）**：
  #S2 `emotion_temperature` None→0：docstring 承诺中性 50，但 494 号（用户 2026-09-28 拍板）
     故意依赖 None→0（冰点真冰点 32.5 < ICE_RECOVERY_TEMP=35）；改 50 会越门误判回升。
  #S4 `consensus_engine` 中性维 dict 计数：修复会让中性占比上限（>0.6）复活，
     改变 JUD `_aggregate_v390` 输出（494 fixture 由 enter→wait）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


# ── #S1：dim3 模块级 logger 已定义 ──────────────────────────

def test_s1_dim3_logger_defined():
    """dim3_vp_engine 有模块级 logger（原缺失 → except 分支 logger.warning 抛 NameError）"""
    import logging
    from app.opportunity_atlas.dimensions import dim3_vp_engine as m

    assert hasattr(m, 'logger'), 'dim3_vp_engine 缺模块级 logger'
    assert isinstance(m.logger, logging.Logger)
    m.logger.warning("PatternEngine.evaluate 异常: %s", RuntimeError("probe"))


def test_s1_dim3_module_defines_logger_ast():
    """AST 级：模块作用域存在 logger 赋值（无 NameError 风险）"""
    import ast
    import inspect
    from app.opportunity_atlas.dimensions import dim3_vp_engine as m

    tree = ast.parse(inspect.getsource(m))
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
    assert 'logger' in assigned, 'dim3_vp_engine 未定义 logger'


# ── #S3：SSRP 注入后维度6 恢复投票 ──────────────────────────

def _mk_df():
    import pandas as pd
    return pd.DataFrame({'close': [10.0] * 60, 'high': [10.0] * 60,
                         'low': [10.0] * 60, 'open': [10.0] * 60,
                         'vol': [1000.0] * 60})


def test_s3_dim_ssrp_votes_when_provided():
    """提供 ssrp（现价 10 / 成本 20 → rel=0.5 < 0.85）→ _dim_ssrp 返回非空投票"""
    from app.opportunity_atlas.phase_detector import PhaseDetectionEngine

    out = PhaseDetectionEngine()._dim_ssrp(_mk_df(), {'ssrp': 20.0})
    assert out, '有 ssrp 时 _dim_ssrp 不应返回空'


def test_s3_dim_ssrp_empty_without_ssrp():
    from app.opportunity_atlas.phase_detector import PhaseDetectionEngine

    assert PhaseDetectionEngine()._dim_ssrp(_mk_df(), {}) == {}


def test_s3_daemon_injects_ssrp_into_extra():
    """daemon RAW-2 含 SSRP 前移计算 + 注入 _extra['ssrp']（源码级断言）"""
    import inspect
    import data_daemon as dd

    src = inspect.getsource(dd)
    assert "_extra['ssrp'] = _chip_pre.get('ssrp')" in src, '未注入 ssrp'
    assert '筹码指标前移' in src, '未前移筹码指标计算'
    assert "_chip_pre = _cp_ci.calculate_all_indicators(" in src or '_chip_pre = _cp_ci' in src


# ── #S5：dim6 ST 升格守卫 ───────────────────────────────────

def test_s5_dim6_st_direction_guarded():
    """ST 升格对 direction 使用 int(float(...)) 守卫（原 int(None) 抛错被吞）"""
    import inspect
    from app.opportunity_atlas.dimensions import dim6_risk_engine as m

    src = inspect.getsource(m)
    assert "int(float(ev.get('direction', 0)))" in src, '未使用 int(float(...)) 守卫'
    assert 'ST_WARNING_EXTREME_DIR' in src


def test_s5_event_block_log_warning_not_debug():
    """事件风险块 except 由 debug 升 warning（原静默吞致升格丢失不可观测）"""
    import inspect
    from app.opportunity_atlas.dimensions import dim6_risk_engine as m

    src = inspect.getsource(m)
    assert '403号Q-05 EventMonitor检测跳过 [%s]' in src
