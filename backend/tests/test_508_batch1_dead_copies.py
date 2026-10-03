"""508号批次1：死副本删除验证（MainForceScorer dim4 内嵌 + framework CrowdingFactor）

方案档：`002-方案存档/508-dim4双副本收敛（物理合入清理）.md` §〇 批次1。

覆盖：
  - dim4 内嵌 MainForceScorer（~789 行）已删（daemon/tests 均用 framework 版）
  - framework/crowding_factor.py 死副本已删（无生产/测试引用）
  - dim4 内嵌 CrowdingFactor 保留（LIVE，Dim4ChipFundEngine 用）
  - framework/chip_strategy.py 版 MainForceScorer 不受影响（daemon 消费）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_dim4_main_force_scorer_dead_copy_removed():
    """dim4 内嵌 MainForceScorer 已删（framework 权威）"""
    import importlib
    m = importlib.import_module('app.opportunity_atlas.dimensions.dim4_chip_fund_engine')
    assert not hasattr(m, 'MainForceScorer'), 'dim4 MainForceScorer 死副本应已删'


def test_framework_crowding_factor_file_removed():
    """framework/crowding_factor.py 死副本已删（无生产/测试引用）"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'engine', 'framework', 'crowding_factor.py')
    assert not os.path.exists(path), 'framework crowding_factor.py 应已删'


def test_dim4_crowding_factor_kept_live():
    """dim4 内嵌 CrowdingFactor 保留（Dim4ChipFundEngine evaluate 用）"""
    import importlib
    m = importlib.import_module('app.opportunity_atlas.dimensions.dim4_chip_fund_engine')
    assert hasattr(m, 'CrowdingFactor'), 'dim4 CrowdingFactor 应保留（LIVE）'
    assert hasattr(m, 'Dim4ChipFundEngine'), 'Dim4ChipFundEngine 应保留'


def test_framework_main_force_scorer_unaffected():
    """framework/chip_strategy.py 版 MainForceScorer 正常（daemon 消费）"""
    from app.engine.framework.chip_strategy import MainForceScorer
    s = MainForceScorer()
    assert hasattr(s, 'get_tags') or hasattr(s, 'get_score'), 'framework 版应可实例化'


def test_dim4_module_line_count_shrunk():
    """dim4 文件缩减（3417 → <2700 行，MainForceScorer -789 行）"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'opportunity_atlas', 'dimensions',
                        'dim4_chip_fund_engine.py')
    n = sum(1 for _ in open(path, encoding='utf-8'))
    assert n < 2700, f'dim4 仍 {n} 行，MainForceScorer 未删净'
