#!/usr/bin/env python3
"""312号批次1 生产代码抽样验证（只读）— 轻量版，不启动 APScheduler"""

import os
import sys
import json
import random
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.data import DataManager
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.opportunity_atlas.phase_detector import PhaseDetectionEngine

SAMPLE_N = 60
random.seed(42)


def main():
    # 不调用 create_app()（会启动 APScheduler/采集线程），直接注入 DataManager
    ecm = EnhancedCacheManager()
    dm = DataManager()
    pd_engine = PhaseDetectionEngine(data_manager=dm)

    snap = ecm._query_df(
        "SELECT ts_code, main_force_phase, sentiment_phase, sector_heat "
        "FROM treemap_snapshot")
    codes = snap["ts_code"].tolist()
    sample = random.sample(codes, min(SAMPLE_N, len(codes)))
    snap_map = {r["ts_code"]: r for _, r in snap.iterrows()}

    chan = ecm._query_df(
        "SELECT ts_code, tag_value FROM opportunity_tags_cache "
        "WHERE tag_name='buy_sell_point' AND id IN "
        "(SELECT MAX(id) FROM opportunity_tags_cache WHERE tag_name='buy_sell_point' GROUP BY ts_code)")
    chan_map = dict(zip(chan["ts_code"], chan["tag_value"]))

    new_phase, old_phase, confs, conflicts, unknowns, errs, vote_samples = [], [], [], 0, [], 0, []
    dim_top = Counter()

    for i, code in enumerate(sample):
        s = snap_map.get(code, {})
        df = ecm.get_cached_daily(code)
        if df is None or df.empty:
            continue
        old_phase.append(s.get("main_force_phase") or "unknown")
        try:
            res = pd_engine.compute_tags(code, df, extra_tags={
                "buy_sell_point": chan_map.get(code),
                "sentiment_phase": s.get("sentiment_phase"),
                "sector_heat": s.get("sector_heat"),
                "capital_nature": None,
            })
        except Exception as e:
            errs += 1
            print(f"  异常 {code}: {e}")
            continue
        new_phase.append(res["main_force_phase"])
        if res["main_force_phase"] != "unknown":
            confs.append(res["phase_confidence"])
        if res["phase_conflict"]:
            conflicts += 1
        if res["main_force_phase"] == "unknown":
            unknowns.append(code)
        try:
            d = json.loads(res["phase_vote_ratio"]) if isinstance(res["phase_vote_ratio"], str) else res["phase_vote_ratio"]
            for k, v in d.items():
                if k.startswith("_") or not isinstance(v, dict) or not v:
                    continue
                dim_top[(k, max(v, key=v.get))] += 1
        except Exception:
            pass
        if i < 3:
            vote_samples.append((code, res["phase_vote_ratio"]))
        if (i + 1) % 10 == 0:
            print(f"  进度 {i+1}/{len(sample)}")

    n = len(new_phase)
    print(f"\n样本数: {n} | 异常: {errs}")
    print("\n阶段分布对比（现状快照 → 312批次1 新逻辑）:")
    cur, new = Counter(old_phase), Counter(new_phase)
    for p in ["building", "washing", "lifting", "distributing", "unknown"]:
        print(f"  {p:<14}{cur.get(p,0)/n*100:>8.1f}%  →  {new.get(p,0)/n*100:>8.1f}%")

    print(f"\nconflict: {conflicts}/{n} | unknown: {len(unknowns)} {unknowns[:5]}")
    print(f"置信度唯一值: {len(set(confs))} 个 | 均值 {sum(confs)/max(len(confs),1):.3f}")
    print(f"置信度分布: 0.8+: {sum(1 for c in confs if c>=0.8)} | 0.6-0.8: {sum(1 for c in confs if 0.6<=c<0.8)} | "
          f"0.4-0.6: {sum(1 for c in confs if 0.4<=c<0.6)} | <0.4: {sum(1 for c in confs if c<0.4)}")
    print("\n各维度投票方向统计（维度 → 主要阶段）:")
    for (k, p), cnt in dim_top.most_common(20):
        print(f"  {k:<8} → {p:<12} {cnt}")
    print("\nphase_vote_ratio 样例:")
    for code, vr in vote_samples:
        d = json.loads(vr) if isinstance(vr, str) else vr
        print(f"  {code}: {json.dumps(d, ensure_ascii=False)[:150]}")


if __name__ == "__main__":
    main()
