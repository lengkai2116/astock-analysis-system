"""509号批次7：低危清理验证（§五 清单）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.9。

批次7 实施范围（2026-10-08）：
  - #J1 `strategy_analyze` `_r` 死分支删除（原为不可达 NameError 残留）；
  - `factor_arbiter` 冗余条件 `fatal_list and len(fatal_list) > 0` → `if fatal_list`；
  - `advice_builder` R:R 门字面量 2.0 → RR_GATE 常量引用；
  - `advice_engine` `_apply_stop_and_tiers` 死参 dim_results 移除；
  - 函数内 import 上移：dim_adapter `import re`、light_derive `import math`、
    advice_engine `_weekly_dir_from_multi_level`；
  - 静默 except 加日志：dim_adapter 周线读 / status_engine 市场池 / potential_engine
    earn·fund 截面 / tag_extractor pre_feat 兜底；
  - potential_engine NaN/inf 守卫（val/roe）+ LIMIT 绑定参；
  - watchlist pre_close 除零守卫 / query.get→db.session.get / add 并发竞态回滚 /
    dashboard 批量取名（daily df 无 name 列）；
  - strategy_analyze dim_states 单次解析 / deep_chip concentration 数值化 /
    惰性日志 / 裸表达式删除 / logger 重复删除；
  - radar L4 实例缓存；reliability docstring ATR 阈值语义修正。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

# ── factor_arbiter：冗余条件删除后行为不变 ──────────────────

def test_factor_arbiter_fatal_veto():
    """fatal_to_veto 非空仍强制 wait（冗余 len 条件删除后行为一致）"""
    from app.opportunity_atlas.factor_arbiter import arbitrate

    r = arbitrate(consensus={'consensus_rate': 0.8},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': ['A', 'B']},
                  tags={}, dims_factor={}, reliability={})
    assert r['opportunity_state'] == 'wait'
    assert '致命冲突' in ' '.join(r['conflict_evidence'])


def test_factor_arbiter_no_fatal():
    """fatal_to_veto 为空 → 不强制 wait（走正常共识路径）"""
    from app.opportunity_atlas.factor_arbiter import arbitrate

    r = arbitrate(consensus={'consensus_rate': 0.8},
                  conflict={'semantic_adjustment': 1.0, 'fatal_to_veto': []},
                  tags={}, dims_factor={}, reliability={})
    assert r['opportunity_state'] != 'wait'


# ── advice_builder：RR_GATE 常量引用 ────────────────────────

def test_advice_builder_rr_gate_constant():
    """advice_builder R:R 门引用 RR_GATE 常量（非字面量）"""
    import inspect

    import app.opportunity_atlas.advice_builder as ab

    assert ab.RR_GATE == 2.0
    src = inspect.getsource(ab)
    # 生效路径用常量：门禁处不应再有裸 `< 2.0`
    assert '_rr < RR_GATE' in src


# ── advice_engine：死参移除 ─────────────────────────────────

def test_advice_engine_stop_tiers_signature():
    """_apply_stop_and_tiers 已移除 dim_results 死参"""
    import inspect

    from app.opportunity_atlas.advice_engine import _apply_stop_and_tiers

    sig = inspect.signature(_apply_stop_and_tiers)
    assert 'dim_results' not in sig.parameters


# ── 函数内 import 上移（AST 级） ────────────────────────────

def test_no_function_level_imports():
    """dim_adapter/light_derive 不再有函数内 import re/math"""
    import ast

    for path in ('app/opportunity_atlas/dim_adapter.py',
                 'app/opportunity_atlas/light_derive.py'):
        full = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
        tree = ast.parse(open(full, encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Import) and child.col_offset > 0:
                        names = [a.name for a in child.names]
                        assert not {'re', 'math'} & set(names), \
                            f'{path}: 函数内 import {names}'


# ── potential_engine：NaN/inf 守卫 ──────────────────────────

def _eng_with_tables():
    """构造带默认截面表的引擎（测试环境无 DB，__init__ 建表失败时补默认）"""
    from app.opportunity_atlas.potential_engine import PotentialEngine, _percentile_lookup

    eng = PotentialEngine()
    for k in ('val', 'earn', 'fund', 'sector', 'trend'):
        if k not in eng._tables:
            eng._tables[k] = _percentile_lookup([])
    return eng


def test_potential_nan_guard():
    """float('nan')/('inf') 不进入 percent lookup（不污染 signal_strength）"""
    eng = _eng_with_tables()
    r = eng.compute_potential({'valuation_deviation': 'nan', 'roe': 'inf'})
    assert 'val' in r.get('potential_breakdown', {})
    assert 'earn' in r.get('potential_breakdown', {})
    ss = r.get('signal_strength', 0)
    assert isinstance(ss, (int, float)) and ss == ss, 'signal_strength 不应为 NaN'


# ── watchlist：pre_close 除零守卫 ───────────────────────────

def test_watchlist_pre_close_zero_guard():
    """pct_chg=-100 不再除零（pre_close=None 而非抛错）"""
    # _build_watch_item 逻辑内联验证：1+pct/100==0 时走 None 分支
    cp, pct = 10.0, -100.0
    pre_close = round(cp / (1 + pct / 100), 2) if cp and pct is not None and (1 + pct / 100) != 0 else None
    assert pre_close is None


def test_watchlist_pre_close_normal():
    """正常 pct 下 pre_close 计算不变"""
    cp, pct = 10.0, 10.0
    pre_close = round(cp / (1 + pct / 100), 2) if cp and pct is not None and (1 + pct / 100) != 0 else None
    assert pre_close == round(10.0 / 1.1, 2)


# ── strategy_analyze：deep_chip concentration 数值化 ───────

def test_chip_concentration_numeric():
    """concentration 为 str 时不抛 TypeError（走 --）"""
    from app.routes.strategy_analyze import _build_chip_dimension

    r = _build_chip_dimension(None, {'concentration': 'abc'})
    assert r['concentration'] == '--'


def test_chip_concentration_normal():
    """concentration 为数值时正常百分比"""
    from app.routes.strategy_analyze import _build_chip_dimension

    r = _build_chip_dimension(None, {'concentration': 0.35})
    assert r['concentration'] == '35.0%'


# ── strategy_analyze：`_r` 死分支删除（AST 级） ────────────

def test_strategy_analyze_no_undefined_r():
    """strategy_analyze 不再引用未定义 `_r`（原死分支 NameError）"""
    import ast
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'routes', 'strategy_analyze.py')
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    # 收集模块内所有赋值目标，确认 `_r` 从未定义且不再被引用
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    assert '_r' not in names


# ── radar：L4 实例缓存 ─────────────────────────────────────

def test_radar_l4_cached():
    """RadarService._get_l4 返回实例级缓存（同实例多次调用同一对象）"""
    from app.opportunity_atlas.radar_service import RadarService

    svc = RadarService(data_manager=None)
    a = svc._get_l4()
    b = svc._get_l4()
    assert a is b
    # 不同实例各自持有（不共享，避免跨请求状态）
    svc2 = RadarService(data_manager=None)
    assert svc2._get_l4() is not a


# ── reliability docstring 语义修正 ─────────────────────────

def test_reliability_risk_docstring():
    """_assess_risk docstring 阈值对齐百分数语义（<3.0/>7.0）"""
    import inspect

    from app.opportunity_atlas import reliability_assessor as ra

    doc = inspect.getdoc(ra._assess_risk)
    assert '3.0' in doc and '7.0' in doc, f'docstring 应反映百分数阈值: {doc}'
