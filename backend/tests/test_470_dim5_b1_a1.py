"""470号：dim5 情绪引擎残留核查处置（B1+A1）单元测试

覆盖：
- B1：dim5 内嵌慢线 `_bociasi_slowline` 国债利率默认取全系统统一
      `CN_10Y_BOND_YIELD_PCT`（env 可配，1.7），不再硬编码 2.85。
      （447 只改四象限侧，漏改 dim5 输出侧——同"ERP"两套国债利率）
- A1：framework `BociasiQuickLine` / `BociasiSlowLine` 双类死代码已清理，
      dim5 用内嵌 `_bociasi_quickline` / `_bociasi_slowline`。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import pandas as pd


# ── B1：慢线国债利率统一 CN_10Y_BOND_YIELD_PCT ───────────────────

class TestSlowLineBondYield:

    def _mk_df(self, pe_value=30.0, ndays=60):
        """构造 ≥60 行 daily_basic 视图（含 pe_ttm，末值可控），满足 len<60 门槛"""
        return pd.DataFrame({'pe_ttm': [pe_value] * ndays})

    def test_default_equals_system_constant(self):
        """默认 bond_yield 与 CN_10Y_BOND_YIELD_PCT 一致（修复前恒 2.85）"""
        import importlib
        from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        df = self._mk_df()
        default_res = mod._bociasi_slowline(df)
        explicit_res = mod._bociasi_slowline(df, bond_yield=float(CN_10Y_BOND_YIELD_PCT))
        assert default_res == explicit_res
        # 慢线 details.erp 按统一利率计算：1/30*100 − 1.7 = 1.6333
        assert default_res['details']['erp'] is not None

    def test_no_longer_hardcodes_285_fallback(self):
        """以可区分两种利率的 pe（3.33 裸利）——2.85 下判 BEARISH、1.7 下判 NEUTRAL，
        证明默认已不再退回 2.85 语义"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        df = self._mk_df(pe_value=30.0)
        default_res = mod._bociasi_slowline(df)
        old_285 = mod._bociasi_slowline(df, bond_yield=2.85)
        # 1/30*100−1.7=1.633 → NEUTRAL；−2.85=0.483 → BEARISH（旧语义）
        assert default_res['signal'] != old_285['signal']
        assert default_res['signal'] == 'NEUTRAL'
        assert old_285['signal'] == 'BEARISH'

    def test_evaluate_does_not_pass_explicit_yield(self):
        """dim5.evaluate 调用 `_bociasi_slowline(df_basic)` 不传 bond_yield，
        确保生产路径走统一常量（而非残留显式 2.85）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        src = open(mod.__file__).read()
        # 显式传 2.85 的调用点应不存在
        assert 'bond_yield=2.85' not in src
        assert '_bociasi_slowline' in src


# ── A1：framework Bociasi 双类死代码清理 ─────────────────────────

class TestFrameworkDeadCodeRemoved:

    def test_framework_modules_deleted(self):
        """framework bociasi_quickline / bociasi_slowline 两个死代码文件已删除"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ('app/engine/framework/bociasi_quickline.py',
                    'app/engine/framework/bociasi_slowline.py'):
            assert not os.path.exists(os.path.join(root, rel)), \
                f'{rel} 应为已删除的死代码，不应存在'

    def test_no_class_residue_in_framework(self):
        """framework 包内不得再有 BociasiQuickLine / BociasiSlowLine 类（无 import 残留）"""
        import glob, os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        framework_dir = os.path.join(root, 'app', 'engine', 'framework')
        for f in glob.glob(os.path.join(framework_dir, '*.py')):
            with open(f) as fh:
                content = fh.read()
            assert 'class BociasiQuickLine' not in content
            assert 'class BociasiSlowLine' not in content
            assert 'BociasiQuickLine.evaluate' not in content
            assert 'BociasiSlowLine.evaluate' not in content

    def test_dim5_still_embeds_quick_slowline(self):
        """删除 framework 双类后，dim5 内嵌快慢线仍可用（生产不依赖被删文件）"""
        import importlib
        mod = importlib.import_module('app.opportunity_atlas.dimensions.dim5_emotion_engine')
        assert callable(mod._bociasi_quickline)
        assert callable(mod._bociasi_slowline)
