"""443号R2测试：dim4 evaluate 补传 cost_ext（_dim_ssrp 洗盘增强）

背景：evaluate 调 PhaseDetectionEngine.compute_tags 时未传 cost_ext（main_force_cost/
  margin_cost_price），该数据此前仅批量 identify_phase 路径消费。R2 将 cost_ext
  透传到 _dim_ssrp 维度，现价距主力成本 5% 内 → 洗盘投票增强（对齐 identify_phase dim4:3541-3544）。
"""
import inspect

import pandas as pd

from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import PhaseDetectionEngine


def _mk_close(close: float) -> pd.DataFrame:
    return pd.DataFrame({'close': [close * 0.9, close * 0.95, close]})


class TestDimSsrpCostExt:
    """_dim_ssrp 的 cost_ext 主力成本近距增强"""

    def test_near_cost_returns_washing_boost(self):
        """现价距 main_force_cost 5% 内 → 返回洗盘增强（washing 0.5）"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 9.0}  # 无 cost_ext 时 rel=1.11 → 原逻辑返回 {}
        cost_ext = {'main_force_cost': 10.2, 'margin_cost_price': None}
        result = pde._dim_ssrp(df, tags, cost_ext=cost_ext)
        assert result.get('washing', 0) >= 0.5, f"近距应返回洗盘增强, 实际: {result}"

    def test_far_cost_keeps_original_rules(self):
        """主力成本远离现价（>5%）→ 走原 rel 规则，不触发增强"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 9.0}
        cost_ext = {'main_force_cost': 20.0}  # 距离 50%
        result = pde._dim_ssrp(df, tags, cost_ext=cost_ext)
        assert result == {}, f"远距不应触发增强, 实际: {result}"

    def test_no_cost_ext_unchanged(self):
        """cost_ext 缺失 → 行为与原逻辑一致"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        tags = {'ssrp': 9.0}
        result = pde._dim_ssrp(df, tags)
        assert result == {}, f"无 cost_ext 应返回原结果, 实际: {result}"

    def test_near_cost_but_no_ssrp_returns_empty(self):
        """ssrp 缺失时即使近距也不投票"""
        pde = PhaseDetectionEngine()
        df = _mk_close(10.0)
        cost_ext = {'main_force_cost': 10.2}
        assert pde._dim_ssrp(df, {}, cost_ext=cost_ext) == {}


class TestComputeTagsSignature:
    """compute_tags 应接受 cost_ext 并透传 _dim_ssrp"""

    def test_compute_tags_accepts_cost_ext(self):
        sig = inspect.signature(PhaseDetectionEngine.compute_tags)
        assert 'cost_ext' in sig.parameters

    def test_compute_tags_passes_cost_ext_to_dim_ssrp(self):
        src = inspect.getsource(PhaseDetectionEngine.compute_tags)
        assert 'cost_ext=cost_ext' in src


class TestEvaluateDataFlow:
    """dim4 evaluate 应从 data_context 读取 cost_ext 并传入 compute_tags"""

    def test_evaluate_reads_and_passes_cost_ext(self):
        from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import Dim4ChipFundEngine
        src = inspect.getsource(Dim4ChipFundEngine.evaluate)
        assert "data_context.get('cost_ext')" in src
        assert 'cost_ext=cost_ext_val' in src
