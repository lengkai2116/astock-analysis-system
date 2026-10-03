"""507号批次5：契约/签名/文档漂移验证（#S24~#S29）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §四.6。

覆盖 4 项落地（均无行为变更）：
  #S24 `_fina_health` docstring 3 元组 → 4 元组（实返含 roce_na）
  #S26 `arbiter` docstring P2「deep→avoid」→「强提示」（335号 S2.3 已改实现）
  #S27 `enum_cn_map.ma_alignment_cn` docstring 哨兵描述 → 回落原值
  #S29 `status_engine` yaml 缺 `emotion_position_cap` 时补默认 0.6（原下游 None）

非缺陷/登记：#S25 build_fcf_percentile 死方法（批次6）、#S28 split(':') 弱、
  #S30 advice_builder 死副本（生效版正确）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

_ATLAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'opportunity_atlas')


def test_s24_fina_health_returns_4_tuple():
    """_fina_health 实返 4 元组 (health, roce_pass, roce_na, df_fina)"""
    import inspect
    from app.opportunity_atlas.valuation_estimator import ValuationEngine

    src = inspect.getsource(ValuationEngine._fina_health)
    assert 'tuple[str, bool, bool, pd.DataFrame]' in src, '签名未含 roce_na'
    assert 'return health, roce_pass, roce_na, df_fina' in src, '返回非 4 元组'


def test_s26_arbiter_docstring_deep_hint():
    """arbiter docstring P2 由「→ avoid」改为「→ 强提示」"""
    src = open(os.path.join(_ATLAS, 'arbiter.py'), encoding='utf-8').read()
    assert 'P2 深度高估  gate.valuation=deep → 强提示' in src
    assert '_DEEP_HINT' in src


def test_s27_ma_alignment_docstring_not_sentinel():
    """ma_alignment_cn docstring 不再声称返回哨兵（回落原值）"""
    import inspect
    from app.opportunity_atlas.dimensions import enum_cn_map as m

    doc = inspect.getdoc(m.ma_alignment_cn)
    assert '回落原值' in (doc or ''), doc
    assert '未知名返回' not in (doc or ''), '仍写哨兵语义'
    # 行为不变：未知回落原值
    assert m.ma_alignment_cn('unknown_xyz') == 'unknown_xyz'


def test_s29_emotion_position_cap_default_when_no_caps():
    """yaml 缺 emotion_position_cap 时 l0 仍产默认 0.6（原下游 get() None）"""
    import inspect
    from app.opportunity_atlas.status_engine import StatusEngine

    src = inspect.getsource(StatusEngine._apply_l0)
    assert "l0['emotion_position_cap'] = 0.6" in src, '缺默认键补丁'
