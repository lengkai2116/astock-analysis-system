#!/usr/bin/env python3
"""
312号方案批次1 模拟验证脚本（只读数据库，不修改任何生产代码）

目标：用真实数据模拟"8 维度加权共识"判定（312号 §三/§四，批次1 可得维度），
对比现状五源投票（washing 57.8%）的分布改善情况。

批次1 可模拟维度（7/8，控盘度批次3 跳过）：
  1 筹码形态（chip_concentration 近似）    权重 3.0
  2 资金流向（fund_flow + moneyflow 强度）  权重 3.0
  3 量价四阶段（daily 重算 + CONSOLIDATION 验证）权重 2.5
  4 ASR 筹码分布（chip 主峰占比近似）       权重 2.0
  5 趋势方向（三周期斜率）                 权重 1.5
  6 主力成本锚定 SSRP（chip 主峰价近似）    权重 2.5
  8 缠论买点（buy_sell_point 标签）         权重 2.0
修正维度（批次1）：资金性质（无龙虎榜数据则跳过）
环境加权：情绪 climax 买入证据×0.7、热点板块 washing×0.7（sector_heat 可用）

对比指标：修复后阶段分布 vs 现状（快照 main_force_phase）、conflict 占比、unknown 占比。
"""

import sqlite3
import statistics
from collections import Counter

DB = "data/duckdb/stock_cache.db"

# 维度权重（312号 §3.1）
W = {"chip": 3.0, "fund": 3.0, "stage": 2.5, "asr": 2.0, "trend": 1.5, "ssrp": 2.5, "chan": 2.0}

PHASES = ["building", "washing", "lifting", "distributing"]


def load():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    snap = [dict(r) for r in conn.execute(
        "SELECT ts_code, main_force_phase, fund_flow, chip_concentration, sentiment_phase, "
        "sector_heat, price_position, close "
        "FROM treemap_snapshot").fetchall()]
    snap_map = {s["ts_code"]: s for s in snap}

    # 缠论买点（最新）
    chan = {r["ts_code"]: r["tag_value"] for r in conn.execute(
        "SELECT ts_code, tag_value FROM opportunity_tags_cache "
        "WHERE tag_name='buy_sell_point' AND id IN "
        "(SELECT MAX(id) FROM opportunity_tags_cache WHERE tag_name='buy_sell_point' GROUP BY ts_code)"
    ).fetchall()}

    # 日线（最近 130 行）
    daily = conn.execute(
        "SELECT ts_code, close, high, low, vol FROM ("
        "  SELECT ts_code, close, high, low, vol, "
        "    ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn "
        "  FROM daily_cache) WHERE rn <= 130"
    ).fetchall()
    daily_map = {}
    for r in daily:
        daily_map.setdefault(r["ts_code"], []).append(
            (float(r["close"]), float(r["high"]), float(r["low"]), float(r["vol"]) or 0.0))

    # 资金流（最近 5 日）
    mf = conn.execute(
        "SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount FROM ("
        "  SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount, "
        "    ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn "
        "  FROM moneyflow_cache) WHERE rn <= 5"
    ).fetchall()
    mf_map = {}
    for r in mf:
        mf_map.setdefault(r["ts_code"], []).append(
            (float(r["net_lg_amount"] or 0), float(r["buy_lg_amount"] or 0), float(r["sell_lg_amount"] or 0)))

    # 筹码分布（每只最新一天，主峰 = chip_ratio 最大 price_bin）
    chip_rows = conn.execute(
        "SELECT c.ts_code, c.price_bin, c.chip_ratio FROM chip_distribution_cache c "
        "JOIN (SELECT ts_code, MAX(update_time) ut FROM chip_distribution_cache GROUP BY ts_code) m "
        "ON c.ts_code=m.ts_code AND c.update_time=m.ut"
    ).fetchall()
    chip_map = {}
    for r in chip_rows:
        chip_map.setdefault(r["ts_code"], []).append((float(r["price_bin"]), float(r["chip_ratio"])))

    conn.close()
    return snap, snap_map, chan, daily_map, mf_map, chip_map


# ── 各维度阶段向量 ──────────────────────────────
def v_chip(s):
    """筹码形态：chip_concentration 近似（生产用 TradingPhaseDetector 评分）"""
    c = s.get("chip_concentration")
    if c == "concentrating":
        return {"building": 0.6, "washing": 0.2}
    if c == "dispersing":
        return {"distributing": 0.5, "washing": 0.2}
    if c == "stable":
        return {"washing": 0.2}   # 弱信号
    return {}


def v_fund(s, mf_map):
    """资金流向：方向 + 连续强度"""
    d = s.get("fund_flow")
    mf = mf_map.get(s["ts_code"], [])
    strength = 0.0
    if mf:
        net5 = sum(r[0] for r in mf)
        tot5 = sum(r[1] + r[2] for r in mf)
        if tot5 > 0:
            strength = min(1.0, abs(net5) / tot5)
    if d == "5d_inflow":
        return {"lifting": 0.3 + 0.5 * strength, "building": 0.2} if strength else {"lifting": 0.3}
    if d == "5d_outflow":
        return {"distributing": 0.3 + 0.5 * strength}
    return {}   # mixed/none 不投（312：资金 mixed 不再投 washing）


def v_stage(rows):
    """量价四阶段：MA60 方向 + HH/HL 简化 + CONSOLIDATION 证据验证"""
    if len(rows) < 60:
        return {}, False
    closes = [r[0] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[1] for r in rows]
    vols = [r[3] for r in rows]
    ma60 = statistics.mean(closes[:60]) if len(closes) >= 60 else statistics.mean(closes)
    ma60_prev = statistics.mean(closes[5:65]) if len(closes) >= 65 else ma60
    ma60_dir = "up" if ma60 > ma60_prev * 1.005 else ("down" if ma60 < ma60_prev * 0.995 else "flat")
    # HH/HL 简化：近 20 日高点/低点 vs 前 20 日
    h1, h2 = max(highs[40:60]), max(highs[20:40])
    l1, l2 = min(lows[40:60]), min(lows[20:40])
    hh_hl = (h2 > h1 and l2 > l1) or (h2 < h1 and l2 < l1)
    pos60 = (closes[0] - min(lows[:60])) / (max(highs[:60]) - min(lows[:60]) + 1e-9)
    # CONSOLIDATION 证据验证：振幅<15% 且 量能萎缩
    amp20 = (max(highs[:20]) - min(lows[:20])) / closes[0]
    vol_shrink = sum(vols[:5]) < sum(vols[5:10]) if sum(vols[5:10]) > 0 else False

    if ma60_dir == "up" and hh_hl:
        if pos60 > 0.75 and closes[0] >= max(highs[20:40]):
            return {"distributing": 0.6, "lifting": 0.3}, True   # 放量顶
        return {"lifting": 0.7, "building": 0.2}, True
    if ma60_dir == "down" and hh_hl:
        if pos60 < 0.25 and not (closes[0] <= min(lows[20:40])):
            return {"building": 0.6, "washing": 0.3}, True       # 底部
        return {"washing": 0.4}, True                             # 下跌中继（不再判 building）
    if ma60_dir == "flat":
        if amp20 < 0.15 and vol_shrink:                            # 有证据的横盘 → washing
            return {"washing": 0.5, "building": 0.3}, True
        return {}, False                                          # 无证据 → 全0（去兜底）
    return {}, False


def v_asr(chip_rows, s):
    """ASR 近似：主峰筹码占比 + 价格位置（生产用 ASR 原值）"""
    if not chip_rows:
        return {}
    peak_ratio = max(r[1] for r in chip_rows)
    peak_price = max(chip_rows, key=lambda r: r[1])[0]
    price = s.get("close") or 0
    if price <= 0:
        return {}
    rel = price / peak_price if peak_price > 0 else 1.0
    if peak_ratio > 0.9 and rel < 0.95:
        return {"lifting": 0.5}
    if peak_ratio < 0.15 and abs(rel - 1.0) < 0.10:
        return {"building": 0.6}
    if peak_ratio < 0.15 and rel > 1.2:
        return {"lifting": 0.5}
    if peak_ratio > 0.3 and rel > 1.05:
        return {"distributing": 0.5}
    return {}   # 去 else→washing 兜底


def v_trend(rows):
    """趋势方向：三周期斜率"""
    if len(rows) < 20:
        return {}
    closes = [r[0] for r in rows]
    def slope(k):
        if len(closes) < k + 1 or closes[k] == 0:
            return 0.0
        return closes[0] / closes[k] - 1
    s5, s20, s60 = slope(5), slope(20), slope(60) if len(closes) >= 60 else slope(20)
    up = sum(1 for x in (s5, s20, s60) if x > 0.01)
    down = sum(1 for x in (s5, s20, s60) if x < -0.01)
    strength = min(1.0, abs(s5) * 15)
    if up >= 2:
        return {"lifting": 0.3 + 0.4 * strength}
    if down >= 2:
        return {"distributing": 0.3 + 0.4 * strength}
    return {}


def v_ssrp(chip_rows, s):
    """主力成本锚定：价格 vs 筹码主峰价（SSRP 近似）"""
    if not chip_rows:
        return {}
    peak_price = max(chip_rows, key=lambda r: r[1])[0]
    price = s.get("close") or 0
    if price <= 0 or peak_price <= 0:
        return {}
    rel = price / peak_price
    dev = abs(rel - 1.0)
    if rel < 0.95:
        return {"building": 0.5 + 0.3 * min(1.0, dev * 2)}   # 成本下方，安全边际
    if abs(rel - 1.0) < 0.10:
        return {"washing": 0.4, "building": 0.2}              # 回踩成本区
    if rel > 1.2:
        return {"lifting": 0.5 + 0.2 * min(1.0, dev)}         # 浮盈
    return {}


def v_chan(bsp):
    """缠论买点"""
    if bsp in ("first_buy", "first_buy_p", "second_buy", "third_buy", "third_buy_a", "third_buy_b"):
        return {"building": 0.5, "lifting": 0.2}
    if bsp in ("first_sell", "first_sell_p", "second_sell", "third_sell"):
        return {"distributing": 0.7}
    return {}


def score_v312(s, chan, daily_map, mf_map, chip_map):
    """312批次1 加权共识判定 → (phase, confidence, conflict, unknown_kind, active_dims)"""
    rows = daily_map.get(s["ts_code"], [])
    chip_rows = chip_map.get(s["ts_code"], [])
    insufficient = len(rows) < 60

    dims = {
        "chip": (v_chip(s), W["chip"]),
        "fund": (v_fund(s, mf_map), W["fund"]),
        "stage": (v_stage(rows)[0], W["stage"]),
        "asr": (v_asr(chip_rows, s), W["asr"]),
        "trend": (v_trend(rows), W["trend"]),
        "ssrp": (v_ssrp(chip_rows, s), W["ssrp"]),
        "chan": (v_chan(chan.get(s["ts_code"])), W["chan"]),
    }

    # 环境加权：情绪 climax → 买入类证据 ×0.7；热点板块 washing ×0.7
    sp = s.get("sentiment_phase")
    sh = s.get("sector_heat")
    env_buy = 0.7 if sp == "climax" else 1.0

    # 加权汇总
    total = {p: 0.0 for p in PHASES}
    w_sum = 0.0
    active = 0
    for name, (vec, w) in dims.items():
        if not vec:
            continue
        active += 1
        w_sum += w
        for p, v in vec.items():
            f = env_buy if p in ("building", "lifting") else 1.0
            if p == "washing" and sh in ("top_10", "top_20"):
                f *= 0.7
            total[p] += w * v * f
    if active == 0 or w_sum == 0:
        kind = "unknown_insufficient" if insufficient else "unknown_no_evidence"
        return "unknown", 0.0, False, kind, 0

    order = sorted(PHASES, key=lambda p: -total[p])
    top, second = order[0], order[1]
    t_sum = sum(total.values()) or 1.0
    confidence = total[top] / t_sum
    conflict = (total[top] - total[second]) / t_sum < 0.15
    if conflict:
        confidence *= 0.6
    return top, round(confidence, 3), conflict, "", active


def main():
    print("=" * 70)
    print("312号批次1 模拟验证（8维度加权共识，只读）")
    print("=" * 70)

    snap, _snap_map, chan, daily_map, mf_map, chip_map = load()
    print(f"股票数: {len(snap)} | 有K线: {len(daily_map)} | 有资金流: {len(mf_map)} | 有筹码分布: {len(chip_map)} | 有缠论: {len(chan)}")

    results = []
    for s in snap:
        phase, conf, conflict, unknown_kind, active = score_v312(s, chan, daily_map, mf_map, chip_map)
        results.append({"s": s, "phase": phase, "conf": conf, "conflict": conflict,
                        "unknown_kind": unknown_kind, "active": active})

    # ── 现状分布 vs 修复后分布 ──
    print("\n" + "─" * 70)
    print("阶段分布对比（现状五源投票 vs 312批次1 模拟）")
    cur = Counter(r["s"]["main_force_phase"] for r in results)
    new = Counter(r["phase"] for r in results)
    n = len(results)
    print(f"\n{'阶段':<14}{'现状':>10}{'修复后':>10}")
    for p in ["building", "washing", "lifting", "distributing", "unknown"]:
        c = cur.get(p, 0) / n * 100
        v = new.get(p, 0) / n * 100
        mark = " ← 改善" if (p == "washing" and v < c) else ""
        print(f"{p:<14}{c:>9.1f}%{v:>9.1f}%{mark}")

    # conflict / unknown 细分
    conflict_n = sum(1 for r in results if r["conflict"])
    unknown_ins = sum(1 for r in results if r["unknown_kind"] == "unknown_insufficient")
    unknown_noe = sum(1 for r in results if r["unknown_kind"] == "unknown_no_evidence")
    print(f"\nconflict 标记: {conflict_n} ({conflict_n / n * 100:.1f}%)")
    print(f"unknown 细分: 数据不足 {unknown_ins} ({unknown_ins / n * 100:.1f}%) | 无证据 {unknown_noe} ({unknown_noe / n * 100:.1f}%)")

    # 置信度分布（连续化验证）
    confs = [r["conf"] for r in results if r["conf"] > 0]
    print(f"\n置信度（非 unknown）: 均值 {statistics.mean(confs):.3f} | 唯一值 {len(set(confs))} 个（现状仅 5 档）")
    print(f"  置信度分布: 0.8-1.0: {sum(1 for c in confs if c >= 0.8)} | 0.6-0.8: {sum(1 for c in confs if 0.6 <= c < 0.8)} | "
          f"0.4-0.6: {sum(1 for c in confs if 0.4 <= c < 0.6)} | 0-0.4: {sum(1 for c in confs if c < 0.4)}")

    # 维度参与度
    actives = Counter(r["active"] for r in results)
    print(f"\n维度参与数分布: {dict(sorted(actives.items()))}（0=无证据→unknown）")

    # 样本抽查
    print("\n" + "─" * 70)
    print("修复后判定为 unknown 的样本（验证不是兜底）")
    unk = [r for r in results if r["phase"] == "unknown"][:5]
    for r in unk:
        print(f"  {r['s']['ts_code']}: {r['unknown_kind']}（原判定={r['s']['main_force_phase']}）")

    print("\n验证完成。")


if __name__ == "__main__":
    main()
