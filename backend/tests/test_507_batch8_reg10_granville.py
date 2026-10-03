"""507号批次8（登记-10）：dim3 _classify_granville breakdown 分支重排验证

方案档：`002-方案存档/507-SIG板块OCR核查与处置.md` §4.3 登记-10。

原 breakdown（5日跌<-4% + 放量 + 跌破MA20）位于 selling_pressure（<-2% + 放量）之后，
条件为其子集被先吞、恒不可达。重排后（更严条件优先）：
  - 深跌破位股 → breakdown（「放量破均线」），audit「量价八准则」负面判定不变（两标签同列表）
  - 一般放量下跌（-2~-4%）→ selling_pressure（保留）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from app.opportunity_atlas.dimensions.dim3_vp_engine import _classify_granville  # noqa: E402


def _mk_df(closes, vols):
    return pd.DataFrame({'close': [float(c) for c in closes],
                         'volume': [float(v) for v in vols]})


def test_reg10_breakdown_reachable_deep_break():
    """深跌破位（5日跌<-4% + 放量 + 破 MA20）→ breakdown（原恒被 selling_pressure 吞）"""
    # 前 25 行缓跌 10→9.5，后 5 行急跌 9.5→7.5（5日区间 -21%）
    closes = [10.0 - i * 0.02 for i in range(25)] + [9.5, 9.0, 8.5, 8.0, 7.5]
    # 前 10 行量 1000，中 15 行 1500，后 5 行 2000（vr≈23% > 10；近3日未连续 1.5×）
    vols = [1000] * 10 + [1500] * 15 + [2000] * 5
    r = _classify_granville(_mk_df(closes, vols), 1.0, {})
    assert r['rule'] == 'breakdown', f'深跌破位应判 breakdown: {r}'
    assert r['name'] == '放量破均线'


def test_reg10_selling_pressure_kept_medium_drop():
    """一般放量下跌（-2~-4% 区间）→ selling_pressure（原语义保留）"""
    # 前 25 行缓跌 10→9.33，后 5 行 9.33→9.0（5日区间 -3.5%）
    closes = [10.0 - i * 0.028 for i in range(25)] + [9.3, 9.25, 9.2, 9.15, 9.0]
    vols = [1000] * 10 + [1500] * 15 + [2000] * 5
    r = _classify_granville(_mk_df(closes, vols), 1.0, {})
    assert r['rule'] == 'selling_pressure', f'中幅放量下跌应判 selling_pressure: {r}'
    assert r['name'] == '放量下跌'


def test_reg10_negative_audit_list_still_contains_both():
    """audit「量价八准则」负面列表仍含两标签（判定等价，重排不改判定）"""
    import inspect
    from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine

    src = inspect.getsource(Dim3VPEngine.evaluate)
    assert "'selling_pressure', 'breakdown'" in src, '负面列表应仍含两标签'
    assert "'heavy_pressure', 'weakening'" in src
