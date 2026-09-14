#!/usr/bin/env python3
"""
311号方案 v2 可行性验证脚本（临时，只读数据库，不修改任何生产代码）

验证目标：
1. v2 评分流程（方向×强度 → 同族去相关 → 跨族加权共识 → 状态依赖权重 → 组合语义 → 风险层 → 百分制）
   能否在真实数据上跑通（无异常/NaN）
2. 百分制分布是否符合目标（90-100 ~8-12%、无同分扎堆）
3. 引擎对照：评分应与 phase_confidence 正相关、与 valuation_deviation 负相关
4. 典型样本：低价高置信建仓 vs 高价低置信建仓；危险组合/财务 fail 封顶
5. 与旧 signal_strength 对比：新分是否拉开差异（同分扎堆程度）

连续量来源说明（对应方案 §3.1.1 数据通道）：
- phase_confidence / valuation_deviation：快照表已落库（真实）
- pos_ratio / price_trend / vol_trend：从 daily_cache 重算（真实，方案要求引擎透出）
- fund_flow_strength：从 moneyflow_cache 重算（真实）
- asr / chanlun_confidence：未落库，用状态代理强度（方案要求引擎透出，本次验证标注"代理"）
"""

import sqlite3
import math
import statistics
from collections import Counter

DB = "data/duckdb/stock_cache.db"

# ──────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────
def load_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 1. 快照表（主数据源）
    snap = [dict(r) for r in conn.execute(
        "SELECT ts_code, signal_strength, valuation_level, valuation_deviation, "
        "main_force_phase, phase_confidence, sentiment_phase, fina_health, "
        "opportunity_type, trend_alignment, price_position, fund_flow, "
        "chip_concentration, volatility_level "
        "FROM treemap_snapshot").fetchall()]

    # 2. 补充标签（volume_price_fit / buy_sell_point，取每只最新一条）
    vpf = {r["ts_code"]: r["tag_value"] for r in conn.execute(
        "SELECT ts_code, tag_value FROM opportunity_tags_cache "
        "WHERE tag_name='volume_price_fit' AND id IN "
        "(SELECT MAX(id) FROM opportunity_tags_cache WHERE tag_name='volume_price_fit' GROUP BY ts_code)"
    ).fetchall()}
    bsp = {r["ts_code"]: r["tag_value"] for r in conn.execute(
        "SELECT ts_code, tag_value FROM opportunity_tags_cache "
        "WHERE tag_name='buy_sell_point' AND id IN "
        "(SELECT MAX(id) FROM opportunity_tags_cache WHERE tag_name='buy_sell_point' GROUP BY ts_code)"
    ).fetchall()}

    # 3. 日线（每只最近 130 行，用于重算 pos_ratio/price_trend/vol_trend）
    daily = conn.execute(
        "SELECT ts_code, close, high, low, vol FROM ("
        "  SELECT ts_code, close, high, low, vol, "
        "    ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn "
        "  FROM daily_cache) WHERE rn <= 130"
    ).fetchall()
    daily_map: dict[str, list] = {}
    for r in daily:
        daily_map.setdefault(r["ts_code"], []).append(
            (float(r["close"]), float(r["high"]), float(r["low"]), float(r["vol"]) or 0.0))

    # 4. 资金流（每只最近 5 日，重算净流入强度）
    mf = conn.execute(
        "SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount FROM ("
        "  SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount, "
        "    ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn "
        "  FROM moneyflow_cache) WHERE rn <= 5"
    ).fetchall()
    mf_map: dict[str, list] = {}
    for r in mf:
        mf_map.setdefault(r["ts_code"], []).append(
            (float(r["net_lg_amount"] or 0), float(r["buy_lg_amount"] or 0), float(r["sell_lg_amount"] or 0)))

    conn.close()
    return snap, vpf, bsp, daily_map, mf_map


# ──────────────────────────────────────────────
# 连续量重算（对应方案 §3.1.1 数据通道）
# ──────────────────────────────────────────────
def compute_continuum(s, daily_map, mf_map):
    """返回 {pos_ratio, price_trend, vol_trend, vp_strength, fund_strength}"""
    rows = daily_map.get(s["ts_code"], [])
    out = {"pos_ratio": 0.5, "price_trend": 0.0, "vol_trend": 0.0,
           "vp_strength": 0.0, "fund_strength": 0.0}

    if len(rows) >= 30:
        closes = [r[0] for r in rows]          # 已按日期倒序 → closes[0] 最新
        highs = [r[2] for r in rows]
        lows = [r[1] for r in rows]
        vols = [r[3] for r in rows]

        # pos_ratio：120 日价格分位（phase_detector 同口径）
        lb = min(120, len(closes))
        lo, hi = min(lows[:lb]), max(highs[:lb])
        if hi - lo > 1e-9:
            out["pos_ratio"] = (closes[0] - lo) / (hi - lo)

        # price_trend / vol_trend：10 日价格 / 5日量 vs 前5日量（_add_vp_simple_tags 同口径）
        if len(closes) >= 11:
            out["price_trend"] = closes[0] / closes[9] - 1
        if len(vols) >= 10 and sum(vols[5:10]) > 0:
            out["vol_trend"] = sum(vols[:5]) / sum(vols[5:10]) - 1

        # 量价强度：幅度越大强度越高（方案 §3.1.2 连续映射）
        out["vp_strength"] = min(1.0, abs(out["price_trend"]) * 12 + abs(out["vol_trend"]) * 1.2)

    # 资金强度：5 日主力净流入占 5 日主力成交额比例
    mf = mf_map.get(s["ts_code"], [])
    if mf:
        net5 = sum(r[0] for r in mf)
        tot5 = sum(r[1] + r[2] for r in mf)
        if tot5 > 0:
            out["fund_strength"] = min(1.0, abs(net5) / tot5)
    return out


# ──────────────────────────────────────────────
# v2 评分实现（方案 §3.1-§3.4）
# ──────────────────────────────────────────────
DIR_MAIN = {"lifting": 1, "building": 1, "washing": 0, "distributing": -1, "unknown": 0, None: 0}
DIR_TREND = {"up_aligned": 1, "down_aligned": -1, "mixed": 0, "no_trend": 0, None: 0}
DIR_VP = {"healthy": 1, "diverging": -1, "neutral": 0, None: 0}
DIR_POS = {"low_zone": 1, "high_zone": -1, "mid_zone": 0, None: 0}
DIR_VAL = {"extreme_low": 1, "low": 1, "fair": 0, "high": -1, "extreme_high": -1, None: 0}
DIR_FUND = {"5d_inflow": 1, "5d_outflow": -1, "mixed": 0, "none": 0, None: 0}
DIR_CHIP = {"concentrating": 1, "dispersing": -1, "stable": 0, None: 0}
DIR_CHAN = {"first_buy": 1, "third_buy": 1, "first_sell": -1, "second_sell": -1, None: 0}


def score_v2(s, c, vpf, bsp):
    """v2 评分：返回 (score_0_100, 诊断信息 dict)"""
    diag = {}

    # ── 基础层：方向 × 强度 ──
    pc = float(s["phase_confidence"] or 0)
    dev = float(s["valuation_deviation"] or 0)

    main = {"dir": DIR_MAIN.get(s["main_force_phase"], 0), "strength": pc}
    trend = {"dir": DIR_TREND.get(s["trend_alignment"], 0),
             "strength": min(1.0, abs(c["price_trend"]) * 30) if c["price_trend"] else 0.0}
    vp = {"dir": DIR_VP.get(vpf.get(s["ts_code"]), 0), "strength": c["vp_strength"]}
    pos = {"dir": DIR_POS.get(s["price_position"], 0), "strength": abs(c["pos_ratio"] - 0.5) * 2}
    val = {"dir": DIR_VAL.get(s["valuation_level"], 0), "strength": min(1.0, abs(dev) / 30)}
    fund = {"dir": DIR_FUND.get(s["fund_flow"], 0), "strength": c["fund_strength"]}
    chip = {"dir": DIR_CHIP.get(s["chip_concentration"], 0),
            "strength": 0.7 if s["chip_concentration"] in ("concentrating", "dispersing") else 0.3}  # 代理
    chan = {"dir": DIR_CHAN.get(bsp.get(s["ts_code"]), 0), "strength": 0.7}  # 代理

    # ── 协同层 Step1：同族去相关 ──
    main_dir = main["dir"]
    same = [x for x in (trend, fund, chip) if x["dir"] == main_dir and x["dir"] != 0]
    opp = [x for x in (trend, fund, chip) if x["dir"] == -main_dir and x["dir"] != 0]
    conflict = bool(opp and (not same or max(x["strength"] for x in opp) > max(x["strength"] for x in same)))
    if main_dir != 0:
        family_main = (main_dir, max([main["strength"]] + [x["strength"] for x in same]) if same else main["strength"], conflict)
    else:
        # 主信号无方向：族内其他源若有方向则跟随
        others = [x for x in (trend, fund, chip) if x["dir"] != 0]
        if others:
            d = max(others, key=lambda x: x["strength"])["dir"]
            family_main = (d, max(x["strength"] for x in others), False)
        else:
            family_main = (0, 0.0, False)

    pos_val_same = [x for x in (pos, val) if x["dir"] != 0]
    if pos_val_same:
        d = max(pos_val_same, key=lambda x: x["strength"])["dir"]
        family_val = (d, max(x["strength"] for x in pos_val_same if x["dir"] == d), False)
    else:
        family_val = (0, 0.0, False)

    # ── 协同层 Step3 先行：状态依赖权重（情绪动态权重矩阵，作用于族权重） ──
    sp = s["sentiment_phase"]
    # 方案 §3.2.3：情绪阶段改变不同族的权重（量价/缠论族在冰点/退潮降权或清零）
    if sp == "climax":
        state_f = {"主力族": 0.5, "价值族": 0.5, "量价族": 0.5, "缠论族": 0.5}
    elif sp == "ebb":
        state_f = {"主力族": 0.3, "价值族": 0.3, "量价族": 0.0, "缠论族": 0.0}
    elif sp == "ice":
        state_f = {"主力族": 1.0, "价值族": 1.0, "量价族": 0.7, "缠论族": 0.7}
    else:
        state_f = {"主力族": 1.0, "价值族": 1.0, "量价族": 1.0, "缠论族": 1.0}
    diag["state_w"] = state_f.get("主力族", 1.0)

    # ── 协同层 Step2：跨族加权共识（权重 = 族权重 × 状态依赖因子） ──
    families = [("主力族", family_main, 3.0), ("价值族", family_val, 2.0),
                ("量价族", (vp["dir"], vp["strength"], False), 1.5),
                ("缠论族", (chan["dir"], chan["strength"], False), 1.5)]
    w_sum = 0.0
    cons = 0.0
    active = 0
    for name, (d, st, _cf), w in families:
        w_eff = w * state_f.get(name, 1.0)
        if d != 0 and w_eff > 0:
            cons += w_eff * d * st
            w_sum += w_eff
            active += 1
    consensus = cons / w_sum if w_sum > 0 else 0.0
    diag["active_families"] = active

    # ── 协同层 Step4：组合语义识别 ──
    combo = 1.0
    diag["combo"] = "普通"
    if main_dir > 0 and sp == "climax" and c["pos_ratio"] > 0.7:
        combo = 0.6
        diag["combo"] = "追高警示"
    elif conflict:
        combo = 0.7
        diag["combo"] = "矛盾型"
    elif main_dir > 0 and sum(1 for x in (vp, chan) if x["dir"] == main_dir) >= 2:
        combo = 1.15
        diag["combo"] = "确认型"
    elif main_dir > 0:
        diag["combo"] = "初现型"

    # ── 风险层 ──
    neg_fams = sum(1 for _n, (d, _st, _c), _w in families if d < 0)
    neg_strengths = [st for _n, (d, st, _c), _w in families if d < 0]
    cap = 100
    diag["risk"] = "无"
    fina = s["fina_health"]
    if fina == "fail":
        cap = 30
        diag["risk"] = "财务fail封顶30"
    elif neg_fams >= 3 and neg_strengths and (sum(neg_strengths) / len(neg_strengths)) > 0.6:
        cap = 20
        diag["risk"] = "强负组合封顶20"
    elif sp == "ebb" and neg_fams >= 2:
        combo *= 0.7
        diag["risk"] = "退潮负叠加×0.7"
    elif neg_fams >= 2:
        # 负向共识放大 ×1.5（对负向 consensus 生效）
        consensus = consensus * 1.5 if consensus < 0 else consensus
        diag["risk"] = "负向叠加×1.5"

    # ── 映射（状态权重已并入族权重，此处仅组合语义 + 封顶） ──
    raw = 100 * consensus * combo
    score = max(0.0, min(100.0, raw))
    score = min(score, cap)
    diag["consensus"] = consensus
    return round(score), diag


# ──────────────────────────────────────────────
# 验证主流程
# ──────────────────────────────────────────────
def main():
    print("=" * 70)
    print("311号方案 v2 可行性验证（真实数据，只读）")
    print("=" * 70)

    snap, vpf, bsp, daily_map, mf_map = load_data()
    print(f"快照股票数: {len(snap)}")
    print(f"daily_cache 有K线: {len(daily_map)} 只 | moneyflow 有资金流: {len(mf_map)} 只")

    # 计算连续量 + 评分
    results = []
    skipped = 0
    for s in snap:
        c = compute_continuum(s, daily_map, mf_map)
        try:
            score, diag = score_v2(s, c, vpf, bsp)
            results.append({"s": s, "c": c, "score": score, "diag": diag})
        except Exception as e:  # noqa: BLE001
            skipped += 1
            if skipped <= 3:
                print(f"  异常 {s['ts_code']}: {e}")

    print(f"\n执行成功: {len(results)} / {len(snap)}（跳过 {skipped}）")

    scores = [r["score"] for r in results]
    print(f"NaN/异常分数: {sum(1 for x in scores if x != x)}")

    # ── 1. 百分制分布 ──
    print("\n" + "─" * 70)
    print("1. 百分制分布（新评分）")
    buckets = [(90, 100), (80, 90), (70, 80), (60, 70), (50, 60),
               (40, 50), (30, 40), (20, 30), (10, 20), (0, 10)]
    for lo, hi in buckets:
        n = sum(1 for x in scores if lo <= x < hi or (hi == 100 and x == 100))
        bar = "#" * int(n / len(scores) * 100)
        print(f"  {lo:3d}-{hi:3d}: {n:5d} ({n / len(scores) * 100:5.1f}%) {bar}")

    # 同分扎堆程度（核心验证：89 vs 81 是否有差别）
    cnt = Counter(scores)
    top_same = cnt.most_common(3)
    print(f"\n  同分扎堆 TOP3: {top_same}")
    print(f"  唯一分数个数: {len(cnt)} / {len(scores)} 只")
    print(f"  标准差: {statistics.pstdev(scores):.2f}（越大越分散）")

    # 与旧分对比
    old = [float(r["s"]["signal_strength"] or 0) for r in results]
    old_cnt = Counter(old)
    print(f"\n  旧分（0-10）唯一数值个数: {len(old_cnt)}（对比：新分 {len(cnt)} 个）")
    print(f"  旧分标准差: {statistics.pstdev(old):.2f}")

    # ── 2. 引擎对照验证 ──
    print("\n" + "─" * 70)
    print("2. 引擎对照（Spearman 相关，新分 vs 引擎连续量）")

    def spearman(a, b):
        ra = {v: i for i, v in enumerate(sorted(set(a)))}
        rb = {v: i for i, v in enumerate(sorted(set(b)))}
        n = len(a)
        ma, mb = sum(ra[x] for x in a) / n, sum(rb[x] for x in b) / n
        cov = sum((ra[x] - ma) * (rb[y] - mb) for x, y in zip(a, b))
        va = sum((ra[x] - ma) ** 2 for x in a) ** 0.5
        vb = sum((rb[y] - mb) ** 2 for y in b) ** 0.5
        return cov / (va * vb) if va and vb else 0

    pc_vals = [(r["score"], float(r["s"]["phase_confidence"] or 0)) for r in results]
    rho_pc = spearman([x[0] for x in pc_vals], [x[1] for x in pc_vals])
    print(f"  新分 vs phase_confidence: ρ = {rho_pc:+.3f}（期望正相关）")

    dev_vals = [(r["score"], float(r["s"]["valuation_deviation"] or 0)) for r in results
                if r["s"]["valuation_deviation"] is not None]
    rho_dev = spearman([x[0] for x in dev_vals], [x[1] for x in dev_vals])
    print(f"  新分 vs valuation_deviation: ρ = {rho_dev:+.3f}（期望负相关，低估高分）")

    # ── 3. 典型样本 ──
    print("\n" + "─" * 70)
    print("3. 典型样本对比")

    def avg_score(pred):
        sub = [r["score"] for r in results if pred(r)]
        return statistics.mean(sub) if sub else None, len(sub)

    def show(name, pred):
        m, n = avg_score(pred)
        print(f"  {name}: 平均分 = {m if m is not None else '—'}（n={n}）")

    show("低价高置信建仓 (building+pos_ratio<0.3+conf≥0.8)",
         lambda r: r["s"]["main_force_phase"] == "building" and r["c"]["pos_ratio"] < 0.3
         and float(r["s"]["phase_confidence"] or 0) >= 0.8)
    show("高价低置信建仓 (building+pos_ratio>0.7+conf<0.6)",
         lambda r: r["s"]["main_force_phase"] == "building" and r["c"]["pos_ratio"] > 0.7
         and float(r["s"]["phase_confidence"] or 0) < 0.6)
    show("危险区 (opportunity_type∈danger*)",
         lambda r: str(r["s"]["opportunity_type"] or "").startswith("danger"))
    show("财务 fail", lambda r: r["s"]["fina_health"] == "fail")
    show("确认型 (主力正向+量价/缠论同向≥2)", lambda r: r["diag"]["combo"] == "确认型")
    show("初现型 (仅主力族正向)", lambda r: r["diag"]["combo"] == "初现型")
    show("追高警示 (拉升+高潮+高位)", lambda r: r["diag"]["combo"] == "追高警示")
    show("无信号 (主力unknown+全部方向0)",
         lambda r: r["s"]["main_force_phase"] in (None, "", "unknown") and r["diag"]["active_families"] == 0)

    # ── 4. 方案目标对照 ──
    print("\n" + "─" * 70)
    print("4. 方案 §1.3 目标分布对照")
    p90 = sum(1 for x in scores if x >= 90) / len(scores) * 100
    p70 = sum(1 for x in scores if 70 <= x < 90) / len(scores) * 100
    p40 = sum(1 for x in scores if 40 <= x < 70) / len(scores) * 100
    p40l = sum(1 for x in scores if x < 40) / len(scores) * 100
    print(f"  90-100: {p90:.1f}%（目标 ~8-12%）")
    print(f"  70-90 : {p70:.1f}%（目标 ~30%）")
    print(f"  40-70 : {p40:.1f}%（目标 ~40%）")
    print(f"  <40   : {p40l:.1f}%（目标 ~15%）")

    # ── 5. 数据缺口（方案 §3.1.1 需要引擎透出的连续量） ──
    print("\n" + "─" * 70)
    print("5. 数据缺口确认（§3.1.1 引擎连续量透出必要性）")
    n_kline = sum(1 for r in results if r["c"]["price_trend"] != 0)
    n_mf = sum(1 for r in results if r["s"]["fund_flow"] in ("5d_inflow", "5d_outflow"))
    print(f"  有K线可重算连续量: {n_kline}/{len(results)}")
    print(f"  有资金流向标签: {n_mf}/{len(results)}（资金强度需 moneyflow 透出）")
    print("  代理强度使用: chip(asr未落库)、缠论(chanlun_confidence未落库) → 需引擎透出")

    print("\n验证完成。")


if __name__ == "__main__":
    main()
