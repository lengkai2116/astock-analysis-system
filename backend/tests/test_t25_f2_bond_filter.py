"""T25-F2 回归测试：债券误采修复

背景：_get_a_share_codes 用 c[0] in ('0','2','3','6') 过滤，'2' 开头误收
12085 条债券/逆回购（23=沪债/24=深债/20=逆回购）→ 81% 快照为垃圾数据。
修复后仅保留真实 A 股代码。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

import pytest

# 模拟 mootdx stocks() 返回的 code 集合（含债券/基金干扰项）
MOCK_CODES = [
    '000001', '000002',          # 深市A股 ✅
    '300750', '301236',          # 创业板 ✅
    '600519', '601318', '603288', '605499', '688981',  # 沪市A股+科创 ✅
    '230001', '230692', '234520',  # 沪市债券 ❌
    '240001', '245001',          # 深市债券 ❌
    '204001', '205001',          # 逆回购 ❌
    '110001', '113001',          # 沪市可转债/基金 ❌
    '510300', '159915',          # 基金 ❌
    '830001', '831001',          # 北交所 ❌
    '730001',                    # 新股申购 ❌
]


@pytest.fixture(scope='module')
def module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'mootdx_test', os.path.join(os.path.dirname(__file__), '..', 'app', 'data', 'mootdx_collector.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_get_a_share_codes_filters_bonds(module, monkeypatch):
    """回退路径（app.db 不可用）：应排除债券/基金/逆回购/北交所，仅保留真实 A 股"""
    monkeypatch.setattr(module, '_refresh_stock_name_map', lambda: {c: f'名称{c}' for c in MOCK_CODES})
    # 模拟 app.db 不可用 → 走 mootdx 回退路径
    import os
    monkeypatch.setattr(os.path, 'exists', lambda p: False)
    codes = module._get_a_share_codes()
    expected = {'000001', '000002', '300750', '301236', '600519', '601318', '603288', '605499', '688981'}
    assert set(codes) == expected, f"应仅保留 A 股: {sorted(codes)}"
    # 明确不含债券
    assert '230692' not in codes, "不应含沪市债券"
    assert '204001' not in codes, "不应含逆回购"
    assert '510300' not in codes, "不应含基金"
    assert '830001' not in codes, "不应含北交所"


def test_get_a_share_codes_from_app_db(module):
    """首选路径：应从 app.db stocks 表读取全市场（含创业板/科创板，无债券）"""
    import os
    # mootdx_collector.py → data → app → backend → 项目根
    project = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(module.__file__)))))
    db = os.path.join(project, 'data', 'app.db')
    assert os.path.exists(db), f"app.db 应存在: {db}"
    codes = module._get_a_share_codes()
    assert len(codes) > 4000, f"_get_a_share_codes 应从 stocks 读取全市场: {len(codes)}"
    # 含创业板/科创板
    assert any(c.startswith('300') for c in codes), "应含创业板(300)"
    assert any(c.startswith('688') for c in codes), "应含科创板(688)"
    # 无债券
    assert not any(c.startswith('23') for c in codes), "不应含沪市债券(23)"
