"""T6.7 回归测试：七维画像事件维度三态红绿灯（L3）

根因：data_daemon.py:2010-2012 —— 只要有事件（含负面 fraud_sign）就 🟡，
无法区分正负向。修复后按 307号§3.1.9 三态：正向🟢/负向🔴/无⚪。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import importlib.util
import pytest

_MODULE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data_daemon.py')


@pytest.fixture(scope='module')
def dd():
    spec = importlib.util.spec_from_file_location('dd_t67', _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _base_tags() -> dict:
    return {
        'fina_health': 'pass', 'main_force_phase': 'building',
        'valuation_level': 'low', 'fund_flow': '5d_inflow',
        'sentiment_phase': 'recovery', 'volume_price_fit': 'healthy',
        'catalyst_event': 'none',
    }


def test_negative_event_red_light(dd):
    """负面事件（fraud_sign）应显示 🔴 负向"""
    tags = _base_tags()
    tags['catalyst_event'] = 'fraud_sign'
    profile = dd._build_opportunity_profile(tags)['opportunity_profile']
    assert profile['event']['light'] == '🔴', f"负面事件应🔴: {profile['event']}"
    assert '负' in profile['event']['status']


def test_positive_event_green_light(dd):
    """正向事件（earnings/breakout）应显示 🟢 正向"""
    for ev in ('earnings', 'breakout', 'buyback', 'concept'):
        tags = _base_tags()
        tags['catalyst_event'] = ev
        profile = dd._build_opportunity_profile(tags)['opportunity_profile']
        assert profile['event']['light'] == '🟢', f"正向事件 {ev} 应🟢: {profile['event']}"


def test_no_event_neutral(dd):
    """无事件应显示 ⚪"""
    tags = _base_tags()
    profile = dd._build_opportunity_profile(tags)['opportunity_profile']
    assert profile['event']['light'] == '⚪', f"无事件应⚪: {profile['event']}"
