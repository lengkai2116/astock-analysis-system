"""494号 批次1 回归（R-2 主链大级别否决 + R-10 周线方向取数）

知识库依据：《分层决策框架》主决策周期唯一、他周期不能否决；周线（背景周期）明确向下而
日线（决策周期）看多 → 矛盾，丢弃买点、降 wait（不判 avoid/空）。

494号两处要点（详见方案 §四 批次1 / §九 R-10）：
- **R-2**：`factor_arbiter.arbitrate` 末段新增大级别否决，与两处 `build_operation_advice`
  建议卡同判据、同语义（周线 down + 日线多 + enter/light → wait）。
- **R-10**：主链 `status_engine._load_tags` 只读 pre_feat，而 pre_feat **不含 multi_level**
  （实证 0/600），故周线方向必须由 `dim_adapter.weekly_direction_from_dim_results(dim_results)`
  取自 dim2 多级别联立后经 `arbitrate(weekly_direction=...)` 传入。
- **共用纯函数**：方向词表/取值口径收敛为 SSOT `dim_adapter._weekly_dir_from_multi_level`，
  供主链与 advice_engine / advice_builder 三处共用。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.dim_adapter import (  # noqa: E402
    _weekly_dir_from_multi_level,
    weekly_direction_from_dim_results,
)
from app.opportunity_atlas.factor_arbiter import arbitrate  # noqa: E402

# ── fixture ─────────────────────────────────────────────────────────

_TAGS = {'right_side_confirm': '强确认'}


def _arb(weekly: str = '', consensus_rate: float = 1.0,
         dims_factor: dict = None) -> dict:
    """调 arbitrate：consensus_rate=1.0 → base 100 → enter（强确认 ×1.0）"""
    if dims_factor is None:
        dims_factor = {'structure': {'direction': 1}, 'vp': {'direction': 1}}
    return arbitrate(
        {'consensus_rate': consensus_rate, 'direction': 'bullish'},
        {},  # conflict：semantic_adjustment 默认 1.0、无 fatal_to_veto
        _TAGS, dims_factor, {},
        weekly_direction=weekly,
    )


def _dim_results_with_weekly(weekly: str) -> dict:
    return {
        'structure': {
            'status_description': {
                'multi_level': {'direction_map': {'weekly': weekly, 'daily': 'up'}},
            },
            'judgment': {'overall_direction': 1},
        },
    }


# ── 1. SSOT：_weekly_dir_from_multi_level ────────────────────────────

def test_ssot_dict_and_json_string():
    assert _weekly_dir_from_multi_level({'direction_map': {'weekly': 'down'}}) == 'down'
    assert _weekly_dir_from_multi_level(
        json.dumps({'direction_map': {'weekly': 'up'}})) == 'up'


def test_ssot_wordlist_variants():
    """词表兼容：中文/英文/买卖标记"""
    assert _weekly_dir_from_multi_level({'direction_map': {'weekly': '下降'}}) == 'down'
    assert _weekly_dir_from_multi_level({'direction_map': {'weekly': 'bearish'}}) == 'down'
    assert _weekly_dir_from_multi_level({'direction_map': {'weekly': '上升'}}) == 'up'
    assert _weekly_dir_from_multi_level({'direction_map': {'weekly': 'bullish'}}) == 'up'


def test_ssot_missing_or_unknown_returns_empty():
    assert _weekly_dir_from_multi_level(None) == ''
    assert _weekly_dir_from_multi_level({}) == ''
    assert _weekly_dir_from_multi_level({'direction_map': {'weekly': 'unknown'}}) == ''
    assert _weekly_dir_from_multi_level({'direction_map': {}}) == ''


# ── 2. R-10：weekly_direction_from_dim_results（主链取数） ────────────

def test_r10_reads_weekly_from_dim_results():
    assert weekly_direction_from_dim_results(_dim_results_with_weekly('down')) == 'down'
    assert weekly_direction_from_dim_results(_dim_results_with_weekly('up')) == 'up'


def test_r10_empty_when_multi_level_absent():
    """pre_feat 派生的 tags 无 multi_level、dim_results 亦无 → 不产（不误判）"""
    assert weekly_direction_from_dim_results({}) == ''
    assert weekly_direction_from_dim_results({'structure': {'status_description': {}}}) == ''
    assert weekly_direction_from_dim_results({'structure': None}) == ''


# ── 3. R-2：arbitrate 大级别否决 ─────────────────────────────────────

def test_weekly_down_degrades_enter_to_wait():
    r = _arb('down')
    assert r['opportunity_state'] == 'wait', f"周线向下应降 wait，实际 {r['opportunity_state']}"
    assert any('大级别否决' in e for e in r['state_evidence'])


def test_weekly_up_or_missing_keeps_state():
    for w in ('up', '', None):
        r = _arb(w)
        assert r['opportunity_state'] == 'enter', f"weekly={w!r} 不应否决，实际 {r['opportunity_state']}"


def test_no_veto_when_daily_not_bullish():
    """日线不看多（结构/量价方向票均 ≤0）→ 不触发（避免对纯空头重复判）"""
    r = _arb('down', dims_factor={'structure': {'direction': 0}, 'vp': {'direction': -1}})
    assert r['opportunity_state'] == 'enter'


def test_no_veto_when_already_not_enter_light():
    """已 wait/reduce/avoid → 不因否决再改（只对 enter/light 生效）"""
    # consensus 0.5 → 50 → wait
    assert _arb('down', consensus_rate=0.5)['opportunity_state'] == 'wait'
    # 0.35 → 35 → reduce
    assert _arb('down', consensus_rate=0.35)['opportunity_state'] == 'reduce'
    # 0.2 → 20 → avoid
    assert _arb('down', consensus_rate=0.2)['opportunity_state'] == 'avoid'


def test_light_also_vetoed():
    """light（65-79）同样降 wait"""
    r = _arb('down', consensus_rate=0.7)  # 70 → light
    assert r['opportunity_state'] == 'wait'


# ── 4. 主链端到端（_aggregate_v390，R-10 接线） ──────────────────────

def _make_engine():
    from app.opportunity_atlas.status_engine import StatusEngine
    eng = StatusEngine.__new__(StatusEngine)
    eng.cfg = {'jud_engine_version': 'v390'}
    eng._detect_market_regime = staticmethod(lambda tags, dims: 'ranging')
    eng.MARKET_REGIME_WEIGHTS = StatusEngine.MARKET_REGIME_WEIGHTS
    return eng


def _run_main_line(dim_results: dict) -> dict:
    """复用 418 号 fixture（signal 合并），端到端跑主链 L5"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        't418', os.path.join(os.path.dirname(__file__), 'test_418_jud_v390.py'))
    t418 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t418)
    eng = _make_engine()
    l0 = {'position_coeff': 1.0, 'hold_only': False, 'soft_risks': [],
          'hard_veto': False, 'hard_reason': '', 'emotion_position_cap': None}
    merged = t418._merge_signal_analysis(dict(dim_results))
    return eng._aggregate_v390(t418.MOCK_TAGS, {}, l0, {}, merged, '000001.SZ')


def test_main_line_baseline_is_enter():
    """无 multi_level（fixture 原样）→ 维持 enter（回归：不误否决）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        't418b', os.path.join(os.path.dirname(__file__), 'test_418_jud_v390.py'))
    t418 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t418)
    r = _run_main_line(dict(t418.MOCK_DIM_RESULTS))
    assert r['opportunity_state'] == 'enter', f"基线应 enter，实际 {r['opportunity_state']}"


def test_main_line_weekly_down_vetoes():
    """主链：dim_results 注入 weekly=down → opportunity_state 降 wait（R-2 生效）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        't418c', os.path.join(os.path.dirname(__file__), 'test_418_jud_v390.py'))
    t418 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t418)
    dr = dict(t418.MOCK_DIM_RESULTS)
    dr['structure'] = dict(dr['structure'])
    dr['structure']['status_description'] = dict(dr['structure']['status_description'])
    dr['structure']['status_description']['multi_level'] = {
        'direction_map': {'weekly': 'down', 'daily': 'up'}}
    r = _run_main_line(dr)
    assert r['opportunity_state'] == 'wait', f"主链应降 wait，实际 {r['opportunity_state']}"
    assert any('大级别否决' in e for e in r['state_evidence']), r['state_evidence'][-3:]


# ── 5. 共用纯函数不变式（三处同口径） ────────────────────────────────

def test_advice_paths_share_ssot():
    """advice_engine / advice_builder 的 _weekly_direction 与 SSOT 同结果"""
    from app.opportunity_atlas.advice_builder import _weekly_direction as _wb
    from app.opportunity_atlas.advice_engine import _weekly_direction as _we
    for w in ('down', 'up', 'unknown'):
        _t = {'multi_level': json.dumps({'direction_map': {'weekly': w}})}
        expect = _weekly_dir_from_multi_level(_t['multi_level'])
        assert _we(_t) == expect
        assert _wb(_t) == expect
    # dimensions 来源（analyze 路径）
    dims = {'chanlun': {'multi_level': {'direction_map': {'weekly': 'down'}}}}
    assert _we(None, dims) == 'down'
    assert _wb(None, dims) == 'down'
