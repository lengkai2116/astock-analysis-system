"""547号：北交所实时快照代码池与前缀映射。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
    os.environ.pop(_k, None)

from app.data.mootdx_collector import (  # noqa: E402
    _get_bj_codes,
    _market_prefix,
    _ts_code_from_prefix,
)


def test_market_prefix_for_bj_before_sh():
    assert _market_prefix('920196') == 'bj'
    assert _market_prefix('430047') == 'bj'
    assert _market_prefix('830799') == 'bj'
    assert _market_prefix('600519') == 'sh'
    assert _market_prefix('000001') == 'sz'
    assert _market_prefix('300750') == 'sz'


def test_ts_code_suffix():
    assert _ts_code_from_prefix('920196', 'bj') == '920196.BJ'
    assert _ts_code_from_prefix('600519', 'sh') == '600519.SH'
    assert _ts_code_from_prefix('000001', 'sz') == '000001.SZ'


def test_bj_code_pool():
    codes = _get_bj_codes()
    assert len(codes) >= 300
    assert any(c.startswith('92') for c in codes)
    assert all(len(c) == 6 for c in codes)
