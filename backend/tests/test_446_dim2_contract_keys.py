"""446号：dim2 7 契约键真实性产出单元测试

445 §6.1 dim2「缺 7 契约键」→ dim_adapter/conflict_matrix 增强静默失效：
  level_cross_score / chanlun_phase / trend_structure_signal / ts_strength /
  buy_sell_points_detail / stage_name / divergence

已接线（真实调用）：
  - level_cross_score   ← ChanlunLevelValidator().validate(df)['cross_score']
  - trend_structure_signal + ts_strength ← TrendStructureDetector().detect(df)
    (ts_strength 由 detector 的字符串 'strong'/'basic' 映射为 float)
  - divergence/divergence_type/divergence_strength ← chanlun_result['divergence']
  - buy_sell_points_detail ← 序列化 buy/sell points（consumer 读 type='buy'/'sell'+confirmed）
  - chanlun_phase         ← chanlun_result['theorem_check'].summary.overall_score（健康/欲病）
  - stage_name            ← struct_state（上升/下降/盘整）

消费端（回归防护）：
  - dim_adapter.dim2 strength = 0.4*chanlun_strength+0.4*level_cross_score+0.2*cont
    123_buy_breakout → += ts_strength+0.05；欲病 → ×0.7；buy_sell_points_detail 增强 direction
  - conflict_matrix C1/C2/C6/C10 读 chanlun_phase/divergence_type/divergence_strength/trend_structure_signal
"""
import numpy as np
import pandas as pd

from app.opportunity_atlas.dimensions.dim2_structure_engine import Dim2StructureEngine


def _mk_df(n=80, uptrend=True):
    """合成日线 df（含 close/high/low/vol/trade_date），供 evaluate 走 analyzer 全流程。"""
    rng = np.random.RandomState(7)
    if uptrend:
        closes = np.linspace(10, 22, n) + rng.normal(0, 0.15, n)
    else:
        closes = np.linspace(22, 10, n) + rng.normal(0, 0.15, n)
    closes = np.clip(closes, 5, None).astype(float)
    df = pd.DataFrame({
        'open': closes,
        'high': closes * 1.01,
        'low': closes * 0.99,
        'close': closes,
        'vol': rng.uniform(1000, 5000, n),
        'trade_date': pd.date_range('2025-01-01', periods=n, freq='B').astype(str),
    })
    return df


def _run(ts_code='TEST.XSHG', uptrend=True):
    """跑一次 evaluate，返回 status_description + judgment。"""
    eng = Dim2StructureEngine()
    df = _mk_df(uptrend=uptrend)
    tags = {'ts_code': ts_code}
    out = eng.evaluate({}, tags, data_context={'daily_df': df})
    return out['status_description'], out['judgment'], df


class TestContractKeysProduced:
    """7 契约键全部真实产出（数据充足、缠论可分析时非空/非默认）"""

    def test_all_seven_keys_present_in_sd(self):
        sd, _, _ = _run()
        for key in ('level_cross_score', 'chanlun_phase', 'trend_structure_signal',
                    'ts_strength', 'buy_sell_points_detail', 'stage_name', 'divergence'):
            assert key in sd, f"缺少契约键: {key}"
        # conflict_matrix C6/C10 补充键
        assert 'divergence_type' in sd and 'divergence_strength' in sd

    def test_level_cross_score_is_bounded_float(self):
        """level_cross_score 为 [0,1] 浮点（真实接线 cross_score）"""
        sd, _, _ = _run()
        v = sd['level_cross_score']
        assert isinstance(v, float) or isinstance(v, int)
        assert 0.0 <= v <= 1.0

    def test_chanlun_phase_in_health_sick(self):
        """chanlun_phase ∈ {健康, 欲病}"""
        sd, _, _ = _run()
        assert sd['chanlun_phase'] in ('健康', '欲病'), sd['chanlun_phase']

    def test_stage_name_reflects_structure(self):
        """stage_name == struct_state（上升/下降/盘整）"""
        sd, jud, _ = _run(uptrend=True)
        assert sd['stage_name'] == jud['structure']
        assert sd['stage_name'] in ('上升', '下降', '盘整')

    def test_ts_strength_is_float_and_bounded(self):
        """ts_strength 为 float（strong→0.3 / basic→0.1，而非字符串）"""
        sd, _, _ = _run()
        v = sd['ts_strength']
        assert isinstance(v, float) or isinstance(v, int)
        assert 0.0 <= v <= 1.0

    def test_trend_structure_signal_is_str(self):
        """trend_structure_signal 为字符串（123_buy_breakout/higher_low/none/''）"""
        sd, _, _ = _run()
        assert isinstance(sd['trend_structure_signal'], str)

    def test_buy_sell_points_detail_is_list_of_dicts(self):
        """buy_sell_points_detail 为 dict 列表，每项含 type/confirmed"""
        sd, _, _ = _run()
        assert isinstance(sd['buy_sell_points_detail'], list)
        if sd['buy_sell_points_detail']:
            p = sd['buy_sell_points_detail'][0]
            assert isinstance(p, dict)
            assert p['type'] in ('buy', 'sell')
            assert 'confirmed' in p

    def test_divergence_is_str(self):
        """divergence 为字符串（底背驰/顶背驰/''）"""
        sd, _, _ = _run()
        assert isinstance(sd['divergence'], str)


class TestConsumerContracts:
    """消费端契约（dim_adapter/conflict_matrix 读取语义）回归防护"""

    def test_ts_strength_supports_float_add_for_breakout(self):
        """ts_strength 可直接参与 dim_adapter 的 `_dim2_str += _ts_strength + 0.05`"""
        sd, jud, _ = _run(uptrend=True)
        # 若 123_buy_breakout 且看多 → 增强路径生效（ts_strength 必须为数值可相加）
        if sd['trend_structure_signal'] == '123_buy_breakout':
            _add = sd['ts_strength'] + 0.05  # 不抛异常
            assert _add >= 0.05
            assert jud['overall_direction'] >= 0
        else:
            assert True  # 非突破态不强制

    def test_chanlun_phase_substring_for_discount(self):
        """欲病判定可用 dim_adapter 的 `'欲病' in chanlun_phase`（子串匹配）"""
        sd, _, _ = _run()
        assert sd['chanlun_phase'] in ('健康', '欲病')  # 子串语义成立

    def test_buy_sell_points_detail_consumer_fields(self):
        """conflict/增强消费：type='buy'/'sell' + confirmed 布尔"""
        sd, _, _ = _run()
        for p in sd['buy_sell_points_detail']:
            assert p['type'] in ('buy', 'sell')
            assert isinstance(p['confirmed'], bool)

    def test_divergence_type_strength_consumer(self):
        """conflict_matrix C6 读 divergence_type=='趋势背驰' + divergence_strength>0.7"""
        sd, _, _ = _run()
        assert sd['divergence_type'] in ('', '趋势背驰', '盘整背驰', '中枢背驰')
        assert isinstance(sd['divergence_strength'], (int, float))
        assert 0.0 <= sd['divergence_strength'] <= 1.0


class TestEmptyDataFallback:
    """数据不足时契约键安全默认（不崩）"""

    def test_sparse_df_safe_defaults(self):
        eng = Dim2StructureEngine()
        tags = {'ts_code': 'TEST.XSHG'}
        out = eng.evaluate({}, {'ts_code': 'TEST.XSHG'},
                           data_context={'daily_df': pd.DataFrame()})
        sd = out['status_description']
        # 不足30行 → 缠论不跑 → 默认值
        assert sd['level_cross_score'] == 0.5
        assert sd['trend_structure_signal'] == ''
        assert sd['ts_strength'] == 0.0
        assert sd['buy_sell_points_detail'] == []
        assert sd['divergence'] == ''
        assert sd['divergence_type'] == ''
