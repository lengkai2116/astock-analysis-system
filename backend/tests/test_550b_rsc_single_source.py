"""550-B：RSC 判定/展示同源 + 致命冲突分数回归。

拍板口径：
- Q3=A：先跑 JUD 重算 RSC，再让 status_engine 用同一 RSC 判状态；
- Q4=A：致命冲突强制 wait 时 final_score 用 wait 下界 45.0（原 30.0 会被读成 reduce）。

本测试不访问数据库、不启动采集。
"""
import inspect
from pathlib import Path
from types import SimpleNamespace

import data_daemon as dd
from app.opportunity_atlas.status_engine import StatusEngine


def _engine_with_cache(pre_feat: dict) -> StatusEngine:
    class _Cache:
        def get_pre_feat(self, ts_code, trade_date=None):
            return pre_feat

    se = object.__new__(StatusEngine)
    se.dm = SimpleNamespace(cache=_Cache(), get_cached_daily_data=lambda ts_code: None)
    se.registry = {}
    se.cfg = {}
    return se


def test_jud_rsc_overrides_filters_and_only_carries_rsc(monkeypatch):
    monkeypatch.setattr(dd, '_jud_meta_cache', {
        '000001.SZ': {'right_side_confirm': '基础确认',
                      'confirm_evidence': ['放量突破']},
        '000002.SZ': {'right_side_confirm': None, 'confirm_evidence': ['x']},
        '000003.SZ': {'signal_strength': 88.0},
    })
    out = dd._jud_rsc_overrides(['000001.SZ', '000002.SZ'])
    assert out == {
        '000001.SZ': {'right_side_confirm': '基础确认',
                      'confirm_evidence': ['放量突破']},
    }


def test_load_tags_override_wins_over_pre_feat():
    se = _engine_with_cache({
        'depth': {'right_side_confirm': '未确认', 'main_force_phase': 'building'},
    })
    tags = se._load_tags('000001.SZ',
                         tag_overrides={'right_side_confirm': '基础确认'})
    assert tags['right_side_confirm'] == '基础确认'
    assert tags['main_force_phase'] == 'building'


def test_load_tags_none_override_does_not_erase():
    se = _engine_with_cache({'depth': {'right_side_confirm': '未确认'}})
    tags = se._load_tags('000001.SZ', tag_overrides={'right_side_confirm': None})
    assert tags['right_side_confirm'] == '未确认'


def test_status_snapshot_accepts_and_passes_overrides():
    sig = inspect.signature(dd._build_status_snapshot)
    assert 'rsc_overrides' in sig.parameters
    src = inspect.getsource(dd._build_status_snapshot)
    assert 'tag_overrides=_rsc_overrides.get(code)' in src
    assert 'rsc_overrides or {}' in src


def test_jud_build_runs_enrich_before_status():
    src = Path(dd.__file__).read_text(encoding='utf-8')
    start = src.index('def _jud_build(_codes):')
    block = src[start:start + 420]
    i_enrich = block.index('_jud_enrich_with_meta')
    i_status = block.index('_build_status_snapshot')
    i_treemap = block.index('_build_treemap_snapshot')
    assert i_enrich < i_status < i_treemap
    assert '_jud_rsc_overrides(_codes)' in block


def test_fatal_conflict_wait_uses_45_not_30():
    src = inspect.getsource(StatusEngine._aggregate_v390)
    start = src.index("if conflict.get('fatal_to_veto'):")
    block = src[start:start + 320]
    assert 'consensus, conflict, 45.0, reliability' in block
    assert 'consensus, conflict, 30.0, reliability' not in block
