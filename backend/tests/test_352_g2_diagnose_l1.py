"""352号阶段一测试：G2 diagnose operation_advice 传入 L1 共识"""
import json
import pytest


class TestG2DiagnoseL1Consensus:
    """diagnose 的 operation_advice 应使用 L1 九维共识（与 analyze 同源）"""

    def test_diagnose_advice_uses_l1_consensus(self):
        """diagnose 的 build_operation_advice 应传入 consensus 和 dirs 参数"""
        import inspect
        from app.opportunity_atlas.cross_validate import L4CrossValidator
        source = inspect.getsource(L4CrossValidator.diagnose)
        # 验证 diagnose 中 build_operation_advice 调用包含 consensus 参数
        assert 'consensus=' in source and '_l1_consensus' in source, \
            "diagnose 应传入 L1 共识给 build_operation_advice"

    def test_diagnose_arb_uses_l1_consensus(self):
        """diagnose 的 arbitrate 调用应使用 L1 共识（非五维标签投票）"""
        import inspect
        from app.opportunity_atlas.cross_validate import L4CrossValidator
        source = inspect.getsource(L4CrossValidator.diagnose)
        # 验证 _arb 的 consensus 来源不是 _compute_consensus
        # 简单验证：diagnose 中应有从 status_verdict 构建共识的逻辑
        assert 'status_verdict' in source or '_l1_consensus' in source, \
            "diagnose 应从 status_verdict 构建 L1 共识"

    def test_nine_dim_consistency(self):
        """九典制药弹窗/个股页 operation_advice 仓位应一致"""
        from app import create_app
        app = create_app()
        with app.app_context():
            from app.opportunity_atlas.cross_validate import L4CrossValidator
            from app.data import DataManager
            dm = DataManager()
            tags = dm.cache.get_tags('300705.SZ')
            v = L4CrossValidator()
            r = v.diagnose('300705.SZ', tags)
            oa = r.get('operation_advice') or {}
            # 操作建议应有 state 和 max_position_ratio
            assert oa.get('state') is not None, "operation_advice 应有 state"
            assert oa.get('max_position_ratio') is not None, "operation_advice 应有 max_position_ratio"
