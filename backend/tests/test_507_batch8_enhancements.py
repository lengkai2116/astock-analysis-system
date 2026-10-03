"""507号批次8：行为增强登记项处置验证

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §十九 收官剩余登记。

覆盖（拍板＝全取推荐项）：
  event_monitor._detect_concept_heat 全市场概念计数按日缓存（消除逐股全表 value_counts）
  potential_engine earn 权重 clamp 提为命名常量（EARN_WEIGHT_MIN/MAX）+ :350 注释
  light_derive.summary_light 拦 NaN/inf（→DATA_MISSING；原 NaN→yellow、inf→green）
  dim1 补采通知日志 f-string → %s 惰性
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

_ATLAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'opportunity_atlas')


# ── event_monitor 概念计数缓存 ─────────────────────────────

def test_event_concept_counts_cached():
    """_get_concept_counts 按日缓存：重复调用不重取全表"""
    from app.opportunity_atlas.event_monitor import EventMonitor

    em = EventMonitor()
    calls = {'n': 0}

    class _FakeCache:
        def get_cached_concept(self):
            calls['n'] += 1
            return pd.DataFrame({'concept_name': ['白酒', '白酒', '半导体']})

    # 同一天两次调用 → 仅一次全表
    c1 = em._get_concept_counts(_FakeCache())
    c2 = em._get_concept_counts(_FakeCache())
    assert calls['n'] == 1, f'应命中缓存: {calls["n"]}'
    assert c1['白酒'] == 2 and c2 is c1


def test_event_concept_counts_none_cached():
    """全表空 → 缓存 None，不抛异常"""
    from app.opportunity_atlas.event_monitor import EventMonitor

    em = EventMonitor()

    class _FakeCache:
        def get_cached_concept(self):
            return pd.DataFrame()

    assert em._get_concept_counts(_FakeCache()) is None


# ── potential_engine 常量提纯 ──────────────────────────────

def test_potential_earn_weight_constants():
    """EARN_WEIGHT_MIN/MAX 命名常量；clamp 处不再硬编码 0.35/0.15"""
    import importlib
    m = importlib.import_module('app.opportunity_atlas.potential_engine')
    assert m.EARN_WEIGHT_MIN == 0.15
    assert m.EARN_WEIGHT_MAX == 0.35
    src = open(m.__file__, encoding='utf-8').read()
    # clamp 处（注释示例除外）应引用常量
    assert 'min(EARN_WEIGHT_MAX, max(EARN_WEIGHT_MIN, w_e))' in src
    assert 'min(EARN_WEIGHT_MAX, max(base' in src


# ── light_derive NaN/inf 拦截 ──────────────────────────────

@pytest.mark.parametrize('v', [float('nan'), float('inf'), float('-inf')])
def test_summary_light_nan_inf_to_missing(v):
    from app.opportunity_atlas.light_derive import DATA_MISSING, summary_light
    assert summary_light(v) == DATA_MISSING, f'{v} 应判缺失灯'


@pytest.mark.parametrize('v,expected', [(0.8, 'green'), (0.2, 'red'), (0.5, 'yellow'),
                                        (None, 'yellow'), ('abc', 'yellow')])
def test_summary_light_normal(v, expected):
    from app.opportunity_atlas.light_derive import summary_light
    assert summary_light(v) == expected


# ── dim1 补采日志惰性 ──────────────────────────────────────

def test_dim1_notify_logs_lazy():
    """dim1 补采通知日志已改 %s 惰性（无 f-string）"""
    src = open(os.path.join(_ATLAS, 'dimensions', 'dim1_signal_engine.py'),
               encoding='utf-8').read()
    assert 'logger.info(f"dim1通知daemon补采' not in src
    assert 'logger.info("dim1通知daemon补采: %s %s", task_type, ts_code)' in src
    assert 'logger.warning(f' not in src and 'logger.debug(f' not in src
