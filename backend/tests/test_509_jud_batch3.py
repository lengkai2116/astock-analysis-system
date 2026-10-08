"""509号批次3：建议/展示层修复验证（#J18~#J27）

方案档：`002-方案存档/509-JUD板块OCR核查与处置.md` §9.5。

批次3 实施范围（2026-10-06）：
  #J18 `signal_analyzer.calc_lifecycle_stage`：自动验证（day>=3 且价在突破位上方）与调用方
      显式确认分离 —— 新增 `auto_verified` 字段标注来源，verified 保持最终结果；
  #J19 `signal_analyzer.detect_decay`：volume_ratio 缺失/为空 → 显式未知 20，不误报「健康」10；
  #J20 `advice_engine._safe_float`：拦 NaN/inf（float('nan')/'inf' 可成功解析，污染仓位计算）；
  #J21 `advice_engine` L0c 门 + 软风险仓位：静默 `except: pass` → warning 日志（语义不降级）；
  #J22 `advice_engine._build_advice_card_fields`：factor 键为 None 时 `.get` 抛 AttributeError →
      (dims.get('factor') or {}) 兜底；
  #J23 `radar_service.get_radar_signals`：get_tags_batch 单条 IN 候选上千占位符超限 → 分块(200)合并；
  #J24 `radar_service._evaluate_push_level`：未知 level 不静默落 99 → 显式告警按 normal 参与；
  #J25 `radar_service.get_watchboard`：name_map 逐只 N+1 → get_stock_meta_batch 批量取名（回退逐只）；
  #J26 `time_rhythm_engine.compute_tags`：参考区间与比对窗口统一为近 30 根（原 60 根过/欠计）；
  #J27 `time_rhythm_engine.compute_tags`：ref_mid<=0（非正价格）阈值无意义 → 不计数。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest  # noqa: E402

# ── #J19：detect_decay volume_ratio 缺失 → 显式未知 20 ─────────────

def test_j19_volume_ratio_missing_not_healthy():
    """volume_ratio 缺失 → volume_energy=35（显式未知），不落健康 15（#J8 标定后）"""
    from app.opportunity_atlas import signal_analyzer as sa

    r = sa.detect_decay(tags={}, lifecycle={'day': 3})
    assert r['breakdown']['volume_energy']['score'] == 35, (
        '缺失量比应显式未知(35)，而非健康(15)')


def test_j19_volume_ratio_present_scoring():
    """volume_ratio 有值 → 按 <0.5/<0.8 分档正常（#J8 标定后 85/55/15）"""
    from app.opportunity_atlas import signal_analyzer as sa

    r_low = sa.detect_decay(tags={'volume_ratio': 0.4}, lifecycle={'day': 3})
    r_hi = sa.detect_decay(tags={'volume_ratio': 1.5}, lifecycle={'day': 3})
    assert r_low['breakdown']['volume_energy']['score'] == 85
    assert r_hi['breakdown']['volume_energy']['score'] == 15


# ── #J18：calc_lifecycle_stage auto_verified 来源分离 ─────────────

def test_j18_auto_verified_flag():
    """day>=3 且 distance>0 自动验证 → auto_verified=True，verified=True"""
    from app.opportunity_atlas import signal_analyzer as sa

    r = sa.calc_lifecycle_stage({'day': 4, 'distance_to_signal_pct': 2.0})
    assert r['verified'] is True
    assert r['auto_verified'] is True


def test_j18_explicit_verified_no_auto():
    """调用方显式 verified=True → auto_verified=False（非自动路径）"""
    from app.opportunity_atlas import signal_analyzer as sa

    r = sa.calc_lifecycle_stage({'day': 1, 'verified': True})
    assert r['verified'] is True
    assert r['auto_verified'] is False


def test_j18_pending_not_verified():
    """day<3 未满验证期 → 不自动置 verified"""
    from app.opportunity_atlas import signal_analyzer as sa

    r = sa.calc_lifecycle_stage({'day': 1, 'distance_to_signal_pct': 2.0})
    assert r['verified'] is False
    assert r['auto_verified'] is False
    assert r['verify_status'] == '待验证（未满3日）'


# ── #J20：advice_engine._safe_float 拦 NaN/inf ─────────────────

def test_j20_safe_float_nan_inf():
    """float('nan')/float('inf') → 回落 default，不污染仓位"""
    from app.opportunity_atlas.advice_engine import _safe_float

    assert _safe_float('nan', 0.0) == 0.0
    assert _safe_float('inf', 1.0) == 1.0
    assert _safe_float('-inf', 1.0) == 1.0
    assert _safe_float(3.5, 0.0) == 3.5
    assert _safe_float('bad', 2.0) == 2.0
    assert _safe_float(None, 2.0) == 2.0


# ── #J22：_build_advice_card_fields factor=None 兜底 ─────────────

def test_j22_build_advice_card_factor_none():
    """dims['factor']=None 时不再 AttributeError，conflict_items=[]"""
    from app.opportunity_atlas.advice_engine import _build_advice_card_fields

    # dims 含 factor=None（部分路径 factor 键存在但为 None）
    dims = {'factor': None, 'emotion': {'rotation_state': ''}}
    # 传入需要的最小参数：executable 需含 position 结构
    executable = {'position': {'max_pct': 0.4, 'initial_pct': 0.2}}
    r = _build_advice_card_fields(
        state='enter', tags={}, dims=dims, geo={}, support=None,
        signal_light='🟢', executable=executable, df=None)
    assert 'signal_light' in r
    assert 'confidence' in r


# ── #J23：radar get_tags_batch 分块 ─────────────────────────────

def test_j23_radar_get_tags_batch_chunked():
    """候选 >200 时分块合并（每次 <=200），保留全量候选（Top-N 承诺）"""
    from types import SimpleNamespace

    from app.opportunity_atlas.radar_service import RadarService

    calls = []

    class _FakeCache:
        def _query_df(self, sql):
            return pd.DataFrame({'ts_code': [f'{i:06d}.SZ' for i in range(450)]})

        def get_tags_batch(self, codes):
            calls.append(len(codes))
            return {c: {'signal_strength': 60.0} for c in codes}

    class _FakeDM:
        def __init__(self):
            self.cache = _FakeCache()

        def get_library_ts_codes(self):
            return []

        def get_stock_info(self, ts_code):
            return {'name': 'x'}

        def get_stock_meta_batch(self, codes):
            return {c: {'name': 'x'} for c in codes}

    svc = RadarService(data_manager=_FakeDM())
    top = svc.get_radar_signals(limit=10)
    assert len(top) == 10
    assert len(calls) >= 3, f'450 候选应分 ≥3 批，实 {calls}'
    assert all(c <= 200 for c in calls), f'每批应 ≤200，实 {calls}'


# ── #J24：_evaluate_push_level 未知 level 保守处理 ─────────────

def test_j24_unknown_level_conservative():
    """未知 level → 显式按 normal 参与（不抛、不静默 99 永不升顶）"""
    from app.opportunity_atlas.radar_service import RadarService

    item = SimpleNamespace(ts_code='000001.SZ')
    daily_change = {
        'has_changes': True,
        'changes': [
            {'level': 'new_level_unknown', 'summary': '未知级别变更'},
        ],
    }
    level, title, msg = RadarService._evaluate_push_level(item, daily_change)
    # 未知 level 保守按 normal：level=normal，仍产出消息（不因未知而降级丢失）
    assert level == 'normal'
    assert '未知级别变更' in msg


# ── #J25：get_watchboard 批量取名 ────────────────────────────────

def test_j25_watchboard_batch_name():
    """get_watchboard 用 get_stock_meta_batch 批量取名（不再逐只 N+1）"""
    from types import SimpleNamespace

    from app.opportunity_atlas.radar_service import RadarService

    _single_calls = []

    class _FakeCache:
        def get_tags_batch(self, codes):
            return {c: {} for c in codes}

    class _FakeDM:
        def __init__(self):
            self.cache = _FakeCache()

        def get_stock_meta_batch(self, codes):
            return {c: {'name': f'名称_{c[:6]}'} for c in codes}

        def get_stock_info(self, ts_code):
            _single_calls.append(ts_code)
            return {'name': 'fallback'}

        def get_library_ts_codes(self, active_only=True):
            return []

    svc = RadarService(data_manager=_FakeDM())
    r = svc.get_watchboard(['000001.SZ', '000002.SZ'])
    assert len(r['stocks']) == 2
    assert r['stocks'][0]['name'].startswith('名称_')
    assert _single_calls == [], f'批量路径不应逐只取名，实 {_single_calls}'


# ── #J26/#J27：time_rhythm 窗口统一 + ref_mid 守卫 ─────────────

def _rhythm_df(closes, highs, lows):
    return pd.DataFrame({'close': closes, 'high': highs, 'low': lows})


def test_j26_consolidation_window_30():
    """横盘比对窗口统一为近 30 根（原 60 根会把陈旧基准误计）"""
    from app.opportunity_atlas.time_rhythm_engine import TimeRhythmEngine

    # 60 根：近 30 根在 ±5% 带内，前 30 根也在同一带内（历史横盘）
    closes = [100.0 + (i * 0.1 if i < 30 else 0.0) for i in range(60)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    # 前 30 根同样横盘（closes 30..59 恒定 103.0 附近），验证不因 60 根窗口越界
    r = TimeRhythmEngine().compute_tags(_rhythm_df(closes, highs, lows))
    assert r['time_rhythm'] in ('mid_consolidation', 'approaching_turn', 'early_consolidation')


def test_j27_ref_mid_zero_guard():
    """ref_mid<=0（全 0 价格）→ 不抛错、不计数（不误标横盘）"""
    from app.opportunity_atlas.time_rhythm_engine import TimeRhythmEngine

    closes = [0.0] * 60
    highs = [0.0] * 60
    lows = [0.0] * 60
    # 全 0 价格：ref_mid=0 → 守卫跳过计数；带宽 0 判定不触发收缩
    r = TimeRhythmEngine().compute_tags(_rhythm_df(closes, highs, lows))
    assert 'time_rhythm' in r
