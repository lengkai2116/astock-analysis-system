"""564 号回归：v390 配置生效性三项（A1 climax 档 / B2 死配置边界 / C1 monthly_halt 落库标记）

覆盖：
  - A1：status_engine.yaml `l0.emotion_position_cap` 显式含 `climax`，且与 normal 同档（0.60）
  - B2：v390 状态映射阈值为 factor_arbiter._THRESHOLDS（80/65/45/30），不读 yaml consensus
  - C1：`monthly_halt_db_flag` 把 False/None 落为 0（不再写 NULL）

纯配置/纯函数，不触库、不写盘。
"""
import pytest


def test_climax_emotion_position_cap_explicit():
    from app.services import status_config
    l0 = status_config.get_status_engine_config()['l0']
    caps = l0['emotion_position_cap']
    assert 'climax' in caps
    assert caps['climax'] == pytest.approx(0.60)
    # 与引擎的情绪阶段归一化键对齐（高潮 -> climax）
    from app.opportunity_atlas.status_engine import _normalize_emotion_phase
    tags = {'sentiment_phase': 'climax'}
    assert _normalize_emotion_phase(tags) == 'climax'
    assert caps[_normalize_emotion_phase(tags)] == pytest.approx(0.60)


def test_v390_thresholds_authoritative_not_yaml():
    from app.opportunity_atlas import factor_arbiter
    assert [(t, s) for t, s in factor_arbiter._THRESHOLDS] == [
        (80, 'enter'), (65, 'light'), (45, 'wait'), (30, 'reduce'),
    ]
    assert factor_arbiter._map_score_to_state(80.0) == 'enter'
    assert factor_arbiter._map_score_to_state(64.9) == 'wait'
    assert factor_arbiter._map_score_to_state(29.9) == 'avoid'


def test_monthly_halt_db_flag_false_is_zero():
    from app.services.account_risk_status import monthly_halt_db_flag
    assert monthly_halt_db_flag(True) == 1
    assert monthly_halt_db_flag(False) == 0
    assert monthly_halt_db_flag(None) == 0
