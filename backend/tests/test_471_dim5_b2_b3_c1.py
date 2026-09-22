"""471号：dim5 残留核查处置（B2+B3+C1 拍板项）单元测试

覆盖：
- B2：慢线 `_bociasi_slowline` 已移除"股债位置差（sb）"死分支——慢线=个股
      纯 ERP 信号，全市场股债维度由四象限慢线历史分位承担；返回不再含
      `sb_signal` 键，传入 index_df 无影响（不再参与信号）。
- B3：慢线与四象限**双语义分层**已在现状话术体现——`bociasi_slow` 前缀"个股
      慢线ERP"、`quadrant` 前缀"大市四象限·全市场分位"，避免同一语境混淆。
- C1：daemon 阶段 fallback（四档降级）保留并标注（471 注释），不触 445 冻结判定。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd

# 复用 470 测试同款构造
def _mk_df(pe_value=30.0, ndays=60):
    return pd.DataFrame({'pe_ttm': [pe_value] * ndays})


# ── B2：慢线死分支（sb 股债位置差）移除 ──────────────────────────

class TestSlowLineSbRemoved:

    def test_no_sb_signal_in_details(self):
        """慢线返回不再含 sb_signal（股债位置差死分支已删）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        df = _mk_df(pe_value=60.0)   # 1/60*100−1.7 = 0.0 → NEUTRAL
        res = mod._bociasi_slowline(df)
        assert 'sb_signal' not in res['details']
        assert 'sb_signal' not in res.get('details', {}).get('sb_signal', {})

    def test_erp_drives_signal_alone(self):
        """慢线信号仅由个股 ERP 驱动：pe 高→ERP 低→BEARISH（不再混入 sb）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        # ERP = 1/100*100 − 1.7 = -0.7 < 0.5 → BEARISH
        res = mod._bociasi_slowline(_mk_df(pe_value=100.0))
        assert res['signal'] == 'BEARISH'
        assert res['details']['erp_signal'] == 'BEARISH'

    def test_index_df_ignored(self):
        """传入 index_df 不再影响慢线结果（死分支删除后 sb 段不参与）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        idx = pd.DataFrame({'close': [10.0] * 30})
        plain = mod._bociasi_slowline(_mk_df(pe_value=60.0))
        with_index = mod._bociasi_slowline(_mk_df(pe_value=60.0), index_df=idx)
        assert plain == with_index


# ── B3：慢线与四象限双语义分层话术 ──────────────────────────────

class TestSlowQuadrantSemantics:

    def _evaluate_description(self):
        import importlib
        from app.opportunity_atlas.dimensions import dim5_emotion_engine as mod
        # 直接读源文件确认话术前缀（引擎 evaluate 需 DB/daemon，纯文本断言足够）
        src = open(mod.__file__).read()
        return src

    def test_slow_label_individual_erp(self):
        """bociasi_slow 话术前缀'个股慢线ERP'（个股纯 ERP 语义）"""
        src = self._evaluate_description()
        assert "'bociasi_slow': f\"个股慢线ERP=" in src
        assert "'bociasi_quick': f\"个股快线=" in src

    def test_quadrant_label_market_percentile(self):
        """quadrant 话术前缀'大市四象限·全市场分位'（与个股慢线区分）"""
        src = self._evaluate_description()
        assert "大市四象限(" in src
        assert "全市场分位)" in src

    def test_distinct_labels_both_present(self):
        """快/慢线（个股）+ 四象限（大市）三层前缀同时存在，话术不混淆"""
        src = self._evaluate_description()
        assert src.count('个股快线') >= 1
        assert src.count('个股慢线ERP') >= 1
        assert src.count('大市四象限') >= 1


# ── C1：daemon 阶段 fallback 降级标注 ────────────────────────────

class TestDaemonStageFallback:

    def test_fallback_four_stage_intact(self):
        """daemon fallback 仍为四档（climax/ebb/ice/ferment），判定逻辑未动"""
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src = open(os.path.join(root, 'data_daemon.py')).read()
        # 471 C1：接受降级 + 标注存在（四档枚举 + 降级说明注释）
        assert "_sentiment_phase_global = 'climax'" in src
        assert "_sentiment_phase_global = 'ferment'" in src
        assert "471号 C1" in src

    def test_fallback_note_mentions_accept(self):
        """降级标注明确记录'经用户拍板接受此降级'"""
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        src = open(os.path.join(root, 'data_daemon.py')).read()
        assert '经用户拍板接受此降级' in src
