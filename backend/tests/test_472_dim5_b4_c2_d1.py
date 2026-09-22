"""472号：dim5 残留核查处置（B4+C2+D1）单元测试

覆盖：
- B4：慢线 `_bociasi_slowline` 数据不足（len<60）标注为"个股 pe_ttm 序列<60日"，
      与"无数据"区分（次新语义）。
- C2：`PHASE_MAP` 补 `neutral` 键——daemon 数据不足产 sentiment_phase='neutral' 时
      不再落兜底"正常/数据不足"，而是映射到中性档（对齐温度 SSOT PHASE_BASE_TEMP neutral:50）。
- D1：`emotion_temperature` SSOT 的 breadth docstring 订正——标注上游用
      `market_stats.ma20_ratio` 近似，非严格"上涨家数占比"。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd


# ── B4：慢线数据不足标注 ────────────────────────────────────────

class TestSlowLineDataShort:

    def test_len_lt_60_marks_secondary_ipo(self):
        """len<60 → 标注'个股 pe_ttm 序列<60日'（次新），而非笼统'数据不足'"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        df = pd.DataFrame({'pe_ttm': [30.0] * 30})   # 仅 30 日
        res = mod._bociasi_slowline(df)
        assert res['signal'] == 'NEUTRAL'
        assert '数据不足（个股 pe_ttm 序列<60日）' in res['details'].get('error', '')

    def test_null_empty_also_marked(self):
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        assert mod._bociasi_slowline(None)['details']['error'].startswith('数据不足（')
        assert mod._bociasi_slowline(pd.DataFrame())['details']['error'].startswith('数据不足（')


# ── C2：PHASE_MAP neutral 键 ───────────────────────────────────

class TestPHaseMapNeutral:

    def test_neutral_in_phase_map(self):
        """PHASE_MAP 含 neutral 键（对齐温度 SSOT neutral:50），不再用兜底"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        assert 'neutral' in mod.PHASE_MAP
        name, desc, light = mod.PHASE_MAP['neutral']
        assert name in ('正常', '中性')
        assert light == 'yellow'

    def test_assess_market_neutral_uses_map(self):
        """sentiment_phase='neutral' → _assess_market_emotion 走 PHASE_MAP neutral，
        不再落兜底 '正常/情绪数据不足'"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        res = mod._assess_market_emotion({'sentiment_phase': 'neutral'}, {})
        # '数据不足，市场中性' 来自 PHASE_MAP neutral（不再是兜底 '情绪数据不足'）
        assert res['detail'] == '情绪数据不足，市场中性'
        assert res['phase'] == '正常'

    def test_phase_map_set_includes_neutral(self):
        """集合断言（447 更新版）：六段论 + neutral 键"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        assert set(mod.PHASE_MAP) == {'ice', 'sprout', 'ferment', 'climax', 'ebb',
                                      'regression', 'neutral'}
        assert 'recovery' not in mod.PHASE_MAP


# ── D1：温度 SSOT breadth docstring 订正 ───────────────────────

class TestBreadthDocstring:

    def test_ssot_breadth_docstring_notes_approximation(self):
        """emotion_temperature SSOT 的 breadth 说明明确标注 ma20_ratio 近似"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.emotion_temperature')
        src = open(mod.__file__).read()
        assert 'ma20_ratio' in src
        assert '上涨家数/总家数' in src

    def test_dim5_feeds_ma20_ratio_as_breadth(self):
        """dim5 evaluate 温度调用 breadth 用 market_stats.ma20_ratio（已知近似，D1 标注）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        src = open(mod.__file__).read()
        assert "ma20_ratio" in src

    def test_ssot_accepts_breadth_optional(self):
        """温度 SSOT breadth 仍为可选入参（None 时走中性 50 分）"""
        import importlib
        import inspect
        mod = importlib.import_module('app.opportunity_atlas.emotion_temperature')
        params = inspect.signature(mod.calc_emotion_temperature).parameters
        assert params['breadth'].default is None
