"""553-D：TdxQuant 可行性探针决策逻辑测试"""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'scripts', '_553d_tdxquant_probe.py')
_spec = importlib.util.spec_from_file_location('tdx_probe_553d', _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_decide_client_first():
    assert _mod.decide({'ok': True}, {'package': False, 'ini': None}) == 'client'
    assert _mod.decide({'ok': True}, {'package': True, 'ini': '/x'}) == 'client'


def test_decide_tqserver():
    assert _mod.decide({'ok': False}, {'package': True, 'ini': '/x/TdxAiData.ini'}) == 'tqserver'


def test_decide_blocked():
    assert _mod.decide({'ok': False}, {'package': False, 'ini': None}) == 'blocked'
    assert _mod.decide({'ok': False}, {'package': True, 'ini': None}) == 'blocked'
    assert _mod.decide({'ok': False}, {'package': False, 'ini': '/x'}) == 'blocked'
