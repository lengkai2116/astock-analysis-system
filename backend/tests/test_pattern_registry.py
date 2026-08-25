"""
测试 pattern registry 注册
验证 50 种 Wiki 形态 + 8 种状态元数据已正确注册
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pytest
from app.engine.patterns import PatternCategory
from app.engine.patterns.registry import PatternRegistry, PatternMeta


@pytest.fixture(scope='module')
def registry():
    """获取全局注册表单例"""
    reg = PatternRegistry()
    return reg


class TestWikiPatternRegistration:
    """验证 Wiki 50 种形态 + 8 种状态注册"""

    def test_total_wiki_patterns_and_states(self, registry):
        """应注册 50 种形态 + 8 种状态 = 58 种"""
        wiki_count = 0
        for meta in registry.list_all():
            if meta.source == "wiki_volume_price":
                wiki_count += 1
        assert wiki_count == 58, f"Wiki 形态+状态应为 58 种，实际: {wiki_count}"

    def test_bullish_patterns_count_20(self, registry):
        """预涨型应有 20 种"""
        bullish = registry.list_by_category(PatternCategory.BULLISH_PATTERNS)
        assert len(bullish) == 20, f"预涨型应为 20 种，实际: {len(bullish)}"

    def test_bearish_patterns_count_20(self, registry):
        """预跌型应有 20 种"""
        bearish = registry.list_by_category(PatternCategory.BEARISH_PATTERNS)
        assert len(bearish) == 20, f"预跌型应为 20 种，实际: {len(bearish)}"

    def test_blackhorse_patterns_count_10(self, registry):
        """黑马型应有 10 种"""
        blackhorse = registry.list_by_category(PatternCategory.BLACKHORSE)
        assert len(blackhorse) == 10, f"黑马型应为 10 种，实际: {len(blackhorse)}"

    def test_state_count_8(self, registry):
        """四类八种状态应有 8 种"""
        states = registry.list_by_category(PatternCategory.STATE)
        assert len(states) == 8, f"状态应为 8 种，实际: {len(states)}"

    def test_bullish_pattern_codes(self, registry):
        """验证预涨型代码 P-1-1 到 P-1-20"""
        bullish = registry.list_by_category(PatternCategory.BULLISH_PATTERNS)
        codes = sorted([m.name for m in bullish], key=lambda x: int(x.split('-')[-1]))
        expected = [f"P-1-{i}" for i in range(1, 21)]
        assert codes == expected, f"预涨型代码不匹配: {codes}"

    def test_bearish_pattern_codes(self, registry):
        """验证预跌型代码 P-2-1 到 P-2-20"""
        bearish = registry.list_by_category(PatternCategory.BEARISH_PATTERNS)
        codes = sorted([m.name for m in bearish], key=lambda x: int(x.split('-')[-1]))
        expected = [f"P-2-{i}" for i in range(1, 21)]
        assert codes == expected, f"预跌型代码不匹配: {codes}"

    def test_blackhorse_pattern_codes(self, registry):
        """验证黑马型代码 P-3-1 到 P-3-10"""
        blackhorse = registry.list_by_category(PatternCategory.BLACKHORSE)
        codes = sorted([m.name for m in blackhorse], key=lambda x: int(x.split('-')[-1]))
        expected = [f"P-3-{i}" for i in range(1, 11)]
        assert codes == expected, f"黑马型代码不匹配: {codes}"

    def test_state_codes(self, registry):
        """验证状态代码 S-1 到 S-8"""
        states = registry.list_by_category(PatternCategory.STATE)
        codes = sorted([m.name for m in states])
        expected = [f"S-{i}" for i in range(1, 9)]
        assert codes == expected, f"状态代码不匹配: {codes}"

    def test_bullish_directions(self, registry):
        """预涨型方向应全为 bullish"""
        for m in registry.list_by_category(PatternCategory.BULLISH_PATTERNS):
            assert m.direction == 'bullish', f"{m.name} 方向应为 bullish，实际: {m.direction}"

    def test_bearish_directions(self, registry):
        """预跌型方向应全为 bearish"""
        for m in registry.list_by_category(PatternCategory.BEARISH_PATTERNS):
            assert m.direction == 'bearish', f"{m.name} 方向应为 bearish，实际: {m.direction}"

    def test_pattern_meta_to_dict(self, registry):
        """验证 PatternMeta.to_dict() 方法正常工作"""
        meta = registry.get("P-1-1")
        assert meta is not None, "P-1-1 应存在"
        d = meta.to_dict()
        assert d['name'] == 'P-1-1'
        assert d['category'] == 'bullish_patterns'
        assert d['direction'] == 'bullish'
        assert len(d['description']) > 0
        assert '预涨型' in d['tags']

    def test_state_meta_structure(self, registry):
        """验证状态元数据结构完整"""
        for code in [f"S-{i}" for i in range(1, 9)]:
            meta = registry.get(code)
            assert meta is not None, f"{code} 应存在"
            assert meta.category == PatternCategory.STATE
            assert meta.direction in ('bullish', 'bearish'), f"{code} 方向无效: {meta.direction}"
            assert len(meta.description) > 0
            assert '四类八种状态' in meta.tags

    def test_all_new_patterns_have_description(self, registry):
        """所有新增形态都应有描述"""
        all_patterns = registry.list_all()
        wiki_patterns = [m for m in all_patterns if m.source == "wiki_volume_price"]
        for m in wiki_patterns:
            assert len(m.description) > 0, f"{m.name} 缺少描述"

    def test_all_new_patterns_have_tags(self, registry):
        """所有新增形态都应有标签"""
        all_patterns = registry.list_all()
        wiki_patterns = [m for m in all_patterns if m.source == "wiki_volume_price"]
        for m in wiki_patterns:
            assert len(m.tags) >= 2, f"{m.name} 标签不足: {m.tags}"


class TestDetectorBaseClass:
    """验证检测器基类可导入"""

    def test_import_pattern_detector(self):
        """应能导入 PatternDetector 基类"""
        from app.engine.patterns.detectors.base import PatternDetector
        assert PatternDetector is not None

    def test_pattern_detector_is_abstract(self):
        """PatternDetector 应为抽象类，不能直接实例化"""
        from app.engine.patterns.detectors.base import PatternDetector
        with pytest.raises(TypeError):
            PatternDetector()
