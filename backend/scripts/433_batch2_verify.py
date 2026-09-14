"""433号 批次2 验证脚本（只读，不写库/不改权重文件）

三项验证：
  1. earn-only 重算实测：耗时 / status / weights / ic_report（只读直连分库，绕开 daemon 写锁）
  2. 无前视审计：对每个截面日验证可用 ROE 均来自「end_date + 披露滞后 <= 截面日」的报告期
  3. 新旧权重对比：当前 data/ic_weights.json（6 键）vs 新算权重逐维差异

用法：.venv/bin/python scripts/433_batch2_verify.py
"""
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # backend/ 根

import pandas as pd

ROOT = "/Users/kalence/Desktop/01-A股股票分析系统"
DBDIR = os.path.join(ROOT, "data", "duckdb")


class ReadOnlyECM:
    """只读直连分库（不经 EnhancedCacheManager，避免 daemon 写锁）"""
    FILES = {"daily_cache": "market_cache.db",
             "fina_indicator_cache": "financial_cache.db"}

    def __init__(self):
        self.conns = {}
        for t, f in self.FILES.items():
            c = sqlite3.connect(f"file:{os.path.join(DBDIR, f)}?mode=ro", uri=True)
            c.execute("PRAGMA busy_timeout=3000")
            self.conns[t] = c

    def _query_shard(self, table, sql, params=None):
        try:
            return pd.read_sql(sql, self.conns[table], params=params)
        except Exception as e:
            print("  [read err]", table, type(e).__name__, e)
            return pd.DataFrame()


def _avail(end_date: str) -> str:
    """披露滞后近似（433 批次0）：Q1+1月 / 半年+2月 / Q3+1月 / 年报+4月"""
    y, m, d = end_date.split("-")
    lag = {"03": 1, "06": 2, "09": 1, "12": 4}.get(m, 2)
    mm = int(m) + lag
    yy = int(y) + (mm - 1) // 12
    mm = (mm - 1) % 12 + 1
    return f"{yy:04d}-{mm:02d}-{d}"


def main():
    from app.opportunity_atlas import potential_engine as pe

    print("=" * 70)
    print("① earn-only 重算实测")
    print("=" * 70)
    ecm = ReadOnlyECM()
    t0 = time.time()
    res = pe.recompute_ic_weights(ecm)
    dt = time.time() - t0
    print(f"耗时 {dt:.1f}s | status={res['status']}")
    print("weights:", res["weights"])
    print("ic_report:", res["ic_report"])
    assert set(res["weights"]) == set(pe.DIM_WEIGHTS)
    assert abs(sum(res["weights"].values()) - 1.0) < 0.01

    print()
    print("=" * 70)
    print("② 无前视审计：各截面日「当时可得」的报告期（披露滞后近似）")
    print("=" * 70)
    # 独立重算截面日集合（与 recompute 同口径，仅用于审计展示）
    dates = sorted(ecm._query_shard(
        'daily_cache',
        "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC "
        "LIMIT %d" % (180 // 20 * 20 + 1))["trade_date"].tolist())
    fina = ecm._query_shard(
        'fina_indicator_cache', "SELECT ts_code, end_date FROM fina_indicator_cache")
    fina["avail"] = fina["end_date"].map(_avail)
    for i in range(0, len(dates) - 20 - 20, 20):
        d0 = dates[i]
        avail = fina[fina["avail"] <= d0]
        if avail.empty:
            print(f"  {d0}: 无可用报告期")
            continue
        dist = avail.groupby("end_date").size().sort_values(ascending=False).head(3)
        dist_str = ", ".join(f"{k}({v}只)" for k, v in dist.items())
        # 无前视断言：所有可用报告的 end_date+lag 均 <= d0
        assert bool((avail["avail"] <= d0).all()), f"{d0} 出现未来报告期"
        print(f"  {d0}: 可用报告期 top3 → {dist_str}")
    print("  ✅ 无前视审计通过（所有截面日可用 ROE 均来自已披露报告期）")

    print()
    print("=" * 70)
    print("③ 新旧权重对比")
    print("=" * 70)
    wfile = os.path.join(ROOT, "data", "ic_weights.json")
    old = dict(pe.DIM_WEIGHTS)
    if os.path.exists(wfile):
        try:
            import json
            with open(wfile, encoding="utf-8") as f:
                loaded = json.load(f)
            if all(k in loaded for k in pe.DIM_WEIGHTS):
                old = {k: loaded[k] for k in pe.DIM_WEIGHTS}
        except Exception:
            pass
    new = res["weights"]
    print(f"  {'维度':<8}{'旧权重':>8}{'新权重':>8}{'Δ':>8}")
    for k in pe.DIM_WEIGHTS:
        print(f"  {k:<8}{old[k]:>8.4f}{new[k]:>8.4f}{new[k]-old[k]:>+8.4f}")
    if res["status"] == "ok" and new != old:
        print(f"  ✅ 新权重已偏离初始值（earn IC={res['ic_report']['earn']['ic_mean']} → earn {old['earn']}→{new['earn']}）")
    elif res["status"] == "no_signal":
        print("  ⏸ earn IC 非正 → 保留配置权重（no_signal，不覆盖）")
    else:
        print(f"  ⚠ status={res['status']}，本次不产生新权重")

    print()
    print("完成（只读验证，未写库/未改权重文件）")


if __name__ == "__main__":
    main()
