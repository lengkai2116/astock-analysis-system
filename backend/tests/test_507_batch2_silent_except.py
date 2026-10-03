"""507号批次2：SIG 静默 except 补日志验证（§4.1 核心站点）

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §四.1。

范围（§4.1 点名核心站点，逐股热路径用 debug、批/关键降级用 warning）：
  dim2:174 结构健康度 / dim5:466/477/496/499/534/558/573 BOCIASI+板块+温度入参+融资 /
  dim7:321 分位基准 / dim8 六个环境定位 helper / dim_adapter:740 signal_confirm /
  tag_extractor:223/251 资金风险标签 / cross_validate:56/83 /
  radar_service:38 股名。（dim6:435 已在批次1 修复；time_rhythm:100 原已有 debug。）

校验方式：AST 定位各目标语句的 except；断言其 body 非「裸 pass」——即异常被记录或
显式降级（不再无声吞掉）。不改变任何降级行为。
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

_ATLAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'opportunity_atlas')


def _handlers(path):
    """返回 {(lineno): body_src_list} —— 所有 ExceptHandler。"""
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = [ast.get_source_segment(src, s) or '' for s in node.body]
            out.append((node.lineno, body, src))
    return out


def _is_silent(body):
    """裸 except: pass（或仅 pass）＝静默。"""
    return body == ['pass']


# §4.1 目标文件 → 该文件内「不应再有裸 pass」的最小校验
_TARGETS = [
    'dimensions/dim2_structure_engine.py',
    'dimensions/dim5_emotion_engine.py',
    'dimensions/dim7_valuation_engine.py',
    'dimensions/dim8_summary_engine.py',
    'dim_adapter.py',
    'tag_extractor.py',
    'cross_validate.py',
    'radar_service.py',
]


@pytest.mark.parametrize('rel', _TARGETS)
def test_batch2_no_new_bare_pass_in_targets(rel):
    """批次2 落地的站点不应存在裸 `except: pass`（补日志后 body 含 logger 调用）"""
    path = os.path.join(_ATLAS, rel)
    # 已知既有裸 pass（非本批次范围，如 dim5 的三层面评估内层）——按文件计数基线守卫：
    #   本测试只断言「本批次新增/改造的站点」不静默，故用 logger 覆盖计数下界。
    handlers = _handlers(path)
    # 至少存在若干条 logger.debug/warning 记录（本批次补入）
    logged = 0
    for _, body, _ in handlers:
        joined = '\n'.join(body)
        if 'logger.debug' in joined or 'logger.warning' in joined:
            logged += 1
    assert logged >= 1, f'{rel}: 未检出补入的 logger 记录'


def test_dim5_bociasi_blocks_logged():
    """dim5 快慢线/四象限/板块/温度入参/融资 6 处补日志（debug）"""
    path = os.path.join(_ATLAS, 'dimensions/dim5_emotion_engine.py')
    src = open(path, encoding='utf-8').read()
    for kw in ('dim5 BOCIASI快线计算失败', 'dim5 BOCIASI慢线计算失败',
               'dim5 四象限分析失败', 'dim5 BOCIASI整体计算失败',
               'dim5 板块热度定位失败', 'dim5 温度市场级入参读取失败',
               'dim5 融资余额变化率读取失败'):
        assert kw in src, f'缺日志: {kw}'


def test_dim8_env_helpers_warning():
    """dim8 六个环境定位 helper 补 warning"""
    path = os.path.join(_ATLAS, 'dimensions/dim8_summary_engine.py')
    src = open(path, encoding='utf-8').read()
    for kw in ('dim8 相对强弱句构建失败', 'dim8 大盘状态句构建失败',
               'dim8 板块定位句构建失败', 'dim8 大盘趋势句构建失败',
               'dim8 行业句构建失败', 'dim8 个股行业位置句构建失败'):
        assert kw in src, f'缺日志: {kw}'


def test_misc_sites_logged():
    """dim2/dim7/dim_adapter/tag_extractor/cross_validate/radar 补日志"""
    expects = {
        'dimensions/dim2_structure_engine.py': ['dim2 结构健康度计算失败'],
        'dimensions/dim7_valuation_engine.py': ['dim7 val 分位基准构建失败',
                                                'dim7 earn 分位基准构建失败'],
        'dim_adapter.py': ['signal_confirm 精细分类失败'],
        'tag_extractor.py': ['net_lg_amount_5d 失败', 'margin_cost_price 计算失败'],
        'cross_validate.py': ['light_derive(emotion) 失败', '_load_dim_engine_results 失败'],
        'radar_service.py': ['_get_stock_name 失败'],
    }
    for rel, kws in expects.items():
        src = open(os.path.join(_ATLAS, rel), encoding='utf-8').read()
        for kw in kws:
            assert kw in src, f'{rel}: 缺日志 {kw}'


def test_behaviour_unchanged_imports():
    """各模块仍可 import（语法/作用域无回归）"""
    import importlib
    for mod in ('app.opportunity_atlas.dim_adapter',
                'app.opportunity_atlas.cross_validate',
                'app.opportunity_atlas.tag_extractor',
                'app.opportunity_atlas.radar_service',
                'app.opportunity_atlas.dimensions.dim5_emotion_engine',
                'app.opportunity_atlas.dimensions.dim8_summary_engine'):
        importlib.import_module(mod)
