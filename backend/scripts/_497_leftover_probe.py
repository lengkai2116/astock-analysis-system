"""497遗留登记 处置验证探针（只读/内存）"""
import os, sys, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

print("=== 登记-4: composite 基准源切 pre_feat（live）===")
from app.data import DataManager
from app.opportunity_atlas.valuation_estimator import ValuationEngine
ecm = DataManager().cache
ve = ValuationEngine()
pre = ve._composite_items_from_pre_feat(ecm)
leg = ve._composite_items_from_legacy(ecm)
print(f"  pre_feat 源条目 = {len(pre)}（期望 ~5500 只，live）")
print(f"  legacy 源条目 = {len(leg)}（陈旧兜底）")
ve.build_composite_percentile(ecm)
print(f"  _comp_percentile 构建 = {'OK' if ve._comp_percentile is not None else 'None'}")
# 对照两源 composite 分布（pre_feat 应更新）
if pre:
    import statistics as st
    print(f"  pre_feat composite: n={len(pre)} 均值={st.mean([v for _,v in pre]):.4f}")

print()
print("=== created_at DEFAULT（#DEFAULT 已加）===")
src = inspect.getsource(__import__('data_daemon')._build_status_snapshot)
print("  CREATE 含 created_at DEFAULT:", "created_at TEXT DEFAULT (datetime('now', 'localtime'))" in src)

print()
print("=== 登记-6 注释更正 ===")
from app.opportunity_atlas import cross_validate
cvsrc = inspect.getsource(cross_validate)
print("  '否决' 注释已更新为实际可达:", "该映射实际可达" in cvsrc)
from app.opportunity_atlas import factor_arbiter
fa = inspect.getsource(factor_arbiter.arbitrate)
print("  reliability 注释已更正（非'预留未使用'）:", "仅并入 state_evidence" in fa)

print()
print("ALL_CHECKS_DONE")
