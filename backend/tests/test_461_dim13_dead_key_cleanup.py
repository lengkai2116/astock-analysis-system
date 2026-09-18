"""461-13：算而不出字段清理回归测试（460 §五 P8 / 阶段2-2-3）

实证：以下字段在 app 运行时层（app/ 目录，逐字段 tags.get 检索）零消费者，
属"算而出"死字段，白耗 daemon CPU（bociasi_signal 还每次 RAW-2 额外拉一次 HS300）。

已排除非死字段（保留）：
- vol_ma5/10/20 —— volume_price_strategy:2498-2509 消费
- volatility_level —— dim6 判定消费（461-4 后）
- sector_heat/sector_rank —— 众多引擎消费
- style_exposure —— 317号/雷达/treemap 消费
- catalyst_event/event_composite_score/event_details/event_risk_factors —— dim6/status_engine 消费
- net_lg_5d/net_lg_5d_positive_ratio —— dim4:515-524 消费

本测试断言死键自 data_daemon 预计算产出路径彻底移除。
"""
import inspect
import data_daemon

_MOD = inspect.getsource(data_daemon)


class TestDeadKeyRemoval:
    def test_sentiment_no_bociasi_signal(self):
        """sentiment 组不再产出 bociasi_signal（死键；唯一"消费方"UPFEngine 未接线）"""
        assert "_sent['bociasi_signal']" not in _MOD
        assert "'bociasi_signal'" not in _MOD

    def test_sector_no_extra_dead_keys(self):
        """sector 组不再产出 sector_momentum/is_sector_leader（死键）"""
        assert "'sector_momentum':" not in _MOD
        assert "'is_sector_leader':" not in _MOD

    def test_sector_heat_rank_kept(self):
        """sector 组保留有消费者键 sector_heat/sector_rank"""
        assert "'sector_heat':" in _MOD
        assert "'sector_rank':" in _MOD

    def test_style_no_size_factor(self):
        """style 组不再产出 size_factor（死键；461-3 口径 bug 随删一并消失）"""
        assert "'size_factor':" not in _MOD
        assert "['size_factor']" not in _MOD

    def test_event_no_catalyst_impact(self):
        """event 组不再产出 catalyst_impact（死键）"""
        assert "'catalyst_impact':" not in _MOD

    def test_event_consumed_keys_kept(self):
        """event 组保留有消费者键（dim6/status_engine 消费）"""
        assert "'event_details'" in _MOD
        assert "'event_risk_factors'" in _MOD
        assert "'catalyst_event':" in _MOD

    def test_volume_price_no_gap_breakout(self):
        """volume_price 组不再产 gap_type/breakout_attempts（死键；_add_vp_simple_tags 内死算亦删）"""
        assert "'gap_type':" not in _MOD
        assert "['breakout_attempts']" not in _MOD
        assert "'breakout_attempts':" not in _MOD

    def test_fund5d_no_consecutive(self):
        """fund_5d 组不再产出 net_lg_5d_consecutive（死键）"""
        assert "['net_lg_5d_consecutive']" not in _MOD
        assert "'net_lg_5d_consecutive':" not in _MOD

    def test_fund5d_consumed_keys_kept(self):
        """fund_5d 组保留有消费者键 net_lg_5d/net_lg_5d_positive_ratio"""
        assert "_fund_5d_feat['net_lg_5d']" in _MOD
        assert "net_lg_5d_positive_ratio" in _MOD

    def test_volume_ext_no_volatility_roc(self):
        """volume_ext 组不再产出 volatility_20d/roc_20（死键）"""
        assert "_vol_feat['volatility_20d']" not in _MOD
        assert "_vol_feat['roc_20']" not in _MOD

    def test_volume_ext_keeps_vol_ma(self):
        """volume_ext 保留 vol_ma5/10/20（volume_price_strategy:2498-2509 消费）"""
        assert "vol_ma5" in _MOD
        assert "vol_ma10" in _MOD
        assert "vol_ma20" in _MOD
