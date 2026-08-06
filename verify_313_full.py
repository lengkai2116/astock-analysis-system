#!/usr/bin/env python3
"""313号 全量重算验证（只写 opportunity_tags_cache 的 signal_strength/potential_breakdown）

对全市场 5578 只重新计算机会潜力强度（0-100，313号 §四），写回标签表。
验证：全量真实分布 + 潜力×时机交叉。快照重建由日终 daemon 执行（会读取新 signal_strength）。
"""

import os
import sys
import json
import statistics
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.data import DataManager
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.opportunity_atlas.potential_engine import PotentialEngine, compute_fund_strength

BATCH = 200


def main():
    ecm = EnhancedCacheManager()
    dm = DataManager()
    eng = PotentialEngine()
    eng.build_percentile_tables(ecm)
    print("截面基准构建完成")

    snap = ecm._query_df("SELECT ts_code, valuation_deviation, fina_health, sector_heat, "
                         "trend_alignment, sentiment_phase, fund_flow FROM treemap_snapshot")
    codes = snap["ts_code"].tolist()
    print(f"全市场股票数: {len(codes)}")
    # catalyst_event 从 tags 补（快照无此列；取最新）
    ce = ecm._query_df("SELECT ts_code, tag_value FROM opportunity_tags_cache WHERE tag_name='catalyst_event' AND id IN "
                       "(SELECT MAX(id) FROM opportunity_tags_cache WHERE tag_name='catalyst_event' GROUP BY ts_code)")
    ce_map = dict(zip(ce["ts_code"], ce["tag_value"]))
    snap_map = {r["ts_code"]: r for _, r in snap.iterrows()}

    scores = []
    n_ok = n_err = 0
    for i, code in enumerate(codes):
        try:
            # 标签以快照为准（sentiment_phase 快照为权威，tags 被全局情绪覆盖为 climax 不可用）
            s = snap_map.get(code, {})
            tags = {
                "valuation_deviation": s.get("valuation_deviation"),
                "fina_health": s.get("fina_health"),
                "sector_heat": s.get("sector_heat"),
                "trend_alignment": s.get("trend_alignment"),
                "sentiment_phase": s.get("sentiment_phase"),
                "fund_flow": s.get("fund_flow"),
                "catalyst_event": ce_map.get(code),
            }
            # 真实 ROE
            roe = 0
            try:
                rr = ecm._query_df("SELECT roe FROM fina_indicator_cache WHERE ts_code=? "
                                   "ORDER BY end_date DESC LIMIT 1", [code])
                if not rr.empty and rr["roe"].iloc[0] is not None:
                    roe = float(rr["roe"].iloc[0])
            except Exception:
                pass
            tags["roe"] = roe
            mf = compute_fund_strength(ecm, code)
            pot = eng.compute_potential(tags, mf)
            # 写回 signal_strength（0-100） + potential_breakdown
            ecm.write_tags(code, {
                "signal_strength": pot["signal_strength"],
                "potential_breakdown": pot["potential_breakdown"],
            })
            scores.append(pot["signal_strength"])
            n_ok += 1
        except Exception as e:
            n_err += 1
            if n_err <= 3:
                print(f"  异常 {code}: {e}")
        if (i + 1) % BATCH == 0:
            ecm.conn.commit()
            print(f"  进度 {i+1}/{len(codes)}（OK {n_ok} / 异常 {n_err}）")

    ecm.conn.commit()
    m = len(scores)
    print(f"\n完成: OK {n_ok} / 异常 {n_err}")
    print(f"全量潜力分布（样本 {m}）:")
    print(f"  均值 {statistics.mean(scores):.1f} | 中位 {statistics.median(scores):.1f} | 唯一值 {len(set(scores))}")
    for lo, hi in [(90, 101), (80, 90), (60, 80), (40, 60), (20, 40), (0, 20)]:
        k = sum(1 for s in scores if lo <= s < hi)
        print(f"  {lo:3d}-{hi:3d}: {k} ({k/m*100:.1f}%)")
    print("\n目标(313 §九): 高分80+ 5-10% | 中分40-60 40-60% | 低分<40 30-40%")


if __name__ == "__main__":
    main()
