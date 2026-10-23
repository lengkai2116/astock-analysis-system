"""544-B：RAW-2 cost_ext 生产导入路径回归测试。

508 批次1 已把 MainForceScorer 收敛到 engine/framework/chip_strategy.py，
dim4_chip_fund_engine 不再导出。若 data_daemon 仍从 dim4 导入，RAW-2 的
成本段会 ImportError → 被 debug 吞掉 → cost_ext 恒为 {} → dim1 对全市场
每只判缺失并反复通知 precompute_raw（2026-10-23 实测 5,628 次/日）。
"""
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_framework_exports_main_force_scorer():
    mod = importlib.import_module('app.engine.framework.chip_strategy')
    scorer = mod.MainForceScorer()
    assert hasattr(scorer, '_calc_main_force_cost')
    assert hasattr(scorer, '_calc_margin_cost_price')


def test_dim4_no_longer_exports_main_force_scorer():
    mod = importlib.import_module('app.opportunity_atlas.dimensions.dim4_chip_fund_engine')
    assert not hasattr(mod, 'MainForceScorer')


def test_daemon_uses_framework_import():
    src = (ROOT / 'data_daemon.py').read_text(encoding='utf-8')
    assert 'from app.engine.framework.chip_strategy import MainForceScorer' in src
    assert 'from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import MainForceScorer' not in src
